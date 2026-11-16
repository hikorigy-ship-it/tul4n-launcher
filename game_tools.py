"""Official game-file verification and bounded, redacted log viewing."""
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
import customtkinter as ct
import minecraft_launcher_lib as mc
import loaders
import packs

HOSTS=('piston-meta.mojang.com','piston-data.mojang.com','launcher.mojang.com','launchermeta.mojang.com','resources.download.minecraft.net','libraries.minecraft.net','maven.fabricmc.net','maven.minecraftforge.net','maven.neoforged.net','repo.spongepowered.org','repo1.maven.org','maven.creeperhost.net')


def audit(game,item,transfer):
    from minecraft_launcher_lib._helper import parse_rule_list
    from minecraft_launcher_lib.natives import get_natives
    game=Path(game);transfer.check();version=item['version'];info=loaders.metadata(version)
    manifest=next(v for v in loaders.manifest()['versions'] if v['id']==version)
    expected={};unknown={}
    def add(relative,record):
        path=packs.safe_path(game,relative)
        if record.get('sha1') and record.get('url'):expected[str(path.relative_to(game.resolve()))]={'path':path,'sha1':record['sha1'],'url':record['url']}
    add('versions/'+version+'/'+version+'.json',manifest)
    if info.get('downloads',{}).get('client'):add('versions/'+version+'/'+version+'.jar',info['downloads']['client'])
    marker=game/'.chunk-loader-ready.json';ready={}
    if marker.exists():
        try:ready=json.loads(marker.read_text('utf-8'))
        except (ValueError,OSError):pass
    kind=item.get('loader_type','fabric');pin=item.get('loader') or (ready.get('loader') if ready.get('kind')==kind else None)
    if kind=='vanilla':pin=version
    profile_id=ready.get('id') if ready.get('kind')==kind and ready.get('minecraft',version)==version and (not item.get('loader') or ready.get('loader')==item['loader']) else None
    bootstrap=not profile_id;profiles=[info]
    if profile_id:
        try:
            profile=packs.safe_path(game,'versions/'+profile_id+'/'+profile_id+'.json')
            installed=json.loads(profile.read_text('utf-8'))
            if installed.get('inheritsFrom',version)!=version:raise ValueError('Wrong inherited version')
            if profile_id!=version:profiles.append(installed)
        except (ValueError,OSError,KeyError):bootstrap=True
    for profile in profiles:
        for library in profile.get('libraries',[]):
            if 'rules' in library and not parse_rule_list(library['rules'],{}):continue
            downloads=library.get('downloads',{})
            artifact=downloads.get('artifact',{})
            if artifact.get('path'):
                if artifact.get('sha1'):add('libraries/'+artifact['path'],artifact)
                else:unknown['libraries/'+artifact['path']]=packs.safe_path(game,'libraries/'+artifact['path'])
            elif library.get('name'):
                parts=library['name'].split(':')
                if len(parts) in (3,4):
                    group,name,release=parts[:3];classifier='-'+parts[3] if len(parts)==4 else ''
                    relative='libraries/'+group.replace('.','/')+'/'+name+'/'+release+'/'+name+'-'+release+classifier+'.jar'
                    unknown[relative]=packs.safe_path(game,relative)
            native=get_natives(library)
            record=downloads.get('classifiers',{}).get(native,{})
            if record.get('path'):add('libraries/'+record['path'],record)
        logger=profile.get('logging',{}).get('client',{}).get('file',{})
        if logger.get('id'):add('assets/log_configs/'+logger['id'],logger)
    index=info.get('assetIndex')
    if index:
        index_path=packs.safe_path(game,'assets/indexes/'+index['id']+'.json');add('assets/indexes/'+index['id']+'.json',index)
        raw=index_path.read_bytes() if index_path.is_file() else b''
        if hashlib.sha1(raw).hexdigest()!=index['sha1']:
            transfer.notify('Получаем официальный список ресурсов Minecraft…',0)
            response=loaders.get(index['url']);raw=response.content
            if hashlib.sha1(raw).hexdigest()!=index['sha1']:raise ValueError('Не совпал хеш официального списка ресурсов')
        for obj in json.loads(raw).get('objects',{}).values():
            digest=obj['hash']
            if not re.fullmatch('[0-9a-f]{40}',digest):raise ValueError('Неверный хеш ресурса Minecraft')
            add('assets/objects/'+digest[:2]+'/'+digest,{'sha1':digest,'url':'https://resources.download.minecraft.net/'+digest[:2]+'/'+digest})
    bad=[];unverified=[];total=len(expected)+len(unknown)
    for number,record in enumerate(expected.values()):
        transfer.check();path=record['path'];good=False
        if path.is_file():
            with path.open('rb') as source:good=hashlib.file_digest(source,'sha1').hexdigest()==record['sha1']
        if not good:bad.append(record)
        if number%50==0:transfer.notify(f'Проверка: {number+1}/{total} • '+path.name,(number+1)/max(1,total))
    for relative,path in unknown.items():
        transfer.check();good=path.is_file()
        if good:
            try:
                with zipfile.ZipFile(path) as archive:good=archive.testzip() is None
            except (OSError,zipfile.BadZipFile):good=False
        if not good:unverified.append(path)
    return {'bad':bad,'unknown_bad':unverified,'unverified':len(unknown),'checked':total,'bootstrap':bootstrap,'pin':pin,'kind':kind}


def repair(root,game,item,transfer):
    game=Path(game);game.mkdir(parents=True,exist_ok=True);plan=audit(game,item,transfer)
    if not plan['bad'] and not plan['unknown_bad'] and not plan['bootstrap']:
        return f'Проверено файлов: {plan["checked"]}. Повреждений не найдено.'+(' Библиотек без опубликованного хеша проверено по структуре ZIP: '+str(plan['unverified']) if plan['unverified'] else '')
    with tempfile.TemporaryDirectory(prefix='.repair-',dir=game) as temporary:
        temporary=Path(temporary)
        for number,record in enumerate(plan['bad']):
            transfer.check();path=record['path'];transfer.notify(f'Восстанавливаем {number+1}/{len(plan["bad"])}: '+path.name,number/max(1,len(plan['bad'])))
            staged=temporary/(str(number)+'.download')
            transfer.download({'filename':path.name,'url':record['url'],'hashes':{'sha1':record['sha1']}},staged,allowed_hosts=HOSTS)
            transfer.check();path.parent.mkdir(parents=True,exist_ok=True);staged.replace(path)
        moved=[]
        try:
            if plan['bootstrap'] or plan['unknown_bad']:
                if not plan['pin']:raise ValueError('Неизвестна точная версия загрузчика. Выберите её на главной странице, затем повторите восстановление.')
                for number,path in enumerate(plan['unknown_bad']):
                    if path.exists():
                        saved=temporary/(str(number)+'.old');path.replace(saved);moved.append((saved,path))
                callback={'setStatus':lambda text:(transfer.check(),transfer.notify(str(text),0)),'setProgress':lambda value:transfer.check()}
                java=loaders.java_for(item['version'],item.get('java',''),runtime_root=root,callback=callback,game=game)
                loaders.install(plan['kind'],item['version'],game,java,callback,plan['pin'],cancel_event=transfer.cancelled,repair=True)
        except Exception:
            for saved,path in moved:
                if saved.exists():saved.replace(path)
            raise
    transfer.notify('Файлы Minecraft восстановлены',1)
    return f'Проверено: {plan["checked"]}. Восстановлено повреждённых/отсутствующих файлов: {len(plan["bad"])+len(plan["unknown_bad"])}.'


def log_sources(game):
    game=Path(game);sources={'Вывод запуска':game/'game.log','Журнал Minecraft':game/'logs/latest.log'}
    crashes=sorted((game/'crash-reports').glob('*.txt'),key=lambda p:p.stat().st_mtime,reverse=True)
    if crashes:sources['Последний crash-report']=crashes[0]
    return sources


def redact(text):
    text=re.sub(r'''(?i)(\b(?:access[_-]?token|refresh[_-]?token|client[_-]?token|password|authorization)\b["']?\s*[:=]\s*)(["'])(.*?)\2''',r'\1\2[скрыто]\2',text)
    text=re.sub(r'(?i)(\b(?:access[_-]?token|refresh[_-]?token|client[_-]?token|password|authorization)\b[\s"\x27:=]+)(?:Bearer\s+)?[^\s,"\x27]+',r'\1[скрыто]',text)
    return re.sub(r'(?i)(--accessToken\s+)\S+',r'\1[скрыто]',text)


def read_log(game,path):
    game=Path(game).resolve();path=Path(path).resolve()
    if not path.is_relative_to(game):raise ValueError('Журнал находится за пределами сборки')
    if not path.exists():return 'Журнал пока не создан. Запустите игру.',None
    stat=path.stat()
    with path.open('rb') as source:source.seek(max(0,stat.st_size-512*1024));text=source.read(512*1024).decode('utf-8','replace')
    return redact(text),(str(path),stat.st_mtime_ns,stat.st_size)


def errors(text):
    lines=text.splitlines();selected=set()
    for i,line in enumerate(lines):
        if re.search(r'(?i)\berror\b|\bfatal\b|exception|caused by|^\s+at\s|OutOfMemory|exit code',line):selected.update(range(max(0,i-2),min(len(lines),i+4)))
    return '\n'.join(lines[i] for i in sorted(selected)) or 'Строк с ошибками в доступной части журнала не найдено.'


class LogWindow:
    def __init__(self,app,item):
        self.app=app;self.game=app.root_path/'instances'/item['id'];self.closed=False;self.loading=False;self.job=None;self.text='';self.signature=None
        self.window=ct.CTkToplevel(app);self.window.title('Журнал • '+item['name']);self.window.geometry('940x660');self.window.transient(app)
        app.label(self.window,'Журнал запуска • '+item['name'],23)
        row=ct.CTkFrame(self.window,fg_color='transparent');row.pack(fill='x',padx=14,pady=6)
        self.source=ct.CTkOptionMenu(row,values=list(log_sources(self.game)),width=220,command=lambda _:self.refresh(True));self.source.pack(side='left',padx=(0,12))
        self.only_errors=ct.BooleanVar(value=False);ct.CTkSwitch(row,text='Только ошибки',variable=self.only_errors,command=self.render).pack(side='left',padx=8)
        self.auto=ct.BooleanVar(value=True);ct.CTkSwitch(row,text='Обновлять',variable=self.auto).pack(side='left',padx=8)
        self.box=ct.CTkTextbox(self.window,wrap='none',font=('Consolas',12));self.box.pack(fill='both',expand=True,padx=14,pady=8);self.box.configure(state='disabled')
        self.note=ct.CTkLabel(self.window,text='Показываются последние 512 КБ. Токены и пароли скрываются.');self.note.pack(pady=3)
        row=ct.CTkFrame(self.window,fg_color='transparent');row.pack(pady=8)
        ct.CTkButton(row,text='Обновить сейчас',command=lambda:self.refresh(True)).pack(side='left',padx=5)
        ct.CTkButton(row,text='Скопировать ошибки',command=lambda:self.copy(True)).pack(side='left',padx=5)
        ct.CTkButton(row,text='Скопировать журнал',command=lambda:self.copy(False)).pack(side='left',padx=5)
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.refresh(True)
    def refresh(self,force=False):
        if self.closed:return
        if self.job:self.app.after_cancel(self.job);self.job=None
        if not self.loading and (force or self.auto.get()):
            sources=log_sources(self.game)
            if list(sources)!=list(self.source.cget('values')):self.source.configure(values=list(sources))
            self.loading=True;path=sources.get(self.source.get(),self.game/'game.log')
            def job():
                try:text,signature=read_log(self.game,path)
                except Exception as error:text,signature=str(error),None
                self.app.events.put(('log_result',(self,text,signature,force)))
            self.app.media_pool.submit(job)
        self.job=self.app.after(1000,self.refresh)
    def result(self,text,signature,force):
        self.loading=False
        if self.closed:return
        if force or signature!=self.signature or text!=self.text:self.text=text;self.signature=signature;self.render()
    def render(self):
        if self.closed:return
        value=errors(self.text) if self.only_errors.get() else self.text
        self.box.configure(state='normal');self.box.delete('1.0','end');self.box.insert('1.0',value);self.box.see('end');self.box.configure(state='disabled')
    def copy(self,only_errors):
        self.app.clipboard_clear();self.app.clipboard_append(errors(self.text) if only_errors else self.text);self.note.configure(text='Скопировано. Токены и пароли скрыты.')
    def close(self):
        self.closed=True
        if self.job:self.app.after_cancel(self.job)
        if self.window.winfo_exists():self.window.destroy()

