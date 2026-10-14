"""
M03 测试 conftest — 共享 fixtures。
"""

import os
import sys
import tempfile
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_M03 = os.path.join(_PROJECT_ROOT, "scripts", "m03")
if _SCRIPTS_M03 not in sys.path:
    sys.path.insert(0, _SCRIPTS_M03)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def sample_candidate_frames():
    """模拟 M02 输出的候选帧列表。"""
    return [
        {
            "frame_id": "s01e15_t000003_f000",
            "episode_id": "s01e15", "season": "1", "episode": "15",
            "character_id": "twilight_unicorn",
            "image_path": "frames/s01/e15/s01e15_t000003_f000.png",
            "timestamp_sec": "3", "timestamp_frame": "0", "timestamp_text": "00:00:03",
            "usable": "1", "reason": "", "note": "",
        },
        {
            "frame_id": "s01e15_t000026_f000",
            "episode_id": "s01e15", "season": "1", "episode": "15",
            "character_id": "twilight_unicorn",
            "image_path": "frames/s01/e15/s01e15_t000026_f000.png",
            "timestamp_sec": "26", "timestamp_frame": "0", "timestamp_text": "00:00:26",
            "usable": "1", "reason": "", "note": "",
        },
        {
            "frame_id": "s01e15_t000331_f000",
            "episode_id": "s01e15", "season": "1", "episode": "15",
            "character_id": "twilight_unicorn",
            "image_path": "frames/s01/e15/s01e15_t000331_f000.png",
            "timestamp_sec": "331", "timestamp_frame": "0", "timestamp_text": "00:05:31",
            "usable": "1", "reason": "", "note": "",
        },
    ]


@pytest.fixture
def sample_bboxes():
    """模拟 bbox 内存数据。"""
    return {
        "s01e15_t000003_f000": {
            "x1": 420, "y1": 180, "x2": 790, "y2": 620,
            "visibility": "clear", "note": "完整清晰",
        },
        "s01e15_t000026_f000": {
            "x1": 500, "y1": 200, "x2": 900, "y2": 700,
            "visibility": "partial", "note": "",
        },
        # frame 331 未标注
    }
