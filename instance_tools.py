"""Pack maintenance, dependency resolution and transactional mod changes."""
import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
import requests
import packs


class Cancelled(Exception):
    pass


class Transfer:
    def __init__(self, notify):
        self.cancelled = threading.Event()
        self.notify = notify
        self.started = time.monotonic()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled('Загрузка отменена. Установленные моды сохранены.')

    def download(self, file, target, allowed_hosts=None):
        from urllib.parse import urlparse
        url = file['url']
        if urlparse(url).hostname not in (allowed_hosts or ('cdn.modrinth.com',)) or not url.startswith('https://'):
            raise ValueError('Неизвестный источник мода')
        hashes = file.get('hashes', {})
        if not hashes.get('sha512') and not hashes.get('sha1'):
            raise ValueError('У мода отсутствует контрольная сумма')
        target = Path(target)
        for attempt in range(3):
            self.check()
            try:
                digests = {k: hashlib.new(k) for k in hashes if k in ('sha1', 'sha512')}
                with packs.session() as session, session.get(url, stream=True, timeout=(10, 20)) as response:
                    response.raise_for_status()
                    size = 0; started = time.monotonic(); updated = 0
                    total = int(response.headers.get('Content-Length', 0))
                    with target.open('wb') as output:
                        for block in response.iter_content(262144):
                            self.check(); size += len(block)
                            if size > 1024 ** 3:
                                raise ValueError('Мод превышает 1 ГБ')
                            output.write(block)
                            for digest in digests.values(): digest.update(block)
                            now = time.monotonic()
                            if now - updated > .15:
                                self.notify(f'{file["filename"]} • {size/1048576:.1f} МБ • {size/1048576/max(.1,now-started):.1f} МБ/с', min(.99, size / total) if total else 0)
                                updated = now
                if any(d.hexdigest() != hashes[k].lower() for k, d in digests.items()):
                    raise ValueError('Ошибка контрольной суммы: ' + file['filename'])
                return
            except requests.RequestException:
                if attempt == 2: raise
                self.notify('Соединение прервано. Повтор '+str(attempt+1)+'/2…', 0)
                if self.cancelled.wait(.5 * (attempt+1)): self.check()


def write_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8'); tmp.replace(path)


def file_hash(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha512').hexdigest()


def inventory(folder, transfer):
    """Identify enabled and disabled JARs by bytes, never by filenames."""
    result = {}; unknown = []
    if (Path(folder)/'mods').is_symlink(): raise ValueError('Папка модов не должна быть ссылкой')
    for path in sorted((Path(folder)/'mods').glob('*')):
        if path.is_symlink(): raise ValueError('Ссылка в папке модов: ' + path.name)
        if not path.is_file() or not path.name.endswith(('.jar', '.jar.disabled')): continue
        transfer.check(); transfer.notify('Определяем мод: '+path.name, 0)
        try:
            release = packs.api('version_file/'+file_hash(path), {'algorithm':'sha512'})
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                unknown.append(path.name); continue
            raise
        project = release['project_id']
        if project in result: raise ValueError('Несколько файлов одного мода: '+project+'. Уберите дубликат.')
        result[project] = {'release':release, 'filename':path.name}
    return result, unknown


def compatible(release, item):
    return item['version'] in release.get('game_versions', []) and item.get('loader_type','fabric') in release.get('loaders', [])


def resolve(item, roots, installed, transfer):
    selected = {}; pinned = {}; visiting = set()
    def choose(project, pin=None):
        transfer.check()
        if pin:
            if project in pinned and pinned[project] != pin:
                raise ValueError('Зависимости требуют разные версии мода '+project)
            pinned[project] = pin
        if project in selected:
            if pin and selected[project]['id'] != pin:
                raise ValueError('Несовместимые требования к версии мода '+project)
            return
        releases = [packs.api('version/'+pin)] if pin else packs.api('project/'+project+'/version', {'game_versions':json.dumps([item['version']]), 'loaders':json.dumps([item.get('loader_type','fabric')])})
        releases = [r for r in releases if r.get('project_id') == project and compatible(r,item)]
        if not releases: raise ValueError('Нет совместимой версии мода '+project+' для '+item.get('loader_type','fabric')+' '+item['version'])
        release = max(releases, key=lambda r:r['date_published'])
        selected[project] = release; visiting.add(project)
        for dependency in release.get('dependencies', []):
            if dependency['dependency_type'] != 'required': continue
            dep = dependency.get('project_id'); version = dependency.get('version_id')
            if not dep and version: dep = packs.api('version/'+version)['project_id']
            if not dep: raise ValueError('Неизвестная обязательная зависимость: '+str(dependency.get('file_name','')))
            choose(dep, version)
        visiting.discard(project)
    for project, pin in roots: choose(project, pin)
    final = {p:v['release'] for p,v in installed.items() if not v['filename'].endswith('.disabled')}
    final.update(selected)
    for project, release in final.items():
        if not compatible(release, item): raise ValueError('Установленный мод '+project+' не подходит выбранной сборке')
        for dependency in release.get('dependencies', []):
            dep = dependency.get('project_id'); pin = dependency.get('version_id')
            if not dep and pin: dep = packs.api('version/'+pin)['project_id']
            actual = final.get(dep)
            if dependency['dependency_type'] == 'required' and (not actual or pin and actual['id'] != pin):
                raise ValueError('Нарушена зависимость мода '+project+': '+str(dep))
            if dependency['dependency_type'] == 'incompatible' and actual and (not pin or actual['id'] == pin):
                raise ValueError('Конфликт модов: '+project+' и '+str(dep))
    return selected


def archive_tree(source, destination, prefixes, transfer,hashes=None):
    source = Path(source)
    temporary = Path(str(destination)+'.part')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for prefix in prefixes:
                base = source/prefix
                if base.is_symlink() or getattr(base,'is_junction',lambda:False)(): raise ValueError('Нельзя архивировать ссылку: '+prefix)
                paths = [base] if base.is_file() else base.rglob('*') if base.exists() else []
                for path in paths:
                    transfer.check()
                    if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()): raise ValueError('Нельзя архивировать ссылку: '+path.name)
                    if path.is_file():
                        transfer.notify('Архивируем: '+path.name, 0)
                        relative=path.relative_to(source).as_posix();digest=hashlib.sha256()
                        with path.open('rb') as src, archive.open(relative,'w',force_zip64=True) as dst:
                            while block := src.read(1048576):transfer.check();dst.write(block);digest.update(block)
                        if hashes is not None:hashes[relative]=digest.hexdigest()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def backup_worlds(folder, transfer):
    folder = Path(folder)
    if not (folder/'saves').exists(): return None
    destination = folder/'backups'; destination.mkdir(exist_ok=True)
    target = destination/('worlds-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.zip')
    archive_tree(folder,target,['saves'],transfer)
    return target


def apply_mods(folder, item, roots, transfer, known=None):
    folder = Path(folder); folder.mkdir(parents=True,exist_ok=True)
    installed, unknown = known if known is not None else inventory(folder,transfer)
    plan = resolve(item,roots,installed,transfer)
    changed = {p:r for p,r in plan.items() if p not in installed or installed[p]['release']['id'] != r['id'] or installed[p]['filename'].endswith('.disabled')}
    if not changed: return 'Совместимые обновления не найдены.' + (' Не опознано файлов: '+str(len(unknown)) if unknown else '')
    mods = folder/'mods'; mods.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mod-stage-',dir=folder) as staging:
        staging = Path(staging); names = set(); records = {}
        for project, release in changed.items():
            files = [f for f in release['files'] if f['filename'].endswith('.jar')]
            if not files: raise ValueError('В релизе нет JAR: '+project)
            file = next((f for f in files if f.get('primary')),files[0]); name = file['filename']
            packs.safe_path(staging,name)
            if Path(name).name != name or name.casefold() in names: raise ValueError('Повторяющееся или неверное имя мода')
            names.add(name.casefold())
            existing = mods/name
            owner = next((p for p,v in installed.items() if v['filename'] == name),None)
            if existing.exists() and owner != project: raise ValueError('Файл уже занят другим модом: '+name)
            transfer.download(file,staging/name)
            records[project] = {'version_id':release['id'],'filename':name}
        transfer.check()
        if item.get('backup_worlds',True): backup_worlds(folder,transfer)
        # A complete snapshot is created before any old file is moved.
        history = folder/'.mod-history'; history.mkdir(exist_ok=True)
        snapshot = history/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.zip')
        archive_tree(folder,snapshot,['mods','.mods-lock.json'],transfer)
        transfer.check()
        try:
            for project in changed:
                if project in installed: (mods/installed[project]['filename']).unlink()
            for record in records.values(): (staging/record['filename']).replace(mods/record['filename'])
            lockpath = folder/'.mods-lock.json'
            lock = json.loads(lockpath.read_text('utf-8')) if lockpath.exists() else {}
            lock.update(records); write_json(lockpath,lock)
        except Exception:
            restore_mods(folder,snapshot); raise
    return f'Установлено модов и зависимостей: {len(changed)}.' + (' Неизвестные файлы сохранены: '+str(len(unknown)) if unknown else '')


def restore_mods(folder, snapshot):
    folder = Path(folder)
    with zipfile.ZipFile(snapshot) as archive:
        for entry in archive.infolist():
            packs.safe_path(folder,entry.filename)
            if entry.filename != '.mods-lock.json' and not entry.filename.startswith('mods/'):
                raise ValueError('Недопустимый файл в копии модов')
        mods = folder/'mods'
        if mods.is_symlink() or any(p.is_symlink() for p in mods.rglob('*')): raise ValueError('Ссылка в папке модов')
        if mods.exists(): shutil.rmtree(mods)
        (folder/'.mods-lock.json').unlink(missing_ok=True)
        for entry in archive.infolist():
            target = packs.safe_path(folder,entry.filename); target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as src, target.open('wb') as dst: shutil.copyfileobj(src,dst)


def rollback(folder):
    folder = Path(folder); snapshots = sorted((folder/'.mod-history').glob('*.zip'),key=lambda p:p.stat().st_mtime_ns)
    if not snapshots: raise ValueError('Копий модов для отката пока нет')
    snapshot = snapshots[-1]; restore_mods(folder,snapshot); snapshot.rename(snapshot.with_suffix('.restored'))
    return 'Предыдущие моды восстановлены.'


def mod_update_plan(folder,item,transfer):
    installed, unknown = inventory(folder,transfer)
    enabled = {p:v for p,v in installed.items() if not v['filename'].endswith('.disabled')}
    dependencies = set()
    for entry in enabled.values():
        for dependency in entry['release'].get('dependencies',[]):
            if dependency['dependency_type'] != 'required': continue
            project = dependency.get('project_id')
            if not project and dependency.get('version_id'): project = packs.api('version/'+dependency['version_id'])['project_id']
            if project: dependencies.add(project)
    # Libraries follow their parent mods' constraints instead of overriding pins.
    roots = [(p,None) for p in enabled if p not in dependencies] or [(p,None) for p in enabled]
    plan=resolve(item,roots,installed,transfer) if roots else {}
    changes=[{'project':p,'before':installed[p]['release'] if p in installed else None,'after':r} for p,r in plan.items() if p not in installed or installed[p]['release']['id']!=r['id'] or installed[p]['filename'].endswith('.disabled')]
    return {'roots':[(p,r['id']) for p,r in plan.items()],'changes':changes,'unknown':unknown,'installed':installed}


def update_mods(folder,item,transfer):
    plan=mod_update_plan(folder,item,transfer)
    if not plan['changes']:return 'Совместимые обновления не найдены.'
    return apply_mods(folder,item,plan['roots'],transfer,(plan['installed'],plan['unknown']))


PORTABLE = ('mods','config','resourcepacks','shaderpacks','cover.png','.mods-lock.json')


def export_pack(folder,item,destination,transfer):
    destination = Path(destination)
    if destination.resolve().is_relative_to(Path(folder).resolve()): raise ValueError('Сохраните архив за пределами папки сборки')
    temporary = destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        hashes={};archive_tree(folder,temporary,PORTABLE,transfer,hashes)
        with zipfile.ZipFile(temporary,'a',zipfile.ZIP_DEFLATED) as archive:
            metadata = {k:item[k] for k in ('name','version','loader','loader_type','description','cover') if k in item}
            marker=Path(folder)/'.chunk-loader-ready.json'
            if marker.exists():
                ready=json.loads(marker.read_text('utf-8'))
                if ready.get('kind')==item.get('loader_type') and ready.get('minecraft',item['version'])==item['version']:metadata['loader']=ready.get('loader')
            archive.writestr('tul4n-pack.json',json.dumps({'format':2,'pack':metadata,'sha256':hashes},ensure_ascii=False))
        transfer.check(); temporary.replace(destination)
    finally: temporary.unlink(missing_ok=True)
    return 'Сборка экспортирована без миров и аккаунтов: '+destination.name


def import_pack(root,source,transfer):
    root = Path(root); instances = root/'instances'; instances.mkdir(parents=True,exist_ok=True)
    identifier = 'pack-'+uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='.import-',dir=instances) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > 30000 or sum(e.file_size for e in entries)>4*1024**3: raise ValueError('Слишком большой архив сборки (максимум 4 ГБ)')
            meta = archive.getinfo('tul4n-pack.json')
            if meta.file_size > 8*1024*1024: raise ValueError('Слишком большие метаданные')
            data = json.loads(archive.read(meta)); item = data['pack']
            if data.get('format') not in (1,2) or not re.fullmatch(r'[\w.+-]{1,64}',item['version']) or item['loader_type'] not in ('vanilla','fabric','forge','neoforge'):
                raise ValueError('Неверный формат сборки')
            if not isinstance(item.get('name'),str) or not 1<=len(item['name'])<=64: raise ValueError('Неверное название сборки')
            if item.get('loader') and (not isinstance(item['loader'],str) or not re.fullmatch(r'[\w.+-]{1,100}',item['loader'])): raise ValueError('Неверная версия загрузчика')
            if item.get('cover') and item['cover']!='cover.png':raise ValueError('Недопустимое имя обложки')
            hashes=data.get('sha256',{})
            if data['format']==2:
                if not isinstance(hashes,dict) or set(hashes)!={e.filename for e in entries if not e.is_dir() and e.filename!='tul4n-pack.json'}:raise ValueError('Список контрольных сумм не соответствует архиву')
                if any(not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h) for h in hashes.values()):raise ValueError('Неверные контрольные суммы архива')
            from build_codes import filename as valid_filename
            seen = set()
            for number,entry in enumerate(entries):
                target = packs.safe_path(staging,entry.filename)
                key = entry.filename.casefold()
                if key in seen or any(':' in part or part.rstrip(' .')!=part for part in Path(entry.filename).parts): raise ValueError('Повторяющийся или неверный путь')
                seen.add(key)
                if entry.filename=='tul4n-pack.json': continue
                for part in Path(entry.filename).parts:valid_filename(part)
                if entry.filename.split('/')[0] not in PORTABLE: raise ValueError('Посторонний файл в сборке: '+entry.filename)
                if entry.is_dir(): continue
                if (entry.external_attr>>16)&0o170000==0o120000:raise ValueError('Ссылки в архиве не поддерживаются')
                transfer.check(); target.parent.mkdir(parents=True,exist_ok=True)
                digest=hashlib.sha256();transfer.notify('Импортируем: '+entry.filename,number/max(1,len(entries)))
                with archive.open(entry) as src,target.open('wb') as dst:
                    while block:=src.read(1048576):transfer.check();dst.write(block);digest.update(block)
                if data['format']==2 and digest.hexdigest()!=hashes[entry.filename]:raise ValueError('Неверная контрольная сумма: '+entry.filename)
        # Import only portable presentation/version fields; paths and Java are local settings.
        item = {k:item[k] for k in ('name','version','loader','loader_type','description','cover') if k in item}
        item.update(id=identifier,source='local')
        write_json(staging/'.chunk.json',item)
        staging.rename(instances/identifier)
        staging.mkdir()  # TemporaryDirectory owns only this now-empty directory.
    return item


def java_arguments(text):
    if not isinstance(text,str) or len(text)>4096:raise ValueError('Дополнительные параметры Java: максимум 4096 символов')
    if not text.strip():return []
    import os
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        parse=ctypes.windll.shell32.CommandLineToArgvW
        parse.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)];parse.restype=ctypes.POINTER(wintypes.LPWSTR)
        count=ctypes.c_int();arguments=parse('java '+text,ctypes.byref(count))
        if not arguments:raise ValueError('Неверные кавычки в параметрах Java')
        try:values=[arguments[i] for i in range(1,count.value)]
        finally:
            free=ctypes.windll.kernel32.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p;free(arguments)
    else:
        import shlex
        values=shlex.split(text)
    forbidden=('-jar','-cp','-classpath','--class-path','-p','--module-path','-m','--module','-Xmx','-Xms')
    if len(values)>64 or any(not v.startswith('-') or any(v==key or v.startswith(key+'=') or key in ('-Xmx','-Xms') and v.startswith(key) for key in forbidden) for v in values):
        raise ValueError('Память задайте отдельным полем. Каждый дополнительный параметр должен начинаться с «-»; значения указывайте через «=». Подмена запуска Minecraft запрещена.')
    return values


def save_options(folder,ram,java,width,height,automatic_backup,jvm_args='',fullscreen=False,close_launcher=False):
    ram = int(ram); width = int(width); height = int(height)
    if not 1<=ram<=64 or not 640<=width<=7680 or not 480<=height<=4320: raise ValueError('Память: 1–64 ГБ; окно: от 640×480 до 7680×4320')
    if java and (not Path(java).is_file() or Path(java).name.lower() not in ('java.exe','javaw.exe')): raise ValueError('Выберите существующий java.exe или javaw.exe')
    java_arguments(jvm_args)
    path = Path(folder)/'.chunk.json'; item = json.loads(path.read_text('utf-8'))
    item.update(ram=ram,java=java,width=width,height=height,backup_worlds=bool(automatic_backup),jvm_args=jvm_args,fullscreen=bool(fullscreen),close_launcher=bool(close_launcher)); write_json(path,item)
    return item


def explain_crash(folder,code):
    if code==0: return 'Игра закрыта.'
    chunks=[]
    for relative in ('game.log','logs/latest.log'):
        path=Path(folder)/relative
        if path.exists():
            with path.open('rb') as source: source.seek(max(0,path.stat().st_size-100000)); chunks.append(source.read().decode('utf-8','replace'))
    text='\n'.join(chunks)
    if 'OutOfMemoryError' in text: return 'Игре не хватило памяти. Увеличьте память в параметрах сборки.'
    if 'UnsupportedClassVersionError' in text: return 'Версия Java не подходит. В параметрах сборки очистите путь Java для автоматического выбора.'
    if any(s in text for s in ('Incompatible mods found','Mod resolution encountered','Missing mandatory dependencies','requires version')):
        lines=[line.strip() for line in text.splitlines() if any(s in line.lower() for s in ('requires','depends','incompatible','mandatory'))]
        return 'Ошибка совместимости модов. '+(' '.join(lines[-3:])[:450] or 'Проверьте версии модов и обязательные зависимости.')
    return f'Игра завершилась с кодом {code}. Причина не определена; откройте game.log в папке сборки.'

