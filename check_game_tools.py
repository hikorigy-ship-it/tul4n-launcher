import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import game_tools as game
import instance_tools as tools
import packs

sha=lambda b:hashlib.sha1(b).hexdigest()
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);item=packs.new_instance(root,'Тест архива','1.21.4','0.20.1','fabric');folder=root/'instances'/item['id']
    for relative,data in {'mods/local.jar':b'local mod','config/test.json':b'{}','resourcepacks/local.zip':b'pack','shaderpacks/local.zip':b'shader','saves/World/level.dat':b'private world','game.log':b'private log'}.items():
        p=folder/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    transfer=tools.Transfer(lambda *a:None);archive=root/'pack.tul4n.zip'
    tools.export_pack(folder,item,archive,transfer)
    imported=tools.import_pack(root,archive,transfer);copy=root/'instances'/imported['id']
    assert (copy/'mods/local.jar').read_bytes()==b'local mod' and not (copy/'saves').exists() and not (copy/'game.log').exists()
    with zipfile.ZipFile(archive) as source:
        files={n:source.read(n) for n in source.namelist()}
    files['mods/local.jar']=b'tampered';bad=root/'bad.zip'
    with zipfile.ZipFile(bad,'w') as target:
        for name,content in files.items():target.writestr(name,content)
    before=set((root/'instances').iterdir())
    try:tools.import_pack(root,bad,transfer)
    except ValueError as e:assert 'контрольная сумма' in str(e)
    else:raise AssertionError('accepted changed archive')
    assert set((root/'instances').iterdir())==before
    legacy=root/'legacy.zip'
    with zipfile.ZipFile(legacy,'w') as target:
        target.writestr('tul4n-pack.json',json.dumps({'format':1,'pack':item}));target.writestr('mods/old.jar',b'old')
    assert (root/'instances'/tools.import_pack(root,legacy,transfer)['id']/'mods/old.jar').read_bytes()==b'old'
    # Small official metadata fixture: only two broken files require a download.
    fixture=root/'game';fixture.mkdir();item=dict(item,loader_type='vanilla',loader='1.21.4')
    payloads={}
    def record(name,data):
        url='https://piston-data.mojang.com/'+name;payloads[url]=data
        return {'url':url,'sha1':sha(data)}
    info={'downloads':{'client':record('client',b'client')},'libraries':[]}
    index=json.dumps({'objects':{'x':{'hash':sha(b'asset')}}}).encode()
    info['assetIndex']=dict(record('index',index),id='test')
    raw=json.dumps(info).encode();manifest={'versions':[dict(record('meta',raw),id='1.21.4')]}
    for relative,data in {'versions/1.21.4/1.21.4.json':raw,'versions/1.21.4/1.21.4.jar':b'broken','assets/indexes/test.json':index}.items():
        p=fixture/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    payloads['https://resources.download.minecraft.net/'+sha(b'asset')[:2]+'/'+sha(b'asset')]=b'asset'
    tools.write_json(fixture/'.chunk-loader-ready.json',{'kind':'vanilla','minecraft':'1.21.4','loader':'1.21.4','id':'1.21.4'})
    downloaded=[]
    def download(file,target,**kwargs):
        data=payloads[file['url']];assert sha(data)==file['hashes']['sha1'];Path(target).write_bytes(data);downloaded.append(file['url'])
    with patch.object(game.loaders,'metadata',return_value=info),patch.object(game.loaders,'manifest',return_value=manifest),patch.object(transfer,'download',side_effect=download),patch.object(game.loaders,'install') as install:
        assert len(game.audit(fixture,item,transfer)['bad'])==2
        game.repair(root,fixture,item,transfer);assert len(downloaded)==2 and not install.called
        game.repair(root,fixture,item,transfer);assert len(downloaded)==2
        client=fixture/'versions/1.21.4/1.21.4.jar';client.write_bytes(b'corrupt')
        with patch.object(transfer,'download',side_effect=OSError('network')):
            try:game.repair(root,fixture,item,transfer)
            except OSError:pass
            else:raise AssertionError('expected error')
        assert client.read_bytes()==b'corrupt'
    text='--accessToken secret\n{"password":"two words"}\naccess_token=token\n[ERROR] boom\njava.lang.Exception: test'
    log=fixture/'game.log';log.write_text(text,'utf-8');redacted,_=game.read_log(fixture,log)
    assert all(secret not in redacted for secret in ('secret','two words','=token')) and 'boom' in game.errors(redacted)
    log.write_bytes(b'x'*600000);assert len(game.read_log(fixture,log)[0])==512*1024
print('PASS: ZIP roundtrip, legacy import, hash rejection/cleanup, targeted game repair, no-op repair, download failure preservation, bounded/redacted logs')

import launcher
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    item=packs.new_instance(root,'UI test','1.21.4','0.20.1','fabric')
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'):
        app=launcher.Launcher();app.active_id=item['id'];app.refresh_instances();app.export_build(item);app.show_game_log(item);app.update()
        viewer=app.log_windows[-1];viewer.result('[ERROR] test',('test',1,1),True);viewer.copy(True)
        assert app.clipboard_get()=='[ERROR] test'
        app.after(250,app.quit);app.mainloop();app.close()
print('PASS: export chooser and log UI/copy/close')

