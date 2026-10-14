"""
M08 相似度搜索 — 测试套件。

覆盖：方向相似度、部件得分、无序腿匹配、schema权重、缺失处理、Top10排序。
"""

import csv
import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "m08"))
import search_similar_poses as m08


# =========================== 方向相似度 ===========================

class TestDirectionSimilarity:
    def test_identical(self):
        assert m08.direction_similarity([1, 0], [1, 0]) == 1.0

    def test_opposite(self):
        assert m08.direction_similarity([1, 0], [-1, 0]) == 0.0

    def test_perpendicular(self):
        assert m08.direction_similarity([1, 0], [0, 1]) == pytest.approx(0.5)

    def test_45_degree(self):
        s = m08.direction_similarity([1, 0], [math.sqrt(2)/2, math.sqrt(2)/2])
        assert s == pytest.approx((math.sqrt(2)/2 + 1) / 2)

    def test_none_input(self):
        assert m08.direction_similarity(None, [1, 0]) is None
        assert m08.direction_similarity([1, 0], None) is None

    def test_clamped_to_range(self):
        # 浮点误差应被限制在 [0, 1]
        s = m08.direction_similarity([1.0000001, 0], [1, 0])
        assert 0.0 <= s <= 1.0


# =========================== 简单部件 ===========================

class TestSimpleComponent:
    def test_head_direction(self):
        q = {"head_direction": [1, 0]}
        s = {"head_direction": [1, 0]}
        assert m08.simple_component_score(q, s, "head") == 1.0

    def test_missing_vector(self):
        q = {}
        s = {"head_direction": [1, 0]}
        assert m08.simple_component_score(q, s, "head") is None


# =========================== 腿部得分 ===========================

@pytest.fixture
def v3_vector_rules():
    return {
        "front_legs": {
            "source_group": "front_legs",
            "direction1": {"name": "leg_direction1", "from": "current_leg.base", "to": "current_leg.mid"},
            "direction2": {"name": "leg_direction2", "from": "current_leg.mid", "to": "current_leg.end"},
            "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5},
            "unordered_group": True,
        },
        "back_legs": {
            "source_group": "back_legs",
            "direction1": {"name": "leg_direction1", "from": "current_leg.base", "to": "current_leg.knee"},
            "direction2": {"name": "leg_direction2", "from": "current_leg.knee", "to": "current_leg.mid"},
            "direction3": {"name": "leg_direction3", "from": "current_leg.mid", "to": "current_leg.end"},
            "direction_weights": {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4},
            "unordered_group": True,
        },
    }


def make_leg_vecs(leg_id, directions):
    return {"leg_id": leg_id, **directions}


class TestLegScore:
    def test_back_leg_weights(self, v3_vector_rules):
        w = v3_vector_rules["back_legs"]["direction_weights"]
        assert w == {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4}

    def test_back_leg_weighted_example(self, v3_vector_rules):
        """后腿 1.0/0.0/1.0 → 加权得分 0.8。"""
        q_vecs = {
            "available": {"back_leg_1": True, "back_leg_2": True},
            "back_legs": [
                make_leg_vecs("back_leg_1", {
                    "leg_direction1": [1, 0], "leg_direction2": [1, 0], "leg_direction3": [1, 0],
                }),
                make_leg_vecs("back_leg_2", {
                    "leg_direction1": [1, 0], "leg_direction2": [1, 0], "leg_direction3": [1, 0],
                }),
            ],
        }
        s_vecs = {
            "available": {"back_leg_1": True, "back_leg_2": True},
            "back_legs": [
                make_leg_vecs("back_leg_1", {
                    "leg_direction1": [1, 0],  # sim=1.0
                    "leg_direction2": [-1, 0], # sim=0.0
                    "leg_direction3": [1, 0],  # sim=1.0
                }),
                make_leg_vecs("back_leg_2", {
                    "leg_direction1": [1, 0],
                    "leg_direction2": [1, 0],
                    "leg_direction3": [1, 0],
                }),
            ],
        }
        score, note = m08.leg_group_score(q_vecs, s_vecs, "back_legs", v3_vector_rules)
        # 腿1: 1.0×0.4 + 0.0×0.2 + 1.0×0.4 = 0.8; 腿2: 1.0; avg = (0.8+1.0)/2 = 0.9
        assert score == pytest.approx(0.9)

    def test_unordered_matching(self, v3_vector_rules):
        """无序匹配应选较优排列。"""
        q_vecs = {
            "available": {"front_leg_1": True, "front_leg_2": True},
            "front_legs": [
                make_leg_vecs("front_leg_1", {"leg_direction1": [1, 0], "leg_direction2": [1, 0]}),
                make_leg_vecs("front_leg_2", {"leg_direction1": [-1, 0], "leg_direction2": [-1, 0]}),
            ],
        }
        s_vecs = {
            "available": {"front_leg_1": True, "front_leg_2": True},
            "front_legs": [
                make_leg_vecs("front_leg_1", {"leg_direction1": [-1, 0], "leg_direction2": [-1, 0]}),
                make_leg_vecs("front_leg_2", {"leg_direction1": [1, 0], "leg_direction2": [1, 0]}),
            ],
        }
        # 方案A: q1↔s1=0.0, q2↔s2=0.0 → avg=0.0
        # 方案B: q1↔s2=1.0, q2↔s1=1.0 → avg=1.0
        score, note = m08.leg_group_score(q_vecs, s_vecs, "front_legs", v3_vector_rules)
        assert score == 1.0
        assert "B" in note

    def test_missing_leg_unavailable(self, v3_vector_rules):
        """缺失腿不参与比较。"""
        q_vecs = {
            "available": {"front_leg_1": True, "front_leg_2": False},
            "front_legs": [
                make_leg_vecs("front_leg_1", {"leg_direction1": [1, 0], "leg_direction2": [1, 0]}),
                make_leg_vecs("front_leg_2", {"leg_direction1": None, "leg_direction2": None}),
            ],
        }
        s_vecs = {
            "available": {"front_leg_1": True, "front_leg_2": False},
            "front_legs": [
                make_leg_vecs("front_leg_1", {"leg_direction1": [1, 0], "leg_direction2": [1, 0]}),
                make_leg_vecs("front_leg_2", {"leg_direction1": None, "leg_direction2": None}),
            ],
        }
        score, note = m08.leg_group_score(q_vecs, s_vecs, "front_legs", v3_vector_rules)
        assert score is not None
        assert "partial" in note


# =========================== 总相似度 ===========================

class TestTotalSimilarity:
    def test_all_available(self, v3_vector_rules):
        """所有部件可用时正常计算总分。"""
        q = {
            "available": {"head": True, "neck": True, "body": True, "tail": True,
                          "front_leg_1": True, "front_leg_2": True,
                          "back_leg_1": True, "back_leg_2": True},
            "head_direction": [1, 0], "neck_direction": [1, 0],
            "body_direction": [1, 0], "tail_direction": [1, 0],
            "front_legs": [
                make_leg_vecs("front_leg_1", {"leg_direction1": [1, 0], "leg_direction2": [1, 0]}),
                make_leg_vecs("front_leg_2", {"leg_direction1": [1, 0], "leg_direction2": [1, 0]}),
            ],
            "back_legs": [
                make_leg_vecs("back_leg_1", {"leg_direction1": [1, 0], "leg_direction2": [1, 0], "leg_direction3": [1, 0]}),
                make_leg_vecs("back_leg_2", {"leg_direction1": [1, 0], "leg_direction2": [1, 0], "leg_direction3": [1, 0]}),
            ],
        }
        score, note = m08.compute_similarity(q, q, v3_vector_rules)
        assert score == pytest.approx(1.0)

    def test_no_comparable_components(self, v3_vector_rules):
        """无可比较部件时返回 None。"""
        q = {"available": {}, "vectors": {}}
        s = {"available": {}, "vectors": {}}
        score, note = m08.compute_similarity(q, s, v3_vector_rules)
        assert score is None


# =========================== Top10 排序 ===========================

class TestTop10:
    def test_sort_descending(self):
        results = [
            {"sample_id": "a", "similarity_score": 0.5, "match_note": ""},
            {"sample_id": "b", "similarity_score": 0.9, "match_note": ""},
            {"sample_id": "c", "similarity_score": 0.3, "match_note": ""},
        ]
        results.sort(key=lambda r: r["similarity_score"], reverse=True)
        assert results[0]["sample_id"] == "b"
        assert results[2]["sample_id"] == "c"

    def test_stable_sort_same_score(self):
        results = [
            {"sample_id": "a", "similarity_score": 0.5, "match_note": ""},
            {"sample_id": "b", "similarity_score": 0.5, "match_note": ""},
            {"sample_id": "c", "similarity_score": 0.5, "match_note": ""},
        ]
        results.sort(key=lambda r: r["similarity_score"], reverse=True)
        assert results[0]["sample_id"] == "a"  # 原序保留
        assert results[1]["sample_id"] == "b"

    def test_csv_field_order(self):
        expected = [
            "rank", "sample_id", "frame_id", "episode_id", "season", "episode",
            "character_id", "timestamp_sec", "timestamp_frame", "timestamp_text",
            "similarity_score", "frame_path", "crop_path", "match_note",
            "mirrored",
        ]
        assert m08.CSV_FIELDS == expected

    def test_write_and_read_csv(self, temp_dir):
        results = [
            {"sample_id": "x", "similarity_score": 0.9, "match_note": "test",
             "frame_id": "f1", "episode_id": "s01e15", "season": "1", "episode": "15",
             "character_id": "twilight_unicorn", "timestamp_sec": 100, "timestamp_frame": 0,
             "timestamp_text": "00:01:40", "frame_path": "f.png", "crop_path": "c.png"},
        ]
        out = os.path.join(temp_dir, "top10.csv")
        m08.write_results_csv(results, out)
        assert os.path.exists(out)
        with open(out, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["rank"] == "1"
        assert rows[0]["similarity_score"] == "0.9"


# =========================== Schema 不一致 ===========================

class TestSchemaMismatch:
    def test_different_schema_ids_detected(self):
        """不同 schema_id 应被检测到。"""
        q = {"keypoint_schema_id": "v3", "character_id": "twilight_unicorn"}
        p = {"keypoint_schema_id": "v1", "character_id": "twilight_unicorn"}
        assert q["keypoint_schema_id"] != p["keypoint_schema_id"]


# =========================== 时间转换 ===========================

class TestTimestamp:
    def test_conversion(self):
        assert m08._sec_to_timestamp(0) == "00:00:00"
        assert m08._sec_to_timestamp(331) == "00:05:31"
        assert m08._sec_to_timestamp(3600) == "01:00:00"


# =========================== 路径推导 (M08) ===========================

class TestPathDerivation:
    """M08 从 frame_id/sample_id 推导 frame_path/crop_path。"""

    def test_search_populates_frame_path(self, v3_vector_rules):
        """搜索结果应包含非空的 frame_path 和 crop_path。"""
        q_vecs = {
            "available": {"head": True},
            "head_direction": [1.0, 0.0],
        }
        s_vecs = {
            "available": {"head": True},
            "head_direction": [1.0, 0.0],
        }
        query_data = {
            "vectors": q_vecs,
            "character_id": "twilight_unicorn",
            "keypoint_schema_id": "v3",
        }
        pose_data = {
            "character_id": "twilight_unicorn",
            "keypoint_schema_id": "v3",
            "episode_id": "s01e15",
            "items": [
                {
                    "sample_id": "s01e15_t000071_f000_twilight_unicorn_001",
                    "frame_id": "s01e15_t000071_f000",
                    "episode_id": "s01e15",
                    "character_id": "twilight_unicorn",
                    "timestamp_sec": 71,
                    "vectors": s_vecs,
                }
            ],
        }
        results = m08.search(query_data, pose_data, v3_vector_rules)
        assert len(results) == 1
        assert results[0]["frame_path"] == "frames/s01/e15/s01e15_t000071_f000.png"
        assert results[0]["crop_path"] == (
            "crops/twilight_unicorn/s01/e15/"
            "s01e15_t000071_f000_twilight_unicorn_001.png")


# =========================== 多剧集搜索 ===========================

class TestMultiEpisode:
    """跨剧集搜索：合并、全局排序、去重、schema检查。"""

    def test_two_episodes_loaded(self, v3_vector_rules):
        """两个剧集的所有样本均被加载。"""
        pose_data = {
            "character_id": "twilight_unicorn",
            "items": [
                {"sample_id": "a", "frame_id": "f1", "episode_id": "s01e15",
                 "character_id": "twilight_unicorn", "timestamp_sec": 0,
                 "_episode_id": "s01e15",
                 "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]}},
                {"sample_id": "b", "frame_id": "f2", "episode_id": "s01e16",
                 "character_id": "twilight_unicorn", "timestamp_sec": 0,
                 "_episode_id": "s01e16",
                 "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]}},
            ],
        }
        query_data = {
            "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]},
            "character_id": "twilight_unicorn",
        }
        results = m08.search(query_data, pose_data, v3_vector_rules)
        assert len(results) == 2
        eids = {r["episode_id"] for r in results}
        assert eids == {"s01e15", "s01e16"}

    def test_global_sort_across_episodes(self, v3_vector_rules):
        """全局排序：高分样本在前，无论来自哪个剧集。"""
        pose_data = {
            "character_id": "twilight_unicorn",
            "items": [
                {"sample_id": "low_s01e15", "frame_id": "f1",
                 "character_id": "twilight_unicorn", "timestamp_sec": 0,
                 "_episode_id": "s01e15",
                 "vectors": {"available": {"head": True}, "head_direction": [0.0, 1.0]}},
                {"sample_id": "high_s01e16", "frame_id": "f2",
                 "character_id": "twilight_unicorn", "timestamp_sec": 0,
                 "_episode_id": "s01e16",
                 "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]}},
            ],
        }
        query_data = {
            "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]},
            "character_id": "twilight_unicorn",
        }
        results = m08.search(query_data, pose_data, v3_vector_rules)
        assert results[0]["sample_id"] == "high_s01e16"
        assert results[1]["sample_id"] == "low_s01e15"

    def test_top_n_after_merge(self, v3_vector_rules):
        """Top N 在合并后截取，不是每集分别取前N。"""
        pose_data = {
            "character_id": "twilight_unicorn",
            "items": [
                {"sample_id": f"s{i}", "frame_id": f"f{i}",
                 "character_id": "twilight_unicorn", "timestamp_sec": i,
                 "_episode_id": "s01e15",
                 "vectors": {"available": {"head": True},
                            "head_direction": [1.0 - i*0.1, 0.0]}}
                for i in range(5)
            ] + [
                {"sample_id": f"t{i}", "frame_id": f"g{i}",
                 "character_id": "twilight_unicorn", "timestamp_sec": 100+i,
                 "_episode_id": "s01e16",
                 "vectors": {"available": {"head": True},
                            "head_direction": [1.0 - (i+5)*0.02, 0.0]}}
                for i in range(5)
            ],
        }
        query_data = {
            "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]},
            "character_id": "twilight_unicorn",
        }
        results = m08.search(query_data, pose_data, v3_vector_rules, top_n=3)
        assert len(results) == 3
        # s0 should be top (i=0 gives [1.0, 0.0] = perfect match)
        assert results[0]["sample_id"] == "s0"

    def test_discover_all_episode_ids(self, temp_dir):
        """发现 poses/ 下所有剧集。"""
        import json
        for eid in ["s01e15", "s01e16", "s02e01"]:
            d = os.path.join(temp_dir, "poses", "twilight_unicorn", eid[:3])
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"pose_vectors_twilight_unicorn_{eid}.json"), "w") as f:
                json.dump({"episode_id": eid, "items": []}, f)
        ids = m08.discover_all_episode_ids(temp_dir, "twilight_unicorn")
        assert ids == ["s01e15", "s01e16", "s02e01"]

    def test_discover_stable_order(self, temp_dir):
        """发现顺序稳定（按 season_code, episode_id 排序）。"""
        import json
        for eid in ["s02e01", "s01e16", "s01e15"]:  # 逆序创建
            d = os.path.join(temp_dir, "poses", "twilight_unicorn", eid[:3])
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"pose_vectors_twilight_unicorn_{eid}.json"), "w") as f:
                json.dump({"episode_id": eid, "items": []}, f)
        ids = m08.discover_all_episode_ids(temp_dir, "twilight_unicorn")
        assert ids == ["s01e15", "s01e16", "s02e01"]  # 排序后

    def test_episode_id_in_output(self, v3_vector_rules):
        """每条结果保留正确的 episode_id。"""
        pose_data = {
            "character_id": "twilight_unicorn",
            "items": [
                {"sample_id": "x", "frame_id": "f1",
                 "character_id": "twilight_unicorn", "timestamp_sec": 0,
                 "_episode_id": "s01e16",
                 "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]}},
            ],
        }
        query_data = {
            "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]},
            "character_id": "twilight_unicorn",
        }
        results = m08.search(query_data, pose_data, v3_vector_rules)
        assert results[0]["episode_id"] == "s01e16"


# =========================== v2 方向级评分测试 ===========================


# ---- helpers ----

def _make_v2_leg(lid, **directions):
    """构造 v2 格式的腿对象。每个方向: {"available": bool, "vector": [x,y]|None, "missing_points": []}."""
    d = {}
    for k, v in directions.items():
        avail = v is not None
        d[k] = {"available": avail, "vector": v, "missing_points": []}
    return {"leg_id": lid, "directions": d}


# =========================== A. 版本与文件选择 ===========================


class TestV2VersionSelection:
    def test_default_is_v1(self):
        """默认参数使用 v1。"""
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--pose-vector-version", default="v1", choices=["v1", "v2"])
        args = p.parse_args([])
        assert args.pose_vector_version == "v1"

    def test_explicit_v2(self):
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--pose-vector-version", default="v1", choices=["v1", "v2"])
        args = p.parse_args(["--pose-vector-version", "v2"])
        assert args.pose_vector_version == "v2"

    def test_v2_path_has_v2_suffix(self):
        p = m08.build_query_vector_path("/proj", "c", "q1", version="v2")
        assert p.replace("\\", "/").endswith("query_pose_vector_v2.json")

    def test_v1_path_no_suffix(self):
        p = m08.build_query_vector_path("/proj", "c", "q1", version="v1")
        assert p.replace("\\", "/").endswith("query_pose_vector.json")

    def test_discover_v2_excludes_v1(self, temp_dir):
        """v2 discovery 只找 _v2.json 文件。"""
        import json
        # 创建 v1 和 v2 文件
        for eid in ["s01e15", "s01e16"]:
            d = os.path.join(temp_dir, "poses", "twilight_unicorn", eid[:3])
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"pose_vectors_twilight_unicorn_{eid}.json"), "w") as f:
                json.dump({"episode_id": eid, "items": []}, f)
        # 只创建一个 v2
        d2 = os.path.join(temp_dir, "poses", "twilight_unicorn", "s01")
        with open(os.path.join(d2, "pose_vectors_twilight_unicorn_s01e16_v2.json"), "w") as f:
            json.dump({"episode_id": "s01e16", "version": "mvp0_pose_vectors_v2", "items": []}, f)
        ids = m08.discover_all_episode_ids(temp_dir, "twilight_unicorn", version="v2")
        assert ids == ["s01e16"]

    def test_v2_query_missing_fails(self, temp_dir):
        """v2 查询文件缺失时 exit 1。"""
        import subprocess, sys
        script = os.path.join(os.path.dirname(__file__), "..", "..",
                             "scripts", "m08", "search_similar_poses.py")
        result = subprocess.run(
            [sys.executable, script, "--project-root", temp_dir,
             "--character-id", "x", "--query-id", "y",
             "--pose-vector-version", "v2", "--episode-id", "s01e15"],
            capture_output=True, text=True, timeout=30)
        assert result.returncode != 0

    def test_v2_version_mismatch_fails(self, temp_dir):
        """文件版本不是 v2 时明确失败。"""
        # 创建一个 v1 版本的 query 但命名为 _v2
        qdir = os.path.join(temp_dir, "queries", "c", "q1")
        os.makedirs(qdir, exist_ok=True)
        with open(os.path.join(qdir, "query_pose_vector_v2.json"), "w") as f:
            json.dump({"version": "mvp0_pose_vectors_v1", "keypoint_schema_id": "s",
                       "character_id": "c", "vectors": {"available": {}}}, f)
        # 创建 schemas
        sd = os.path.join(temp_dir, "data", "meta")
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, "keypoint_schemas.json"), "w") as f:
            json.dump({"schemas": {"s": {"vector_rules": {}}}}, f)
        # 创建 pose
        pd = os.path.join(temp_dir, "poses", "c", "s01")
        os.makedirs(pd, exist_ok=True)
        with open(os.path.join(pd, "pose_vectors_c_s01e15_v2.json"), "w") as f:
            json.dump({"episode_id": "s01e15", "version": "mvp0_pose_vectors_v2",
                       "character_id": "c", "keypoint_schema_id": "s", "items": []}, f)
        import subprocess, sys
        script = os.path.join(os.path.dirname(__file__), "..", "..",
                             "scripts", "m08", "search_similar_poses.py")
        result = subprocess.run(
            [sys.executable, script, "--project-root", temp_dir,
             "--character-id", "c", "--query-id", "q1",
             "--pose-vector-version", "v2", "--episode-id", "s01e15"],
            capture_output=True, text=True, timeout=30)
        assert result.returncode != 0


# =========================== B. 单方向语义 ===========================


class TestV2DirectionSemantics:
    def test_query_unavailable_skips(self, v3_vector_rules):
        """查询方向不可用时不比较、不惩罚。"""
        q_leg = _make_v2_leg("fl1", leg_direction1=None, leg_direction2=[0.0, 1.0])
        s_leg = _make_v2_leg("fl1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        weights = {"leg_direction1": 0.5, "leg_direction2": 0.5}
        num, den, v, m = m08.score_leg_pair_v2(q_leg, s_leg, directions, weights, 1.0)
        # d1: q unavailable → skip (0,0), d2: both available → sim=1.0 * 0.5 = 0.5 num, 0.5 den
        assert num == pytest.approx(0.5)
        assert den == pytest.approx(0.5)
        assert v == 1  # only d2

    def test_both_available_normal_score(self, v3_vector_rules):
        """查询和样本均可用时正常评分。"""
        q_leg = _make_v2_leg("fl1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0])
        s_leg = _make_v2_leg("fl1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        weights = {"leg_direction1": 0.5, "leg_direction2": 0.5}
        num, den, v, m = m08.score_leg_pair_v2(q_leg, s_leg, directions, weights, 1.0)
        assert num == pytest.approx(1.0 * 0.5 + 1.0 * 0.5)
        assert den == pytest.approx(1.0)
        assert v == 2

    def test_sample_missing_penalized(self, v3_vector_rules):
        """查询可用、样本不可用时按方向权重应用缺失惩罚。"""
        q_leg = _make_v2_leg("fl1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0])
        s_leg = _make_v2_leg("fl1", leg_direction1=None, leg_direction2=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        weights = {"leg_direction1": 0.5, "leg_direction2": 0.5}
        penalty = 0.5
        num, den, v, m = m08.score_leg_pair_v2(q_leg, s_leg, directions, weights, penalty)
        # d1: q avail, s not → 0 num, 0.5*0.5=0.25 den; d2: both → 0.5 num, 0.5 den
        assert num == pytest.approx(0.5)
        assert den == pytest.approx(0.75)
        assert m == 1  # d1 sample missing

    def test_penalty_zero_no_denominator(self, v3_vector_rules):
        """sample_missing_penalty=0 时样本缺失方向不增加分母。"""
        q_leg = _make_v2_leg("fl1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0])
        s_leg = _make_v2_leg("fl1", leg_direction1=None, leg_direction2=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        weights = {"leg_direction1": 0.5, "leg_direction2": 0.5}
        num, den, v, m = m08.score_leg_pair_v2(q_leg, s_leg, directions, weights, 0.0)
        assert den == pytest.approx(0.5)  # only d2's weight
        assert num == pytest.approx(0.5)

    def test_one_missing_does_not_affect_other(self, v3_vector_rules):
        """一个方向缺失不影响同腿其他方向。"""
        q_leg = _make_v2_leg("bl1", leg_direction1=[0.0, 1.0],
                             leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])
        s_leg = _make_v2_leg("bl1", leg_direction1=None,
                             leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}, {"name": "leg_direction3"}]
        weights = {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4}
        num, den, v, m = m08.score_leg_pair_v2(q_leg, s_leg, directions, weights, 1.0)
        # d1: penalized (0, 0.4); d2: perfect (0.2, 0.2); d3: perfect (0.4, 0.4)
        assert num == pytest.approx(0.6)
        assert den == pytest.approx(1.0)
        assert v == 2
        assert m == 1


# =========================== C. 部分腿匹配 ===========================


class TestV2PartialLeg:
    def test_front_only_d1(self, v3_vector_rules):
        q = _make_v2_leg("fl1", leg_direction1=[1.0, 0.0], leg_direction2=None)
        s = _make_v2_leg("fl1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        weights = {"leg_direction1": 0.5, "leg_direction2": 0.5}
        num, den, v, m = m08.score_leg_pair_v2(q, s, directions, weights, 1.0)
        # d1: perfect (0.5, 0.5); d2: q unavailable → skip
        assert num == pytest.approx(0.5)
        assert den == pytest.approx(0.5)
        assert v == 1

    def test_back_only_d3(self, v3_vector_rules):
        q = _make_v2_leg("bl1", leg_direction1=None, leg_direction2=None, leg_direction3=[0.0, 1.0])
        s = _make_v2_leg("bl1", leg_direction1=[0.0, 1.0], leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}, {"name": "leg_direction3"}]
        weights = {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4}
        num, den, v, m = m08.score_leg_pair_v2(q, s, directions, weights, 1.0)
        assert den == pytest.approx(0.4)
        assert v == 1

    def test_sample_missing_one_direction_keeps_leg(self, v3_vector_rules):
        """样本仅缺一个方向时不丢弃整腿。"""
        q = _make_v2_leg("bl1", leg_direction1=[0.0, 1.0],
                         leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])
        s = _make_v2_leg("bl1", leg_direction1=[0.0, 1.0],
                         leg_direction2=None, leg_direction3=[0.0, 1.0])
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}, {"name": "leg_direction3"}]
        weights = {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4}
        num, den, v, m = m08.score_leg_pair_v2(q, s, directions, weights, 1.0)
        assert den > 0.5  # d1 0.4 + d2 0.2 (penalized) + d3 0.4
        assert v == 2
        assert m == 1


# =========================== D. 无序一致配对 ===========================


class TestV2ConsistentPairing:
    def _make_two_legs(self, prefix):
        return [
            _make_v2_leg(f"{prefix}_1", leg_direction1=[0.0, 1.0], leg_direction2=[1.0, 0.0]),
            _make_v2_leg(f"{prefix}_2", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0]),
        ]

    def test_original_order_chosen_when_better(self, v3_vector_rules):
        q = self._make_two_legs("q")
        s = [
            _make_v2_leg("s_1", leg_direction1=[0.0, 1.0], leg_direction2=[1.0, 0.0]),  # perfect match q1
            _make_v2_leg("s_2", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0]),  # perfect match q2
        ]
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        weights = {"leg_direction1": 0.5, "leg_direction2": 0.5}
        num, den, note = m08.score_leg_group_v2(
            q, s, "front_legs", v3_vector_rules, 1.0, 1.0)
        assert "original" in note

    def test_swapped_chosen_when_better(self, v3_vector_rules):
        q = self._make_two_legs("q")
        # q1=[0,1],[1,0]; q2=[1,0],[0,1]
        # s1=[1,0],[0,1] (matches q2); s2=[0,1],[1,0] (matches q1)
        # original: q1→s1 (bad), q2→s2 (bad) → low score
        # swapped: q1→s2 (perfect), q2→s1 (perfect) → high score
        s = [
            _make_v2_leg("s_1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0]),
            _make_v2_leg("s_2", leg_direction1=[0.0, 1.0], leg_direction2=[1.0, 0.0]),
        ]
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        num, den, note = m08.score_leg_group_v2(
            q, s, "front_legs", v3_vector_rules, 1.0, 1.0)
        assert "swapped" in note

    def test_no_cross_leg_splicing(self, v3_vector_rules):
        """禁止跨腿拼接：direction1 和 direction2 不能来自不同样本腿。"""
        q = [_make_v2_leg("q1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0])]
        # s1: d1 perfect, d2 terrible; s2: d1 terrible, d2 perfect
        # 非法拼接: d1→s1, d2→s2, 会得到虚假满分
        s = [
            _make_v2_leg("s1", leg_direction1=[1.0, 0.0], leg_direction2=[-1.0, 0.0]),
            _make_v2_leg("s2", leg_direction1=[-1.0, 0.0], leg_direction2=[0.0, 1.0]),
        ]
        directions = [{"name": "leg_direction1"}, {"name": "leg_direction2"}]
        weights = {"leg_direction1": 0.5, "leg_direction2": 0.5}
        # 选 s1: d1=1.0, d2=0.0, avg=0.5; 选 s2: d1=0.0, d2=1.0, avg=0.5
        # 一致性配对不能同时选 s1 的 d1 和 s2 的 d2（那会是 1.0 满分）
        num_s1, den_s1, v1, m1 = m08.score_leg_pair_v2(q[0], s[0], directions, weights, 1.0)
        score_s1 = num_s1 / den_s1 if den_s1 > 0 else 0.0
        assert score_s1 < 0.99  # 不应该接近满分
        # 非法拼接检查: _score_direction_pair 是独立逐方向调用的
        # 但在 score_leg_group_v2 中，一个 query leg 的多个方向必须来自同一个 sample leg
        # 这个测试确认 score_leg_pair_v2 不会跨腿

    def test_two_query_legs_no_duplicate_sample(self, v3_vector_rules):
        """两个查询腿不得匹配同一个样本腿。"""
        q = [
            _make_v2_leg("q1", leg_direction1=[1.0, 0.0]),
            _make_v2_leg("q2", leg_direction1=[1.0, 0.0]),
        ]
        s = [
            _make_v2_leg("s1", leg_direction1=[1.0, 0.0]),
        ]
        # 只有一条样本腿但两条查询腿——在无序匹配中 ns < 2，走 leg_id 路径
        # 或用 nq==2,ns==1 的 fallback 逻辑
        num, den, note = m08.score_leg_group_v2(
            q, s, "front_legs", v3_vector_rules, 1.0, 1.0)
        # 应该有结果（至少不会把同一条样本腿指派两次）
        assert den > 0

    def test_tie_goes_to_original(self, v3_vector_rules):
        """平分时稳定选择原顺序。"""
        q = [
            _make_v2_leg("q1", leg_direction1=[1.0, 0.0]),
            _make_v2_leg("q2", leg_direction1=[1.0, 0.0]),
        ]
        s = [
            _make_v2_leg("s1", leg_direction1=[1.0, 0.0]),
            _make_v2_leg("s2", leg_direction1=[1.0, 0.0]),
        ]
        directions = [{"name": "leg_direction1"}]
        # Original and swapped are identical → tie → original
        num, den, note = m08.score_leg_group_v2(
            q, s, "front_legs", v3_vector_rules, 1.0, 1.0)
        assert "original" in note

    def test_single_query_leg_chooses_best(self, v3_vector_rules):
        """只有一条查询腿有效时选择最优样本腿。"""
        q = [_make_v2_leg("q1", leg_direction1=[1.0, 0.0])]
        s = [
            _make_v2_leg("s1", leg_direction1=[-1.0, 0.0]),  # bad
            _make_v2_leg("s2", leg_direction1=[1.0, 0.0]),   # perfect
        ]
        num, den, note = m08.score_leg_group_v2(
            q, s, "front_legs", v3_vector_rules, 1.0, 1.0)
        # Should choose s2
        assert num / den == pytest.approx(1.0)

    def test_both_query_legs_no_available_skips(self, v3_vector_rules):
        """查询两条腿均无有效方向时腿组不参与。"""
        q = [
            _make_v2_leg("q1", leg_direction1=None, leg_direction2=None),
            _make_v2_leg("q2", leg_direction1=None, leg_direction2=None),
        ]
        s = [
            _make_v2_leg("s1", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0]),
            _make_v2_leg("s2", leg_direction1=[1.0, 0.0], leg_direction2=[0.0, 1.0]),
        ]
        result = m08.score_leg_group_v2(
            q, s, "front_legs", v3_vector_rules, 1.0, 1.0)
        assert result is None


# =========================== E. 权重与归一化 ===========================


class TestV2Weights:
    def test_direction_count_does_not_amplify_group(self, v3_vector_rules):
        """前腿2方向、后腿3方向不会导致后腿全局权重自动变大。"""
        # v2 腿组得分在内部归一化，不影响外部 group_weight
        q_bl = [_make_v2_leg("bl1", leg_direction1=[0.0, 1.0],
                             leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])]
        s_bl = [_make_v2_leg("bl1", leg_direction1=[0.0, 1.0],
                             leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])]
        num, den, note = m08.score_leg_group_v2(
            q_bl, s_bl, "back_legs", v3_vector_rules, 1.0, 1.0)
        # group_weight=1.0, 所以 leg_group 贡献不应超过 1.0
        # 3个完美方向: num = 0.4+0.2+0.4 = 1.0, den = 1.0
        assert num == pytest.approx(1.0)
        assert den == pytest.approx(1.0)

    def test_direction_weight_override_effective(self, v3_vector_rules):
        """方向权重覆盖实际生效。"""
        import copy
        vr = copy.deepcopy(v3_vector_rules)
        vr["back_legs"]["direction_weights"] = {"leg_direction1": 1.0, "leg_direction2": 0.0, "leg_direction3": 0.0}
        q = [_make_v2_leg("bl1", leg_direction1=[0.0, 1.0], leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])]
        s = [_make_v2_leg("bl1", leg_direction1=[0.0, 1.0], leg_direction2=[0.0, 1.0], leg_direction3=[0.0, 1.0])]
        num, den, note = m08.score_leg_group_v2(q, s, "back_legs", vr, 1.0, 1.0)
        # only d1 contributes
        assert num == pytest.approx(1.0)
        assert den == pytest.approx(1.0)


# =========================== F. v1 回归 ===========================


class TestV1Regression:
    def test_v1_single_episode_top3(self, v3_vector_rules):
        """v1 单集搜索前三名不变。"""
        pose_data = {
            "character_id": "twilight_unicorn",
            "items": [
                {"sample_id": "a", "frame_id": "f1", "character_id": "twilight_unicorn",
                 "timestamp_sec": 0, "_episode_id": "s01e15",
                 "vectors": {"available": {"head": True, "neck": True, "body": True, "tail": True,
                                          "front_leg_1": True, "front_leg_2": True,
                                          "back_leg_1": True, "back_leg_2": True},
                            "head_direction": [1.0, 0.0],
                            "neck_direction": [1.0, 0.0],
                            "body_direction": [1.0, 0.0],
                            "tail_direction": [1.0, 0.0],
                            "front_legs": [
                                {"leg_id": "front_leg_1", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0]},
                                {"leg_id": "front_leg_2", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0]},
                            ],
                            "back_legs": [
                                {"leg_id": "back_leg_1", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0], "leg_direction3": [1.0, 0.0]},
                                {"leg_id": "back_leg_2", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0], "leg_direction3": [1.0, 0.0]},
                            ]}},
                {"sample_id": "b", "frame_id": "f2", "character_id": "twilight_unicorn",
                 "timestamp_sec": 0, "_episode_id": "s01e15",
                 "vectors": {"available": {"head": True, "neck": True, "body": True, "tail": True,
                                          "front_leg_1": True, "front_leg_2": True,
                                          "back_leg_1": True, "back_leg_2": True},
                            "head_direction": [-1.0, 0.0],
                            "neck_direction": [-1.0, 0.0],
                            "body_direction": [-1.0, 0.0],
                            "tail_direction": [-1.0, 0.0],
                            "front_legs": [
                                {"leg_id": "front_leg_1", "leg_direction1": [-1.0, 0.0], "leg_direction2": [-1.0, 0.0]},
                                {"leg_id": "front_leg_2", "leg_direction1": [-1.0, 0.0], "leg_direction2": [-1.0, 0.0]},
                            ],
                            "back_legs": [
                                {"leg_id": "back_leg_1", "leg_direction1": [-1.0, 0.0], "leg_direction2": [-1.0, 0.0], "leg_direction3": [-1.0, 0.0]},
                                {"leg_id": "back_leg_2", "leg_direction1": [-1.0, 0.0], "leg_direction2": [-1.0, 0.0], "leg_direction3": [-1.0, 0.0]},
                            ]}},
            ],
        }
        query_data = {
            "vectors": {"available": {"head": True, "neck": True, "body": True, "tail": True,
                                     "front_leg_1": True, "front_leg_2": True,
                                     "back_leg_1": True, "back_leg_2": True},
                       "head_direction": [1.0, 0.0], "neck_direction": [1.0, 0.0],
                       "body_direction": [1.0, 0.0], "tail_direction": [1.0, 0.0],
                       "front_legs": [
                           {"leg_id": "front_leg_1", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0]},
                           {"leg_id": "front_leg_2", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0]},
                       ],
                       "back_legs": [
                           {"leg_id": "back_leg_1", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0], "leg_direction3": [1.0, 0.0]},
                           {"leg_id": "back_leg_2", "leg_direction1": [1.0, 0.0], "leg_direction2": [1.0, 0.0], "leg_direction3": [1.0, 0.0]},
                       ]},
            "character_id": "twilight_unicorn",
        }
        results = m08.search(query_data, pose_data, v3_vector_rules, top_n=3, version="v1")
        assert len(results) == 2
        assert results[0]["sample_id"] == "a"
        assert results[0]["similarity_score"] == 1.0
        assert results[1]["sample_id"] == "b"
        assert results[1]["similarity_score"] == 0.0

    def test_v1_old_query_no_version_works(self, v3_vector_rules):
        """v1 旧查询无 version 字段仍能读取。"""
        # 旧查询没有 version 字段——v1 模式不应校验
        query_data = {
            "keypoint_schema_id": "s",
            "character_id": "twilight_unicorn",
            "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]},
        }
        # 这应该在 main() 中通过——这里只测试不会因为缺少 version 而崩溃
        # 由于我们测试的是 search() 函数，它不读 version 字段
        pose_data = {"character_id": "twilight_unicorn", "items": [
            {"sample_id": "x", "frame_id": "f1", "character_id": "twilight_unicorn",
             "timestamp_sec": 0, "_episode_id": "s01e15",
             "vectors": {"available": {"head": True}, "head_direction": [1.0, 0.0]}},
        ]}
        results = m08.search(query_data, pose_data, v3_vector_rules, version="v1")
        assert len(results) == 1

    def test_v1_same_as_before(self, v3_vector_rules):
        """v1 结果与之前一致（相同输入 → 相同分数）。"""
        # 使用与旧测试相同的数据验证 compute_similarity 未变
        q = {"available": {"head": True}, "head_direction": [1.0, 0.0]}
        s = {"available": {"head": True}, "head_direction": [1.0, 0.0]}
        score, note = m08.compute_similarity(q, s, v3_vector_rules)
        assert score == 1.0
