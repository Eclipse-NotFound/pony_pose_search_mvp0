#!/usr/bin/env python3
"""
Annotation Suggestion Utils — MVP1 共享纯工具。

为 M03 角色框建议与 M05 关键点建议提供：
- 建议状态校验（suggested / accepted / edited / rejected）
- bbox 建议 / keypoint 建议文件格式校验
- 建议文件 JSON 读写（UTF-8，格式稳定）
- bbox 坐标工具（校验 / 归一化 / 裁剪 / 插值）
- 关键点坐标映射（相对坐标 / 跨框映射 / 插值）

本模块只包含纯函数：
- 不包含 GUI 逻辑；
- 不包含跟踪算法（CSRT / 光流 / 模板匹配）；
- 不隐式扫描或修改项目数据目录；
- 不会读写正式标注数据（bboxes / keypoints / poses）。

建议文件属于派生数据，只能写入独立建议路径，正式数据只能由后续人工确认流程写入。
"""

import json
import os


# ---------------------------------------------------------------------------
# schema 关键点顺序（dataset 导出与 AI 预测共用）
# ---------------------------------------------------------------------------

def schema_keypoint_order(schema):
    """返回 schema 关键点路径的有序列表。

    顺序规则：
    - 按 keypoint_rules 的组顺序；
    - 普通组按组内名称顺序；
    - 腿部按 leg 顺序 + leg_keypoint_rules 子键顺序。

    dataset 导出与 AI 预测必须使用同一顺序。
    """
    order = []
    rules = schema.get("keypoint_rules", {})
    leg_rules = schema.get("leg_keypoint_rules", {})
    for group_name, names in rules.items():
        if group_name in ("front_legs", "back_legs"):
            subs = leg_rules.get(group_name, [])
            for leg_name in names:
                for sub in subs:
                    order.append(f"{group_name}.{leg_name}.{sub}")
        else:
            for name in names:
                order.append(f"{group_name}.{name}")
    return order


# ---------------------------------------------------------------------------
# 建议版本与状态
# ---------------------------------------------------------------------------

BBOX_SUGGESTION_VERSION = "mvp1_bbox_suggestions_v1"
KEYPOINT_SUGGESTION_VERSION = "mvp1_keypoint_suggestions_v1"

VALID_STATUSES = ("suggested", "accepted", "edited", "rejected")

STATUS_MEANINGS = {
    "suggested": "系统已生成建议，尚未确认",
    "accepted": "用户直接接受建议",
    "edited": "用户修改后接受",
    "rejected": "用户拒绝建议",
}


def is_valid_status(status):
    """status 是否为四种合法状态之一。"""
    return status in VALID_STATUSES


# ---------------------------------------------------------------------------
# 基础类型校验
# ---------------------------------------------------------------------------

def _is_number(value):
    """是否为数字（排除 bool，bool 是 int 子类）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_ratio(ratio):
    """ratio 必须在 [0.0, 1.0] 范围内，否则抛出明确错误。"""
    if not _is_number(ratio) or not (0.0 <= ratio <= 1.0):
        raise ValueError(f"ratio must be a number in [0.0, 1.0], got: {ratio!r}")


def _require_positive_image(image_width, image_height):
    """图像宽高必须为正数。"""
    if not (_is_number(image_width) and _is_number(image_height)
            and image_width > 0 and image_height > 0):
        raise ValueError(
            f"image size must be positive numbers, got: {image_width}x{image_height}")


# ---------------------------------------------------------------------------
# 角色框工具
# ---------------------------------------------------------------------------

def validate_bbox(bbox):
    """校验 bbox 结构是否合法。

    bbox 格式：{"x": .., "y": .., "width": .., "height": ..}
    - x / y / width / height 必须为数字（不允许 bool、字符串）
    - width > 0，height > 0
    - 坐标为负数时结构仍合法（例如部分位于图像外的框），
      由 clip_bbox_to_image 负责图像范围约束

    返回 True / False，不抛出异常。
    """
    if not isinstance(bbox, dict):
        return False
    if not all(k in bbox for k in ("x", "y", "width", "height")):
        return False
    if not all(_is_number(bbox[k]) for k in ("x", "y", "width", "height")):
        return False
    return bbox["width"] > 0 and bbox["height"] > 0


def _require_valid_bbox(bbox):
    """validate_bbox 失败时抛出明确错误（供其他工具函数使用）。"""
    if not validate_bbox(bbox):
        raise ValueError(
            "Invalid bbox, expected dict with numeric x/y and width > 0, "
            f"height > 0: {bbox!r}")


def normalize_bbox(bbox, image_width, image_height):
    """将 bbox 坐标归一化为相对图像宽高的比例值（0-1 范围）。

    返回 {"x": .., "y": .., "width": .., "height": ..}，全部为 float。
    只做比例换算，不做裁剪；超出图像范围的部分保持超出。
    """
    _require_valid_bbox(bbox)
    _require_positive_image(image_width, image_height)
    return {
        "x": bbox["x"] / image_width,
        "y": bbox["y"] / image_height,
        "width": bbox["width"] / image_width,
        "height": bbox["height"] / image_height,
    }


def clip_bbox_to_image(bbox, image_width, image_height):
    """将 bbox 裁剪到图像范围内。

    - 裁剪后宽高仍必须大于 0；
    - bbox 完全位于图像外时抛出 ValueError（不允许静默产生空框）。
    """
    _require_valid_bbox(bbox)
    _require_positive_image(image_width, image_height)

    x1 = max(bbox["x"], 0)
    y1 = max(bbox["y"], 0)
    x2 = min(bbox["x"] + bbox["width"], image_width)
    y2 = min(bbox["y"] + bbox["height"], image_height)

    if x2 <= x1 or y2 <= y1:
        raise ValueError(
            f"bbox fully outside image {image_width}x{image_height}: {bbox!r}")

    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def interpolate_bbox(bbox_a, bbox_b, ratio):
    """按 ratio (0.0-1.0) 对两个 bbox 做线性插值。

    ratio=0.0 时等于 bbox_a，ratio=1.0 时等于 bbox_b。
    输出坐标可能为 float。
    """
    _require_valid_bbox(bbox_a)
    _require_valid_bbox(bbox_b)
    _require_ratio(ratio)

    return {
        "x": bbox_a["x"] + (bbox_b["x"] - bbox_a["x"]) * ratio,
        "y": bbox_a["y"] + (bbox_b["y"] - bbox_a["y"]) * ratio,
        "width": bbox_a["width"] + (bbox_b["width"] - bbox_a["width"]) * ratio,
        "height": bbox_a["height"] + (bbox_b["height"] - bbox_a["height"]) * ratio,
    }


# ---------------------------------------------------------------------------
# 关键点坐标工具
# ---------------------------------------------------------------------------

def _as_point(value):
    """把 (x, y) 元组 / 列表 / 含 x、y 的 dict 统一转成 (x, y)。

    坐标必须是数字，否则抛出明确错误。
    """
    if isinstance(value, dict):
        x, y = value.get("x"), value.get("y")
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        x, y = value[0], value[1]
    else:
        raise ValueError(
            f"point must be a (x, y) tuple/list or dict with x/y, got: {value!r}")

    if not (_is_number(x) and _is_number(y)):
        raise ValueError(f"point coordinates must be numbers, got: {value!r}")
    return x, y


def point_to_bbox_relative(point, bbox):
    """将绝对坐标点转换为 bbox 内相对坐标 (rx, ry)。

    点在 bbox 内时相对坐标落在 [0.0, 1.0]；允许超出范围（不裁剪）。
    """
    _require_valid_bbox(bbox)
    px, py = _as_point(point)
    return ((px - bbox["x"]) / bbox["width"],
            (py - bbox["y"]) / bbox["height"])


def point_from_bbox_relative(relative_point, bbox):
    """将 bbox 内相对坐标 (rx, ry) 转换为绝对坐标 (x, y)。"""
    _require_valid_bbox(bbox)
    rx, ry = _as_point(relative_point)
    return (bbox["x"] + rx * bbox["width"],
            bbox["y"] + ry * bbox["height"])


def map_keypoints_between_bboxes(keypoints, source_bbox, target_bbox):
    """把关键点从源框映射到目标框。

    keypoints 格式：{"<name>": {"x": .., "y": .., "available": bool}, ...}

    基础映射规则：
    - available=true 的关键点：先转为源框内相对坐标，再映射到目标框；
    - available=false 的关键点：保持不可用，输出坐标为 None（不参与映射）。
    """
    _require_valid_bbox(source_bbox)
    _require_valid_bbox(target_bbox)
    if not isinstance(keypoints, dict):
        raise ValueError(f"keypoints must be a dict, got: {keypoints!r}")

    mapped = {}
    for name, kp in keypoints.items():
        if not isinstance(kp, dict):
            raise ValueError(f"keypoint '{name}' must be a dict, got: {kp!r}")
        if not isinstance(kp.get("available"), bool):
            raise ValueError(
                f"keypoint '{name}' must have a bool 'available' field, got: {kp!r}")

        if not kp["available"]:
            mapped[name] = {"x": None, "y": None, "available": False}
            continue

        rx, ry = point_to_bbox_relative(kp, source_bbox)
        nx, ny = point_from_bbox_relative((rx, ry), target_bbox)
        mapped[name] = {"x": nx, "y": ny, "available": True}

    return mapped


def interpolate_keypoints(keypoints_a, keypoints_b, ratio):
    """按 ratio (0.0-1.0) 对两帧关键点做线性插值。

    明确规则：
    - 两端均 available=true 的关键点：插值坐标，结果为 available=true；
    - 其他情况（任一端不可用或只在一端出现）：
      结果为 available=false，坐标为 None。
    """
    _require_ratio(ratio)
    if not isinstance(keypoints_a, dict) or not isinstance(keypoints_b, dict):
        raise ValueError("keypoints_a and keypoints_b must be dicts")

    result = {}
    for name in set(keypoints_a) | set(keypoints_b):
        ka, kb = keypoints_a.get(name), keypoints_b.get(name)
        both_available = (
            isinstance(ka, dict) and isinstance(kb, dict)
            and ka.get("available") is True and kb.get("available") is True
        )
        if both_available:
            result[name] = {
                "x": ka["x"] + (kb["x"] - ka["x"]) * ratio,
                "y": ka["y"] + (kb["y"] - ka["y"]) * ratio,
                "available": True,
            }
        else:
            result[name] = {"x": None, "y": None, "available": False}

    return result


# ---------------------------------------------------------------------------
# 建议文件读写
# ---------------------------------------------------------------------------

def load_suggestion_file(path):
    """读取建议 JSON 文件（UTF-8，仅解析不做内容校验）。

    - 文件不存在：FileNotFoundError；
    - JSON 损坏：ValueError（带文件路径）。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Suggestion file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in suggestion file {path}: {e}")


def save_suggestion_file(path, data):
    """写入建议 JSON 文件（UTF-8，indent=2，格式稳定）。

    写入前必须通过对应版本的完整校验，非法数据直接拒绝写入；
    不静默修复、不覆盖正式数据。
    """
    if not isinstance(data, dict):
        raise ValueError("suggestion data must be a dict")

    version = data.get("version")
    if version == BBOX_SUGGESTION_VERSION:
        errors = validate_bbox_suggestion_file(data)
    elif version == KEYPOINT_SUGGESTION_VERSION:
        errors = validate_keypoint_suggestion_file(data)
    else:
        raise ValueError(
            f"unknown suggestion version: {version!r} "
            f"(expected {BBOX_SUGGESTION_VERSION} or {KEYPOINT_SUGGESTION_VERSION})")

    if errors:
        raise ValueError("invalid suggestion data: " + "; ".join(errors))

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# bbox 建议文件校验
# ---------------------------------------------------------------------------

def _validate_header_identity(data, errors):
    """校验 character_id / episode_id 公共头字段。"""
    if not isinstance(data.get("character_id"), str) or not data["character_id"]:
        errors.append("character_id must be a non-empty string")
    if not isinstance(data.get("episode_id"), str) or not data["episode_id"]:
        errors.append("episode_id must be a non-empty string")


def _validate_quality_field(quality, errors, prefix):
    """校验可选 quality 字段（M03 图片质量判断，mvp1_quality_v1）。

    字段全部可选；出现时类型必须合法。不校验阈值语义（只做结构校验）。
    """
    if quality is None:
        return
    if not isinstance(quality, dict):
        errors.append(f"{prefix}.quality must be a dict")
        return
    for key in ("partial", "occluded", "low_res"):
        if key in quality and not isinstance(quality[key], bool):
            errors.append(f"{prefix}.quality.{key} must be a bool")
    for key in ("partial_prob", "occluded_prob", "score"):
        if key in quality:
            v = quality[key]
            if not _is_number(v) or not (0.0 <= v <= 1.0):
                errors.append(f"{prefix}.quality.{key} must be a number in [0.0, 1.0]")
    if "blurred" in quality and quality["blurred"] is not None \
            and not isinstance(quality["blurred"], bool):
        errors.append(f"{prefix}.quality.blurred must be a bool or null")
    if "occlusion_hints" in quality \
            and not isinstance(quality["occlusion_hints"], list):
        errors.append(f"{prefix}.quality.occlusion_hints must be a list")
    if "res" in quality:
        res = quality["res"]
        if not isinstance(res, dict):
            errors.append(f"{prefix}.quality.res must be a dict")
        else:
            for key in ("area", "min_side", "max_side"):
                if key in res and (not _is_number(res[key]) or res[key] < 0):
                    errors.append(f"{prefix}.quality.res.{key} must be a non-negative number")


def validate_bbox_suggestion_file(data):
    """校验 bbox 建议文件结构。

    版本：mvp1_bbox_suggestions_v1

    返回错误消息列表，空列表表示合法。不修改输入数据。
    """
    if not isinstance(data, dict):
        return ["top-level data must be a dict"]

    errors = []
    if data.get("version") != BBOX_SUGGESTION_VERSION:
        errors.append(f"version must be {BBOX_SUGGESTION_VERSION!r}")
    _validate_header_identity(data, errors)

    suggestions = data.get("suggestions")
    if not isinstance(suggestions, list):
        errors.append("'suggestions' must be a list")
        return errors

    seen_frame_ids = set()
    for i, s in enumerate(suggestions):
        prefix = f"suggestions[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{prefix} must be a dict")
            continue

        frame_id = s.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            errors.append(f"{prefix}.frame_id must be a non-empty string")
        if not isinstance(s.get("source_frame_id"), str) or not s["source_frame_id"]:
            errors.append(f"{prefix}.source_frame_id must be a non-empty string")
        if not isinstance(s.get("method"), str) or not s["method"]:
            errors.append(f"{prefix}.method must be a non-empty string")

        confidence = s.get("confidence")
        if not _is_number(confidence) or not (0.0 <= confidence <= 1.0):
            errors.append(f"{prefix}.confidence must be a number in [0.0, 1.0]")

        if not is_valid_status(s.get("status")):
            errors.append(f"{prefix}.status must be one of {VALID_STATUSES}")

        if not validate_bbox(s.get("bbox")):
            errors.append(f"{prefix}.bbox is invalid")

        _validate_quality_field(s.get("quality"), errors, prefix)

        if isinstance(frame_id, str):
            if frame_id in seen_frame_ids:
                errors.append(f"duplicate frame_id: {frame_id}")
            seen_frame_ids.add(frame_id)

    return errors


# ---------------------------------------------------------------------------
# keypoint 建议文件校验
# ---------------------------------------------------------------------------

def _validate_suggestion_keypoint(prefix, kp):
    """校验单个建议关键点 {"x": .., "y": .., "available": bool}。

    规则：
    - available 必须为 bool；
    - available=true：x / y 必须为数字；
    - available=false：坐标允许为空（None），给出时必须是数字。

    返回错误消息列表。
    """
    errors = []
    if not isinstance(kp, dict):
        return [f"{prefix} must be a dict"]

    if not isinstance(kp.get("available"), bool):
        return [f"{prefix}.available must be a bool"]

    if kp["available"]:
        if not _is_number(kp.get("x")) or not _is_number(kp.get("y")):
            errors.append(f"{prefix} must have numeric x and y when available=true")
    else:
        if kp.get("x") is not None and not _is_number(kp.get("x")):
            errors.append(f"{prefix}.x must be a number or null when available=false")
        if kp.get("y") is not None and not _is_number(kp.get("y")):
            errors.append(f"{prefix}.y must be a number or null when available=false")

    return errors


def validate_keypoint_suggestion_file(data):
    """校验 keypoint 建议文件结构。

    版本：mvp1_keypoint_suggestions_v1

    返回错误消息列表，空列表表示合法。不修改输入数据。
    """
    if not isinstance(data, dict):
        return ["top-level data must be a dict"]

    errors = []
    if data.get("version") != KEYPOINT_SUGGESTION_VERSION:
        errors.append(f"version must be {KEYPOINT_SUGGESTION_VERSION!r}")
    _validate_header_identity(data, errors)

    if not isinstance(data.get("keypoint_schema_id"), str) or not data["keypoint_schema_id"]:
        errors.append("keypoint_schema_id must be a non-empty string")

    suggestions = data.get("suggestions")
    if not isinstance(suggestions, list):
        errors.append("'suggestions' must be a list")
        return errors

    seen_frame_ids = set()
    for i, s in enumerate(suggestions):
        prefix = f"suggestions[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{prefix} must be a dict")
            continue

        frame_id = s.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id:
            errors.append(f"{prefix}.frame_id must be a non-empty string")
        if not isinstance(s.get("source_frame_id"), str) or not s["source_frame_id"]:
            errors.append(f"{prefix}.source_frame_id must be a non-empty string")
        if not isinstance(s.get("method"), str) or not s["method"]:
            errors.append(f"{prefix}.method must be a non-empty string")

        confidence = s.get("confidence")
        if not _is_number(confidence) or not (0.0 <= confidence <= 1.0):
            errors.append(f"{prefix}.confidence must be a number in [0.0, 1.0]")

        if not is_valid_status(s.get("status")):
            errors.append(f"{prefix}.status must be one of {VALID_STATUSES}")

        keypoints = s.get("keypoints")
        if not isinstance(keypoints, dict):
            errors.append(f"{prefix}.keypoints must be a dict")
        else:
            for name, kp in keypoints.items():
                errors.extend(
                    _validate_suggestion_keypoint(f"{prefix}.keypoints.{name}", kp))

        if isinstance(frame_id, str):
            if frame_id in seen_frame_ids:
                errors.append(f"duplicate frame_id: {frame_id}")
            seen_frame_ids.add(frame_id)

    return errors
