"""Official Minecraft metadata and loader installers."""
import json, os, re, subprocess, zipfile
from pathlib import Path
from functools import lru_cache
from xml.etree import ElementTree
import requests
import minecraft_launcher_lib as mc

VERSIONS=['1.16.5','1.20.1','1.21.1','1.21.4','1.21.11','26.1','26.2','26.3']
LOADERS=['Vanilla','Fabric','Forge','NeoForge']
COMPATIBILITY={}

def get(url):
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    with requests.Session() as session:
        session.mount('https://',HTTPAdapter(max_retries=Retry(total=2,backoff_factor=.3,status_forcelist=[429,500,502,503,504])))
        r=session.get(url,timeout=(10,45));r.raise_for_status();return r

@lru_cache(maxsize=1)
def manifest():return get('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json').json()

def release_versions():
    return [v['id'] for v in manifest()['versions'] if v['type']=='release']

def version_key(value):return tuple(int(x) for x in re.findall(r'\d+',value))

@lru_cache(maxsize=1)
def forge_versions():return mc.forge.list_forge_versions()

@lru_cache(maxsize=32)
def metadata(version):
    entry=next((v for v in manifest()['versions'] if v['id']==version),None)
    if not entry:raise ValueError('Версия '+version+' отсутствует в официальном каталоге Mojang')
    return get(entry['url']).json()

def java_major(path):
    try:
        r=subprocess.run([str(path),'-version'],capture_output=True,text=True,creationflags=0x08000000,timeout=15)
        m=re.search(r'version "(?:1\.)?(\d+)',r.stderr+r.stdout)
        return int(m.group(1)) if m else None
    except (OSError,subprocess.TimeoutExpired):return None

def java_for(version,custom='',runtime_root=None,callback=None,game=None):
    base=Path(game)/'versions'/version/(version+'.json') if game else None
    info=json.loads(base.read_text('utf-8')) if base and base.exists() else metadata(version)
    required=info.get('javaVersion',{}).get('majorVersion',8)
    if custom:
        if java_major(custom)!=required:raise ValueError(f'Для Minecraft {version} нужна Java {required}. Очистите путь Java в настройках для автоматического выбора.')
        return str(custom)
    candidates=[]
    if runtime_root and (Path(runtime_root)/'runtime').exists():candidates.extend((Path(runtime_root)/'runtime').glob('**/bin/java.exe'))
    runtime=Path(os.environ.get('APPDATA',''))/'.minecraft'/'runtime'
    if runtime.exists():candidates.extend(runtime.glob('**/bin/java.exe'))
    for base in (Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Java',Path(os.environ.get('LOCALAPPDATA',''))/'Programs'/'Eclipse Adoptium'):
        if base.exists():candidates.extend(base.glob('*/bin/java.exe'))
    import shutil
    system=shutil.which('java')
    if system:candidates.append(Path(system))
    for candidate in dict.fromkeys(candidates):
        if java_major(candidate)==required:return str(candidate)
    component=info.get('javaVersion',{}).get('component')
    if runtime_root and component:
        mc.runtime.install_jvm_runtime(component,str(runtime_root),callback=callback or {})
        installed=mc.runtime.get_executable_path(component,str(runtime_root))
        if installed and java_major(installed)==required:return installed
    raise ValueError(f'Не найдена Java {required} для Minecraft {version}. Установите её и укажите java.exe в настройках.')

@lru_cache(maxsize=1)
def neoforge_versions():
    root=ElementTree.fromstring(get('https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml').content)
    return [x.text for x in root.findall('./versioning/versions/version') if x.text]

def neo_minecraft(loader):
    parts=loader.split('.')
    if int(parts[0])>=26:
        return '.'.join(parts[:2] if parts[2]=='0' else parts[:3])
    return '1.'+'.'.join(parts[:2])

@lru_cache(maxsize=128)
def loader_versions(kind,version):
    if not any(v['id']==version for v in manifest()['versions']):raise ValueError('Версия отсутствует в каталоге Mojang: '+version)
    if kind=='vanilla':return [version]
    if kind=='fabric':
        entries=get('https://meta.fabricmc.net/v2/versions/loader/'+version).json()
        stable=[x['loader']['version'] for x in entries if x['loader'].get('stable')]
        return stable+[x['loader']['version'] for x in entries if not x['loader'].get('stable')]
    elif kind=='forge':
        return sorted((v for v in forge_versions() if v.startswith(version+'-')),key=version_key,reverse=True)
    elif kind=='neoforge':
        versions=sorted((v for v in neoforge_versions() if neo_minecraft(v)==version),key=version_key,reverse=True)
        stable=[v for v in versions if 'beta' not in v and 'alpha' not in v]
        return stable+[v for v in versions if v not in stable]
    raise ValueError('Неизвестный загрузчик: '+kind)

def compatible(version):
    result={'vanilla':loader_versions('vanilla',version)}; errors=[]
    from concurrent.futures import ThreadPoolExecutor
    def fetch(kind):
        try:return kind,loader_versions(kind,version),''
        except Exception as e:return kind,[],kind.title()+': '+str(e)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for kind,versions,error in pool.map(fetch,('fabric','forge','neoforge')):
            if versions:result[kind]=versions
            if error:errors.append(error)
    COMPATIBILITY[version]=result
    return result,errors

def available(kind,version):
    versions=loader_versions(kind,version)
    if versions:return versions[0]
    raise ValueError(f'Для Minecraft {version} нет поддерживаемой установки {kind.title()}. Выберите другой загрузчик или версию.')

def install(kind,version,game,java,callback,pinned=None,cancel_event=None,repair=False):
    def check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            from instance_tools import Cancelled
            raise Cancelled('Импорт отменён')
    check_cancel()
    game=Path(game); game.mkdir(parents=True,exist_ok=True)
    if kind=='forge' and pinned and not pinned.startswith(version+'-'):pinned=version+'-'+pinned
    marker=game/'.chunk-loader-ready.json'
    if marker.exists() and not repair:
        data=json.loads(marker.read_text('utf-8'))
        if data.get('kind')==kind and data.get('minecraft',version)==version and (pinned is None or data.get('loader')==pinned) and (game/'versions'/data['id']/(data['id']+'.json')).exists():return data['id']
    if repair:marker.unlink(missing_ok=True)
    loader=pinned or available(kind,version)
    if kind=='forge' and not loader.startswith(version+'-'):loader=version+'-'+loader
    if loader not in loader_versions(kind,version):raise ValueError('Выбранный загрузчик несовместим с Minecraft '+version)
    if kind=='vanilla':
        mc.install.install_minecraft_version(version,str(game),callback=callback)
        installed=version
    elif kind=='fabric':
        # Official profile avoids running a modern installer under old game's Java 8.
        profile=get(f'https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/profile/json').json()
        installed=profile['id']
        if profile.get('inheritsFrom')!=version or not re.fullmatch(r'[\w.+-]+',installed):raise ValueError('Неверный профиль Fabric')
        folder=game/'versions'/installed;folder.mkdir(parents=True,exist_ok=True)
        (folder/(installed+'.json')).write_text(json.dumps(profile),'utf-8')
        mc.install.install_minecraft_version(version,str(game),callback=callback)
        mc.install.install_minecraft_version(installed,str(game),callback=callback)
    elif kind=='forge':
        forge_version=loader if loader.startswith(version+'-') else version+'-'+loader
        if cancel_event is None:mc.forge.install_forge_version(forge_version,str(game),callback=callback,java=java)
        else:
            original_process=mc.forge.subprocess
            class CancellableProcessors:
                def __getattr__(self,name):return getattr(original_process,name)
                def run(self,command,**options):
                    options.pop('check',None);options.setdefault('creationflags',0x08000000)
                    process=original_process.Popen(command,**options)
                    while process.poll() is None:
                        if cancel_event.wait(.2):
                            process.terminate()
                            try:process.wait(timeout=5)
                            except subprocess.TimeoutExpired:process.kill();process.wait()
                            check_cancel()
                    if process.returncode:raise subprocess.CalledProcessError(process.returncode,command)
                    return subprocess.CompletedProcess(command,process.returncode)
            try:
                mc.forge.subprocess=CancellableProcessors()
                mc.forge.install_forge_version(forge_version,str(game),callback=callback,java=java)
            finally:mc.forge.subprocess=original_process
        installed=mc.forge.forge_to_installed_version(forge_version)
    elif kind=='neoforge':
        mc.install.install_minecraft_version(version,str(game),callback=callback)
        profiles=game/'launcher_profiles.json'
        if not profiles.exists():profiles.write_text('{"profiles":{}}','utf-8')
        cache=game/'loader-cache';cache.mkdir(exist_ok=True)
        installer=cache/('neoforge-'+loader+'-installer.jar')
        if not re.fullmatch(r'[0-9][0-9A-Za-z.+-]*',loader):raise ValueError('Неверная версия NeoForge')
        if not installer.exists():
            response=get(f'https://maven.neoforged.net/releases/net/neoforged/neoforge/{loader}/neoforge-{loader}-installer.jar')
            installer.write_bytes(response.content)
        with zipfile.ZipFile(installer) as archive:
            profile=json.loads(archive.read('install_profile.json'))
        if profile['minecraft']!=version:raise ValueError('Установщик NeoForge предназначен для другой версии Minecraft')
        installed=profile['version']
        callback.get('setStatus',lambda _:None)('Устанавливаем NeoForge '+loader+'…')
        with (game/'loader-install.log').open('w',encoding='utf-8') as log:
            if cancel_event is None:
                code=subprocess.call([java,'-jar',str(installer),'--installClient',str(game)],cwd=game,stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
            else:
                process=subprocess.Popen([java,'-jar',str(installer),'--installClient',str(game)],cwd=game,stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
                while process.poll() is None:
                    if cancel_event.wait(.2):
                        process.terminate()
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:process.kill();process.wait()
                        check_cancel()
                code=process.returncode
        if code:raise ValueError('Установщик NeoForge завершился с ошибкой. Подробности в loader-install.log')
        mc.install.install_minecraft_version(installed,str(game),callback=callback)
    else:raise ValueError('Неизвестный загрузчик')
    if not (game/'versions'/installed/(installed+'.json')).exists():raise ValueError('Установщик не создал профиль загрузчика')
    check_cancel()
    marker.write_text(json.dumps({'kind':kind,'loader':loader,'minecraft':version,'id':installed}),'utf-8')
    return installed

