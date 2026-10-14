"""
MVP2 AI 模型接口测试 conftest — 共享 fixtures。
"""

import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts", "ai"))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts", "dataset"))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts", "common"))

MINI_SCHEMA_ID = "mini_schema_v1"
MINI_SCHEMA = {
    "keypoint_rules": {
        "head": ["head_center", "head_front"],
        "body": ["body_1"],
        "front_legs": ["front_leg_1", "front_leg_2"],
        "back_legs": ["back_leg_1", "back_leg_2"],
        "tail": ["tail_base"],
    },
    "leg_keypoint_rules": {
        "front_legs": ["mid", "end"],
        "back_legs": ["mid"],
    },
}


@pytest.fixture
def temp_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        yield td


class _MockBackend:
    """可配置的 mock 模型后端。"""

    def __init__(self):
        self.detections = [{"bbox": (50, 40, 150, 120), "confidence": 0.9}]
        self.kp_prediction = None
        self.class_probs = {"partial": 0.9, "not_partial": 0.1}

    def detect_bboxes(self, image, settings):
        return self.detections

    def predict_keypoints(self, image, bbox, settings):
        return self.kp_prediction

    def predict_classify(self, image, settings):
        return dict(self.class_probs)


@pytest.fixture
def mock_backend():
    """注册 .mock 后端（测试结束自动卸载）。返回可配置的 stub 对象。"""
    import model_interface as ai
    backend = _MockBackend()
    ai.register_backend(".mock", lambda path: backend)
    yield backend
    ai._BACKENDS.pop(".mock", None)


@pytest.fixture
def mock_model_path(tmp_path):
    """返回一个存在的 .mock 模型文件路径。"""
    p = tmp_path / "model.mock"
    p.write_bytes(b"mock")
    return str(p)


@pytest.fixture
def mini_schema():
    return MINI_SCHEMA
