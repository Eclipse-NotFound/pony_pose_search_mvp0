"""Direction-first pose observations, independent of models and file storage.

An observation is one annotation revision of one subject in one image view.
Points are optional evidence; they are not required to represent directions.
"""
import copy
import hashlib
import math

FORMAT = "pose_record_v1"
DEFINITION = "pony_body14_v1"
VIEWS = {"front", "front_oblique", "side", "rear_oblique", "rear"}
POINTS = {
    "head.center": ("head", "head_center"),
    "head.forward_reference": ("head", "head_front"),
    "neck.reference": ("head", "neck"),
    "body.front": ("body", "body_1"), "body.rear": ("body", "body_2"),
    "tail.root": ("tail", "tail_base"), "tail.forward_reference": ("tail", "tail_end"),
}
for group, count in (("front", 2), ("hind", 3)):
    old_group = "front_legs" if group == "front" else "back_legs"
    old_prefix = "front_leg" if group == "front" else "back_leg"
    points = [("root", "base"), ("bend", "mid"), ("hoof", "end")] if count == 2 else [
        ("root", "base"), ("upper_bend", "knee"), ("lower_bend", "mid"), ("hoof", "end")]
    for index in (1, 2):
        for new, old in points:
            POINTS[f"{group}.{index}.{new}"] = (old_group, f"{old_prefix}_{index}", old)

EDGES = {
    "head": ("head.center", "head.forward_reference"),
    "neck": ("body.front", "neck.reference"),
    "body": ("body.front", "body.rear"),
    "tail": ("tail.root", "tail.forward_reference"),
}
for group, names in (("front", ["root", "bend", "hoof"]),
                     ("hind", ["root", "upper_bend", "lower_bend", "hoof"])):
    for index in (1, 2):
        for segment, (start, end) in enumerate(zip(names, names[1:]), 1):
            EDGES[f"{group}.{index}.{segment}"] = (f"{group}.{index}.{start}", f"{group}.{index}.{end}")


def finite_xy(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in value))


def unit(value):
    if not finite_xy(value):
        return None
    length = math.hypot(*value)
    return [v / length for v in value] if length > 0 and math.isfinite(length) else None


def flatten_legacy_points(keypoints):
    result = {}
    for name, path in POINTS.items():
        if len(path) == 2:
            value = keypoints.get(path[0], {}).get(path[1])
        else:
            leg = next((leg for leg in keypoints.get(path[0], []) if leg.get("leg_id") == path[1]), {})
            value = leg.get(path[2])
        result[name] = copy.deepcopy(value)
    return result


def layout_from_points(points):
    front, rear = points.get("body.front"), points.get("body.rear")
    if not finite_xy(front) or not finite_xy(rear):
        return {"reference": "body_midpoint_and_length", "anchors": {}}
    scale = math.dist(front, rear)
    # Tiny torso projection is not a reliable ruler (e.g. a front view).
    if scale < 2:
        return {"reference": "body_midpoint_and_length", "anchors": {}}
    center = [(front[i] + rear[i]) / 2 for i in (0, 1)]
    raw = {"head": points.get("head.center")}
    for group in ("front", "hind"):
        a, b = points.get(f"{group}.1.hoof"), points.get(f"{group}.2.hoof")
        if finite_xy(a) and finite_xy(b):
            # Symmetric group centers remain valid under whole-leg assignment.
            raw[f"{group}_feet"] = [(a[i] + b[i]) / 2 for i in (0, 1)]
    return {"reference": "body_midpoint_and_length", "anchors": {
        name: [(point[i] - center[i]) / scale for i in (0, 1)]
        for name, point in raw.items() if finite_xy(point)}}


def from_legacy(sample, *, source_path, source_sha256, origin="human",
                review_status="legacy_official", image_size=None):
    """Convert without inventing visibility, view labels or review history."""
    old_character = sample.get("character_id", "twilight_unicorn")
    if old_character == "twilight_unicorn":
        character, form, wings = "twilight_sparkle", "unicorn", False
    elif old_character in ("twilight_princess", "twilight_alicorn"):
        character, form, wings = "twilight_sparkle", "alicorn", True
    else:
        character, form, wings = old_character, "unknown", None
    sample_id = sample.get("sample_id") or sample.get("query_id") or sample["frame_id"]
    points = flatten_legacy_points(sample.get("keypoints", {}))
    directions = {}
    for name, (start, end) in EDGES.items():
        a, b = points[start], points[end]
        vector = unit([b[i] - a[i] for i in (0, 1)]) if finite_xy(a) and finite_xy(b) else None
        invalid = (a is not None and not finite_xy(a)) or (b is not None and not finite_xy(b))
        reason = None if vector is not None else (
            "invalid_geometry" if invalid or (a is not None and b is not None) else "legacy_unspecified")
        directions[name] = {"value": vector, "support": "legacy_reference" if vector else "unknown",
                            "visibility": "unknown", "missing_reason": reason, "confidence": None}
    label_token = hashlib.sha256((source_sha256 + ":" + sample_id).encode()).hexdigest()[:24]
    return {
        "schema_version": FORMAT, "pose_definition_id": DEFINITION,
        "record_id": "annotation_" + label_token, "sample_id": sample_id,
        "subject": {"character_id": character, "form_id": form, "body_profile_id": "pony_quadruped",
                    "legacy_character_id": old_character,
                    "instance_id": sample_id, "track_id": None},
        "source": {"kind": "query_image" if "query_id" in sample else "episode_frame",
                   "episode_id": sample.get("episode_id"), "frame_id": sample.get("frame_id"),
                   "timestamp_sec": sample.get("timestamp_sec"), "absolute_frame_index": None,
                   "timebase": None, "scene_id": None, "asset_instance_path": None,
                   "image_path": sample.get("crop_path", sample.get("query_image_path")),
                   "frame_path": sample.get("frame_path"), "image_sha256": None},
        "coordinates": {"space": "image_pixels", "x_axis": "right", "y_axis": "down",
                        "image_size": image_size, "to_source_transform": None},
        "annotation": {"origin": origin, "review_status": review_status, "reviewed_by": None,
                       "source_path": source_path, "source_sha256": source_sha256,
                       "method": "legacy_points_conversion", "notes": sample.get("note", "")},
        "asset_access": {"complete_character": "unknown", "evidence_ref": None},
        "view": {"body": None, "head": None}, "directions": directions,
        "reference_points": points, "layout": layout_from_points(points),
        "leg_identity": {f"{g}.{i}": {"depth": "unknown", "anatomical_side": "unknown", "asset_path": None}
                         for g in ("front", "hind") for i in (1, 2)},
        "optional_parts": {"wings": {"present": wings, "annotation": None}},
    }


def validate(record):
    errors = []
    if record.get("schema_version") != FORMAT:
        errors.append("unsupported schema_version")
    if record.get("pose_definition_id") != DEFINITION:
        errors.append("unsupported pose_definition_id")
    for field in ("record_id", "sample_id"):
        if not isinstance(record.get(field), str) or not record[field]:
            errors.append(f"{field}: required")
    for section in ("subject", "source", "coordinates", "annotation", "asset_access", "view", "directions"):
        if not isinstance(record.get(section), dict):
            errors.append(f"{section}: required object")
    if errors:
        return errors
    for field in ("character_id", "form_id", "body_profile_id", "instance_id"):
        if not record["subject"].get(field):
            errors.append(f"subject.{field}: required")
    for field in ("origin", "review_status", "source_path", "source_sha256"):
        if not record["annotation"].get(field):
            errors.append(f"annotation.{field}: required")
    if record["annotation"].get("origin") not in {"human", "agent", "model", "asset", "query"}:
        errors.append("annotation.origin: invalid")
    if record["annotation"].get("review_status") not in {
        "unreviewed", "approved", "corrected", "rejected", "legacy_official", "query_input"}:
        errors.append("annotation.review_status: invalid")
    coordinates = record["coordinates"]
    if coordinates.get("space") != "image_pixels" or coordinates.get("x_axis") != "right" or coordinates.get("y_axis") != "down":
        errors.append("coordinates: expected image pixels, x right, y down")
    size = coordinates.get("image_size")
    if size is not None and (not finite_xy(size) or any(v <= 0 for v in size)):
        errors.append("coordinates.image_size: invalid")
    access = record["asset_access"]
    if access.get("complete_character") not in {"unknown", "unavailable", "verified"}:
        errors.append("asset_access.complete_character: invalid status")
    if access.get("complete_character") == "verified" and not access.get("evidence_ref"):
        errors.append("verified complete character requires evidence_ref")
    if set(record["directions"]) != set(EDGES):
        errors.append("directions must contain the 14 defined body directions")
    for name, direction in record["directions"].items():
        if not isinstance(direction, dict):
            errors.append(f"{name}: direction must be an object")
            continue
        value = direction.get("value")
        if value is not None and (not finite_xy(value) or abs(math.hypot(*value) - 1) > 1e-6):
            errors.append(f"{name}: expected finite unit vector")
        if value is None and not direction.get("missing_reason"):
            errors.append(f"{name}: missing value requires a reason")
        if direction.get("missing_reason") not in {None, "not_annotated", "not_discernible", "occluded",
                                                    "out_of_frame", "not_applicable", "not_drawn",
                                                    "invalid_geometry", "legacy_unspecified"}:
            errors.append(f"{name}: invalid missing reason")
        if value is not None and direction.get("missing_reason") is not None:
            errors.append(f"{name}: present value cannot have a missing reason")
        if direction.get("support") not in {"observed", "inferred", "asset_geometry", "legacy_reference", "unknown"}:
            errors.append(f"{name}: invalid support")
        if value is not None and direction.get("support") == "unknown":
            errors.append(f"{name}: present value requires evidence support")
        if direction.get("visibility") not in {"visible", "occluded", "out_of_frame", "unknown", "not_applicable"}:
            errors.append(f"{name}: invalid visibility")
        confidence = direction.get("confidence")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (float, int))
                                       or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            errors.append(f"{name}: invalid confidence")
    for name in ("body", "head"):
        if record["view"].get(name) is not None and record["view"][name] not in VIEWS:
            errors.append(f"view.{name}: invalid view")
    layout = record.get("layout", {})
    if layout and layout.get("reference") != "body_midpoint_and_length":
        errors.append("unsupported layout reference")
    for name, point in layout.get("anchors", {}).items():
        if not finite_xy(point):
            errors.append(f"layout.{name}: invalid point")
    return errors


def usable_for_search(record, direction):
    if unit(direction.get("value")) is None:
        return False
    if direction.get("visibility") in {"occluded", "out_of_frame"}:
        return (direction.get("support") == "asset_geometry"
                and record["asset_access"].get("complete_character") == "verified"
                and bool(record["asset_access"].get("evidence_ref")))
    return direction.get("visibility") != "not_applicable"


def as_legacy_vectors(record):
    """Adapter to the corrected, direction-level matching engine; no point requirement."""
    vectors = {"available": {}, "front_legs": [], "back_legs": []}
    for name in ("head", "neck", "body", "tail"):
        direction = record["directions"][name]
        usable = usable_for_search(record, direction)
        vectors["available"][name] = usable
        if usable:
            vectors[name + "_direction"] = direction["value"]
    for group, legacy, segments in (("front", "front_legs", 2), ("hind", "back_legs", 3)):
        for i in (1, 2):
            leg = {"leg_id": f"{group}.{i}", "directions": {}}
            for segment in range(1, segments + 1):
                direction = record["directions"][f"{group}.{i}.{segment}"]
                usable = usable_for_search(record, direction)
                leg["directions"][f"leg_direction{segment}"] = {
                    "available": usable, "vector": direction["value"] if usable else None}
            vectors[legacy].append(leg)
    return vectors


def mirror_record(record):
    mirrored = copy.deepcopy(record)
    for direction in mirrored["directions"].values():
        if direction["value"] is not None:
            direction["value"][0] *= -1
    for point in mirrored.get("layout", {}).get("anchors", {}).values():
        point[0] *= -1
    # A match-time projection, not a new annotation: raw pixel points are removed
    # because flipping them needs an explicit image transform and width convention.
    mirrored.pop("reference_points", None)
    return mirrored
