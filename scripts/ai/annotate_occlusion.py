#!/usr/bin/env python3
"""M2 遮挡标注工具 — annotate_occlusion.py

人工逐张标注遮挡分类器的训练样本（多标签，可同时勾选）：

    P = partial   身体部分在帧边界外
    O = occluded  被其他角色/物品遮挡
    都不勾选 = 清晰（clear）

操作：
    P / O      切换对应标签
    ← 或 A      上一张
    → 或 D      下一张
    S           立即保存（每次切换自动保存，可随时中断）
    Esc         保存并退出

标注结果（人工成果，不在 gitignore 范围）：
    annotations/occlusion_labels.json
    {"version": "occlusion_labels_v1",
     "labels": {"<sample_id>": {"partial": bool, "occluded": bool}}}

已标注样本再次浏览时回显标签状态，可直接修改。

Usage:
    python scripts/ai/annotate_occlusion.py --project-root .
"""

import argparse
import csv
import json
import os
import sys
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

_CDIR = os.path.dirname(os.path.abspath(__file__))

LABELS_VERSION = "occlusion_labels_v1"
LABELS_REL = os.path.join("annotations", "occlusion_labels.json")
MANIFEST_REL = os.path.join("dataset", "occlusion_samples", "manifest.csv")

MAX_DISPLAY_WIDTH = 900
MAX_DISPLAY_HEIGHT = 640


def load_labels(project_root):
    """读取已有标注 → {sample_id: {"partial": bool, "occluded": bool}}。"""
    path = os.path.join(project_root, LABELS_REL)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("labels", {})


def save_labels(project_root, labels):
    """保存标注（原子写入）。"""
    path = os.path.join(project_root, LABELS_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"version": LABELS_VERSION, "labels": labels}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_manifest(project_root):
    """读取样本清单 → list[dict]；缺文件抛 FileNotFoundError。"""
    path = os.path.join(project_root, MANIFEST_REL)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"manifest not found: {path}（先运行 prepare_occlusion_samples.py）")
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def first_unlabeled(manifest, labels):
    """第一个未标注样本下标；全部已标注 → -1。"""
    for i, r in enumerate(manifest):
        if r["sample_id"] not in labels:
            return i
    return -1


class OcclusionAnnotator:
    """遮挡标注窗口。"""

    def __init__(self, root, project_root):
        self.root = root
        self.project_root = project_root
        self.root.title("Occlusion Annotator — 遮挡标注")
        self.root.geometry("1060x720")
        self.root.minsize(900, 600)

        self.manifest = load_manifest(project_root)
        if not self.manifest:
            raise ValueError("manifest is empty（无样本可标注）")
        self.labels = load_labels(project_root)
        self.idx = max(0, first_unlabeled(self.manifest, self.labels))
        self._photo = None
        self._current_row = None

        self._build_ui()
        self._bind_keys()
        self._show_current()
        self._update_progress()

    # ---- UI ----

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=5)
        main.pack(fill=tk.BOTH, expand=True)

        # 左侧：图片
        self._canvas = tk.Canvas(main, bg="#222222", highlightthickness=0)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 右侧：信息 + 操作
        info = ttk.Frame(main, width=300, padding=8)
        info.pack(side=tk.RIGHT, fill=tk.Y)
        info.pack_propagate(False)

        self._lbl_progress = ttk.Label(info, text="", font=("", 11, "bold"))
        self._lbl_progress.pack(anchor=tk.W)
        self._lbl_frame = ttk.Label(info, text="", foreground="#0066CC")
        self._lbl_frame.pack(anchor=tk.W, pady=2)
        self._lbl_source = ttk.Label(info, text="", foreground="gray")
        self._lbl_source.pack(anchor=tk.W)

        ttk.Separator(info, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(info, text="标签（可同时勾选）:", font=("", 10)).pack(anchor=tk.W)
        self._var_partial = tk.BooleanVar(value=False)
        self._var_occluded = tk.BooleanVar(value=False)
        ttk.Checkbutton(info, text="P — 部分出框（身体在帧边界外）",
                        variable=self._var_partial,
                        command=self._on_label_changed).pack(anchor=tk.W, pady=3)
        ttk.Checkbutton(info, text="O — 被遮挡（被其他角色/物品挡住）",
                        variable=self._var_occluded,
                        command=self._on_label_changed).pack(anchor=tk.W, pady=3)
        ttk.Label(info, text="都不勾选 = 清晰", foreground="gray").pack(anchor=tk.W)

        ttk.Separator(info, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        nav = ttk.Frame(info)
        nav.pack(fill=tk.X)
        ttk.Button(nav, text="◀ 上一张", command=self._prev).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav, text="下一张 ▶", command=self._next).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav, text="保存", command=self._save_now).pack(side=tk.LEFT, padx=2)
        ttk.Button(info, text="保存并退出", command=self._save_and_exit).pack(
            anchor=tk.W, pady=6)

        ttk.Label(info, text="快捷键: P/O 标签 | ←/→ 翻页 | S 保存 | Esc 退出",
                  foreground="gray", wraplength=280).pack(anchor=tk.W)

    def _bind_keys(self):
        self.root.bind("<p>", lambda e: self._toggle_partial())
        self.root.bind("<P>", lambda e: self._toggle_partial())
        self.root.bind("<o>", lambda e: self._toggle_occluded())
        self.root.bind("<O>", lambda e: self._toggle_occluded())
        self.root.bind("<Left>", lambda e: self._prev())
        self.root.bind("<a>", lambda e: self._prev())
        self.root.bind("<A>", lambda e: self._prev())
        self.root.bind("<Right>", lambda e: self._next())
        self.root.bind("<d>", lambda e: self._next())
        self.root.bind("<D>", lambda e: self._next())
        self.root.bind("<s>", lambda e: self._save_now())
        self.root.bind("<S>", lambda e: self._save_now())
        self.root.bind("<Escape>", lambda e: self._save_and_exit())

    # ---- 显示与交互 ----

    def _show_current(self):
        if self.idx < 0 or self.idx >= len(self.manifest):
            self._canvas.delete("all")
            self._lbl_progress.config(text="全部已标注完毕 🎉")
            return
        row = self.manifest[self.idx]
        self._current_row = row
        crop_path = os.path.join(self.project_root, row["crop_path"])
        try:
            im = Image.open(crop_path).convert("RGB")
        except (IOError, OSError) as e:
            self._canvas.delete("all")
            self._lbl_progress.config(text=f"图片读取失败: {crop_path}\n{e}")
            return
        im.thumbnail((MAX_DISPLAY_WIDTH, MAX_DISPLAY_HEIGHT))
        self._photo = ImageTk.PhotoImage(im)
        self._canvas.delete("all")
        self._canvas.config(width=im.width, height=im.height)
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)

        self._lbl_frame.config(
            text=f"{row['sample_id']}  |  bbox {row.get('bbox_w','?')}x"
                 f"{row.get('bbox_h','?')}")
        src = row.get("source", "")
        note = "正式 crops" if src == "official_crop" else "AI 建议帧"
        self._lbl_source.config(text=note)

        # 回显已标注状态（可修改）
        label = self.labels.get(row["sample_id"], {})
        self._var_partial.set(bool(label.get("partial", False)))
        self._var_occluded.set(bool(label.get("occluded", False)))

    def _update_progress(self):
        done = sum(1 for r in self.manifest if r["sample_id"] in self.labels)
        self._lbl_progress.config(
            text=f"进度: {done}/{len(self.manifest)} 已标注"
                 f"{'  （当前第 %d 张）' % (self.idx + 1)}")

    def _toggle_partial(self):
        self._var_partial.set(not self._var_partial.get())
        self._on_label_changed()

    def _toggle_occluded(self):
        self._var_occluded.set(not self._var_occluded.get())
        self._on_label_changed()

    def _save_current(self):
        """把当前帧判定落盘（不勾选 = 清晰）。翻页/退出前调用。"""
        if self._current_row is None:
            return
        sid = self._current_row["sample_id"]
        self.labels[sid] = {
            "partial": bool(self._var_partial.get()),
            "occluded": bool(self._var_occluded.get()),
        }
        self._save_now()
        self._update_progress()

    def _on_label_changed(self):
        """勾选变化 → 立即保存当前样本标签。"""
        self._save_current()

    def _prev(self):
        self._save_current()  # 离开当前样本前保存判定（不勾=清晰）
        if self.idx > 0:
            self.idx -= 1
            self._show_current()
            self._update_progress()

    def _next(self):
        self._save_current()  # 离开当前样本前保存判定（不勾=清晰）
        if self.idx < len(self.manifest) - 1:
            self.idx += 1
            self._show_current()
            self._update_progress()

    def _save_now(self):
        save_labels(self.project_root, self.labels)

    def _save_and_exit(self):
        self._save_now()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="遮挡标注工具")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    root = tk.Tk()
    try:
        OcclusionAnnotator(root, os.path.abspath(args.project_root))
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}")
        return 1
    root.mainloop()
    print("标注已保存:", os.path.join(os.path.abspath(args.project_root),
                                    LABELS_REL))
    return 0


if __name__ == "__main__":
    sys.exit(main())
