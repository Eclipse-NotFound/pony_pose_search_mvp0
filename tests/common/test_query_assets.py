import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/common"))
from query_assets import query_image_destination, resolve_query_image


def test_new_queries_do_not_share_image_destinations(tmp_path):
    a = query_image_destination(tmp_path, "c", "q1")
    b = query_image_destination(tmp_path, "c", "q2")
    assert a != b
    shared = tmp_path / "queries/c/query_input.png"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"shared")
    assert resolve_query_image(tmp_path, "c", "q1") == a


def test_missing_declared_image_does_not_use_unrelated_shared_image(tmp_path):
    folder = tmp_path / "queries/c/q1"
    folder.mkdir(parents=True)
    (folder.parent / "query_input.png").write_bytes(b"other query")
    (folder / "query_keypoints.json").write_text(json.dumps({"query_image_path": "queries/c/q1/lost.png"}))
    assert Path(resolve_query_image(tmp_path, "c", "q1")) == folder / "lost.png"


def test_explicit_legacy_source_remains_readable_until_independent_copy_exists(tmp_path):
    folder = tmp_path / "queries/c/q1"
    folder.mkdir(parents=True)
    shared = folder.parent / "query_input.png"
    shared.write_bytes(b"declared")
    (folder / "query_keypoints.json").write_text(json.dumps({"query_image_path": "queries/c/query_input.png"}))
    assert Path(resolve_query_image(tmp_path, "c", "q1")) == shared
    owned = folder / "query_input.png"
    owned.write_bytes(b"owned")
    assert Path(resolve_query_image(tmp_path, "c", "q1")) == owned
