"""CLI for the same catalog, library and matcher used by the local workbench."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts/common"))
from multispecies import Library, DataError
from multispecies.catalog import load_json
from multispecies.importers import import_v1, import_predictions
from workflow import PoseWorkflow
from source_catalog import SourceCatalog, SourceService
from multispecies.training import training_snapshot


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--library", type=Path, default=ROOT/"data/pose_library_v2")
    p.add_argument("--catalog", type=Path, default=ROOT/"data/meta/body_catalog_v2.json")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    verify = sub.add_parser("verify")
    verify.add_argument("--output", type=Path)
    imp = sub.add_parser("import-v1")
    imp.add_argument("--input", type=Path, action="append", required=True)
    imp.add_argument("--project-root", type=Path, default=ROOT)
    imp.add_argument("--output", type=Path)
    cat = sub.add_parser("add-catalog")
    cat.add_argument("--input", type=Path, required=True)
    observation = sub.add_parser("import-record")
    observation.add_argument("--input", type=Path, required=True)
    observation.add_argument("--image", type=Path, required=True)
    prediction = sub.add_parser("import-predictions")
    prediction.add_argument("--observation", required=True)
    prediction.add_argument("--revision", required=True)
    prediction.add_argument("--capability", type=Path, required=True)
    prediction.add_argument("--values", type=Path, required=True)
    query = sub.add_parser("search")
    query.add_argument("--observation", required=True)
    query.add_argument("--contract", default="pony.body14@1")
    query.add_argument("--allow-mirror", action="store_true")
    query.add_argument("--allow-draft", action="store_true")
    query.add_argument("--include-unreviewed", action="store_true")
    query.add_argument("--output", type=Path, required=True)
    export = sub.add_parser("export-training")
    export.add_argument("--allow-draft", action="store_true")
    export.add_argument("--include-ungrouped", action="store_true")
    export.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    library = Library(args.library, default_catalog=args.catalog)
    if args.command == "init":
        result = {"library": str(library.root), "catalog_sha256": library.catalog.sha256}
    elif args.command == "verify":
        result = library.verify()
    elif args.command == "add-catalog":
        result = {"catalog_sha256": library.extend_catalog(load_json(args.input)).sha256}
    elif args.command == "import-v1":
        count = skipped = 0
        for path in args.input:
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.suffix == ".jsonl" else [load_json(path)]
            for old in records:
                _, added = import_v1(old, library, args.project_root)
                count += added
                skipped += not added
        result = {"imported": count, "already_present": skipped, "verification": library.verify()}
    elif args.command == "import-record":
        record = load_json(args.input)
        image = library.register_image(args.image)
        record["image_ref"], record["coordinates"]["image_size"] = image["id"], image["size"]
        result = library.save(record)
    elif args.command == "import-predictions":
        original = library.read(args.observation, args.revision)
        updated = import_predictions(original, library.catalog, load_json(args.capability), load_json(args.values))
        result = library.save(updated, expected_revision=args.revision)
    elif args.command == "search":
        sources = SourceCatalog(library.root/'sources')
        service = SourceService(sources, library)
        service.recover()
        workflow = PoseWorkflow(library, service)
        spec = workflow.prepare_query(args.observation, contract_ref=args.contract,
                                      options=dict(allow_mirror=args.allow_mirror, allow_draft=args.allow_draft,
                                                   include_unreviewed=args.include_unreviewed))
        result = workflow.search(spec['id'])
    else:
        result = training_snapshot(library, allow_draft=args.allow_draft, include_ungrouped=args.include_ungrouped)
    if getattr(args, "output", None):
        write(args.output, result)
    print(json.dumps(result if args.command not in {"export-training", "import-record", "import-predictions"} else
                     {"saved": str(getattr(args, "output", "")), "records": len(result.get("records", [])), "annotation": result.get("annotation", {}).get("id")}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (DataError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc))
