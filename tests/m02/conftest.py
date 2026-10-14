"""
M02 测试 conftest — 共享 fixtures。
"""

import os
import sys
import tempfile
import pytest

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_SCRIPTS_M02 = os.path.join(_PROJECT_ROOT, "scripts", "m02")
if _SCRIPTS_M02 not in sys.path:
    sys.path.insert(0, _SCRIPTS_M02)


@pytest.fixture
def temp_dir():
    """提供临时目录。"""
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def sample_frames():
    """返回一组模拟的 M01 帧记录。"""
    return [
        {
            "frame_id": "s01e15_t000000_f000",
            "episode_id": "s01e15",
            "season": "1",
            "episode": "15",
            "timestamp_sec": "0",
            "timestamp_frame": "0",
            "timestamp_text": "00:00:00",
            "source_frame_index": "0",
            "fps": "23.976",
            "image_path": "frames/s01/e15/s01e15_t000000_f000.png",
        },
        {
            "frame_id": "s01e15_t000001_f000",
            "episode_id": "s01e15",
            "season": "1",
            "episode": "15",
            "timestamp_sec": "1",
            "timestamp_frame": "0",
            "timestamp_text": "00:00:01",
            "source_frame_index": "24",
            "fps": "23.976",
            "image_path": "frames/s01/e15/s01e15_t000001_f000.png",
        },
        {
            "frame_id": "s01e15_t000002_f000",
            "episode_id": "s01e15",
            "season": "1",
            "episode": "15",
            "timestamp_sec": "2",
            "timestamp_frame": "0",
            "timestamp_text": "00:00:02",
            "source_frame_index": "48",
            "fps": "23.976",
            "image_path": "frames/s01/e15/s01e15_t000002_f000.png",
        },
    ]


@pytest.fixture
def sample_judgments():
    """返回一组模拟的判定数据。"""
    return {
        "s01e15_t000000_f000": {
            "usable": 1,
            "reason": "clear_twilight",
            "note": "暮光闪闪清晰可见",
        },
        "s01e15_t000001_f000": {
            "usable": 0,
            "reason": "blurry",
            "note": "模糊不清",
        },
        "s01e15_t000002_f000": {
            "usable": 1,
            "reason": "good_pose",
            "note": "",
        },
    }
