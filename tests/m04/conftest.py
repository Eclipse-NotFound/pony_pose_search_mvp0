"""
M04 测试 conftest — 共享 fixtures。
"""

import os
import subprocess
import sys
import tempfile
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_M04 = os.path.join(_PROJECT_ROOT, "scripts", "m04")
if _SCRIPTS_M04 not in sys.path:
    sys.path.insert(0, _SCRIPTS_M04)


def _generate_test_frame(output_path: str, width: int = 320, height: int = 240):
    """生成纯色测试帧图片。"""
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    img.save(output_path, "PNG")


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def mock_project(temp_dir):
    """
    创建模拟项目结构，包含测试帧图片和 bbox CSV。
    返回 (project_root, character_id, episode_id, bbox_csv_path)。
    """
    project_root = temp_dir
    character_id = "twilight_unicorn"
    episode_id = "s01e15"

    # 创建 frames 目录和测试帧图片
    frames_dir = os.path.join(project_root, "frames", "s01", "e15")
    os.makedirs(frames_dir, exist_ok=True)

    frame_files = {
        "s01e15_t000003_f000.png": (320, 240),
        "s01e15_t000026_f000.png": (320, 240),
        "s01e15_t000331_f000.png": (320, 240),
    }
    for fname, size in frame_files.items():
        _generate_test_frame(os.path.join(frames_dir, fname), *size)

    # 创建 bbox CSV
    bboxes_dir = os.path.join(project_root, "bboxes", character_id, "s01")
    os.makedirs(bboxes_dir, exist_ok=True)
    bbox_csv_path = os.path.join(bboxes_dir, f"bboxes_{character_id}_{episode_id}.csv")

    import csv
    fields = [
        "sample_id", "frame_id", "episode_id", "season", "episode",
        "character_id", "image_path", "timestamp_sec", "timestamp_frame",
        "timestamp_text", "x1", "y1", "x2", "y2", "visibility", "note",
    ]
    rows = [
        ["s01e15_t000003_f000_twilight_unicorn_001",
         "s01e15_t000003_f000", "s01e15", "1", "15",
         "twilight_unicorn", "frames/s01/e15/s01e15_t000003_f000.png",
         "3", "0", "00:00:03", "50", "40", "200", "180", "clear", ""],
        ["s01e15_t000026_f000_twilight_unicorn_001",
         "s01e15_t000026_f000", "s01e15", "1", "15",
         "twilight_unicorn", "frames/s01/e15/s01e15_t000026_f000.png",
         "26", "0", "00:00:26", "80", "60", "250", "200", "partial", ""],
        ["s01e15_t000331_f000_twilight_unicorn_001",
         "s01e15_t000331_f000", "s01e15", "1", "15",
         "twilight_unicorn", "frames/s01/e15/s01e15_t000331_f000.png",
         "331", "0", "00:05:31", "100", "50", "300", "220", "clear",
         "完整清晰"],
    ]
    with open(bbox_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        writer.writerows(rows)

    return project_root, character_id, episode_id, bbox_csv_path
