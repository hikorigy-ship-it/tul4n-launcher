"""Short, cancellable hover transitions without resizing or relaying out widgets."""
import time
import tkinter as tk
import customtkinter as ct


class AnimatedButton(ct.CTkButton):
    def __init__(self, *args, **kwargs):
        self._fade_job = None
        self._fade_color = None
        self._lift = 0
        self._lift_padding = None
        super().__init__(*args, **kwargs)

    def pack(self, **kwargs):
        padding = kwargs.get('pady', 0)
        if isinstance(padding, (tuple, list)):
            top, bottom = padding
        else:
            top = bottom = padding
        self._lift_padding = (float(top)+3, float(bottom)+3)
        kwargs['pady'] = self._lift_padding
        return super().pack(**kwargs)

    def _paint_lift(self, offset):
        self._lift = offset
        if self._lift_padding is not None and self.winfo_manager() == 'pack':
            top, bottom = self._lift_padding
            # Constant total padding reserves the movement; siblings stay still.
            tk.Pack.pack_configure(self, pady=(round(self._apply_widget_scaling(top+offset)),
                                              round(self._apply_widget_scaling(bottom-offset))))

    def _cancel_fade(self):
        if self._fade_job is not None:
            self.after_cancel(self._fade_job)
            self._fade_job = None

    def _paint(self, color):
        self._canvas.itemconfig('inner_parts', fill=color, outline=color)
        for label in (self._text_label, self._image_label):
            if label is not None:
                label.configure(bg=color)
        self._fade_color = color

    def _transition(self, hovered):
        self._cancel_fade()
        base = self._bg_color if self._fg_color == 'transparent' else self._fg_color
        target = self._hover_color if hovered and self._hover_color else base
        target = self._apply_appearance_mode(target)
        start = self._fade_color or self._apply_appearance_mode(base)
        rgb_start = self.winfo_rgb(start)
        rgb_target = self.winfo_rgb(target)
        started = time.monotonic()
        lift_start = self._lift
        lift_target = -3 if hovered else 0

        def frame():
            self._fade_job = None
            try:
                if not self.winfo_exists() or not self.winfo_ismapped():
                    self._fade_color = None
                    return
                progress = min(1.0, (time.monotonic() - started) / 0.16)
                eased = 1 - (1 - progress) ** 3
                color = '#' + ''.join(f'{round((a + (b-a)*eased)/257):02x}'
                                      for a, b in zip(rgb_start, rgb_target))
                self._paint(color)
                self._paint_lift(lift_start+(lift_target-lift_start)*eased)
                if progress < 1:
                    self._fade_job = self.after(16, frame)
            except tk.TclError:
                self._fade_job = None
        frame()

    def _on_enter(self, event=None):
        if self._hover and self._state == 'normal':
            self._transition(True)

    def _on_leave(self, event=None):
        self._click_animation_running = False
        self._transition(False)

    def configure(self, require_redraw=False, **kwargs):
        if any(key in kwargs for key in ('state', 'fg_color', 'hover_color')):
            self._cancel_fade()
            self._fade_color = None
            self._paint_lift(0)
        return super().configure(require_redraw=require_redraw, **kwargs)

    def destroy(self):
        self._cancel_fade()
        super().destroy()

