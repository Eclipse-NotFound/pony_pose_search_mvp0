#!/usr/bin/env python3
"""M3 遮挡分类器数据集构建 — build_occlusion_datasets.py

把人工遮挡标注（annotations/occlusion_labels.json）转换为两个
YOLOv8-cls 数据集（ultralytics 目录布局）：

  dataset/twilight_occlusion_partial/{train,val}/partial|not_partial
  dataset/twilight_occlusion_occluded/{train,val}/occluded|not_occluded

标注键兼容两种来源（M10 审核窗口按 frame_id、独立标注工具按 sample_id，
sample_id 形如 "{frame_id}_twilight_unicorn_001"，自动归一化为 frame_id）。
crop 优先取 prepare 阶段已裁切的样本（manifest），缺失时按建议 bbox
现裁帧图。划分按标签分层（80/20，固定 seed），保证两个类别都在验证集。

Usage:
    python scripts/ai/build_occlusion_datasets.py --project-root .
"""

import argparse
import csv
import json
import os
import random
import shutil
import sys

from PIL import Image

_CDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_CDIR, "..", "common"))

LABELS_REL = os.path.join("annotations", "occlusion_labels.json")
MANIFEST_REL = os.path.join("dataset", "occlusion_samples", "manifest.csv")
SUGG_REL = os.path.join("suggestions", "twilight_unicorn", "s01e15",
                        "bbox_suggestions.json")

VAL_FRACTION = 0.2
SEED = 42
MIN_CROP_SIDE = 24

LABEL_DEFS = {
    "partial": {"dir": "twilight_occlusion_partial",
                "names": {0: "partial", 1: "not_partial"},
                "pos_key": "partial"},
    "occluded": {"dir": "twilight_occlusion_occluded",
                 "names": {0: "occluded", 1: "not_occluded"},
                 "pos_key": "occluded"},
}


def normalize_key(key, character_id="twilight_unicorn"):
    """标注键 → frame_id（sample_id 去掉 "{cid}_001" 后缀）。"""
    suffix = f"_{character_id}_001"
    return key[:-len(suffix)] if key.endswith(suffix) else key


def load_labels(project_root):
    """读取标注并归一化为 {frame_id: {"partial": bool, "occluded": bool}}。"""
    path = os.path.join(project_root, LABELS_REL)
    if not os.path.exists(path):
        raise FileNotFoundError(f"labels not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    normalized = {}
    for key, val in data.get("labels", {}).items():
        fid = normalize_key(key)
        normalized[fid] = {
            "partial": bool(val.get("partial", False)),
            "occluded": bool(val.get("occluded", False)),
        }
    return normalized


def _manifest_crops(project_root):
    """manifest → {frame_id: crop_path}（首条优先）。"""
    path = os.path.join(project_root, MANIFEST_REL)
    result = {}
    if not os.path.exists(path):
        return result
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            result.setdefault(r["frame_id"], r["crop_path"])
    return result


def _suggestion_bboxes(project_root):
    """全部剧集的建议文件 → {frame_id: bbox}。"""
    base = os.path.join(project_root, "suggestions")
    result = {}
    if not os.path.isdir(base):
        return result
    for cid in os.listdir(base):
        cdir = os.path.join(base, cid)
        if not os.path.isdir(cdir):
            continue
        for eid in os.listdir(cdir):
            path = os.path.join(cdir, eid, "bbox_suggestions.json")
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for s in data.get("suggestions", []):
                if s.get("bbox"):
                    result.setdefault(s["frame_id"], s["bbox"])
    return result


def _frames_index(project_root, episode_id=None, frame_id=None):
    """M01 frames_index → {frame_id: row}。

    由 episode_id 或 frame_id（s01e15_t000008_f000 格式）解析剧集。
    """
    if episode_id is None and frame_id:
        episode_id = frame_id.split("_")[0]  # "s01e15_t000008_f000" → "s01e15"
    sc, ec = episode_id[:3], episode_id[3:]
    path = os.path.join(project_root, "frames", sc, ec,
                        f"frames_index_{episode_id}.csv")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return {r["frame_id"]: r for r in csv.DictReader(f)}


def _extract_crop(project_root, out_dir, fid, frame_row, bbox):
    """按建议 bbox 现裁帧图 → 返回相对 crop 路径；失败返回 None。"""
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
    os.makedirs(out_dir, exist_ok=True)
    rel = os.path.join("dataset", "occlusion_samples", f"{fid}.png")
    with Image.open(image_path) as im:
        im.crop((x1, y1, x2, y2)).save(os.path.join(project_root, rel))
    return rel


def resolve_crops(project_root):
    """为每个标注帧解析 crop 路径。返回 {frame_id: crop_path}。"""
    labels = load_labels(project_root)
    manifest = _manifest_crops(project_root)
    bboxes = _suggestion_bboxes(project_root)
    out_dir = os.path.join(project_root, "dataset", "occlusion_samples")
    crops = {}
    missing = []
    for fid in labels:
        crop = manifest.get(fid)
        if crop and os.path.exists(os.path.join(project_root, crop)):
            crops[fid] = crop
            continue
        bbox = bboxes.get(fid)
        if bbox:
            frames = _frames_index(project_root, frame_id=fid)
            row = frames.get(fid)
            if row:
                crop = _extract_crop(project_root, out_dir, fid, row, bbox)
                if crop:
                    crops[fid] = crop
                    continue
        missing.append(fid)
    return crops, missing


def _reviewed_valid_frames(project_root):
    """可作遮挡训练样本的帧集合。

    只包含 bbox 经人工确认的帧：
      - accepted/edited 建议帧（bbox 已确认并写入正式数据）
      - 有正式 bbox 的帧（M04 crops 来源，人工标注）
    排除 rejected（bbox 被拒绝，可能框错误，错误区域裁切的 crop
    标注会污染训练）与 suggested（未审核）帧。
    """
    valid = set()
    base = os.path.join(project_root, "suggestions")
    if os.path.isdir(base):
        for cid in os.listdir(base):
            cdir = os.path.join(base, cid)
            if not os.path.isdir(cdir):
                continue
            for eid in os.listdir(cdir):
                path = os.path.join(cdir, eid, "bbox_suggestions.json")
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for s in data.get("suggestions", []):
                    if s.get("status") in ("accepted", "edited"):
                        valid.add(s["frame_id"])
    bbox_root = os.path.join(project_root, "bboxes")
    if os.path.isdir(bbox_root):
        for cid in os.listdir(bbox_root):
            cdir = os.path.join(bbox_root, cid)
            if not os.path.isdir(cdir):
                continue
            for sc in os.listdir(cdir):
                sdir = os.path.join(cdir, sc)
                if not os.path.isdir(sdir):
                    continue
                for fn in os.listdir(sdir):
                    if not fn.endswith(".csv"):
                        continue
                    with open(os.path.join(sdir, fn), "r", encoding="utf-8") as f:
                        for r in csv.DictReader(f):
                            if r.get("frame_id"):
                                valid.add(r["frame_id"])
    return valid


def build_datasets(project_root, val_fraction=VAL_FRACTION, seed=SEED):
    """构建两个分类数据集（幂等：重建前清空对应目录）。

    只使用 bbox 经人工确认的帧（accepted/edited/正式 bbox）；
    rejected/suggested 帧的遮挡标注被排除（防止污染训练）。
    返回统计 dict。
    """
    labels = load_labels(project_root)
    valid = _reviewed_valid_frames(project_root)
    excluded = {fid: lab for fid, lab in labels.items() if fid not in valid}
    labels = {fid: lab for fid, lab in labels.items() if fid in valid}
    crops, missing = resolve_crops(project_root)
    stats = {"missing": missing, "labels": len(labels),
             "excluded": len(excluded),
             "crops": len(crops)}
    rng = random.Random(seed)

    for label, cfg in LABEL_DEFS.items():
        pos_key = cfg["pos_key"]
        ds_root = os.path.join(project_root, "dataset", cfg["dir"])
        # 幂等：重建
        for split in ("train", "val"):
            for cls in cfg["names"].values():
                d = os.path.join(ds_root, split, cls)
                if os.path.isdir(d):
                    shutil.rmtree(d)
                os.makedirs(d)

        pos, neg = [], []
        for fid, lab in labels.items():
            if fid not in crops:
                continue
            (pos if lab.get(pos_key) else neg).append(fid)
        rng.shuffle(pos)
        rng.shuffle(neg)

        # 分层 80/20：每个类别至少 1 个进验证集
        n_val_pos = max(1, round(len(pos) * val_fraction)) if pos else 0
        n_val_neg = max(1, round(len(neg) * val_fraction)) if neg else 0
        val_pos, train_pos = pos[:n_val_pos], pos[n_val_pos:]
        val_neg, train_neg = neg[:n_val_neg], neg[n_val_neg:]

        def copy_all(fids, split, cls):
            for fid in fids:
                shutil.copy(os.path.join(project_root, crops[fid]),
                            os.path.join(ds_root, split, cls, f"{fid}.png"))

        copy_all(train_pos, "train", cfg["names"][0])
        copy_all(val_pos, "val", cfg["names"][0])
        copy_all(train_neg, "train", cfg["names"][1])
        copy_all(val_neg, "val", cfg["names"][1])

        # data.yaml
        with open(os.path.join(ds_root, "data.yaml"), "w", encoding="utf-8") as f:
            f.write(f"path: {cfg['dir']}\n")
            f.write("train: train\n")
            f.write("val: val\n")
            f.write(f"names: {json.dumps(cfg['names'])}\n")

        stats[label] = {
            "pos": len(pos), "neg": len(neg),
            "train_pos": len(train_pos), "val_pos": len(val_pos),
            "train_neg": len(train_neg), "val_neg": len(val_neg),
        }
    return stats


def main():
    parser = argparse.ArgumentParser(description="构建遮挡分类数据集")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    stats = build_datasets(os.path.abspath(args.project_root))
    print(f"标注帧: {stats['labels']} | crop 可解析: {stats['crops']} | 缺失: {len(stats['missing'])}")
    for label in LABEL_DEFS:
        s = stats[label]
        print(f"{label}: 正 {s['pos']} 负 {s['neg']} "
              f"| train {s['train_pos']}+{s['train_neg']} val {s['val_pos']}+{s['val_neg']}")


if __name__ == "__main__":
    main()
