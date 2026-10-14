"""
M2 遮挡标注（样本准备 + 标注工具）— 测试套件。

覆盖：
- prepare_occlusion_samples：manifest 生成/字段/幂等/过小样本过滤/分层采样
- annotate_occlusion 纯逻辑：labels 读写往返、first_unlabeled、manifest 缺失报错
- GUI 冒烟：标注窗口打开、勾选标签立即保存、续标回显
"""

import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "scripts", "ai"))
import prepare_occlusion_samples as prep
import annotate_occlusion as ann

CID, EID = "twilight_unicorn", "s01e15"


@pytest.fixture
def temp_dir():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        yield td


def make_project(pr, n_frames=3):
    """帧图 + frames_index + 建议文件（带 quality）+ 1 张正式 crop。"""
    from PIL import Image
    sc, ec = EID[:3], EID[3:]
    frames_dir = os.path.join(pr, "frames", sc, ec)
    os.makedirs(frames_dir)
    for i in range(n_frames):
        Image.new("RGB", (300, 200), (i * 40, 100, 200)).save(
            os.path.join(frames_dir, f"{EID}_t0000{i}_f000.png"))
    with open(os.path.join(frames_dir, f"frames_index_{EID}.csv"),
              "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame_id", "episode_id", "season", "episode",
                    "timestamp_sec", "timestamp_frame", "timestamp_text",
                    "image_path"])
        for i in range(n_frames):
            w.writerow([f"{EID}_t0000{i}_f000", EID, "1", "15", str(i), "0",
                        f"00:00:0{i}", f"frames/s01/e15/{EID}_t0000{i}_f000.png"])

    # 建议文件（带 quality score，覆盖低/高分）
    sug_dir = os.path.join(pr, "suggestions", CID, EID)
    os.makedirs(sug_dir, exist_ok=True)
    suggestions = []
    for i in range(n_frames):
        suggestions.append({
            "frame_id": f"{EID}_t0000{i}_f000",
            "source_frame_id": "yolo_detector_v1",
            "bbox": {"x": 40 + i, "y": 30, "width": 150, "height": 120},
            "method": "yolo_detector_v1", "confidence": 0.9,
            "status": "suggested",
            "quality": {"score": 0.3 if i == 0 else 1.0,
                        "low_res": i == 0, "partial": False,
                        "occluded": False, "blurred": None,
                        "occlusion_hints": [], "res": {}},
        })
    with open(os.path.join(sug_dir, "bbox_suggestions.json"), "w",
              encoding="utf-8") as f:
        json.dump({"version": "mvp1_bbox_suggestions_v1",
                   "character_id": CID, "episode_id": EID,
                   "suggestions": suggestions}, f)

    # 正式 crops（1 张）
    crop_dir = os.path.join(pr, "crops", CID, sc, ec)
    os.makedirs(crop_dir, exist_ok=True)
    Image.new("RGB", (100, 90)).save(os.path.join(
        crop_dir, f"{EID}_t00000_f000_{CID}_001.png"))
    with open(os.path.join(crop_dir, f"crops_index_{CID}_{EID}.csv"),
              "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "frame_id", "crop_path"])
        w.writerow([f"{EID}_t00000_f000_{CID}_001", f"{EID}_t00000_f000",
                    f"crops/{CID}/s01/e15/{EID}_t00000_f000_{CID}_001.png"])
    return pr


def manifest_rows(pr):
    with open(os.path.join(pr, prep.OUT_ROOT, prep.MANIFEST_NAME),
              encoding="utf-8") as f:
        return list(csv.DictReader(f))


# =========================== 样本准备 ===========================

class TestPrepareSamples:
    def test_prepare_basic(self, temp_dir):
        pr = make_project(temp_dir)
        rows = prep.prepare_samples(pr, [CID], [EID], target=5, seed=1)
        # 1 张正式 crop + 建议帧采样（target 内）
        assert len(rows) >= 1
        assert rows[0]["source"] == "official_crop"
        # crop 文件全部存在
        for r in rows:
            assert os.path.exists(os.path.join(pr, r["crop_path"])), r["sample_id"]
        # 字段完整
        for r in rows:
            for field in prep.MANIFEST_FIELDS:
                assert field in r, field

    def test_prepare_idempotent(self, temp_dir):
        """重复运行不重复裁切/登记（sample_id 去重）。"""
        pr = make_project(temp_dir)
        prep.prepare_samples(pr, [CID], [EID], target=5, seed=1)
        first = manifest_rows(pr)
        prep.prepare_samples(pr, [CID], [EID], target=5, seed=1)
        second = manifest_rows(pr)
        assert len(first) == len(second)
        assert [r["sample_id"] for r in first] == [r["sample_id"] for r in second]

    def test_low_score_samples_preferred(self, temp_dir):
        """分层采样：低质量分（score<0.8）优先覆盖。"""
        pr = make_project(temp_dir)
        rows = prep.prepare_samples(pr, [CID], [EID], target=2, seed=1)
        # 低分样本 t00000 必须被选中（source=ai_suggestion 且 score 0.3）
        low = [r for r in rows if r["sample_id"] == f"{EID}_t00000_f000"]
        assert low, "低质量分样本应被优先纳入"

    def test_tiny_bbox_skipped(self, temp_dir):
        """过小 bbox（< MIN_CROP_SIDE）→ 跳过不生成 crop。"""
        pr = make_project(temp_dir)
        # 把一个建议 bbox 改到 5x5
        with open(os.path.join(pr, "suggestions", CID, EID,
                               "bbox_suggestions.json"), "r",
                  encoding="utf-8") as f:
            data = json.load(f)
        data["suggestions"][1]["bbox"] = {"x": 10, "y": 10, "width": 5, "height": 5}
        with open(os.path.join(pr, "suggestions", CID, EID,
                               "bbox_suggestions.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f)
        rows = prep.prepare_samples(pr, [CID], [EID], target=10, seed=1)
        tiny = [r for r in rows if r["bbox_w"] == "5"]
        assert not tiny, "过小 bbox 的样本不应进入 manifest"


# =========================== 标注逻辑 ===========================

class TestAnnotationLogic:
    def test_labels_roundtrip(self, temp_dir):
        labels = {"s1": {"partial": True, "occluded": False},
                  "s2": {"partial": False, "occluded": True}}
        ann.save_labels(temp_dir, labels)
        assert ann.load_labels(temp_dir) == labels

    def test_labels_missing_file(self, temp_dir):
        assert ann.load_labels(temp_dir) == {}

    def test_load_manifest_missing_fails(self, temp_dir):
        with pytest.raises(FileNotFoundError):
            ann.load_manifest(temp_dir)

    def test_first_unlabeled(self, temp_dir):
        pr = make_project(temp_dir)
        rows = prep.prepare_samples(pr, [CID], [EID], target=5, seed=1)
        labels = {}
        assert ann.first_unlabeled(rows, labels) == 0
        labels[rows[0]["sample_id"]] = {"partial": False, "occluded": False}
        assert ann.first_unlabeled(rows, labels) == 1
        for r in rows:
            labels[r["sample_id"]] = {"partial": False, "occluded": False}
        assert ann.first_unlabeled(rows, labels) == -1

    def test_labels_file_outside_gitignore(self, temp_dir):
        """标注结果是人工成果，必须落在非 ignore 目录（annotations/）。"""
        pr = make_project(temp_dir)
        ann.save_labels(pr, {"s1": {"partial": True, "occluded": False}})
        assert os.path.exists(os.path.join(pr, "annotations",
                                           "occlusion_labels.json"))


# =========================== GUI 冒烟 ===========================

class TestAnnotatorGui:
    def test_annotate_and_resume(self, temp_dir):
        """打开标注窗口 → 勾选保存 → 重开回显（续标）。"""
        import gc
        import time
        import tkinter as tk
        pr = make_project(temp_dir)
        prep.prepare_samples(pr, [CID], [EID], target=3, seed=1)
        rows = manifest_rows(pr)

        def _create_tk():
            for _ in range(3):
                try:
                    return tk.Tk()
                except tk.TclError:
                    time.sleep(0.2)
                    gc.collect()
            raise RuntimeError("cannot create Tk root")

        root = _create_tk()
        root.withdraw()
        try:
            app = ann.OcclusionAnnotator(root, pr)
            assert app.manifest  # 加载成功
            # 勾选当前样本 → 立即保存
            app._var_partial.set(True)
            app._on_label_changed()
            sid = app.manifest[app.idx]["sample_id"]
            labels = ann.load_labels(pr)
            assert labels[sid]["partial"] is True
            # 下一张 → 上一张回显（可修改）
            app._next()
            assert app.idx == 1
            app._prev()
            assert ann.load_labels(pr)[sid]["partial"] is True
            # 重开窗口：跳转到第一个未标注样本
            # （翻页保存生效：浏览过的 sample0/sample1 都算已标注）
            root.destroy()
            root2 = _create_tk()
            root2.withdraw()
            app2 = ann.OcclusionAnnotator(root2, pr)
            assert app2.idx == 2
            assert app2.labels[sid]["partial"] is True
            root2.destroy()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    def test_navigation_records_clear(self, temp_dir):
        """翻页保存当前样本判定：不勾选（清晰）也会被记录（修复 bug）。"""
        import gc
        import time
        import tkinter as tk
        pr = make_project(temp_dir)
        prep.prepare_samples(pr, [CID], [EID], target=3, seed=1)
        rows = manifest_rows(pr)

        def _create_tk():
            for _ in range(3):
                try:
                    return tk.Tk()
                except tk.TclError:
                    time.sleep(0.2)
                    gc.collect()
            raise RuntimeError("cannot create Tk root")

        root = _create_tk()
        root.withdraw()
        try:
            app = ann.OcclusionAnnotator(root, pr)
            sid0 = app.manifest[app.idx]["sample_id"]
            # 不勾选 → 直接翻页 → 清晰被记录
            app._next()
            labels = ann.load_labels(pr)
            assert labels[sid0] == {"partial": False, "occluded": False}
        finally:
            root.destroy()
