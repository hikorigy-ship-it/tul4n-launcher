import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
import requests
import packs
import instance_tools as tools


def release(project, version, dependencies=(), game='1.21.4', loader='fabric'):
    content=(project+version).encode()
    return dict(project_id=project,id=project+version,date_published=version,game_versions=[game],loaders=[loader],dependencies=list(dependencies),files=[dict(filename=project+'-'+version+'.jar',url='https://cdn.modrinth.com/'+project+version,hashes={'sha512':hashlib.sha512(content).hexdigest()})])


def required(project, version=None):return dict(project_id=project,version_id=version,dependency_type='required')
releases=[release('lib','1'),release('lib','2'),release('mod','1',[required('lib','lib1')]),release('mod','2',[required('lib','lib2')])]
latest={'lib':'lib2','mod':'mod1'}
def api(path,params=None):
    if path.startswith('project/'):
        project=path.split('/')[1];return [r for r in releases if r['id']==latest[project]]
    if path.startswith('version/'):
        return next(r for r in releases if r['id']==path.split('/')[1])
    if path.startswith('version_file/'):
        result=next((r for r in releases if r['files'][0]['hashes']['sha512']==path.split('/')[1]),None)
        if result:return result
        response=requests.Response();response.status_code=404;raise requests.HTTPError(response=response)
    raise AssertionError(path)


def download(self,file,target):
    self.check();Path(target).write_bytes(file['url'].rsplit('/',1)[1].encode())


def rejected(fn,fragment):
    try:fn()
    except ValueError as error:assert fragment in str(error),str(error)
    else:raise AssertionError('Expected rejection: '+fragment)


with tempfile.TemporaryDirectory() as directory, patch.object(packs,'api',side_effect=api), patch.object(tools.Transfer,'download',download):
    root=Path(directory);item=packs.new_instance(root,'Test','1.21.4','0.20.1','fabric');folder=root/'instances'/item['id']
    transfer=tools.Transfer(lambda *a:None)
    saves=folder/'saves'/'World';saves.mkdir(parents=True);(saves/'level.dat').write_bytes(b'world')
    result=tools.apply_mods(folder,item,[('mod',None)],transfer)
    assert len(list((folder/'mods').glob('*.jar')))==2
    assert (folder/'mods'/'lib-1.jar').exists() and (folder/'mods'/'mod-1.jar').exists()
    assert list((folder/'backups').glob('*.zip'))
    old={p.name:p.read_bytes() for p in (folder/'mods').glob('*')}
    # Failure during staging leaves every old mod unchanged.
    latest['mod']='mod2'
    with patch.object(tools.Transfer,'download',side_effect=OSError('network')):
        try:tools.update_mods(folder,item,transfer)
        except OSError:pass
        else:raise AssertionError('Expected download failure')
    assert old=={p.name:p.read_bytes() for p in (folder/'mods').glob('*')}
    tools.update_mods(folder,item,transfer)
    assert sorted(p.name for p in (folder/'mods').glob('*.jar'))==['lib-2.jar','mod-2.jar']
    tools.rollback(folder)
    assert old=={p.name:p.read_bytes() for p in (folder/'mods').glob('*')}
    rejected(lambda:tools.resolve(dict(item,version='1.20.1'),[('mod',None)],{},transfer),'Нет совместимой')
    conflict=release('bad','1',[dict(project_id='mod',version_id=None,dependency_type='incompatible')])
    releases.append(conflict);latest['bad']='bad1'
    installed,unknown=tools.inventory(folder,transfer)
    rejected(lambda:tools.resolve(item,[('bad',None)],installed,transfer),'Конфликт')
    rejected(lambda:tools.resolve(item,[('mod','mod1'),('lib','lib2')],{},transfer),'разные версии')
    exported=root/'test.tul4n.zip';tools.export_pack(folder,item,exported,transfer)
    with zipfile.ZipFile(exported) as archive:
        assert 'tul4n-pack.json' in archive.namelist()
        assert not any(p.startswith('saves/') or 'settings.json' in p for p in archive.namelist())
    imported=tools.import_pack(root,exported,transfer)
    assert imported['id']!=item['id'] and (root/'instances'/imported['id']/'mods'/'mod-1.jar').exists()
    malicious=root/'bad.zip'
    with zipfile.ZipFile(malicious,'w') as archive:
        archive.writestr('tul4n-pack.json',json.dumps({'format':1,'pack':item}));archive.writestr('../escape.txt','bad')
    rejected(lambda:tools.import_pack(root,malicious,transfer),'Недопустимый')
    assert not (root/'instances'/'escape.txt').exists()
    updated=tools.save_options(folder,6,'',1600,900,True)
    assert updated['ram']==6 and updated['width']==1600
    rejected(lambda:tools.save_options(folder,100,'',1280,720,True),'Память')
    cancelled=tools.Transfer(lambda *a:None);cancelled.cancelled.set()
    try:tools.apply_mods(folder,item,[('mod',None)],cancelled)
    except tools.Cancelled:pass
    else:raise AssertionError('Expected cancellation')
    assert old=={p.name:p.read_bytes() for p in (folder/'mods').glob('*')}
    (folder/'game.log').write_text('java.lang.OutOfMemoryError','utf-8');assert 'памяти' in tools.explain_crash(folder,1)
print('PASS: dependencies, compatibility/conflicts, staged failure, updates/rollback, world backup, portable export/import, traversal rejection, options, cancellation and crash explanation')

# Exercise real streaming and hash checks without downloading large files.
payload=b'small verified jar'
class Response:
    headers={'Content-Length':str(len(payload))}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):pass
    def iter_content(self,*args):yield payload
class Session(Response):
    attempts=0
    def get(self,*args,**kwargs):
        Session.attempts+=1
        if Session.attempts==1:raise requests.ConnectionError('test interruption')
        return Response()
with tempfile.TemporaryDirectory() as directory,patch.object(packs,'session',return_value=Session()):
    file=dict(filename='test.jar',url='https://cdn.modrinth.com/test.jar',hashes={'sha512':hashlib.sha512(payload).hexdigest()})
    target=Path(directory)/'test.jar';tools.Transfer(lambda *a:None).download(file,target)
    assert target.read_bytes()==payload and Session.attempts==2
    rejected(lambda:tools.Transfer(lambda *a:None).download(dict(file,hashes={'sha512':'0'*128}),target),'контрольной суммы')
print('PASS: streamed checksum verification and automatic retry')

import launcher
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    item=packs.new_instance(root,'UI test','1.21.4','0.20.1','fabric')
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'):
        app=launcher.Launcher();app.catalog_loaded=True;app.active_id=item['id'];app.refresh_instances();app.pack_tools(item);app.update()
        assert app.tools_note.winfo_exists()
        app.accounts=['Player'];app.launch_context=('Player',dict(item,ram=6,width=1600,height=900));app.cfg['ram']=2
        class Process:
            def wait(self):return 0
        with patch.object(launcher.loaders,'java_for',return_value='java.exe'),patch.object(launcher.loaders,'install',return_value='profile'),patch.object(launcher.mc.command,'get_minecraft_command',return_value=['java.exe']) as command,patch.object(launcher.subprocess,'Popen',return_value=Process()):
            app.launch()
            options=command.call_args.args[2]
            assert options['jvmArguments']==['-Xmx6G'] and options['resolutionWidth']=='1600' and options['resolutionHeight']=='900'
        app.close()
print('PASS: maintenance UI and per-instance memory/resolution launch options')

