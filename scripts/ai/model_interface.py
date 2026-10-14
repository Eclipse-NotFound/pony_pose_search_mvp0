#!/usr/bin/env python3
"""
MVP2 AI 模型统一接口 — model_interface.py

统一预测接口，输出转换为 MVP1 suggestion 格式：

    predict_bbox(image, model_path, settings)
        → [BBoxSuggestion]（method=yolo_detector，status=suggested）

    predict_keypoints(image, bbox, model_path, settings)
        → KeypointSuggestion（method=yolo_pose，status=suggested）

本模块不绑定具体模型。模型加载按文件扩展名路由到注册的后端：
    register_backend(".pt", loader) / 内置 ".pt"（ultralytics，可选依赖）。

AI 预测结果只是 suggestion 来源之一，必须经过人工审核才能进入正式数据；
本模块绝不写入正式标注，也不生成 Pose Vector。
"""

import os
import sys

_CDIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_CDIR, "..", "common"))
import annotation_suggestion_utils as sugg

METHOD_YOLO_DETECTOR = "yolo_detector"
METHOD_YOLO_POSE = "yolo_pose"

# 后端注册表：文件扩展名 → loader(model_path) → 带预测接口的对象
_BACKENDS = {}


def register_backend(extension, loader):
    """注册模型后端：文件扩展名 → 加载函数。

    loader(model_path) 返回预测对象，接口约定：
      - detect_bboxes(image, settings) -> [{"bbox": (x1,y1,x2,y2) 或
        {"x","y","width","height"}, "confidence": float}]
      - predict_keypoints(image, bbox, settings) ->
        {"keypoints": [(nx, ny, vis), ...], "confidence": float}
        关键点归一化到图像坐标，顺序与 schema_keypoint_order 一致；
        vis=0 表示不可用。

    供测试注册 mock 后端，也供未来接入具体模型。
    """
    ext = extension.lower()
    if not ext.startswith("."):
        ext = "." + ext
    _BACKENDS[ext] = loader


# ---------------------------------------------------------------------------
# 模型加载
# ---------------------------------------------------------------------------

def load_model(model_path):
    """加载模型。

    文件不存在 → FileNotFoundError；
    扩展名无对应后端 → ValueError（列出已注册后端，明确报错）。
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"model not found: {model_path}")
    ext = os.path.splitext(model_path)[1].lower()
    loader = _BACKENDS.get(ext)
    if loader is None:
        raise ValueError(
            f"no model backend for extension {ext!r} "
            f"(registered: {sorted(_BACKENDS)})")
    return loader(model_path)


def _load_yolo_pt(model_path):
    """ultralytics YOLO 后端（可选依赖）。"""
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise ValueError(
            "yolo backend requires 'ultralytics' (not installed)") from e
    return _UltralyticsBackend(YOLO(model_path))


class _UltralyticsBackend:
    """ultralytics 模型适配层（检测与关键点）。"""

    def __init__(self, model):
        self._model = model

    def detect_bboxes(self, image, settings):
        conf = settings.get("conf_threshold", 0.25)
        results = self._model.predict(image, conf=conf, verbose=False)
        detections = []
        for r in results:
            if r.boxes is None:
                continue
            for box, score in zip(r.boxes.xyxy, r.boxes.conf):
                x1, y1, x2, y2 = (float(v) for v in box)
                detections.append({
                    "bbox": (x1, y1, x2, y2),
                    "confidence": float(score),
                })
        return detections

    def predict_keypoints(self, image, bbox, settings):
        conf = settings.get("conf_threshold", 0.25)
        kp_conf = settings.get("kp_conf_threshold", 0.25)
        results = self._model.predict(image, conf=conf, verbose=False)
        for r in results:
            if r.keypoints is None or len(r.keypoints) == 0:
                continue
            kps = r.keypoints[0]  # 第一个目标
            data = kps.data[0] if hasattr(kps, "data") else kps.xy[0]
            kp_list = []
            confs = []
            for row in data:
                x, y, v = (float(t) for t in row[:3])
                # 单点置信度低于阈值 → 视为不可用（available=false 语义）
                vis = 1 if v >= kp_conf else 0
                kp_list.append((x / image.size[0], y / image.size[1], vis))
                confs.append(v if vis else 0.0)
            return {"keypoints": kp_list, "confidence": (sum(confs) / len(confs)) if confs else 0.0}
        raise ValueError("model returned no keypoint predictions")

    def predict_classify(self, image, settings):
        """分类预测：返回 {class_name: prob}（全部类别概率）。"""
        results = self._model.predict(image, verbose=False)
        for r in results:
            if r.probs is None:
                raise ValueError("model returned no classification probs")
            return {r.names[i]: float(p) for i, p in enumerate(r.probs.data.tolist())}
        raise ValueError("model returned no classification predictions")


register_backend(".pt", _load_yolo_pt)


# ---------------------------------------------------------------------------
# 输入转换
# ---------------------------------------------------------------------------

def _load_image(image):
    """图片输入转换：路径或 PIL.Image → PIL.Image。无效时抛 ValueError。"""
    from PIL import Image
    if isinstance(image, str):
        if not os.path.exists(image):
            raise ValueError(f"image not found: {image}")
        try:
            im = Image.open(image)
            im.load()  # 触发解码，损坏图片在此报错
            return im
        except Exception as e:
            raise ValueError(f"cannot open image {image}: {e}")
    if hasattr(image, "size") and hasattr(image, "convert"):
        return image
    raise ValueError(f"unsupported image input: {image!r}")


def _as_xyxy(value):
    """检测框统一为 (x1, y1, x2, y2)；非法时抛 ValueError。"""
    if isinstance(value, dict):
        if sugg.validate_bbox(value):
            return (value["x"], value["y"],
                    value["x"] + value["width"], value["y"] + value["height"])
        raise ValueError(f"invalid bbox dict: {value!r}")
    if isinstance(value, (tuple, list)) and len(value) == 4:
        return tuple(float(v) for v in value)
    raise ValueError(f"invalid bbox: {value!r}")


# ---------------------------------------------------------------------------
# 输出转换（纯函数，可测试）
# ---------------------------------------------------------------------------

def bbox_detections_to_suggestions(detections, image_size, frame_id,
                                   method=METHOD_YOLO_DETECTOR,
                                   conf_threshold=None, source_frame_id=""):
    """模型 bbox 原始输出 → MVP1 bbox suggestion 列表。

    detections: [{"bbox": ..., "confidence": float}, ...]
    - confidence 必须为 [0,1] 内数字，否则抛 ValueError；
    - bbox 必须合法且位于图像内；
    - conf_threshold 提供时丢弃低于阈值的检测。

    每条建议 status=suggested，只作为建议来源。
    """
    img_w, img_h = image_size
    suggestions = []
    for i, det in enumerate(detections):
        conf = det.get("confidence")
        if not (isinstance(conf, (int, float)) and not isinstance(conf, bool)
                and 0.0 <= conf <= 1.0):
            raise ValueError(f"detection[{i}] confidence out of range: {conf!r}")
        if conf_threshold is not None and conf < conf_threshold:
            continue
        x1, y1, x2, y2 = _as_xyxy(det.get("bbox"))
        if not (0 <= x1 < x2 <= img_w and 0 <= y1 < y2 <= img_h):
            raise ValueError(
                f"detection[{i}] bbox invalid for image {image_size}: "
                f"({x1}, {y1}, {x2}, {y2})")
        suggestions.append({
            "frame_id": frame_id,
            "source_frame_id": source_frame_id,
            "bbox": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
            "method": method,
            "confidence": float(conf),
            "status": "suggested",
        })
    return suggestions


def keypoint_predictions_to_suggestion(prediction, schema, frame_id, bbox,
                                       image_size, method=METHOD_YOLO_POSE,
                                       source_frame_id=""):
    """模型关键点原始输出 → MVP1 keypoint suggestion。

    prediction: {"keypoints": [(nx, ny, vis), ...], "confidence": float}
      - 坐标归一化到图像，顺序必须与 schema_keypoint_order 一致；
      - vis=0 → available=false（坐标为 None）。
    bbox: {x, y, width, height}（frame 坐标）。
    关键点转换到目标框内（crop 相对）坐标：crop_x = nx * img_w - bbox.x。

    返回单条建议（status=suggested）。
    """
    if not isinstance(prediction, dict):
        raise ValueError(f"keypoint prediction must be a dict, got: {prediction!r}")
    conf = prediction.get("confidence")
    if not (isinstance(conf, (int, float)) and not isinstance(conf, bool)
            and 0.0 <= conf <= 1.0):
        raise ValueError(f"keypoint prediction confidence out of range: {conf!r}")
    if not sugg.validate_bbox(bbox):
        raise ValueError(f"invalid bbox: {bbox!r}")

    order = sugg.schema_keypoint_order(schema)
    keypoints = prediction.get("keypoints")
    if not isinstance(keypoints, (list, tuple)) or len(keypoints) != len(order):
        raise ValueError(
            f"keypoint count mismatch: got {len(keypoints) if keypoints is not None else 'none'}, "
            f"expected {len(order)} (schema order)")

    img_w, img_h = image_size
    bx, by = bbox["x"], bbox["y"]
    flat = {}
    for path, raw in zip(order, keypoints):
        try:
            nx, ny, vis = float(raw[0]), float(raw[1]), float(raw[2])
        except (ValueError, TypeError, IndexError):
            raise ValueError(f"invalid keypoint value for {path}: {raw!r}")
        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            raise ValueError(f"keypoint {path} out of image range: ({nx}, {ny})")
        if vis > 0:
            flat[path] = {"x": nx * img_w - bx, "y": ny * img_h - by, "available": True}
        else:
            flat[path] = {"x": None, "y": None, "available": False}

    return {
        "frame_id": frame_id,
        "source_frame_id": source_frame_id,
        "method": method,
        "confidence": float(conf),
        "status": "suggested",
        "keypoints": flat,
    }


# ---------------------------------------------------------------------------
# 统一预测接口
# ---------------------------------------------------------------------------

def predict_bbox(image, model_path, settings=None):
    """统一 bbox 预测接口 → MVP1 bbox suggestion 列表（status=suggested）。

    settings 可选键：
      frame_id / source_frame_id / method / conf_threshold
    """
    settings = settings or {}
    model = load_model(model_path)
    pil_image = _load_image(image)
    detections = model.detect_bboxes(pil_image, settings)
    method = settings.get("method", METHOD_YOLO_DETECTOR)
    return bbox_detections_to_suggestions(
        detections, pil_image.size,
        frame_id=settings.get("frame_id", ""),
        method=method,
        conf_threshold=settings.get("conf_threshold"),
        source_frame_id=settings.get("source_frame_id") or method)


def predict_keypoints(image, bbox, model_path, settings=None):
    """统一关键点预测接口 → MVP1 keypoint suggestion（status=suggested）。

    settings 必填：schema（决定关键点顺序与路径）。
    可选：frame_id / source_frame_id / method / conf_threshold。
    """
    settings = settings or {}
    schema = settings.get("schema")
    if not schema:
        raise ValueError("settings['schema'] is required for keypoint prediction")
    model = load_model(model_path)
    pil_image = _load_image(image)
    prediction = model.predict_keypoints(pil_image, bbox, settings)
    method = settings.get("method", METHOD_YOLO_POSE)
    return keypoint_predictions_to_suggestion(
        prediction, schema,
        frame_id=settings.get("frame_id", ""),
        bbox=bbox, image_size=pil_image.size,
        method=method,
        source_frame_id=settings.get("source_frame_id") or method)


def predict_occlusion(image, model_path, settings=None):
    """统一遮挡分类预测接口。

    输入为单个二分类模型（partial 或 occluded，M3 训练）。
    settings 必填：occlusion_label（"partial" | "occluded"，对应
    数据集类别名）；可选 frame_id / source_frame_id / method。

    返回 {"<label>_prob": float, "top1": str, "top1_prob": float}，
    例如 {"partial_prob": 0.93, "top1": "partial", "top1_prob": 0.93}。
    模型无分类输出 / 类别名不存在 → ValueError。
    """
    settings = settings or {}
    label = settings.get("occlusion_label")
    if not label:
        raise ValueError("settings['occlusion_label'] is required "
                         "(partial | occluded)")
    model = load_model(model_path)
    pil_image = _load_image(image)
    probs = model.predict_classify(pil_image, settings)
    if label not in probs:
        raise ValueError(
            f"occlusion_label {label!r} not in model classes {sorted(probs)}")
    top1 = max(probs, key=probs.get)
    return {
        f"{label}_prob": probs[label],
        "top1": top1,
        "top1_prob": probs[top1],
    }
