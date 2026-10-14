"""M09 测试 conftest。"""
import csv
import os
import tempfile
import pytest


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


def make_csv(path, rows, fields=None):
    """创建测试 CSV。"""
    if fields is None:
        fields = [
            "rank", "sample_id", "frame_id", "episode_id", "season", "episode",
            "character_id", "timestamp_sec", "timestamp_frame", "timestamp_text",
            "similarity_score", "frame_path", "crop_path", "match_note",
        ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


@pytest.fixture
def sample_csv(temp_dir):
    p = os.path.join(temp_dir, "top10_results.csv")
    rows = [
        {"rank": "1", "sample_id": "s01e15_t000003_001", "frame_id": "f1",
         "episode_id": "s01e15", "season": "1", "episode": "15",
         "character_id": "twilight_unicorn", "timestamp_sec": "3",
         "timestamp_frame": "0", "timestamp_text": "00:00:03",
         "similarity_score": "0.95", "frame_path": "frames/s01/e15/f1.png",
         "crop_path": "crops/twilight_unicorn/s01/e15/c1.png",
         "match_note": "test & <note>"},
        {"rank": "2", "sample_id": "s01e15_t000026_001", "frame_id": "f2",
         "episode_id": "s01e15", "season": "1", "episode": "15",
         "character_id": "twilight_unicorn", "timestamp_sec": "26",
         "timestamp_frame": "0", "timestamp_text": "00:00:26",
         "similarity_score": "0.80", "frame_path": "",
         "crop_path": "", "match_note": ""},
    ]
    make_csv(p, rows)
    return p
