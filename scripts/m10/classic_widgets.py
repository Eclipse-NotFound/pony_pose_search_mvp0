"""Small native controls used by the original-style annotation and result pages."""
import io
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk
from ui_components import ScrollPanel


class AnnotationList(tk.Listbox):
    """Keep all point/direction names visible, with stable keys and selection."""
    def __init__(self, parent, items=None):
        super().__init__(parent, exportselection=False, activestyle='none',
                         height=21, width=32, font=('Microsoft YaHei UI', 9))
        self.keys, self.names = [], {}
        self.set_items(items or {})

    def set_items(self, items, selected=None):
        old = selected or self.key()
        self.keys, self.names = list(items), dict(items)
        self.delete(0, 'end')
        for name in items.values():
            self.insert('end', name)
        if self.keys:
            self.choose(old if old in self.keys else self.keys[0])

    def key(self):
        selected = self.curselection()
        return self.keys[selected[0]] if selected and selected[0] < len(self.keys) else None

    def current(self, index=None):
        if index is None:
            return self.curselection()[0] if self.curselection() else -1
        if self.keys:
            index = max(0, min(index, len(self.keys)-1))
            self.selection_clear(0, 'end')
            self.selection_set(index)
            self.activate(index)
            self.see(index)

    def choose(self, key):
        if key in self.keys:
            self.current(self.keys.index(key))

    def show_states(self, values):
        selected, position = self.key(), self.yview()[0]
        lines = [('> ' if key == selected else '  ') + self.names[key] + '  ' + values.get(key, '—')
                 for key in self.keys]
        # Avoid replacing the selected row in response to its own selection event.
        if tuple(lines) == self.get(0, 'end'):
            return
        self.delete(0, 'end')
        for line in lines:
            self.insert('end', line)
        self.choose(selected)
        self.yview_moveto(position)


class ResultGallery(ttk.Frame):
    """M09's frame + crop result rows, rendered inside the native application."""
    def __init__(self, parent, host):
        super().__init__(parent)
        self.host, self.data, self.page = host, None, 0
        self.photos = []
        bar = ttk.Frame(self); bar.pack(side='bottom', fill='x')
        host.button(bar, '上一页', lambda: self.turn(-1))
        host.button(bar, '下一页', lambda: self.turn(1))
        self.count = ttk.Label(bar); self.count.pack(side='left', padx=6)
        self.scroll = ScrollPanel(self, width=650)
        self.scroll.pack(fill='both', expand=True)

    def render(self, data):
        self.data, self.page = data, 0
        self.draw()

    def turn(self, delta):
        maximum = max(0, (len((self.data or {}).get('results', []))-1)//8)
        self.page = max(0, min(self.page+delta, maximum))
        self.draw()

    def thumbnail(self, parent, image, size, title):
        box = ttk.Frame(parent); box.pack(side='left', padx=4)
        ttk.Label(box, text=title).pack()
        if image is None:
            ttk.Label(box, text='无留存原画面', width=24, anchor='center').pack(pady=35)
            return
        image.thumbnail(size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image, master=self)
        self.photos.append(photo)
        ttk.Label(box, image=photo).pack()

    def draw(self):
        for widget in self.scroll.content.winfo_children():
            widget.destroy()
        self.photos.clear()
        rows = (self.data or {}).get('results', [])
        self.count.configure(text=f'{len(rows)} 条结果 · 第 {self.page+1} / {max(1,(len(rows)+7)//8)} 页')
        if not rows:
            ttk.Label(self.scroll.content, text='尚无结果。到 M08 设置条件并搜索。').pack(pady=30)
        for index in range(self.page*8, min(len(rows), (self.page+1)*8)):
            row = rows[index]; info = row['location']
            record = self.host.session.library.read(row['observation_id'], row['annotation_id'])
            character = self.host.catalog.tables['characters'].get(record['subject'].get('character_ref'), {}).get('label', '身份未确认')
            group = ttk.LabelFrame(self.scroll.content,
                text=f"#{index+1}  {character}  ·  相似分 {row['score']:.3f}" + ('  ·  需左右翻转' if row['mirrored'] else ''), padding=5)
            group.pack(fill='x', pady=4)
            pictures = ttk.Frame(group); pictures.pack(fill='x')
            frame = None
            if info.get('position_id'):
                try:
                    with Image.open(self.host.session.sources.cached_image(info['position_id'])) as image:
                        frame = image.convert('RGB')
                except (OSError, ValueError):
                    pass
            self.thumbnail(pictures, frame, (320, 150), '原画面')
            try:
                raw, _ = self.host.session.library.image_bytes(row['image_ref'])
                with Image.open(io.BytesIO(raw)) as image:
                    crop = image.convert('RGBA')
                self.thumbnail(pictures, crop, (220, 150), '角色裁剪')
            except (OSError, ValueError):
                ttk.Label(pictures, text='裁剪图片不可用').pack(side='left')
            from ui_components import position_caption
            source_position = position_caption(info.get('position'))
            location = info['name'] + (' · '+source_position if source_position else '')
            caption = ttk.Label(group, text=location, wraplength=650)
            caption.pack(fill='x', pady=3)
            caption.bind('<Configure>', lambda e, w=caption: w.configure(wraplength=max(100,e.width)))
            from ui_components import Toolbar
            actions = Toolbar(group); actions.pack(fill='x')
            def action(fn, i=index):
                self.host.results.selection_set(str(i))
                return fn()
            for title, fn in [('查看原画面／帧号', self.host.open_result_source),
                              ('在文件夹中选中', self.host.locate_result),
                              ('复制素材位置', lambda r=row: self.host.copy_text(r['position_text'])),
                              ('查看命中标注', self.host.open_result_record)]:
                self.host.button(actions, title, lambda f=fn, a=action: a(f))
        self.scroll.canvas.yview_moveto(0)
        self.scroll._bind_wheel()
