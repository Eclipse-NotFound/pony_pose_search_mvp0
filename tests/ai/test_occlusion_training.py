"""
M3 遮挡分类器（数据集构建 + 训练入口）— 测试套件。

覆盖：
- build_occlusion_datasets：sample_id 键归一化、分层划分（两类都进验证集）、
  幂等重建、crop 缺失帧跳过
- train_occlusion：数据集未构建时明确失败
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "scripts", "ai"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "scripts", "common"))
import build_occlusion_datasets as bd
import train_occlusion as to


@pytest.fixture
def temp_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        yield td


def make_labeled_project(pr):
    """4 帧标注 + manifest（crop 图真实存在）。"""
    from PIL import Image
    # 标注（含 sample_id 与 frame_id 两种键）
    labels = {
        "f0001": {"partial": True, "occluded": False},
        "f0002": {"partial": False, "occluded": True},
        "f0003": {"partial": True, "occluded": True},
        "f0004_twilight_unicorn_001": {"partial": False, "occluded": False},
    }
    d = os.path.join(pr, "annotations")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "occlusion_labels.json"), "w",
              encoding="utf-8") as f:
        json.dump({"version": "occlusion_labels_v1", "labels": labels}, f)

    # manifest + crop 图
    out = os.path.join(pr, "dataset", "occlusion_samples")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "manifest.csv"), "w", newline="",
              encoding="utf-8") as f:
        f.write("sample_id,frame_id,source,bbox_x,bbox_y,bbox_w,bbox_h,"
                "crop_path,image_path\n")
        for fid in ("f0001", "f0002", "f0003", "f0004"):
            Image.new("RGB", (64, 64)).save(os.path.join(out, f"{fid}.png"))
            f.write(f"{fid},{fid},official_crop,,,,,"
                    f"dataset/occlusion_samples/{fid}.png,\n")

    # 正式 bbox（4 帧均为人工确认 → 可作训练样本）
    bbox_dir = os.path.join(pr, "bboxes", "twilight_unicorn", "s01")
    os.makedirs(bbox_dir, exist_ok=True)
    with open(os.path.join(bbox_dir, "bboxes_twilight_unicorn_s01e15.csv"),
              "w", newline="", encoding="utf-8") as f:
        f.write("sample_id,frame_id\n")
        for fid in ("f0001", "f0002", "f0003", "f0004"):
            f.write(f"{fid},{fid}\n")
    return pr


def _count_dir(path):
    return len(os.listdir(path)) if os.path.isdir(path) else 0


# =========================== 数据集构建 ===========================

class TestBuildDatasets:
    def test_normalize_key(self):
        assert bd.normalize_key("f0004_twilight_unicorn_001") == "f0004"
        assert bd.normalize_key("f0001") == "f0001"

    def test_load_labels_normalizes(self, temp_dir):
        make_labeled_project(temp_dir)
        labels = bd.load_labels(temp_dir)
        assert set(labels.keys()) == {"f0001", "f0002", "f0003", "f0004"}
        assert labels["f0004"] == {"partial": False, "occluded": False}

    def test_build_stratified_split(self, temp_dir):
        """两类都进验证集；划分比例合理。"""
        pr = make_labeled_project(temp_dir)
        stats = bd.build_datasets(pr, val_fraction=0.5, seed=1)
        for label, cfg in bd.LABEL_DEFS.items():
            ds = os.path.join(pr, "dataset", cfg["dir"])
            pos_cls, neg_cls = cfg["names"][0], cfg["names"][1]
            assert _count_dir(os.path.join(ds, "val", pos_cls)) >= 1
            assert _count_dir(os.path.join(ds, "val", neg_cls)) >= 1
            assert _count_dir(os.path.join(ds, "train", pos_cls)) >= 1
        # partial: 正 2（f0001, f0003）负 2
        assert stats["partial"]["pos"] == 2 and stats["partial"]["neg"] == 2
        # occluded: 正 2（f0002, f0003）负 2
        assert stats["occluded"]["pos"] == 2 and stats["occluded"]["neg"] == 2

    def test_build_idempotent(self, temp_dir):
        """重复构建不残留旧文件（重建清空）。"""
        pr = make_labeled_project(temp_dir)
        bd.build_datasets(pr, seed=1)
        first = _count_dir(os.path.join(
            pr, "dataset", "twilight_occlusion_partial", "train", "partial"))
        bd.build_datasets(pr, seed=1)
        second = _count_dir(os.path.join(
            pr, "dataset", "twilight_occlusion_partial", "train", "partial"))
        assert first == second > 0

    def test_missing_crop_skipped(self, temp_dir):
        """crop 缺失的帧被跳过并计入 missing。"""
        pr = make_labeled_project(temp_dir)
        os.remove(os.path.join(pr, "dataset", "occlusion_samples",
                               "f0002.png"))
        stats = bd.build_datasets(pr, seed=1)
        assert "f0002" in stats["missing"]
        # f0002 是 occluded 正样本 → occluded 正样本少 1
        assert stats["occluded"]["pos"] == 1

    def test_labels_missing_fails(self, temp_dir):
        with pytest.raises(FileNotFoundError):
            bd.build_datasets(temp_dir)

    def test_rejected_frames_excluded(self, temp_dir):
        """rejected/suggested 帧的遮挡标注被排除（不污染训练）。

        真实场景：rejected 帧无正式 bbox（reject 不写正式数据），
        因此删除 fixture 的 bboxes CSV 模拟。
        """
        pr = make_labeled_project(temp_dir)
        # 删除正式 bbox（模拟 rejected/suggested 帧无正式 bbox）
        os.remove(os.path.join(pr, "bboxes", "twilight_unicorn", "s01",
                               "bboxes_twilight_unicorn_s01e15.csv"))
        # 构造建议文件：f0001=rejected, f0002=suggested, f0003=accepted
        sug_dir = os.path.join(pr, "suggestions", "twilight_unicorn", "s01e15")
        os.makedirs(sug_dir, exist_ok=True)
        suggestions = []
        for i, (fid, st) in enumerate((("f0001", "rejected"),
                                       ("f0002", "suggested"),
                                       ("f0003", "accepted"))):
            suggestions.append({
                "frame_id": fid, "source_frame_id": "yolo_detector_v1",
                "bbox": {"x": 1 + i, "y": 1, "width": 50, "height": 50},
                "method": "yolo_detector_v1", "confidence": 0.9,
                "status": st,
            })
        with open(os.path.join(sug_dir, "bbox_suggestions.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": "mvp1_bbox_suggestions_v1",
                       "character_id": "twilight_unicorn",
                       "episode_id": "s01e15",
                       "suggestions": suggestions}, f)
        valid = bd._reviewed_valid_frames(pr)
        assert "f0001" not in valid   # rejected 排除
        assert "f0002" not in valid   # suggested 排除
        assert "f0003" in valid       # accepted 保留
        assert "f0004" not in valid   # 无正式 bbox 也无建议 → 排除
        # build 后统计排除数 = 3（f0001 rejected + f0002 suggested + f0004）
        stats = bd.build_datasets(pr, seed=1)
        assert stats["excluded"] == 3
        # 被排除帧的标注不出现在数据集中
        for label in bd.LABEL_DEFS:
            ds = os.path.join(pr, "dataset", bd.LABEL_DEFS[label]["dir"])
            found = []
            for split in ("train", "val"):
                for cls in bd.LABEL_DEFS[label]["names"].values():
                    d = os.path.join(ds, split, cls)
                    if os.path.isdir(d):
                        found += os.listdir(d)
            assert not any(x.startswith(("f0001", "f0002", "f0004"))
                           for x in found)


# =========================== 训练入口 ===========================

class TestTrainOcclusion:
    def test_dataset_not_built_fails(self, temp_dir):
        """数据集未构建 → FileNotFoundError（在加载模型前失败）。"""
        with pytest.raises(FileNotFoundError, match="dataset not built"):
            to.train_occlusion(temp_dir, "partial")

    def test_data_yaml_written(self, temp_dir):
        """构建后 data.yaml 存在且 names 正确。"""
        pr = make_labeled_project(temp_dir)
        bd.build_datasets(pr, seed=1)
        for label, cfg in bd.LABEL_DEFS.items():
            yaml_path = os.path.join(pr, "dataset", cfg["dir"], "data.yaml")
            assert os.path.exists(yaml_path)
            with open(yaml_path, encoding="utf-8") as f:
                content = f.read()
            assert cfg["dir"] in content
            assert "names" in content
