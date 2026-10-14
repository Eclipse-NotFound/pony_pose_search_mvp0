#!/usr/bin/env python3
"""M3 遮挡分类器训练 — train_occlusion.py

对 partial / occluded 两个标签各训练一个 YOLOv8n-cls 二分类模型。

数据：dataset/twilight_occlusion_{label}/{train,val}/{pos,neg}
     （由 build_occlusion_datasets.py 生成）
输出：
    models/twilight_occlusion_v1/{partial,occluded}_best.pt
    models/twilight_occlusion_v1/{partial,occluded}_training_record.json

Usage:
    python scripts/ai/train_occlusion.py --project-root . --label partial --epochs 100
    python scripts/ai/train_occlusion.py --project-root . --label occluded
"""

import argparse
import json
import os
import sys
import time

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

MODELS_ROOT = "models"
RUNS_ROOT = "models/_runs"
MODEL_NAME = "twilight_occlusion_v1"


def dataset_paths(project_root, label):
    """返回该标签的数据集目录与 data.yaml 路径。"""
    ds = os.path.join(project_root, "dataset", f"twilight_occlusion_{label}")
    yaml_path = os.path.join(ds, "data.yaml")
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(
            f"dataset not built: {yaml_path}（先运行 build_occlusion_datasets.py）")
    return ds, yaml_path


def train_occlusion(project_root, label, model_size="n", epochs=100,
                    imgsz=224, batch=16, device="0", workers=0,
                    use_pretrained=True):
    """训练一个二分类模型。返回训练记录 dict。"""
    from ultralytics import YOLO

    ds, yaml_path = dataset_paths(project_root, label)
    out_dir = os.path.join(project_root, MODELS_ROOT, MODEL_NAME)
    os.makedirs(out_dir, exist_ok=True)

    if use_pretrained:
        model = YOLO(f"yolov8{model_size}-cls.pt")  # 预训练权重（自动下载）
    else:
        model = YOLO(f"yolov8{model_size}-cls.yaml")

    started = time.time()
    # classify 数据集参数传目录（train/val + 类目录），不是 data.yaml。
    # amp=False：跳过 ultralytics 的 AMP 检查（会额外加载 yolo26n.pt 前向，
    # 4GB 显卡上与训练模型同时驻留导致 OOM）。
    model.train(data=ds, epochs=epochs, imgsz=imgsz, batch=batch,
                device=device, workers=workers, amp=False,
                project=os.path.join(project_root, RUNS_ROOT),
                name=f"{label}_v1", exist_ok=True, verbose=False)
    elapsed = time.time() - started

    run_dir = os.path.join(project_root, RUNS_ROOT, f"{label}_v1")
    best_src = os.path.join(run_dir, "weights", "best.pt")
    if not os.path.exists(best_src):
        raise FileNotFoundError(f"training produced no best.pt: {best_src}")
    best_dst = os.path.join(out_dir, f"{label}_best.pt")
    import shutil
    shutil.copy(best_src, best_dst)

    # 验证指标（results.csv top1）
    val_results = {}
    results_csv = os.path.join(run_dir, "results.csv")
    if os.path.exists(results_csv):
        with open(results_csv, "r", encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        if len(lines) >= 2:
            header = [h.strip() for h in lines[0].split(",")]
            last = [v.strip() for v in lines[-1].split(",")]
            row = dict(zip(header, last))
            for key in ("metrics/accuracy_top1", "metrics/accuracy_top5"):
                short = key.split("/")[-1]
                try:
                    val_results[short] = float(row.get(key, ""))
                except (ValueError, TypeError):
                    val_results[short] = None

    record = {
        "model_name": MODEL_NAME,
        "model_version": f"{MODEL_NAME}_{label}",
        "label": label,
        "training_params": {
            "base_model": f"yolov8{model_size}-cls.pt",
            "epochs": epochs, "imgsz": imgsz, "batch": batch, "device": device,
            "pretrained": use_pretrained,
        },
        "training_time_seconds": round(elapsed, 1),
        "validation_results": val_results,
        "model_file": os.path.relpath(best_dst, project_root).replace("\\", "/"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(out_dir, f"{label}_training_record.json"), "w",
              encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


def main():
    parser = argparse.ArgumentParser(description="训练遮挡分类器")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--label", choices=("partial", "occluded"), required=True)
    parser.add_argument("--model-size", default="n")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()

    record = train_occlusion(
        os.path.abspath(args.project_root), args.label,
        model_size=args.model_size, epochs=args.epochs, imgsz=args.imgsz,
        batch=args.batch, device=args.device)
    print(f"[{args.label}] 训练完成: "
          f"top1={record['validation_results'].get('accuracy_top1')} "
          f"用时 {record['training_time_seconds']}s")
    print("模型:", os.path.join("models", MODEL_NAME, f"{args.label}_best.pt"))


if __name__ == "__main__":
    main()
