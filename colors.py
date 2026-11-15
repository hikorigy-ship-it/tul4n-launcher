"""Persistent accent palettes shared by existing and newly created widgets."""
import colorsys
import copy
import re
import weakref
import tkinter as tk
import customtkinter as ct

PALETTES={'Синий':('#2563b8','#357bd5'), 'Голубой':('#087e9c','#109ebf'),
          'Черный':('#303036','#4a4a53'), 'Белый':('#e4e7ed','#ffffff'),
          'Фиолетовый':('#7042be','#8959db'), 'Зеленый':('#168653','#20a56a'),
          'Красный':('#b63343','#d94759')}
PALETTES.update({'Изумрудная':('#168653','#20a56a'),'Голубая':('#087e9c','#109ebf'),'Синяя':('#2563b8','#357bd5'),
 'Фиолетовая':('#7042be','#8959db'),'Красная':('#b63343','#d94759'),'Оранжевая':('#b65316','#d96826'),
 'Розовая':('#af3474','#d34c91'),'Золотая':('#9b7513','#bd921e'),'Бирюзовая':('#087e78','#119f97'),'Чёрно-белая':('#45454d','#666670')})
PRESET_NAMES=list(PALETTES)[7:]
current='Зеленый'
profile={'custom':{},'radius':None,'density':'Стандартные','style':'Классический','opacity':1.0}
_keys=weakref.WeakKeyDictionary()
_geometry=weakref.WeakKeyDictionary()
_widgets=weakref.WeakKeyDictionary()
_reverse={}
_applying=False
_defaults=copy.deepcopy(ct.ThemeManager.theme)

def valid_hex(value):return isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value) is not None

def set_profile(options):
    global profile
    options=options if isinstance(options,dict) else {}
    custom=options.get('custom',{})
    custom={k:v.lower() for k,v in custom.items() if k in ('accent','buttons','selection','panels') and valid_hex(v)} if isinstance(custom,dict) else {}
    radius=options.get('radius')
    if not isinstance(radius,int) or not 0<=radius<=24:radius=None
    opacity=options.get('opacity',1)
    if not isinstance(opacity,(int,float)):opacity=1
    profile={'custom':custom,'radius':radius,'density':options.get('density') if options.get('density') in ('Компактные','Стандартные') else 'Стандартные',
             'style':options.get('style') if options.get('style') in ('Классический','Мягкий','Контрастный') else 'Классический','opacity':max(.85,min(1,float(opacity)))}
    return copy.deepcopy(profile)

def luminance(value):
    rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
    return sum(w*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4) for w,v in zip((.2126,.7152,.0722),rgb))

def contrast(a,b):
    values=sorted((luminance(a),luminance(b)));return (values[1]+.05)/(values[0]+.05)

def color(value):
    if isinstance(value,(list,tuple)):return [color(v) for v in value]
    if not isinstance(value,str) or len(value)!=7 or not value.startswith('#'):return value
    primary,hover=PALETTES[current]
    primary=profile['custom'].get('accent',primary)
    if 'accent' in profile['custom']:
        rgb=[int(primary[i:i+2],16) for i in (1,3,5)];hover='#'+''.join(f'{min(255,round(v*.85+38)):02x}' for v in rgb)
    if value in ('#168653','#176b47','#126b43'):result=primary
    elif value in ('#20a56a','#229b65'):result=hover
    else:
        rgb=tuple(int(value[i:i+2],16)/255 for i in (1,3,5))
        h,s,v=colorsys.rgb_to_hsv(*rgb)
        if not .16<=h<=.49:return value
        target=tuple(int(primary[i:i+2],16)/255 for i in (1,3,5))
        hue=colorsys.rgb_to_hsv(*target)[0]
        if colorsys.rgb_to_hsv(*target)[1]<.15:s=0
        result='#'+''.join(f'{round(x*255):02x}' for x in colorsys.hsv_to_rgb(hue,s,v))
    if result!=value:_reverse[result]=value
    return result

def _colors(kwargs):return {k:v for k,v in kwargs.items() if k.endswith('_color') and v is not None}

def _contrast(widget,kwargs,parent=None):
    if not hasattr(widget,'_text_color') and 'text_color' not in kwargs:return
    fg=kwargs.get('fg_color',getattr(widget,'_fg_color','transparent'))
    if isinstance(fg,(list,tuple)):fg=fg[-1]
    ancestor=parent or getattr(widget,'master',None)
    while not valid_hex(fg) and ancestor is not None:
        fg=getattr(ancestor,'_fg_color','transparent');ancestor=getattr(ancestor,'master',None)
        if isinstance(fg,(list,tuple)):fg=fg[-1]
    if valid_hex(fg):
        text=kwargs.get('text_color',getattr(widget,'_text_color','#ffffff'))
        if isinstance(text,(list,tuple)):text=text[-1]
        if not valid_hex(text) or contrast(text,fg)<4.5:
            dark='#111318' if contrast('#111318',fg)>=4.5 else '#000000'
            kwargs['text_color']=max((dark,'#ffffff'),key=lambda choice:contrast(choice,fg))

def _options(key,base,widget=None):
    result={k:color(v) for k,v in base.items()};custom=profile['custom']
    for option,value in list(result.items()):
        raw=base[option]
        if option in ('segmented_button_selected_color','selected_color') and custom.get('selection'):result[option]=custom['selection']
        elif option in ('fg_color','button_color') and key in ('CTkButton','CTkOptionMenu') and raw!='transparent' and custom.get('buttons'):result[option]=custom['buttons']
        elif option=='hover_color' and key in ('CTkButton','CTkOptionMenu') and custom.get('buttons'):
            rgb=[int(custom['buttons'][i:i+2],16) for i in (1,3,5)];result[option]='#'+''.join(f'{min(255,round(v*.8+42)):02x}' for v in rgb)
        elif option=='fg_color' and key in ('CTkFrame','CTkTabview','CTkTextbox') and raw!='transparent':
            if custom.get('panels'):result[option]=custom['panels']
            elif profile['style']=='Контрастный':result[option]='#0b0d0f'
            elif profile['style']=='Мягкий' and valid_hex(value):result[option]='#'+''.join(f'{min(255,int(value[i:i+2],16)+12):02x}' for i in (1,3,5))
        elif option=='border_color' and profile['style']=='Контрастный':result[option]='#76847e'
    if widget is not None and getattr(widget,'_selection_accent',False) and custom.get('selection') and base.get('fg_color')!='transparent':result['fg_color']=custom['selection']
    return result

def install():
    for cls,key in [(ct.CTkFrame,'CTkFrame'),(ct.CTkButton,'CTkButton'),
                    (ct.CTkOptionMenu,'CTkOptionMenu'),(ct.CTkEntry,'CTkEntry'),
                    (ct.CTkLabel,'CTkLabel'),(ct.CTkTextbox,'CTkTextbox'),
                    (ct.CTkProgressBar,'CTkProgressBar'),(ct.CTkScrollbar,'CTkScrollbar'),
                    (ct.CTkSegmentedButton,'CTkSegmentedButton'),(ct.CTkTabview,'CTkTabview'),(ct.CTkSwitch,'CTkSwitch')]:
        init,configure=cls.__init__,cls.configure
        def themed_init(self,*args,_init=init,_key=key,**kwargs):
            base={k:_reverse.get(v,v) if isinstance(v,str) and k not in ('text_color','text_color_disabled') else v for k,v in _colors(kwargs).items()}
            defaults={k:v for k,v in _defaults.get(_key,{}).items() if k.endswith('_color') and v is not None}
            kwargs.update(_options(_key,base,self))
            if _key in ('CTkButton','CTkOptionMenu') and 'fg_color' in defaults:
                kwargs.setdefault('fg_color',_options(_key,defaults,self)['fg_color'])
            if 'text_color' in defaults:kwargs.setdefault('text_color',color(defaults['text_color']))
            _contrast(self,kwargs,args[0] if args else kwargs.get('master'))
            original_radius=kwargs.get('corner_radius',_defaults.get(_key,{}).get('corner_radius'))
            if original_radius is None:original_radius=_defaults.get(_key,{}).get('corner_radius')
            if profile['radius'] is not None and 'corner_radius' in _defaults.get(_key,{}) and kwargs.get('height',20)>5:kwargs['corner_radius']=profile['radius']
            _init(self,*args,**kwargs)
            defaults.update(base)
            _widgets[self]={k:v for k,v in defaults.items() if hasattr(self,'_'+k)}
            _keys[self]=_key
            if hasattr(self,'_corner_radius'):
                _geometry[self]=original_radius if original_radius is not None else getattr(self,'_corner_radius')
        def themed_configure(self,*args,_configure=configure,_key=key,**kwargs):
            if not _applying:
                base=_colors(kwargs)
                _widgets.setdefault(self,{}).update(base)
                kwargs.update(_options(_keys.get(self,_key),base,self))
                _contrast(self,kwargs)
            return _configure(self,*args,**kwargs)
        cls.__init__,cls.configure=themed_init,themed_configure

def select(name):
    global current,_applying
    current=name if name in PALETTES else 'Зеленый'
    for key,values in _defaults.items():
        for option,value in values.items():
            if option.endswith('_color'):ct.ThemeManager.theme[key][option]=_options(key,{option:value})[option]
    _applying=True
    try:
        for widget,base in list(_widgets.items()):
            try:
                if not widget.winfo_exists():continue
            except tk.TclError:
                _widgets.pop(widget,None);continue
            options=_options(_keys.get(widget,''),base,widget)
            if widget in _geometry:
                options['corner_radius']=profile['radius'] if profile['radius'] is not None and getattr(widget,'_current_height',20)>5 else _geometry[widget]
            _contrast(widget,options)
            widget.configure(**options)
    finally:_applying=False

def recolor_canvas(canvas):
    originals=getattr(canvas,'_palette_items',{})
    for item in canvas.find_all():
        for option in ('fill','outline'):
            try:
                value=canvas.itemcget(item,option)
                key=(item,option)
                originals.setdefault(key,_reverse.get(value,value))
                if value:canvas.itemconfigure(item,**{option:color(originals[key])})
            except Exception:pass
    canvas._palette_items=originals

