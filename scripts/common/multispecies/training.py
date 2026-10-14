"""Freeze reviewed labels and keep linked shots/assets/images in the same split."""
import copy
import hashlib

from .catalog import fingerprint, require
from .records import now, usable, validate_observation


def training_snapshot(library, *, collections=("official", "manual"), allow_draft=False, include_ungrouped=False, seed="pose-v2"):
    catalog, assets = library.catalog, library.assets
    entries, excluded = [], []
    for record in library.records(collections):
        validate_observation(record, catalog, assets)
        reason = None
        channels = catalog.channels(record["profile_ref"])
        if record.get("example_only") or record.get("test_only") or record["collection"] in {"query", "test"}:
            reason = "synthetic_or_query"
        elif assets[record["image_ref"]]["issues"]:
            reason = "image_issue"
        else:
            try:
                library.image_bytes(record["image_ref"])
            except ValueError:
                reason = "image_changed_or_missing"
        values, mask = [], []
        for key, definition in channels.items():
            d = record["annotation"]["directions"].get(key)
            known = usable(record, key, reviewed_only=True)
            # An occluded composite is not an unobstructed-image training example.
            if d and d["visibility"] in {"occluded", "out_of_frame"}:
                known = False
            if not allow_draft and definition.get("rule_status") != "legacy_equivalent":
                known = False
            values.append(copy.deepcopy(d["value"]) if known else None)
            mask.append(known)
        if not any(mask):
            reason = reason or "no_approved_supported_directions"
        groups = ["shot:"+record["split_groups"]["shot_ref"]] if record["split_groups"].get("shot_ref") else []
        if record["split_groups"].get("asset_family_ref"):
            groups.append("asset:"+record["split_groups"]["asset_family_ref"])
        if not groups and not include_ungrouped:
            reason = reason or "group_not_confirmed"
        if reason:
            excluded.append({"observation_id": record["observation_id"], "reason": reason})
            continue
        entries.append({"observation_id": record["observation_id"], "annotation_id": record["annotation"]["id"],
                        "image_ref": record["image_ref"], "image_path": assets[record["image_ref"]]["path"],
                        "image_sha256": assets[record["image_ref"]]["sha256"], "profile_ref": record["profile_ref"],
                        "channel_order": list(channels), "values": values, "mask": mask, "weight": 1.,
                        "observation": copy.deepcopy(record),
                        "review_status": {k: record["annotation"]["directions"][k]["review_status"] for k, flag in zip(channels, mask) if flag},
                        "group_confirmed": bool(groups), "links": groups + ["image:"+record["image_ref"], "occurrence:"+record["occurrence_id"]]})
    assign_splits(entries, seed)
    body = {"schema_version": "pose_training_snapshot_v2", "catalog_sha256": catalog.sha256,
            "catalog": catalog.data, "generator": "multispecies.training@1", "seed": seed,
            "options": {"collections": list(collections), "allow_draft": allow_draft, "include_ungrouped": include_ungrouped},
            "records": entries, "excluded": excluded}
    body["snapshot_sha256"] = fingerprint(body)
    body["created_at"] = now()
    return body


def assign_splits(entries, seed):
    """Shared split policy for direction, point and detection snapshots."""
    parents = {}

    def root(x):
        parents.setdefault(x, x)
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    for entry in entries:
        first = entry["links"][0]
        for link in entry["links"][1:]:
            a, b = root(first), root(link)
            if a != b:
                parents[max(a, b)] = min(a, b)
    unknown_groups = {root(e["links"][0]) for e in entries if not e["group_confirmed"]}
    for entry in entries:
        group = root(entry["links"][0])
        entry["split_group"] = fingerprint(group)
        value = int(hashlib.sha256((seed+":"+group).encode()).hexdigest()[:8], 16)/2**32
        entry["split"] = "unassigned" if group in unknown_groups else "train" if value < .8 else "validation" if value < .9 else "test"
