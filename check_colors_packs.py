import json,tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import launcher,colors,packs

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);launcher.ROOT=root;launcher.CONFIG=root/'settings.json'
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'):
        app=launcher.Launcher();app.catalog_loaded=True;app.update()
        for name,(accent,hover) in colors.PALETTES.items():
            app.change_color(name);app.update()
            value=app.play.cget('fg_color');assert (value[-1] if isinstance(value,(list,tuple)) else value)==accent,(name,value,accent)
            assert json.loads(launcher.CONFIG.read_text('utf-8'))['color']==name
            button=launcher.ct.CTkButton(app.pages['Настройки'],text='New');button.pack();app.update()
            value=button.cget('fg_color');assert (value[-1] if isinstance(value,(list,tuple)) else value)==accent,(name,value)
            if name=='Белый':assert button.cget('text_color')=='#111318'
            button.destroy()
        item=packs.new_instance(root,'Тест','1.21.4',loader_type='fabric')
        image=root/'input.png';Image.new('RGB',(100,80),'red').save(image)
        packs.update_presentation(root,item,'Моё описание',image)
        restored=next(x for x in packs.list_instances(root) if x['id']==item['id'])
        assert restored['description']=='Моё описание' and restored['loader_type']=='fabric'
        with Image.open(root/'instances'/item['id']/restored['cover']) as picture:assert picture.size==(640,360)
        app.refresh_instances();app.render_pack_results([{'title':'Pack','description':'Описание','project_id':'test','downloads':0}], '1.21.4')
        packs.update_presentation(root,restored,'Новое описание',remove=True)
        restored=next(x for x in packs.list_instances(root) if x['id']==item['id'])
        assert 'cover' not in restored
        app.close()
        colors.select(json.loads(launcher.CONFIG.read_text('utf-8'))['color']);assert colors.current=='Красный'
print('PASS: seven palettes, contrast, new widgets, persistence, cover sizing/removal and pack metadata')

