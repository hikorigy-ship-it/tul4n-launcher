"""Focused routing/compatibility checks; no game or Java downloads."""
import io,json,tempfile,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
import loaders,packs,launcher

def response(value=None,content=b''):
    return Mock(json=lambda:value,content=content)

with patch.object(loaders,'manifest',return_value={'versions':[{'id':'1.21.1','type':'release'},{'id':'26.1','type':'release'}]}), patch.object(loaders,'forge_versions',return_value=['1.21.1-52.0.2','1.21.1-52.1.21']), patch.object(loaders,'neoforge_versions',return_value=['26.1.2.126','26.1.0.19-beta','21.1.266']):
    loaders.loader_versions.cache_clear()
    assert loaders.loader_versions('forge','1.21.1')[0]=='1.21.1-52.1.21'
    assert loaders.loader_versions('neoforge','26.1')==['26.1.0.19-beta']
    assert loaders.neo_minecraft('26.1.2.126')=='26.1.2'
    assert loaders.neo_minecraft('21.11.48')=='1.21.11'
loaders.loader_versions.cache_clear()

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)
    def fake_install(version,game,**kwargs):
        folder=Path(game)/'versions'/version;folder.mkdir(parents=True,exist_ok=True)
        (folder/(version+'.json')).write_text(json.dumps({'id':version,'inheritsFrom':'1.21.1'}))
    for kind,release in [('vanilla','1.21.1'),('fabric','0.20.1'),('forge','1.21.1-52.1.21'),('neoforge','21.1.266')]:
        game=root/kind
        profile={'id':'fabric-loader-0.20.1-1.21.1','inheritsFrom':'1.21.1'}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('install_profile.json',json.dumps({'minecraft':'1.21.1','version':'neoforge-21.1.266'}))
        with patch.object(loaders,'loader_versions',return_value=[release]), patch.object(loaders,'get',return_value=response(profile,buffer.getvalue())), patch.object(loaders.mc.install,'install_minecraft_version',side_effect=fake_install) as vanilla, patch.object(loaders.mc.forge,'install_forge_version',side_effect=lambda version,path,**kw:fake_install(loaders.mc.forge.forge_to_installed_version(version),path)) as forge, patch.object(loaders.subprocess,'call',return_value=0) as cli:
            installed=loaders.install(kind,'1.21.1',game,'chosen-java',{},release)
            assert (game/'versions'/installed/(installed+'.json')).exists()
            if kind=='forge':assert forge.call_args.args[0]==release and forge.call_args.kwargs['java']=='chosen-java'
            if kind=='neoforge':assert cli.call_args.args[0][0]=='chosen-java' and '--installClient' in cli.call_args.args[0]
            if kind=='vanilla':assert vanilla.call_args.args[0]=='1.21.1'
        with patch.object(loaders,'loader_versions',side_effect=AssertionError('Offline launch queried server')):
            pin=release.split('-',1)[1] if kind=='forge' else release
            assert loaders.install(kind,'1.21.1',game,'chosen-java',{},pin)==installed
    with patch.object(loaders,'metadata',return_value={'javaVersion':{'majorVersion':17}}),patch.object(loaders,'java_major',return_value=21):
        try:loaders.java_for('1.20.1','wrong-java')
        except ValueError:pass
        else:raise AssertionError('Wrong Java accepted')

    launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    catalog={'vanilla':['1.20.1'],'fabric':['0.20.1'],'forge':['1.20.1-47.4.29','1.20.1-47.4.28']}
    loaders.COMPATIBILITY['1.20.1']=catalog
    def compatibility(app,version,scope='home'):
        app.compat_requests[scope]=app.compat_requests.get(scope,0)+1
        app.apply_compatibility(scope,app.compat_requests[scope],version,catalog,[])
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility',compatibility):
        app=launcher.Launcher();app.catalog_loaded=True;app.update()
        app.choose_base('1.20.1');app.choose_loader('Forge')
        assert app.active_instance()['version']=='1.20.1'
        app.choose_loader_release('1.20.1-47.4.28')
        first=app.active_instance()['id']
        assert app.active_instance()['loader']=='1.20.1-47.4.28'
        app.choose_loader_release('1.20.1-47.4.29')
        assert app.active_instance()['id']!=first
        app.nick.set('OfflineUser');app.accounts=['OfflineUser']
        with patch.object(app,'work'):
            app.begin_launch()
        assert app.launch_context[1]['version']=='1.20.1' and app.launch_context[1]['loader']=='1.20.1-47.4.29'
        app.choose_loader('Vanilla');assert app.active_instance()['loader_type']=='vanilla'
        assert 'NeoForge' not in app.loader_menu.cget('values')
        app.close()
print('PASS: four installer routes, exact versions/Java, offline reuse, NeoForge mapping, UI selection and isolated loader versions')

