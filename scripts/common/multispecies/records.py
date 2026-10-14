"""One image observation, with append-only annotation revisions and field review."""
import copy
from datetime import datetime, timezone
import math
import re
import uuid

from .catalog import require, number, xy, fingerprint

FORMAT = "pose_observation_v2"
REVIEW = {"unreviewed", "approved", "corrected", "rejected", "legacy_official", "query_input"}
ACCEPTED = {"approved", "corrected", "legacy_official"}
VISIBILITY = {"visible", "occluded", "out_of_frame", "unknown"}
MISSING = {"not_annotated", "not_discernible", "occluded", "out_of_frame", "not_drawn", "invalid_geometry", "legacy_unspecified", "unsupported_model"}
VIEWS = {"front", "front_oblique", "side", "rear_oblique", "rear"}


def _validate_engineering_source(source):
    """Keep a rendered engineering frame distinct from a decoded video frame."""
    require(source.get('kind') == 'fla_frame' and source.get('precision') == 'timeline_exact',
            '工程画面必须使用 fla_frame / timeline_exact 定位')
    require(isinstance(source.get('locator_ref'), str) and source['locator_ref'], '工程画面缺少来源位置')
    require(isinstance(source.get('media_ref'), str) and source['media_ref'], '工程画面缺少源素材引用')
    engineering = source.get('engineering')
    fields = {'timeline_id', 'timeline_kind', 'timeline_name', 'frame_index0', 'frame_count',
              'render_scope', 'renderer', 'export_ref'}
    require(isinstance(engineering, dict) and set(engineering) == fields, '工程定位字段缺失或无效')
    kind, timeline_id, name = (engineering.get(k) for k in ('timeline_kind', 'timeline_id', 'timeline_name'))
    require(kind in {'scene', 'symbol'} and isinstance(timeline_id, str), '工程时间轴种类或编号无效')
    require(isinstance(name, str) and name.strip() and '\x00' not in name, '工程时间轴名称无效')
    if kind == 'scene':
        require(re.fullmatch(r'scene:(0|[1-9][0-9]*)', timeline_id), '工程场景编号无效')
    else:
        require(timeline_id == 'symbol:'+name, '工程元件编号与精确库名不一致')
    frame, count = engineering.get('frame_index0'), engineering.get('frame_count')
    require(isinstance(frame, int) and not isinstance(frame, bool) and isinstance(count, int)
            and not isinstance(count, bool) and 0 <= frame < count, '工程帧号超出时间轴范围')
    require(source.get('frame_index') == frame, '观测帧号与工程帧号不一致')
    require(source.get('timestamp_sec') is None, '工程时间轴帧不能伪装为视频时间戳')
    require(engineering.get('render_scope') == kind, '工程渲染范围与时间轴种类不一致')
    renderer = engineering.get('renderer')
    require(isinstance(renderer, dict) and renderer.get('name') == 'Adobe Animate'
            and isinstance(renderer.get('version'), str) and renderer['version'].strip(),
            '工程定位缺少 Animate 渲染器版本')
    export_ref = engineering.get('export_ref')
    require(isinstance(export_ref, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,150}', export_ref),
            '工程定位缺少有效导出引用')


def new_id(prefix):
    return prefix + "_" + uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


def unit(value):
    require(xy(value) and math.hypot(*value) > 1e-12, "方向必须是有限、非零的二维向量")
    length = math.hypot(*value)
    return [float(v / length) for v in value]


def transform_direction(value, affine):
    """Transform a direction (never translate it); re-normalize anisotropic scale."""
    require(isinstance(affine, list) and len(affine) == 6 and all(number(v) for v in affine), "坐标变换需要6个有限数值")
    x, y = unit(value)
    a, b, c, d, _, _ = affine
    return unit([a*x+c*y, b*x+d*y])


def blank_direction(evidence_ref, reason="not_annotated"):
    return {"value": None, "missing_reason": reason, "visibility": "unknown", "confidence": None,
            "evidence_refs": [evidence_ref], "review_status": "unreviewed"}


def new_observation(catalog, *, profile_ref, image_ref, image_size, character_ref=None,
                    form_ref=None, actor="本机用户", occurrence_id=None, collection="manual"):
    profile = catalog.get("profiles", profile_ref)
    evidence_id = new_id("evidence")
    record = {
        "schema_version": FORMAT, "observation_id": new_id("obs"),
        "occurrence_id": occurrence_id or new_id("occurrence"), "collection": collection,
        "subject": {"character_ref": character_ref, "form_ref": form_ref, "track_ref": None},
        "profile_ref": profile_ref, "image_ref": image_ref,
        "coordinates": {"space": "image_2d", "x_axis": "right", "y_axis": "down", "image_size": image_size},
        "source": {"kind": "image", "media_ref": None, "scene_ref": None, "frame_index": None,
                   "fps": None, "asset_instance_path": None, "alignment_ref": None},
        "split_groups": {"shot_ref": None, "asset_family_ref": None},
        "asset_access": {"complete_character": "unknown", "evidence_refs": []},
        "evidence": [{"id": evidence_id, "kind": "manual", "actor": actor, "created_at": now(),
                      "method": "structure_selected_parts_not_yet_confirmed"}],
        "annotation": {"id": new_id("ann"), "parent_ids": [], "author": actor, "created_at": now(),
                       "parts": {p["slot"]: {"presence": "unknown", "missing_reason": "not_confirmed",
                                  "identity": {"anatomical_side": None, "camera_depth": None, "asset_path": None},
                                  "evidence_refs": [evidence_id], "review_status": "unreviewed"} for p in profile["parts"]},
                       "directions": {}, "reference_points": {}, "view": {}, "layout": None, "review_events": []}}
    validate_observation(record, catalog)
    return record


def validate_observation(record, catalog, assets=None):
    """Raise a field-level DataError before saving, indexing or using any labels."""
    r = record
    require(isinstance(r, dict) and r.get("schema_version") == FORMAT, "不支持的观测格式")
    for flag in ("example_only", "test_only"):
        require(flag not in r or isinstance(r[flag], bool), f"{flag}: 必须为布尔值")
    for key in ("observation_id", "occurrence_id", "profile_ref", "image_ref", "collection"):
        require(isinstance(r.get(key), str) and r[key], f"{key}: 必须填写")
    for key in ("subject", "coordinates", "source", "split_groups", "asset_access", "annotation"):
        require(isinstance(r.get(key), dict), f"{key}: 必须是对象")
    profile = catalog.get("profiles", r["profile_ref"])
    channels = catalog.channels(r["profile_ref"])
    subject = r["subject"]
    for field in ("character_ref", "form_ref", "track_ref"):
        require(subject.get(field) is None or isinstance(subject[field], str) and subject[field], f"subject.{field}: 无效引用")
    if subject.get("character_ref") is not None:
        catalog.get("characters", subject["character_ref"])
    if subject.get("form_ref") is not None:
        form = catalog.get("forms", subject["form_ref"])
        require(form["profile_ref"] == r["profile_ref"], "形态和身体说明书不一致")
        require(form.get("character_ref") in (None, subject.get("character_ref")), "形态属于另一个角色")
    coord = r["coordinates"]
    require(coord.get("space") == "image_2d" and coord.get("x_axis") == "right" and coord.get("y_axis") == "down", "只接受右/下为正的二维图像方向")
    size = coord.get("image_size")
    require(size is None or xy(size) and all(isinstance(x, int) and x > 0 for x in size), "图片尺寸必须为正整数")
    if assets is not None:
        require(r["image_ref"] in assets, "image_ref未登记")
        require(assets[r["image_ref"]].get("size") == size, "观测尺寸与图片资产不符")
    source = r["source"]
    require(isinstance(source.get("kind"), str) and source["kind"], "source.kind缺失")
    frame = source.get("frame_index")
    require(frame is None or isinstance(frame, int) and not isinstance(frame, bool) and frame >= 0, "帧号无效")
    fps = source.get("fps")
    require(fps is None or isinstance(fps, list) and len(fps) == 2 and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in fps), "帧率必须为正整数分子/分母")
    if source.get("locator_ref") is not None:
        for key in ("locator_ref", "source_version_ref", "import_ref"):
            require(isinstance(source.get(key), str) and source[key], f"source.{key}: 缺少来源引用")
        require(source.get("precision") in {"frame_exact", "image_exact", "timeline_exact"}, "来源定位精度无效")
        roi = source.get("roi")
        require(isinstance(roi, list) and len(roi) == 4 and all(isinstance(v, int) and not isinstance(v, bool) for v in roi), "角色框无效")
        require(roi[0] >= 0 and roi[1] >= 0 and roi[2] > 0 and roi[3] > 0, "角色框范围无效")
        full = source.get("source_image_size")
        require(xy(full) and roi[0]+roi[2] <= full[0] and roi[1]+roi[3] <= full[1], "角色框超出来源画面")
        require(size == roi[2:], "角色裁剪尺寸与观测不一致")
        require(source.get("source_to_image") == [1, 0, 0, 1, -roi[0], -roi[1]], "来源坐标变换与裁剪不符")
    if source.get('kind') == 'fla_frame' or source.get('precision') == 'timeline_exact' or 'engineering' in source:
        _validate_engineering_source(source)
    for key in ("shot_ref", "asset_family_ref"):
        require(r["split_groups"].get(key) is None or isinstance(r["split_groups"][key], str) and r["split_groups"][key], "无效数据分组")
    evidence = r.get("evidence")
    require(isinstance(evidence, list), "证据必须是列表")
    by_evidence = {}
    for item in evidence:
        require(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] not in by_evidence, "无效或重复证据id")
        require(item.get("kind") in {"manual", "agent", "model", "asset", "legacy", "synthetic", "query"}, "证据种类无效")
        by_evidence[item["id"]] = item

    def refs(item, name):
        values = item.get("evidence_refs")
        require(isinstance(values, list) and values and all(isinstance(v, str) and v in by_evidence for v in values), f"{name}: 证据引用缺失")

    a = r["annotation"]
    for field in ("id", "author", "created_at"):
        require(isinstance(a.get(field), str) and a[field], f"annotation.{field}: 必填")
    require(isinstance(a.get("parent_ids"), list) and all(isinstance(x, str) and x for x in a["parent_ids"]) and a["id"] not in a["parent_ids"], "父修订无效")
    require(len(set(a["parent_ids"])) == len(a["parent_ids"]), "父修订重复")
    require(isinstance(a.get("parts"), dict) and set(a["parts"]) == {p["slot"] for p in profile["parts"]}, "部位必须完整对应身体说明书")
    expected = set()
    fields = {}
    for slot, part in a["parts"].items():
        require(isinstance(part, dict) and part.get("presence") in {"present", "absent", "unknown"}, f"{slot}: 存在性无效")
        require(part.get("presence") != "unknown" or isinstance(part.get("missing_reason"), str) and part["missing_reason"], f"{slot}: 未知存在性需要原因")
        require(part.get("presence") == "unknown" or part.get("missing_reason") is None, f"{slot}: 已确认存在性不能有缺失原因")
        identity = part.get("identity")
        require(isinstance(identity, dict), f"{slot}: 缺少身份对象")
        require(identity.get("anatomical_side") in {None, "left", "right", "midline"} and identity.get("camera_depth") in {None, "near", "far"}, f"{slot}: 身份无效")
        require(identity.get("asset_path") is None or isinstance(identity["asset_path"], str), f"{slot}: 工程身份无效")
        refs(part, slot)
        fields["parts."+slot] = part
        if part["presence"] == "present":
            expected.update(k for k, definition in channels.items() if definition["slot"] == slot)
    require(isinstance(a.get("directions"), dict) and set(a["directions"]) == expected, "存在部位必须包含所有方向；不存在/未知部位不得填方向")
    for key, d in a["directions"].items():
        require(isinstance(d, dict), f"{key}: 方向必须是对象")
        value = d.get("value")
        require(value is None or xy(value) and abs(math.hypot(*value)-1) <= 1e-6, f"{key}: 必须是有限单位向量")
        require(d.get("missing_reason") in MISSING if value is None else d.get("missing_reason") is None, f"{key}: 缺失原因不正确")
        require(d.get("visibility") in VISIBILITY, f"{key}: 可见性无效")
        c = d.get("confidence")
        require(c is None or number(c) and 0 <= c <= 1, f"{key}: 可信度无效")
        refs(d, key)
        fields["directions."+key] = d
    reviews = a.get("review_events")
    from .keypoints import validate as validate_keypoints
    fields.update(validate_keypoints(r, refs))
    require(isinstance(reviews, list), "必须保留逐项审核事件")
    reviewed = {}
    for event in reviews:
        require(isinstance(event, dict) and event.get("actor") and event.get("at") and event.get("revision_ref"), "审核事件缺少人、时间或版本")
        require(event.get("status") in {"approved", "corrected", "rejected"}, "审核结论无效")
        require(isinstance(event.get("targets"), list) and event["targets"], "审核范围不能为空")
        for target in event["targets"]:
            # A historical event can refer to a direction removed by a later presence edit.
            require(isinstance(target, str) and target.startswith(("parts.", "directions.", "keypoints.")), "审核目标无效")
            reviewed[target] = event["status"]
    for key, item in fields.items():
        status = item.get("review_status")
        require(status in REVIEW, f"{key}: 审核状态无效")
        if status in {"approved", "corrected", "rejected"}:
            require(reviewed.get(key) == status, f"{key}: 审核状态没有对应事件")
        if status == "legacy_official":
            require(any(by_evidence[e]["kind"] == "legacy" and by_evidence[e].get("review_status") == "legacy_official" for e in item["evidence_refs"]), "不能凭迁移升级旧审核")
        if r.get("example_only"):
            require(status == "unreviewed", "设计示例不能变成人工审核标签")
    points = a.get("reference_points") or {}
    require(isinstance(points, dict) and set(points) <= expected, "参考点引用未知方向")
    for key, pair in points.items():
        require(isinstance(pair, dict) and xy(pair.get("start")) and xy(pair.get("end")), "人工参考点无效")
        if size is not None:
            require(all(0 <= p[0] <= size[0] and 0 <= p[1] <= size[1] for p in (pair["start"], pair["end"])), "参考点超出图像")
        value = a["directions"][key]["value"]
        if value is not None:
            derived = unit([pair["end"][i]-pair["start"][i] for i in (0, 1)])
            require(math.dist(value, derived) < 1e-6, "参考点与所存方向不一致")
    require(isinstance(a.get("view"), dict), "view必须是对象")
    for part, value in a["view"].items():
        require(part in {"body", "head"} and isinstance(value, dict) and value.get("definition_ref") and value.get("value") in VIEWS, "视角缺少定义或取值无效")
    layout = a.get("layout")
    if layout is not None:
        require(isinstance(layout, dict) and layout.get("definition_ref") and isinstance(layout.get("anchors"), dict), "布局缺少定义")
        require(all(xy(v) for v in layout["anchors"].values()), "布局坐标无效")
    access = r["asset_access"]
    require(access.get("complete_character") in {"verified", "unknown", "unavailable"}, "完整素材状态无效")
    if access["complete_character"] == "verified":
        refs(access, "asset_access")
        for ref in access["evidence_refs"]:
            e = by_evidence[ref]
            require(e["kind"] == "asset" and all(e.get(k) for k in ("project_path", "instance_path", "alignment_ref", "verified_by", "verified_at")), "完整角色必须有可定位、已核对的工程证据")
            require(e.get("image_ref") == r["image_ref"] and e.get("occurrence_ref") == r["occurrence_id"], "工程证据必须对齐当前图片与角色实例")
            require(isinstance(e.get("frame_index"), int) and not isinstance(e["frame_index"], bool) and e["frame_index"] >= 0, "工程证据缺少帧号")
            require(isinstance(e.get("transform"), list) and len(e["transform"]) == 6 and all(number(v) for v in e["transform"]), "工程证据缺少坐标变换")
    fingerprint(r)  # Reject non-JSON and non-finite values anywhere, including metadata.
    return r


def usable(record, key, *, reviewed_only=False):
    a = record["annotation"]
    d = a["directions"].get(key)
    if not d or d["value"] is None or d["review_status"] == "rejected":
        return False
    if d.get('derived_from', {}).get('stale'):
        return False
    part = a["parts"][key.split(".", 1)[0]]
    if part["review_status"] == "rejected":
        return False
    if reviewed_only and (d["review_status"] not in ACCEPTED or part["review_status"] not in ACCEPTED):
        return False
    if d["visibility"] in {"occluded", "out_of_frame"}:
        asset_evidence = set(record["asset_access"].get("evidence_refs", []))
        return record["asset_access"]["complete_character"] == "verified" and bool(asset_evidence.intersection(d["evidence_refs"]))
    return True


def revise(record, catalog, changes, *, actor, review=None):
    """Apply edits to a copy; changed fields lose approval, untouched fields retain it."""
    require(isinstance(changes, dict) and set(changes) <= {"parts", "directions", "keypoints", "view", "layout", "split_groups"}, "未知修改项目")
    for field in ("parts", "directions"):
        require(isinstance(changes.get(field, {}), dict), f"{field}: 修改必须是对象")
    require(isinstance(actor, str) and actor.strip(), "需要标注者名称")
    r = copy.deepcopy(record)
    a = r["annotation"]
    a["reference_points"] = a.get("reference_points") or {}
    a.update(id=new_id("ann"), parent_ids=[record["annotation"]["id"]], author=actor.strip(), created_at=now())
    e_id = new_id("evidence")
    r["evidence"].append({"id": e_id, "kind": "manual", "actor": actor.strip(), "created_at": now(), "method": "direction_editor"})
    definitions = catalog.channels(r["profile_ref"])
    for slot, patch in changes.get("parts", {}).items():
        require(slot in a["parts"] and isinstance(patch, dict) and set(patch) <= {"presence", "missing_reason", "identity"}, "部位修改无效")
        part = a["parts"][slot]
        old_presence = part["presence"]
        part.update(copy.deepcopy(patch), review_status="unreviewed", evidence_refs=[e_id])
        part["missing_reason"] = part.get("missing_reason") or "not_confirmed" if part["presence"] == "unknown" else None
        if part["presence"] != old_presence:
            for key, d in definitions.items():
                if d["slot"] == slot:
                    a["directions"].pop(key, None)
                    a["reference_points"].pop(key, None)
                    if part["presence"] == "present":
                        a["directions"][key] = blank_direction(e_id)
    for key, patch in changes.get("directions", {}).items():
        require(key in a["directions"] and isinstance(patch, dict) and set(patch) <= {"value", "missing_reason", "visibility", "reference_points"}, "方向修改无效或部位尚未确认存在")
        d = a["directions"][key]
        patch = copy.deepcopy(patch)
        pair = patch.pop("reference_points", None)
        geometry_changed = pair is not None or "value" in patch
        if pair is not None:
            require(isinstance(pair, dict) and xy(pair.get("start")) and xy(pair.get("end")), "参考点不完整")
            patch["value"] = unit([pair["end"][i]-pair["start"][i] for i in (0, 1)])
            a["reference_points"][key] = pair
        elif "value" in patch:
            a["reference_points"].pop(key, None)
            if patch["value"] is not None:
                patch["value"] = unit(patch["value"])
        refs = [e_id] if geometry_changed else list(dict.fromkeys(d["evidence_refs"]+[e_id]))
        d.update(patch, review_status="unreviewed", evidence_refs=refs, confidence=None)
        d["missing_reason"] = (d.get("missing_reason") or "not_annotated") if d["value"] is None else None
        if geometry_changed:
            d.pop('derived_from', None)
            # Existing point-derived spatial context must not outlive its geometry.
            a["layout"] = None
    if 'keypoints' in changes:
        from .keypoints import edit as edit_keypoints
        edit_keypoints(r, changes['keypoints'], e_id)
    for name in ("view", "layout"):
        if name in changes:
            a[name] = copy.deepcopy(changes[name])
    if "split_groups" in changes:
        r["split_groups"] = copy.deepcopy(changes["split_groups"])
    if review:
        require(isinstance(review, dict), "审核必须是对象")
        targets, status = review.get("targets"), review.get("status")
        require(status in {"approved", "corrected", "rejected"} and isinstance(targets, list) and targets, "审核范围与结论必填")
        for target in targets:
            require(isinstance(target, str) and "." in target, "审核目标无效")
            section, key = target.split(".", 1)
            items = a.get('keypoints', {}).get('points', {}) if section == 'keypoints' else a.get(section, {})
            require(section in {"parts", "directions", "keypoints"} and key in items, "审核目标不存在")
            items[key]["review_status"] = status
        a["review_events"].append({"id": new_id("review"), "actor": actor, "at": now(), "revision_ref": a["id"], "targets": targets, "status": status})
    validate_observation(r, catalog)
    return r
