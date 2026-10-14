"""
MVP1 Task 01 — annotation_suggestion_utils 测试套件。

覆盖：
- 建议状态校验（四种合法 / 非法失败）
- bbox 建议文件格式校验
- keypoint 建议文件格式校验
- bbox 坐标工具（校验 / 裁剪 / 归一化 / 插值）
- 关键点坐标映射（相对坐标 / 跨框映射 / 插值）
- 建议文件读写与数据保护（不写入正式数据目录）
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "common"))
import annotation_suggestion_utils as utils


# ---------------------------------------------------------------------------
# 测试数据构造
# ---------------------------------------------------------------------------

def make_valid_bbox_suggestion_file():
    return {
        "version": utils.BBOX_SUGGESTION_VERSION,
        "character_id": "twilight_unicorn",
        "episode_id": "s01e15",
        "suggestions": [
            {
                "frame_id": "s01e15_f000101",
                "source_frame_id": "s01e15_f000100",
                "bbox": {"x": 320, "y": 145, "width": 420, "height": 510},
                "method": "bbox_mapping",
                "confidence": 0.8,
                "status": "suggested",
            }
        ],
    }


def make_valid_keypoint_suggestion_file():
    return {
        "version": utils.KEYPOINT_SUGGESTION_VERSION,
        "character_id": "twilight_unicorn",
        "episode_id": "s01e15",
        "keypoint_schema_id": "pony_unicorn_no_wings_mvp0_v1",
        "suggestions": [
            {
                "frame_id": "s01e15_f000101",
                "source_frame_id": "s01e15_f000100",
                "method": "bbox_relative_mapping",
                "confidence": 0.75,
                "status": "suggested",
                "keypoints": {
                    "body_center": {"x": 500, "y": 350, "available": True},
                    "hidden_point": {"x": None, "y": None, "available": False},
                },
            }
        ],
    }


# =========================== 状态和格式 ===========================

class TestStatus:
    """建议状态：只允许四种合法值。"""

    def test_four_valid_statuses_pass(self):
        for status in utils.VALID_STATUSES:
            assert utils.is_valid_status(status) is True

    def test_invalid_status_fails(self):
        for status in ("", "confirmed", "pending", "APPROVED", "suggested "):
            assert utils.is_valid_status(status) is False

    def test_non_string_status_fails(self):
        for status in (None, 1, ["suggested"]):
            assert utils.is_valid_status(status) is False


class TestBboxSuggestionFileValidation:
    """bbox 建议文件：合法结构通过，非法字段失败。"""

    def test_valid_file_passes(self):
        assert utils.validate_bbox_suggestion_file(make_valid_bbox_suggestion_file()) == []

    def test_invalid_version_fails(self):
        data = make_valid_bbox_suggestion_file()
        data["version"] = "mvp1_bbox_suggestions_v2"
        errors = utils.validate_bbox_suggestion_file(data)
        assert any("version" in e for e in errors)

    def test_confidence_out_of_range_fails(self):
        for bad in (-0.1, 1.1, "0.8", None):
            data = make_valid_bbox_suggestion_file()
            data["suggestions"][0]["confidence"] = bad
            errors = utils.validate_bbox_suggestion_file(data)
            assert any("confidence" in e for e in errors), f"confidence={bad!r}"

    def test_duplicate_frame_id_fails(self):
        data = make_valid_bbox_suggestion_file()
        data["suggestions"].append(dict(data["suggestions"][0]))
        errors = utils.validate_bbox_suggestion_file(data)
        assert any("duplicate" in e for e in errors)

    def test_invalid_status_fails(self):
        data = make_valid_bbox_suggestion_file()
        data["suggestions"][0]["status"] = "pending"
        errors = utils.validate_bbox_suggestion_file(data)
        assert any("status" in e for e in errors)

    def test_zero_size_bbox_fails(self):
        for key in ("width", "height"):
            data = make_valid_bbox_suggestion_file()
            data["suggestions"][0]["bbox"][key] = 0
            errors = utils.validate_bbox_suggestion_file(data)
            assert any("bbox" in e for e in errors)

    def test_missing_header_fails(self):
        data = make_valid_bbox_suggestion_file()
        del data["character_id"]
        errors = utils.validate_bbox_suggestion_file(data)
        assert any("character_id" in e for e in errors)

    def test_missing_suggestions_fails(self):
        data = make_valid_bbox_suggestion_file()
        del data["suggestions"]
        assert any("suggestions" in e for e in utils.validate_bbox_suggestion_file(data))

    def test_empty_suggestions_allowed(self):
        data = make_valid_bbox_suggestion_file()
        data["suggestions"] = []
        assert utils.validate_bbox_suggestion_file(data) == []

    def test_missing_frame_id_fails(self):
        data = make_valid_bbox_suggestion_file()
        del data["suggestions"][0]["frame_id"]
        errors = utils.validate_bbox_suggestion_file(data)
        assert any("frame_id" in e for e in errors)


class TestQualityField:
    """可选 quality 字段（M03 图片质量判断）：合法通过，非法拒绝。"""

    def test_valid_quality_passes(self):
        data = make_valid_bbox_suggestion_file()
        data["suggestions"][0]["quality"] = {
            "version": "mvp1_quality_v1",
            "partial": True, "occluded": False, "low_res": True,
            "blurred": None,
            "occlusion_hints": ["edge_cut"],
            "res": {"area": 8000, "min_side": 80, "max_side": 100},
            "score": 0.5,
        }
        assert utils.validate_bbox_suggestion_file(data) == []

    def test_quality_optional_absent(self):
        assert utils.validate_bbox_suggestion_file(
            make_valid_bbox_suggestion_file()) == []

    def test_quality_must_be_dict(self):
        data = make_valid_bbox_suggestion_file()
        data["suggestions"][0]["quality"] = "bad"
        errors = utils.validate_bbox_suggestion_file(data)
        assert any("quality" in e for e in errors)

    def test_quality_bool_fields(self):
        for key in ("partial", "occluded", "low_res"):
            data = make_valid_bbox_suggestion_file()
            data["suggestions"][0]["quality"] = {key: "yes"}
            errors = utils.validate_bbox_suggestion_file(data)
            assert any(f"quality.{key}" in e for e in errors), key

    def test_quality_prob_range(self):
        for key in ("partial_prob", "occluded_prob", "score"):
            for bad in (-0.1, 1.1):
                data = make_valid_bbox_suggestion_file()
                data["suggestions"][0]["quality"] = {key: bad}
                errors = utils.validate_bbox_suggestion_file(data)
                assert any(f"quality.{key}" in e for e in errors), (key, bad)

    def test_quality_blurred_nullable(self):
        data = make_valid_bbox_suggestion_file()
        data["suggestions"][0]["quality"] = {"blurred": True}
        assert utils.validate_bbox_suggestion_file(data) == []
        data["suggestions"][0]["quality"] = {"blurred": "yes"}
        assert any("quality.blurred" in e
                   for e in utils.validate_bbox_suggestion_file(data))


class TestKeypointSuggestionFileValidation:
    """keypoint 建议文件：合法结构通过，非法字段失败。"""

    def test_valid_file_passes(self):
        assert utils.validate_keypoint_suggestion_file(
            make_valid_keypoint_suggestion_file()) == []

    def test_invalid_version_fails(self):
        data = make_valid_keypoint_suggestion_file()
        data["version"] = "mvp1_keypoint_suggestions_v2"
        errors = utils.validate_keypoint_suggestion_file(data)
        assert any("version" in e for e in errors)

    def test_missing_schema_id_fails(self):
        data = make_valid_keypoint_suggestion_file()
        del data["keypoint_schema_id"]
        errors = utils.validate_keypoint_suggestion_file(data)
        assert any("keypoint_schema_id" in e for e in errors)

    def test_available_true_requires_coords(self):
        data = make_valid_keypoint_suggestion_file()
        data["suggestions"][0]["keypoints"]["body_center"] = {
            "x": None, "y": None, "available": True}
        errors = utils.validate_keypoint_suggestion_file(data)
        assert any("x" in e or "y" in e for e in errors)

    def test_available_false_allows_empty_coords(self):
        data = make_valid_keypoint_suggestion_file()
        data["suggestions"][0]["keypoints"]["body_center"] = {
            "x": None, "y": None, "available": False}
        assert utils.validate_keypoint_suggestion_file(data) == []

    def test_available_must_be_bool(self):
        data = make_valid_keypoint_suggestion_file()
        data["suggestions"][0]["keypoints"]["body_center"] = {
            "x": 1.0, "y": 2.0, "available": "yes"}
        errors = utils.validate_keypoint_suggestion_file(data)
        assert any("available" in e for e in errors)

    def test_duplicate_frame_id_fails(self):
        data = make_valid_keypoint_suggestion_file()
        data["suggestions"].append(dict(data["suggestions"][0]))
        errors = utils.validate_keypoint_suggestion_file(data)
        assert any("duplicate" in e for e in errors)

    def test_keypoints_must_be_dict(self):
        data = make_valid_keypoint_suggestion_file()
        data["suggestions"][0]["keypoints"] = []
        errors = utils.validate_keypoint_suggestion_file(data)
        assert any("keypoints" in e for e in errors)


# =========================== 角色框工具 ===========================

class TestBboxTools:
    """validate_bbox / clip / normalize / interpolate。"""

    def test_valid_bbox_passes(self):
        assert utils.validate_bbox({"x": 10, "y": 20, "width": 100, "height": 200}) is True
        assert utils.validate_bbox({"x": 0.0, "y": 0.0, "width": 1.5, "height": 2.5}) is True

    def test_zero_width_or_height_fails(self):
        assert utils.validate_bbox({"x": 0, "y": 0, "width": 0, "height": 100}) is False
        assert utils.validate_bbox({"x": 0, "y": 0, "width": 100, "height": 0}) is False

    def test_missing_or_bad_fields_fails(self):
        assert utils.validate_bbox({"x": 0, "y": 0, "width": 100}) is False
        assert utils.validate_bbox({"x": "0", "y": 0, "width": 100, "height": 100}) is False
        assert utils.validate_bbox({"x": True, "y": 0, "width": 100, "height": 100}) is False
        assert utils.validate_bbox(None) is False

    def test_clip_bbox_to_image(self):
        bbox = {"x": -20, "y": 30, "width": 200, "height": 100}
        clipped = utils.clip_bbox_to_image(bbox, 160, 120)
        assert clipped == {"x": 0, "y": 30, "width": 160, "height": 90}

    def test_clip_keeps_inside_bbox_unchanged(self):
        bbox = {"x": 10, "y": 10, "width": 50, "height": 50}
        assert utils.clip_bbox_to_image(bbox, 100, 100) == bbox

    def test_bbox_fully_outside_image_fails(self):
        bbox = {"x": 500, "y": 500, "width": 100, "height": 100}
        with pytest.raises(ValueError):
            utils.clip_bbox_to_image(bbox, 100, 100)

    def test_clip_rejects_bad_image_size(self):
        bbox = {"x": 0, "y": 0, "width": 10, "height": 10}
        with pytest.raises(ValueError):
            utils.clip_bbox_to_image(bbox, 0, 100)

    def test_normalize_bbox(self):
        bbox = {"x": 50, "y": 25, "width": 50, "height": 25}
        norm = utils.normalize_bbox(bbox, 100, 100)
        assert norm["x"] == pytest.approx(0.5)
        assert norm["y"] == pytest.approx(0.25)
        assert norm["width"] == pytest.approx(0.5)
        assert norm["height"] == pytest.approx(0.25)

    def test_interpolate_bbox(self):
        a = {"x": 10, "y": 20, "width": 100, "height": 200}
        b = {"x": 30, "y": 60, "width": 140, "height": 300}
        assert utils.interpolate_bbox(a, b, 0.0) == a
        assert utils.interpolate_bbox(a, b, 1.0) == b

        mid = utils.interpolate_bbox(a, b, 0.5)
        assert mid["x"] == pytest.approx(20.0)
        assert mid["y"] == pytest.approx(40.0)
        assert mid["width"] == pytest.approx(120.0)
        assert mid["height"] == pytest.approx(250.0)

    def test_invalid_ratio_fails(self):
        a = {"x": 0, "y": 0, "width": 10, "height": 10}
        b = {"x": 10, "y": 10, "width": 20, "height": 20}
        for bad in (-0.1, 1.1, "0.5", None):
            with pytest.raises(ValueError):
                utils.interpolate_bbox(a, b, bad)

    def test_interpolate_requires_valid_boxes(self):
        with pytest.raises(ValueError):
            utils.interpolate_bbox(
                {"x": 0, "y": 0, "width": 0, "height": 10},
                {"x": 1, "y": 1, "width": 1, "height": 1},
                0.5)


# =========================== 关键点工具 ===========================

class TestPointRelativeMapping:
    """点与 bbox 相对坐标互转。"""

    def test_point_to_relative_correct(self):
        bbox = {"x": 100, "y": 50, "width": 200, "height": 100}
        rx, ry = utils.point_to_bbox_relative((150, 100), bbox)
        assert rx == pytest.approx(0.25)
        assert ry == pytest.approx(0.5)

    def test_relative_to_point_correct(self):
        bbox = {"x": 100, "y": 50, "width": 200, "height": 100}
        x, y = utils.point_from_bbox_relative((0.25, 0.5), bbox)
        assert x == pytest.approx(150)
        assert y == pytest.approx(100)

    def test_relative_roundtrip(self):
        bbox = {"x": 10, "y": 20, "width": 300, "height": 200}
        rx, ry = utils.point_to_bbox_relative((37, 42), bbox)
        x, y = utils.point_from_bbox_relative((rx, ry), bbox)
        assert x == pytest.approx(37)
        assert y == pytest.approx(42)

    def test_invalid_point_fails(self):
        bbox = {"x": 0, "y": 0, "width": 10, "height": 10}
        for bad in ((1, 2, 3), (1, "2"), "1,2", None):
            with pytest.raises(ValueError):
                utils.point_to_bbox_relative(bad, bbox)


class TestMapKeypointsBetweenBboxes:
    """跨框关键点映射。"""

    def test_same_bbox_unchanged(self):
        bbox = {"x": 100, "y": 50, "width": 200, "height": 150}
        kps = {"body_1": {"x": 150, "y": 100, "available": True}}
        mapped = utils.map_keypoints_between_bboxes(kps, bbox, bbox)
        assert mapped["body_1"]["x"] == pytest.approx(150)
        assert mapped["body_1"]["y"] == pytest.approx(100)
        assert mapped["body_1"]["available"] is True

    def test_scaled_bbox_mapping(self):
        src = {"x": 100, "y": 50, "width": 200, "height": 150}
        dst = {"x": 200, "y": 100, "width": 400, "height": 300}
        kps = {"body_1": {"x": 150, "y": 100, "available": True}}
        mapped = utils.map_keypoints_between_bboxes(kps, src, dst)
        # 相对坐标 (0.25, 1/3) 映射到 2 倍目标框
        assert mapped["body_1"]["x"] == pytest.approx(300)
        assert mapped["body_1"]["y"] == pytest.approx(200)

    def test_translated_bbox_mapping(self):
        src = {"x": 0, "y": 0, "width": 100, "height": 100}
        dst = {"x": 50, "y": 50, "width": 100, "height": 100}
        kps = {"body_1": {"x": 25, "y": 25, "available": True}}
        mapped = utils.map_keypoints_between_bboxes(kps, src, dst)
        assert mapped["body_1"]["x"] == pytest.approx(75)
        assert mapped["body_1"]["y"] == pytest.approx(75)

    def test_unavailable_stays_unavailable(self):
        src = {"x": 0, "y": 0, "width": 100, "height": 100}
        dst = {"x": 50, "y": 50, "width": 100, "height": 100}
        kps = {"leg_1": {"x": 10, "y": 10, "available": False}}
        mapped = utils.map_keypoints_between_bboxes(kps, src, dst)
        assert mapped["leg_1"]["available"] is False
        assert mapped["leg_1"]["x"] is None
        assert mapped["leg_1"]["y"] is None

    def test_invalid_keypoint_fails(self):
        src = {"x": 0, "y": 0, "width": 100, "height": 100}
        dst = {"x": 0, "y": 0, "width": 100, "height": 100}
        with pytest.raises(ValueError):
            utils.map_keypoints_between_bboxes(
                {"p": {"x": 1, "y": 2, "available": "yes"}}, src, dst)


class TestInterpolateKeypoints:
    """关键点线性插值。"""

    def test_interpolate_correct(self):
        a = {"p": {"x": 0, "y": 0, "available": True}}
        b = {"p": {"x": 10, "y": 20, "available": True}}
        assert utils.interpolate_keypoints(a, b, 0.0)["p"]["x"] == pytest.approx(0.0)
        assert utils.interpolate_keypoints(a, b, 1.0)["p"]["x"] == pytest.approx(10.0)

        mid = utils.interpolate_keypoints(a, b, 0.5)
        assert mid["p"]["x"] == pytest.approx(5.0)
        assert mid["p"]["y"] == pytest.approx(10.0)
        assert mid["p"]["available"] is True

    def test_available_mismatch_rule(self):
        # 只有两端均 available=true 才插值；否则结果为 available=false
        a = {"p": {"x": 0, "y": 0, "available": True}}
        b = {"p": {"x": 10, "y": 20, "available": False}}
        mid = utils.interpolate_keypoints(a, b, 0.5)
        assert mid["p"]["available"] is False
        assert mid["p"]["x"] is None
        assert mid["p"]["y"] is None

    def test_key_missing_one_side_rule(self):
        a = {"p1": {"x": 0, "y": 0, "available": True}}
        b = {"p2": {"x": 10, "y": 20, "available": True}}
        mid = utils.interpolate_keypoints(a, b, 0.5)
        assert mid["p1"]["available"] is False
        assert mid["p2"]["available"] is False

    def test_invalid_ratio_fails(self):
        a = {"p": {"x": 0, "y": 0, "available": True}}
        b = {"p": {"x": 1, "y": 1, "available": True}}
        for bad in (-0.5, 1.5):
            with pytest.raises(ValueError):
                utils.interpolate_keypoints(a, b, bad)


# =========================== 文件读写 ===========================

class TestFileIO:
    """建议文件读写与校验。"""

    def test_save_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "suggestions" / "bbox_suggestions.json")
        data = make_valid_bbox_suggestion_file()
        data["note"] = "中文备注"
        utils.save_suggestion_file(path, data)
        loaded = utils.load_suggestion_file(path)
        assert loaded == data

    def test_keypoint_save_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "keypoint_suggestions.json")
        utils.save_suggestion_file(path, make_valid_keypoint_suggestion_file())
        assert utils.load_suggestion_file(path) == make_valid_keypoint_suggestion_file()

    def test_output_format_stable(self, tmp_path):
        path = str(tmp_path / "s.json")
        utils.save_suggestion_file(path, make_valid_bbox_suggestion_file())
        with open(path, "r", encoding="utf-8") as f:
            first = f.read()
        utils.save_suggestion_file(path, make_valid_bbox_suggestion_file())
        with open(path, "r", encoding="utf-8") as f:
            second = f.read()
        assert first == second

    def test_save_rejects_invalid_data(self, tmp_path):
        path = str(tmp_path / "bad.json")
        data = make_valid_bbox_suggestion_file()
        data["suggestions"][0]["confidence"] = 2.5
        with pytest.raises(ValueError):
            utils.save_suggestion_file(path, data)
        assert not os.path.exists(path)

    def test_save_rejects_unknown_version(self, tmp_path):
        path = str(tmp_path / "unknown.json")
        with pytest.raises(ValueError):
            utils.save_suggestion_file(path, {"version": "some_other_v1"})

    def test_load_corrupted_json_fails(self, tmp_path):
        path = str(tmp_path / "broken.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        with pytest.raises(ValueError):
            utils.load_suggestion_file(path)

    def test_load_missing_file_fails(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            utils.load_suggestion_file(str(tmp_path / "missing.json"))


class TestDataProtection:
    """建议工具不写入正式数据目录，不产生隐式副作用。"""

    def test_no_write_to_formal_dirs(self, tmp_path):
        formal_dirs = [
            os.path.join(str(tmp_path), "bboxes"),
            os.path.join(str(tmp_path), "keypoints"),
            os.path.join(str(tmp_path), "poses"),
            os.path.join(str(tmp_path), "queries"),
        ]
        for d in formal_dirs:
            os.makedirs(d)

        # 只在显式传入的建议路径下写入
        utils.save_suggestion_file(
            os.path.join(str(tmp_path), "suggestions", "bbox_suggestions.json"),
            make_valid_bbox_suggestion_file())

        # 正式数据目录必须保持为空
        for d in formal_dirs:
            assert os.listdir(d) == []

        # 其他纯函数调用不产生任何文件
        bbox = {"x": 10, "y": 10, "width": 50, "height": 50}
        utils.clip_bbox_to_image(bbox, 100, 100)
        utils.normalize_bbox(bbox, 100, 100)
        utils.interpolate_bbox(bbox, bbox, 0.5)
        kps = {"p": {"x": 1, "y": 2, "available": True}}
        utils.map_keypoints_between_bboxes(kps, bbox, bbox)
        utils.interpolate_keypoints(kps, kps, 0.5)

        assert set(os.listdir(str(tmp_path))) == {
            "bboxes", "keypoints", "poses", "queries", "suggestions"}
