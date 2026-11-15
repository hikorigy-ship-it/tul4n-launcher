"""Real Modrinth roundtrip; only the large Minecraft/Java installation is mocked."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import build_codes as codes
import loaders
import packs
from resource_catalog import install_asset
from instance_tools import Transfer,apply_mods


def fake_game_install(kind,version,game,java,callback,pinned=None,**kwargs):
    folder=Path(game)/'versions'/'test-profile';folder.mkdir(parents=True,exist_ok=True)
    (folder/'test-profile.json').write_text(json.dumps({'inheritsFrom':version}))
    (Path(game)/'.chunk-loader-ready.json').write_text(json.dumps({'kind':kind,'minecraft':version,'loader':pinned,'id':'test-profile'}))
    return 'test-profile'


with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);loader=loaders.loader_versions('fabric','1.21.1')[0]
    item=packs.new_instance(root,'Build Code — точный тест','1.21.1',loader,'fabric');source=root/'instances'/item['id']
    iris=packs.api('project/iris')
    apply_mods(source,dict(item,backup_worlds=False),[(iris['id'],None)],Transfer(lambda *args:None))
    selected_assets={}
    for kind,query in [('resourcepack','Fast Better Grass'),('shader','MakeUp Ultra Fast')]:
        hits,_=packs.search(query,'1.21.1',None,kind,6,order='relevance')
        assert hits,'Actual Modrinth search failed'
        install_asset(source,hits[0],'1.21.1',kind,Transfer(lambda *args:None))
        selected_assets[kind]=next((source/codes.FOLDERS[kind]).glob('*.zip')).name
    (source/'options.txt').write_text('resourcePacks:'+json.dumps(['vanilla','file/'+selected_assets['resourcepack']])+'\n')
    config=source/'config';config.mkdir(exist_ok=True)
    (config/'iris.properties').write_text('shaderPack='+selected_assets['shader']+'\nenableShaders=true\n')
    rows,_,_=codes.scan(source);selection=[(r['kind'],r['filename']) for r in rows if r['default']]
    data,code=codes.export(source,item,selection,Transfer(lambda *args:None))
    decoded=codes.decode(code);resolved,major=codes.prepare(decoded,Transfer(lambda *args:None))
    original={(c['kind'],c['filename']):hashlib.sha512((source/codes.FOLDERS[c['kind']]/c['filename']).read_bytes()).hexdigest() for c in decoded['components']}
    session=codes.ImportSession(root,decoded,resolved)
    with patch.object(loaders,'java_for',return_value='test-java'),patch.object(loaders,'install',side_effect=fake_game_install):
        restored=session.run(Transfer(lambda *args:None),lambda state:None)
    destination=root/'instances'/restored['id']
    assert restored['name']==item['name'] and restored['loader']==loader and restored['version']=='1.21.1'
    snapshot=json.loads((destination/'.tul4n-build.json').read_text('utf-8'));assert snapshot==decoded
    for component in decoded['components']:
        key=(component['kind'],component['filename']);path=codes.FOLDERS[component['kind']]+'/'+component['filename']
        assert hashlib.sha512((destination/path).read_bytes()).hexdigest()==original[key]
        assert hashlib.sha512((source/path).read_bytes()).hexdigest()==original[key]
    assert codes.properties(destination/'config/iris.properties')['shaderPack']==selected_assets['shader']
    assert 'file/'+selected_assets['resourcepack'] in (destination/'options.txt').read_text()
    counts={kind:sum(c['kind']==kind for c in decoded['components']) for kind in codes.FOLDERS}
    assert counts['mod']>=2 and counts['resourcepack']==counts['shader']==1
    print('PASS: real Modrinth source -> code -> clean instance; counts',counts,'code length',len(code),'exact versions/hashes, Unicode name and activation restored; source unchanged')
    print('Minecraft/Java installer routing was mocked; full game files were not downloaded for this test.')

