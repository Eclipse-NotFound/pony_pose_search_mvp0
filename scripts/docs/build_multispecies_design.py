"""Build and check an isolated design bundle; never change production labels."""
from pathlib import Path
import copy
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/multispecies-design"
DESIGN = ROOT / "设计/multispecies-v2"


def module(key, label, names, established=False):
    named = {"head": ("头部中心", "头部朝向参考"), "neck": ("前躯连接中心", "颈部朝向参考"),
             "body": ("前躯连接中心", "后躯连接中心"), "tail": ("尾部连接区域", "尾巴向外初始朝向参考"),
             "torso": ("骨盆参考", "肩部参考"), "torso_a": ("躯干前部参考", "躯干中部参考"),
             "torso_b": ("躯干中部参考", "躯干后部参考"),
             "root_to_bend": ("翼与身体连接区域", "翼的主要转折参考"),
             "bend_to_tip_reference": ("翼的主要转折参考", "翼的外伸朝向参考")}
    chain = (["连接区域中间", "上转折参考", "下转折参考", "末端参考"] if len(names) == 3
             else ["连接区域中间", "转折参考", "末端参考"])
    directions = []
    for index, name in enumerate(names):
        start, end = named[name] if name in named else (chain[index], chain[index+1])
        if name == "neck" and key.startswith("dragon"):
            start = "肩部连接区域"
        directions.append({"key": name, "definition_ref": key + "/" + name,
                           "from_semantic": start, "to_semantic": end, "coordinate_space": "image_2d",
                           "rule_status": "legacy_equivalent" if established else "draft_requires_visual_examples"})
    return {"id": key, "label": label, "status": "legacy_equivalent" if established else "draft", "directions": directions}


def make_bundle():
    modules = [
        module("pony.core@1", "小马头颈、躯干、尾根", ["head", "neck", "body", "tail"], True),
        module("pony.fore@1", "小马前腿：2段", ["upper", "lower"], True),
        module("pony.hind@1", "小马后腿：3段", ["upper", "middle", "lower"], True),
        module("griffon.core@draft1", "狮鹫头颈、躯干、尾根", ["head", "neck", "body", "tail"]),
        module("claw.fore@draft1", "爪形前肢：示例2段", ["upper", "lower"]),
        module("feline.hind@draft1", "兽形后肢：示例3段", ["upper", "middle", "lower"]),
        module("wing.feather@draft1", "羽翼：示例2段", ["root_to_bend", "bend_to_tip_reference"]),
        module("dragon.core@draft1", "双足龙：头颈、骨盆至肩、尾根", ["head", "neck", "torso", "tail"]),
        module("arm.claw@draft1", "爪形手臂：示例2段", ["upper", "lower"]),
        module("leg.biped@draft1", "双足腿：示例3段", ["upper", "middle", "lower"]),
        module("wing.membrane@draft1", "膜翼：示例2段", ["root_to_bend", "bend_to_tip_reference"]),
        module("hybrid.core@draft1", "弯曲躯干：示例2段＋头颈尾", ["head", "neck", "torso_a", "torso_b", "tail"]),
        module("limb.long@draft1", "异形肢：示例3段", ["upper", "middle", "lower"]),
    ]
    def part(slot, role, ref, optional=False):
        return {"slot": slot, "role": role, "module_ref": ref, "optional": optional}
    def profile(key, label, parts, groups):
        return {"id": key, "label": label, "parts": parts,
                "exchange_groups": [{"slots": g, "mode": "whole_chain", "default": "allow"} for g in groups]}
    pony = [part("core", "core", "pony.core@1")]
    pony += [part("fore_"+x, "forelimb", "pony.fore@1") for x in ("a", "b")]
    pony += [part("hind_"+x, "hindlimb", "pony.hind@1") for x in ("a", "b")]
    pony += [part("wing_"+x, "wing", "wing.feather@draft1", True) for x in ("a", "b")]
    griffon = [part("core", "core", "griffon.core@draft1")]
    griffon += [part("fore_"+x, "forelimb", "claw.fore@draft1") for x in ("a", "b")]
    griffon += [part("hind_"+x, "hindlimb", "feline.hind@draft1") for x in ("a", "b")]
    griffon += [part("wing_"+x, "wing", "wing.feather@draft1") for x in ("a", "b")]
    dragon = [part("core", "core", "dragon.core@draft1")]
    dragon += [part("arm_"+x, "arm", "arm.claw@draft1") for x in ("a", "b")]
    dragon += [part("leg_"+x, "leg", "leg.biped@draft1") for x in ("a", "b")]
    dragon += [part("wing_"+x, "wing", "wing.membrane@draft1", True) for x in ("a", "b")]
    hybrid = [part("core", "core", "hybrid.core@draft1"),
              part("fore_a", "forelimb", "claw.fore@draft1"), part("fore_b", "forelimb", "limb.long@draft1"),
              part("hind_a", "hindlimb", "pony.hind@1"), part("hind_b", "hindlimb", "claw.fore@draft1"),
              part("wing_a", "wing", "wing.feather@draft1"), part("wing_b", "wing", "wing.membrane@draft1")]
    profiles = [profile("pony.quadruped@2draft1", "小马：四足＋可选翼", pony, [["fore_a", "fore_b"], ["hind_a", "hind_b"], ["wing_a", "wing_b"]]),
                profile("griffon.quadruped@draft1", "狮鹫结构示例", griffon, [["fore_a", "fore_b"], ["hind_a", "hind_b"], ["wing_a", "wing_b"]]),
                profile("dragon.biped@draft1", "双足有翼龙结构示例", dragon, [["arm_a", "arm_b"], ["leg_a", "leg_b"], ["wing_a", "wing_b"]]),
                profile("hybrid.asymmetric@draft1", "不对称混合结构示例", hybrid, [])]
    forms = []
    for key, character, species, profile_id, wings in (
            ("twilight.unicorn@1", "twilight_sparkle", "pony", profiles[0]["id"], False),
            ("twilight.alicorn@1", "twilight_sparkle", "pony", profiles[0]["id"], True),
            ("example.griffon@1", "example_griffon", "griffon", profiles[1]["id"], True),
            ("example.dragon@1", "example_dragon", "dragon", profiles[2]["id"], True),
            ("example.hybrid@1", "example_hybrid", "mixed_unspecified", profiles[3]["id"], True)):
        forms.append({"id": key, "character_ref": character, "species_ref": species, "profile_ref": profile_id,
                      "expected_presence": {"wing_a": "present" if wings else "absent", "wing_b": "present" if wings else "absent"},
                      "status": "design_example"})
    catalog = {"characters": [{"id": "twilight_sparkle", "label": "暮光闪闪"},
                              {"id": "example_griffon", "label": "狮鹫示例角色"}, {"id": "example_dragon", "label": "龙示例角色"},
                              {"id": "example_hybrid", "label": "混合身体示例角色"}],
               "species": [{"id": s, "label": label} for s, label in (("pony", "小马"), ("griffon", "狮鹫"), ("dragon", "龙"), ("mixed_unspecified", "混合，未细分"))],
               "forms": forms, "modules": modules, "profiles": profiles}
    by_module = {m["id"]: m for m in modules}
    by_profile = {p["id"]: p for p in profiles}
    examples = []
    for number, form in enumerate(forms, 1):
        p = by_profile[form["profile_ref"]]
        presence = {part["slot"]: form["expected_presence"].get(part["slot"], "present") for part in p["parts"]}
        directions = {}
        for part in p["parts"]:
            if presence[part["slot"]] != "present":
                continue
            for d in by_module[part["module_ref"]]["directions"]:
                key = part["slot"] + "." + d["key"]
                angle = 180 if d["key"] == "head" else (0 if d["key"] in ("body", "tail") else 70)
                directions[key] = {"value": [round(math.cos(math.radians(angle)), 9), round(math.sin(math.radians(angle)), 9)],
                                   "missing_reason": None, "visibility": "unknown", "evidence_refs": ["evidence_example"],
                                   "review_status": "unreviewed", "confidence": None}
        examples.append({"schema_version": "pose_observation_v2alpha1", "example_only": True,
                         "observation_id": f"example_observation_{number}", "occurrence_id": f"example_occurrence_{number}",
                         "subject": {"character_ref": form["character_ref"], "form_ref": form["id"], "track_ref": None},
                         "profile_ref": p["id"], "image_ref": f"illustration_{number}",
                         "coordinates": {"space": "image_2d", "x_axis": "right", "y_axis": "down", "image_size": [360, 250]},
                         "annotation": {"id": f"example_annotation_{number}_r1", "parent_ids": [], "directions": directions,
                                        "parts": {key: {"presence": state, "evidence_refs": ["evidence_example"],
                                                        "identity": {"anatomical_side": None, "camera_depth": None, "asset_path": None}}
                                                  for key, state in presence.items()},
                                        "reference_points": None, "view": {"body": None, "head": None}, "layout": None},
                         "asset_access": {"complete_character": "unknown", "evidence_refs": []},
                         "evidence": [{"id": "evidence_example", "kind": "synthetic", "note": "仅用于验证设计，非真实角色或训练标注"}],
                         "source": {"kind": "synthetic_diagram", "media_ref": None, "scene_ref": None, "frame_index": None,
                                    "fps": None, "asset_instance_path": None, "alignment_ref": None},
                         "split_groups": {"shot_ref": None, "asset_family_ref": None}})
    legacy = {"head": "core.head", "neck": "core.neck", "body": "core.body", "tail": "core.tail"}
    for old, slots, segments in (("front", ["fore_a", "fore_b"], ["upper", "lower"]),
                                 ("hind", ["hind_a", "hind_b"], ["upper", "middle", "lower"])):
        for i, slot in enumerate(slots, 1):
            for j, segment in enumerate(segments, 1):
                legacy[f"{old}.{i}.{j}"] = slot + "." + segment
    contracts = [{"id": "pony.body14@1", "status": "legacy_equivalent", "meaning": "只比较小马原14方向，翼不在本次请求内",
                  "profiles": [profiles[0]["id"]], "channels": list(legacy.values()), "required_parts": ["core", "fore_a", "fore_b", "hind_a", "hind_b"]},
                 {"id": "cross_species.head_only@draft1", "status": "draft_not_production", "meaning": "只比较头的朝向，不能称为整体姿态相似",
                  "projections": [{"profile_ref": p["id"], "mapping": {"head_facing": "core.head"}} for p in profiles]},
                 {"id": "feather_wings@draft1", "status": "draft_not_production", "meaning": "翼的分段规则需实际素材确认，不将羽翼和膜翼自动等同",
                  "profiles": [profiles[0]["id"], profiles[1]["id"]], "required_parts": ["wing_a", "wing_b"]}]
    return {"bundle_version": "multispecies_design_20261011_v1", "status": "design_proposal_not_runtime_migration",
            "catalog": catalog, "comparison_contracts": contracts, "legacy_body14_mapping": legacy, "examples": examples}


def validate_bundle(bundle):
    cat = bundle["catalog"]
    maps = {name: {r["id"]: r for r in rows} for name, rows in cat.items()}
    assert all(len(maps[name]) == len(cat[name]) for name in maps), "duplicate ID"
    for p in cat["profiles"]:
        parts = {r["slot"]: r for r in p["parts"]}
        assert len(parts) == len(p["parts"])
        for part in p["parts"]:
            assert part["module_ref"] in maps["modules"], "unknown module"
        for g in p["exchange_groups"]:
            assert all(slot in parts for slot in g["slots"])
            assert len({parts[slot]["module_ref"] for slot in g["slots"]}) == 1, "incompatible whole-chain exchange"
    for e in bundle["examples"]:
        p = maps["profiles"][e["profile_ref"]]
        f = maps["forms"][e["subject"]["form_ref"]]
        assert f["profile_ref"] == p["id"] and f["character_ref"] == e["subject"]["character_ref"]
        expected = set()
        for part in p["parts"]:
            presence = e["annotation"]["parts"][part["slot"]]["presence"]
            assert presence in ("present", "absent", "unknown")
            if presence == "present":
                expected.update(part["slot"] + "." + d["key"] for d in maps["modules"][part["module_ref"]]["directions"])
        assert set(e["annotation"]["directions"]) == expected, "absent part has labels or present part omitted"
        evidence = {r["id"] for r in e["evidence"]}
        for d in e["annotation"]["directions"].values():
            assert set(d["evidence_refs"]) <= evidence and d["evidence_refs"], "missing evidence"
            assert d["review_status"] == "unreviewed", "synthetic examples must stay unreviewed"
            if d["value"] is not None:
                assert len(d["value"]) == 2 and all(math.isfinite(x) for x in d["value"])
                assert abs(math.hypot(*d["value"]) - 1) < 1e-6, "not a unit vector"
                assert d["missing_reason"] is None
            else:
                assert d["missing_reason"]
    for c in bundle["comparison_contracts"]:
        for projection in c.get("projections", []):
            p = maps["profiles"][projection["profile_ref"]]
            valid = {part["slot"]+"."+d["key"] for part in p["parts"] for d in maps["modules"][part["module_ref"]]["directions"]}
            assert set(projection["mapping"].values()) <= valid
    assert len(bundle["legacy_body14_mapping"]) == len(set(bundle["legacy_body14_mapping"].values())) == 14


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    DESIGN.mkdir(parents=True, exist_ok=True)
    (OUT / "qa").mkdir(exist_ok=True)
    bundle = make_bundle()
    validate_bundle(bundle)
    negative = []
    for name, edit in (
        ("unknown_module", lambda b: b["catalog"]["profiles"][0]["parts"][0].update(module_ref="missing")),
        ("nonunit_direction", lambda b: b["examples"][0]["annotation"]["directions"]["core.head"].update(value=[9, 0])),
        ("absent_wing_with_measurements", lambda b: b["examples"][1]["annotation"]["parts"]["wing_a"].update(presence="absent")),
        ("unproven_review_upgrade", lambda b: b["examples"][0]["annotation"]["directions"]["core.head"].update(review_status="approved")),
        ("unresolved_evidence", lambda b: b["examples"][0]["annotation"]["directions"]["core.head"].update(evidence_refs=["missing"])),
        ("mismatched_form_profile", lambda b: b["examples"][0].update(profile_ref=b["catalog"]["profiles"][1]["id"])),
        ("asymmetric_chain_swapped", lambda b: b["catalog"]["profiles"][-1]["exchange_groups"].append({"slots":["fore_a","fore_b"]})),
    ):
        case = copy.deepcopy(bundle)
        edit(case)
        try:
            validate_bundle(case)
        except (AssertionError, KeyError):
            negative.append({"case": name, "rejected": True})
        else:
            raise AssertionError(f"invalid case accepted: {name}")
    data = json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (DESIGN / "design-bundle.json").write_text(data, encoding="utf-8")
    template = ROOT / "scripts/docs/templates/multispecies-design.html"
    page = template.read_text(encoding="utf-8").replace("__DESIGN_JSON__", data.replace("</", "<\\/"))
    assert "__DESIGN_JSON__" not in page
    (OUT / "index.html").write_text(page, encoding="utf-8")
    report = {"date": "2026-10-11", "positive_examples": len(bundle["examples"]),
              "direction_counts": [len(e["annotation"]["directions"]) for e in bundle["examples"]],
              "negative_cases": negative, "legacy_mapping_count": 14,
              "scope": "Design reference, unit-vector and example checks; not a JSON Schema validator or production multispecies test"}
    (OUT / "qa/validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    sources = [ROOT / "scripts/common/pose_record.py", ROOT / "scripts/common/pose_matching.py", ROOT / "docs/pose-record-v1.md", template, Path(__file__)]
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (OUT / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
