"""
M06 测试 conftest — 共享 fixtures。
"""

import json
import math
import os
import sys
import tempfile
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_M06 = os.path.join(_PROJECT_ROOT, "scripts", "m06")
_COMMON = os.path.join(_PROJECT_ROOT, "scripts", "common")
if _SCRIPTS_M06 not in sys.path:
    sys.path.insert(0, _SCRIPTS_M06)
if _COMMON not in sys.path:
    sys.path.insert(0, _COMMON)

import generate_pose_vectors as m06
import pose_vector_utils as pvu


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def v3_schema():
    """简化的 v3 schema 用于测试。"""
    return {
        "vector_rules": {
            "head_direction": {"from": "head.head_center", "to": "head.head_front"},
            "neck_direction": {"from": "body.body_1", "to": "head.neck"},
            "body_direction": {"from": "body.body_1", "to": "body.body_2"},
            "tail_direction": {"from": "tail.tail_base", "to": "tail.tail_end"},
            "front_legs": {
                "source_group": "front_legs",
                "direction1": {"name": "leg_direction1", "from": "current_leg.base", "to": "current_leg.mid"},
                "direction2": {"name": "leg_direction2", "from": "current_leg.mid", "to": "current_leg.end"},
                "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5},
            },
            "back_legs": {
                "source_group": "back_legs",
                "direction1": {"name": "leg_direction1", "from": "current_leg.base", "to": "current_leg.knee"},
                "direction2": {"name": "leg_direction2", "from": "current_leg.knee", "to": "current_leg.mid"},
                "direction3": {"name": "leg_direction3", "from": "current_leg.mid", "to": "current_leg.end"},
                "direction_weights": {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4},
            },
        }
    }


@pytest.fixture
def v1_schema():
    """简化的 v1 schema（使用 anchor_keypoint）。"""
    return {
        "vector_rules": {
            "head_direction": {"from": "head.head_center", "to": "head.head_front"},
            "neck_direction": {"from": "body.body_1", "to": "head.neck"},
            "body_direction": {"from": "body.body_1", "to": "body.body_2"},
            "tail_direction": {"from": "tail.tail_base", "to": "tail.tail_end"},
            "front_legs": {
                "source_group": "front_legs",
                "anchor_keypoint": "body.body_1",
                "direction1": {"name": "leg_direction1", "from": "anchor_keypoint", "to": "current_leg.mid"},
                "direction2": {"name": "leg_direction2", "from": "current_leg.mid", "to": "current_leg.end"},
                "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5},
            },
            "back_legs": {
                "source_group": "back_legs",
                "anchor_keypoint": "body.body_2",
                "direction1": {"name": "leg_direction1", "from": "anchor_keypoint", "to": "current_leg.mid"},
                "direction2": {"name": "leg_direction2", "from": "current_leg.mid", "to": "current_leg.end"},
                "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5},
            },
        }
    }


@pytest.fixture
def sample_keypoints_v3():
    """完整的 v3 样本关键点（所有点都有值）。"""
    return {
        "head": {"head_center": [100, 50], "head_front": [120, 45], "neck": [90, 80]},
        "body": {"body_1": [80, 100], "body_2": [200, 105]},
        "front_legs": [
            {"leg_id": "front_leg_1", "base": [70, 110], "mid": [65, 160], "end": [60, 210]},
            {"leg_id": "front_leg_2", "base": [90, 115], "mid": [85, 165], "end": [80, 215]},
        ],
        "back_legs": [
            {"leg_id": "back_leg_1", "base": [190, 115], "knee": [195, 140], "mid": [200, 170], "end": [205, 220]},
            {"leg_id": "back_leg_2", "base": [210, 120], "knee": [215, 145], "mid": [220, 175], "end": [225, 225]},
        ],
        "tail": {"tail_base": [210, 100], "tail_end": [280, 85]},
    }


@pytest.fixture
def sample_keypoints_v1():
    """v1 样本关键点（腿只有 mid/end）。"""
    return {
        "head": {"head_center": [100, 50], "head_front": [120, 45], "neck": [90, 80]},
        "body": {"body_1": [80, 100], "body_2": [200, 105]},
        "front_legs": [
            {"leg_id": "front_leg_1", "mid": [65, 160], "end": [60, 210]},
            {"leg_id": "front_leg_2", "mid": [85, 165], "end": [80, 215]},
        ],
        "back_legs": [
            {"leg_id": "back_leg_1", "mid": [200, 170], "end": [205, 220]},
            {"leg_id": "back_leg_2", "mid": [220, 175], "end": [225, 225]},
        ],
        "tail": {"tail_base": [210, 100], "tail_end": [280, 85]},
    }
