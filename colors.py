"""Persistent accent palettes shared by existing and newly created widgets."""
import colorsys
import copy
import weakref
import tkinter as tk
import customtkinter as ct

PALETTES={'Синий':('#2563b8','#357bd5'), 'Голубой':('#087e9c','#109ebf'),
          'Черный':('#303036','#4a4a53'), 'Белый':('#e4e7ed','#ffffff'),
          'Фиолетовый':('#7042be','#8959db'), 'Зеленый':('#168653','#20a56a'),
          'Красный':('#b63343','#d94759')}
current='Зеленый'
_widgets=weakref.WeakKeyDictionary()
_reverse={}
_applying=False
_defaults=copy.deepcopy(ct.ThemeManager.theme)

def color(value):
    if isinstance(value,(list,tuple)):return [color(v) for v in value]
    if not isinstance(value,str) or len(value)!=7 or not value.startswith('#'):return value
    primary,hover=PALETTES[current]
    if value in ('#168653','#176b47','#126b43'):result=primary
    elif value in ('#20a56a','#229b65'):result=hover
    else:
        rgb=tuple(int(value[i:i+2],16)/255 for i in (1,3,5))
        h,s,v=colorsys.rgb_to_hsv(*rgb)
        if not .16<=h<=.49:return value
        target=tuple(int(primary[i:i+2],16)/255 for i in (1,3,5))
        hue=colorsys.rgb_to_hsv(*target)[0]
        if current in ('Черный','Белый'):s=0
        result='#'+''.join(f'{round(x*255):02x}' for x in colorsys.hsv_to_rgb(hue,s,v))
    if result!=value:_reverse[result]=value
    return result

def _colors(kwargs):return {k:v for k,v in kwargs.items() if k.endswith('_color') and v is not None}

def _contrast(widget,kwargs):
    if not isinstance(widget,(ct.CTkButton,ct.CTkOptionMenu)):return
    fg=kwargs.get('fg_color',getattr(widget,'_fg_color','transparent'))
    if isinstance(fg,(list,tuple)):fg=fg[-1]
    if isinstance(fg,str) and fg.startswith('#') and len(fg)==7:
        rgb=[int(fg[i:i+2],16) for i in (1,3,5)]
        if sum(rgb)/3>180:kwargs['text_color']='#111318'

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
            kwargs.update({k:color(v) for k,v in base.items()})
            if _key in ('CTkButton','CTkOptionMenu') and 'fg_color' in defaults:
                kwargs.setdefault('fg_color',color(defaults['fg_color']))
            _contrast(self,kwargs)
            _init(self,*args,**kwargs)
            defaults.update(base)
            _widgets[self]={k:v for k,v in defaults.items() if hasattr(self,'_'+k)}
        def themed_configure(self,*args,_configure=configure,**kwargs):
            if not _applying:
                base=_colors(kwargs)
                _widgets.setdefault(self,{}).update(base)
                kwargs.update({k:color(v) for k,v in base.items()})
                _contrast(self,kwargs)
            return _configure(self,*args,**kwargs)
        cls.__init__,cls.configure=themed_init,themed_configure

def select(name):
    global current,_applying
    current=name if name in PALETTES else 'Зеленый'
    for key,values in _defaults.items():
        for option,value in values.items():
            if option.endswith('_color'):ct.ThemeManager.theme[key][option]=color(value)
    _applying=True
    try:
        for widget,base in list(_widgets.items()):
            try:
                if not widget.winfo_exists():continue
            except tk.TclError:
                _widgets.pop(widget,None);continue
            options={k:color(v) for k,v in base.items()}
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

