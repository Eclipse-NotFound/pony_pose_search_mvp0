"""Compare direction-first records with bounded optional visual context."""
import copy
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m08"))
from search_similar_poses import compute_similarity_v2
from pose_record import as_legacy_vectors, mirror_record, validate, usable_for_search


RULES = {}
for group, weights in (("front_legs", [.5, .5]), ("back_legs", [.4, .2, .4])):
    RULES[group] = {"unordered_group": True, "direction_weights": {}}
    for i, weight in enumerate(weights, 1):
        RULES[group][f"direction{i}"] = {"name": f"leg_direction{i}"}
        RULES[group]["direction_weights"][f"leg_direction{i}"] = weight


def compare(query, candidate, *, allow_mirror=False, part_weights=None,
            sample_missing_penalty=1.0, view_weight=.10, layout_weight=.05):
    """Context can reduce a direction score by at most 0.15 by default.

    Unknown context is ignored, never called a confirmed match. This is a
    transparent heuristic, not an empirically calibrated retrieval probability.
    """
    for name, record in (("query", query), ("candidate", candidate)):
        errors = validate(record)
        if errors:
            raise ValueError(f"{name}: " + "; ".join(errors))
    for name, value in (("view_weight", view_weight), ("layout_weight", layout_weight),
                        ("sample_missing_penalty", sample_missing_penalty)):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be finite in [0, 1]")
    if view_weight + layout_weight > .25:
        raise ValueError("context penalties must sum to at most 0.25; directions remain primary")
    if part_weights is not None and any(not isinstance(w, (int, float))
                                       or not math.isfinite(w) or w < 0 for w in part_weights.values()):
        raise ValueError("part weights must be finite and non-negative")
    if query["subject"]["body_profile_id"] != candidate["subject"]["body_profile_id"]:
        return None
    query_vectors = as_legacy_vectors(query)
    view_order = ["front", "front_oblique", "side", "rear_oblique", "rear"]

    def evaluate(record, mirrored):
        direction_score, note = compute_similarity_v2(
            query_vectors, as_legacy_vectors(record), RULES,
            part_weights=part_weights, sample_missing_penalty=sample_missing_penalty)
        if direction_score is None:
            return None
        view_differences = []
        for part in ("body", "head"):
            q, s = query["view"].get(part), record["view"].get(part)
            if q is not None and s is not None:
                view_differences.append(abs(view_order.index(q) - view_order.index(s)) / 4)
        qa = query.get("layout", {}).get("anchors", {})
        sa = record.get("layout", {}).get("anchors", {})
        distances = [min(1.0, math.dist(qa[k], sa[k])) for k in sorted(qa.keys() & sa.keys())]
        view_penalty = view_weight * sum(view_differences) / len(view_differences) if view_differences else 0
        layout_penalty = layout_weight * sum(distances) / len(distances) if distances else 0
        return {"score": max(0.0, direction_score - view_penalty - layout_penalty),
                "direction_score": direction_score, "view_penalty": view_penalty,
                "layout_penalty": layout_penalty, "compared_views": len(view_differences),
                "compared_layout_anchors": len(distances), "mirrored": mirrored,
                "query_available_directions": sum(usable_for_search(query, d) for d in query["directions"].values()),
                "candidate_available_directions": sum(usable_for_search(record, d) for d in record["directions"].values()),
                "leg_match_note": note}

    original = evaluate(candidate, False)
    if not allow_mirror:
        return original
    mirrored = evaluate(mirror_record(candidate), True)
    if mirrored is not None and (original is None or mirrored["score"] > original["score"] + 1e-9):
        return mirrored
    return original


def search_records(query, records, *, top_n=15, include_unreviewed=False,
                   character_id=None, form_id=None, **options):
    if top_n < 1:
        raise ValueError("top_n must be positive")
    results = []
    for record in records:
        if not include_unreviewed and record["annotation"]["review_status"] not in {
            "legacy_official", "approved", "corrected"}:
            continue
        if character_id and record["subject"]["character_id"] != character_id:
            continue
        if form_id and record["subject"]["form_id"] != form_id:
            continue
        scores = compare(query, record, **options)
        if scores is not None:
            results.append({"record_id": record["record_id"], "sample_id": record["sample_id"],
                            "subject": copy.deepcopy(record["subject"]),
                            "source": copy.deepcopy(record["source"]),
                            "annotation": copy.deepcopy(record["annotation"]),
                            "asset_access": copy.deepcopy(record["asset_access"]), **scores})
    return sorted(results, key=lambda r: (-r["score"], r["record_id"]))[:top_n]
