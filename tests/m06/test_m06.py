"""
M06 姿态向量生成 — 测试套件。

覆盖：
- 单位方向向量计算
- 关键点引用解析
- 简单向量生成 (head, neck, body, tail)
- 腿部向量 (v1 anchor, v2 base, v3 knee三段)
- 可用性/缺失检测
- Schema 动态读取 direction_weights
- 缺失点去重
- 完整管道
"""

import json
import math
import os

import pytest

import generate_pose_vectors as m06
import pose_vector_utils as pvu


# =========================== 单位向量 ===========================

class TestUnitDirection:
    def test_basic(self):
        v = pvu.unit_direction([0, 0], [3, 4])
        assert v == pytest.approx([0.6, 0.8])

    def test_horizontal(self):
        v = pvu.unit_direction([0, 0], [5, 0])
        assert v == [1.0, 0.0]

    def test_vertical(self):
        v = pvu.unit_direction([0, 0], [0, -5])
        assert v == [0.0, -1.0]

    def test_zero_length(self):
        assert pvu.unit_direction([1, 1], [1, 1]) is None


# =========================== 关键点解析 ===========================

class TestResolveKeypoint:
    def test_absolute_path(self):
        kp = {"head": {"head_center": [100, 50]}}
        assert pvu.resolve_keypoint(kp, "head.head_center") == [100, 50]

    def test_current_leg(self):
        leg = {"base": [10, 20], "mid": [30, 40]}
        assert pvu.resolve_keypoint({}, "current_leg.base", leg=leg) == [10, 20]

    def test_anchor_keypoint(self):
        kp = {"body": {"body_1": [50, 60]}}
        result = pvu.resolve_keypoint(kp, "anchor_keypoint", anchor_path="body.body_1")
        assert result == [50, 60]

    def test_nonexistent(self):
        assert pvu.resolve_keypoint({}, "head.nonexistent") is None


# =========================== 简单向量 ===========================

class TestSimpleVectors:
    def test_all_present(self, sample_keypoints_v3, v3_schema):
        vecs, avail, missing = pvu.compute_simple_vectors(
            sample_keypoints_v3, v3_schema["vector_rules"])
        assert avail["head"] is True
        assert avail["neck"] is True
        assert avail["body"] is True
        assert avail["tail"] is True
        assert "head_direction" in vecs
        assert len(missing) == 0

    def test_missing_point(self, sample_keypoints_v3, v3_schema):
        kp = dict(sample_keypoints_v3)
        kp["head"] = dict(kp["head"])
        kp["head"]["head_front"] = None
        vecs, avail, missing = pvu.compute_simple_vectors(
            kp, v3_schema["vector_rules"])
        assert avail["head"] is False
        assert "head.head_front" in missing


# =========================== 腿部向量 v3 ===========================

class TestLegVectorsV3:
    def test_back_legs_three_segments(self, sample_keypoints_v3, v3_schema):
        bl, avail, missing = pvu.compute_leg_vectors(
            sample_keypoints_v3, v3_schema["vector_rules"], "back_legs")
        assert len(bl) == 2
        leg = bl[0]
        assert leg["leg_id"] == "back_leg_1"
        assert "leg_direction1" in leg  # base → knee
        assert "leg_direction2" in leg  # knee → mid
        assert "leg_direction3" in leg  # mid → end
        assert len(leg) == 4  # leg_id + 3 directions

    def test_front_legs_two_segments(self, sample_keypoints_v3, v3_schema):
        fl, avail, missing = pvu.compute_leg_vectors(
            sample_keypoints_v3, v3_schema["vector_rules"], "front_legs")
        leg = fl[0]
        assert "leg_direction1" in leg
        assert "leg_direction2" in leg
        assert "leg_direction3" not in leg  # 前腿无第三段

    def test_back_leg_missing_knee(self, sample_keypoints_v3, v3_schema):
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": None, "mid": [200, 170], "end": [205, 220]},
            {"leg_id": "back_leg_2", "base": [210, 120], "knee": [215, 145], "mid": [220, 175], "end": [225, 225]},
        ]
        bl, avail, missing = pvu.compute_leg_vectors(
            kp, v3_schema["vector_rules"], "back_legs")
        assert avail["back_leg_1"] is False
        assert avail["back_leg_2"] is True
        assert "back_leg_1.knee" in missing


# =========================== 腿部向量 v1 ===========================

class TestLegVectorsV1:
    def test_anchor_keypoint_resolution(self, sample_keypoints_v1, v1_schema):
        fl, avail, missing = pvu.compute_leg_vectors(
            sample_keypoints_v1, v1_schema["vector_rules"], "front_legs")
        leg = fl[0]
        assert leg["leg_id"] == "front_leg_1"
        assert leg["anchor_point"] == "body.body_1"
        assert "leg_direction1" in leg  # body_1 → mid
        assert "leg_direction2" in leg  # mid → end

    def test_v1_missing_body_anchor(self, sample_keypoints_v1, v1_schema):
        kp = dict(sample_keypoints_v1)
        kp["body"] = {"body_1": None, "body_2": [200, 105]}
        fl, avail, missing = pvu.compute_leg_vectors(
            kp, v1_schema["vector_rules"], "front_legs")
        assert avail["front_leg_1"] is False
        assert avail["front_leg_2"] is False


# =========================== 完整管道 v3 ===========================

class TestFullPipelineV3:
    def test_generate_vectors_full(self, sample_keypoints_v3, v3_schema):
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v3, v3_schema["vector_rules"])

        v = result["vectors"]
        assert v["available"]["head"] is True
        assert v["available"]["front_leg_1"] is True
        assert v["available"]["back_leg_1"] is True
        assert len(v["back_legs"]) == 2
        assert len(v["back_legs"][0]) == 4  # leg_id + 3

    def test_missing_points_deduplicated(self, sample_keypoints_v3, v3_schema):
        """缺失点列表去重。"""
        kp = dict(sample_keypoints_v3)
        # 让 base 缺失：direction1 (base→knee) 和 leg 都缺 base
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": None, "knee": [195, 140], "mid": [200, 170], "end": [205, 220]},
            {"leg_id": "back_leg_2", "base": None, "knee": None, "mid": [220, 175], "end": [225, 225]},
        ]
        result = pvu.generate_vectors_for_sample(kp, v3_schema["vector_rules"])
        mp = result["missing_points"]
        # back_leg_1.base 只出现一次
        assert mp.count("back_leg_1.base") == 1


# =========================== Schema 权重动态读取 ===========================

class TestDirectionWeights:
    """验证 direction_weights 从 schema 动态读取，无写死。"""

    def test_v3_back_leg_weights(self, v3_schema):
        w = v3_schema["vector_rules"]["back_legs"]["direction_weights"]
        assert w == {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4}

    def test_v3_front_leg_weights(self, v3_schema):
        w = v3_schema["vector_rules"]["front_legs"]["direction_weights"]
        assert w == {"leg_direction1": 0.5, "leg_direction2": 0.5}

    def test_v3_weights_sum(self, v3_schema):
        for group in ["front_legs", "back_legs"]:
            w = v3_schema["vector_rules"][group]["direction_weights"]
            assert sum(w.values()) == pytest.approx(1.0)

    def test_v1_weights(self, v1_schema):
        w = v1_schema["vector_rules"]["back_legs"]["direction_weights"]
        assert w == {"leg_direction1": 0.5, "leg_direction2": 0.5}

    def test_weights_dynamic_count(self, v3_schema):
        """验证 direction_weights 条目数与方向数匹配，无硬编码常量。"""
        for group in ["front_legs", "back_legs"]:
            rule = v3_schema["vector_rules"][group]
            # 动态计数方向数
            d_count = sum(1 for k in rule if k.startswith("direction") and k[9:].isdigit())
            w_count = len(rule["direction_weights"])
            assert d_count == w_count, f"{group}: {d_count} directions but {w_count} weights"

    def test_weighted_score_manual(self, v3_schema):
        """人工验证：1.0, 0.0, 1.0 → 0.8"""
        w = v3_schema["vector_rules"]["back_legs"]["direction_weights"]
        sims = [1.0, 0.0, 1.0]
        score = sum(s * w[k] for s, k in zip(sims, sorted(w.keys())))
        assert score == pytest.approx(0.8)


# =========================== 完整管道 v1 ===========================

class TestFullPipelineV1:
    def test_generate_with_v1_schema(self, sample_keypoints_v1, v1_schema):
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v1, v1_schema["vector_rules"])
        v = result["vectors"]
        assert v["available"]["head"] is True
        assert len(v["front_legs"]) == 2
        assert v["front_legs"][0]["anchor_point"] == "body.body_1"


# =========================== JSON 输入/输出 ===========================

class TestJsonIO:
    def test_full_generate_pose_vectors(self, temp_dir, sample_keypoints_v3, v3_schema):
        """完整管道：keypoints JSON → pose_vectors JSON。"""
        kp_data = {
            "project": "pony_pose_search_mvp0",
            "version": "mvp0_keypoints_v1",
            "keypoint_schema_id": "pony_unicorn_no_wings_mvp0_v3",
            "character_id": "twilight_unicorn",
            "episode_id": "s01e15",
            "season": 1, "episode": 15,
            "items": [
                {
                    "sample_id": "test_001",
                    "frame_id": "f1", "episode_id": "s01e15",
                    "character_id": "twilight_unicorn",
                    "timestamp_sec": 0,
                    "frame_path": "f.png", "crop_path": "c.png",
                    "keypoints": sample_keypoints_v3,
                    "note": "",
                }
            ],
        }

        schemas_data = {
            "version": "keypoint_schemas_v1",
            "schemas": {
                "pony_unicorn_no_wings_mvp0_v3": v3_schema,
            }
        }

        result = m06.generate_pose_vectors(kp_data, schemas_data)

        assert result["project"] == "pony_pose_search_mvp0"
        assert result["version"] == "mvp0_pose_vectors_v1"
        assert result["keypoint_schema_id"] == "pony_unicorn_no_wings_mvp0_v3"
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["sample_id"] == "test_001"
        assert len(item["vectors"]["back_legs"][0]) == 4  # leg_id + 3 directions

    def test_missing_schema_id(self, temp_dir, sample_keypoints_v3, v3_schema):
        kp_data = {"keypoint_schema_id": "", "items": []}
        schemas_data = {"schemas": {"v3": v3_schema}}
        with pytest.raises(ValueError, match="missing keypoint_schema_id"):
            m06.generate_pose_vectors(kp_data, schemas_data)

    def test_unknown_schema_id(self, temp_dir, sample_keypoints_v3, v3_schema):
        kp_data = {"keypoint_schema_id": "nonexistent", "items": []}
        schemas_data = {"schemas": {"v3": v3_schema}}
        with pytest.raises(ValueError, match="not found"):
            m06.generate_pose_vectors(kp_data, schemas_data)


# =========================== 路径 ===========================

class TestPaths:
    def test_keypoints_path(self):
        p = m06.build_keypoints_path("/proj", "twilight_unicorn", "s01e15")
        assert p.replace("\\", "/").endswith(
            "keypoints/twilight_unicorn/s01/keypoints_twilight_unicorn_s01e15.json")

    def test_output_path(self):
        p = m06.build_output_path("/proj", "twilight_unicorn", "s01e15")
        assert p.replace("\\", "/").endswith(
            "poses/twilight_unicorn/s01/pose_vectors_twilight_unicorn_s01e15.json")


# =========================== v2 方向级测试 ===========================


class TestV2FrontLegs:
    """v2 前腿：base→mid (d1), mid→end (d2)，各方向独立。"""

    def _call(self, keypoints, vr):
        fl, avail, missing = pvu.compute_leg_vectors(
            keypoints, vr, "front_legs", version="v2")
        return fl, avail, missing

    def test_base_missing_only_disables_d1(self, sample_keypoints_v3, v3_schema):
        """base缺失时只禁用direction1，direction2保留。"""
        kp = dict(sample_keypoints_v3)
        kp["front_legs"] = [
            {"leg_id": "front_leg_1", "base": None, "mid": [65, 160], "end": [60, 210]},
            {"leg_id": "front_leg_2", "base": [90, 115], "mid": [85, 165], "end": [80, 215]},
        ]
        fl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = fl[0]["directions"]
        assert d["leg_direction1"]["available"] is False
        assert d["leg_direction1"]["vector"] is None
        assert "front_leg_1.base" in d["leg_direction1"]["missing_points"]
        assert d["leg_direction2"]["available"] is True
        assert d["leg_direction2"]["vector"] is not None
        assert avail["front_leg_1"] is True

    def test_mid_missing_disables_both(self, sample_keypoints_v3, v3_schema):
        """mid缺失时两个方向均不可用。"""
        kp = dict(sample_keypoints_v3)
        kp["front_legs"] = [
            {"leg_id": "front_leg_1", "base": [70, 110], "mid": None, "end": [60, 210]},
        ]
        fl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = fl[0]["directions"]
        assert d["leg_direction1"]["available"] is False  # base→mid，mid缺失
        assert d["leg_direction2"]["available"] is False  # mid→end，mid缺失
        assert avail["front_leg_1"] is False

    def test_end_missing_only_disables_d2(self, sample_keypoints_v3, v3_schema):
        """end缺失时只禁用direction2，direction1保留。"""
        kp = dict(sample_keypoints_v3)
        kp["front_legs"] = [
            {"leg_id": "front_leg_1", "base": [70, 110], "mid": [65, 160], "end": None},
        ]
        fl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = fl[0]["directions"]
        assert d["leg_direction1"]["available"] is True
        assert d["leg_direction2"]["available"] is False
        assert "front_leg_1.end" in d["leg_direction2"]["missing_points"]
        assert avail["front_leg_1"] is True

    def test_d1_zero_length_does_not_affect_d2(self, sample_keypoints_v3, v3_schema):
        """d1零长度只禁用d1，不影响d2。"""
        kp = dict(sample_keypoints_v3)
        kp["front_legs"] = [
            {"leg_id": "front_leg_1", "base": [70, 110], "mid": [70, 110], "end": [60, 210]},
        ]
        fl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = fl[0]["directions"]
        assert d["leg_direction1"]["available"] is False  # 零长度
        assert d["leg_direction1"]["vector"] is None
        assert d["leg_direction2"]["available"] is True  # mid→end正常
        assert d["leg_direction2"]["vector"] is not None
        assert avail["front_leg_1"] is True

    def test_d2_zero_length_does_not_affect_d1(self, sample_keypoints_v3, v3_schema):
        """d2零长度只禁用d2，不影响d1。"""
        kp = dict(sample_keypoints_v3)
        kp["front_legs"] = [
            {"leg_id": "front_leg_1", "base": [70, 110], "mid": [65, 160], "end": [65, 160]},
        ]
        fl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = fl[0]["directions"]
        assert d["leg_direction1"]["available"] is True
        assert d["leg_direction2"]["available"] is False  # 零长度
        assert avail["front_leg_1"] is True


class TestV2BackLegs:
    """v2 后腿：base→knee (d1), knee→mid (d2), mid→end (d3)，各方向独立。"""

    def _call(self, keypoints, vr):
        bl, avail, missing = pvu.compute_leg_vectors(
            keypoints, vr, "back_legs", version="v2")
        return bl, avail, missing

    def test_base_missing_preserves_d2_d3(self, sample_keypoints_v3, v3_schema):
        """base缺失→d1不可用，d2/d3保留。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": None, "knee": [195, 140], "mid": [200, 170], "end": [205, 220]},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is False
        assert "back_leg_1.base" in d["leg_direction1"]["missing_points"]
        assert d["leg_direction2"]["available"] is True
        assert d["leg_direction3"]["available"] is True
        assert avail["back_leg_1"] is True

    def test_knee_missing_preserves_d3(self, sample_keypoints_v3, v3_schema):
        """knee缺失→d1/d2不可用，d3保留。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": None, "mid": [200, 170], "end": [205, 220]},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is False
        assert d["leg_direction2"]["available"] is False
        assert d["leg_direction3"]["available"] is True
        assert avail["back_leg_1"] is True

    def test_mid_missing_preserves_d1(self, sample_keypoints_v3, v3_schema):
        """mid缺失→d2/d3不可用，d1保留。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": [195, 140], "mid": None, "end": [205, 220]},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is True
        assert d["leg_direction2"]["available"] is False
        assert d["leg_direction3"]["available"] is False
        assert avail["back_leg_1"] is True

    def test_end_missing_preserves_d1_d2(self, sample_keypoints_v3, v3_schema):
        """end缺失→d3不可用，d1/d2保留。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": [195, 140], "mid": [200, 170], "end": None},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is True
        assert d["leg_direction2"]["available"] is True
        assert d["leg_direction3"]["available"] is False
        assert "back_leg_1.end" in d["leg_direction3"]["missing_points"]
        assert avail["back_leg_1"] is True

    def test_d1_zero_does_not_affect_d2_d3(self, sample_keypoints_v3, v3_schema):
        """d1零长度不影响d2/d3。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": [190, 115], "mid": [200, 170], "end": [205, 220]},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is False
        assert d["leg_direction2"]["available"] is True
        assert d["leg_direction3"]["available"] is True
        assert avail["back_leg_1"] is True

    def test_d2_zero_does_not_affect_d1_d3(self, sample_keypoints_v3, v3_schema):
        """d2零长度不影响d1/d3。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": [195, 140], "mid": [195, 140], "end": [205, 220]},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is True
        assert d["leg_direction2"]["available"] is False
        assert d["leg_direction3"]["available"] is True
        assert avail["back_leg_1"] is True

    def test_d3_zero_does_not_affect_d1_d2(self, sample_keypoints_v3, v3_schema):
        """d3零长度不影响d1/d2。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": [195, 140], "mid": [200, 170], "end": [200, 170]},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is True
        assert d["leg_direction2"]["available"] is True
        assert d["leg_direction3"]["available"] is False
        assert avail["back_leg_1"] is True

    def test_all_points_missing(self, sample_keypoints_v3, v3_schema):
        """所有点缺失→所有方向不可用。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": None, "knee": None, "mid": None, "end": None},
        ]
        bl, avail, missing = self._call(kp, v3_schema["vector_rules"])
        d = bl[0]["directions"]
        assert d["leg_direction1"]["available"] is False
        assert d["leg_direction2"]["available"] is False
        assert d["leg_direction3"]["available"] is False
        assert avail["back_leg_1"] is False


class TestV2Format:
    """v2 输出格式验证。"""

    def test_each_direction_has_entry(self, sample_keypoints_v3, v3_schema):
        """v2中schema定义的每个方向都有对象。"""
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v3, v3_schema["vector_rules"], version="v2")
        v = result["vectors"]
        bl = v["back_legs"][0]
        assert set(bl["directions"].keys()) == {"leg_direction1", "leg_direction2", "leg_direction3"}
        fl = v["front_legs"][0]
        assert set(fl["directions"].keys()) == {"leg_direction1", "leg_direction2"}

    def test_unavailable_vector_is_null(self, sample_keypoints_v3, v3_schema):
        """unavailable时vector=null。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": None, "knee": [195, 140], "mid": [200, 170], "end": [205, 220]},
        ]
        result = pvu.generate_vectors_for_sample(
            kp, v3_schema["vector_rules"], version="v2")
        d = result["vectors"]["back_legs"][0]["directions"]
        assert d["leg_direction1"]["vector"] is None
        assert d["leg_direction1"]["available"] is False

    def test_available_vector_length_near_one(self, sample_keypoints_v3, v3_schema):
        """available方向向量长度≈1。"""
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v3, v3_schema["vector_rules"], version="v2")
        for dname, d in result["vectors"]["back_legs"][0]["directions"].items():
            if d["available"]:
                import math
                length = math.hypot(d["vector"][0], d["vector"][1])
                assert length == pytest.approx(1.0)

    def test_version_string_v2(self, temp_dir, sample_keypoints_v3, v3_schema):
        """顶层version正确设置为v2。"""
        kp_data = {
            "project": "pony_pose_search_mvp0",
            "version": "mvp0_keypoints_v1",
            "keypoint_schema_id": "pony_unicorn_no_wings_mvp0_v3",
            "character_id": "twilight_unicorn",
            "episode_id": "s01e15",
            "season": 1, "episode": 15,
            "items": [{
                "sample_id": "test_001", "frame_id": "f1",
                "episode_id": "s01e15", "character_id": "twilight_unicorn",
                "timestamp_sec": 0, "frame_path": "f.png", "crop_path": "c.png",
                "keypoints": sample_keypoints_v3, "note": "",
            }],
        }
        schemas_data = {"version": "keypoint_schemas_v1",
                        "schemas": {"pony_unicorn_no_wings_mvp0_v3": v3_schema}}
        result = m06.generate_pose_vectors(kp_data, schemas_data, version="v2")
        assert result["version"] == "mvp0_pose_vectors_v2"

    def test_missing_points_deduplicated_v2(self, sample_keypoints_v3, v3_schema):
        """顶层missing_points去重。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": None, "knee": None, "mid": [200, 170], "end": [205, 220]},
        ]
        result = pvu.generate_vectors_for_sample(
            kp, v3_schema["vector_rules"], version="v2")
        mp = result["missing_points"]
        # knee缺失出现在d1和d2的missing_points中，但顶层只出现一次
        assert mp.count("back_leg_1.knee") == 1
        assert mp.count("back_leg_1.base") == 1

    def test_keypoint_in_multiple_direction_missing(self, sample_keypoints_v3, v3_schema):
        """一个关键点可同时出现在多个方向的missing_points中。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": None, "mid": [200, 170], "end": [205, 220]},
        ]
        result = pvu.generate_vectors_for_sample(
            kp, v3_schema["vector_rules"], version="v2")
        d = result["vectors"]["back_legs"][0]["directions"]
        # knee缺失影响d1(to)和d2(from)
        assert "back_leg_1.knee" in d["leg_direction1"]["missing_points"]
        assert "back_leg_1.knee" in d["leg_direction2"]["missing_points"]


class TestV2Compatibility:
    """v1/v2 兼容性测试。"""

    def test_default_is_v1(self, sample_keypoints_v3, v3_schema):
        """不传版本参数时仍输出v1。"""
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v3, v3_schema["vector_rules"])
        bl = result["vectors"]["back_legs"][0]
        # v1: leg_direction1直接在leg级，无directions子结构
        assert "leg_direction1" in bl
        assert "directions" not in bl

    def test_explicit_v1_unchanged(self, sample_keypoints_v3, v3_schema):
        """显式选择v1时结果不变。"""
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v3, v3_schema["vector_rules"], version="v1")
        bl = result["vectors"]["back_legs"][0]
        assert "leg_direction1" in bl
        assert "directions" not in bl

    def test_explicit_v2_new_structure(self, sample_keypoints_v3, v3_schema):
        """显式选择v2时生成新结构。"""
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v3, v3_schema["vector_rules"], version="v2")
        bl = result["vectors"]["back_legs"][0]
        assert "directions" in bl
        assert "leg_direction1" not in bl  # v2不在腿级直接放向量

    def test_simple_vectors_unchanged_in_v2(self, sample_keypoints_v3, v3_schema):
        """非腿部向量在v2中行为不变。"""
        result = pvu.generate_vectors_for_sample(
            sample_keypoints_v3, v3_schema["vector_rules"], version="v2")
        assert "head_direction" in result["vectors"]
        assert "neck_direction" in result["vectors"]
        assert "body_direction" in result["vectors"]
        assert "tail_direction" in result["vectors"]
        assert result["vectors"]["available"]["head"] is True

    def test_old_v1_test_behavior_preserved(self, sample_keypoints_v3, v3_schema):
        """v1整腿不可用行为不变（旧测试语义保留）。"""
        kp = dict(sample_keypoints_v3)
        kp["back_legs"] = [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": None, "mid": [200, 170], "end": [205, 220]},
            {"leg_id": "back_leg_2", "base": [210, 120], "knee": [215, 145], "mid": [220, 175], "end": [225, 225]},
        ]
        # v1: knee缺失→整腿unavailable
        bl_v1, avail_v1, _ = pvu.compute_leg_vectors(
            kp, v3_schema["vector_rules"], "back_legs", version="v1")
        assert avail_v1["back_leg_1"] is False  # 整腿不可用

        # v2: knee缺失→d1/d2不可用，d3可用，腿整体可用
        bl_v2, avail_v2, _ = pvu.compute_leg_vectors(
            kp, v3_schema["vector_rules"], "back_legs", version="v2")
        assert avail_v2["back_leg_1"] is True  # 至少d3可用


# =========================== v2 输出隔离测试 ===========================




class TestImportIsolation:
    """M06 和 M07 都从 common 导入，M07 不导入 M06。"""

    def test_m06_imports_from_common(self):
        """M06 从 scripts/common 导入共享函数。"""
        import generate_pose_vectors
        # 验证 M06 模块中可访问共享函数（通过 common 导入）
        assert hasattr(generate_pose_vectors, 'generate_vectors_for_sample')

    def test_m07_does_not_import_m06(self):
        """M07 不导入 M06 模块。"""
        # 动态检查 M07 的导入
        import importlib.util
        spec = importlib.util.find_spec('annotate_query_pose')
        if spec is None:
            # M07 有 GUI 依赖，在无 display 环境中可能无法导入模块级别
            # 改用源码检查
            m07_path = os.path.join(os.path.dirname(__file__), "..", "..",
                                    "scripts", "m07", "annotate_query_pose.py")
            with open(m07_path, "r", encoding="utf-8") as f:
                code = f.read()
            assert "from generate_pose_vectors import" not in code
            assert "from workflow.cli import" in code
        else:
            # 如果能导入，检查其属性
            import annotate_query_pose
            src = __import__('inspect').getsource(annotate_query_pose)
            assert "from generate_pose_vectors import" not in src

    def test_common_module_exports_all_shared(self):
        """pose_vector_utils 导出所有共享函数。"""
        expected = ['unit_direction', 'resolve_keypoint', 'compute_simple_vectors',
                     'compute_leg_vectors', 'generate_vectors_for_sample']
        for name in expected:
            assert hasattr(pvu, name), f"{name} missing from pose_vector_utils"
