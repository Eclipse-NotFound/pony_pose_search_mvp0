#!/usr/bin/env python3
"""M03 AI 图片质量判断 — quality_utils.py

纯函数：分辨率 / 清晰度 / 遮挡（算法侧）指标计算与 quality 汇总。

只标记不拦截：所有指标只写入 suggestion / AI 候选 CSV 的 quality 字段，
不修改正式数据，不自动过滤/拒绝。AI 遮挡概率（M4 分类器）由调用方
传入 extra 信号融合，本模块只做确定性算法指标。

阈值基于真实标注分布校准（e15/e24 crops + 正式 bbox，帧 1920×1080）：
- 分辨率：e15 正式框短边 min=90 / 中位=452 → 短边<100 或 面积<10000 → 低分辨率
- 宽高比：e15 正式框 w/h p10~p90 = 0.72~1.67 → 正常区间 [0.6, 1.8]
- 清晰度：e15/e24 crops Laplacian 方差 中位≈306、底部 ~15% <150 → 阈值 150
"""

import os

import cv2
import numpy as np
from PIL import Image

QUALITY_VERSION = "mvp1_quality_v1"

# ---------------------------------------------------------------------------
# 阈值常量（基于真实数据校准；调用方可覆盖）
# ---------------------------------------------------------------------------

LOW_RES_MIN_SIDE = 100.0     # 短边 < 100px → 低分辨率
LOW_RES_AREA = 10000.0       # 面积 < 10000px² → 低分辨率
SMALL_MIN_SIDE = 200.0       # 短边 < 200px → 偏小（提示档，不判定 low_res）
FRAME_RATIO_LOW = 0.005      # bbox 面积 / 帧面积 < 0.5% → 相对占比低
EDGE_CUT_MARGIN = 2.0        # bbox 距帧边 < 2px → 边缘截断（partial 提示）
ASPECT_RATIO_RANGE = (0.6, 1.8)  # w/h 正常范围（超出 → 疑似遮挡/检测错误）
BLUR_LAPLACIAN_VAR = 150.0   # Laplacian 方差 < 150 → 模糊
MIN_SHARPNESS_PATCH = 8      # 清晰度计算的最小 crop 边长（更小则跳过）

# score 扣分（启发式，仅用于排序参考）
_PENALTY = {
    "low_res": 0.30,
    "occluded": 0.25,
    "partial": 0.20,
    "blurred": 0.20,
}


# ---------------------------------------------------------------------------
# 分辨率指标
# ---------------------------------------------------------------------------

def bbox_metrics(bbox, frame_size):
    """计算 bbox 分辨率指标。

    返回 {area, min_side, max_side, aspect_ratio, frame_ratio}：
      area        bbox 像素面积（w*h）
      min_side    短边像素（角色最小可分辨尺寸）
      aspect_ratio  w/h（宽高比，正常区间见 ASPECT_RATIO_RANGE）
      frame_ratio bbox 面积 / 帧面积（跨分辨率相对占比）
    非法 bbox / 帧尺寸 → ValueError。
    """
    w = bbox.get("width", 0)
    h = bbox.get("height", 0)
    if not (w > 0 and h > 0):
        raise ValueError(f"invalid bbox: {bbox!r}")
    fw, fh = frame_size
    if not (fw > 0 and fh > 0):
        raise ValueError(f"invalid frame size: {frame_size!r}")
    area = w * h
    return {
        "area": area,
        "min_side": min(w, h),
        "max_side": max(w, h),
        "aspect_ratio": w / h,
        "frame_ratio": area / (fw * fh),
    }


def detect_low_res(bbox, frame_size, min_side=LOW_RES_MIN_SIDE,
                   area=LOW_RES_AREA):
    """低分辨率：短边或面积低于阈值（角色在画面中像素太少）。"""
    m = bbox_metrics(bbox, frame_size)
    return m["min_side"] < min_side or m["area"] < area


def detect_small(bbox, frame_size, min_side=SMALL_MIN_SIDE):
    """偏小提示档（不判定 low_res，仅提示）。"""
    return bbox_metrics(bbox, frame_size)["min_side"] < min_side


def detect_low_frame_ratio(bbox, frame_size, ratio=FRAME_RATIO_LOW):
    """相对画面占比过低（跨视频分辨率自适应）。"""
    return bbox_metrics(bbox, frame_size)["frame_ratio"] < ratio


# ---------------------------------------------------------------------------
# 遮挡（算法侧）
# ---------------------------------------------------------------------------

def detect_edge_cut(bbox, frame_size, margin=EDGE_CUT_MARGIN):
    """边缘截断：bbox 贴到帧边界（身体部分在帧外 → partial 提示）。"""
    w = bbox.get("width", 0)
    h = bbox.get("height", 0)
    x, y = bbox.get("x", 0), bbox.get("y", 0)
    fw, fh = frame_size
    return (x <= margin or y <= margin
            or x + w >= fw - margin or y + h >= fh - margin)


def detect_aspect_outlier(bbox, aspect_range=ASPECT_RATIO_RANGE):
    """宽高比异常：超出正常区间 → 疑似部分遮挡或检测框错误。"""
    ratio = bbox_metrics(bbox, (1, 1))["aspect_ratio"]  # 比例与帧尺寸无关
    lo, hi = aspect_range
    return ratio < lo or ratio > hi


# ---------------------------------------------------------------------------
# 清晰度
# ---------------------------------------------------------------------------

def _to_grayscale_array(image):
    """image（PIL.Image 或路径）→ uint8 灰度数组；失败抛异常。"""
    if isinstance(image, str):
        with Image.open(image) as im:
            im = im.convert("L")
            return np.asarray(im, dtype=np.uint8)
    im = image.convert("L")
    return np.asarray(im, dtype=np.uint8)


def sharpness_variance(image, bbox=None):
    """Laplacian 方差（清晰度）。返回 float；图太小/加载失败返回 None。

    bbox 提供时只在角色区域计算（crop 过小则跳过）。
    """
    try:
        arr = _to_grayscale_array(image)
    except Exception:
        return None
    if bbox is not None:
        x1 = max(0, int(bbox.get("x", 0)))
        y1 = max(0, int(bbox.get("y", 0)))
        x2 = min(arr.shape[1], int(bbox.get("x", 0) + bbox.get("width", 0)))
        y2 = min(arr.shape[0], int(bbox.get("y", 0) + bbox.get("height", 0)))
        if x2 - x1 < MIN_SHARPNESS_PATCH or y2 - y1 < MIN_SHARPNESS_PATCH:
            return None
        arr = arr[y1:y2, x1:x2]
    if arr.size == 0:
        return None
    try:
        return float(cv2.Laplacian(arr, cv2.CV_64F).var())
    except cv2.error:
        return None


def detect_blurred(image, bbox=None, threshold=BLUR_LAPLACIAN_VAR):
    """模糊判断：Laplacian 方差 < 阈值 → True；无法计算 → None。"""
    v = sharpness_variance(image, bbox)
    if v is None:
        return None
    return v < threshold


# ---------------------------------------------------------------------------
# quality 汇总
# ---------------------------------------------------------------------------

def assess_bbox_quality(image, bbox, frame_size=None,
                        blur_threshold=BLUR_LAPLACIAN_VAR,
                        ai_signals=None):
    """对单个 bbox 汇总质量指标。

    输入：
      image        PIL.Image 或图片路径（None 时需给 frame_size，跳过清晰度）
      bbox         {x, y, width, height}（帧坐标）
      frame_size   (w, h)；缺省从 image 读取
      ai_signals   可选 AI 信号 dict（M4 分类器）：
                   {"partial_prob": float, "occluded_prob": float}

    返回 quality dict（见 QUALITY_VERSION）：
      partial / occluded / low_res / blurred / occlusion_hints /
      res{area,min_side,aspect_ratio,frame_ratio,sharpness} / score
    不会失败：bbox 非法 → ValueError；清晰度计算失败 → blurred=None。
    """
    if not (isinstance(bbox, dict) and bbox.get("width", 0) > 0
            and bbox.get("height", 0) > 0):
        raise ValueError(f"invalid bbox for quality: {bbox!r}")
    if frame_size is None:
        if isinstance(image, str):
            with Image.open(image) as im:
                frame_size = im.size
        elif image is not None:
            frame_size = image.size
        else:
            raise ValueError("quality requires frame_size when no image given")

    m = bbox_metrics(bbox, frame_size)
    edge_cut = detect_edge_cut(bbox, frame_size)
    aspect = detect_aspect_outlier(bbox)

    ai_signals = ai_signals or {}
    partial_prob = ai_signals.get("partial_prob")
    occluded_prob = ai_signals.get("occluded_prob")
    ai_partial = partial_prob is not None and partial_prob > 0.5
    ai_occluded = occluded_prob is not None and occluded_prob > 0.5

    partial = edge_cut or ai_partial
    occluded = aspect or ai_occluded

    hints = []
    if edge_cut:
        hints.append("edge_cut")
    if aspect:
        hints.append("aspect_ratio")
    if ai_partial:
        hints.append("ai_partial")
    if ai_occluded:
        hints.append("ai_occluded")

    sharp = sharpness_variance(image, bbox)
    blurred = None if sharp is None else sharp < blur_threshold
    low_res = m["min_side"] < LOW_RES_MIN_SIDE or m["area"] < LOW_RES_AREA

    # 连续扣分：有 AI 概率时按概率加权（避免离散扣分导致分数平台化，
    # 如大量帧固定卡在 0.55 = partial+occluded 组合）；无概率按满额扣。
    score = 1.0
    if low_res:
        score -= _PENALTY["low_res"]
    if occluded:
        score -= _PENALTY["occluded"] * (occluded_prob if occluded_prob is not None else 1.0)
    if partial:
        score -= _PENALTY["partial"] * (partial_prob if partial_prob is not None else 1.0)
    if blurred:
        score -= _PENALTY["blurred"]
    score = round(max(0.0, min(1.0, score)), 2)

    quality = {
        "version": QUALITY_VERSION,
        "partial": bool(partial),
        "occluded": bool(occluded),
        "occlusion_hints": hints,
        "low_res": bool(low_res),
        "blurred": blurred,
        "res": {
            "area": m["area"],
            "min_side": m["min_side"],
            "max_side": m["max_side"],
            "aspect_ratio": round(m["aspect_ratio"], 3),
            "frame_ratio": round(m["frame_ratio"], 5),
            "sharpness": None if sharp is None else round(sharp, 1),
        },
        "score": score,
    }
    if partial_prob is not None:
        quality["partial_prob"] = round(float(partial_prob), 4)
    if occluded_prob is not None:
        quality["occluded_prob"] = round(float(occluded_prob), 4)
    return quality
