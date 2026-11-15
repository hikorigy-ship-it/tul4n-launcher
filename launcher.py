import os, sys, json, re, uuid, hashlib, threading, subprocess, queue
from pathlib import Path
if getattr(sys, 'frozen', False):
    sys.stdout = sys.stderr = open(Path(sys.executable).parent / 'launcher.log', 'a', encoding='utf-8', buffering=1)
import requests
import customtkinter as ct
from customtkinter.windows.widgets.core_rendering import DrawEngine
import tkinter as tk
import minecraft_launcher_lib as mc
from PIL import Image
from io import BytesIO
import html
import math,time
from urllib.parse import urlparse
import packs
import loaders
import updater
from hover import AnimatedButton
from menus import StyledOptionMenu

ct.CTkButton = AnimatedButton
ct.CTkOptionMenu = StyledOptionMenu

class MediaWorkers:
    """Bounded background work that never keeps a closed launcher alive."""
    def __init__(self,max_workers=4):
        self.tasks=queue.Queue(); self.closed=False
        for _ in range(max_workers):threading.Thread(target=self.run,daemon=True).start()
    def run(self):
        while True:
            task=self.tasks.get()
            if task is None:return
            fn,args=task
            if not self.closed:
                try:fn(*args)
                except Exception:
                    import traceback
                    traceback.print_exc()
    def submit(self,fn,*args):
        if not self.closed:self.tasks.put((fn,args))
    def shutdown(self,**kwargs):
        self.closed=True
        while not self.tasks.empty():
            try:self.tasks.get_nowait()
            except queue.Empty:break
        for _ in range(4):self.tasks.put(None)

def russian(text):
    """Translate public mod text; keep originals available and cache successful results."""
    if not text.strip(): return text
    cache=ROOT/'cache'/'translations'; cache.mkdir(parents=True,exist_ok=True)
    target=cache/(hashlib.sha256(('ru-v1:'+text).encode()).hexdigest()+'.txt')
    if target.exists(): return target.read_text('utf-8')
    chunks=[]; remaining=text
    while remaining:
        end=min(2500,len(remaining))
        if end<len(remaining):
            split=remaining.rfind('\n',0,end)
            if split>1000:end=split+1
        chunks.append(remaining[:end]); remaining=remaining[end:]
    translated=[]
    for chunk in chunks:
        response=requests.get('https://translate.googleapis.com/translate_a/single',params={'client':'gtx','sl':'auto','tl':'ru','dt':'t','q':chunk},timeout=25)
        response.raise_for_status()
        result=response.json()
        value=''.join(part[0] for part in result[0] if part and part[0])
        if not value.strip(): raise ValueError('Пустой ответ сервиса перевода')
        translated.append(value)
    value=''.join(translated)
    target.write_text(value,'utf-8'); return value

def readable_description(body):
    body=re.sub(r'!\[[^\]]*\]\([^)]*\)','',body)
    body=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'\1 (\2)',body)
    body=re.sub(r'<(?:br|/p|/div|/h[1-6])\s*/?>','\n',body,flags=re.I)
    body=re.sub(r'<[^>]*>','',body)
    body=re.sub(r'(?m)^#{1,6}\s*','',body)
    body=body.replace('**','').replace('```','').replace('`','')
    return html.unescape(re.sub(r'\n{3,}','\n\n',body)).strip()

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
CONFIG = ROOT / 'settings.json'
VERSIONS = loaders.VERSIONS
ct.set_appearance_mode('dark')
# Native polygons avoid expensive font-glyph rendering during Windows resizing.
DrawEngine.preferred_drawing_method='polygon_shapes'
ct.set_default_color_theme('blue')
for widget in ('CTkButton','CTkOptionMenu'):
    ct.ThemeManager.theme[widget]['fg_color']=['#168653','#168653']
    ct.ThemeManager.theme[widget]['hover_color']=['#20a56a','#20a56a']
ct.ThemeManager.theme['CTkOptionMenu']['button_color']=['#126b43','#126b43']
ct.ThemeManager.theme['CTkOptionMenu']['button_hover_color']=['#20a56a','#20a56a']
ct.ThemeManager.theme['CTkEntry']['fg_color']=['#222c22','#222c22']
ct.ThemeManager.theme['CTkEntry']['border_color']=['#313e32','#313e32']

class Launcher(ct.CTk):
    def __init__(self):
        super().__init__()
        self.title('TUL4N Лаунчер • Minecraft')
        icon = Path(getattr(sys, '_MEIPASS', ROOT)) / 'chunk.ico'
        if icon.exists(): self.iconbitmap(str(icon))
        self.geometry('1180x780'); self.minsize(1060, 720)
        self.configure(fg_color='#101410')
        self.cfg = json.loads(CONFIG.read_text('utf-8')) if CONFIG.exists() else {}
        self.accounts = self.cfg.get('accounts', [])
        self.nick = ct.StringVar(value=self.cfg.get('nick', self.accounts[0] if self.accounts else ''))
        self.version = ct.StringVar(value=self.cfg.get('version', '1.21.11'))
        self.loader_type=ct.StringVar(value='Fabric'); self.search_timer=None
        self.events = queue.Queue(); self.busy = False
        self.game_running=False; self.searching=False; self.search_id=0
        self.current_page=None;self.closing=False;self.resizing_until=0
        self.nav_animation=None;self.nav_y=None;self.hero_resize_job=None;self.hero_size=None
        self.content_resize_job=None;self.content_size=(940,665)
        self.instances=packs.list_instances(ROOT)
        self.active_id=self.cfg.get('active_instance',self.version.get())
        if not any(x['id']==self.active_id for x in self.instances):self.active_id=self.version.get()
        self.instance_name=ct.StringVar(value='')
        self.media_pool=MediaWorkers(max_workers=4)
        self.search_generation=0; self.mod_widgets={}
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(1, weight=1)
        self.page_host=tk.Frame(self,bg='#101410',bd=0,highlightthickness=0)
        self.page_host.grid(row=1,column=1,sticky='nsew',padx=(24,28),pady=(4,22))
        self.page_host.bind('<Configure>',self.queue_content_resize)
        header=ct.CTkFrame(self,height=64,corner_radius=0,fg_color='#101410'); header.grid(row=0,column=1,sticky='ew',padx=(24,28)); header.grid_propagate(False)
        self.transition_line=tk.Canvas(header,height=2,bg='#101410',highlightthickness=0,bd=0)
        self.transition_line.place(relx=0,rely=1,relwidth=1,anchor='sw')
        ct.CTkLabel(header,text='С возвращением в свой мир!',font=('Segoe UI',15),text_color='#dce9dd').pack(side='left',pady=18)
        ct.CTkLabel(header,text='●  FABRIC · FORGE · NEOFORGE',font=('Segoe UI',11,'bold'),text_color='#8af8a2').pack(side='right',pady=18)
        side = ct.CTkFrame(self, width=185, corner_radius=0, fg_color='#101410'); side.grid(row=0,column=0,rowspan=2,sticky='ns')
        side.grid_propagate(False)
        ct.CTkLabel(side,text='ϟ  TUL4N',font=('Segoe UI',25,'bold'),text_color='#70e6a1').pack(pady=(19,3))
        ct.CTkLabel(side,text='MINECRAFT LAUNCHER',font=('Segoe UI',9),text_color='#637866').pack(pady=(0,34))
        self.pages={}; self.nav={}
        for name,symbol in [('Главная','⌂'),('Моды','▦'),('Сборки','◫'),('Аккаунты','♙'),('Настройки','⚙')]:
            b=ct.CTkButton(side,text=f'{symbol}   {name}',height=44,corner_radius=11,fg_color='transparent',text_color='#879d8b',hover_color='#212f24',anchor='w',font=('Segoe UI',14),command=lambda n=name:self.show(n)); b.pack(padx=12,pady=6,fill='x'); self.nav[name]=b
            p=ct.CTkFrame(self.page_host,width=940,height=665,fg_color='#101410',corner_radius=0);p.pack_propagate(False);self.pages[name]=p
        self.nav_indicator=tk.Frame(side,bg='#a3ffbb',width=3,height=22)
        profile=ct.CTkFrame(side,fg_color='#1a231b',corner_radius=13); profile.pack(side='bottom',padx=12,pady=18,fill='x')
        ct.CTkLabel(profile,text='◈  Офлайн-профиль',font=('Segoe UI',12,'bold'),text_color='#a4ffb8').pack(padx=10,pady=(12,4))
        self.sidebar_nick=ct.CTkLabel(profile,text=self.nick.get() or 'Выберите ник',font=('Segoe UI',13)); self.sidebar_nick.pack(pady=(0,12))
        self.home(); self.mods(); self.builds(); self.profiles(); self.settings(); self.refresh_instances(); self.show('Главная')
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.bind('<Control-f>',lambda _:self.focus_search())
        self.animation_job=self.after(60,self.animate_hero)
        self.bind('<Configure>',self.on_window_resize,add='+')
        self.after(100,self.poll)
        self.update_checking=False
        self.update_timer=self.after(10000,self.check_updates_automatically)

    def label(self,p,text,size=16,color='#e6efdc'):
        w=ct.CTkLabel(p,text=text,font=('Segoe UI',size,'bold' if size>20 else 'normal'),text_color=color,wraplength=720,justify='left'); w.pack(anchor='w',pady=10); return w
    def show(self,n):
        if self.current_page==n:return
        previous=self.current_page
        if previous:
            self.pages[previous].place_forget()
            self.nav[previous].configure(fg_color='transparent',text_color='#879d8b')
        self.current_page=n
        self.pages[n].configure(width=self.content_size[0],height=self.content_size[1]);self.pages[n].place(x=0,y=0)
        self.nav[n].configure(fg_color='#168653',text_color='#ffffff')
        if self.nav_animation:self.after_cancel(self.nav_animation);self.nav_animation=None
        self.after_idle(lambda:self.start_navigation_animation(n))
        if n=='Моды' and not getattr(self,'catalog_loaded',False) and not self.searching:self.after(80,self.start_search)
    def start_navigation_animation(self,name):
        if self.closing or name!=self.current_page:return
        button=self.nav[name]
        if not button.winfo_ismapped() or button.winfo_y()<40:
            self.nav_animation=self.after(40,lambda:self.start_navigation_animation(name));return
        target=button.winfo_y()+button.winfo_height()/2-11
        start=self.nav_y if self.nav_y is not None else target
        began=time.monotonic(); self.transition_line.delete('all')
        line=self.transition_line.create_rectangle(0,0,0,2,fill='#8affa6',outline='')
        def frame():
            if self.closing or name!=self.current_page:return
            t=min(1,(time.monotonic()-began)/.23);ease=1-(1-t)**3
            self.nav_y=start+(target-start)*ease
            self.nav_indicator.place(x=5,y=round(self.nav_y),width=3,height=22)
            self.pages[name].place_configure(y=round(10*(1-ease)))
            width=self.transition_line.winfo_width()
            self.transition_line.coords(line,width*ease-140,0,width*ease,2)
            if t<1:self.nav_animation=self.after(20,frame)
            else:self.nav_animation=None;self.transition_line.delete('all')
        frame()
    def on_window_resize(self,event):
        if event.widget is self:self.resizing_until=time.monotonic()+.14
    def queue_content_resize(self,event):
        self.target_content_size=(max(1,event.width),max(1,event.height))
        if self.content_resize_job:self.after_cancel(self.content_resize_job)
        self.content_resize_job=self.after(120,self.apply_content_resize)
    def apply_content_resize(self):
        self.content_resize_job=None
        if self.closing:return
        self.content_size=self.target_content_size
        if self.current_page:self.pages[self.current_page].configure(width=self.content_size[0],height=self.content_size[1])
    def animate_hero(self):
        if self.closing:return
        if self.current_page=='Главная' and self.state()!='iconic' and time.monotonic()>self.resizing_until:
            now=time.monotonic()
            for i,item in enumerate(self.hero_canvas.find_withtag('spark')[::4]):
                value=int(140+55*(1+math.sin(now*1.5+i))/2)
                self.hero_canvas.itemconfigure(item,fill=f'#{int(value*.55):02x}{value:02x}{int(value*.72):02x}')
            for i,item in enumerate(self.hero_canvas.find_withtag('glow')):
                value=int(175+35*(1+math.sin(now*1.9+i))/2)
                self.hero_canvas.itemconfigure(item,outline=f'#70{value:02x}a0')
        self.animation_job=self.after(100,self.animate_hero)
    def focus_search(self):
        self.show('Моды'); self.search.focus_set(); self.search.select_range(0,'end')
    def close(self):
        self.closing=True
        for job in (self.nav_animation,self.hero_resize_job,self.content_resize_job,getattr(self,'animation_job',None),getattr(self,'update_timer',None),self.search_timer):
            if job:
                try:self.after_cancel(job)
                except tk.TclError:pass
        self.search_generation+=1
        self.media_pool.shutdown(wait=False,cancel_futures=True)
        self.destroy()
    def save(self):
        self.cfg.update(accounts=self.accounts,nick=self.nick.get(),version=self.version.get(),active_instance=self.active_id)
        tmp=CONFIG.with_suffix('.tmp'); tmp.write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2),'utf-8'); tmp.replace(CONFIG)
    def home(self):
        p=self.pages['Главная']
        hero=ct.CTkFrame(p,height=300,corner_radius=20,fg_color='#132217',border_width=1,border_color='#294735'); hero.pack(fill='x'); hero.pack_propagate(False)
        self.hero_canvas=tk.Canvas(hero,bg='#132217',highlightthickness=0,bd=0); self.hero_canvas.place(relx=.48,rely=0,relwidth=.52,relheight=1)
        self.hero_canvas.bind('<Configure>',self.draw_hero)
        copy=ct.CTkFrame(hero,fg_color='#132217',corner_radius=0); copy.place(x=24,y=20)
        ct.CTkLabel(copy,text='Добро пожаловать',font=('Segoe UI',29,'bold'),text_color='white').pack(anchor='w')
        ct.CTkLabel(copy,text='в TUL4N',font=('Segoe UI',31,'bold'),text_color='#6bff91').pack(anchor='w')
        ct.CTkLabel(copy,text='Твой мир. Твои правила.',font=('Segoe UI',14),text_color='#a0b9ab').pack(anchor='w',pady=(7,17))
        actions=ct.CTkFrame(copy,fg_color='transparent'); actions.pack(anchor='w')
        self.play=ct.CTkButton(actions,text='▷  Играть',width=135,height=46,corner_radius=12,border_width=1,border_color='#44bd80',font=('Segoe UI',17,'bold'),command=self.begin_launch); self.play.pack(side='left',padx=(0,10))
        ct.CTkOptionMenu(actions,values=VERSIONS,variable=self.version,command=self.choose_base,width=118,height=46,fg_color='#212e24',button_color='#212e24',button_hover_color='#304437',font=('Segoe UI',14)).pack(side='left',padx=(0,8))
        ct.CTkOptionMenu(actions,values=loaders.LOADERS,variable=self.loader_type,command=lambda _:self.choose_base(self.version.get()),width=120,height=46,fg_color='#212e24',button_color='#212e24',button_hover_color='#304437',font=('Segoe UI',14)).pack(side='left')
        ct.CTkLabel(copy,text='MINECRAFT JAVA EDITION',font=('Segoe UI',10,'bold'),text_color='#95b4a0').pack(anchor='w',pady=(10,0))
        self.status=ct.CTkLabel(p,text='Готов к новому приключению',font=('Segoe UI',12),text_color='#8ba592',wraplength=800,anchor='w',justify='left'); self.status.pack(fill='x',pady=(10,14))
        self.instance_menu=ct.CTkOptionMenu(p,values=['Загрузка сборок…'],variable=self.instance_name,command=self.choose_instance,height=34); self.instance_menu.pack(fill='x',pady=(0,10))
        self.operation_progress=ct.CTkProgressBar(p,height=4,progress_color='#87ffa4'); self.operation_progress.pack(fill='x',pady=(0,8)); self.operation_progress.set(0)
        lower=ct.CTkFrame(p,fg_color='transparent'); lower.pack(fill='both',expand=True); lower.grid_columnconfigure((0,1),weight=1); lower.grid_rowconfigure(0,weight=1)
        left=ct.CTkFrame(lower,fg_color='#191f19',corner_radius=15); left.grid(row=0,column=0,sticky='nsew',padx=(0,8))
        right=ct.CTkFrame(lower,fg_color='#191f19',corner_radius=15); right.grid(row=0,column=1,sticky='nsew',padx=(8,0))
        ct.CTkLabel(left,text='▤  Твой профиль',font=('Segoe UI',18,'bold')).pack(anchor='w',padx=20,pady=(18,8))
        ct.CTkLabel(left,text='Выбери ник для следующего приключения',text_color='#829688',font=('Segoe UI',12)).pack(anchor='w',padx=20,pady=(0,15))
        self.account_menu=ct.CTkOptionMenu(left,values=self.accounts or ['Создайте профиль'],variable=self.nick,width=280,height=42,fg_color='#253028',button_color='#2a4633',command=lambda n:self.select_account(n)); self.account_menu.pack(anchor='w',padx=20)
        ct.CTkButton(left,text='＋  Создать аккаунт',fg_color='#253028',hover_color='#304338',height=40,command=lambda:self.show('Аккаунты')).pack(fill='x',padx=20,pady=16)
        ct.CTkLabel(right,text='✧  Мастерская модов',font=('Segoe UI',18,'bold')).pack(anchor='w',padx=20,pady=(18,8))
        ct.CTkLabel(right,text='MODRINTH',text_color='#95ffb1',font=('Segoe UI',11,'bold')).pack(anchor='w',padx=20)
        ct.CTkLabel(right,text='Найди новые возможности для своего мира.\nМоды и зависимости — одним нажатием.',text_color='#96af9e',font=('Segoe UI',13),justify='left').pack(anchor='w',padx=20,pady=12)
        ct.CTkButton(right,text='Открыть каталог  →',height=40,command=lambda:self.show('Моды')).pack(fill='x',padx=20,pady=(0,20))
    def draw_hero(self,event):
        self.hero_target_size=(max(event.width,1),max(event.height,1))
        if self.hero_resize_job is None:self.hero_resize_job=self.after(45,self.paint_hero)
    def paint_hero(self):
        self.hero_resize_job=None
        if self.closing:return
        c=self.hero_canvas;w,h=self.hero_target_size
        if self.hero_size:
            previous_w,previous_h=self.hero_size
            if (w,h)!=(previous_w,previous_h):c.scale('all',0,0,w/previous_w,h/previous_h)
            self.hero_size=(w,h)
            return
        # Native vector artwork: an isometric emerald cavern.
        for x in range(0,w,4):
            t=x/max(w,1); c.create_rectangle(x,0,x+4,h,fill=f'#{int(19+7*t):02x}{int(34+28*t):02x}{int(23+15*t):02x}',outline='')
        import random
        rng=random.Random(42)
        for i in range(55):
            x=rng.randint(0,max(w,1)); y=rng.randint(0,max(h,1)); r=rng.choice([1,1,2]); c.create_oval(x,y,x+r,y+r,fill=rng.choice(['#609b75','#325949','#92ffb9']),outline='',tags='spark')
        def cube(x,y,s,top,left,right):
            c.create_polygon(x,y-s/2,x+s,y,x,y+s/2,x-s,y,fill=top,outline='')
            c.create_polygon(x-s,y,x,y+s/2,x,y+s*1.5,x-s,y+s,fill=left,outline='')
            c.create_polygon(x,y+s/2,x+s,y,x+s,y+s,x,y+s*1.5,fill=right,outline='')
        for row in range(3):
            for col in range(5):
                cube(w*.5+(col-2)*62+(row%2)*30,h*.68+row*33,32,'#335744','#1d3021','#233f30')
        for x,y,s in [(w*.52,h*.43,68),(w*.74,h*.52,45),(w*.29,h*.68,34),(w*.88,h*.76,28)]:
            c.create_polygon(x-s*.65,y+s*.8,x-s*.4,y-s*.3,x,y-s*1.45,x+s*.45,y-s*.35,x+s*.7,y+s*.8,fill='#61f198',outline='#94ffba',width=2,tags='glow')
            c.create_polygon(x,y-s*1.45,x+s*.45,y-s*.35,x+s*.7,y+s*.8,x,y+s*.65,fill='#41b667',outline='')
            c.create_line(x-s*.4,y-s*.3,x,y-s*1.45,fill='#dbffed',width=3)
        c.create_text(w*.6,h*.91,text='THE EMERALD CAVES',fill='#90d6ab',font=('Segoe UI',10,'bold'))
        self.hero_size=(w,h)
    def work(self,fn):
        if self.busy:
            self.events.put(('status','Идёт установка. Дождитесь её завершения; поиск доступен.')); return
        self.busy=True; self.play.configure(state='disabled')
        self.operation_progress.configure(mode='indeterminate'); self.operation_progress.start()
        def job():
            try: fn()
            except Exception as e: self.events.put(('status','Ошибка: '+str(e)))
            finally: self.events.put(('done',None))
        threading.Thread(target=job,daemon=True).start()
    def poll(self):
        if self.closing:return
        try:self.process_events()
        except Exception:
            import traceback
            traceback.print_exc()
            self.status.configure(text='Не удалось обновить интерфейс. Повторите поиск.')
        finally:
            if not self.closing:self.after(45,self.poll)
    def process_events(self):
        deadline=time.perf_counter()+.008
        while not self.events.empty() and time.perf_counter()<deadline:
            kind,data=self.events.get()
            if kind=='status': self.status.configure(text=data); self.modstatus.configure(text=data); self.pack_status.configure(text=data)
            elif kind=='update_status': self.update_status.configure(text=data)
            elif kind=='update_checked':
                self.update_checking=False
                self.available_update=data
                self.update_button.configure(state='normal',text='Обновить и перезапустить' if data else 'Проверить обновления')
                self.update_status.configure(text=f'Доступна версия {data[0]}' if data else 'Установлена последняя версия')
                if data:self.status.configure(text=f'Доступен TUL4N {data[0]} — обновление в Настройках')
            elif kind=='update_error':
                self.update_checking=False
                self.update_button.configure(state='normal',text='Повторить проверку')
                self.available_update=None
                self.update_status.configure(text='Ошибка обновления: '+str(data)[:180])
            elif kind=='update_ready':
                self.update_checking=False
                if self.busy or self.game_running:
                    self.update_button.configure(state='normal',text='Обновить и перезапустить')
                    self.update_status.configure(text='Завершите игру или установку, затем повторите обновление')
                else:
                    try: updater.restart(data,sys.executable)
                    except Exception as error:
                        self.events.put(('update_error',str(error)))
                    else: self.close(); return
            elif kind=='mods': self.render_mods(data)
            elif kind=='search_result':
                request,result,version,error,query,loader_type,notice=data
                if request==self.search_id:
                    self.searching=False; self.search_button.configure(state='normal',text='Найти моды'); self.search_progress.stop(); self.search_progress.set(0)
                    if error:self.modstatus.configure(text=error+' • нажмите «Найти моды», чтобы повторить')
                    else:
                        self.catalog_loaded=True; self.render_mods((result,version,loader_type))
                        self.modstatus.configure(text=notice or (f'«{query}» • Найдено: {len(result)} • {loader_type.title()} {version}' if result else f'По запросу «{query}» ничего не найдено для {loader_type.title()} {version}. Измените версию или загрузчик.'))
            elif kind=='pack_results':
                result,version,loader_type,error=data
                self.pack_search_button.configure(state='normal',text='Найти сборки')
                self.pack_status.configure(text=error or f'Найдено: {len(result)} • {loader_type.title()} {version}')
                if not error:self.render_pack_results(result,version,loader_type)
            elif kind=='instance_added':
                self.active_id=data['id']; self.refresh_instances(); self.save()
            elif kind=='progress':
                text,value=data; self.status.configure(text=text); self.pack_status.configure(text=text)
                self.operation_progress.stop(); self.operation_progress.configure(mode='determinate'); self.operation_progress.set(value)
            elif kind=='card_media':
                generation,mid,picture,description,translated=data
                if generation==self.search_generation and mid in self.mod_widgets:
                    icon,summary,note=self.mod_widgets[mid]
                    if picture:
                        asset=ct.CTkImage(light_image=picture,dark_image=picture,size=(64,64)); icon.configure(image=asset,text=''); icon.image=asset
                    summary.configure(text=description)
                    note.configure(text='Автоперевод • русский' if translated else 'Оригинал • перевод недоступен')
            elif kind=='details':
                window,textbox,note,original,translated,error=data
                if window.winfo_exists():
                    window.original_description=original; window.russian_description=translated
                    textbox.configure(state='normal'); textbox.delete('1.0','end'); textbox.insert('1.0',translated or original); textbox.configure(state='disabled')
                    note.configure(text=error or 'Автоперевод Google • русский • оригинал доступен ниже')
            elif kind=='game_closed': self.game_running=False; self.play.configure(state='normal',text='▷  Играть'); self.status.configure(text=data)
            elif kind=='done':
                self.busy=False; self.play.configure(state='disabled' if self.game_running else 'normal',text='Игра запущена' if self.game_running else '▷  Играть')
                self.operation_progress.stop(); self.operation_progress.configure(mode='determinate'); self.operation_progress.set(0)
    def begin_launch(self):
        self.launch_context=(self.nick.get(),dict(self.active_instance()))
        self.work(self.launch)
    def launch(self):
        nick,instance=self.launch_context; version=instance['version']
        if nick not in self.accounts: raise ValueError('Создайте и выберите аккаунт во вкладке «Аккаунты».')
        game=ROOT/'instances'/instance['id']; game.mkdir(parents=True,exist_ok=True)
        kind=instance.get('loader_type','fabric')
        loaders.available(kind,version)
        java=loaders.java_for(version,self.cfg.get('java','').strip())
        callback={'setStatus':lambda s:self.events.put(('status',s))}
        self.events.put(('status','Проверяем и устанавливаем Minecraft + '+kind.title()+'…'))
        installed=loaders.install(kind,version,game,java,callback,instance.get('loader'))
        digest=bytearray(hashlib.md5(('OfflinePlayer:'+nick).encode()).digest()); digest[6]=(digest[6]&15)|48; digest[8]=(digest[8]&63)|128
        options={'username':nick,'uuid':str(uuid.UUID(bytes=bytes(digest))),'token':'0','executablePath':java,'jvmArguments':[f'-Xmx{self.cfg.get("ram",4)}G'],'gameDirectory':str(game),'launcherName':'TUL4N'}
        cmd=mc.command.get_minecraft_command(installed,str(game),options)
        self.events.put(('status','Minecraft запущен. Журнал: instances/'+version+'/game.log'))
        log=(game/'game.log').open('w',encoding='utf-8')
        try:process=subprocess.Popen(cmd,cwd=game,stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
        except Exception:log.close(); raise
        self.game_running=True
        def monitor():
            code=process.wait(); log.close()
            self.events.put(('game_closed','Игра закрыта.' if code==0 else f'Игра завершилась с кодом {code}. Проверьте game.log.'))
        threading.Thread(target=monitor,daemon=True).start()
    def active_instance(self):
        return next((x for x in self.instances if x['id']==self.active_id),self.instances[0])
    def instance_label(self,item):
        if item['source']=='base':return item['name']
        return item['name']+' • '+item.get('loader_type','fabric').title()+' '+item['version']+' ['+item['id'][-6:]+']'
    def refresh_instances(self):
        self.instances=packs.list_instances(ROOT)
        selected=self.active_instance(); self.version.set(selected['version']); self.loader_type.set(next(x for x in loaders.LOADERS if x.lower()==selected.get('loader_type','fabric')))
        self.instance_menu.configure(values=[self.instance_label(x) for x in self.instances]); self.instance_name.set(self.instance_label(selected))
        if hasattr(self,'library'):self.render_library()
        if hasattr(self,'mod_target'):self.mod_target.configure(text='Установка модов в: '+selected['name']+' • '+selected.get('loader_type','fabric').title()+' '+selected['version'])
    def choose_instance(self,label):
        for instance in self.instances:
            if self.instance_label(instance)==label:self.active_id=instance['id']; break
        self.refresh_instances(); self.save(); self.catalog_loaded=False
    def choose_base(self,version):
        kind=self.loader_type.get().lower()
        self.active_id=version if kind=='fabric' else kind+'-'+version
        self.refresh_instances(); self.save(); self.catalog_loaded=False
    def activate_instance(self,instance):
        self.active_id=instance['id']; self.refresh_instances(); self.save(); self.catalog_loaded=False; self.show('Главная')
        self.status.configure(text='Выбрана сборка: '+instance['name'])
    def builds(self):
        p=self.pages['Сборки']; self.label(p,'Твои сборки',32)
        self.label(p,'Отдельные моды, настройки и миры для каждого приключения.',13,'#9bb8a7')
        tabs=ct.CTkTabview(p,fg_color='#191f19',segmented_button_selected_color='#168653'); tabs.pack(fill='both',expand=True)
        own=tabs.add('Мои сборки'); catalog=tabs.add('Modrinth')
        form=ct.CTkFrame(own,fg_color='transparent'); form.pack(fill='x',pady=8)
        self.build_name=ct.CTkEntry(form,placeholder_text='Название новой сборки',width=270,height=38); self.build_name.pack(side='left',padx=(4,10))
        self.build_version=ct.CTkOptionMenu(form,values=VERSIONS,width=130,height=38); self.build_version.set(self.version.get()); self.build_version.pack(side='left',padx=(0,10))
        self.build_loader=ct.CTkOptionMenu(form,values=loaders.LOADERS,width=125,height=38); self.build_loader.pack(side='left',padx=(0,10))
        ct.CTkButton(form,text='＋ Создать',width=125,height=38,command=self.create_build).pack(side='left')
        self.library=ct.CTkScrollableFrame(own,fg_color='transparent'); self.library.pack(fill='both',expand=True,pady=8)
        self.pack_query=ct.CTkEntry(catalog,placeholder_text='Название сборки…',height=38); self.pack_query.pack(fill='x',pady=8)
        tools=ct.CTkFrame(catalog,fg_color='transparent'); tools.pack(fill='x')
        self.pack_version=ct.CTkOptionMenu(tools,values=VERSIONS,width=145); self.pack_version.set(self.version.get()); self.pack_version.pack(side='left',padx=(0,10))
        self.pack_loader=ct.CTkOptionMenu(tools,values=loaders.LOADERS,width=135); self.pack_loader.pack(side='left',padx=(0,10))
        self.pack_search_button=ct.CTkButton(tools,text='Найти сборки',command=self.search_packs); self.pack_search_button.pack(side='left')
        self.pack_query.bind('<Return>',lambda _:self.search_packs())
        self.pack_results=ct.CTkScrollableFrame(catalog,fg_color='transparent'); self.pack_results.pack(fill='both',expand=True,pady=12)
        self.pack_status=ct.CTkLabel(p,text='Выберите готовую сборку Modrinth или создайте свою.',wraplength=850,text_color='#a4d0b6'); self.pack_status.pack(fill='x',pady=8)
    def create_build(self):
        try:
            item=packs.new_instance(ROOT,self.build_name.get(),self.build_version.get(),loader_type=self.build_loader.get().lower())
            self.active_id=item['id']; self.refresh_instances(); self.save(); self.build_name.delete(0,'end')
            self.pack_status.configure(text='Создана и выбрана: '+item['name']+'. Добавляйте моды во вкладке «Моды».')
        except Exception as e:self.pack_status.configure(text=str(e))
    def render_library(self):
        for widget in self.library.winfo_children():widget.destroy()
        for item in self.instances:
            if item['source']=='base' and item['id']!=self.active_id and not (ROOT/'instances'/item['id']).exists():continue
            card=ct.CTkFrame(self.library,fg_color='#233128'); card.pack(fill='x',pady=5)
            count=len(list((ROOT/'instances'/item['id']/'mods').glob('*.jar')))
            title=('●  ' if item['id']==self.active_id else '◫  ')+item['name']
            ct.CTkLabel(card,text=title,font=('Segoe UI',17,'bold'),wraplength=520).pack(anchor='w',padx=15,pady=(12,0))
            ct.CTkLabel(card,text=f'{item.get("loader_type","fabric").title()} {item["version"]}  •  модов: {count}  •  '+('Modrinth' if item['source']=='modrinth' else 'Локальная'),text_color='#9ab7a7').pack(anchor='w',padx=15)
            row=ct.CTkFrame(card,fg_color='transparent'); row.pack(fill='x',padx=15,pady=12)
            ct.CTkButton(row,text='Выбрать сборку',width=165,command=lambda x=item:self.activate_instance(x)).pack(side='right')
            ct.CTkButton(row,text='Папка',fg_color='#344f40',width=85,command=lambda x=item:self.open_instance_folder(x)).pack(side='right',padx=8)
            ct.CTkButton(row,text='Моды',fg_color='#344f40',width=80,command=lambda x=item:self.manage_mods(x)).pack(side='right')
    def manage_mods(self,item):
        window=ct.CTkToplevel(self); window.title('Моды • '+item['name']); window.geometry('740x570')
        ct.CTkLabel(window,text=item['name'],font=('Segoe UI',23,'bold'),wraplength=680).pack(anchor='w',padx=20,pady=(20,5))
        note=ct.CTkLabel(window,text='Включайте и отключайте моды. Изменения действуют при следующем запуске.',wraplength=680,text_color='#9cc9af'); note.pack(anchor='w',padx=20,pady=8)
        panel=ct.CTkScrollableFrame(window,fg_color='#1d2921'); panel.pack(fill='both',expand=True,padx=20,pady=15)
        folder=ROOT/'instances'/item['id']/'mods'
        files=sorted([p for p in folder.glob('*') if p.is_file() and (p.name.endswith('.jar') or p.name.endswith('.jar.disabled'))])
        if not files:ct.CTkLabel(panel,text='Модов пока нет. Выберите сборку и откройте каталог «Моды».',wraplength=620).pack(pady=30)
        for path in files:
            enabled=ct.BooleanVar(value=path.name.endswith('.jar'))
            def toggle(p=path,v=enabled):
                if self.game_running or self.busy:
                    v.set(not v.get()); note.configure(text='Сначала закройте игру и дождитесь завершения установки.'); return
                base=p.name.removesuffix('.disabled')
                source=folder/(base+'.disabled' if v.get() else base)
                destination=folder/(base if v.get() else base+'.disabled')
                try:
                    if destination.exists():raise ValueError('Файл с таким именем уже существует')
                    source.rename(destination); note.configure(text='Состояние мода сохранено.'); self.render_library()
                except Exception as e:v.set(not v.get()); note.configure(text='Ошибка: '+str(e))
            ct.CTkSwitch(panel,text=path.name.removesuffix('.disabled'),variable=enabled,command=toggle,progress_color='#168653',font=('Segoe UI',12)).pack(anchor='w',padx=10,pady=9)
    def open_instance_folder(self,item):
        folder=ROOT/'instances'/item['id']; folder.mkdir(parents=True,exist_ok=True); os.startfile(folder)
    def search_packs(self):
        query,version=self.pack_query.get().strip(),self.pack_version.get()
        kind=self.pack_loader.get().lower()
        self.pack_search_button.configure(state='disabled',text='Поиск…'); self.pack_status.configure(text='Ищем сборки '+kind.title()+' '+version+' на Modrinth…')
        def job():
            try:
                result,_=packs.search(query,version,kind,'modpack',15)
                self.events.put(('pack_results',(result,version,kind,'')))
            except Exception as e:self.events.put(('pack_results',([],version,kind,'Ошибка поиска: '+str(e))))
        threading.Thread(target=job,daemon=True).start()
    def render_pack_results(self,result,version,loader_type='fabric'):
        for widget in self.pack_results.winfo_children():widget.destroy()
        for item in result:
            card=ct.CTkFrame(self.pack_results,fg_color='#233128'); card.pack(fill='x',pady=6)
            ct.CTkLabel(card,text='◫  '+item['title'],font=('Segoe UI',19,'bold'),wraplength=700).pack(anchor='w',padx=15,pady=(12,4))
            ct.CTkLabel(card,text=item['description'],wraplength=700,justify='left',text_color='#b0cebe').pack(anchor='w',padx=15)
            tools=ct.CTkFrame(card,fg_color='transparent'); tools.pack(fill='x',padx=15,pady=12)
            ct.CTkLabel(tools,text=f'{loader_type.title()} {version} • ↓ {item["downloads"]:,}',text_color='#8ead9d').pack(side='left')
            ct.CTkButton(tools,text='Установить сборку',width=180,command=lambda x=item,v=version,k=loader_type:self.work(lambda:self.install_pack(x,v,k))).pack(side='right')
    def install_pack(self,project,version,loader_type='fabric'):
        item=packs.install(ROOT,project,version,lambda text,value:self.events.put(('progress',(text,value))),loader_type)
        self.events.put(('instance_added',item))
    def start_mod_download(self,mid,version,loader_type='fabric'):
        instance=dict(self.active_instance())
        if instance['version']!=version or instance.get('loader_type','fabric')!=loader_type:
            self.modstatus.configure(text='Версия или загрузчик сборки изменились. Повторите поиск.'); return
        folder=ROOT/'instances'/instance['id']/'mods'
        self.work(lambda:self.download_mod(mid,version,set(),target_folder=folder,loader_type=loader_type))
    def profiles(self):
        p=self.pages['Аккаунты']; self.label(p,'Твоя личность',36); self.label(p,'Офлайн-аккаунт содержит только ник. Он подходит для одиночной игры\nи серверов, разрешающих офлайн-подключения.',16,'#afbc9e')
        self.name_entry=ct.CTkEntry(p,placeholder_text='Ник игрока',width=340,height=45); self.name_entry.pack(anchor='w',pady=15)
        self.profile_status=self.label(p,'3–16 символов: латинские буквы, цифры, _',14)
        ct.CTkButton(p,text='Создать аккаунт',command=self.add_account,height=44).pack(anchor='w')
        self.profile_list=ct.CTkScrollableFrame(p,fg_color='#191f19'); self.profile_list.pack(fill='both',expand=True,pady=25); self.render_profiles()
    def add_account(self):
        n=self.name_entry.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{3,16}',n): self.profile_status.configure(text='Неверный ник: нужно 3–16 латинских букв, цифр или _.'); return
        if n not in self.accounts:self.accounts.append(n)
        self.nick.set(n); self.save(); self.sidebar_nick.configure(text=n); self.account_menu.configure(values=self.accounts); self.render_profiles()
    def render_profiles(self):
        for w in self.profile_list.winfo_children():w.destroy()
        for n in self.accounts:
            ct.CTkButton(self.profile_list,text='◈  '+n+'    •    OFFLINE',height=50,fg_color='#263f30',command=lambda x=n:self.select_account(x)).pack(fill='x',pady=6)
    def select_account(self,n): self.nick.set(n); self.save(); self.sidebar_nick.configure(text=n); self.profile_status.configure(text='Выбран: '+n)
    def settings(self):
        p=self.pages['Настройки']; self.label(p,'Настрой под себя',36)
        self.label(p,'Путь к java.exe • оставьте пустым для автоматического выбора'); self.java_entry=ct.CTkEntry(p,width=650); self.java_entry.insert(0,self.cfg.get('java','')); self.java_entry.pack(anchor='w')
        self.label(p,'1.16.5 → Java 8 • 1.20.1 → Java 17 • 1.21.x → Java 21 • 26.x → Java 25',12,'#afbc9e')
        self.label(p,'Память игры, ГБ'); self.ram=ct.CTkOptionMenu(p,values=['2','3','4','6','8','12','16']); self.ram.set(str(self.cfg.get('ram',4))); self.ram.pack(anchor='w')
        self.label(p,'Магазин модов • Modrinth',22)
        self.label(p,'Поиск и скачивание доступны без аккаунта и API-ключа.',14,'#afbc9e')
        self.label(p,'Описания автоматически переводятся через Google Translate.\nСервис получает только публичный текст описания мода.',12,'#afbc9e')
        ct.CTkButton(p,text='Сохранить настройки',height=44,command=self.save_settings).pack(anchor='w',pady=20)
        self.settings_status=self.label(p,'Minecraft — Mojang • Fabric — FabricMC • Моды — Modrinth',14)
        self.available_update=None
        self.update_button=ct.CTkButton(p,text='Проверить обновления',height=40,command=self.update_launcher)
        self.update_button.pack(anchor='w',pady=(14,4))
        self.update_status=self.label(p,'TUL4N '+updater.VERSION,12,'#afbc9e')
        self.label(p,'Автопроверка при запуске и каждые 5 часов',12,'#829889')
    def check_updates_automatically(self):
        if self.closing:return
        self.update_timer=self.after(5*60*60*1000,self.check_updates_automatically)
        if not self.available_update and not self.update_checking and not self.busy and not self.game_running:
            self.update_launcher()
    def update_launcher(self):
        if self.update_checking:return
        if not getattr(sys,'frozen',False):
            self.update_status.configure(text='Обновления доступны в установленной .exe версии'); return
        if self.busy or self.game_running:
            self.update_status.configure(text='Сначала завершите игру или установку'); return
        release=self.available_update
        self.update_checking=True
        self.update_button.configure(state='disabled')
        self.update_status.configure(text='Скачиваем обновление…' if release else 'Проверяем обновления…')
        def job():
            try:
                if release:
                    stage=updater.download(release[1],sys.executable,lambda text:self.events.put(('update_status',text)))
                    self.events.put(('update_ready',stage))
                else:self.events.put(('update_checked',updater.latest()))
            except Exception as error:self.events.put(('update_error',str(error)))
        threading.Thread(target=job,daemon=True).start()
    def save_settings(self):
        self.cfg.update(java=self.java_entry.get().strip(),ram=int(self.ram.get())); self.save(); self.settings_status.configure(text='Настройки сохранены')
    def api(self,path,params=None):
        return packs.api(path,params)
    def mods(self):
        p=self.pages['Моды']; self.label(p,'Собери свой Minecraft',36); self.label(p,'MODRINTH • версия и загрузчик выбраны на Главной',14,'#8bffac')
        self.search=ct.CTkEntry(p,placeholder_text='Название мода…',width=500,height=42); self.search.pack(anchor='w',pady=10)
        self.search_button=ct.CTkButton(p,text='Найти моды',command=self.start_search); self.search_button.pack(anchor='w')
        self.search.bind('<Return>',lambda _:self.start_search())
        self.search.bind('<KeyRelease>',self.queue_search)
        self.mod_target=ct.CTkLabel(p,text='',text_color='#a0e5b8'); self.mod_target.pack(anchor='w')
        self.modstatus=self.label(p,'Введите название или нажмите «Найти моды», чтобы увидеть популярные.',14)
        self.search_progress=ct.CTkProgressBar(p,height=4,mode='indeterminate',progress_color='#87ffa4'); self.search_progress.pack(fill='x',pady=(0,8)); self.search_progress.set(0)
        self.modlist=ct.CTkScrollableFrame(p,fg_color='#191f19'); self.modlist.pack(fill='both',expand=True)
    def queue_search(self,event=None):
        if event and event.keysym in ('Return','Tab','Shift_L','Shift_R','Control_L','Control_R','Left','Right','Up','Down','Escape'):return
        if self.search_timer:self.after_cancel(self.search_timer)
        self.search_id+=1
        self.modstatus.configure(text='Запрос изменён. Ищем после окончания ввода…')
        self.search_timer=self.after(600,self.start_search)
    def start_search(self):
        if self.search_timer:self.after_cancel(self.search_timer);self.search_timer=None
        query,version=self.search.get().strip(),self.active_instance()['version']
        kind=self.active_instance().get('loader_type','fabric')
        aliases={'креейт':'Create','криэйт':'Create','содиум':'sodium','натрий':'sodium','ирис':'iris','мод меню':'mod menu','фабрик апи':'fabric api','миникарта':'minimap','карта':'map','шейдеры':'shader','оптимизация':'optimization'}
        query=aliases.get(query.lower(),query)
        self.search_id+=1; request=self.search_id; self.searching=True
        self.search_button.configure(state='disabled',text='Поиск…'); self.search_progress.start()
        self.render_mods(([],version,kind))
        self.modstatus.configure(text=f'Ищем «{query}» • {kind.title()} {version}…')
        threading.Thread(target=self.find_mods,args=(query,version,request,kind),daemon=True).start()
    def find_mods(self,query,version,request=None,loader_type='fabric'):
        try:
            data,notice=packs.search(query,version,loader_type)
            self.events.put(('search_result',(request,data,version,'',query,loader_type,notice)))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.events.put(('search_result',(request,[],version,'Modrinth не ответил: '+str(e)[:160],query,loader_type,'')))
    def render_mods(self,result):
        data,version=result[:2]; loader_type=result[2] if len(result)>2 else 'fabric'
        self.search_generation+=1; generation=self.search_generation; self.mod_widgets={}
        for w in self.modlist.winfo_children():w.destroy()
        self.remaining_mods=list(data);self.mod_list_context=(version,loader_type,generation);self.more_mods=None
        self.append_mod_cards()
    def append_mod_cards(self):
        version,loader_type,generation=self.mod_list_context
        if self.more_mods:self.more_mods.destroy();self.more_mods=None
        batch=self.remaining_mods[:6];self.remaining_mods=self.remaining_mods[6:]
        for m in batch:
            f=ct.CTkFrame(self.modlist,fg_color='#232e25'); f.pack(fill='x',pady=7,padx=6)
            top=ct.CTkFrame(f,fg_color='transparent'); top.pack(fill='x',padx=16,pady=(16,8))
            icon=ct.CTkLabel(top,text='◈',width=72,height=72,font=('Segoe UI',30),text_color='#9affb5',fg_color='#2b4332',corner_radius=12); icon.pack(side='left',anchor='n',padx=(0,16))
            copy=ct.CTkFrame(top,fg_color='transparent'); copy.pack(side='left',fill='x',expand=True)
            ct.CTkLabel(copy,text=m['title'],font=('Segoe UI',19,'bold')).pack(anchor='w')
            ct.CTkLabel(copy,text=f'Автор: {m.get("author", "—")}   •   ↓ {m.get("downloads",0):,}'.replace(',',' '),font=('Segoe UI',11),text_color='#899f92').pack(anchor='w',pady=(0,5))
            summary=ct.CTkLabel(copy,text=m['description'],wraplength=610,justify='left',text_color='#bed1c4',font=('Segoe UI',13)); summary.pack(anchor='w')
            bottom=ct.CTkFrame(f,fg_color='transparent'); bottom.pack(fill='x',padx=16,pady=(4,14))
            note=ct.CTkLabel(bottom,text='Загружаем логотип и перевод…',text_color='#839f92',font=('Segoe UI',10)); note.pack(side='left')
            ct.CTkButton(bottom,text=f'Скачать • {version} ↓',width=165,height=36,command=lambda mid=m['project_id'],v=version,k=loader_type:self.start_mod_download(mid,v,k)).pack(side='right',padx=(8,0))
            ct.CTkButton(bottom,text='Подробнее',width=110,height=36,fg_color='#314e3b',command=lambda mod=m,v=version,k=loader_type:self.open_details(mod,v,k)).pack(side='right')
            self.mod_widgets[m['project_id']]=(icon,summary,note)
            self.media_pool.submit(self.load_card_media,m,generation)
        if self.remaining_mods:
            self.more_mods=ct.CTkButton(self.modlist,text=f'Показать ещё • осталось {len(self.remaining_mods)}',height=40,fg_color='#304539',command=self.append_mod_cards)
            self.more_mods.pack(fill='x',padx=8,pady=12)
    def load_card_media(self,mod,generation):
        if generation!=self.search_generation: return
        picture=None; description=mod['description']; translated=False
        try:
            url=mod.get('icon_url') or ''
            if urlparse(url).hostname=='cdn.modrinth.com' and url.startswith('https://'):
                cache=ROOT/'cache'/'icons'; cache.mkdir(parents=True,exist_ok=True)
                target=cache/(hashlib.sha256(url.encode()).hexdigest()+'.img')
                if not target.exists():
                    response=requests.get(url,timeout=20); response.raise_for_status(); target.write_bytes(response.content)
                with Image.open(BytesIO(target.read_bytes())) as asset:
                    asset.thumbnail((128,128)); picture=asset.convert('RGBA').copy()
        except Exception: pass
        try: description=russian(description); translated=True
        except Exception: pass
        self.events.put(('card_media',(generation,mod['project_id'],picture,description,translated)))
    def open_details(self,mod,version,loader_type='fabric'):
        window=ct.CTkToplevel(self); window.title(mod['title']+' • Modrinth'); window.geometry('820x700'); window.configure(fg_color='#171f19')
        ct.CTkLabel(window,text=mod['title'],font=('Segoe UI',27,'bold'),wraplength=760).pack(anchor='w',padx=24,pady=(20,4))
        note=ct.CTkLabel(window,text='Загружаем подробное описание и перевод…',text_color='#94e8af',wraplength=760); note.pack(anchor='w',padx=24,pady=(0,10))
        textbox=ct.CTkTextbox(window,wrap='word',font=('Segoe UI',14),fg_color='#212c24'); textbox.pack(fill='both',expand=True,padx=24,pady=8); textbox.insert('1.0','Загрузка…'); textbox.configure(state='disabled')
        controls=ct.CTkFrame(window,fg_color='transparent'); controls.pack(fill='x',padx=24,pady=18)
        def language(original):
            value=getattr(window,'original_description' if original else 'russian_description','')
            if value:
                textbox.configure(state='normal'); textbox.delete('1.0','end'); textbox.insert('1.0',value); textbox.configure(state='disabled')
        ct.CTkButton(controls,text='Русский',width=100,command=lambda:language(False)).pack(side='left',padx=(0,8))
        ct.CTkButton(controls,text='Оригинал',width=100,fg_color='#314e3b',command=lambda:language(True)).pack(side='left')
        ct.CTkButton(controls,text=f'Скачать • {version}',width=175,command=lambda:self.start_mod_download(mod['project_id'],version,loader_type)).pack(side='right')
        threading.Thread(target=self.load_details,args=(mod,window,textbox,note),daemon=True).start()
    def load_details(self,mod,window,textbox,note):
        original=''; translated=''; error=''
        try:
            project=self.api('project/'+mod['project_id'])
            original=readable_description(project.get('body') or project['description'])
            try: translated=russian(original)
            except Exception: error='Сервис перевода недоступен. Показан оригинал описания.'
        except Exception: original=mod['description']; error='Не удалось загрузить подробное описание. Показано краткое.'
        self.events.put(('details',(window,textbox,note,original,translated,error)))
    def download_mod(self,mid,version,seen,pinned=None,target_folder=None,loader_type='fabric'):
        if mid in seen:return
        seen.add(mid)
        versions=[self.api('version/'+pinned)] if pinned else self.api(f'project/{mid}/version',{'game_versions':json.dumps([version]),'loaders':json.dumps([loader_type])})
        versions=[v for v in versions if version in v['game_versions'] and loader_type in v['loaders']]
        if not versions:raise ValueError(f'Нет совместимого {loader_type.title()}-файла для мода {mid}.')
        release=max(versions,key=lambda v:v['date_published'])
        for d in release.get('dependencies',[]):
            if d['dependency_type']=='required':
                dep=d.get('project_id')
                if not dep and d.get('version_id'):dep=self.api('version/'+d['version_id'])['project_id']
                if not dep:raise ValueError('У зависимости отсутствует проект Modrinth.')
                self.download_mod(dep,version,seen,d.get('version_id'),target_folder,loader_type)
        files=[f for f in release['files'] if f['filename'].endswith('.jar')]
        if not files:raise ValueError('В релизе нет JAR-файла.')
        f=next((f for f in files if f.get('primary')),files[0]); url=f['url']
        from urllib.parse import urlparse
        host=urlparse(url).hostname or ''
        if host!='cdn.modrinth.com' or not url.startswith('https://'):raise ValueError('Неожиданный адрес загрузки Modrinth.')
        name=f['filename']
        if Path(name).name!=name or not name.endswith('.jar'):raise ValueError('Недопустимое имя файла.')
        folder=target_folder or ROOT/'instances'/version/'mods'; folder.mkdir(parents=True,exist_ok=True)
        self.events.put(('status','Скачиваем '+name))
        r=requests.get(url,headers={'User-Agent':'CHUNKLauncher/1.1'},timeout=120); r.raise_for_status()
        for algo,expected in f['hashes'].items():
            if algo in ('sha512','sha1') and hashlib.new(algo,r.content).hexdigest()!=expected.lower():raise ValueError('Ошибка проверки файла.')
        tmp=folder/(name+'.part'); tmp.write_bytes(r.content); tmp.replace(folder/name)
        self.events.put(('status','Установлен: '+name))

if __name__=='__main__':
    try:
        Launcher().mainloop()
    except Exception:
        import traceback
        traceback.print_exc()
        raise

