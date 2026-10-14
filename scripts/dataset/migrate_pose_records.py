"""Read existing labels; write independent, fingerprinted direction-first records."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m06"))
from pose_record import from_legacy, validate
from generate_pose_vectors import generate_pose_vectors


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unflatten(points):
    if len(points) != 21:
        raise ValueError("expected the documented 21-point legacy ordering")
    result = {"head": dict(zip(["head_center", "head_front", "neck"], points[:3])),
              "body": dict(zip(["body_1", "body_2"], points[3:5])),
              "tail": dict(zip(["tail_base", "tail_end"], points[19:21]))}
    offset = 5
    for group, fields, prefix in (("front_legs", ["base", "mid", "end"], "front_leg"),
                                  ("back_legs", ["base", "knee", "mid", "end"], "back_leg")):
        result[group] = []
        for i in (1, 2):
            result[group].append({"leg_id": f"{prefix}_{i}", **dict(zip(fields, points[offset:offset+len(fields)]))})
            offset += len(fields)
    return result


def migrate(root, output):
    root, output = root.resolve(), output.resolve()
    if output == root or not output.is_relative_to(root / "experiments"):
        raise ValueError("migration output must be a dedicated project experiments subdirectory")
    output.mkdir(parents=True, exist_ok=True)
    fingerprints, missing_images, image_issues = {}, [], []

    def fingerprint(path):
        key = path.relative_to(root).as_posix()
        fingerprints.setdefault(key, sha(path))
        return fingerprints[key]

    def convert(sample, source, **options):
        image_path = sample.get("crop_path", sample.get("query_image_path"))
        image = root / image_path if image_path else None
        size, image_sha = None, None
        if image and image.is_file():
            with Image.open(image) as im:
                size = list(im.size)
                if all(low == high for low, high in im.convert("RGB").getextrema()):
                    image_issues.append({"sample": sample.get("sample_id", sample.get("query_id")),
                                         "path": image_path, "issue": "constant_color_image"})
            image_sha = fingerprint(image)
        else:
            missing_images.append({"sample": sample.get("sample_id", sample.get("query_id")), "path": image_path})
        record = from_legacy(sample, source_path=source.relative_to(root).as_posix(),
                             source_sha256=fingerprint(source), image_size=size, **options)
        record["source"]["image_sha256"] = image_sha
        record["dataset_groups"] = {"episode_id": sample.get("episode_id"), "shot_id": None,
                                     "asset_family_id": None}
        errors = validate(record)
        if errors:
            raise ValueError(f"{record['sample_id']}: {errors}")
        return record

    def write(name, data):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    def write_records(name, records):
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records), encoding="utf-8")

    official, drift = [], []
    schemas_path = root / "data/meta/keypoint_schemas.json"
    schemas = read(schemas_path)
    fingerprint(schemas_path)
    for source in sorted((root / "keypoints").rglob("*.json")):
        original = read(source)
        for sample in original.get("items", []):
            official.append(convert(sample, source))
        for version in ("v1", "v2"):
            generated = generate_pose_vectors(original, schemas, version)
            name = source.name.replace("keypoints_", "pose_vectors_")
            if version == "v2":
                name = name.replace(".json", "_v2.json")
            old_path = root / "poses" / source.relative_to(root / "keypoints").parent / name
            old = read(old_path) if old_path.exists() else {"items": []}
            if old_path.exists():
                fingerprint(old_path)
            old_items = {r["sample_id"]: r for r in old["items"]}
            new_items = {r["sample_id"]: r for r in generated["items"]}
            changed = [key for key in old_items.keys() & new_items.keys()
                       if old_items[key]["vectors"] != new_items[key]["vectors"]]
            drift.append({"source": source.relative_to(root).as_posix(), "version": version,
                          "old_count": len(old_items), "current_count": len(new_items),
                          "missing_sample_ids": sorted(new_items.keys() - old_items.keys()),
                          "extra_sample_ids": sorted(old_items.keys() - new_items.keys()),
                          "changed_vectors": sorted(changed)})
            write("regenerated_legacy/" + name, generated)
    write_records("official_records.jsonl", official)

    queries = []
    for source in sorted((root / "queries").rglob("query_keypoints.json")):
        record = convert(read(source), source, origin="query", review_status="query_input")
        write("queries/" + source.parent.name + ".json", record)
        queries.append(record)

    experiment = root / "experiments/direction_scaling_20261009/dataset.json"
    experimental = []
    if experiment.exists():
        for entry in read(experiment)["records"]:
            fid = entry["frame_id"]
            sample = {"sample_id": Path(entry["image"]).stem, "frame_id": fid,
                      "episode_id": fid[:6], "character_id": "twilight_unicorn",
                      "timestamp_sec": int(fid.split("_t")[1].split("_")[0]),
                      "crop_path": entry["image"], "keypoints": unflatten(entry["points"]),
                      "note": entry.get("notes", "")}
            human = entry["source"] == "human_official"
            record = convert(sample, experiment, origin="human" if human else "agent",
                             review_status="legacy_official" if human else "unreviewed")
            record["legacy_experiment"] = {key: entry[key] for key in ("split", "source", "weight", "regimes") if key in entry}
            experimental.append(record)
        write_records("experimental_records.jsonl", experimental)

    all_records = official + experimental + queries
    if len({r["record_id"] for r in all_records}) != len(all_records):
        raise ValueError("record id collision")
    summary = {
        "schema_version": "pose_record_v1", "official_records": len(official),
        "query_records": len(queries), "experimental_records": len(experimental),
        "experimental_review_states": dict(Counter(r["annotation"]["review_status"] for r in experimental)),
        "official_empty_records": [r["sample_id"] for r in official if all(d["value"] is None for d in r["directions"].values())],
        "view_labels_inferred": 0,
        "official_with_layout": sum(bool(r["layout"]["anchors"]) for r in official),
        "missing_images": missing_images, "image_issues": image_issues, "legacy_vector_drift": drift,
        "source_hashes": fingerprints,
        "boundaries": ["official and experimental records are separate snapshots, not a merged training dataset",
                       "no new labels or view categories inferred; legacy missing reasons remain unspecified",
                       "no FLA-derived pose labels imported; alicorn behavior is checked with synthetic contract fixtures"],
    }
    changes = [name for name, expected in fingerprints.items() if sha(root / name) != expected]
    summary["source_changes_during_migration"] = changes
    if changes:
        raise RuntimeError(f"sources changed during migration: {changes}")
    write("migration-report.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.project_root / "experiments/schema_review_20261011/migrated"
    summary = migrate(args.project_root, output)
    print(json.dumps({k: summary[k] for k in ("official_records", "experimental_records", "query_records",
                                             "experimental_review_states", "missing_images")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
