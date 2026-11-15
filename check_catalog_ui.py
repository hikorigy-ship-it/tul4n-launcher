import json,tempfile
from pathlib import Path
from unittest.mock import patch
import launcher,packs,loaders

hits=[{'project_id':str(i),'title':'Mod '+str(i),'description':'Описание мода','downloads':1000,'author':'Author','categories':['magic']} for i in range(6)]
with patch.object(packs,'api',return_value={'hits':hits,'total_hits':17}) as api:
    result,notice,total=packs.search('', '1.21.4','fabric',limit=6,offset=6,category='magic',order='downloads',with_total=True)
    params=api.call_args.args[1]
    assert params['offset']==6 and params['index']=='downloads'
    assert ['categories:magic'] in json.loads(params['facets']) and total==17

with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    item=packs.new_instance(root,'Test pack','1.21.4','0.20.1','fabric')
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'),patch.object(launcher.Launcher,'load_card_media'):
        app=launcher.Launcher();app.catalog_loaded=True;app.active_id=item['id'];app.refresh_instances();app.update()
        app.render_mods((hits,'1.21.4','fabric'));app.update()
        assert len(app.mod_widgets)==6 and not app.remaining_mods
        app.update_pages('mod',17,6)
        assert app.mod_page_controls[1].cget('text')=='Стр. 2 из 3'
        with patch.object(app,'start_search') as start:
            app.change_page('mod',1);assert app.mod_offset==12;start.assert_called_once_with(False)
        folder=root/'instances'/item['id']/'mods';folder.mkdir();(folder/'test.jar').touch()
        app.mod_tabs.set('Установленные');app.show_installed_mods();assert app.installed_modlist.winfo_children()
        app.render_pack_results(hits,'1.21.4','fabric');assert len(app.pack_results.winfo_children())==6
        app.show('Моды');app.update();assert app.search.winfo_width()>150
        app.close()
print('PASS: category/sort API parameters, six compact rows, real pagination, installed mods and pack cards')

