#!/usr/bin/env python3
"""M08 shared-library command. Pure legacy math below is retained for migration and historical regression only. Run --help for current arguments."""

import argparse
import copy
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
from pose_vector_utils import derivation_errors


# ---------------------------------------------------------------------------
# 路径构建
# ---------------------------------------------------------------------------

def _sc(episode_id): return episode_id[:3]


def build_query_vector_path(project_root, character_id, query_id, version="v1"):
    """构建查询姿态向量路径。v2 使用 _v2 后缀。"""
    base = os.path.join(
        project_root, "queries", character_id, query_id, "query_pose_vector")
    if version == "v2":
        return base + "_v2.json"
    return base + ".json"


def build_pose_vectors_path(project_root, character_id, episode_id, version="v1"):
    """构建姿态向量路径。v2 使用 _v2 后缀。"""
    base = os.path.join(
        project_root, "poses", character_id, _sc(episode_id),
        f"pose_vectors_{character_id}_{episode_id}")
    if version == "v2":
        return base + "_v2.json"
    return base + ".json"


def build_schemas_path(project_root):
    return os.path.join(project_root, "data", "meta", "keypoint_schemas.json")


def build_output_path(project_root, character_id, query_id):
    return os.path.join(
        project_root, "outputs", character_id, query_id, "top_results.csv")


def build_config_output_path(project_root, character_id, query_id):
    return os.path.join(
        project_root, "outputs", character_id, query_id, "search_run_config.json")


CSV_FIELDS = [
    "rank", "sample_id", "frame_id", "episode_id", "season", "episode",
    "character_id", "timestamp_sec", "timestamp_frame", "timestamp_text",
    "similarity_score", "frame_path", "crop_path", "match_note", "mirrored",
]


# ---------------------------------------------------------------------------
# 单方向相似度
# ---------------------------------------------------------------------------

def direction_similarity(q, s):
    """方向相似度；归一化有效输入，拒绝零长度或非有限向量。"""
    def normalized(value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in value):
            return None
        length = math.hypot(*value)
        if length == 0 or not math.isfinite(length):
            return None
        return [v / length for v in value]

    q, s = normalized(q), normalized(s)
    if q is None or s is None:
        return None
    dot = q[0] * s[0] + q[1] * s[1]
    sim = (dot + 1.0) / 2.0
    return max(0.0, min(1.0, sim))


# ---------------------------------------------------------------------------
# 部件得分
# ---------------------------------------------------------------------------

def simple_component_score(q_vectors, s_vectors, comp_name):
    """计算普通部件（head/neck/body/tail）的相似度。"""
    dname = f"{comp_name}_direction"
    qv = q_vectors.get(dname)
    sv = s_vectors.get(dname)
    if qv is None or sv is None:
        return None
    return direction_similarity(qv, sv)


def leg_group_score(q_vectors, s_vectors, group_name, vector_rules):
    """
    计算腿组得分，含无序匹配。

    返回 (score, note_suffix) 或 (None, reason)
    """
    leg_rule = vector_rules.get(group_name)
    if not leg_rule:
        return None, "no rule"

    source_group = leg_rule.get("source_group", group_name)
    weights = leg_rule.get("direction_weights", {})
    unordered = leg_rule.get("unordered_group", False)

    # 收集方向定义
    directions = []
    i = 1
    while f"direction{i}" in leg_rule:
        directions.append(leg_rule[f"direction{i}"])
        i += 1

    if not directions or not weights:
        return None, "no directions/weights"

    q_legs = q_vectors.get(group_name, [])
    s_legs = s_vectors.get(group_name, [])

    if not isinstance(q_legs, list) or not isinstance(s_legs, list):
        return None, "invalid leg data"

    # 单腿得分函数
    def single_leg_score(q_leg, s_leg):
        if q_leg is None or s_leg is None:
            return None
        total = 0.0
        w_total = 0.0
        for d in directions:
            dname = d["name"]
            w = weights.get(dname, 0)
            if w <= 0:
                continue
            qv = q_leg.get(dname)
            sv = s_leg.get(dname)
            if qv is None or sv is None:
                return None  # 任一段缺失则整腿不可用
            sim = direction_similarity(qv, sv)
            total += sim * w
            w_total += w
        if w_total == 0:
            return None
        return total / w_total  # 归一化

    q_available = q_vectors.get("available", {})
    s_available = s_vectors.get("available", {})

    # 收集可用的腿（available=true 且有向量数据）
    q_usable = []
    for leg in q_legs:
        lid = leg.get("leg_id", "")
        if q_available.get(lid, False) and any(
            leg.get(d["name"]) is not None for d in directions
        ):
            q_usable.append(leg)

    s_usable = []
    for leg in s_legs:
        lid = leg.get("leg_id", "")
        if s_available.get(lid, False) and any(
            leg.get(d["name"]) is not None for d in directions
        ):
            s_usable.append(leg)

    if not q_usable or not s_usable:
        return None, "no usable legs"

    nq, ns = len(q_usable), len(s_usable)

    if nq == 1 and ns >= 1:
        # 查询只有一条可用腿，选得分最高的样本腿
        best = max(
            (single_leg_score(q_usable[0], sl) for sl in s_usable
             if single_leg_score(q_usable[0], sl) is not None),
            default=None
        )
        if best is None:
            return None, "no valid pair"
        return best, "partial match"

    if ns == 1 and nq >= 1:
        best = max(
            (single_leg_score(ql, s_usable[0]) for ql in q_usable
             if single_leg_score(ql, s_usable[0]) is not None),
            default=None
        )
        if best is None:
            return None, "no valid pair"
        return best, "partial match"

    # 多条腿 → 无序匹配（取两种排列的最高分）
    if unordered and nq >= 2 and ns >= 2:
        # 方案 A: 0↔0, 1↔1
        score_a1 = single_leg_score(q_usable[0], s_usable[0])
        score_a2 = single_leg_score(q_usable[1], s_usable[1])
        # 方案 B: 0↔1, 1↔0
        score_b1 = single_leg_score(q_usable[0], s_usable[1])
        score_b2 = single_leg_score(q_usable[1], s_usable[0])

        valid_a = (score_a1 is not None and score_a2 is not None)
        valid_b = (score_b1 is not None and score_b2 is not None)

        if valid_a and valid_b:
            avg_a = (score_a1 + score_a2) / 2
            avg_b = (score_b1 + score_b2) / 2
            if avg_b > avg_a:
                return avg_b, "unordered match (B)"
            return avg_a, "unordered match (A)"
        elif valid_a:
            return (score_a1 + score_a2) / 2, "unordered match (A only)"
        elif valid_b:
            return (score_b1 + score_b2) / 2, "unordered match (B only)"

    # 非无序或腿数不足 → 按 leg_id 匹配
    score_sum = 0.0
    count = 0
    for ql in q_usable:
        for sl in s_usable:
            if ql.get("leg_id") == sl.get("leg_id"):
                s = single_leg_score(ql, sl)
                if s is not None:
                    score_sum += s
                    count += 1
                break
    if count == 0:
        return None, "no leg_id match"
    return score_sum / count, "leg_id matched"


# ---------------------------------------------------------------------------
# 总相似度（加权版）
# ---------------------------------------------------------------------------

def compute_similarity(query_vecs, sample_vecs, vector_rules,
                       part_weights=None, sample_missing_penalty=1.0):
    """
    计算查询与样本的加权总相似度。

    part_weights: {head, neck, body, tail, front_legs, back_legs} 权重
    sample_missing_penalty: 0.0~1.0

    返回 (total_score, match_note) 或 (None, reason)。
    """
    if part_weights is None:
        part_weights = {}

    q_avail = query_vecs.get("available", {})
    s_avail = sample_vecs.get("available", {})

    numerator = 0.0
    denominator = 0.0
    notes = []
    component_details = {}

    # 普通部件
    for comp in ["head", "neck", "body", "tail"]:
        w = part_weights.get(comp, 1.0)
        q_ok = q_avail.get(comp, False)
        s_ok = s_avail.get(comp, False)

        if not q_ok:
            notes.append(f"{comp}: query unavailable")
            continue

        if s_ok:
            sim = simple_component_score(query_vecs, sample_vecs, comp)
            if sim is not None:
                numerator += sim * w
                denominator += w
                component_details[comp] = sim
                notes.append(f"{comp}: {sim:.3f}")
            else:
                # 查询可用、样本声称可用但无向量 → 实际不可用 → 惩罚
                denominator += w * sample_missing_penalty
                notes.append(f"{comp}: vector missing (penalized)")
        else:
            # 查询可用、样本不可用 → 惩罚
            denominator += w * sample_missing_penalty
            notes.append(f"{comp}: sample missing (penalized)")

    # 腿部
    for group in ["front_legs", "back_legs"]:
        w = part_weights.get(group, 1.0)
        leg_result = leg_group_score_weighted(
            query_vecs, sample_vecs, group, vector_rules,
            group_weight=w, penalty=sample_missing_penalty,
        )
        if leg_result:
            num_add, den_add, leg_note = leg_result
            numerator += num_add
            denominator += den_add
            notes.append(f"{group}: {leg_note}")
        else:
            notes.append(f"{group}: no usable legs")

    if denominator == 0:
        return None, "no comparable components"

    total = numerator / denominator
    # 生成简洁的 match_note
    detail_str = " | ".join(
        f"{k}={v:.2f}" for k, v in component_details.items()
    ) if component_details else ""
    missing_str = "; ".join(n for n in notes if "missing" in n or "unavailable" in n or "penalized" in n)
    match_note = (detail_str + " | " + missing_str) if missing_str else detail_str

    return total, match_note


def leg_group_score_weighted(query_vecs, sample_vecs, group_name, vector_rules,
                              group_weight=1.0, penalty=1.0):
    """
    腿组加权得分。

    返回 (numerator_add, denominator_add, note) 或 None。
    """
    leg_rule = vector_rules.get(group_name)
    if not leg_rule:
        return None

    source_group = leg_rule.get("source_group", group_name)
    weights = leg_rule.get("direction_weights", {})
    unordered = leg_rule.get("unordered_group", False)

    directions = []
    i = 1
    while f"direction{i}" in leg_rule:
        directions.append(leg_rule[f"direction{i}"])
        i += 1
    if not directions or not weights:
        return None

    q_avail = query_vecs.get("available", {})
    s_avail = sample_vecs.get("available", {})
    q_legs = query_vecs.get(group_name, [])
    s_legs = sample_vecs.get(group_name, [])

    # 单腿得分（内部归一化到 [0,1]）
    def single_leg_score(q_leg, s_leg):
        if q_leg is None or s_leg is None:
            return None
        total = 0.0
        w_total = 0.0
        for d in directions:
            dname = d["name"]
            w = weights.get(dname, 0)
            if w <= 0:
                continue
            qv = q_leg.get(dname)
            sv = s_leg.get(dname)
            if qv is None or sv is None:
                return None
            total += direction_similarity(qv, sv) * w
            w_total += w
        if w_total == 0:
            return None
        return total / w_total

    # 收集查询可用腿和样本可用腿
    q_usable = []
    for leg in q_legs:
        lid = leg.get("leg_id", "")
        if q_avail.get(lid, False):
            q_usable.append(leg)

    s_usable = []
    for leg in s_legs:
        lid = leg.get("leg_id", "")
        if s_avail.get(lid, False):
            s_usable.append(leg)

    nq = len(q_usable)
    ns = len(s_usable)

    if nq == 0:
        return None  # 查询无可用腿 → 不参与

    leg_unit_weight = group_weight / nq
    num = 0.0
    den = 0.0

    if ns == 0:
        # 样本无可用腿 → 全部惩罚
        den += group_weight * penalty
        return num, den, f"all {nq} query legs penalized"

    # 无序匹配
    if unordered and nq >= 2 and ns >= 2:
        # 两种排列
        a1 = single_leg_score(q_usable[0], s_usable[0])
        a2 = single_leg_score(q_usable[1], s_usable[1])
        b1 = single_leg_score(q_usable[0], s_usable[1])
        b2 = single_leg_score(q_usable[1], s_usable[0])

        def pair_score(s1, s2):
            cnt = 0
            sc = 0.0
            if s1 is not None:
                sc += s1
                cnt += 1
            if s2 is not None:
                sc += s2
                cnt += 1
            return sc, cnt

        sc_a, cnt_a = pair_score(a1, a2)
        sc_b, cnt_b = pair_score(b1, b2)

        if cnt_a == 0 and cnt_b == 0:
            den += group_weight * penalty
            return 0.0, den, "no valid leg pairs"

        # 选较优排列
        if cnt_b > cnt_a or (cnt_b == cnt_a and sc_b > sc_a):
            best_score_sum = sc_b
            matched_count = cnt_b
            note = "unordered (B)"
        else:
            best_score_sum = sc_a
            matched_count = cnt_a
            note = "unordered (A)"

        # 匹配腿贡献
        num += best_score_sum * leg_unit_weight
        den += matched_count * leg_unit_weight

        # 未匹配查询腿惩罚
        unmatched = nq - matched_count
        if unmatched > 0:
            den += unmatched * leg_unit_weight * penalty
            note += f" +{unmatched} penalized"
    else:
        # 按 leg_id 匹配
        matched = 0
        for ql in q_usable:
            found = False
            for sl in s_usable:
                if ql.get("leg_id") == sl.get("leg_id"):
                    s = single_leg_score(ql, sl)
                    if s is not None:
                        num += s * leg_unit_weight
                        den += leg_unit_weight
                        matched += 1
                    found = True
                    break
            if not found:
                den += leg_unit_weight * penalty
        note = f"leg_id matched {matched}/{nq}"

    if den == 0:
        return None

    return num, den, note


# ---------------------------------------------------------------------------
# v2 方向级评分
# ---------------------------------------------------------------------------

def _get_v2_direction(leg, dname):
    """从 v2 腿结构中提取方向的 (available, vector)。v1 返回 (True, vec) 或 (True, None)。"""
    if "directions" in leg:
        d = leg["directions"].get(dname)
        if d:
            return d["available"], d["vector"]
        return False, None
    # v1 fallback: 腿级直接存向量
    vec = leg.get(dname)
    return (True, vec) if vec is not None else (False, None)


def _score_direction_pair(q_avail, q_vec, s_avail, s_vec, weight, penalty):
    """单个方向的 (numerator_add, denominator_add)。"""
    if not q_avail:
        return 0.0, 0.0  # 查询不可用: 不比较，不惩罚
    if s_avail:
        sim = direction_similarity(q_vec, s_vec)
        if sim is not None:
            return sim * weight, weight
        # 查询有向量但样本向量为 None → 样本缺失
        return 0.0, weight * penalty
    else:
        return 0.0, weight * penalty


def score_leg_pair_v2(q_leg, s_leg, directions, weights, penalty):
    """
    v2 单条腿配对评分：遍历所有 schema 方向，每个方向独立评分。

    返回 (numerator, denominator, valid_dirs, missing_dirs)。
    """
    num = 0.0
    den = 0.0
    valid = 0
    missing = 0
    for d in directions:
        dname = d["name"]
        w = weights.get(dname, 0)
        if w <= 0:
            continue
        q_avail, q_vec = _get_v2_direction(q_leg, dname)
        s_avail, s_vec = _get_v2_direction(s_leg, dname)
        n_add, d_add = _score_direction_pair(q_avail, q_vec, s_avail, s_vec, w, penalty)
        num += n_add
        den += d_add
        if q_avail and s_avail and s_vec is not None:
            valid += 1
        elif q_avail and not s_avail:
            missing += 1
    return num, den, valid, missing


def score_leg_group_v2(q_legs, s_legs, group_name, vector_rules, group_weight, penalty):
    """
    v2 腿组评分：无序一致配对的腿组。

    遍历两种排列方案（原序 / 交换序），选择得分更高的方案。
    每条查询腿的所有方向必须与同一样本腿比较（禁止跨腿拼接）。

    返回 (numerator, denominator, note) 或 None。
    """
    if group_weight <= 0:
        return None
    leg_rule = vector_rules.get(group_name)
    if not leg_rule:
        return None

    weights = leg_rule.get("direction_weights", {})
    unordered = leg_rule.get("unordered_group", False)

    directions = []
    i = 1
    while f"direction{i}" in leg_rule:
        directions.append(leg_rule[f"direction{i}"])
        i += 1
    if not directions or not weights:
        return None

    # 收集有至少一个查询可用方向的腿
    def has_any_q_available(leg):
        for d in directions:
            dname = d["name"]
            if weights.get(dname, 0) <= 0:
                continue
            q_avail, _ = _get_v2_direction(leg, dname)
            if q_avail:
                return True
        return False

    def has_any_s_available(leg):
        for d in directions:
            dname = d["name"]
            if weights.get(dname, 0) <= 0:
                continue
            s_avail, _ = _get_v2_direction(leg, dname)
            if s_avail:
                return True
        return False

    q_usable = [l for l in q_legs if has_any_q_available(l)]
    s_usable = [l for l in s_legs if has_any_s_available(l)]

    nq = len(q_usable)
    ns = len(s_usable)

    if nq == 0:
        return None  # 查询无可用腿 → 不参与

    # 组权重由所有查询腿共享，不能因两条腿而自动翻倍。
    direction_total = sum(weights.get(d["name"], 0) for d in directions
                          if weights.get(d["name"], 0) > 0)
    group_scale = group_weight / (nq * direction_total)

    if ns == 0:
        # 样本无可用腿 → 全部查询方向按缺失惩罚
        total_den = 0.0
        for ql in q_usable:
            for d in directions:
                dname = d["name"]
                w = weights.get(dname, 0)
                if w <= 0:
                    continue
                q_avail, _ = _get_v2_direction(ql, dname)
                if q_avail:
                    total_den += w * penalty
        if total_den == 0:
            return None
        return 0.0, total_den * group_scale, f"all query legs penalized (no sample legs)"

    # 辅助：为一种配对方案计算总分
    def evaluate_assignment(assignment_pairs):
        """assignment_pairs: [(q_leg, s_leg), ...]"""
        total_num = 0.0
        total_den = 0.0
        total_valid = 0
        total_missing = 0
        for ql, sl in assignment_pairs:
            n, d, v, m = score_leg_pair_v2(ql, sl, directions, weights, penalty)
            total_num += n
            total_den += d
            total_valid += v
            total_missing += m
        return total_num, total_den, total_valid, total_missing

    if unordered and nq >= 2 and ns >= 2:
        # 方案 A: 原顺序
        a_assign = [(q_usable[0], s_usable[0]), (q_usable[1], s_usable[1])]
        # 方案 B: 交换顺序
        b_assign = [(q_usable[0], s_usable[1]), (q_usable[1], s_usable[0])]

        a_num, a_den, a_valid, a_missing = evaluate_assignment(a_assign)
        b_num, b_den, b_valid, b_missing = evaluate_assignment(b_assign)

        # 按包含缺失惩罚的得分选择；平分保持原序。
        def score_or_zero(n, d):
            return n / d if d > 0 else 0.0

        a_score = score_or_zero(a_num, a_den)
        b_score = score_or_zero(b_num, b_den)

        # 选更优方案：den > 0 优先，再比得分
        a_ok = a_den > 0
        b_ok = b_den > 0

        if a_ok and b_ok:
            if b_score > a_score + 1e-9:
                num, den, valid, missing = b_num, b_den, b_valid, b_missing
                note = f"swapped: {valid}d cmp, {missing}d m"
            else:
                num, den, valid, missing = a_num, a_den, a_valid, a_missing
                note = f"original: {valid}d cmp, {missing}d m"
        elif b_ok:
            num, den, valid, missing = b_num, b_den, b_valid, b_missing
            note = f"swapped only: {valid}d cmp, {missing}d m"
        elif a_ok:
            num, den, valid, missing = a_num, a_den, a_valid, a_missing
            note = f"original only: {valid}d cmp, {missing}d m"
        else:
            return None
    elif unordered and nq >= 2 and ns == 1:
        # 一个样本腿只能分配一次，其余查询腿仍计缺失惩罚。
        empty_leg = {"directions": {}}
        choices = []
        for matched_index in range(nq):
            pairs = [(ql, s_usable[0] if i == matched_index else empty_leg)
                     for i, ql in enumerate(q_usable)]
            n, d, v, m = evaluate_assignment(pairs)
            if d > 0:
                choices.append((n / d, n, d, v, m))
        if not choices:
            return None
        _, num, den, valid, missing = max(choices, key=lambda item: item[0])
        note = f"1-sample leg: {valid}d cmp, {missing}d m"
    elif unordered and nq == 1 and ns >= 1:
        # 一条查询腿：选最佳样本腿
        best_num = best_den = 0.0
        best_valid = best_missing = 0
        best_score = -1.0
        for sl in s_usable:
            n, d, v, m = score_leg_pair_v2(q_usable[0], sl, directions, weights, penalty)
            if d > 0:
                s = n / d
                if s > best_score + 1e-9:
                    best_score = s
                    best_num, best_den = n, d
                    best_valid, best_missing = v, m
        if best_den == 0:
            return None
        num, den, valid, missing = best_num, best_den, best_valid, best_missing
        note = f"1-query leg: {valid}d cmp, {missing}d m"
    else:
        # 按 leg_id 匹配
        total_num = 0.0
        total_den = 0.0
        total_valid = 0
        total_missing = 0
        for ql in q_usable:
            matched = False
            for sl in s_usable:
                if ql.get("leg_id") == sl.get("leg_id"):
                    n, d, v, m = score_leg_pair_v2(ql, sl, directions, weights, penalty)
                    total_num += n
                    total_den += d
                    total_valid += v
                    total_missing += m
                    matched = True
                    break
            if not matched:
                # 查询腿无对应样本腿 → 所有查询可用方向按缺失惩罚
                for d in directions:
                    dname = d["name"]
                    w = weights.get(dname, 0)
                    if w <= 0:
                        continue
                    q_avail, _ = _get_v2_direction(ql, dname)
                    if q_avail:
                        total_den += w * penalty
        if total_den == 0:
            return None
        num, den, valid, missing = total_num, total_den, total_valid, total_missing
        note = f"leg_id: {valid}d cmp, {missing}d m"

    if den == 0:
        return None
    return num * group_scale, den * group_scale, note


def compute_similarity_v2(query_vecs, sample_vecs, vector_rules,
                           part_weights=None, sample_missing_penalty=1.0):
    """
    v2 方向级加权总相似度。

    非腿部：与 v1 相同。
    腿部：使用 v2 方向级独立评分 + 一致配对。
    """
    if part_weights is None:
        part_weights = {}

    q_avail = query_vecs.get("available", {})
    s_avail = sample_vecs.get("available", {})

    numerator = 0.0
    denominator = 0.0
    notes = []
    component_details = {}

    # 普通部件（与 v1 相同）
    for comp in ["head", "neck", "body", "tail"]:
        w = part_weights.get(comp, 1.0)
        q_ok = q_avail.get(comp, False)
        s_ok = s_avail.get(comp, False)

        if not q_ok:
            notes.append(f"{comp}: query unavailable")
            continue

        if s_ok:
            sim = simple_component_score(query_vecs, sample_vecs, comp)
            if sim is not None:
                numerator += sim * w
                denominator += w
                component_details[comp] = sim
            else:
                denominator += w * sample_missing_penalty
        else:
            denominator += w * sample_missing_penalty

    # 腿部 v2
    for group in ["front_legs", "back_legs"]:
        w = part_weights.get(group, 1.0)
        q_legs = query_vecs.get(group, [])
        s_legs = sample_vecs.get(group, [])

        result = score_leg_group_v2(
            q_legs, s_legs, group, vector_rules, w, sample_missing_penalty)
        if result:
            num_add, den_add, leg_note = result
            numerator += num_add
            denominator += den_add
            notes.append(f"{group}: {leg_note}")
        else:
            notes.append(f"{group}: no usable legs")

    if denominator == 0:
        return None, "no comparable components"

    total = numerator / denominator
    detail_str = " | ".join(
        f"{k}={v:.2f}" for k, v in component_details.items()
    ) if component_details else ""
    note_str = "; ".join(notes)
    match_note = (detail_str + " | " + note_str) if detail_str else note_str

    return total, match_note


# ---------------------------------------------------------------------------
# 搜索主逻辑
# ---------------------------------------------------------------------------

def mirror_vectors(vectors):
    """镜像整个候选方向；不交换腿身份，不修改原记录。"""
    mirrored = copy.deepcopy(vectors)
    for key in ("head_direction", "neck_direction", "body_direction", "tail_direction"):
        if mirrored.get(key) is not None:
            mirrored[key][0] = -mirrored[key][0]
    for group in ("front_legs", "back_legs"):
        for leg in mirrored.get(group, []):
            if "directions" in leg:
                for direction in leg["directions"].values():
                    if direction.get("vector") is not None:
                        direction["vector"][0] = -direction["vector"][0]
            else:
                for name, vec in leg.items():
                    if name.startswith("leg_direction") and vec is not None:
                        vec[0] = -vec[0]
    return mirrored


def search(query_data, pose_data, vector_rules, top_n=10,
           part_weights=None, sample_missing_penalty=1.0, version="v1",
           allow_mirror=False):
    """执行搜索，返回按相似度降序的结果列表。"""
    q_vecs = query_data.get("vectors", {})
    results = []
    character_id = pose_data.get("character_id", "")

    for sample in pose_data.get("items", []):
        s_vecs = sample.get("vectors", {})
        scorer = compute_similarity_v2 if version == "v2" else compute_similarity
        score, note = scorer(
            q_vecs, s_vecs, vector_rules,
            part_weights=part_weights,
            sample_missing_penalty=sample_missing_penalty,
        )
        mirrored = False
        if allow_mirror:
            flipped_score, flipped_note = scorer(
                q_vecs, mirror_vectors(s_vecs), vector_rules,
                part_weights=part_weights,
                sample_missing_penalty=sample_missing_penalty,
            )
            if flipped_score is not None and (score is None or flipped_score > score + 1e-9):
                score, note = flipped_score, "左右翻转后匹配 | " + flipped_note
                mirrored = True

        if score is not None:
            fid = sample.get("frame_id", "")
            sid = sample.get("sample_id", "")
            # 每样本独立的 episode 信息
            eid = sample.get("_episode_id", pose_data.get("episode_id", ""))
            sc = eid[:3] if len(eid) >= 3 else "s01"
            ec = eid[3:] if len(eid) >= 5 else "e15"
            frame_path = f"frames/{sc}/{ec}/{fid}.png" if fid else ""
            crop_path = (f"crops/{character_id}/{sc}/{ec}/{sid}.png"
                         if sid and character_id else "")

            results.append({
                "sample_id": sid,
                "frame_id": fid,
                "episode_id": eid,
                "season": "",  # 由 write_results_csv 填充
                "episode": "",
                "character_id": character_id,
                "timestamp_sec": sample.get("timestamp_sec", 0),
                "timestamp_frame": 0,
                "timestamp_text": "",
                "similarity_score": round(score, 6),
                "frame_path": frame_path,
                "crop_path": crop_path,
                "match_note": note,
                "mirrored": mirrored,
            })

    # 排序：降序，相同分数保持原序（稳定排序）
    results.sort(key=lambda r: r["similarity_score"], reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def write_results_csv(results, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for i, r in enumerate(results, start=1):
            r["rank"] = i
            eid = r.get("episode_id", "")
            # s01e15 → season=1, episode=15
            r["season"] = int(eid[1:3]) if len(eid) >= 3 else 1
            r["episode"] = int(eid[4:6]) if len(eid) >= 6 else 15
            r["timestamp_text"] = _sec_to_timestamp(int(r.get("timestamp_sec", 0)))
            writer.writerow(r)
    return len(results)


def _sec_to_timestamp(sec):
    h, m = divmod(sec, 3600)
    m, s = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def discover_all_episode_ids(project_root, character_id, version="v1"):
    """发现所有可用剧集的 pose_vectors 文件，返回排序后的 episode_id 列表。"""
    poses_dir = os.path.join(project_root, "poses", character_id)
    if not os.path.isdir(poses_dir):
        return []
    episode_ids = []
    for season_dir in sorted(os.listdir(poses_dir)):
        season_path = os.path.join(poses_dir, season_dir)
        if not os.path.isdir(season_path):
            continue
        for fname in sorted(os.listdir(season_path)):
            prefix = f"pose_vectors_{character_id}_"
            if not fname.startswith(prefix):
                continue
            if version == "v2":
                if not fname.endswith("_v2.json"):
                    continue
                middle = fname[len(prefix):-len("_v2.json")]
            else:
                # v1: 匹配 .json 但排除 _v2.json
                if not fname.endswith(".json") or fname.endswith("_v2.json"):
                    continue
                middle = fname[len(prefix):-len(".json")]
            episode_ids.append(middle)
    return episode_ids


def load_pose_file(filepath):
    """加载单个姿态向量文件，返回 (episode_id, data) 或 None。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        eid = data.get("episode_id", "")
        return eid, data
    except (json.JSONDecodeError, IOError) as e:
        print(f"ERROR: Failed to load {filepath}: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]/'common'))
    from workflow.cli import run_module
    return run_module('M08')

if __name__=='__main__':main()
