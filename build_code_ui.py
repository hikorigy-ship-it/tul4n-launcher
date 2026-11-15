"""Export selection, self-contained code sharing, and reviewed imports with retry."""
import copy
import json
import os
import threading
from pathlib import Path
from tkinter import filedialog
import customtkinter as ct
import build_codes
from instance_tools import Cancelled


class BuildCodeUI:
    def __init__(self,app):self.app=app;self.imports=[]
    def section(self,parent):
        self.app.label(parent,'Импорт по коду TUL4N',25)
        self.app.label(parent,'Вставьте полный код. Он содержит состав сборки, а не JAR/ZIP-файлы.\nMinecraft, загрузчик и точные файлы будут скачаны автоматически.',13)
        self.input=ct.CTkTextbox(parent,wrap='char',height=230);self.input.pack(fill='both',expand=True,padx=8,pady=8)
        row=ct.CTkFrame(parent,fg_color='transparent');row.pack(fill='x',padx=8,pady=6)
        ct.CTkButton(row,text='Импортировать и установить',width=230,command=self.begin_import).pack(side='left',padx=(0,8))
        def open_file():
            path=filedialog.askopenfilename(parent=self.app,title='Открыть код сборки',filetypes=[('Код TUL4N','*.tul4ncode *.txt')])
            if not path:return
            try:
                if Path(path).stat().st_size>build_codes.MAX_CODE:raise ValueError('Файл кода слишком большой')
                self.input.delete('1.0','end');self.input.insert('1.0',Path(path).read_text('utf-8-sig'))
            except Exception as error:self.app.pack_status.configure(text=str(error))
        ct.CTkButton(row,text='Открыть файл кода',width=180,fg_color='#344f40',command=open_file).pack(side='left')
    def export(self,item):
        if self.app.busy or self.app.game_running:self.app.pack_status.configure(text='Сначала закройте игру и дождитесь текущей операции.');return
        item=dict(item);game=self.app.root_path/'instances'/item['id']
        try:rows,_,_=build_codes.scan(game)
        except Exception as error:self.app.pack_status.configure(text=str(error));return
        window=ct.CTkToplevel(self.app);window.title('Экспорт • '+item['name']);window.geometry('730x680');window.transient(self.app)
        self.app.label(window,item['name'],25);self.app.label(window,item.get('loader_type','fabric').title()+' • Minecraft '+item['version'],13)
        self.app.label(window,'Выберите файлы. Неизвестные Modrinth файлы нужно исключить.\nМиры, кэш, логи, аккаунты и личные настройки не экспортируются.',12)
        panel=ct.CTkScrollableFrame(window);panel.pack(fill='both',expand=True,padx=12,pady=8);choices=[]
        labels={'mod':'Мод','resourcepack':'Ресурспак','shader':'Шейдер'}
        for row in rows:
            selected=ct.BooleanVar(value=row['default']);choices.append((row,selected))
            state='активен' if row['active'] else 'не активен'
            ct.CTkCheckBox(panel,text=labels[row['kind']]+' • '+row['filename']+' • '+state,variable=selected).pack(anchor='w',padx=8,pady=6)
        if not rows:ct.CTkLabel(panel,text='Дополнительных файлов нет. Будут сохранены Minecraft и загрузчик.').pack(pady=20)
        note=ct.CTkLabel(window,text='Каждый экспорт создаёт новый независимый снимок.',wraplength=680);note.pack(pady=4)
        button=ct.CTkButton(window,text='Создать код');button.pack(pady=8)
        def generate():
            if self.app.busy or self.app.game_running:note.configure(text='Сначала завершите текущую операцию.');return
            selection=[(r['kind'],r['filename']) for r,v in choices if v.get()];button.configure(state='disabled');note.configure(text='Проверяем точные файлы на Modrinth…')
            def job():
                original=self.app.transfer.notify
                def notice(text,value):
                    original(text,value)
                    self.app.events.put(('code_ui',lambda text=text:note.configure(text=text) if window.winfo_exists() else None))
                self.app.transfer.notify=notice
                try:
                    data,code=build_codes.export(game,item,selection,self.app.transfer)
                    self.app.events.put(('code_ui',lambda:self.exported(window,note,button,data,code)))
                except Exception as error:
                    text=str(error)
                    def failed():
                        if window.winfo_exists():note.configure(text=text);button.configure(state='normal')
                    self.app.events.put(('code_ui',failed))
                finally:self.app.transfer.notify=original
            self.app.work(job,True)
        button.configure(command=generate)
    def exported(self,selection,note,button,data,code):
        if selection.winfo_exists():selection.destroy()
        window=ct.CTkToplevel(self.app);window.title('Код сборки • '+data['name']);window.geometry('780x600');window.transient(self.app)
        self.app.label(window,data['name'],26)
        counts={kind:sum(c['kind']==kind for c in data['components']) for kind in build_codes.FOLDERS}
        self.app.label(window,f'Minecraft {data["minecraft"]} • {data["loader"]["type"].title()} {data["loader"]["version"]}\nМодов: {counts["mod"]} • ресурспаков: {counts["resourcepack"]} • шейдеров: {counts["shader"]}',14)
        box=ct.CTkTextbox(window,wrap='char');box.pack(fill='both',expand=True,padx=14,pady=8);box.insert('1.0',code);box.configure(state='disabled')
        status=ct.CTkLabel(window,text='Код создан. Старые коды останутся неизменными.',wraplength=720);status.pack(pady=6)
        row=ct.CTkFrame(window,fg_color='transparent');row.pack(pady=12)
        def copy_code():
            self.app.clipboard_clear();self.app.clipboard_append(code);status.configure(text='Код скопирован без изменений.')
        def save():
            path=filedialog.asksaveasfilename(parent=window,title='Сохранить код',defaultextension='.tul4ncode',filetypes=[('Код TUL4N','*.tul4ncode')])
            if path:
                try:Path(path).write_text(code,'utf-8');status.configure(text='Код сохранён: '+Path(path).name)
                except OSError as error:status.configure(text=str(error))
        def share():
            copy_code();status.configure(text='Код скопирован. Вставьте его другу в выбранном мессенджере; для длинного кода можно отправить файл .tul4ncode.')
        ct.CTkButton(row,text='Скопировать код',width=175,command=copy_code).pack(side='left',padx=5)
        ct.CTkButton(row,text='Сохранить код в файл',width=185,command=save).pack(side='left',padx=5)
        ct.CTkButton(row,text='Поделиться кодом',width=175,command=share).pack(side='left',padx=5)
    def begin_import(self):
        if self.app.busy or self.app.game_running:self.app.pack_status.configure(text='Сначала закройте игру и дождитесь текущей операции.');return
        try:data=build_codes.decode(self.input.get('1.0','end'))
        except Exception as error:self.app.pack_status.configure(text=str(error));return
        view=ImportView(self,data);self.imports.append(view);view.prepare()
    def close(self):
        for view in self.imports:view.close()
    def cancel_running(self):
        active=[view for view in self.imports if view.running]
        if active and self.app.transfer:self.app.transfer.cancelled.set()
        return bool(active)


class ImportView:
    def __init__(self,owner,data):
        self.owner=owner;self.app=owner.app;self.data=data;self.session=None;self.running=False;self.closed=False;self.ready=False;self.transfer=None
        self.window=ct.CTkToplevel(self.app);self.window.title('Импорт • '+data['name']);self.window.geometry('760x660');self.window.transient(self.app)
        self.app.label(self.window,'Импорт сборки',26)
        self.name=ct.CTkEntry(self.window);self.name.insert(0,data['name']);self.name.pack(fill='x',padx=16,pady=5)
        duplicate=any(i['name']==data['name'] for i in self.app.instances)
        self.choice=ct.CTkOptionMenu(self.window,values=['Создать отдельную копию','Указать другое название'],width=270);self.choice.set('Создать отдельную копию');self.choice.pack(anchor='w',padx=16,pady=5)
        ct.CTkLabel(self.window,text=('Такое название уже есть. ' if duplicate else '')+'Существующие сборки останутся без изменений.',wraplength=700).pack(anchor='w',padx=16)
        self.summary=ct.CTkLabel(self.window,text=f'Minecraft {data["minecraft"]} • {data["loader"]["type"].title()} {data["loader"]["version"]} • файлов: {len(data["components"])}',wraplength=700);self.summary.pack(anchor='w',padx=16,pady=8)
        self.phase=ct.CTkLabel(self.window,text='Проверяем манифест и доступность точных версий…',wraplength=700,justify='left');self.phase.pack(fill='x',padx=16,pady=6)
        self.bar=ct.CTkProgressBar(self.window,mode='indeterminate');self.bar.pack(fill='x',padx=16,pady=6);self.bar.start()
        self.count=ct.CTkLabel(self.window,text='0% • файлов: 0 • осталось: '+str(len(data['components'])));self.count.pack(anchor='w',padx=16)
        self.stages=ct.CTkLabel(self.window,text='Minecraft: ожидание\nЗагрузчик: ожидание\nМоды: ожидание\nРесурспаки: ожидание\nШейдеры: ожидание',justify='left');self.stages.pack(anchor='w',padx=16,pady=12)
        row=ct.CTkFrame(self.window,fg_color='transparent');row.pack(pady=12)
        self.action=ct.CTkButton(row,text='Подтвердить импорт',width=230,state='disabled',command=self.start);self.action.pack(side='left',padx=6)
        self.cancel=ct.CTkButton(row,text='Отмена',width=140,fg_color='#344f40',command=self.cancel_request);self.cancel.pack(side='left',padx=6)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
    def post(self,method,*args):self.app.events.put(('code_ui',lambda:method(*args) if not self.closed and self.window.winfo_exists() else None))
    def prepare(self):
        if self.app.busy:return
        self.running=True
        def job():
            self.transfer=self.app.transfer
            original=self.transfer.notify
            self.transfer.notify=lambda text,value:self.post(self.preflight_progress,text)
            try:
                resolved,major=build_codes.prepare(self.data,self.transfer,self.app.cfg.get('java','').strip())
                self.session=build_codes.ImportSession(self.app.root_path,self.data,resolved,self.app.cfg.get('java','').strip());self.ready=True
                self.post(self.prepared,major)
            except Exception as error:self.post(self.failed,str(error),True)
            finally:self.transfer.notify=original;self.running=False
        self.app.work(job,True)
    def preflight_progress(self,text):self.phase.configure(text=text)
    def prepared(self,major):
        self.bar.stop();self.bar.configure(mode='determinate');self.bar.set(0);self.phase.configure(text='Точные версии проверены. Требуется Java '+str(major)+'. Проверьте название и подтвердите установку.');self.action.configure(state='normal',text='Подтвердить импорт',command=self.start)
    def start(self):
        if self.app.busy or self.running:return
        if not self.ready:self.prepare();return
        data=copy.deepcopy(self.data);new_name=self.name.get().strip()
        if self.choice.get()=='Указать другое название' and new_name==self.data['name']:
            self.phase.configure(text='Введите другое название или выберите создание копии.');return
        data['name']=new_name
        try:build_codes.validate(data)
        except ValueError as error:self.phase.configure(text=str(error));return
        self.session.data=data;self.running=True;self.action.configure(state='disabled');self.cancel.configure(state='normal')
        def job():
            self.transfer=self.app.transfer
            try:
                result=self.session.run(self.transfer,lambda state:self.post(self.progress,state))
                self.app.events.put(('instance_added',result));self.post(self.completed,result)
            except Exception as error:self.post(self.failed,'Импорт отменён.' if isinstance(error,Cancelled) else str(error),False)
            finally:
                self.running=False
                if self.closed and self.session:
                    try:self.session.cleanup()
                    except OSError:pass
        self.app.work(job,True)
    def progress(self,state):
        self.bar.stop();self.bar.configure(mode='determinate');self.bar.set(state['progress']);self.phase.configure(text=state['text'])
        self.count.configure(text=f'{round(state["progress"]*100)}% • файлов: {state["done"]}/{state["total"]} • осталось: {state["total"]-state["done"]}')
        self.stages.configure(text='\n'.join(k+': '+v for k,v in state['status'].items()))
    def completed(self,result):
        self.bar.set(1);self.phase.configure(text='Установлена отдельная сборка: '+result['name']);self.action.configure(state='disabled',text='Готово');self.cancel.configure(text='Закрыть',command=self.close)
    def failed(self,text,preflight):
        self.bar.stop();self.bar.configure(mode='determinate');self.phase.configure(text=text+'\nЧастичная сборка не добавлена в список готовых.')
        if preflight:self.ready=False
        self.action.configure(state='normal',text='Повторить проверку' if preflight else 'Повторить неудачный этап',command=self.prepare if preflight else self.start)
        self.cancel.configure(state='normal',text='Закрыть',command=self.close)
    def cancel_request(self):
        if self.running and self.app.transfer:self.app.transfer.cancelled.set();self.phase.configure(text='Отменяем импорт и завершаем текущую операцию…');self.cancel.configure(state='disabled')
        else:self.close()
    def close(self):
        if self.closed:return
        self.closed=True
        if self.running and self.app.transfer:self.app.transfer.cancelled.set()
        elif self.session:
            try:self.session.cleanup()
            except OSError:pass
        if self.window.winfo_exists():self.window.destroy()

