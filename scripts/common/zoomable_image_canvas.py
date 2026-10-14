"""
共享组件：可缩放/平移的图片 Canvas。

提供：
- 图片加载与显示
- 原图坐标 ↔ 画布坐标转换
- 鼠标滚轮缩放（以光标为中心）
- 空格+拖动平移
- 适应窗口 / 100% 按钮
- 缩放比例显示
"""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

MIN_ZOOM = 0.25
MAX_ZOOM = 8.0
ZOOM_STEP = 1.15


class ZoomableImageCanvas(tk.Canvas):
    """可缩放和平移的图片 Canvas。"""

    def __init__(self, parent, on_click=None, on_draw_overlay=None,
                 bg="#222222", **kwargs):
        super().__init__(parent, bg=bg, highlightthickness=0, **kwargs)
        self._pil_original = None   # 原始 PIL 图片
        self._tk_image = None       # 当前显示的 PhotoImage
        self._img_w = 0
        self._img_h = 0
        self._zoom = 1.0
        self._offset_x = 0
        self._offset_y = 0

        # 外部回调
        self._on_click_callback = on_click
        self._on_draw_overlay_callback = on_draw_overlay

        # 平移状态
        self._is_pan_mode = False
        self._is_panning = False
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._pan_orig_offset_x = 0
        self._pan_orig_offset_y = 0

        # 绑定
        self.bind("<Button-1>", self._on_mouse_down)
        self.bind("<B1-Motion>", self._on_mouse_drag)
        self.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Button-4>", self._on_mousewheel_up)
        self.bind("<Button-5>", self._on_mousewheel_down)
        self.bind("<Configure>", self._on_resize)

        self._needs_initial_fit = True

    # ---- 坐标转换 ----

    def image_to_canvas(self, ix, iy):
        """原图坐标 → 画布坐标。"""
        return ix * self._zoom + self._offset_x, iy * self._zoom + self._offset_y

    def canvas_to_image(self, cx, cy):
        """画布坐标 → 原图坐标（夹紧到图片范围内）。"""
        ix = (cx - self._offset_x) / self._zoom
        iy = (cy - self._offset_y) / self._zoom
        if self._img_w > 0:
            ix = max(0, min(round(ix), self._img_w - 1))
        if self._img_h > 0:
            iy = max(0, min(round(iy), self._img_h - 1))
        return ix, iy

    @property
    def zoom_level(self):
        return self._zoom

    @property
    def image_size(self):
        return self._img_w, self._img_h

    def has_image(self):
        return self._pil_original is not None

    # ---- 图片加载 ----

    def load_image(self, path):
        """加载图片文件。"""
        self._pil_original = None
        self._tk_image = None
        self._img_w = self._img_h = 0
        self._needs_initial_fit = True
        if path and __import__('os').path.exists(path):
            try:
                self._pil_original = Image.open(path)
                self._img_w, self._img_h = self._pil_original.size
            except Exception:
                self._pil_original = None

    def load_pil_image(self, pil_image):
        """直接加载 PIL Image 对象。"""
        self._pil_original = pil_image
        self._tk_image = None
        self._needs_initial_fit = True
        if pil_image:
            self._img_w, self._img_h = pil_image.size
        else:
            self._img_w = self._img_h = 0

    # ---- 缩放 ----

    def fit_to_window(self):
        """适应窗口：缩放至图片完整可见并居中。"""
        if not self._pil_original:
            return
        cw = self.winfo_width()
        ch = self.winfo_height()
        if cw < 10 or ch < 10 or self._img_w <= 0 or self._img_h <= 0:
            return
        self._zoom = min(cw / self._img_w, ch / self._img_h, 1.0)
        self._center_image()
        self._redraw()

    def zoom_100(self):
        """1:1 显示。"""
        if not self._pil_original:
            return
        self._zoom = 1.0
        self._center_image()
        self._redraw()

    def zoom_in(self, cx=None, cy=None):
        """放大（以 (cx,cy) 画布坐标为中心）。"""
        self._apply_zoom(ZOOM_STEP, cx, cy)

    def zoom_out(self, cx=None, cy=None):
        """缩小（以 (cx,cy) 画布坐标为中心）。"""
        self._apply_zoom(1.0 / ZOOM_STEP, cx, cy)

    def _apply_zoom(self, factor, cx=None, cy=None):
        if not self._pil_original:
            return
        old_zoom = self._zoom
        new_zoom = old_zoom * factor
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
        if new_zoom == old_zoom:
            return

        # 以鼠标位置为缩放中心
        if cx is None or cy is None:
            cx = self.winfo_width() // 2
            cy = self.winfo_height() // 2

        # 鼠标指向的原图位置
        ix = (cx - self._offset_x) / old_zoom
        iy = (cy - self._offset_y) / old_zoom

        self._zoom = new_zoom
        # 调整偏移使同一点保持在鼠标位置
        self._offset_x = cx - ix * new_zoom
        self._offset_y = cy - iy * new_zoom
        self._redraw()

    def _center_image(self):
        """图片居中。"""
        cw = self.winfo_width()
        ch = self.winfo_height()
        if cw < 10 or ch < 10:
            return
        dw = self._img_w * self._zoom
        dh = self._img_h * self._zoom
        self._offset_x = (cw - dw) // 2
        self._offset_y = (ch - dh) // 2

    # ---- 平移 ----

    def enter_pan_mode(self):
        if self._pil_original:
            self._is_pan_mode = True
            self.configure(cursor="fleur")

    def exit_pan_mode(self):
        self._is_pan_mode = False
        self._is_panning = False
        self.configure(cursor="crosshair")

    # ---- 重绘 ----

    def _redraw(self):
        if not self._pil_original or self._img_w <= 0 or self._img_h <= 0:
            return
        self.delete("all")

        pw, ph = self._img_w, self._img_h
        new_w = max(1, int(pw * self._zoom))
        new_h = max(1, int(ph * self._zoom))

        # 从原始图片缩放（避免累计模糊）
        resized = self._pil_original.resize((new_w, new_h), Image.LANCZOS)
        self._tk_image = ImageTk.PhotoImage(resized)

        self.create_image(self._offset_x, self._offset_y,
                          image=self._tk_image, anchor=tk.NW, tags="img")

        # 回调：绘制覆盖层（关键点等）
        if self._on_draw_overlay_callback:
            self._on_draw_overlay_callback(self)

    def force_redraw(self):
        self._redraw()

    # ---- 鼠标事件 ----

    def _on_mouse_down(self, event):
        if not self._pil_original:
            return
        if self._is_pan_mode:
            self._is_panning = True
            self._pan_start_x = event.x
            self._pan_start_y = event.y
            self._pan_orig_offset_x = self._offset_x
            self._pan_orig_offset_y = self._offset_y
            return
        # 普通点击：传给回调
        if self._on_click_callback:
            ix, iy = self.canvas_to_image(event.x, event.y)
            self._on_click_callback(ix, iy, event.x, event.y)

    def _on_mouse_drag(self, event):
        if self._is_panning:
            dx = event.x - self._pan_start_x
            dy = event.y - self._pan_start_y
            self._offset_x = self._pan_orig_offset_x + dx
            self._offset_y = self._pan_orig_offset_y + dy
            self._redraw()

    def _on_mouse_up(self, event):
        self._is_panning = False

    def _on_mousewheel(self, event):
        """Windows/macOS 滚轮。"""
        if event.delta > 0:
            self.zoom_in(event.x, event.y)
        else:
            self.zoom_out(event.x, event.y)

    def _on_mousewheel_up(self, event):
        """Linux Button-4。"""
        self.zoom_in(event.x, event.y)

    def _on_mousewheel_down(self, event):
        """Linux Button-5。"""
        self.zoom_out(event.x, event.y)

    def _on_resize(self, event):
        """Canvas 尺寸变化时，首次达到可用尺寸时自动适应窗口。"""
        if self._needs_initial_fit:
            cw = self.winfo_width()
            ch = self.winfo_height()
            if cw >= 10 and ch >= 10 and self._pil_original:
                self._needs_initial_fit = False
                self.fit_to_window()
