#!/usr/bin/env python3
"""
Pose Vector Utils — 共享纯函数，供 M06 和 M07 使用。

包含：
- unit_direction: 单位方向向量计算
- resolve_keypoint: 关键点路径解析
- compute_simple_vectors: 非腿部方向向量 (head, neck, body, tail)
- compute_leg_vectors: 腿部方向向量 (支持 v1 整腿 / v2 方向级)
- generate_vectors_for_sample: 单样本完整姿态向量

不包含任何文件 I/O、CLI 参数解析或 GUI 逻辑。
"""

import math
import hashlib
import json


def content_fingerprint(value):
    """Fingerprint parsed JSON content, independent of whitespace and key order."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derivation_errors(pose_data, keypoints_data, vector_rules):
    """Check a generated library against its declared input revisions."""
    provenance = pose_data.get("derivation")
    if not provenance:
        return []  # Legacy files have no fingerprint; absence is not freshness proof.
    errors = []
    if provenance.get("keypoints_content_sha256") != content_fingerprint(keypoints_data):
        errors.append("keypoints changed; regenerate pose vectors")
    if provenance.get("rules_content_sha256") != content_fingerprint(vector_rules):
        errors.append("vector rules changed; regenerate pose vectors")
    return errors


# ---------------------------------------------------------------------------
# 向量计算
# ---------------------------------------------------------------------------

def unit_direction(from_pt, to_pt):
    """计算从 from_pt 指向 to_pt 的单位方向向量 [dx, dy]。

    返回 None 表示长度为零，向量不可用。
    """
    for point in (from_pt, to_pt):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return None
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in point):
            return None
    dx = to_pt[0] - from_pt[0]
    dy = to_pt[1] - from_pt[1]
    length = math.hypot(dx, dy)
    if length == 0 or not math.isfinite(length):
        return None
    return [dx / length, dy / length]


# ---------------------------------------------------------------------------
# 关键点路径解析
# ---------------------------------------------------------------------------

def resolve_keypoint(keypoints, ref, leg=None, anchor_path=None):
    """
    解析关键点引用。

    ref 可以是：
      - "head.head_center" → keypoints["head"]["head_center"]
      - "current_leg.base" → leg["base"] (需传 leg 参数)
      - "anchor_keypoint" → 解析 anchor_path (如 "body.body_1")
    """
    if ref == "anchor_keypoint":
        if anchor_path is None:
            return None
        return resolve_keypoint(keypoints, anchor_path, leg, anchor_path)

    if ref.startswith("current_leg."):
        if leg is None:
            return None
        sub = ref.split(".", 1)[1]
        return leg.get(sub)

    # 绝对路径 "group.key"
    parts = ref.split(".", 1)
    if len(parts) == 2:
        group, key = parts
        group_data = keypoints.get(group)
        if isinstance(group_data, dict):
            return group_data.get(key)
        elif isinstance(group_data, list):
            return None
    return None


def _leg_point_name(ref):
    """从 'current_leg.base' 中提取 'base'。"""
    return ref.replace("current_leg.", "")


# ---------------------------------------------------------------------------
# 非腿部向量
# ---------------------------------------------------------------------------

def compute_simple_vectors(keypoints, vector_rules):
    """计算非腿部方向向量 (head, neck, body, tail)。"""
    vectors = {}
    missing = []
    available = {}

    simple_names = ["head_direction", "neck_direction", "body_direction", "tail_direction"]

    for name in simple_names:
        if name not in vector_rules:
            continue
        rule = vector_rules[name]
        from_pt = resolve_keypoint(keypoints, rule["from"])
        to_pt = resolve_keypoint(keypoints, rule["to"])

        part_name = name.replace("_direction", "")  # head, neck, body, tail
        if from_pt is None:
            missing.append(rule["from"])
            available[part_name] = False
            continue
        if to_pt is None:
            missing.append(rule["to"])
            available[part_name] = False
            continue

        vec = unit_direction(from_pt, to_pt)
        if vec is None:
            missing.append(rule["from"])
            missing.append(rule["to"])
            available[part_name] = False
            continue

        vectors[name] = vec
        available[part_name] = True

    return vectors, available, missing


# ---------------------------------------------------------------------------
# 腿部向量 (v1 整腿 / v2 方向级)
# ---------------------------------------------------------------------------

def compute_leg_vectors(keypoints, vector_rules, leg_group_name, version="v1"):
    """
    计算腿部方向向量。

    根据 vector_rules[leg_group_name] 中的定义动态生成每腿每段的方向向量。
    支持任意数量的方向段（v1/v2: 2段, v3后腿: 3段）。

    version:
      - "v1": 整腿可用性（任一关键点缺失或零长度 → 整腿 unavailable）
      - "v2": 方向级可用性（每个方向独立判断）
    """
    leg_rule = vector_rules.get(leg_group_name)
    if not leg_rule:
        return [], {}, []

    source_group = leg_rule.get("source_group", leg_group_name)
    anchor_path = leg_rule.get("anchor_keypoint")  # v1 only
    legs_data = keypoints.get(source_group, [])

    if not isinstance(legs_data, list):
        return [], {}, []

    # 收集方向定义：direction1, direction2, direction3...
    directions = []
    i = 1
    while True:
        dkey = f"direction{i}"
        if dkey in leg_rule:
            directions.append(leg_rule[dkey])
            i += 1
        else:
            break

    result_legs = []
    available = {}
    missing = []

    for leg in legs_data:
        lid = leg.get("leg_id", "")

        if version == "v2":
            # ---- v2: 方向级独立可用性 ----
            leg_result = {"leg_id": lid, "directions": {}}
            any_available = False

            for d in directions:
                dname = d["name"]
                from_pt = resolve_keypoint(keypoints, d["from"], leg, anchor_path)
                to_pt = resolve_keypoint(keypoints, d["to"], leg, anchor_path)
                dir_missing = []

                from_sub = _leg_point_name(d["from"])
                to_sub = _leg_point_name(d["to"])

                if from_pt is None:
                    dir_missing.append(f"{lid}.{from_sub}")
                if to_pt is None:
                    dir_missing.append(f"{lid}.{to_sub}")

                if dir_missing:
                    leg_result["directions"][dname] = {
                        "available": False,
                        "vector": None,
                        "missing_points": dir_missing,
                    }
                    missing.extend(dir_missing)
                else:
                    vec = unit_direction(from_pt, to_pt)
                    if vec is not None:
                        leg_result["directions"][dname] = {
                            "available": True,
                            "vector": vec,
                            "missing_points": [],
                        }
                        any_available = True
                    else:
                        leg_result["directions"][dname] = {
                            "available": False,
                            "vector": None,
                            "missing_points": [],
                        }

            available[lid] = any_available
            result_legs.append(leg_result)

        else:
            # ---- v1: 整腿可用性（现有行为，不变） ----
            leg_vecs = {"leg_id": lid}

            if anchor_path:
                leg_vecs["anchor_point"] = anchor_path

            leg_available = True
            for d in directions:
                dname = d["name"]
                from_pt = resolve_keypoint(keypoints, d["from"], leg, anchor_path)
                to_pt = resolve_keypoint(keypoints, d["to"], leg, anchor_path)

                if from_pt is None:
                    missing.append(f"{lid}.{d['from'].replace('current_leg.', '')}")
                    leg_available = False
                if to_pt is None:
                    missing.append(f"{lid}.{d['to'].replace('current_leg.', '')}")
                    leg_available = False

                if from_pt is not None and to_pt is not None:
                    vec = unit_direction(from_pt, to_pt)
                    if vec is not None:
                        leg_vecs[dname] = vec
                    else:
                        missing.append(f"{lid}.{d['from'].replace('current_leg.', '')}")
                        missing.append(f"{lid}.{d['to'].replace('current_leg.', '')}")
                        leg_available = False
                else:
                    leg_available = False

            available[lid] = leg_available
            if leg_vecs:
                result_legs.append(leg_vecs)

    return result_legs, available, missing


# ---------------------------------------------------------------------------
# 单样本完整向量
# ---------------------------------------------------------------------------

def generate_vectors_for_sample(keypoints, vector_rules, version="v1"):
    """为单个样本生成完整姿态向量。

    供 M06（数据库样本）和 M07（查询样本）共同使用。
    """
    # 简单向量
    vecs, avail, missing = compute_simple_vectors(keypoints, vector_rules)

    # 前腿
    fl, fl_avail, fl_miss = compute_leg_vectors(
        keypoints, vector_rules, "front_legs", version=version)
    for k, v in fl_avail.items():
        avail[k] = v
    missing.extend(fl_miss)
    vecs["front_legs"] = fl

    # 后腿
    bl, bl_avail, bl_miss = compute_leg_vectors(
        keypoints, vector_rules, "back_legs", version=version)
    for k, v in bl_avail.items():
        avail[k] = v
    missing.extend(bl_miss)
    vecs["back_legs"] = bl

    # 去重
    seen = set()
    unique_missing = []
    for pt in missing:
        if pt not in seen:
            seen.add(pt)
            unique_missing.append(pt)

    result = {
        "vectors": {
            "available": avail,
        },
        "missing_points": unique_missing,
    }
    result["vectors"].update(vecs)

    return result
