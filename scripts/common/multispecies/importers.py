"""Adapters for existing body14 records and declared direction-model outputs."""
import copy
import hashlib
import re
from pathlib import Path

from .catalog import Catalog, fingerprint, require
from .records import new_observation, blank_direction, validate_observation, transform_direction, now, new_id

LEGACY_MAPPING = {"head": "core.head", "neck": "core.neck", "body": "core.body", "tail": "core.tail"}
for group, slots, names in (("front", ["fore_a", "fore_b"], ["upper", "lower"]), ("hind", ["hind_a", "hind_b"], ["upper", "middle", "lower"])):
    for i, slot in enumerate(slots, 1):
        for j, name in enumerate(names, 1):
            LEGACY_MAPPING[f"{group}.{i}.{j}"] = slot+"."+name


def import_v1(old, library, project_root):
    """Stable observation IDs do not depend on the enclosing label file's hash."""
    from pose_record import validate, EDGES
    errors = validate(old)
    require(not errors, "旧记录无效: "+"; ".join(errors))
    source, ann = old["source"], old["annotation"]
    path = Path(project_root)/source["image_path"] if source.get("image_path") else Path(project_root)/"__missing__"/(old["sample_id"]+".png")
    asset = library.register_image(path, allow_missing=True, expected_size=old["coordinates"].get("image_size"))
    origin = ann["origin"]
    collection = "query" if origin == "query" else "official" if ann["review_status"] == "legacy_official" and "legacy_experiment" not in old else "experimental"
    subject = old["subject"]
    cat = library.catalog
    character = subject["character_id"]
    if character not in cat.tables["characters"]:
        library.extend_catalog({"characters": [{"id": character, "label": character}]})
        cat = library.catalog
    form = {"unicorn": "twilight.unicorn@1", "alicorn": "twilight.alicorn@1"}.get(subject["form_id"]) if character == "twilight_sparkle" else None
    record = new_observation(cat, profile_ref="pony.quadruped@2draft1", image_ref=asset["id"], image_size=asset["size"],
                             character_ref=character, form_ref=form, actor="legacy_import", collection=collection)
    stable = fingerprint([ann["source_path"], old["sample_id"]])[:32]
    record["observation_id"] = "obs_legacy_"+stable
    record["occurrence_id"] = "occurrence_legacy_"+stable
    # Record image-independent identity and all original provenance, without invented reviews.
    record["source"].update(kind=source["kind"], media_ref=source.get("episode_id"), scene_ref=source.get("scene_id"),
                            frame_index=source.get("absolute_frame_index"), fps=source.get("timebase"),
                            asset_instance_path=source.get("asset_instance_path"), frame_id=source.get("frame_id"), timestamp_sec=source.get("timestamp_sec"))
    record["split_groups"] = {"shot_ref": old.get("dataset_groups", {}).get("shot_id"), "asset_family_ref": old.get("dataset_groups", {}).get("asset_family_id")}
    e_id = "evidence_legacy_"+stable
    record["evidence"] = [{"id": e_id, "kind": "legacy", "origin": origin, "method": ann["method"],
                            "source_path": ann["source_path"], "source_sha256": ann["source_sha256"],
                            "source_record_id": old["record_id"], "review_status": ann["review_status"]}]
    a = record["annotation"]
    status = ann["review_status"] if ann["review_status"] in {"legacy_official", "query_input", "unreviewed"} else "unreviewed"
    for slot, part in a["parts"].items():
        is_wing = slot.startswith("wing_")
        wing_presence = old["optional_parts"]["wings"]["present"]
        part.update(presence=("unknown" if wing_presence is None else "present" if wing_presence else "absent") if is_wing else "present",
                    review_status=status, evidence_refs=[e_id], missing_reason=None)
        if part["presence"] == "unknown":
            part["missing_reason"] = "legacy_unspecified"
    for group, slots in (("front", ["fore_a", "fore_b"]), ("hind", ["hind_a", "hind_b"])):
        for i, slot in enumerate(slots, 1):
            identity = old["leg_identity"][f"{group}.{i}"]
            a["parts"][slot]["identity"] = {"camera_depth": None if identity["depth"] == "unknown" else identity["depth"],
                                              "anatomical_side": None if identity["anatomical_side"] == "unknown" else identity["anatomical_side"], "asset_path": identity["asset_path"]}
    for key, d in cat.channels(record["profile_ref"]).items():
        if a["parts"][d["slot"]]["presence"] == "present":
            a["directions"][key] = blank_direction(e_id, "legacy_unspecified")
    for old_key, key in LEGACY_MAPPING.items():
        d = copy.deepcopy(old["directions"][old_key])
        d.pop("support", None)
        # v1 "not_applicable" direction visibility is not a body-existence judgement.
        if d["visibility"] == "not_applicable":
            d["visibility"] = "unknown"
        if d.get("missing_reason") == "not_applicable":
            d["missing_reason"] = "legacy_unspecified"
        d.update(evidence_refs=[e_id], review_status=status)
        a["directions"][key] = d
        start, end = (old.get("reference_points", {}).get(name) for name in EDGES[old_key])
        if start is not None and end is not None and d["value"] is not None:
            size = asset["size"]
            if size is not None and all(0 <= p[0] <= size[0] and 0 <= p[1] <= size[1] for p in (start, end)):
                a["reference_points"][key] = {"start": start, "end": end}
    a["view"] = {k: {"definition_ref": "pony.view5@1", "value": v} for k, v in old["view"].items() if v is not None}
    layout = old.get("layout")
    a["layout"] = {"definition_ref": "pony.body_midpoint_and_length@1", "anchors": copy.deepcopy(layout["anchors"])} if layout else None
    record["legacy"] = {"sample_id": old["sample_id"], "record_id": old["record_id"], "source_annotation": copy.deepcopy(ann),
                          "reference_points": copy.deepcopy(old.get("reference_points")), "experiment": copy.deepcopy(old.get("legacy_experiment")),
                          "asset_access": copy.deepcopy(old["asset_access"])}
    # The old bare evidence_ref cannot prove asset alignment in v2; keep it as evidence,
    # and require a full engineering evidence entry before any hidden pose is used.
    a["id"] = "ann_legacy_"+fingerprint(old)[:32]
    a["created_at"] = "legacy-time-unknown"
    validate_observation(record, cat)
    existing = library.head_id(record["observation_id"])
    if existing:
        stored = library.read(record["observation_id"])
        require(stored.get("legacy", {}).get("record_id") == old["record_id"], "旧来源已改变；请先核对，不覆盖当前人工修订")
        return stored, False
    library.save(record)
    return record, True


def import_predictions(record, catalog, capability, values, *, affine=None):
    """Model output requires an explicit semantic capability map; never auto-review."""
    require(isinstance(capability, dict) and isinstance(capability.get("id"), str) and capability["id"], "模型能力清单缺少版本")
    require(isinstance(capability.get("model_sha256"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", capability["model_sha256"]), "模型指纹必须为SHA256")
    require(isinstance(capability.get("profiles"), dict), "模型结构映射必须是对象")
    mapping = capability["profiles"].get(record["profile_ref"])
    require(isinstance(mapping, dict) and mapping, "模型未声明支持此身体结构")
    require(all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()), "模型输出映射必须使用方向键")
    definitions = catalog.channels(record["profile_ref"])
    require(set(mapping.values()) <= set(definitions) and len(set(mapping.values())) == len(mapping), "模型输出映射无效或重复")
    require(isinstance(values, dict) and set(values) <= set(mapping), "预测含有未声明输出")
    require(capability.get("coordinate_space") == "image_2d", "模型坐标空间未声明")
    r = copy.deepcopy(record)
    a = r["annotation"]
    a["reference_points"] = a.get("reference_points") or {}
    if values:
        a["layout"] = None
    a.update(id=new_id("ann"), parent_ids=[record["annotation"]["id"]], author=capability["id"], created_at=now())
    evidence = new_id("evidence")
    r["evidence"].append({"id": evidence, "kind": "model", "capability": copy.deepcopy(capability), "transform": affine, "created_at": now()})
    for output, value in values.items():
        key = mapping[output]
        require(key in a["directions"], "部位必须先确认存在，不能由模型能力清单推断身体")
        a["reference_points"].pop(key, None)
        a["directions"][key] = {"value": None if value is None else transform_direction(value, affine or [1, 0, 0, 1, 0, 0]),
                                 "missing_reason": "not_discernible" if value is None else None, "visibility": "unknown",
                                 "confidence": None, "evidence_refs": [evidence], "review_status": "unreviewed"}
    validate_observation(r, catalog)
    return r
