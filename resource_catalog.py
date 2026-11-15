"""Shared Modrinth resourcepack/shader catalogue and non-destructive ZIP installs."""
import hashlib
import json
import math
import os
import tempfile
import threading
import zipfile
from pathlib import Path
import customtkinter as ct
import packs

KINDS={'resourcepack':('Ресурспаки','resourcepacks'),'shader':('Шейдеры','shaderpacks')}
ORDERS={'По популярности':'follows','По загрузкам':'downloads','По обновлению':'updated','Сначала новые':'newest','По релевантности':'relevance'}


def shader_engines(game):
    result=set()
    for path in (Path(game)/'mods').glob('*.jar'):
        try:
            with zipfile.ZipFile(path) as archive:
                if 'fabric.mod.json' in archive.namelist():
                    if json.loads(archive.read('fabric.mod.json')).get('id') in ('iris','oculus'):result.add('iris')
                for name in ('META-INF/neoforge.mods.toml','META-INF/mods.toml'):
                    if name in archive.namelist():
                        import tomllib
                        if any(m.get('modId') in ('iris','oculus') for m in tomllib.loads(archive.read(name).decode()).get('mods',[])):result.add('iris')
                if any(n in archive.namelist() for n in ('net/optifine/Config.class','optifine/Config.class','optifine/OptiFineClassTransformer.class')):result.add('optifine')
        except (OSError,ValueError,zipfile.BadZipFile):continue
    return result


def shader_notice(game,loaders):
    engines=shader_engines(game);supported=set(loaders)&{'iris','optifine'}
    if not engines:return 'Для использования шейдера установите совместимый Iris или OptiFine. ZIP скачан успешно.'
    if supported and not supported&engines:return 'ZIP скачан. Для этого шейдера нужен '+', '.join(sorted(supported))+', обнаружен '+', '.join(sorted(engines))+'.'
    return ''


def install_asset(game,project,version,kind,transfer,engine=None,release_id=None):
    if kind not in KINDS:raise ValueError('Неверный тип ресурса')
    game=Path(game);game.mkdir(parents=True,exist_ok=True)
    params={'game_versions':json.dumps([version])}
    if kind=='shader' and engine:params['loaders']=json.dumps([engine])
    versions=[packs.api('version/'+release_id)] if release_id else packs.api('project/'+project['project_id']+'/version',params)
    versions=[v for v in versions if version in v.get('game_versions',[]) and (not release_id or v.get('project_id')==project['project_id']) and (not engine or engine in v.get('loaders',[]))]
    if not versions:raise ValueError('Нет совместимого ZIP для Minecraft '+version+(' • '+engine if engine else ''))
    release=max(versions,key=lambda v:v['date_published'])
    files=[f for f in release['files'] if f['filename'].lower().endswith('.zip')]
    if not files:raise ValueError('Для этой версии нет ZIP-файла')
    file=next((f for f in files if f.get('primary')),files[0]);name=file['filename']
    if Path(name).name!=name or '\\' in name or ':' in name:raise ValueError('Недопустимое имя ZIP')
    folder=packs.safe_path(game,KINDS[kind][1]);folder.mkdir(parents=True,exist_ok=True)
    target=packs.safe_path(folder,name)
    hashes=file.get('hashes',{});algorithm=next((a for a in ('sha512','sha1') if hashes.get(a)),None)
    if not algorithm:raise ValueError('Modrinth не предоставил контрольную сумму файла')
    if target.exists():
        if target.is_file():
            with target.open('rb') as stream:checksum=hashlib.file_digest(stream,algorithm).hexdigest()
            if checksum==hashes[algorithm].lower():return 'Уже установлен: '+name+(' • '+shader_notice(game,release.get('loaders',[])) if kind=='shader' else '')
        raise ValueError('Файл '+name+' уже существует и отличается. Он сохранён без изменений.')
    with tempfile.TemporaryDirectory(prefix='.tul4n-download-',dir=folder) as temporary:
        staged=Path(temporary)/name;transfer.download(file,staged);transfer.check()
        with zipfile.ZipFile(staged) as archive:
            names=archive.namelist()
            if kind=='resourcepack' and 'pack.mcmeta' not in names:raise ValueError('В ZIP нет pack.mcmeta; файл не установлен')
            if kind=='shader' and not any(p.startswith('shaders/') for p in names):raise ValueError('В ZIP нет папки shaders; файл не установлен')
        # Windows rename never replaces an existing destination, including a race with another installer.
        if os.name=='nt':os.rename(staged,target)
        else:os.link(staged,target)
    notice=shader_notice(game,release.get('loaders',[])) if kind=='shader' else ''
    transfer.notify('Установлен: '+name,1)
    return 'Установлен: '+name+(' • '+notice if notice else '')


class ResourceCatalog:
    def __init__(self,app,kind):
        self.app=app;self.kind=kind;self.title,self.directory=KINDS[kind]
        self.generation=0;self.offset=0;self.total=0;self.loading=False;self.loaded=False;self.timer=None;self.target_id=None;self.hits=[];self.context=None;self.animation_jobs=[]
        page=app.pages[self.title];app.catalog_header(page,self.title.upper(),'Modrinth • поиск и установка в выбранную сборку')
        app.target_selector(page)
        self.target=ct.CTkLabel(page,text='',anchor='w',text_color='#9ab7a7',wraplength=780);self.target.pack(fill='x',pady=(8,4))
        controls=ct.CTkFrame(page,fg_color='transparent');controls.pack(fill='x',pady=4)
        ct.CTkLabel(controls,text='Minecraft:').pack(side='left',padx=(0,6))
        self.version=ct.CTkOptionMenu(controls,values=app.minecraft_menu.cget('values'),width=125,command=lambda _:self.search());self.version.set(app.version.get());self.version.pack(side='left',padx=(0,8))
        self.engine=None
        if kind=='shader':
            self.engine=ct.CTkOptionMenu(controls,values=['Любой','Iris','OptiFine'],width=110,command=lambda _:self.search());self.engine.pack(side='left',padx=(0,8))
        ct.CTkButton(controls,text='Открыть папку',width=135,height=30,command=self.open_folder).pack(side='right')
        if kind=='shader':ct.CTkButton(controls,text='Установить Iris',width=140,height=30,command=app.install_iris).pack(side='right',padx=6)
        maintenance=ct.CTkFrame(page,fg_color='transparent');maintenance.pack(fill='x',pady=3)
        ct.CTkButton(maintenance,text='Обновить установленные',width=200,height=28,command=lambda:self.maintain(False)).pack(side='left',padx=(0,8))
        ct.CTkButton(maintenance,text='Вернуть предыдущую версию',width=225,height=28,fg_color='#344f40',command=lambda:self.maintain(True)).pack(side='left')
        row=ct.CTkFrame(page,fg_color='transparent');row.pack(fill='x',pady=4)
        self.query=ct.CTkEntry(row,placeholder_text='Название ресурспака…' if kind=='resourcepack' else 'Название шейдера…',height=34);self.query.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.sort=ct.CTkOptionMenu(row,values=list(ORDERS),width=150,command=lambda _:self.search());self.sort.set('По загрузкам');self.sort.pack(side='left',padx=(0,8))
        self.button=ct.CTkButton(row,text='Найти',width=80,height=34,command=self.search);self.button.pack(side='left')
        self.query.bind('<Return>',lambda _:self.search());self.query.bind('<KeyRelease>',self.queue_search)
        self.note=ct.CTkLabel(page,text='Введите название или найдите популярные проекты.',anchor='w',wraplength=800,text_color='#9ab7a7');self.note.pack(fill='x',pady=4)
        self.progress=ct.CTkProgressBar(page,height=3,mode='determinate');self.progress.pack(fill='x');self.progress.set(0)
        footer=ct.CTkFrame(page,fg_color='transparent');footer.pack(side='bottom',fill='x',pady=5)
        self.next=ct.CTkButton(footer,text='Далее ▸',width=94,height=30,state='disabled',command=lambda:self.change_page(1));self.next.pack(side='right')
        self.page_label=ct.CTkLabel(footer,text='Стр. 1 из 1',width=120);self.page_label.pack(side='right')
        self.previous=ct.CTkButton(footer,text='◂ Назад',width=94,height=30,state='disabled',command=lambda:self.change_page(-1));self.previous.pack(side='right')
        self.cancel=ct.CTkButton(footer,text='Отменить загрузку',width=160,height=30,state='disabled',command=app.cancel_transfer);self.cancel.pack(side='left')
        self.cards=ct.CTkScrollableFrame(page,fg_color='#111515',corner_radius=0);self.cards.pack(fill='both',expand=True,pady=5)
    def sync_target(self):
        item=self.app.active_instance();changed=self.target_id!=item['id'];self.target_id=item['id']
        self.target.configure(text='Сборка: '+item['name']+' • Minecraft '+item['version']+' → '+self.directory)
        if changed:
            self.version.set(item['version']);self.generation+=1;self.loading=False;self.loaded=False
            self.button.configure(state='normal',text='Найти');self.progress.stop();self.progress.set(0)
            self.render([]);self.note.configure(text='Сборка изменена. Нажмите «Найти», чтобы обновить каталог.')
    def queue_search(self,event):
        if event.keysym in ('Return','Tab','Shift_L','Shift_R','Control_L','Control_R','Left','Right','Up','Down','Escape'):return
        if self.timer:self.app.after_cancel(self.timer)
        self.generation+=1;self.timer=self.app.after(500,self.search)
    def search(self,reset=True):
        if self.timer:self.app.after_cancel(self.timer);self.timer=None
        if reset:self.offset=0
        self.generation+=1;generation=self.generation;self.loading=True
        version=self.version.get();query=self.query.get().strip();engine=self.engine.get().lower() if self.engine and self.engine.get()!='Любой' else None
        order=ORDERS[self.sort.get()];offset=self.offset
        self.context=(version,engine);self.button.configure(state='disabled',text='Поиск…');self.note.configure(text='Ищем на Modrinth…');self.progress.configure(mode='indeterminate');self.progress.start()
        self.previous.configure(state='disabled');self.next.configure(state='disabled')
        def job():
            try:
                hits,_,total=packs.search(query,version,engine,self.kind,6,offset,order=order,with_total=True)
                self.app.events.put(('resource_result',(self.kind,generation,hits,total,offset,version,engine,'')))
            except Exception as error:self.app.events.put(('resource_result',(self.kind,generation,[],0,offset,version,engine,'Modrinth недоступен: '+str(error)[:180])))
        threading.Thread(target=job,daemon=True).start()
    def result(self,generation,hits,total,offset,version,engine,error):
        if generation!=self.generation:return
        self.loading=False;self.loaded=not bool(error);self.button.configure(state='normal',text='Найти');self.progress.stop();self.progress.configure(mode='determinate');self.progress.set(0)
        self.total=total;self.offset=offset;self.context=(version,engine);self.render(hits)
        self.note.configure(text=error or (f'Найдено: {total:,} • Minecraft {version}' if hits else 'Ничего не найдено. Измените название или версию Minecraft.'))
        self.page_label.configure(text=f'Стр. {offset//6+1} из {max(1,math.ceil(total/6))}')
        self.previous.configure(state='normal' if offset else 'disabled');self.next.configure(state='normal' if offset+6<total else 'disabled')
    def change_page(self,direction):
        if self.loading:return
        offset=self.offset+6*direction
        if not 0<=offset<self.total:return
        self.offset=offset;self.search(False)
    def render(self,hits):
        self.hits=list(hits)
        for job in self.animation_jobs:
            try:self.app.after_cancel(job)
            except Exception:pass
        self.animation_jobs=[]
        for widget in self.cards.winfo_children():widget.destroy()
        compact=self.app.cfg.get('appearance',{}).get('density','Стандартные')=='Компактные'
        for i,item in enumerate(hits):
            item=dict(item,_catalog_type=self.kind)
            card=ct.CTkFrame(self.cards,fg_color='#202425',border_width=1,border_color='#3b4242',corner_radius=0)
            body=ct.CTkFrame(card,fg_color='transparent');body.pack(fill='x',padx=10,pady=5 if compact else 10)
            self.app.pack_cover(body,item)
            actions=ct.CTkFrame(body,fg_color='transparent');actions.pack(side='right',padx=(8,0))
            version,engine=self.context
            ct.CTkButton(actions,text='Скачать',width=100,height=28,command=lambda m=item,v=version,e=engine:self.start_install(m,v,e)).pack()
            ct.CTkButton(actions,text='Подробнее',width=100,height=28,fg_color='#344f40',command=lambda m=item,v=version:self.app.open_details(m,v)).pack()
            self.app.favorite_button(actions,item,self.kind)
            copy=ct.CTkFrame(body,fg_color='transparent');copy.pack(side='left',fill='both',expand=True)
            ct.CTkLabel(copy,text=item['title']+'  от '+item.get('author','—'),font=('Segoe UI',14,'bold'),wraplength=450,justify='left').pack(anchor='w')
            text=item.get('description','');limit=110 if compact else 240
            ct.CTkLabel(copy,text=text[:limit]+('…' if len(text)>limit else ''),wraplength=450,justify='left',text_color='#c2ceca').pack(anchor='w')
            followers=item.get('follows');stats=f'↓ {item.get("downloads",0):,}'+(f' • ♥ {followers:,}' if isinstance(followers,int) else '')
            ct.CTkLabel(copy,text=stats,font=('Segoe UI',10),text_color='#929d97').pack(anchor='w')
            def reveal(card=card):
                if card.winfo_exists():card.pack(fill='x',pady=4)
            self.animation_jobs.append(self.app.after(i*25,reveal))
    def start_install(self,project,version,engine=None):
        item=dict(self.app.active_instance())
        if item['version']!=version:self.note.configure(text='Выберите сборку Minecraft '+version+' перед установкой.');return
        if self.app.busy or self.app.game_running:self.note.configure(text='Сначала закройте игру и дождитесь текущей загрузки.');return
        self.app.asset_operation=self.kind;self.cancel.configure(state='normal')
        self.note.configure(text='Проверяем совместимость и скачиваем ZIP…')
        folder=self.app.root_path/'instances'/item['id']
        def job():
            result=install_asset(folder,project,version,self.kind,self.app.transfer,engine)
            self.app.events.put(('resource_installed',(self.kind,result)))
        self.app.work(job,True)
    def open_folder(self):
        folder=packs.safe_path(self.app.root_path/'instances'/self.app.active_instance()['id'],self.directory);folder.mkdir(parents=True,exist_ok=True);os.startfile(folder)
    def maintain(self,rollback):
        import content_updates
        if self.app.busy or self.app.game_running:self.note.configure(text='Сначала закройте игру и дождитесь текущей операции.');return
        item=dict(self.app.active_instance());folder=self.app.root_path/'instances'/item['id']
        self.app.asset_operation=self.kind;self.cancel.configure(state='normal');self.note.configure(text='Проверяем установленные ZIP…')
        def job():
            text=(content_updates.rollback if rollback else content_updates.update)(folder,item,self.kind,self.app.transfer)
            self.app.events.put(('resource_installed',(self.kind,text)))
        self.app.work(job,True)
    def close(self):
        self.generation+=1
        for job in ([self.timer] if self.timer else [])+self.animation_jobs:
            try:self.app.after_cancel(job)
            except Exception:pass

