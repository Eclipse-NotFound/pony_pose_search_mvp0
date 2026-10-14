"""
M05 测试 conftest — 共享 fixtures。
"""

import json
import os
import sys
import tempfile
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_M05 = os.path.join(_PROJECT_ROOT, "scripts", "m05")
if _SCRIPTS_M05 not in sys.path:
    sys.path.insert(0, _SCRIPTS_M05)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@pytest.fixture
def mock_project(temp_dir):
    """创建包含 Meta 文件和 crops index 的模拟项目。"""
    project_root = temp_dir

    # Meta files (same as real ones)
    _write_json(os.path.join(project_root, "data/meta/characters.json"), {
        "version": "characters_v1",
        "characters": {
            "twilight_unicorn": {
                "display_name_zh": "暮光闪闪（独角兽状态）",
                "display_name_en": "Twilight Sparkle Unicorn",
                "species_type": "unicorn",
            }
        }
    })
    _write_json(os.path.join(project_root, "data/meta/anatomy_templates.json"), {
        "version": "anatomy_templates_v1",
        "anatomy": {
            "unicorn": {
                "has_wings": False, "has_tail": True, "leg_count": 4,
                "wing_count": 0,
                "default_keypoint_schema_id": "pony_unicorn_no_wings_mvp0_v3",
            }
        }
    })
    _write_json(os.path.join(project_root, "data/meta/keypoint_schemas.json"), {
        "version": "keypoint_schemas_v1",
        "schemas": {
            "pony_unicorn_no_wings_mvp0_v1": {
                "keypoint_rules": {
                    "head": ["head_center", "head_front", "neck"],
                    "body": ["body_1", "body_2"],
                    "front_legs": ["front_leg_1", "front_leg_2"],
                    "back_legs": ["back_leg_1", "back_leg_2"],
                    "tail": ["tail_base", "tail_end"],
                },
                "leg_keypoint_rules": {
                    "front_legs": ["mid", "end"],
                    "back_legs": ["mid", "end"]
                },
                "vector_rules": {
                    "front_legs": {
                        "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5}
                    },
                    "back_legs": {
                        "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5}
                    }
                }
            },
            "pony_unicorn_no_wings_mvp0_v2": {
                "keypoint_rules": {
                    "head": ["head_center", "head_front", "neck"],
                    "body": ["body_1", "body_2"],
                    "front_legs": ["front_leg_1", "front_leg_2"],
                    "back_legs": ["back_leg_1", "back_leg_2"],
                    "tail": ["tail_base", "tail_end"],
                },
                "leg_keypoint_rules": {
                    "front_legs": ["base", "mid", "end"],
                    "back_legs": ["base", "mid", "end"]
                },
                "vector_rules": {
                    "front_legs": {
                        "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5}
                    },
                    "back_legs": {
                        "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5}
                    }
                }
            },
            "pony_unicorn_no_wings_mvp0_v3": {
                "keypoint_rules": {
                    "head": ["head_center", "head_front", "neck"],
                    "body": ["body_1", "body_2"],
                    "front_legs": ["front_leg_1", "front_leg_2"],
                    "back_legs": ["back_leg_1", "back_leg_2"],
                    "tail": ["tail_base", "tail_end"],
                },
                "leg_keypoint_rules": {
                    "front_legs": ["base", "mid", "end"],
                    "back_legs": ["base", "knee", "mid", "end"]
                },
                "vector_rules": {
                    "front_legs": {
                        "direction_weights": {"leg_direction1": 0.5, "leg_direction2": 0.5}
                    },
                    "back_legs": {
                        "direction_weights": {"leg_direction1": 0.4, "leg_direction2": 0.2, "leg_direction3": 0.4}
                    }
                }
            }
        }
    })

    # Create a test crop image (using PIL)
    from PIL import Image
    crops_dir = os.path.join(project_root, "crops/twilight_unicorn/s01/e15")
    os.makedirs(crops_dir, exist_ok=True)
    for i in range(3):
        img = Image.new("RGB", (200, 150), color=(100 + i*50, 150, 200 - i*30))
        fname = f"s01e15_t00000{i}_f000_twilight_unicorn_001.png"
        img.save(os.path.join(crops_dir, fname))

    # Crops index CSV
    import csv
    csv_path = os.path.join(crops_dir, "crops_index_twilight_unicorn_s01e15.csv")
    fields = ["sample_id", "frame_id", "episode_id", "season", "episode",
              "character_id", "timestamp_sec", "timestamp_frame", "timestamp_text",
              "frame_path", "crop_path", "x1", "y1", "x2", "y2"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i in range(3):
            sid = f"s01e15_t00000{i}_f000_twilight_unicorn_001"
            w.writerow({
                "sample_id": sid,
                "frame_id": f"s01e15_t00000{i}_f000",
                "episode_id": "s01e15", "season": "1", "episode": "15",
                "character_id": "twilight_unicorn",
                "timestamp_sec": str(i), "timestamp_frame": "0",
                "timestamp_text": f"00:00:0{i}",
                "frame_path": f"frames/s01/e15/s01e15_t00000{i}_f000.png",
                "crop_path": f"crops/twilight_unicorn/s01/e15/{sid}.png",
                "x1": "10", "y1": "20", "x2": "190", "y2": "130",
            })

    return project_root
