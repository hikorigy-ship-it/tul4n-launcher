import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import launcher,colors,i18n
def accent(app):
    value=app.play.cget('fg_color');return value[-1] if isinstance(value,(list,tuple)) else value

with tempfile.TemporaryDirectory() as folder:
    launcher.ROOT=Path(folder);launcher.CONFIG=Path(folder)/'settings.json'
    with patch.object(launcher.Launcher,'refresh_version_catalog'),patch.object(launcher.Launcher,'queue_compatibility'):
        app=launcher.Launcher();app.update()
        app.change_color('Красная')
        assert accent(app)!=colors.PALETTES['Красная'][0]
        app.after(550,app.quit);app.mainloop()
        assert accent(app)==colors.PALETTES['Красная'][0]
        app.change_color('Синяя');app.change_color('Изумрудная');app.after(550,app.quit);app.mainloop()
        assert accent(app)==colors.PALETTES['Изумрудная'][0] and colors._transition is None
        app.change_language('English');app.update()
        assert app.play.cget('text')=='▷  Play' and 'Home' in app.nav['Главная'].cget('text')
        app.show('Моды');app.update();assert app.current_page=='Моды'
        app.mod_sort.set('По загрузкам');assert app.mod_sort.get()=='По загрузкам' and app.mod_sort._text_label.cget('text')=='Downloads'
        new=launcher.ct.CTkButton(app,text='Скачать');assert new.cget('text')=='Download';new.destroy()
        assert json.loads(launcher.CONFIG.read_text('utf-8'))['language']=='en'
        app.change_language('Русский');assert app.play.cget('text')=='▷  Играть'
        app.change_color('Красная');app.close();assert colors._transition is None
        cfg=json.loads(launcher.CONFIG.read_text('utf-8'));cfg['language']='en';launcher.CONFIG.write_text(json.dumps(cfg),'utf-8')
        app=launcher.Launcher();assert app.play.cget('text')=='▷  Play';app.close()
print('PASS: smooth color transition, rapid changes, final colors, RU/EN navigation, menu keys, new controls, persistence and close cancellation')

