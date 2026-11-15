import base64
import copy
import hashlib
import io
import json
import tempfile
import uuid
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch
import build_codes as codes
import packs
import loaders
from instance_tools import Transfer,Cancelled


def manifest():return {'schema':1,'snapshot':uuid.uuid4().hex,'name':'Точная сборка','minecraft':'1.21.1','loader':{'type':'fabric','version':'0.20.1'},'components':[],'resource_order':[],'shader':None}
def rejected(fn):
    try:fn()
    except (ValueError,KeyError):return
    raise AssertionError('Invalid manifest accepted')
data=manifest();code=codes.encode(data);assert codes.decode(code)==data
rejected(lambda:codes.decode(code[:-1]+('0' if code[-1]!='0' else '1')))
for value in ('../evil.jar','C:evil.jar','CON.jar','x.jar:token','x\\evil.jar','x.jar '):rejected(lambda value=value:codes.filename(value,'mod'))
bad=dict(data,url='https://attacker.invalid/file');rejected(lambda:codes.encode(bad))
compressed=base64.urlsafe_b64encode(zlib.compress(b' '* (codes.MAX_JSON+1))).decode().rstrip('=')
rejected(lambda:codes.decode('TUL4N-1-'+compressed+'.'+'0'*64))
rejected(lambda:codes.decode('TUL4N-99-invalid.'+'0'*64))

payloads={};releases={};projects={}
for kind,project,version,filename in [('mod','library','lib1','library.jar'),('mod','example','mod1','example.jar'),('resourcepack','textures','pack1','textures.zip'),('shader','shader','shader1','shader.zip')]:
    if kind=='mod':blob=(project+'-jar-bytes').encode()
    else:
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:archive.writestr('pack.mcmeta' if kind=='resourcepack' else 'shaders/main.fsh','{}')
        blob=buffer.getvalue()
    payloads[filename]=blob;hashes={'sha512':hashlib.sha512(blob).hexdigest(),'sha1':hashlib.sha1(blob).hexdigest()}
    releases[version]={'id':version,'project_id':project,'date_published':'2026-01-01','game_versions':['1.21.1'],'loaders':['fabric'] if kind=='mod' else ['minecraft'] if kind=='resourcepack' else ['iris','optifine'],'files':[{'filename':filename,'url':'https://cdn.modrinth.com/'+filename,'hashes':hashes,'primary':True}],
        'dependencies':[{'dependency_type':'required','project_id':'library','version_id':'lib1'}] if project=='example' else []}
    projects[project]={'id':project,'slug':project,'project_type':kind}
def api(path,params=None):
    if path.startswith('version_file/'):
        digest=path.split('/')[1]
        return next(r for r in releases.values() if r['files'][0]['hashes']['sha512']==digest)
    if path.startswith('version/'):return copy.deepcopy(releases[path.split('/')[1]])
    if path.startswith('project/'):return copy.deepcopy(projects[path.split('/')[1]])
    raise AssertionError(path)
def fake_download(self,file,target):
    self.check();Path(target).write_bytes(payloads[file['filename']]);self.notify(file['filename']+' • 1 МБ/с',1)
def install(kind,version,folder,java,callback,pinned=None,**kwargs):
    folder=Path(folder);profile=folder/'versions'/'installed';profile.mkdir(parents=True,exist_ok=True);(profile/'installed.json').write_text('{}')
    (folder/'.chunk-loader-ready.json').write_text(json.dumps({'kind':kind,'minecraft':version,'loader':pinned,'id':'installed'}))
    return 'installed'
with tempfile.TemporaryDirectory() as temporary,patch.object(packs,'api',side_effect=api),patch.object(Transfer,'download',fake_download):
    root=Path(temporary);item=packs.new_instance(root,'Точная сборка','1.21.1','0.20.1','fabric');source=root/'instances'/item['id']
    for release in releases.values():
        file=release['files'][0];kind=projects[release['project_id']]['project_type'];folder=source/codes.FOLDERS[kind];folder.mkdir(exist_ok=True);(folder/file['filename']).write_bytes(payloads[file['filename']])
    (source/'options.txt').write_text('resourcePacks:["vanilla","file/textures.zip"]\n')
    (source/'settings.json').write_text('{"password":"never-export-me"}')
    rows,_,_=codes.scan(source);selection=[(r['kind'],r['filename']) for r in rows if r['default']]
    exported,code=codes.export(source,item,selection,Transfer(lambda *args:None));decoded=codes.decode(code)
    assert len(decoded['components'])==4 and 'never-export-me' not in json.dumps(decoded)
    assert all(c['version'] in releases for c in decoded['components'])
    original={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    with patch.object(loaders,'metadata',return_value={'javaVersion':{'majorVersion':21}}),patch.object(loaders,'loader_versions',return_value=['0.20.1']):
        resolved,major=codes.prepare(decoded,Transfer(lambda *args:None));assert major==21
    for kind,pin in [('vanilla','1.21.1'),('fabric','0.20.1'),('forge','1.21.1-52.1.0'),('neoforge','21.1.219')]:
        empty=manifest();empty.update(name='Empty '+kind,loader={'type':kind,'version':pin})
        session=codes.ImportSession(root,empty,[])
        with patch.object(loaders,'java_for',return_value='java.exe'),patch.object(loaders,'install',side_effect=install) as routed:
            result=session.run(Transfer(lambda *a:None),lambda state:None)
            assert routed.call_args.args[0]==kind and routed.call_args.args[5]==pin
            assert result['loader']==pin
    session=codes.ImportSession(root,decoded,resolved);states=[]
    with patch.object(loaders,'java_for',return_value='java.exe'),patch.object(loaders,'install',side_effect=install):
        result=session.run(Transfer(lambda *args:None),states.append)
    destination=root/'instances'/result['id'];assert destination!=source and result['name']==item['name']
    for component in decoded['components']:
        path=destination/codes.FOLDERS[component['kind']]/component['filename'];assert hashlib.sha512(path.read_bytes()).hexdigest()==component['hashes']['sha512']
    assert not (destination/'settings.json').exists() and states[-1]['progress']==1
    assert original=={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    # A failed second file can be retried without re-downloading the first.
    session=codes.ImportSession(root,decoded,resolved);attempts=[];fail=[True]
    def interrupted(self,file,target):
        attempts.append(file['filename'])
        if len(attempts)==2 and fail[0]:raise OSError('test interrupted download')
        fake_download(self,file,target)
    with patch.object(loaders,'java_for',return_value='java.exe'),patch.object(loaders,'install',side_effect=install),patch.object(Transfer,'download',interrupted):
        try:session.run(Transfer(lambda *a:None),lambda state:None)
        except OSError:pass
        else:raise AssertionError('Expected failure')
        assert not any(i['id']==session.identifier for i in packs.list_instances(root))
        fail[0]=False;session.run(Transfer(lambda *a:None),lambda state:None)
        assert attempts.count(attempts[0])==1
    session=codes.ImportSession(root,decoded,resolved);cancel=Transfer(lambda *args:None);cancel.cancelled.set()
    try:session.run(cancel,lambda state:None)
    except Cancelled:pass
    else:raise AssertionError('Expected cancellation')
    assert session.stage is None and not any(i['id']==session.identifier for i in packs.list_instances(root))
    missing=copy.deepcopy(decoded);missing['components']=[c for c in missing['components'] if c['project']!='library'];rejected(lambda:codes.resolve(missing,Transfer(lambda *args:None)))
    bad=copy.deepcopy(decoded);bad['components'][0]['hashes']['sha512']='0'*128;rejected(lambda:codes.resolve(bad,Transfer(lambda *args:None)))
    assert codes.encode(exported)!=codes.encode(dict(exported,snapshot=uuid.uuid4().hex))
print('PASS: format/checksum/bounds/path safety, exact components and dependencies, four installer routes, isolated Unicode-name roundtrip, no private data, unchanged source, retry reuses verified files, cancellation and incomplete-instance exclusion')

import launcher
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'),patch.object(launcher.Launcher,'load_pack_cover'):
        app=launcher.Launcher();app.catalog_loaded=True;app.update();app.show('Сборки');app.build_tabs.set('Импорт по коду');app.after(200,app.quit);app.mainloop()
        app.build_code_ui.input.insert('1.0',code);assert app.build_code_ui.input.get('1.0','end').strip()==code
        app.clipboard_clear();app.clipboard_append(code);assert app.clipboard_get()==code
        assert app.build_code_ui.input.winfo_ismapped()
        app.close()
print('PASS: build-code import tab, long code input and exact clipboard roundtrip')

