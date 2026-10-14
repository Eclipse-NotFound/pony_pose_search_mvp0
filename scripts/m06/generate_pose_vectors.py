#!/usr/bin/env python3
"""M06 shared-library command. Pure legacy math below is retained for migration and historical regression only. Run --help for current arguments."""

import argparse
import json
import math
import os
import sys

# 共享纯函数
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
from pose_vector_utils import (
    unit_direction,
    resolve_keypoint,
    compute_simple_vectors,
    compute_leg_vectors,
    generate_vectors_for_sample,
    content_fingerprint,
)


# ---------------------------------------------------------------------------
# 路径构建
# ---------------------------------------------------------------------------

def _sc(episode_id):
    return episode_id[:3]


def build_keypoints_path(project_root, character_id, episode_id):
    return os.path.join(
        project_root, "keypoints", character_id, _sc(episode_id),
        f"keypoints_{character_id}_{episode_id}.json",
    )


def build_schemas_path(project_root):
    return os.path.join(project_root, "data", "meta", "keypoint_schemas.json")


def build_output_path(project_root, character_id, episode_id, version="v1"):
    """构建姿态向量输出路径。v1 和 v2 使用不同文件名。"""
    base = os.path.join(
        project_root, "poses", character_id, _sc(episode_id),
        f"pose_vectors_{character_id}_{episode_id}",
    )
    if version == "v2":
        return base + "_v2.json"
    return base + ".json"


# ---------------------------------------------------------------------------
# 批量处理
# ---------------------------------------------------------------------------

def generate_pose_vectors(keypoints_data, schemas_data, version="v1"):
    """处理整个 keypoints JSON，返回 pose_vectors JSON 数据。"""
    schema_id = keypoints_data.get("keypoint_schema_id", "")
    if not schema_id:
        raise ValueError("keypoints JSON missing keypoint_schema_id")

    schemas = schemas_data.get("schemas", {})
    if schema_id not in schemas:
        raise ValueError(f"Schema '{schema_id}' not found in keypoint_schemas.json")

    schema = schemas[schema_id]
    vector_rules = schema.get("vector_rules", {})
    if not vector_rules:
        raise ValueError(f"Schema '{schema_id}' has no vector_rules")

    items = []
    for sample in keypoints_data.get("items", []):
        sid = sample.get("sample_id", "")
        kps = sample.get("keypoints", {})

        vec_result = generate_vectors_for_sample(kps, vector_rules, version=version)

        items.append({
            "sample_id": sid,
            "frame_id": sample.get("frame_id", ""),
            "episode_id": sample.get("episode_id", ""),
            "character_id": sample.get("character_id", ""),
            "timestamp_sec": sample.get("timestamp_sec", 0),
            "vectors": vec_result["vectors"],
            "missing_points": vec_result["missing_points"],
        })

    version_str = f"mvp0_pose_vectors_{version}"
    return {
        "project": "pony_pose_search_mvp0",
        "version": version_str,
        "character_id": keypoints_data.get("character_id", ""),
        "episode_id": keypoints_data.get("episode_id", ""),
        "keypoint_schema_id": schema_id,
        "derivation": {
            "generator_revision": "2026-10-11",
            "keypoints_content_sha256": content_fingerprint(keypoints_data),
            "rules_content_sha256": content_fingerprint(vector_rules),
        },
        "items": items,
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]/'common'))
    from workflow.cli import run_module
    return run_module('M06')

if __name__=='__main__':main()
