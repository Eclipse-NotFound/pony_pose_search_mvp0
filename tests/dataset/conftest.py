"""
MVP2 dataset 测试 conftest — 共享 fixtures。
"""

import csv
import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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

EXPECTED_KP_ORDER = [
    "head.head_center", "head.head_front", "body.body_1",
    "front_legs.front_leg_1.mid", "front_legs.front_leg_1.end",
    "front_legs.front_leg_2.mid", "front_legs.front_leg_2.end",
    "back_legs.back_leg_1.mid", "back_legs.back_leg_2.mid",
    "tail.tail_base",
]


@pytest.fixture
def temp_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        yield td


def _make_keypoints(**vals):
    """按 mini schema 构造关键点结构。vals: path -> [x, y]"""
    kp = {
        "head": {"head_center": None, "head_front": None},
        "body": {"body_1": None},
        "front_legs": [{"leg_id": "front_leg_1", "mid": None, "end": None},
                       {"leg_id": "front_leg_2", "mid": None, "end": None}],
        "back_legs": [{"leg_id": "back_leg_1", "mid": None},
                      {"leg_id": "back_leg_2", "mid": None}],
        "tail": {"tail_base": None},
    }
    for path, xy in vals.items():
        parts = path.split(".")
        if len(parts) == 2:
            kp[parts[0]][parts[1]] = xy
        else:
            for leg in kp[parts[0]]:
                if leg["leg_id"] == parts[1]:
                    leg[parts[2]] = xy
    return kp


@pytest.fixture
def mini_project(temp_dir):
    """2 帧小项目：meta + 帧图片 + bboxes + crops + keypoints。

    帧图 200x150；
    样本 0 bbox (10,20,190,130)，全部 10 个关键点可用；
    样本 1 bbox (20,30,180,140)，仅 head_center / tail_base / fl1.mid 可用。
    """
    pr = temp_dir
    cid, eid = "twilight_unicorn", "s01e15"

    from PIL import Image
    d = os.path.join(pr, "data", "meta")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "characters.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "characters_v1",
                   "characters": {cid: {"species_type": "unicorn"}}}, f)
    with open(os.path.join(d, "anatomy_templates.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "anatomy_templates_v1", "anatomy": {
            "unicorn": {"default_keypoint_schema_id": MINI_SCHEMA_ID}}}, f)
    with open(os.path.join(d, "keypoint_schemas.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "keypoint_schemas_v1",
                   "schemas": {MINI_SCHEMA_ID: MINI_SCHEMA}}, f)

    frames_dir = os.path.join(pr, "frames", "s01", "e15")
    os.makedirs(frames_dir, exist_ok=True)
    for i, color in ((0, (200, 100, 50)), (1, (50, 100, 200))):
        Image.new("RGB", (200, 150), color).save(
            os.path.join(frames_dir, f"s01e15_t00000{i}_f000.png"))

    d = os.path.join(pr, "bboxes", cid, "s01")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"bboxes_{cid}_{eid}.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "frame_id", "image_path", "x1", "y1",
                    "x2", "y2", "visibility", "note"])
        w.writerow([f"{eid}_t000000_f000_{cid}_001", f"{eid}_t000000_f000",
                    "frames/s01/e15/s01e15_t000000_f000.png", 10, 20, 190, 130,
                    "clear", ""])
        w.writerow([f"{eid}_t000001_f000_{cid}_001", f"{eid}_t000001_f000",
                    "frames/s01/e15/s01e15_t000001_f000.png", 20, 30, 180, 140,
                    "clear", ""])

    d = os.path.join(pr, "crops", cid, "s01", "e15")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"crops_index_{cid}_{eid}.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "frame_id", "frame_path", "crop_path",
                    "x1", "y1", "x2", "y2"])
        w.writerow([f"{eid}_t000000_f000_{cid}_001", f"{eid}_t000000_f000",
                    "frames/s01/e15/s01e15_t000000_f000.png",
                    "crops/x.png", 10, 20, 190, 130])
        w.writerow([f"{eid}_t000001_f000_{cid}_001", f"{eid}_t000001_f000",
                    "frames/s01/e15/s01e15_t000001_f000.png",
                    "crops/y.png", 20, 30, 180, 140])

    items = [
        {"sample_id": f"{eid}_t000000_f000_{cid}_001",
         "frame_id": f"{eid}_t000000_f000",
         "frame_path": "frames/s01/e15/s01e15_t000000_f000.png",
         "keypoints": _make_keypoints(
             **{"head.head_center": [90, 50], "head.head_front": [110, 40],
                "body.body_1": [80, 90],
                "front_legs.front_leg_1.mid": [95, 95],
                "front_legs.front_leg_1.end": [100, 105],
                "front_legs.front_leg_2.mid": [70, 97],
                "front_legs.front_leg_2.end": [60, 103],
                "back_legs.back_leg_1.mid": [30, 95],
                "back_legs.back_leg_2.mid": [15, 98],
                "tail.tail_base": [20, 70]}),
         "note": ""},
        {"sample_id": f"{eid}_t000001_f000_{cid}_001",
         "frame_id": f"{eid}_t000001_f000",
         "frame_path": "frames/s01/e15/s01e15_t000001_f000.png",
         "keypoints": _make_keypoints(
             **{"head.head_center": [80, 60],
                "front_legs.front_leg_1.mid": [90, 100],
                "tail.tail_base": [30, 80]}),
         "note": ""},
    ]
    d = os.path.join(pr, "keypoints", cid, "s01")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"keypoints_{cid}_{eid}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"version": "mvp0_keypoints_v1",
                   "keypoint_schema_id": MINI_SCHEMA_ID,
                   "items": items}, f)

    return pr
