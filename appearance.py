"""Immediate, persistent appearance controls using the existing theme registry."""
import copy
import tkinter as tk
from tkinter import colorchooser
import customtkinter as ct
import colors


class AppearancePanel:
    def __init__(self,app,parent):
        self.app=app;self.entries={};self.opacity_job=None
        app.label(parent,'Оформление',22)
        row=ct.CTkFrame(parent,fg_color='transparent');row.pack(fill='x',pady=4)
        ct.CTkLabel(row,text='Цветовая схема',width=200,anchor='w').pack(side='left')
        app.color_menu=ct.CTkOptionMenu(row,values=colors.PRESET_NAMES,command=app.change_color,width=200);app.color_menu.set(colors.current);app.color_menu.pack(side='left')
        for key,title in [('accent','Основной акцент'),('buttons','Цвет кнопок'),('selection','Выделенные элементы'),('panels','Панели и карточки')]:
            row=ct.CTkFrame(parent,fg_color='transparent');row.pack(fill='x',pady=3)
            ct.CTkLabel(row,text=title,width=200,anchor='w').pack(side='left')
            entry=ct.CTkEntry(row,width=130,placeholder_text='#RRGGBB');entry.pack(side='left',padx=(0,8));self.entries[key]=entry
            entry.bind('<Return>',lambda _,k=key:self.apply_hex(k));entry.bind('<FocusOut>',lambda _,k=key:self.apply_hex(k,quiet=True))
            ct.CTkButton(row,text='Палитра',width=100,height=28,command=lambda k=key:self.pick(k)).pack(side='left')
        row=ct.CTkFrame(parent,fg_color='transparent');row.pack(fill='x',pady=8)
        self.style=ct.CTkOptionMenu(row,values=['Классический','Мягкий','Контрастный'],width=175,command=lambda v:self.option('style',v));self.style.pack(side='left',padx=(0,8))
        self.radius=ct.CTkOptionMenu(row,values=['Исходные углы','0','4','8','12','16','20','24'],width=140,command=lambda v:self.option('radius',None if v=='Исходные углы' else int(v)));self.radius.pack(side='left',padx=(0,8))
        self.density=ct.CTkOptionMenu(row,values=['Стандартные','Компактные'],width=150,command=lambda v:self.option('density',v));self.density.pack(side='left')
        row=ct.CTkFrame(parent,fg_color='transparent');row.pack(fill='x',pady=4)
        ct.CTkLabel(row,text='Непрозрачность окна',width=200,anchor='w').pack(side='left')
        self.alpha=ct.CTkSlider(row,from_=.85,to=1,number_of_steps=15,width=200,command=self.set_opacity);self.alpha.pack(side='left',padx=(0,10))
        self.alpha_label=ct.CTkLabel(row,text='100%');self.alpha_label.pack(side='left')
        self.preview=ct.CTkFrame(parent,fg_color='#202425',border_width=1,border_color='#3b4242');self.preview.pack(fill='x',pady=8)
        ct.CTkLabel(self.preview,text='Предпросмотр • TUL4N',font=('Segoe UI',16,'bold')).pack(anchor='w',padx=12,pady=(8,0))
        ct.CTkLabel(self.preview,text='Изменения сразу видны во всём лаунчере.').pack(anchor='w',padx=12)
        ct.CTkButton(self.preview,text='Пример кнопки',width=180).pack(anchor='w',padx=12,pady=8)
        self.note=ct.CTkLabel(parent,text='HEX: #RRGGBB. Цвета сохраняются автоматически.',wraplength=700,anchor='w');self.note.pack(fill='x')
        ct.CTkButton(parent,text='Сбросить оформление',fg_color='#344f40',command=self.reset).pack(anchor='w',pady=10)
        self.sync()
    def sync(self):
        profile=colors.profile;custom=profile['custom'];accent=custom.get('accent',colors.PALETTES[colors.current][0])
        defaults={'accent':accent,'buttons':accent,'selection':accent,'panels':'#202425'}
        for key,entry in self.entries.items():entry.delete(0,'end');entry.insert(0,custom.get(key,defaults[key]))
        self.style.set(profile['style']);self.radius.set(str(profile['radius']) if profile['radius'] is not None else 'Исходные углы');self.density.set(profile['density']);self.alpha.set(profile['opacity']);self.alpha_label.configure(text=f'{round(profile["opacity"]*100)}%')
    def apply_hex(self,key,quiet=False):
        value=self.entries[key].get().strip()
        if not colors.valid_hex(value):
            if not quiet:self.note.configure(text='Введите цвет в формате #RRGGBB, например #22aa77.')
            return
        if value.lower()==colors.profile['custom'].get(key):return
        options=copy.deepcopy(colors.profile);options['custom'][key]=value.lower();self.commit(options)
        self.note.configure(text='Цвет сохранён. Контраст текста подбирается автоматически.')
    def pick(self,key):
        initial=self.entries[key].get().strip();initial=initial if colors.valid_hex(initial) else '#168653'
        selected=colorchooser.askcolor(initialcolor=initial,parent=self.app,title='Цвет TUL4N')[1]
        if selected:self.entries[key].delete(0,'end');self.entries[key].insert(0,selected);self.apply_hex(key)
    def option(self,key,value):
        options=copy.deepcopy(colors.profile);options[key]=value;self.commit(options,refresh_cards=key=='density')
    def commit(self,options,refresh_cards=False):
        self.app.cfg['appearance']=colors.set_profile(options);self.app.apply_appearance(refresh_cards);self.app.save()
    def set_opacity(self,value):
        value=round(float(value),2);self.alpha_label.configure(text=f'{round(value*100)}%')
        try:self.app.attributes('-alpha',value)
        except tk.TclError:self.note.configure(text='Прозрачность окна недоступна в этой системе.');return
        if self.opacity_job:self.app.after_cancel(self.opacity_job)
        def save():
            self.opacity_job=None;options=copy.deepcopy(colors.profile);options['opacity']=value
            self.app.cfg['appearance']=colors.set_profile(options);self.app.save()
        self.opacity_job=self.app.after(250,save)
    def reset(self):
        self.app.cfg['color']='Изумрудная';self.app.cfg['appearance']=colors.set_profile({});self.app.color_menu.set('Изумрудная');self.app.apply_appearance(True);self.app.save();self.sync();self.note.configure(text='Исходное оформление восстановлено.')
    def close(self):
        if self.opacity_job:
            self.app.after_cancel(self.opacity_job);self.opacity_job=None
            options=copy.deepcopy(colors.profile);options['opacity']=self.alpha.get();self.app.cfg['appearance']=colors.set_profile(options);self.app.save()

