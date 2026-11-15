"""Self-contained, versioned build snapshots; only verified Modrinth files are imported."""
import base64
import copy
import hashlib
import hmac
import json
import re
import shutil
import tempfile
import uuid
import zlib
from pathlib import Path
from urllib.parse import urlparse
import requests
import packs
import loaders
from instance_tools import Cancelled,write_json

FOLDERS={'mod':'mods','resourcepack':'resourcepacks','shader':'shaderpacks'}
MAX_JSON=4*1024*1024
MAX_CODE=2*1024*1024


def filename(value,kind=None):
    if not isinstance(value,str) or not 1<=len(value)<=200 or value in ('.','..') or any(c in value for c in '/\\:<>"|?*') or any(ord(c)<32 for c in value) or value.rstrip(' .')!=value:raise ValueError('Недопустимое имя файла: '+str(value)[:100])
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:raise ValueError('Зарезервированное имя файла')
    if kind=='mod' and not value.lower().endswith(('.jar','.jar.disabled')):raise ValueError('Мод должен быть JAR-файлом')
    if kind in ('resourcepack','shader') and not value.lower().endswith('.zip'):raise ValueError('Ресурс должен быть ZIP-файлом')
    return value


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9]{1,64}',value):raise ValueError('Недопустимый идентификатор Modrinth')
    return value


def validate(data):
    allowed={'schema','snapshot','name','minecraft','loader','components','resource_order','shader'}
    if not isinstance(data,dict) or set(data)!=allowed or type(data.get('schema')) is not int or data['schema']!=1:raise ValueError('Неподдерживаемая схема кода TUL4N')
    if not isinstance(data.get('snapshot'),str) or not re.fullmatch('[0-9a-f]{32}',data['snapshot']):raise ValueError('Неверный снимок сборки')
    name=data.get('name')
    if not isinstance(name,str) or not name.strip() or not 1<=len(name)<=64 or any(ord(c)<32 for c in name):raise ValueError('Неверное название сборки')
    if not isinstance(data.get('minecraft'),str) or not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._+-]{0,63}',data['minecraft']):raise ValueError('Неверная версия Minecraft')
    loader=data.get('loader')
    if not isinstance(loader,dict) or set(loader)!={'type','version'} or loader['type'] not in ('vanilla','fabric','forge','neoforge') or not isinstance(loader['version'],str) or not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._+-]{0,99}',loader['version']):raise ValueError('Неверный загрузчик или его версия')
    components=data.get('components')
    if not isinstance(components,list) or len(components)>3000:raise ValueError('Слишком много компонентов в коде')
    paths=set()
    fields={'kind','project','version','filename','source_filename','hashes','enabled','active','dependencies'}
    for component in components:
        if not isinstance(component,dict) or set(component)!=fields or component['kind'] not in FOLDERS:raise ValueError('Неверный компонент сборки')
        kind=component['kind'];identifier(component['project']);identifier(component['version']);filename(component['filename'],kind);filename(component['source_filename'],'mod' if kind=='mod' else kind)
        key=(kind,component['filename'].casefold())
        if key in paths:raise ValueError('Повторяется файл: '+component['filename'])
        paths.add(key)
        if not isinstance(component['enabled'],bool) or not isinstance(component['active'],bool):raise ValueError('Неверное состояние компонента')
        if kind=='mod' and component['enabled']==component['filename'].lower().endswith('.disabled'):raise ValueError('Расширение мода не соответствует его состоянию')
        hashes=component['hashes']
        if not isinstance(hashes,dict) or not hashes or set(hashes)-{'sha1','sha512'}:raise ValueError('Неверные контрольные суммы')
        for algorithm,value in hashes.items():
            if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{'+str(40 if algorithm=='sha1' else 128)+'}',value):raise ValueError('Неверная контрольная сумма файла')
        deps=component['dependencies']
        if not isinstance(deps,list) or len(deps)>128:raise ValueError('Слишком много зависимостей')
        for dep in deps:
            if not isinstance(dep,dict) or set(dep)!={'type','project','version','file'} or dep['type'] not in ('required','optional','incompatible','embedded'):raise ValueError('Неверная зависимость')
            if dep['project'] is not None:identifier(dep['project'])
            if dep['version'] is not None:identifier(dep['version'])
            if dep['file'] is not None:filename(dep['file'])
    order=data.get('resource_order',[])
    if not isinstance(order,list) or len(order)>3000 or any(not isinstance(n,str) for n in order):raise ValueError('Неверный порядок ресурспаков')
    available={c['filename'] for c in components if c['kind']=='resourcepack'}
    if len(set(order))!=len(order) or any(n not in available for n in order):raise ValueError('Порядок ссылается на отсутствующий ресурспак')
    if any(not c['active'] for c in components if c['kind']=='resourcepack' and c['filename'] in order):raise ValueError('Неверное состояние активного ресурспака')
    shader=data.get('shader')
    if shader is not None:
        if not isinstance(shader,dict) or set(shader)!={'filename','engine'} or shader['engine'] not in ('iris','oculus','optifine') or not any(c['kind']=='shader' and c['filename']==shader['filename'] and c['active'] for c in components):raise ValueError('Неверные настройки шейдера')
    return data


def encode(data):
    validate(data)
    raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>MAX_JSON:raise ValueError('Манифест слишком большой')
    payload=base64.urlsafe_b64encode(zlib.compress(raw,9)).decode().rstrip('=')
    return 'TUL4N-1-'+payload+'.'+hashlib.sha256(raw).hexdigest()


def decode(code):
    if not isinstance(code,str) or len(code)>MAX_CODE:raise ValueError('Код слишком большой')
    code=''.join(code.split())
    match=re.fullmatch(r'TUL4N-1-([A-Za-z0-9_-]+)\.([0-9a-f]{64})',code)
    if not match:raise ValueError('Неверный формат кода TUL4N или неподдерживаемая версия')
    try:
        payload=match[1];compressed=base64.b64decode(payload+'='*(-len(payload)%4),altchars=b'-_',validate=True)
        stream=zlib.decompressobj();raw=stream.decompress(compressed,MAX_JSON+1)
        if len(raw)>MAX_JSON or not stream.eof or stream.unused_data or stream.unconsumed_tail:raise ValueError('Слишком большой или повреждённый манифест')
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(),match[2]):raise ValueError('Контрольная сумма кода не совпала')
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('Повторяющееся поле JSON')
                result[key]=value
            return result
        data=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Неверное число JSON')))
        return validate(data)
    except (UnicodeError,zlib.error,RecursionError) as error:raise ValueError('Код TUL4N повреждён') from error


def properties(path):
    result={}
    if path.exists():
        for line in path.read_text('utf-8',errors='replace').splitlines():
            if '=' in line and not line.lstrip().startswith(('#','!')):
                key,value=line.split('=',1);result[key.strip()]=re.sub(r'\\u([0-9a-fA-F]{4})',lambda m:chr(int(m[1],16)),value.strip()).replace('\\ ',' ').replace('\\=', '=')
    return result


def scan(game):
    game=Path(game);resource_order=None;shader=None
    options=game/'options.txt'
    if options.exists():
        for line in options.read_text('utf-8',errors='replace').splitlines():
            if line.startswith('resourcePacks:'):
                try:resource_order=[n[5:] for n in json.loads(line.split(':',1)[1]) if isinstance(n,str) and n.startswith('file/')]
                except (ValueError,TypeError):pass
    for engine,relative in [('iris','config/iris.properties'),('oculus','config/oculus.properties'),('optifine','optionsshaders.txt')]:
        state=properties(game/relative);selected=state.get('shaderPack')
        if selected and selected not in ('OFF','(internal)') and state.get('enableShaders','true').lower()!='false':shader={'filename':selected,'engine':engine};break
    rows=[]
    for kind,directory in FOLDERS.items():
        folder=packs.safe_path(game,directory)
        for path in sorted(folder.glob('*')):
            if not path.is_file():continue
            try:filename(path.name,kind)
            except ValueError:continue
            if path.is_symlink():raise ValueError('Ссылка вместо файла: '+path.name)
            enabled=not path.name.endswith('.disabled')
            active=enabled if kind=='mod' else path.name in (resource_order or []) if kind=='resourcepack' else bool(shader and shader['filename']==path.name)
            rows.append({'kind':kind,'filename':path.name,'enabled':enabled,'active':active,'default':active or kind!='mod' and (resource_order is None if kind=='resourcepack' else shader is None)})
    return rows,resource_order,shader


def dependencies(release):
    return [{'type':d['dependency_type'],'project':d.get('project_id'),'version':d.get('version_id'),'file':d.get('file_name')} for d in release.get('dependencies',[])]


def check_dependencies(resolved,transfer):
    active={}
    for entry in resolved:
        c=entry['component']
        if c['kind']=='mod' and c['enabled']:
            if c['project'] in active:raise ValueError('Дублирующийся мод: '+c['filename'])
            active[c['project']]=entry
    for project,entry in active.items():
        for dep in entry['release'].get('dependencies',[]):
            transfer.check();kind=dep['dependency_type']
            if kind not in ('required','incompatible'):continue
            target=dep.get('project_id');version=dep.get('version_id')
            if not target and version:target=packs.api('version/'+version)['project_id']
            match=active.get(target)
            if not target and dep.get('file_name'):match=next((v for v in active.values() if v['component']['source_filename']==dep['file_name']),None)
            present=bool(match and (not version or match['release']['id']==version))
            if kind=='required' and not present:raise ValueError(entry['component']['filename']+': отсутствует выбранная обязательная зависимость '+str(target or dep.get('file_name') or version))
            if kind=='incompatible' and present:raise ValueError('Конфликт: '+entry['component']['filename']+' и '+match['component']['filename'])


def resolve(data,transfer):
    validate(data);resolved=[];projects={}
    for component in data['components']:
        transfer.check();name=component['filename'];transfer.notify('Проверяем точную версию: '+name,0)
        try:
            release=packs.api('version/'+component['version'])
            if release['project_id']!=component['project']:raise ValueError('идентификатор проекта не совпадает')
            if data['minecraft'] not in release.get('game_versions',[]):raise ValueError('несовместимая версия Minecraft')
            if component['kind']=='mod' and data['loader']['type'] not in release.get('loaders',[]):raise ValueError('несовместимый загрузчик')
            file=next((f for f in release['files'] if f['filename']==component['source_filename'] and all(f.get('hashes',{}).get(k)==v for k,v in component['hashes'].items())),None)
            if not file:raise ValueError('точный файл или его хеш отсутствует на Modrinth')
            if urlparse(file['url']).hostname!='cdn.modrinth.com' or not file['url'].startswith('https://'):raise ValueError('непроверенный источник скачивания')
            if component['project'] not in projects:projects[component['project']]=packs.api('project/'+component['project'])
            project=projects[component['project']]
            if project.get('project_type')!=component['kind']:raise ValueError('тип проекта не совпадает с типом файла')
            if component['kind']=='shader' and not set(release.get('loaders',[]))&{'iris','optifine'}:raise ValueError('не указан поддерживаемый движок шейдера')
            resolved.append({'component':component,'release':release,'file':file,'project':project})
        except (requests.RequestException,KeyError,ValueError) as error:raise ValueError(name+': '+str(error)) from error
    check_dependencies(resolved,transfer)
    shader=data.get('shader')
    if shader:
        engines={e['project'].get('slug') for e in resolved if e['component']['kind']=='mod' and e['component']['enabled']}
        if shader['engine'] not in engines:raise ValueError('Для активного шейдера необходимо включить в код поддерживаемый мод '+shader['engine']+'. Неизвестные локальные загрузчики не подменяются.')
        entry=next(e for e in resolved if e['component']['kind']=='shader' and e['component']['filename']==shader['filename'])
        compatible_engine='iris' if shader['engine'] in ('iris','oculus') else 'optifine'
        if compatible_engine not in entry['release']['loaders']:raise ValueError('Выбранный шейдер не поддерживает '+shader['engine'])
    return resolved


def export(game,item,selected,transfer):
    rows,order,shader=scan(game);wanted=set(selected);rows=[r for r in rows if (r['kind'],r['filename']) in wanted]
    if len(rows)!=len(wanted):raise ValueError('Состав сборки изменился. Откройте экспорт заново.')
    kind=item.get('loader_type','fabric');loader=item.get('loader')
    marker=Path(game)/'.chunk-loader-ready.json'
    if marker.exists():
        ready=json.loads(marker.read_text('utf-8'))
        if ready.get('kind')==kind and ready.get('minecraft',item['version'])==item['version']:loader=ready.get('loader')
    if kind=='vanilla':loader=item['version']
    if not loader:raise ValueError('Неизвестна точная версия загрузчика. Сначала выберите и установите её.')
    components=[]
    for i,row in enumerate(rows):
        transfer.check();path=packs.safe_path(Path(game)/FOLDERS[row['kind']],row['filename']);transfer.notify(f'Определяем файл {i+1}/{len(rows)}: '+path.name,i/max(1,len(rows)))
        with path.open('rb') as source:digest=hashlib.file_digest(source,'sha512').hexdigest()
        try:release=packs.api('version_file/'+digest,{'algorithm':'sha512'})
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code==404:raise ValueError(path.name+': точный файл не найден в поддерживаемом источнике Modrinth. Исключите его из экспорта.') from error
            raise ValueError(path.name+': ошибка Modrinth, повторите экспорт. '+str(error)) from error
        except requests.RequestException as error:raise ValueError(path.name+': Modrinth недоступен, повторите экспорт. '+str(error)) from error
        file=next((f for f in release['files'] if f.get('hashes',{}).get('sha512')==digest),None)
        if not file:raise ValueError('Не удалось подтвердить файл: '+path.name)
        components.append({'kind':row['kind'],'project':release['project_id'],'version':release['id'],'filename':path.name,'source_filename':file['filename'],
                           'hashes':{k:v for k,v in file['hashes'].items() if k in ('sha1','sha512')},'enabled':row['enabled'],'active':row['active'],'dependencies':dependencies(release)})
    selected_names={c['filename'] for c in components if c['kind']=='resourcepack'}
    selected_shader=shader if shader and any(c['kind']=='shader' and c['filename']==shader['filename'] for c in components) else None
    data={'schema':1,'snapshot':uuid.uuid4().hex,'name':item['name'],'minecraft':item['version'],'loader':{'type':kind,'version':loader},'components':components,
          'resource_order':[n for n in (order or []) if n in selected_names],'shader':selected_shader}
    resolve(data,transfer)
    for component in components:
        path=Path(game)/FOLDERS[component['kind']]/component['filename']
        with path.open('rb') as source:
            if hashlib.file_digest(source,'sha512').hexdigest()!=component['hashes']['sha512']:raise ValueError('Файл изменился во время экспорта: '+path.name)
    return data,encode(data)


class ImportSession:
    def __init__(self,root,data,resolved,java=''):
        self.root=Path(root);self.data=copy.deepcopy(validate(data));self.resolved=resolved;self.java=java
        self.identifier='pack-'+uuid.uuid4().hex[:12];self.stage=None;self.finished=False
    def cleanup(self):
        if self.stage and self.stage.exists():
            target=self.stage.resolve();parent=(self.root/'instances').resolve()
            if not target.is_relative_to(parent) or not target.name.startswith('.code-'):raise ValueError('Неверный путь временной сборки')
            shutil.rmtree(target)
            self.stage=None
    def run(self,transfer,notify):
        if self.finished:raise ValueError('Эта сборка уже импортирована')
        parent=self.root/'instances';parent.mkdir(parents=True,exist_ok=True)
        if self.stage is None:self.stage=Path(tempfile.mkdtemp(prefix='.code-',dir=parent))
        stage=self.stage;data=self.data;count=len(self.resolved);done=0;maximum=1;last_progress=0
        status={label:'ожидание' for label in ('Minecraft','Загрузчик','Моды','Ресурспаки','Шейдеры')}
        def emit(text,value):
            nonlocal last_progress
            last_progress=max(last_progress,min(1,value));notify({'text':text,'progress':last_progress,'done':done,'total':count,'status':dict(status)})
        def check():transfer.check()
        def progress(value):check();emit('Файлы Minecraft и загрузчика',.05+.45*min(1,value/max(1,maximum)))
        def set_max(value):
            nonlocal maximum
            maximum=value
        callback={'setStatus':lambda text:(check(),emit(str(text),last_progress)),'setMax':set_max,'setProgress':progress}
        original_notify=transfer.notify
        try:
            check();emit('Проверяем Java',.01)
            java=loaders.java_for(data['minecraft'],self.java,runtime_root=self.root,callback=callback,game=stage)
            check();status['Minecraft']='устанавливается';status['Загрузчик']='устанавливается' if data['loader']['type']!='vanilla' else 'не требуется';emit('Установка Minecraft и загрузчика',.05)
            loaders.install(data['loader']['type'],data['minecraft'],stage,java,callback,data['loader']['version'],cancel_event=transfer.cancelled)
            check();status['Minecraft']='готово';status['Загрузчик']='готово' if data['loader']['type']!='vanilla' else 'не требуется';emit('Minecraft и загрузчик установлены',.50)
            labels={'mod':'Моды','resourcepack':'Ресурспаки','shader':'Шейдеры'}
            for index,entry in enumerate(self.resolved):
                check();component=entry['component'];label=labels[component['kind']];status[label]='скачивание'
                path=packs.safe_path(stage,FOLDERS[component['kind']]+'/'+component['filename']);path.parent.mkdir(parents=True,exist_ok=True)
                expected=component['hashes'];algorithm='sha512' if 'sha512' in expected else 'sha1'
                valid=False
                if path.is_file():
                    with path.open('rb') as source:valid=hashlib.file_digest(source,algorithm).hexdigest()==expected[algorithm]
                transfer.notify=lambda text,value,index=index:emit(text,.50+.45*(index+value)/max(1,count))
                emit('Компонент: '+component['filename'],.50+.45*index/max(1,count))
                if not valid:
                    temporary=path.with_name(path.name+'.part')
                    try:transfer.download(entry['file'],temporary);check();temporary.replace(path)
                    finally:temporary.unlink(missing_ok=True)
                done=index+1
                if not any(later['component']['kind']==component['kind'] for later in self.resolved[index+1:]):status[label]='готово'
                emit('Установлен: '+component['filename'],.50+.45*done/max(1,count))
            for label in labels.values():status[label]='готово' if any(labels[e['component']['kind']]==label for e in self.resolved) else 'нет файлов'
            check();emit('Сохраняем точный состав сборки',.97)
            if data['resource_order']:(stage/'options.txt').write_text('resourcePacks:'+json.dumps(['vanilla']+['file/'+n for n in data['resource_order']],ensure_ascii=False)+'\n','utf-8')
            if data['shader']:
                shader=data['shader'];relative='optionsshaders.txt' if shader['engine']=='optifine' else 'config/'+shader['engine']+'.properties'
                settings=packs.safe_path(stage,relative);settings.parent.mkdir(parents=True,exist_ok=True)
                escaped=shader['filename'].replace('\\','\\\\').replace('=','\\=').replace(':','\\:')
                settings.write_text('shaderPack='+escaped+'\nenableShaders=true\n','utf-8')
            pinned=data['loader']['version']
            if data['loader']['type']=='forge' and not pinned.startswith(data['minecraft']+'-'):pinned=data['minecraft']+'-'+pinned
            metadata={'id':self.identifier,'name':data['name'],'version':data['minecraft'],'loader_type':data['loader']['type'],'loader':pinned,'source':'code','build_snapshot':data['snapshot']}
            write_json(stage/'.tul4n-build.json',data);write_json(stage/'.chunk.json',metadata)
            check();stage.rename(parent/self.identifier);self.stage=None;self.finished=True;emit('Сборка установлена: '+data['name'],1)
            return metadata
        except Cancelled:
            self.cleanup();raise
        finally:transfer.notify=original_notify


def prepare(data,transfer,custom_java=''):
    validate(data);transfer.check()
    info=loaders.metadata(data['minecraft']);kind=data['loader']['type'];version=data['loader']['version']
    normalized=version if kind!='forge' or version.startswith(data['minecraft']+'-') else data['minecraft']+'-'+version
    if normalized not in loaders.loader_versions(kind,data['minecraft']):raise ValueError('Точная версия '+kind+' '+version+' недоступна для Minecraft '+data['minecraft'])
    major=info.get('javaVersion',{}).get('majorVersion',8)
    if custom_java and loaders.java_major(custom_java)!=major:raise ValueError('Для сборки нужна Java '+str(major)+'. Очистите путь Java в настройках для автоматического выбора.')
    resolved=resolve(data,transfer)
    return resolved,major

