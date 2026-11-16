"""Rounded launcher menus with mouse and keyboard navigation."""
import tkinter as tk
import time
import weakref
import customtkinter as ct
import i18n
from hover import AnimatedButton


class StyledOptionMenu(ct.CTkOptionMenu):
    _instances = weakref.WeakSet()

    def __init__(self, *args, **kwargs):
        self._popup = None
        super().__init__(*args, **kwargs)
        self._instances.add(self)
        self.bind('<KeyPress-space>', lambda event: self._open_dropdown_menu(), add='+')
        self.bind('<KeyPress-Return>', lambda event: self._open_dropdown_menu(), add='+')
        self.refresh_translation()

    def refresh_translation(self):
        self._text_label.configure(text=i18n.tr(self.get()))

    def set(self,value):
        super().set(value);self.refresh_translation()

    def _variable_callback(self,*args):
        super()._variable_callback(*args);self.refresh_translation()

    def _dropdown_callback(self,value):
        super()._dropdown_callback(value);self.refresh_translation()

    def _close_popup(self):
        popup, self._popup = self._popup, None
        if popup is not None:
            try:
                popup.grab_release()
                popup.destroy()
                self.winfo_toplevel().focus_force()
            except tk.TclError:
                pass

    @classmethod
    def close_all(cls):
        for menu in list(cls._instances):
            menu._close_popup()

    def _open_dropdown_menu(self):
        if self._popup is not None:
            self._close_popup()
            return
        if self._state == 'disabled' or not self._values:
            return
        popup = self._popup = tk.Toplevel(self)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())
        popup.wm_attributes('-topmost', True)
        popup.configure(bg='#010203')
        if self.tk.call('tk', 'windowingsystem') == 'win32':
            popup.wm_attributes('-transparentcolor', '#010203')
        panel = ct.CTkFrame(popup, fg_color='#19271c', corner_radius=12,
                            border_width=1, border_color='#365f47')
        panel.pack(fill='both', expand=True)
        count = len(self._values)
        width = max(self.winfo_width(), int(self._apply_widget_scaling(156)))
        height = int(self._apply_widget_scaling(min(count, 8)*40+16))
        x = min(self.winfo_rootx(), self.winfo_screenwidth()-width-8)
        y = self.winfo_rooty()+self.winfo_height()+5
        if y+height > self.winfo_screenheight()-40:
            y = max(8, self.winfo_rooty()-height-5)
        popup.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        if count > 8:
            body = ct.CTkScrollableFrame(panel, fg_color='transparent', corner_radius=0,
                                        scrollbar_button_color='#365f47')
            body.pack(fill='both', expand=True, padx=6, pady=8)
        else:
            body = panel
        buttons = []
        selected = [self._values.index(self.get()) if self.get() in self._values else 0]

        def choose(value):
            self._close_popup()
            self._dropdown_callback(value)

        def highlight(index):
            selected[0] = index % count
            for i, button in enumerate(buttons):
                button.configure(fg_color='#176b47' if i == selected[0] else 'transparent')
            buttons[selected[0]].focus_set()
            return 'break'

        for index, value in enumerate(self._values):
            button = AnimatedButton(body, text=('✓  ' if value == self.get() else '    ')+value,
                height=30, corner_radius=7, anchor='w', font=('Segoe UI',13),
                fg_color='#176b47' if index == selected[0] else 'transparent',
                hover_color='#229b65', text_color='#eafaf1',
                command=lambda v=value: choose(v))
            button.pack(fill='x', padx=7, pady=(8 if index == 0 and count <= 8 else 2,2))
            button.bind('<Return>', lambda event,v=value: choose(v), add='+')
            buttons.append(button)
        popup.bind('<Escape>', lambda event:self._close_popup())
        popup.bind('<Up>', lambda event:highlight(selected[0]-1))
        popup.bind('<Down>', lambda event:highlight(selected[0]+1))

        def outside(event):
            if not (popup.winfo_rootx() <= event.x_root < popup.winfo_rootx()+popup.winfo_width()
                    and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty()+popup.winfo_height()):
                self._close_popup()
        popup.bind('<ButtonPress-1>', outside, add='+')
        popup.deiconify()
        popup.update_idletasks()
        popup.lift()
        popup.focus_force()
        popup.grab_set()
        buttons[selected[0]].focus_set()
        started = time.monotonic()
        def reveal():
            if self._popup is not popup or not popup.winfo_exists():
                return
            progress = min(1, (time.monotonic()-started)/.14)
            popup.wm_attributes('-alpha', .82+.18*(1-(1-progress)**3))
            if progress < 1:
                popup.after(16,reveal)
        reveal()

    def destroy(self):
        self._close_popup()
        super().destroy()


class FocusedEntry(ct.CTkEntry):
    """Return native keyboard focus after closing a borderless dropdown."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._entry.bind('<Button-1>', self._focus_input, add='+')

    def _focus_input(self, event):
        StyledOptionMenu.close_all()
        self._entry.focus_force()

