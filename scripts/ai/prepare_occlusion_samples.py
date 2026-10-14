#!/usr/bin/env python3
"""M2 遮挡标注样本准备 — prepare_occlusion_samples.py

从现有 crops + AI 建议帧按 bbox 裁切，生成遮挡分类器的标注样本集。

样本来源：
1. 现有正式 crops（M04 生成，e15/e24 共 42 张）——全部纳入；
2. 建议帧补充采样：按质量分分层（score<0.8 的低质量帧优先全覆盖，
   高质量帧均匀采样补足到目标数量），覆盖不同姿态/镜头/远近。

输出（dataset/ 为派生数据，已被 gitignore，可再生成）：
  dataset/occlusion_samples/{sample_id}.png   裁切图
  dataset/occlusion_samples/manifest.csv      样本清单（供标注工具使用）

Usage:
    python scripts/ai/prepare_occlusion_samples.py --project-root . \
        --characters twilight_unicorn --episodes s01e15 s01e24 \
        --target 200 --seed 42
"""

import argparse
import csv
import json
import os
import random
import sys

from PIL import Image

_CDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_CDIR, "..", "common"))
import quality_utils

MANIFEST_FIELDS = ["sample_id", "frame_id", "source",
                   "bbox_x", "bbox_y", "bbox_w", "bbox_h",
                   "crop_path", "image_path"]

OUT_ROOT = os.path.join("dataset", "occlusion_samples")
MANIFEST_NAME = "manifest.csv"

# 低质量分阈值（分层采样：低于此值全覆盖）
LOW_SCORE = 0.8
# 裁切最小边长（过小的样本跳过，无法判断）
MIN_CROP_SIDE = 24


def _load_frames_index(project_root, episode_id):
    """M01 frames_index → {frame_id: row}。"""
    sc, ec = episode_id[:3], episode_id[3:]
    path = os.path.join(project_root, "frames", sc, ec,
                        f"frames_index_{episode_id}.csv")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return {r["frame_id"]: r for r in csv.DictReader(f)}


def _load_bbox_suggestions(project_root, character_id, episode_id):
    """bbox 建议 → {frame_id: suggestion}；无文件返回 {}。"""
    path = os.path.join(project_root, "suggestions", character_id, episode_id,
                        "bbox_suggestions.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {s.get("frame_id"): s for s in data.get("suggestions", [])}


def _existing_crops(project_root, character_id, episode_id):
    """正式 crops index → [(sample_id, frame_id, crop_path)]。"""
    sc, ec = episode_id[:3], episode_id[3:]
    d = os.path.join(project_root, "crops", character_id, sc, ec)
    path = os.path.join(d, f"crops_index_{character_id}_{episode_id}.csv")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [(r.get("sample_id", ""), r.get("frame_id", ""),
                 r.get("crop_path", "")) for r in csv.DictReader(f)]


def _extract_crop(project_root, out_dir, sample_id, frame_row, bbox):
    """按 bbox（帧坐标）裁切帧图 → dataset/occlusion_samples/{sample_id}.png。

    返回相对 crop_path；失败（帧缺失/过小）返回 None。
    """
    image_path = os.path.join(project_root, frame_row["image_path"])
    if not os.path.exists(image_path):
        return None
    with Image.open(image_path) as im:
        w, h = im.size
        x1 = max(0, int(bbox.get("x", 0)))
        y1 = max(0, int(bbox.get("y", 0)))
        x2 = min(w, int(bbox.get("x", 0) + bbox.get("width", 0)))
        y2 = min(h, int(bbox.get("y", 0) + bbox.get("height", 0)))
    if x2 - x1 < MIN_CROP_SIDE or y2 - y1 < MIN_CROP_SIDE:
        return None
    with Image.open(image_path) as im:
        crop = im.crop((x1, y1, x2, y2))
    os.makedirs(out_dir, exist_ok=True)
    rel = os.path.join("dataset", "occlusion_samples", f"{sample_id}.png")
    crop.save(os.path.join(project_root, rel))
    return rel


def _existing_samples(out_dir):
    """已生成的 sample_id 集合（幂等重跑不重复裁切）。"""
    if not os.path.isdir(out_dir):
        return set()
    return {os.path.splitext(f)[0] for f in os.listdir(out_dir)
            if f.endswith(".png")}


def prepare_samples(project_root, characters, episodes, target=200,
                    seed=42, low_score=LOW_SCORE):
    """生成标注样本清单。返回 manifest 行列表。"""
    out_dir = os.path.join(project_root, OUT_ROOT)
    done = _existing_samples(out_dir)
    manifest = []

    # 1. 现有正式 crops 全部纳入（裁切图已存在，直接登记）
    for cid in characters:
        for eid in episodes:
            sc, ec = eid[:3], eid[3:]
            for sample_id, frame_id, crop_path in _existing_crops(
                    project_root, cid, eid):
                if not crop_path or not os.path.exists(
                        os.path.join(project_root, crop_path)):
                    continue
                manifest.append({
                    "sample_id": sample_id, "frame_id": frame_id,
                    "source": "official_crop",
                    "bbox_x": "", "bbox_y": "", "bbox_w": "", "bbox_h": "",
                    "crop_path": crop_path,
                    "image_path": "",
                })

    # 2. 建议帧补充采样（按质量分分层）
    pending = []
    for cid in characters:
        for eid in episodes:
            suggs = _load_bbox_suggestions(project_root, cid, eid)
            frames = _load_frames_index(project_root, eid)
            for fid, s in suggs.items():
                if fid in frames:
                    q = s.get("quality") or {}
                    pending.append((q.get("score", 1.0), fid, s["bbox"],
                                    frames[fid], eid))

    need = max(0, target - len(manifest))
    if need > 0 and pending:
        rng = random.Random(seed)
        rng.shuffle(pending)
        low = [p for p in pending if p[0] < low_score]
        high = [p for p in pending if p[0] >= low_score]
        # 低质量帧全覆盖优先，其余均匀采样
        chosen = low[:need]
        if len(chosen) < need:
            chosen += high[: need - len(chosen)]
        for score, fid, bbox, frame_row, eid in chosen:
            sample_id = fid
            if sample_id in done:
                continue
            crop_path = _extract_crop(project_root, out_dir, sample_id,
                                      frame_row, bbox)
            if crop_path is None:
                continue
            manifest.append({
                "sample_id": sample_id, "frame_id": fid,
                "source": "ai_suggestion",
                "bbox_x": int(bbox.get("x", 0)),
                "bbox_y": int(bbox.get("y", 0)),
                "bbox_w": int(bbox.get("width", 0)),
                "bbox_h": int(bbox.get("height", 0)),
                "crop_path": crop_path,
                "image_path": frame_row.get("image_path", ""),
            })

    # 写 manifest（幂等：与已有合并去重）
    manifest_path = os.path.join(out_dir, MANIFEST_NAME)
    existing = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[r["sample_id"]] = r
    for row in manifest:
        existing.setdefault(row["sample_id"], row)
    merged = list(existing.values())
    os.makedirs(out_dir, exist_ok=True)
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(merged)
    return merged


def main():
    parser = argparse.ArgumentParser(description="准备遮挡标注样本")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--characters", nargs="+", default=["twilight_unicorn"])
    parser.add_argument("--episodes", nargs="+", default=["s01e15", "s01e24"])
    parser.add_argument("--target", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    manifest = prepare_samples(
        os.path.abspath(args.project_root), args.characters,
        args.episodes, target=args.target, seed=args.seed)
    src_counts = {}
    for r in manifest:
        src_counts[r["source"]] = src_counts.get(r["source"], 0) + 1
    print(f"样本总数: {len(manifest)}")
    print(f"来源分布: {src_counts}")
    print(f"清单: {os.path.join(OUT_ROOT, MANIFEST_NAME)}")


if __name__ == "__main__":
    main()
