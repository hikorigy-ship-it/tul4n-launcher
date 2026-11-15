"""Isolated Fabric instances and validated Modrinth pack installation."""
import hashlib
import json
import re
import uuid
import zipfile
from pathlib import Path, PurePosixPath
import requests
from loaders import VERSIONS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def session():
    s=requests.Session()
    s.headers['User-Agent']='CHUNKLauncher/2.0 (personal Windows launcher)'
    s.mount('https://',HTTPAdapter(max_retries=Retry(total=2,backoff_factor=.5,status_forcelist=[429,500,502,503,504])))
    return s

def api(path,params=None):
    with session() as s:
        r=s.get('https://api.modrinth.com/v2/'+path,params=params,timeout=(10,35))
        r.raise_for_status(); return r.json()

def search(query,version,loader_type,project_type='mod',limit=20):
    facets=[['project_type:'+project_type],['categories:'+loader_type],['versions:'+version]]
    data=api('search',{'query':query,'facets':json.dumps(facets),'index':'relevance' if query else 'downloads','limit':limit})['hits']
    notice=''
    if query:
        # Prioritize names without discarding legitimate description-based searches.
        named=[x for x in data if query.casefold() in x['title'].casefold()]
        if named:data=named
        def normal(value):return re.sub(r'[^\w]+',' ',value.casefold()).strip()
        wanted=normal(query)
        exact=lambda x:normal(x['title']) in (wanted,wanted+' '+loader_type)
        data.sort(key=lambda x:not exact(x))
        if not any(exact(x) for x in data):
            try:
                alternatives=api('search',{'query':query,'facets':json.dumps([['project_type:'+project_type],['categories:'+loader_type]]),'index':'relevance','limit':15})['hits']
                match=next((x for x in alternatives if exact(x)),None)
                if match and version not in match.get('versions',[]):
                    supported=', '.join(match.get('versions',[])[-6:])
                    notice=f'{match["title"]} недоступен для {loader_type.title()} {version}. Версии на Modrinth: {supported}. Ниже — другие совпадения по запросу.'
            except requests.RequestException:pass
    return data,notice

def safe_path(root,relative):
    if '\\' in relative or ':' in relative: raise ValueError('Недопустимый путь в сборке')
    p=PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts: raise ValueError('Недопустимый путь в сборке')
    result=(Path(root)/Path(*p.parts)).resolve()
    if not result.is_relative_to(Path(root).resolve()): raise ValueError('Файл выходит за папку сборки')
    return result

def new_instance(root,name,version,loader=None,loader_type='fabric'):
    name=name.strip()
    if not 1<=len(name)<=64: raise ValueError('Название сборки должно содержать от 1 до 64 символов')
    folder=Path(root)/'instances'/('pack-'+uuid.uuid4().hex[:12])
    folder.mkdir(parents=True,exist_ok=False)
    data={'id':folder.name,'name':name,'version':version,'loader':loader,'loader_type':loader_type,'source':'local'}
    (folder/'.chunk.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
    return data

def list_instances(root):
    result=[{'id':v if kind=='fabric' else kind+'-'+v,'name':kind.title()+' '+v,'version':v,'loader':None,'loader_type':kind,'source':'base'} for v in VERSIONS for kind in ('fabric','forge','neoforge')]
    folder=Path(root)/'instances'
    if folder.exists():
        for child in folder.iterdir():
            if child.is_symlink() or not child.is_dir(): continue
            metadata=child/'.chunk.json'
            if not metadata.exists(): continue
            try:
                data=json.loads(metadata.read_text('utf-8'))
                data.setdefault('loader_type','fabric')
                if data['id']==child.name and data['version'] in VERSIONS:result.append(data)
            except (ValueError,KeyError,OSError): pass
    return result

def download(url,path,hashes=None):
    from urllib.parse import urlparse
    host=urlparse(url).hostname or ''
    allowed=('cdn.modrinth.com','github.com','raw.githubusercontent.com','objects.githubusercontent.com','resources.download.minecraft.net','edge.forgecdn.net','mediafilez.forgecdn.net')
    if not url.startswith('https://') or host not in allowed: raise ValueError('Сборка содержит неподдерживаемый источник: '+host)
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.part')
    digests={algo:hashlib.new(algo) for algo in (hashes or {}) if algo in ('sha1','sha512')}
    try:
        with session() as s, s.get(url,stream=True,timeout=(10,90)) as r:
            r.raise_for_status()
            total=0
            with tmp.open('wb') as f:
                for block in r.iter_content(262144):
                    total+=len(block)
                    if total>1024*1024*1024:raise ValueError('Файл сборки превышает 1 ГБ')
                    f.write(block)
                    for digest in digests.values():digest.update(block)
        for algo,digest in digests.items():
            if digest.hexdigest()!=(hashes[algo]).lower():raise ValueError('Не совпала контрольная сумма: '+path.name)
        tmp.replace(path)
    finally:
        if tmp.exists():tmp.unlink()

def unpack(archive,folder,version,notify,loader_type='fabric'):
    with zipfile.ZipFile(archive) as z:
        index=json.loads(z.read('modrinth.index.json'))
        deps=index['dependencies']
        if index.get('formatVersion')!=1 or index.get('game')!='minecraft':raise ValueError('Неподдерживаемый формат сборки')
        key={'fabric':'fabric-loader','forge':'forge','neoforge':'neoforge'}[loader_type]
        if deps.get('minecraft')!=version or not deps.get(key):raise ValueError(f'Нужна сборка {loader_type.title()} для Minecraft '+version)
        if any(k in deps for k in ('fabric-loader','forge','neoforge','quilt-loader') if k!=key):raise ValueError('Эта сборка использует другой загрузчик')
        files=[f for f in index['files'] if f.get('env',{}).get('client')!='unsupported']
        # Validate the entire manifest and archive before creating any pack file.
        for f in files:
            safe_path(folder,f['path'])
            if not f.get('hashes',{}).get('sha1'):raise ValueError('В сборке отсутствует контрольная сумма файла')
        overrides=[]
        expanded=0
        for prefix in ('overrides/','client-overrides/'):
            for item in z.infolist():
                if item.filename.startswith(prefix) and not item.is_dir():
                    target=safe_path(folder,item.filename[len(prefix):]); expanded+=item.file_size
                    if expanded>2*1024**3:raise ValueError('Слишком большой размер распакованной сборки')
                    overrides.append((item,target))
        for i,f in enumerate(files):
            notify(f'Файлы сборки: {i+1}/{len(files)} • '+Path(f['path']).name,(i+1)/(len(files)+1))
            last=None
            for url in f.get('downloads',[]):
                try:download(url,safe_path(folder,f['path']),f['hashes']); last=None; break
                except Exception as e:last=e
            if last or not f.get('downloads'):raise ValueError('Не удалось скачать '+f['path']+': '+str(last))
        for item,target in overrides:
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item) as src,target.open('wb') as dst:
                import shutil
                shutil.copyfileobj(src,dst)
        return deps[key]

def install(root,project,version,notify,loader_type='fabric'):
    versions=api('project/'+project['project_id']+'/version',{'game_versions':json.dumps([version]),'loaders':json.dumps([loader_type])})
    versions=[v for v in versions if version in v['game_versions'] and loader_type in v['loaders']]
    if not versions:raise ValueError('Нет совместимой сборки '+loader_type.title()+' для '+version)
    release=max(versions,key=lambda v:v['date_published'])
    files=[f for f in release['files'] if f['filename'].endswith('.mrpack')]
    if not files:raise ValueError('У сборки отсутствует файл .mrpack')
    file=next((f for f in files if f.get('primary')),files[0])
    cache=Path(root)/'cache'/'modpacks'; cache.mkdir(parents=True,exist_ok=True)
    archive=cache/(release['id']+'.mrpack')
    notify('Скачиваем архив '+project['title'],0)
    download(file['url'],archive,file['hashes'])
    # Unique staging directory; incomplete packs never appear in the library.
    instance_id='pack-'+uuid.uuid4().hex[:12]
    staging=Path(root)/'instances'/('.install-'+uuid.uuid4().hex)
    staging.mkdir(parents=True,exist_ok=False)
    try:
        loader=unpack(archive,staging,version,notify,loader_type)
        data={'id':instance_id,'name':project['title'],'version':version,'loader':loader,'loader_type':loader_type,'source':'modrinth','project_id':project['project_id'],'release_id':release['id']}
        (staging/'.chunk.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
        staging.rename(Path(root)/'instances'/instance_id)
        notify('Сборка установлена: '+project['title'],1)
        return data
    finally:
        if staging.exists() and staging.parent.resolve()==(Path(root)/'instances').resolve() and staging.name.startswith('.install-'):
            import shutil
            shutil.rmtree(staging)

