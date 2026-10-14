"""
M03 图片质量判断 — quality_utils 单元测试。

覆盖：
- bbox_metrics 分辨率指标 / 非法输入
- low_res / edge_cut / aspect_outlier 阈值边界
- sharpness（空白 vs 噪声图、过小 crop 跳过）
- assess_bbox_quality 汇总（帧尺寸推断、AI 信号融合、score）
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "scripts", "common"))
import quality_utils as q


def make_image(size=(200, 150), mode="RGB", fill=(128, 128, 128)):
    from PIL import Image
    return Image.new(mode, size, fill)


def make_noisy(size=(200, 150)):
    """随机噪声图（高 Laplacian 方差）。"""
    import numpy as np
    from PIL import Image
    arr = np.random.default_rng(42).integers(0, 256, size=size[::-1], dtype=np.uint8)
    return Image.fromarray(arr, mode="L")


BBOX = {"x": 50, "y": 40, "width": 100, "height": 80}


@pytest.fixture
def temp_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        yield td


# =========================== bbox_metrics ===========================

class TestBboxMetrics:
    def test_metrics_values(self):
        m = q.bbox_metrics(BBOX, (200, 150))
        assert m["area"] == 8000
        assert m["min_side"] == 80
        assert m["max_side"] == 100
        assert m["aspect_ratio"] == 1.25
        assert m["frame_ratio"] == pytest.approx(8000 / 30000)

    def test_invalid_bbox_fails(self):
        with pytest.raises(ValueError):
            q.bbox_metrics({"x": 0, "y": 0, "width": 0, "height": 10}, (200, 150))

    def test_invalid_frame_size_fails(self):
        with pytest.raises(ValueError):
            q.bbox_metrics(BBOX, (0, 0))


# =========================== 分辨率 ===========================

class TestResolution:
    def test_low_res_by_min_side(self):
        assert q.detect_low_res({"x": 0, "y": 0, "width": 99, "height": 200}, (1920, 1080)) is True
        assert q.detect_low_res({"x": 0, "y": 0, "width": 100, "height": 200}, (1920, 1080)) is False

    def test_low_res_by_area(self):
        # 120×83=9960 < 10000 → 面积触发
        assert q.detect_low_res({"x": 0, "y": 0, "width": 120, "height": 83}, (1920, 1080)) is True
        # 120×100=12000 ≥ 10000 且 min_side=100 → 不触发
        assert q.detect_low_res({"x": 0, "y": 0, "width": 120, "height": 100}, (1920, 1080)) is False

    def test_small_hint_is_softer_than_low_res(self):
        bbox = {"x": 0, "y": 0, "width": 150, "height": 150}
        assert q.detect_small(bbox, (1920, 1080)) is True
        assert q.detect_low_res(bbox, (1920, 1080)) is False  # 150px 只是偏小，不是低分辨率

    def test_low_frame_ratio(self):
        bbox = {"x": 0, "y": 0, "width": 100, "height": 100}
        assert q.detect_low_frame_ratio(bbox, (1920, 1080)) is True  # 10000/2073600 < 0.5%
        assert q.detect_low_frame_ratio(BBOX, (200, 150)) is False    # 8000/30000


# =========================== 遮挡（算法侧） ===========================

class TestOcclusionSignals:
    def test_edge_cut_top_left(self):
        assert q.detect_edge_cut({"x": 0, "y": 0, "width": 100, "height": 80}, (200, 150)) is True
        assert q.detect_edge_cut({"x": 1, "y": 0, "width": 100, "height": 80}, (200, 150)) is True

    def test_edge_cut_right_bottom(self):
        assert q.detect_edge_cut({"x": 100, "y": 70, "width": 100, "height": 80}, (200, 150)) is True

    def test_inside_not_cut(self):
        assert q.detect_edge_cut(BBOX, (200, 150)) is False
        assert q.detect_edge_cut({"x": 3, "y": 3, "width": 100, "height": 80}, (200, 150)) is False

    def test_aspect_outlier(self):
        assert q.detect_aspect_outlier({"x": 0, "y": 0, "width": 300, "height": 100}) is True
        assert q.detect_aspect_outlier({"x": 0, "y": 0, "width": 100, "height": 300}) is True
        assert q.detect_aspect_outlier(BBOX) is False  # 1.25 在 [0.6, 1.8]

    def test_aspect_boundary(self):
        assert q.detect_aspect_outlier({"x": 0, "y": 0, "width": 60, "height": 100}) is False
        assert q.detect_aspect_outlier({"x": 0, "y": 0, "width": 59, "height": 100}) is True


# =========================== 清晰度 ===========================

class TestSharpness:
    def test_blank_image_low_variance(self):
        v = q.sharpness_variance(make_image())
        assert v is not None and v < 1.0

    def test_noisy_image_high_variance(self):
        v = q.sharpness_variance(make_noisy())
        assert v is not None and v > 100.0

    def test_blank_detected_blurred(self):
        assert q.detect_blurred(make_image()) is True
        assert q.detect_blurred(make_noisy()) is False

    def test_path_input(self, temp_dir):
        from PIL import Image
        p = os.path.join(temp_dir, "img.png")
        make_noisy().save(p)
        v = q.sharpness_variance(p)
        assert v is not None and v > 100.0

    def test_missing_path_returns_none(self, temp_dir):
        assert q.sharpness_variance(os.path.join(temp_dir, "nope.png")) is None

    def test_tiny_bbox_skips(self):
        # bbox 区域 < 8x8 → 跳过清晰度（None），不崩溃
        assert q.sharpness_variance(make_image(),
                                    {"x": 0, "y": 0, "width": 4, "height": 4}) is None


# =========================== assess_bbox_quality ===========================

class TestAssessBboxQuality:
    def test_basic_structure(self):
        qd = q.assess_bbox_quality(make_image(), BBOX)
        assert qd["version"] == q.QUALITY_VERSION
        assert isinstance(qd["partial"], bool)
        assert isinstance(qd["occluded"], bool)
        assert isinstance(qd["low_res"], bool)
        assert isinstance(qd["occlusion_hints"], list)
        assert qd["res"]["area"] == 8000
        assert 0.0 <= qd["score"] <= 1.0

    def test_invalid_bbox_fails(self):
        with pytest.raises(ValueError):
            q.assess_bbox_quality(make_image(), {"x": 0, "y": 0, "width": 0, "height": 0})

    def test_no_image_requires_frame_size(self):
        with pytest.raises(ValueError):
            q.assess_bbox_quality(None, BBOX)

    def test_no_image_with_frame_size_skips_sharpness(self):
        qd = q.assess_bbox_quality(None, BBOX, frame_size=(200, 150))
        assert qd["blurred"] is None
        assert qd["res"]["sharpness"] is None

    def test_edge_cut_sets_partial_and_hint(self):
        qd = q.assess_bbox_quality(make_image(), {"x": 0, "y": 0, "width": 100, "height": 80})
        assert qd["partial"] is True
        assert "edge_cut" in qd["occlusion_hints"]

    def test_ai_signals_fusion(self):
        """AI 分类器概率（M4）融合：>0.5 触发并记录 ai_ 来源 hint。"""
        qd = q.assess_bbox_quality(
            make_image(), BBOX,
            ai_signals={"partial_prob": 0.9, "occluded_prob": 0.1})
        assert qd["partial"] is True
        assert qd["occluded"] is False
        assert "ai_partial" in qd["occlusion_hints"]
        assert qd["partial_prob"] == 0.9

    def test_ai_signals_low_prob_no_flag(self):
        qd = q.assess_bbox_quality(
            make_image(), BBOX, ai_signals={"occluded_prob": 0.4})
        assert qd["occluded"] is False
        assert "ai_occluded" not in qd["occlusion_hints"]

    def test_ai_signals_absent_no_prob_fields(self):
        qd = q.assess_bbox_quality(make_image(), BBOX)
        assert "partial_prob" not in qd
        assert "occluded_prob" not in qd

    def test_score_penalties(self):
        # 干净 bbox：min_side=100 且面积充足、不贴边、不模糊 → 满分
        clean_bbox = {"x": 40, "y": 20, "width": 120, "height": 100}
        clean = q.assess_bbox_quality(make_noisy(), clean_bbox)
        assert clean["score"] == 1.0
        # 低分辨率 → 扣分
        low = q.assess_bbox_quality(make_image(), {"x": 0, "y": 0, "width": 80, "height": 100})
        assert low["low_res"] is True
        assert low["score"] < 1.0

    def test_score_continuous_with_probs(self):
        """概率加权扣分：不再卡固定平台（如 0.55）。"""
        bbox = {"x": 40, "y": 20, "width": 120, "height": 100}
        # partial+occluded 且概率中等 → 分数按概率连续变化
        s1 = q.assess_bbox_quality(
            make_noisy(), bbox,
            ai_signals={"partial_prob": 0.6, "occluded_prob": 0.6})
        s2 = q.assess_bbox_quality(
            make_noisy(), bbox,
            ai_signals={"partial_prob": 0.9, "occluded_prob": 0.9})
        assert s1["score"] > s2["score"]
        # 高概率 P+O：1.0 - 0.25*0.9 - 0.20*0.9 = 0.595
        assert s2["score"] == pytest.approx(0.595, abs=0.01)
        # 概率 1.0 = 满额扣分（与无概率时的固定扣分一致）
        s3 = q.assess_bbox_quality(
            make_noisy(), bbox,
            ai_signals={"partial_prob": 1.0, "occluded_prob": 1.0})
        s4 = q.assess_bbox_quality(
            make_noisy(), bbox,
            ai_signals={"partial_prob": 0.0, "occluded_prob": 0.0})
        assert s3["score"] == 0.55
        assert s4["score"] == 1.0  # 概率为 0 → 不扣分
