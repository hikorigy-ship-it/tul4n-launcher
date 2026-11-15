"""Official Minecraft metadata and loader installers."""
import json, os, re, subprocess, zipfile
from pathlib import Path
from functools import lru_cache
from xml.etree import ElementTree
import requests
import minecraft_launcher_lib as mc

VERSIONS=['1.16.5','1.20.1','1.21.1','1.21.4','1.21.11','26.1','26.2','26.3']
LOADERS=['Fabric','Forge','NeoForge']

def get(url):
    r=requests.get(url,timeout=(10,45));r.raise_for_status();return r

@lru_cache(maxsize=1)
def manifest():return get('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json').json()

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

def java_for(version,custom=''):
    required=metadata(version).get('javaVersion',{}).get('majorVersion',8)
    if custom:
        if java_major(custom)!=required:raise ValueError(f'Для Minecraft {version} нужна Java {required}. Очистите путь Java в настройках для автоматического выбора.')
        return str(custom)
    candidates=[]
    runtime=Path(os.environ.get('APPDATA',''))/'.minecraft'/'runtime'
    if runtime.exists():candidates.extend(runtime.glob('**/bin/java.exe'))
    for base in (Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Java',Path(os.environ.get('LOCALAPPDATA',''))/'Programs'/'Eclipse Adoptium'):
        if base.exists():candidates.extend(base.glob('*/bin/java.exe'))
    import shutil
    system=shutil.which('java')
    if system:candidates.append(Path(system))
    for candidate in dict.fromkeys(candidates):
        if java_major(candidate)==required:return str(candidate)
    raise ValueError(f'Не найдена Java {required} для Minecraft {version}. Установите её и укажите java.exe в настройках.')

@lru_cache(maxsize=32)
def available(kind,version):
    if kind=='fabric':
        entries=get('https://meta.fabricmc.net/v2/versions/loader/'+version).json()
        stable=[x['loader']['version'] for x in entries if x['loader'].get('stable')]
        if stable:return stable[0]
        if entries:return entries[0]['loader']['version']
    elif kind=='forge':
        result=next((v for v in forge_versions() if v.startswith(version+'-')),None)
        if result:return result
    elif kind=='neoforge':
        prefix=(version[2:] if version.startswith('1.') else version)+'.'
        root=ElementTree.fromstring(get('https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml').content)
        versions=[x.text for x in root.findall('./versioning/versions/version') if x.text and x.text.startswith(prefix)]
        versions.sort(key=lambda v:tuple(int(n) for n in re.findall(r'\d+',v)),reverse=True)
        stable=[v for v in versions if 'beta' not in v and 'alpha' not in v]
        if stable or versions:return (stable or versions)[0]
    raise ValueError(f'Для Minecraft {version} нет поддерживаемой установки {kind.title()}. Выберите другой загрузчик или версию.')

def install(kind,version,game,java,callback,pinned=None):
    game=Path(game); game.mkdir(parents=True,exist_ok=True)
    loader=pinned or available(kind,version)
    marker=game/'.chunk-loader-ready.json'
    if marker.exists():
        data=json.loads(marker.read_text('utf-8'))
        if data.get('kind')==kind and data.get('loader')==loader and (game/'versions'/data['id']/(data['id']+'.json')).exists():return data['id']
    if kind=='fabric':
        mc.fabric.install_fabric(version,str(game),loader_version=loader,callback=callback,java=java)
        installed=f'fabric-loader-{loader}-{version}'
    elif kind=='forge':
        forge_version=loader if loader.startswith(version+'-') else version+'-'+loader
        mc.forge.install_forge_version(forge_version,str(game),callback=callback,java=java)
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
        with zipfile.ZipFile(installer) as archive:installed=json.loads(archive.read('install_profile.json'))['version']
        callback.get('setStatus',lambda _:None)('Устанавливаем NeoForge '+loader+'…')
        with (game/'loader-install.log').open('w',encoding='utf-8') as log:
            code=subprocess.call([java,'-jar',str(installer),'--installClient',str(game)],cwd=game,stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
        if code:raise ValueError('Установщик NeoForge завершился с ошибкой. Подробности в loader-install.log')
    else:raise ValueError('Неизвестный загрузчик')
    if not (game/'versions'/installed/(installed+'.json')).exists():raise ValueError('Установщик не создал профиль загрузчика')
    marker.write_text(json.dumps({'kind':kind,'loader':loader,'id':installed}),'utf-8')
    return installed

