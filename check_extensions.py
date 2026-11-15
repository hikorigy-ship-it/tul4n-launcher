import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
import packs
import instance_tools as tools
import content_updates
import resource_catalog
import launcher


def blob(version):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:archive.writestr('pack.mcmeta',json.dumps({'version':version}))
    return stream.getvalue()
payloads={v:blob(v) for v in ('one','two')}
releases={v:{'id':v,'project_id':'project','version_number':v,'date_published':'2026-01-0'+str(i+1),'game_versions':['1.21.1'],'loaders':['minecraft'],'files':[{'filename':v+'.zip','primary':True,'url':'https://cdn.modrinth.com/'+v,'hashes':{'sha512':hashlib.sha512(payloads[v]).hexdigest()}}]} for i,v in enumerate(payloads)}
def api(path,params=None):
    if path.startswith('version_file/'):
        return next(v for v in releases.values() if v['files'][0]['hashes']['sha512']==path.split('/')[1])
    if path.startswith('version/'):return releases[path.split('/')[1]]
    if path=='project/project/version':return list(releases.values())
    raise AssertionError(path)
class Transfer:
    def check(self):pass
    def notify(self,*args):pass
    def download(self,file,target):Path(target).write_bytes(payloads[file['url'].rsplit('/',1)[1]])


with tempfile.TemporaryDirectory() as temporary,patch.object(packs,'api',side_effect=api):
    game=Path(temporary);folder=game/'resourcepacks';folder.mkdir();(folder/'one.zip').write_bytes(payloads['one']);item={'version':'1.21.1'}
    assert '1' in content_updates.update(game,item,'resourcepack',Transfer())
    assert not (folder/'one.zip').exists() and (folder/'two.zip').read_bytes()==payloads['two']
    assert not (game/'backups').exists() and not (game/'.mod-history').exists()
    assert [p.name for p in folder.iterdir()]==['two.zip']
    assert content_updates.rollback(game,item,'resourcepack',Transfer()).startswith('Предыдущая')
    assert (folder/'one.zip').read_bytes()==payloads['one'] and not (folder/'two.zip').exists()
    (folder/'two.zip').write_bytes(b'user content')
    try:content_updates.update(game,item,'resourcepack',Transfer())
    except (ValueError,StopIteration):pass
    else:raise AssertionError('Conflicting file was overwritten')
    assert (folder/'two.zip').read_bytes()==b'user content' and (folder/'one.zip').read_bytes()==payloads['one']

assert tools.java_arguments('-Dlabel="Hello world" --add-opens=java.base/java.lang=ALL-UNNAMED')==['-Dlabel=Hello world','--add-opens=java.base/java.lang=ALL-UNNAMED']
assert tools.java_arguments('-Dpath="C:\\My Folder"')==['-Dpath=C:\\My Folder']
for invalid in ('-Xmx16G','-jar hacked.jar','--class-path=other','@file.txt'):
    try:tools.java_arguments(invalid)
    except ValueError:pass
    else:raise AssertionError('Accepted launch replacement: '+invalid)

with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    item=packs.new_instance(root,'Pack','1.21.1','0.20.1','fabric');game=root/'instances'/item['id']
    saved=tools.save_options(game,4,'',1280,720,False,'-Dlabel="Hello world"',True,True)
    assert saved['fullscreen'] and saved['close_launcher'] and saved['jvm_args']
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'),patch.object(launcher.Launcher,'load_pack_cover'):
        app=launcher.Launcher();app.catalog_loaded=True;app.active_id=item['id'];app.refresh_instances();app.update()
        project={'project_id':'project','title':'Favourite','description':'Description','author':'Author'}
        for kind in ('mod','modpack','resourcepack','shader'):
            app.toggle_favorite(project,kind);assert json.loads(launcher.CONFIG.read_text('utf-8'))['favorites'][kind]['project']['title']=='Favourite'
            app.show_favorites(kind)
        preview={'roots':[('project','new')],'unknown':[],'changes':[{'project':'project','before':{'id':'old','version_number':'old'},'after':{'id':'new','name':'Mod','version_number':'new','changelog':'Fixed a bug'}}]}
        app.show_mod_update_preview(item,preview);app.update()
        with patch.object(app,'work') as work:
            app.install_iris();work.assert_called_once()
        unsupported=dict(item,loader_type='forge');app.instances.append(unsupported);app.active_id=unsupported['id']
        with patch.object(app,'active_instance',return_value=unsupported),patch.object(app,'work') as work:
            app.install_iris();assert 'Fabric' in app.resource_catalogs['shader'].note.cget('text');work.assert_not_called()
        app.accounts=['Player'];app.launch_context=('Player',dict(saved,id=item['id'],version='1.21.1',loader_type='fabric'))
        class Process:
            def wait(self):return 0
        with patch.object(launcher.loaders,'java_for',return_value='java.exe'),patch.object(launcher.loaders,'install',return_value='profile'),patch.object(launcher.mc.command,'get_minecraft_command',return_value=['java.exe']) as command,patch.object(launcher.subprocess,'Popen',return_value=Process()) as spawn:
            app.launch();assert '-Dlabel=Hello world' in command.call_args.args[2]['jvmArguments']
            assert '--fullscreen' in spawn.call_args.args[0]
            assert any(event[0]=='close_after_launch' for event in list(app.events.queue))
        app.close()
print('PASS: resource update/rollback re-download without backup ZIPs, collisions, Windows JVM argument quoting/validation, favourite persistence/UI, mod changelog preview, Iris action/unsupported loader, fullscreen and close-after-launch')

