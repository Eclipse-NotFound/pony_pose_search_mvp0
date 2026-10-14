import copy
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import sys

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts/common"))
from multispecies import Catalog, DataError, Library, ConflictError, new_observation, validate_observation
from multispecies.records import revise, transform_direction, usable
from multispecies.matching import compare, search, _assignment
from multispecies.importers import import_v1, import_predictions, LEGACY_MAPPING
from multispecies.training import training_snapshot
from pose_record import from_legacy
from pose_matching import compare as old_compare


@pytest.fixture
def cat():
    return Catalog.read(ROOT/"data/meta/body_catalog_v2.json")


@pytest.fixture
def library(tmp_path, cat):
    return Library(tmp_path/"library", default_catalog=cat)


@pytest.fixture
def asset(tmp_path, library):
    im = Image.new("RGB", (64, 48), "white")
    im.putpixel((1, 1), (50, 100, 150))
    path = tmp_path/"image.png"
    im.save(path)
    return library.register_image(path)


def labeled(cat, asset, profile="pony.quadruped@2draft1", wings=False, approved=True):
    r = new_observation(cat, profile_ref=profile, image_ref=asset["id"], image_size=asset["size"], actor="fixture")
    parts = {key: {"presence": "absent" if key.startswith("wing") and not wings else "present"} for key in r["annotation"]["parts"]}
    r = revise(r, cat, {"parts": parts}, actor="fixture")
    values = {key: {"value": [1., 0.], "visibility": "visible"} for key in r["annotation"]["directions"]}
    targets = ["parts."+k for k in r["annotation"]["parts"]]+["directions."+k for k in values]
    r = revise(r, cat, {"directions": values}, actor="fixture", review={"targets": targets, "status": "approved"} if approved else None)
    r["annotation"]["parent_ids"] = []  # Independent initial fixture snapshot, no fake library parents.
    return r


def test_catalog_four_bodies_and_optional_parts(cat, asset):
    counts = []
    for profile in cat.tables["profiles"]:
        record = labeled(cat, asset, profile, wings=True)
        validate_observation(record, cat)
        counts.append(len(record["annotation"]["directions"]))
    assert counts == [18, 18, 18, 19]
    assert len(labeled(cat, asset)["annotation"]["directions"]) == 14


def test_new_observation_does_not_treat_form_prior_as_fact(cat, asset):
    r = new_observation(cat, profile_ref="pony.quadruped@2draft1", image_ref=asset["id"], image_size=asset["size"],
                        character_ref="twilight_sparkle", form_ref="twilight.alicorn@1")
    assert all(p["presence"] == "unknown" for p in r["annotation"]["parts"].values())
    assert r["annotation"]["directions"] == {}


@pytest.mark.parametrize("edit", [
    lambda r: r["annotation"]["directions"]["core.head"].update(value=[float("nan"), 0]),
    lambda r: r["annotation"]["directions"]["core.head"].update(value=[True, 0]),
    lambda r: r["annotation"]["directions"]["core.head"].update(value=[0, 0]),
    lambda r: r["annotation"]["directions"]["core.head"].update(value=[3, 0]),
    lambda r: r["annotation"]["directions"]["core.head"].update(value=None, missing_reason=None),
    lambda r: r["annotation"]["directions"]["core.head"].update(evidence_refs=["missing"]),
    lambda r: r["annotation"]["parts"]["fore_a"].update(presence="absent"),
    lambda r: r["annotation"].update(review_events=[]),
    lambda r: r.update(profile_ref="unknown"),
    lambda r: r["asset_access"].update(complete_character="verified", evidence_refs=[]),
    lambda r: r["subject"].update(character_ref="not_registered"),
    lambda r: r["coordinates"].update(image_size=[0, 20]),
    lambda r: r["source"].update(fps=[24, 0]),
    lambda r: r.update(example_only=True),
])
def test_invalid_records_cannot_be_saved(cat, asset, library, edit):
    r = labeled(cat, asset)
    edit(r)
    with pytest.raises(DataError):
        library.save(r)
    assert library.records() == []


def test_catalog_prevents_shape_and_semantic_aliases(cat):
    bad = copy.deepcopy(cat.data)
    bad["profiles"][-1]["exchange_groups"] = [{"slots": ["fore_a", "fore_b"], "mode": "whole_chain"}]
    with pytest.raises(DataError, match="整肢"):
        Catalog(bad)
    modified = copy.deepcopy(cat.data["modules"][0])
    modified["label"] = "different meaning"
    with pytest.raises(DataError, match="新版本"):
        cat.extended({"modules": [modified]})
    bad = copy.deepcopy(cat.data)
    bad["contracts"][0]["projections"]["pony.quadruped@2draft1"]["core.head"] = "core.neck"
    with pytest.raises(DataError, match="重复方向"):
        Catalog(bad)


def test_partial_review_and_edit_history(cat, asset, library):
    original = labeled(cat, asset, approved=False)
    library.save(original)
    key = original["observation_id"]
    reviewed = library.edit(key, original["annotation"]["id"], {}, actor="reviewer", review={"status": "approved", "targets": ["directions.core.head", "parts.core"]})
    assert usable(reviewed, "core.head", reviewed_only=True)
    assert not usable(reviewed, "core.neck", reviewed_only=True)
    changed = library.edit(key, reviewed["annotation"]["id"], {"directions": {"core.head": {"reference_points": {"start": [20, 20], "end": [20, 10]}}}}, actor="editor")
    assert changed["annotation"]["directions"]["core.head"]["value"] == [0, -1]
    assert changed["annotation"]["directions"]["core.head"]["review_status"] == "unreviewed"
    assert library.read(key, original["annotation"]["id"]) == original
    assert len(library.history(key)) == 3


def test_conflicts_and_idempotent_retry_cannot_roll_back_head(cat, asset, library):
    original = labeled(cat, asset)
    library.save(original)
    def attempt(x):
        try:
            return library.edit(original["observation_id"], original["annotation"]["id"], {"directions": {"core.head": {"value": x}}}, actor="test")
        except ConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ([0, 1], [0, -1])))
    assert outcomes.count("conflict") == 1
    head = library.head_id(original["observation_id"])
    library.save(original)
    assert library.head_id(original["observation_id"]) == head


def test_whole_chain_exchange_and_fixed_missing_denominator(cat, asset):
    q = labeled(cat, asset)
    c = copy.deepcopy(q)
    for prefix in ("fore_a", "fore_b"):
        for seg in ("upper", "lower"):
            q["annotation"]["directions"][prefix+"."+seg]["value"] = [1, 0] if prefix == "fore_a" else [-1, 0]
            c["annotation"]["directions"][prefix+"."+seg]["value"] = [-1, 0] if prefix == "fore_a" else [1, 0]
    weights = {g["id"]: 1 if g["id"] == "front_legs" else 0 for g in cat.get("contracts", "pony.body14@1")["groups"]}
    options = {"contract_ref": "pony.body14@1", "group_weights": weights}
    best = compare(q, c, cat, **options)
    assert best["score"] == 1 and best["assignment"]["fore_a.upper"] == "fore_b.upper"
    assert compare(q, c, cat, allow_whole_limb_exchange=False, **options)["score"] == 0
    for d in c["annotation"]["directions"].values():
        d.update(value=None, missing_reason="not_annotated")
    c["annotation"]["directions"]["fore_b.upper"].update(value=[1, 0], missing_reason=None)
    sparse = compare(q, c, cat, **options)
    assert sparse["candidate_coverage"] == .25 and sparse["score"] == .25
    assert len(set(sparse["assignment"].values())) == len(sparse["assignment"])


def test_cannot_assemble_one_limb_from_two_candidates(cat, asset):
    q = labeled(cat, asset)
    c = copy.deepcopy(q)
    for slot in ("fore_a", "fore_b"):
        q["annotation"]["directions"][slot+".lower"]["value"] = [0, 1]
    c["annotation"]["directions"]["fore_a.lower"]["value"] = [0, -1]
    c["annotation"]["directions"]["fore_b.upper"]["value"] = [-1, 0]
    c["annotation"]["directions"]["fore_b.lower"]["value"] = [0, 1]
    weights = {g["id"]: int(g["id"] == "front_legs") for g in cat.get("contracts", "pony.body14@1")["groups"]}
    assert compare(q, c, cat, contract_ref="pony.body14@1", group_weights=weights)["direction_score"] == .5


def test_mirror_default_off_and_strict_unknown_identity(cat, asset):
    q, c = labeled(cat, asset), labeled(cat, asset)
    for d in c["annotation"]["directions"].values():
        d["value"] = [-1, 0]
    options = {"contract_ref": "pony.body14@1"}
    assert compare(q, c, cat, **options)["score"] == 0
    result = compare(q, c, cat, allow_mirror=True, **options)
    assert result["score"] == 1 and result["mirrored"]
    strict = compare(q, q, cat, strict_identity=True, **options)
    assert strict["candidate_compared"] == 4


def test_draft_explicit_scope_and_absent_wing(cat, asset):
    pony, griffon = labeled(cat, asset, wings=True), labeled(cat, asset, "griffon.quadruped@draft1", wings=True)
    assert compare(pony, griffon, cat, contract_ref="pony.body14@1")["status"] == "incompatible"
    with pytest.raises(DataError, match="草案"):
        compare(pony, griffon, cat, contract_ref="cross_species.head_only@draft1")
    partial = compare(pony, griffon, cat, contract_ref="cross_species.head_only@draft1", allow_draft=True)
    assert partial["candidate_compared"] == partial["query_requested"] == 1
    no_wing = labeled(cat, asset)
    absent = compare(pony, no_wing, cat, contract_ref="feather_wings@draft1", allow_draft=True)
    assert absent["status"] == "not_applicable"
    assert compare(pony, no_wing, cat, contract_ref="pony.body14@1")["score"] == 1
    result = compare(no_wing, no_wing, cat, contract_ref="whole.pony.quadruped@2draft1", allow_draft=True)
    assert result["query_coverage"] == 1 and len(result["query_not_applicable"]) == 4


def test_hidden_asset_directions_need_aligned_evidence(cat, asset):
    q, c = labeled(cat, asset), labeled(cat, asset)
    for d in c["annotation"]["directions"].values():
        d["visibility"] = "occluded"
    assert compare(q, c, cat, contract_ref="pony.body14@1")["candidate_compared"] == 0
    evidence = {"id": "asset_evidence", "kind": "asset", "project_path": "fixture.fla", "instance_path": "layer/pony", "alignment_ref": "fixture_alignment",
                "image_ref": c["image_ref"], "occurrence_ref": c["occurrence_id"],
                "verified_by": "fixture", "verified_at": "fixture", "frame_index": 0, "transform": [1, 0, 0, 1, 0, 0]}
    c["evidence"].append(evidence)
    c["asset_access"] = {"complete_character": "verified", "evidence_refs": ["asset_evidence"]}
    for d in c["annotation"]["directions"].values():
        d["evidence_refs"] = ["asset_evidence"]
    assert compare(q, c, cat, contract_ref="pony.body14@1")["score"] == 1
    assert all(d["visibility"] == "occluded" for d in c["annotation"]["directions"].values())


def test_model_capability_and_transform_never_approve(cat, asset):
    original = labeled(cat, asset)
    manifest = {"id": "model@1", "model_sha256": "0"*64, "coordinate_space": "image_2d",
                "profiles": {original["profile_ref"]: {"head": "core.head"}}}
    updated = import_predictions(original, cat, manifest, {"head": [1, 1]}, affine=[2, 0, 0, 1, 20, 30])
    assert updated["annotation"]["directions"]["core.head"]["value"] == pytest.approx([2/math.sqrt(5), 1/math.sqrt(5)])
    assert updated["annotation"]["directions"]["core.head"]["review_status"] == "unreviewed"
    assert updated["annotation"]["directions"]["core.neck"]["review_status"] == "approved"
    with pytest.raises(DataError, match="未声明"):
        import_predictions(original, cat, manifest, {"wing": [0, 1]})
    with pytest.raises(DataError):
        transform_direction([1, 0], [0, 0, 0, 0, 0, 0])


def test_migration_preserves_vectors_and_legacy_scores(cat, library, asset, tmp_path):
    records, olds = [], []
    for i in range(2):
        old = from_legacy({"sample_id": f"old_{i}", "crop_path": asset["path"], "keypoints": {}}, source_path="source.json", source_sha256="1"*64)
        for j, d in enumerate(old["directions"].values()):
            angle = (j*23 + i*47)*math.pi/180
            d.update(value=[math.cos(angle), math.sin(angle)], missing_reason=None, support="observed", visibility="visible")
        imported, added = import_v1(old, library, tmp_path)
        assert added
        for key, mapped in LEGACY_MAPPING.items():
            assert imported["annotation"]["directions"][mapped]["value"] == old["directions"][key]["value"]
        records.append(imported); olds.append(old)
    assert compare(*records, cat, contract_ref="pony.body14@1")["score"] == pytest.approx(old_compare(*olds)["score"])
    old = copy.deepcopy(olds[0]); old["annotation"]["source_sha256"] = "2"*64; old["record_id"] = "another_global_file_hash"
    second_library = Library(tmp_path/"second", default_catalog=cat)
    converted, _ = import_v1(old, second_library, tmp_path)
    assert converted["observation_id"] == records[0]["observation_id"]
    assert import_v1(olds[0], library, tmp_path)[1] is False


def test_training_groups_masks_and_asset_fingerprints(cat, library, asset):
    first, second = labeled(cat, asset), labeled(cat, asset)
    first["split_groups"] = {"shot_ref": "shot_a", "asset_family_ref": "rig_a"}
    second["split_groups"] = {"shot_ref": "shot_b", "asset_family_ref": "rig_a"}
    second["annotation"]["directions"]["core.head"]["review_status"] = "unreviewed"
    library.save(first); library.save(second)
    snapshot = training_snapshot(library)
    entries = snapshot["records"]
    assert len(entries) == 2 and entries[0]["split"] == entries[1]["split"]
    assert sum(sum(e["mask"]) for e in entries) == 27
    assert snapshot["snapshot_sha256"] == training_snapshot(library)["snapshot_sha256"]
    Path(asset["path"]).write_bytes(b"changed")
    assert training_snapshot(library)["records"] == []


def test_unknown_groups_are_quarantined_and_all_empty_queries_rejected(cat, library, asset):
    record = labeled(cat, asset)
    library.save(record)
    assert training_snapshot(library)["records"] == []
    assert training_snapshot(library, include_ungrouped=True)["records"][0]["split"] == "unassigned"
    empty = new_observation(cat, profile_ref=record["profile_ref"], image_ref=asset["id"], image_size=asset["size"])
    with pytest.raises(DataError, match="没有可用"):
        search(empty, [], cat, contract_ref="pony.body14@1")


def test_assignment_scales_beyond_bilateral_limbs():
    n = 24
    scores = [[int(j == n-i-1) for j in range(n)] for i in range(n)]
    assert _assignment(scores) == list(reversed(range(n)))


def test_optional_points_and_geometry_context_are_not_stale(cat, asset):
    record = labeled(cat, asset)
    record["annotation"].update(reference_points=None, layout={"definition_ref": "fixture@1", "anchors": {"body": [0, 0]}})
    validate_observation(record, cat)
    changed = revise(record, cat, {"directions": {"core.head": {"value": [0, 1]}}}, actor="fixture")
    assert changed["annotation"]["reference_points"] == {}
    assert changed["annotation"]["layout"] is None
    capability = {"id": "fixture@1", "model_sha256": "1"*64, "coordinate_space": "image_2d", "profiles": {record["profile_ref"]: {"head": "core.head"}}}
    prediction = import_predictions(record, cat, capability, {"head": [1, 0]})
    assert prediction["annotation"]["layout"] is None
    with pytest.raises(DataError, match="SHA256"):
        import_predictions(record, cat, dict(capability, model_sha256="not-a-hash"), {})


def test_test_records_remain_isolated_across_revisions(cat, library, asset):
    record = labeled(cat, asset)
    record["test_only"] = True
    library.save(record)
    changed = revise(record, cat, {}, actor="fixture")
    changed["test_only"] = False
    with pytest.raises(DataError, match="隔离"):
        library.save(changed, expected_revision=record["annotation"]["id"])
    assert training_snapshot(library, include_ungrouped=True)["records"] == []
    assert search(labeled(cat, asset), [record], cat, contract_ref="pony.body14@1")["results"] == []
    with pytest.raises(DataError, match="修改必须"):
        revise(record, cat, {"directions": None}, actor="fixture")
