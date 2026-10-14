"""Shared visual language and resizing behavior for the native M10 window."""
import tkinter as tk
from tkinter import ttk, font

COLORS = dict(canvas='#202632', line='#c8c8c8')


def position_caption(position):
    """Use the source's own timeline instead of labelling every picture a video."""
    position = position or {}
    if position.get('kind') == 'fla_frame':
        kind = '元件' if position.get('timeline_kind') == 'symbol' else '场景'
        name = position.get('timeline_name') or position.get('timeline_id') or '未命名时间轴'
        ordinal = position.get('frame_index0')
        return f'{kind}：{name}' + (f' · 第 {ordinal+1} 工程帧' if ordinal is not None else '')
    ordinal = position.get('presentation_ordinal0')
    if ordinal is not None:
        return f'第 {ordinal+1} 视频帧'
    return '原图' if position.get('precision') == 'image_exact' or position.get('kind') == 'image' else ''


def install_theme(widget):
    """Use ordinary platform controls, like the original M10 control center."""
    style=ttk.Style(widget)
    if bool(int(widget.tk.call('info','exists','pony_classic_style'))):
        return
    widget.tk.call('set','pony_classic_style','1')
    if 'vista' in style.theme_names():
        style.theme_use('vista')
    for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont'):
        font.nametofont(name,root=widget).configure(family='Microsoft YaHei UI',size=9)
    background=style.lookup('TFrame','background') or 'SystemButtonFace'
    style.configure('App.TFrame',background=background)
    style.configure('Muted.TLabel',foreground='#4f5962')
    style.configure('Title.TLabel',font=('Microsoft YaHei UI',11,'bold'))
    style.configure('Section.TLabel',font=('Microsoft YaHei UI',9,'bold'))
    style.configure('Badge.TLabel',font='TkDefaultFont')
    # These aliases deliberately retain the platform button border and feedback.
    for name in ('Primary.TButton','Quiet.TButton','Compact.TButton'):
        style.configure(name,padding=(5,2))
    style.configure('Nav.TButton',anchor='w',padding=(7,3))
    style.configure('Active.Nav.TButton',anchor='w',padding=(7,3))
    lineheight=font.nametofont('TkDefaultFont',root=widget).metrics('linespace')
    style.configure('Treeview',rowheight=max(22,lineheight+5))
    style.configure('TPanedwindow',sashwidth=6)
    style.configure('Module.TNotebook',borderwidth=0)
    style.layout('Module.TNotebook.Tab',[])
    widget.option_add('*Text.relief','sunken')
    widget.option_add('*Text.borderWidth',1)
    widget.option_add('*Text.highlightThickness',0)
    widget.option_add('*Text.padX',4)
    widget.option_add('*Text.padY',3)
    widget.option_add('*TCombobox*Listbox.font','TkDefaultFont')


class Toolbar(ttk.Frame):
    """Wrap actions as a window narrows, preserving their order and tab stops."""
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._layout_id = None
        self.bind('<Configure>', self._schedule)
        self.bind('<Map>', self._schedule)
        self.bind('<Destroy>', self._destroy, add='+')

    def _destroy(self, event):
        if event.widget == self and self._layout_id:
            self.after_cancel(self._layout_id)
            self._layout_id = None

    def _schedule(self, event=None):
        if not self._layout_id:
            self._layout_id = self.after_idle(self._layout)

    def _layout(self):
        self._layout_id = None
        available = self.winfo_width()
        if available < 10:
            return
        x = y = row_height = 0
        for child in self.winfo_children():
            if isinstance(child, tk.Toplevel):
                continue
            width = min(child.winfo_reqwidth(), available)
            height = child.winfo_reqheight()
            if x and x + width > available:
                x = 0
                y += row_height + 5
                row_height = 0
            if child.winfo_manager() == 'pack':
                child.pack_forget()
            child.place(x=x, y=y, width=width, height=height)
            x += width + 6
            row_height = max(row_height, height)
        self.configure(height=max(1, y + row_height + 5))


class ScrollPanel(ttk.Frame):
    """A real vertical settings panel; wheel is confined to this panel."""
    def __init__(self, parent, width=285):
        super().__init__(parent, width=width)
        self.canvas = tk.Canvas(self, width=width, height=1, background=ttk.Style(self).lookup('TFrame','background'), highlightthickness=0)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.content = ttk.Frame(self.canvas, padding=(4, 2, 6, 4))
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.content.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.item, width=e.width))
        self.bind('<Map>', self._bind_wheel)

    def _bind_wheel(self, event=None):
        def bind_children(widget):
            # Combobox arrows/keys remain available; wheel scrolls the panel,
            # never changes a selected annotation field accidentally.
            widget.bind('<MouseWheel>', self._wheel)
            for child in widget.winfo_children():
                bind_children(child)
        bind_children(self.content)
        self.canvas.bind('<MouseWheel>', self._wheel)

    def _wheel(self, event):
        bounds = self.canvas.bbox('all')
        if bounds and bounds[3] > self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'


class FieldGroup(ttk.LabelFrame):
    """Visible settings with a plain group label; no hidden workflow controls."""
    def __init__(self,parent,title):
        super().__init__(parent,text=title,padding=(4,3))
        self.content=ttk.Frame(self)
        self.content.pack(fill='x')


def section(parent, title, note=None):
    ttk.Label(parent, text=title, style='Section.TLabel').pack(anchor='w', pady=(2,3))
    if note:
        widget = ttk.Label(parent, text=note, style='Muted.TLabel', wraplength=260)
        widget.pack(fill='x', pady=(0,3))
        widget.bind('<Configure>', lambda e: widget.configure(wraplength=max(80, e.width)))


def dialog_form(window):
    """Keep longer forms usable when text is larger than a fixed dialog height."""
    panel=ScrollPanel(window,width=460)
    panel.pack(fill='both',expand=True,padx=8,pady=8)
    window.minsize(380,220)
    def fit(event):
        if event.widget!=window:return
        window.unbind('<Map>',binding)
        def resize():
            width=min(window.winfo_screenwidth()-60,max(480,panel.content.winfo_reqwidth()+40))
            height=min(window.winfo_screenheight()-120,max(240,panel.content.winfo_reqheight()+28))
            window.geometry(f'{width}x{height}')
        window.after_idle(resize)
    binding=window.bind('<Map>',fit,add='+')
    return panel.content


def split(parent, widths, weights=None):
    """Set useful initial column ratios instead of propagating long label widths."""
    panes = ttk.Panedwindow(parent, orient='horizontal')
    panes.pack(fill='both', expand=True)
    frames = [ttk.Frame(panes, width=w) for w in widths]
    for frame, weight in zip(frames, weights or [1]*len(widths)):
        panes.add(frame, weight=weight)
    def initialize(event):
        if event.widget != panes or panes.winfo_width() < 100:
            return
        total = sum(widths)
        available = panes.winfo_width()
        for i in range(len(widths)-1):
            panes.sashpos(i, round(available*sum(widths[:i+1])/total))
        panes.unbind('<Configure>', binding)
    binding = panes.bind('<Configure>', initialize)
    return panes, frames
