"""Create the initial runtime catalog from the reviewed design (no example labels)."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts/common"))
from multispecies.catalog import Catalog


def build():
    bundle = json.loads((ROOT/"设计/multispecies-v2/design-bundle.json").read_text(encoding="utf-8"))
    cat = copy.deepcopy(bundle["catalog"])
    cat["schema_version"] = "pose_catalog_v2"
    cat["characters"] = [c for c in cat["characters"] if not c["id"].startswith("example_")]
    for form in cat["forms"]:
        if form["id"].startswith("example."):
            form["id"] = form["id"].replace("example.", "generic.")
            form["character_ref"] = None
            form["status"] = "structure_template"
        else:
            form["status"] = "known_form"
        form["label"] = {"twilight.unicorn@1": "暮光 · 独角兽", "twilight.alicorn@1": "暮光 · 公主",
                         "generic.griffon@1": "狮鹫 · 四足羽翼", "generic.dragon@1": "龙 · 双足膜翼",
                         "generic.hybrid@1": "混合 · 不对称身体"}[form["id"]]
    modules = {m["id"]: m for m in cat["modules"]}

    def groups(profile, exclude_wings=False):
        result, limbs, main = [], {}, []
        for part in profile["parts"]:
            if exclude_wings and part["role"] == "wing":
                continue
            keys = [part["slot"]+"."+d["key"] for d in modules[part["module_ref"]]["directions"]]
            if part["role"] == "core":
                body_keys = []
                for key in keys:
                    if key.rsplit(".", 1)[1] in {"head", "neck", "tail"}:
                        result.append({"id": key.rsplit(".", 1)[1], "weight": 1., "exchange": False,
                                       "chains": [{"channels": [key], "segment_weights": [1.]}]})
                    else:
                        body_keys.append(key)
                result.append({"id": "body", "weight": 1., "exchange": False,
                               "chains": [{"channels": body_keys, "segment_weights": [1.]*len(body_keys)}]})
            else:
                limbs.setdefault(part["role"], []).append((part, keys))
        for role, parts in limbs.items():
            slots = {p["slot"] for p, _ in parts}
            result.append({"id": {"forelimb": "front_legs", "hindlimb": "back_legs"}.get(role, role), "weight": 1.,
                           "exchange": any(slots == set(g["slots"]) for g in profile["exchange_groups"]),
                           "chains": [{"channels": keys, "segment_weights": [.4, .2, .4] if len(keys) == 3 else [1.]*len(keys)} for p, keys in parts]})
        return result

    cat["contracts"] = []
    for i, profile in enumerate(cat["profiles"]):
        gs = groups(profile)
        channels = [key for g in gs for c in g["chains"] for key in c["channels"]]
        cat["contracts"].append({"id": "whole."+profile["id"], "label": profile["label"]+" · 全部已存在部位（草案）",
                                 "status": "draft", "groups": gs, "projections": {profile["id"]: {key: key for key in channels}}, "context": {}})
        if i == 0:
            gs = groups(profile, True)
            keys = [key for g in gs for c in g["chains"] for key in c["channels"]]
            cat["contracts"].insert(0, {"id": "pony.body14@1", "label": "小马身体14方向（不比较翼）", "status": "confirmed",
                                      "groups": gs, "projections": {profile["id"]: {key: key for key in keys}},
                                      "context": {"view_parts": ["body", "head"], "layout_definitions": ["pony.body_midpoint_and_length@1"]}})
    cat["contracts"].append({"id": "cross_species.head_only@draft1", "label": "跨物种仅头部（草案）", "status": "draft",
                             "groups": [{"id": "head", "weight": 1., "exchange": False, "chains": [{"channels": ["head_facing"], "segment_weights": [1.]}]}],
                             "projections": {p["id"]: {"head_facing": "core.head"} for p in cat["profiles"]}, "context": {}})
    wings = [g for g in groups(cat["profiles"][0]) if g["id"] == "wing"]
    cat["contracts"].append({"id": "feather_wings@draft1", "label": "羽翼局部姿态（草案）", "status": "draft", "groups": wings,
                             "projections": {p["id"]: {k: k for g in wings for c in g["chains"] for k in c["channels"]} for p in cat["profiles"][:2]}, "context": {}})
    Catalog(cat)
    return cat


if __name__ == "__main__":
    target = ROOT/"data/meta/body_catalog_v2.json"
    if target.exists():
        raise SystemExit("目录已存在；新增定义请使用工作台目录导入，不覆盖版本")
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(target)
