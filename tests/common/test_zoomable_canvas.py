"""ZoomableImageCanvas 测试 — 坐标转换、缩放、平移。"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "common"))
from zoomable_image_canvas import ZoomableImageCanvas, MIN_ZOOM, MAX_ZOOM


class TestCoordinateConversion:
    """image_to_canvas / canvas_to_image 转换。"""

    def test_identity(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 1.0
        z._offset_x = 0
        z._offset_y = 0
        z._img_w = 200
        z._img_h = 150

        cx, cy = z.image_to_canvas(50, 80)
        assert (cx, cy) == (50, 80)
        ix, iy = z.canvas_to_image(50, 80)
        assert (ix, iy) == (50, 80)

    def test_scaled(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 2.0
        z._offset_x = 100
        z._offset_y = 50
        z._img_w = 200
        z._img_h = 150

        cx, cy = z.image_to_canvas(50, 80)
        assert cx == 200  # 50*2 + 100
        assert cy == 210  # 80*2 + 50

    def test_canvas_to_image_clamped(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 1.0
        z._offset_x = 0
        z._offset_y = 0
        z._img_w = 200
        z._img_h = 150

        # 超出范围被夹紧
        ix, iy = z.canvas_to_image(300, -10)
        assert ix == 199  # clamped to img_w-1
        assert iy == 0

    def test_roundtrip(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 0.6
        z._offset_x = 30
        z._offset_y = 20
        z._img_w = 320
        z._img_h = 240

        for ox, oy in [(0, 0), (50, 80), (319, 239)]:
            cx, cy = z.image_to_canvas(ox, oy)
            ix, iy = z.canvas_to_image(cx, cy)
            assert ix == ox, f"roundtrip: {ox},{oy} → {cx},{cy} → {ix},{iy}"
            assert iy == oy


class TestZoomBounds:
    """缩放范围限制。"""

    def test_zoom_in_applies_factor(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 1.0
        z._img_w = 100; z._img_h = 100
        z._offset_x = 0; z._offset_y = 0
        z._pil_original = True
        z._redraw = lambda: None  # skip Canvas redraw

        z._apply_zoom(1.5, 50, 50)
        assert z._zoom == 1.5

    def test_zoom_clamped_to_max(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 7.5
        z._img_w = 100; z._img_h = 100
        z._offset_x = 0; z._offset_y = 0
        z._pil_original = True
        z._redraw = lambda: None

        z._apply_zoom(1.5, 50, 50)
        assert z._zoom == MAX_ZOOM

    def test_zoom_clamped_to_min(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 0.3
        z._img_w = 100; z._img_h = 100
        z._offset_x = 0; z._offset_y = 0
        z._pil_original = True
        z._redraw = lambda: None

        z._apply_zoom(0.5, 50, 50)
        assert z._zoom == MIN_ZOOM


class TestFitToWindow:
    """适应窗口计算。"""

    def test_fit_ratio(self):
        """适应窗口缩放比例正确。"""
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._img_w = 200
        z._img_h = 150

        def fake_width(): return 400
        def fake_height(): return 300
        z.winfo_width = fake_width
        z.winfo_height = fake_height
        z._pil_original = True  # has image
        z._redraw = lambda: None

        z.fit_to_window()
        # scale = min(400/200, 300/150) = min(2.0, 2.0) = 2.0, then min(2.0, 1.0) = 1.0
        assert z._zoom == 1.0

    def test_fit_smaller_canvas(self):
        """Canvas 小于图片时缩小。"""
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._img_w = 800
        z._img_h = 600

        def fake_width(): return 400
        def fake_height(): return 300
        z.winfo_width = fake_width
        z.winfo_height = fake_height
        z._pil_original = True
        z._redraw = lambda: None

        z.fit_to_window()
        assert z._zoom == pytest.approx(0.5)


class TestMouseCenterZoom:
    """鼠标中心缩放：缩放前后鼠标指向的原图位置不变。"""

    def test_mouse_center_preserved(self):
        z = ZoomableImageCanvas.__new__(ZoomableImageCanvas)
        z._zoom = 1.0
        z._offset_x = 50
        z._offset_y = 30
        z._img_w = 200
        z._img_h = 150
        z._pil_original = True
        z._redraw = lambda: None

        # 鼠标在画布位置 (150, 110)
        cx, cy = 150, 110
        ix_before = (cx - z._offset_x) / z._zoom
        iy_before = (cy - z._offset_y) / z._zoom

        z._apply_zoom(1.5, cx, cy)

        # 缩放后同一画布位置对应的原图坐标应不变
        ix_after = (cx - z._offset_x) / z._zoom
        iy_after = (cy - z._offset_y) / z._zoom
        assert ix_after == pytest.approx(ix_before)
        assert iy_after == pytest.approx(iy_before)
