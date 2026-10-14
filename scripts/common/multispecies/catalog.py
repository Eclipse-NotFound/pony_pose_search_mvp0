"""The catalog is the sole definition of body slots and comparison semantics."""
import copy
import hashlib
import json
import math
from pathlib import Path


class DataError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise DataError(message)


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def xy(x):
    return isinstance(x, (list, tuple)) and len(x) == 2 and all(number(v) for v in x)


def fingerprint(value):
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise DataError("JSON必须只包含有限数值与可保存的数据") from exc
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"重复JSON字段: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


class Catalog:
    """Validate once. Callers ask for channels or a named comparison contract."""

    def __init__(self, data):
        require(isinstance(data, dict) and data.get("schema_version") == "pose_catalog_v2", "不支持的身体目录版本")
        self.data = copy.deepcopy(data)
        self.tables = {}
        for name in ("characters", "species", "forms", "modules", "profiles", "contracts"):
            rows = data.get(name)
            require(isinstance(rows, list), f"目录 {name} 必须是列表")
            table = {}
            for row in rows:
                require(isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"], f"{name}: 缺少id")
                require(row["id"] not in table, f"{name}: 重复id {row['id']}")
                if name in {"forms", "modules", "profiles", "contracts"}:
                    require("@" in row["id"], f"{name}: 必须引用精确版本")
                table[row["id"]] = copy.deepcopy(row)
            self.tables[name] = table
        for module in self.tables["modules"].values():
            ds = module.get("directions")
            require(isinstance(ds, list) and ds, "模块必须定义方向")
            keys = []
            for d in ds:
                require(isinstance(d, dict) and isinstance(d.get("key"), str) and d["key"] and "." not in d["key"], "无效方向名")
                require(d.get("definition_ref") == module["id"] + "/" + d["key"], "方向必须引用所属模块的精确版本")
                require(d.get("from_semantic") and d.get("to_semantic") and d.get("coordinate_space") == "image_2d", "方向缺少起止语义或坐标定义")
                keys.append(d["key"])
            require(len(keys) == len(set(keys)), "重复模块方向")
        for profile in self.tables["profiles"].values():
            require(isinstance(profile.get("parts"), list) and profile["parts"], "身体必须定义部位")
            slots = []
            for part in profile["parts"]:
                require(isinstance(part, dict) and isinstance(part.get("slot"), str) and part["slot"] and "." not in part["slot"], "无效部位名")
                require(isinstance(part.get("role"), str) and part["role"], "部位缺少用途标签")
                self.get("modules", part.get("module_ref"))
                slots.append(part["slot"])
            require(len(slots) == len(set(slots)), "重复部位槽位")
            used = set()
            for group in profile.get("exchange_groups", []):
                group_slots = group.get("slots", [])
                require(isinstance(group_slots, list) and len(group_slots) >= 2 and len(set(group_slots)) == len(group_slots), "交换组至少包含两个不同部位")
                require(set(group_slots) <= set(slots) and not used.intersection(group_slots), "交换组有未知或重复部位")
                refs = {p["module_ref"] for p in profile["parts"] if p["slot"] in group_slots}
                require(len(refs) == 1 and group.get("mode") == "whole_chain", "只有同定义的整肢可以交换")
                used.update(group_slots)
        for form in self.tables["forms"].values():
            profile = self.get("profiles", form.get("profile_ref"))
            for table, ref in (("characters", "character_ref"), ("species", "species_ref")):
                if form.get(ref) is not None:
                    self.get(table, form[ref])
            states = form.get("expected_presence", {})
            require(isinstance(states, dict) and set(states) <= {p["slot"] for p in profile["parts"]}, "形态配置有未知部位")
            require(all(v in {"present", "absent", "unknown"} for v in states.values()), "形态存在性无效")
        for contract in self.tables["contracts"].values():
            self._validate_contract(contract)
        self.sha256 = fingerprint(self.data)

    @classmethod
    def read(cls, path):
        return cls(load_json(path))

    def get(self, table, key):
        require(isinstance(key, str) and key in self.tables[table], f"未知{table}引用: {key}")
        return self.tables[table][key]

    def channels(self, profile_ref):
        result = {}
        for part in self.get("profiles", profile_ref)["parts"]:
            for d in self.get("modules", part["module_ref"])["directions"]:
                key = part["slot"] + "." + d["key"]
                result[key] = {**d, "slot": part["slot"], "role": part["role"], "module_ref": part["module_ref"]}
        return result

    def _validate_contract(self, c):
        require(c.get("status") in {"confirmed", "draft"}, "比较约定状态无效")
        require(isinstance(c.get("groups"), list) and c["groups"], "比较约定缺少分组")
        channels, group_ids = [], []
        for group in c["groups"]:
            require(isinstance(group.get("id"), str) and group["id"], "比较组缺少id")
            require(number(group.get("weight")) and group["weight"] >= 0, "分组权重无效")
            require(isinstance(group.get("chains"), list) and group["chains"], "比较组缺少整肢")
            group_ids.append(group["id"])
            lengths = []
            for chain in group["chains"]:
                names, weights = chain.get("channels"), chain.get("segment_weights")
                require(isinstance(names, list) and names and all(isinstance(k, str) and k for k in names), "整肢方向无效")
                require(isinstance(weights, list) and len(weights) == len(names) and all(number(w) and w > 0 for w in weights), "分段权重无效")
                channels.extend(names)
                lengths.append(len(names))
            if group.get("exchange"):
                require(len(set(lengths)) == 1, "可交换整肢必须有相同分段")
        require(len(set(group_ids)) == len(group_ids) and len(set(channels)) == len(channels), "比较组或方向重复")
        require(any(g["weight"] > 0 for g in c["groups"]), "比较总权重不能为零")
        projections = c.get("projections")
        require(isinstance(projections, dict) and projections, "比较约定缺少结构映射")
        for profile_id, mapping in projections.items():
            available = self.channels(profile_id)
            require(isinstance(mapping, dict) and set(mapping) == set(channels), "比较映射必须完整覆盖所选语义")
            require(set(mapping.values()) <= set(available) and len(set(mapping.values())) == len(mapping), "比较映射指向未知或重复方向")
            profile = self.get("profiles", profile_id)
            for group in c["groups"]:
                if not group.get("exchange"):
                    continue
                slots, modules = [], []
                for chain in group["chains"]:
                    actual = [available[mapping[k]] for k in chain["channels"]]
                    require(len({d["slot"] for d in actual}) == 1, "不能将不同腿拼成整肢")
                    slots.append(actual[0]["slot"])
                    modules.append(actual[0]["module_ref"])
                require(len(set(slots)) == len(slots) and len(set(modules)) == 1, "不兼容整肢交换")
                require(any(set(slots) <= set(g["slots"]) for g in profile.get("exchange_groups", [])), "身体说明书未允许这组交换")

    def extended(self, additions):
        """Append definitions. Existing version IDs may never change meaning."""
        data = copy.deepcopy(self.data)
        for table, rows in additions.items():
            require(table in self.tables and isinstance(rows, list), "只能追加目录条目")
            for row in rows:
                existing = self.tables[table].get(row.get("id"))
                if existing is not None:
                    require(existing == row, "已有版本不可改写，请使用新版本id")
                else:
                    data[table].append(copy.deepcopy(row))
        return Catalog(data)
