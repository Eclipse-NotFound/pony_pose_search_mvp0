"""
MVP2 AI 模型统一接口 — 测试套件（MVP2 Task 01）。

覆盖（任务卡测试要求）：
- 模型不存在 / 未知格式明确失败
- 输入图片错误时失败
- 输出格式符合 MVP1 suggestion（可经 Task 01 完整校验）
- confidence 范围校验
- 不写正式数据 / 不写 dataset / 不生成 suggestion 文件
"""

import os

import pytest

import model_interface as ai
import annotation_suggestion_utils as sugg

BBOX = {"x": 10, "y": 20, "width": 100, "height": 80}


def make_pil_image():
    from PIL import Image
    return Image.new("RGB", (200, 150), (10, 20, 30))


def make_kp_prediction(n=10, available=3, confidence=0.85):
    """按 mini schema 顺序构造关键点预测。"""
    kps = []
    for i in range(n):
        if i < available:
            kps.append((0.1 + i * 0.05, 0.2, 1))
        else:
            kps.append((0.0, 0.0, 0))
    return {"keypoints": kps, "confidence": confidence}


# =========================== 模型加载 ===========================

class TestLoadModel:
    """模型加载与后端路由。"""

    def test_missing_model_fails(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="model not found"):
            ai.load_model(str(tmp_path / "nope.pt"))

    def test_unknown_extension_fails(self, tmp_path):
        p = tmp_path / "model.xyz"
        p.write_bytes(b"x")
        with pytest.raises(ValueError, match="no model backend"):
            ai.load_model(str(p))

    def test_registered_backend_loads(self, mock_backend, mock_model_path):
        assert ai.load_model(mock_model_path) is mock_backend


# =========================== bbox 预测 ===========================

class TestPredictBbox:
    """predict_bbox → MVP1 bbox suggestion。"""

    def test_output_format_suggestion(self, mock_backend, mock_model_path):
        suggs = ai.predict_bbox(make_pil_image(), mock_model_path,
                                settings={"frame_id": "s01e24_f000100",
                                          "source_frame_id": "src"})
        assert len(suggs) == 1
        s = suggs[0]
        assert s["status"] == "suggested"
        assert s["method"] == "yolo_detector"
        assert s["confidence"] == 0.9
        assert s["bbox"] == {"x": 50, "y": 40, "width": 100, "height": 80}
        assert s["frame_id"] == "s01e24_f000100"
        # 输出可组装为 Task 01 建议文件并通过完整校验
        data = {"version": sugg.BBOX_SUGGESTION_VERSION,
                "character_id": "twilight_unicorn", "episode_id": "s01e24",
                "suggestions": suggs}
        assert sugg.validate_bbox_suggestion_file(data) == []

    def test_image_path_input(self, mock_backend, mock_model_path, tmp_path):
        from PIL import Image
        p = tmp_path / "img.png"
        Image.new("RGB", (100, 80)).save(p)
        mock_backend.detections = [{"bbox": (10, 10, 90, 70), "confidence": 0.8}]
        suggs = ai.predict_bbox(str(p), mock_model_path)
        assert len(suggs) == 1

    def test_conf_threshold_filter(self, mock_backend, mock_model_path):
        mock_backend.detections = [
            {"bbox": (10, 10, 50, 50), "confidence": 0.9},
            {"bbox": (60, 60, 80, 80), "confidence": 0.3},
        ]
        suggs = ai.predict_bbox(make_pil_image(), mock_model_path,
                                settings={"conf_threshold": 0.5})
        assert len(suggs) == 1
        assert suggs[0]["confidence"] == 0.9

    def test_confidence_out_of_range_fails(self, mock_backend, mock_model_path):
        mock_backend.detections = [{"bbox": (10, 10, 50, 50), "confidence": 1.5}]
        with pytest.raises(ValueError, match="confidence"):
            ai.predict_bbox(make_pil_image(), mock_model_path)

    def test_invalid_detection_bbox_fails(self, mock_backend, mock_model_path):
        # 检测框超出图像范围
        mock_backend.detections = [{"bbox": (10, 10, 500, 50), "confidence": 0.8}]
        with pytest.raises(ValueError, match="bbox invalid"):
            ai.predict_bbox(make_pil_image(), mock_model_path)

    def test_bad_image_fails(self, mock_backend, mock_model_path, tmp_path):
        with pytest.raises(ValueError, match="image not found"):
            ai.predict_bbox(str(tmp_path / "nope.png"), mock_model_path)
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        with pytest.raises(ValueError, match="cannot open"):
            ai.predict_bbox(str(bad), mock_model_path)


# =========================== 关键点预测 ===========================

class TestPredictKeypoints:
    """predict_keypoints → MVP1 keypoint suggestion。"""

    def test_schema_required(self, mock_backend, mock_model_path):
        with pytest.raises(ValueError, match="schema"):
            ai.predict_keypoints(make_pil_image(), BBOX, mock_model_path)

    def test_output_format_suggestion(self, mock_backend, mock_model_path, mini_schema):
        mock_backend.kp_prediction = make_kp_prediction(available=2)
        s = ai.predict_keypoints(make_pil_image(), BBOX, mock_model_path,
                                 settings={"schema": mini_schema, "frame_id": "f1"})
        assert s["status"] == "suggested"
        assert s["method"] == "yolo_pose"
        assert s["confidence"] == 0.85
        # head.head_center：nx=0.1 → x = 0.1*200 - 10 = 10；ny=0.2 → y = 0.2*150 - 20 = 10
        kp = s["keypoints"]["head.head_center"]
        assert kp["available"] is True
        assert kp["x"] == pytest.approx(10)
        assert kp["y"] == pytest.approx(10)
        # 不可用关键点（body.body_1，第 3 个）→ available=false，坐标为 None
        body = s["keypoints"]["body.body_1"]
        assert body["available"] is False
        assert body["x"] is None
        # 输出可组装为 Task 01 建议文件并通过完整校验
        data = {"version": sugg.KEYPOINT_SUGGESTION_VERSION,
                "character_id": "twilight_unicorn", "episode_id": "s01e24",
                "keypoint_schema_id": "mini_schema_v1", "suggestions": [s]}
        assert sugg.validate_keypoint_suggestion_file(data) == []

    def test_count_mismatch_fails(self, mock_backend, mock_model_path, mini_schema):
        mock_backend.kp_prediction = {"keypoints": [(0.1, 0.1, 1)], "confidence": 0.5}
        with pytest.raises(ValueError, match="count mismatch"):
            ai.predict_keypoints(make_pil_image(), BBOX, mock_model_path,
                                 settings={"schema": mini_schema})

    def test_confidence_out_of_range_fails(self, mock_backend, mock_model_path,
                                           mini_schema):
        mock_backend.kp_prediction = make_kp_prediction(confidence=1.2)
        with pytest.raises(ValueError, match="confidence"):
            ai.predict_keypoints(make_pil_image(), BBOX, mock_model_path,
                                 settings={"schema": mini_schema})

    def test_kp_out_of_image_fails(self, mock_backend, mock_model_path, mini_schema):
        kps = [(1.5, 0.1, 1)] + [(0.1, 0.1, 1)] * 9
        mock_backend.kp_prediction = {"keypoints": kps, "confidence": 0.5}
        with pytest.raises(ValueError, match="out of image"):
            ai.predict_keypoints(make_pil_image(), BBOX, mock_model_path,
                                 settings={"schema": mini_schema})

    def test_invalid_bbox_fails(self, mock_backend, mock_model_path, mini_schema):
        mock_backend.kp_prediction = make_kp_prediction()
        with pytest.raises(ValueError, match="bbox"):
            ai.predict_keypoints(
                make_pil_image(), {"x": 0, "y": 0, "width": 0, "height": 10},
                mock_model_path, settings={"schema": mini_schema})


# =========================== 遮挡分类预测 ===========================

class TestPredictOcclusion:
    """predict_occlusion → 单标签概率（M4 遮挡分类器）。"""

    def test_returns_label_prob(self, mock_backend, mock_model_path):
        mock_backend.class_probs = {"partial": 0.93, "not_partial": 0.07}
        res = ai.predict_occlusion(make_pil_image(), mock_model_path,
                                   settings={"occlusion_label": "partial"})
        assert res["partial_prob"] == pytest.approx(0.93)
        assert res["top1"] == "partial"
        assert res["top1_prob"] == pytest.approx(0.93)

    def test_occluded_label(self, mock_backend, mock_model_path):
        mock_backend.class_probs = {"occluded": 0.8, "not_occluded": 0.2}
        res = ai.predict_occlusion(make_pil_image(), mock_model_path,
                                   settings={"occlusion_label": "occluded"})
        assert res["occluded_prob"] == pytest.approx(0.8)

    def test_missing_label_fails(self, mock_backend, mock_model_path):
        with pytest.raises(ValueError, match="occlusion_label"):
            ai.predict_occlusion(make_pil_image(), mock_model_path, settings={})

    def test_label_not_in_classes_fails(self, mock_backend, mock_model_path):
        mock_backend.class_probs = {"partial": 0.9, "not_partial": 0.1}
        with pytest.raises(ValueError, match="not in model classes"):
            ai.predict_occlusion(make_pil_image(), mock_model_path,
                                 settings={"occlusion_label": "occluded"})

    def test_missing_model_fails(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="model not found"):
            ai.predict_occlusion(make_pil_image(),
                                 str(tmp_path / "nope.pt"),
                                 settings={"occlusion_label": "partial"})


# =========================== 数据保护 ===========================

class TestDataProtection:
    """预测不写任何数据。"""

    def test_predict_writes_nothing(self, mock_backend, mock_model_path, tmp_path,
                                    mini_schema):
        """预测后不产生任何新文件（正式数据 / dataset / suggestion 均不受影响）。"""
        mock_backend.kp_prediction = make_kp_prediction()
        ai.predict_bbox(make_pil_image(), mock_model_path,
                        settings={"frame_id": "f1"})
        ai.predict_keypoints(make_pil_image(), BBOX, mock_model_path,
                             settings={"schema": mini_schema, "frame_id": "f1"})
        assert os.listdir(str(tmp_path)) == ["model.mock"]
