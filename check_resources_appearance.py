import copy
import hashlib
import io
import json
import tempfile
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch
import packs
import resource_catalog as resources
import instance_tools
import launcher
import colors


def zip_bytes(kind):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('pack.mcmeta' if kind=='resourcepack' else 'shaders/test.fsh','{}')
    return stream.getvalue()


def release(kind,blob):
    return {'id':'version','date_published':'2026-11-15','game_versions':['1.21.1'],'loaders':['iris'] if kind=='shader' else ['minecraft'],
            'files':[{'filename':kind+'.zip','url':'https://cdn.modrinth.com/test.zip','hashes':{'sha512':hashlib.sha512(blob).hexdigest()},'primary':True}]}

with patch.object(packs,'session') as factory:
    session=factory.return_value.__enter__.return_value;session.get.return_value.json.return_value={'hits':[],'total_hits':0}
    first=packs.api('search',{'query':'cache-check'});first['hits'].append('mutated')
    assert not packs.api('search',{'query':'cache-check'})['hits'] and session.get.call_count==1
    packs._api_cache.clear()


with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);item=packs.new_instance(root,'Own pack','1.21.1','0.20.1','fabric');game=root/'instances'/item['id']
    for kind in resources.KINDS:
        blob=zip_bytes(kind);version=release(kind,blob)
        class Transfer:
            def download(self,file,target):Path(target).write_bytes(blob)
            def check(self):pass
            def notify(self,*args):pass
        with patch.object(packs,'api',return_value=[version]) as api:
            result=resources.install_asset(game,{'project_id':'test'},'1.21.1',kind,Transfer())
            target=game/resources.KINDS[kind][1]/(kind+'.zip')
            assert target.read_bytes()==blob
            if kind=='shader':assert 'Iris' in result
            with patch.object(Transfer,'download',side_effect=AssertionError('Duplicate download')):
                assert 'Уже установлен' in resources.install_asset(game,{'project_id':'test'},'1.21.1',kind,Transfer())
            target.write_bytes(b'existing user content')
            try:resources.install_asset(game,{'project_id':'test'},'1.21.1',kind,Transfer())
            except ValueError as error:assert 'уже существует' in str(error)
            else:raise AssertionError('Overwrote an existing file')
            assert target.read_bytes()==b'existing user content'
        incompatible=copy.deepcopy(version);incompatible['game_versions']=['1.20.1']
        with patch.object(packs,'api',return_value=[incompatible]):
            try:resources.install_asset(game,{'project_id':'test'},'1.21.1',kind,Transfer())
            except ValueError as error:assert 'совместимого' in str(error)
            else:raise AssertionError('Accepted incompatible ZIP')
    mods=game/'mods';mods.mkdir()
    with zipfile.ZipFile(mods/'iris.jar','w') as archive:archive.writestr('fabric.mod.json',json.dumps({'id':'iris'}))
    assert resources.shader_engines(game)=={'iris'} and not resources.shader_notice(game,['iris'])
    assert 'optifine' in resources.shader_notice(game,['optifine'])
    with patch.object(packs,'api',return_value={'hits':[],'total_hits':0}) as api:
        packs.search('', '1.21.1',None,'resourcepack',6,with_total=True)
        facets=json.loads(api.call_args.args[1]['facets']);assert ['project_type:resourcepack'] in facets and not any('categories:' in f for row in facets for f in row)
    launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    downloaded=packs.new_instance(root,'Downloaded pack','1.21.1','0.20.1','fabric');downloaded['source']='modrinth';instance_tools.write_json(root/'instances'/downloaded['id']/'.chunk.json',downloaded)
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'),patch.object(launcher.Launcher,'load_pack_cover'):
        app=launcher.Launcher();app.catalog_loaded=True;app.update()
        assert 'Друзья' not in app.pages and len(app.target_menus)==3
        assert {'Главная','Моды','Сборки','Ресурспаки','Шейдеры','Аккаунты','Настройки'}==set(app.pages)
        app.choose_instance(app.instance_label(downloaded));assert app.active_id==downloaded['id']
        for menu in app.target_menus:assert app.instance_label(item) in menu.cget('values') and app.instance_label(downloaded) in menu.cget('values')
        hits=[dict(project_id='project',title='Resource',description='Описание',author='Author',downloads=42,follows=3)]
        for kind,view in app.resource_catalogs.items():
            view.result(view.generation,hits,17,6,'1.21.1',None,'')
            assert view.page_label.cget('text')=='Стр. 2 из 3'
            view.result(view.generation-1,[],0,0,'1.21.1',None,'stale');assert view.hits
            for size in ('1060x720','1420x900'):
                app.geometry(size);app.show(view.title);app.after(250,app.quit);app.mainloop()
                assert view.query.winfo_width()>100 and view.cards.winfo_height()>100
        for palette in colors.PRESET_NAMES:
            app.change_color(palette);assert json.loads(launcher.CONFIG.read_text('utf-8'))['color']==palette
            value=app.play.cget('fg_color');assert (value[-1] if isinstance(value,(list,tuple)) else value)==colors.PALETTES[palette][0]
        options={'custom':{'accent':'#ffaa22','buttons':'#ffffff','selection':'#44bbff','panels':'#ffffff'},'radius':16,'density':'Компактные','style':'Мягкий','opacity':.95}
        app.appearance_panel.commit(options,True);app.appearance_panel.sync();app.update()
        assert app.play.cget('fg_color')=='#ffffff'
        assert app.play.cget('text_color')=='#111318' and app.play.cget('corner_radius')==16
        sample=launcher.ct.CTkLabel(app.pages['Настройки'],text='Contrast');sample.pack();app.update()
        assert colors.contrast(sample.cget('text_color'),sample.master.cget('fg_color'))>=4.5
        saved=json.loads(launcher.CONFIG.read_text('utf-8'));assert saved['appearance']==colors.profile
        app.close()
        # Recreate using saved settings, exercising constructor theming as well as runtime changes.
        code="import sys;from pathlib import Path;from unittest.mock import patch;import launcher,colors;launcher.ROOT=Path(sys.argv[1]);launcher.CONFIG=launcher.ROOT/'settings.json'\nwith patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'):\n app=launcher.Launcher();app.catalog_loaded=True;app.update();assert colors.profile['custom']['panels']=='#ffffff' and app.play.cget('corner_radius')==16;app.appearance_panel.reset();assert colors.profile['custom']=={} and colors.profile['radius'] is None;app.close()"
        subprocess.run([sys.executable,'-c',code,str(root)],cwd=Path(__file__).parent,check=True)
print('PASS: ZIP destinations/bytes, duplicate and overwrite protection, version compatibility, shader warning, official facets, own/Modrinth target selectors, pagination/stale results, navigation at two sizes, 10 themes, custom contrast/radius/density and persisted restart/reset')

