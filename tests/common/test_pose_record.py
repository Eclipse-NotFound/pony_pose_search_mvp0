import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/common"))
from pose_record import EDGES, from_legacy, validate, mirror_record, usable_for_search, layout_from_points
from pose_matching import compare, search_records
from pose_vector_utils import content_fingerprint, derivation_errors


def observation(character="twilight_unicorn"):
    sample = {"sample_id": "fixture", "character_id": character, "keypoints": {}}
    record = from_legacy(sample, source_path="synthetic-fixture", source_sha256="0" * 64)
    for direction in record["directions"].values():
        direction.update(value=[1., 0.], support="observed", visibility="visible", missing_reason=None)
    return record


def test_direction_record_does_not_require_points():
    record = observation()
    record.pop("reference_points")
    assert validate(record) == []
    assert compare(record, record)["direction_score"] == pytest.approx(1)


def test_identity_and_form_are_separate_without_inventing_wing_pose():
    unicorn, alicorn = observation(), observation("twilight_princess")
    assert unicorn["subject"]["character_id"] == alicorn["subject"]["character_id"]
    assert unicorn["subject"]["form_id"] != alicorn["subject"]["form_id"]
    assert alicorn["optional_parts"]["wings"] == {"present": True, "annotation": None}
    assert compare(unicorn, alicorn)["score"] == 1


def test_complete_asset_uses_occluded_parts_only_with_verified_access():
    q, s = observation(), observation()
    s["source"]["kind"] = "fla_frame"
    for direction in s["directions"].values():
        direction.update(visibility="occluded", support="asset_geometry")
    assert compare(q, s)["direction_score"] == 0
    s["asset_access"] = {"complete_character": "verified", "evidence_ref": "synthetic-render-check"}
    assert compare(q, s)["score"] == 1
    # The composite is still not visibly annotated, despite being searchable.
    assert all(d["visibility"] == "occluded" for d in s["directions"].values())


def test_complete_asset_without_evidence_is_rejected():
    s = observation()
    s["asset_access"]["complete_character"] = "verified"
    assert any("evidence_ref" in error for error in validate(s))


def test_unknown_view_is_not_called_a_known_match():
    result = compare(observation(), observation())
    assert result["score"] == 1
    assert result["compared_views"] == 0
    assert result["compared_layout_anchors"] == 0


def test_same_directions_can_be_distinguished_by_context():
    q, matching, different = observation(), observation(), observation()
    for r in (q, matching, different):
        r["view"].update(body="front", head="front")
        r["layout"]["anchors"] = {"head": [0, -1]}
    different["view"].update(body="rear", head="rear")
    different["layout"]["anchors"] = {"head": [0, 0]}
    a, b = compare(q, matching), compare(q, different)
    assert a["direction_score"] == b["direction_score"] == 1
    assert a["score"] == 1
    assert b["score"] == pytest.approx(.85)


def test_mirror_applies_to_both_directions_and_layout():
    q = observation()
    q["layout"]["anchors"] = {"head": [-1, -.5]}
    candidate = mirror_record(q)
    result = compare(q, candidate, allow_mirror=True)
    assert result["score"] == 1 and result["mirrored"]
    assert compare(q, candidate)["score"] == 0
    assert candidate["layout"]["anchors"]["head"][0] == 1


def test_translation_and_uniform_scale_do_not_change_layout():
    points = {"body.front": [10, 10], "body.rear": [30, 10], "head.center": [5, 0],
              "front.1.hoof": [8, 30], "front.2.hoof": [12, 30]}
    changed = {k: [3 * p[0] + 150, 3 * p[1] - 60] for k, p in points.items()}
    assert layout_from_points(points) == layout_from_points(changed)
    del points["front.2.hoof"]
    assert "front_feet" not in layout_from_points(points)["anchors"]


def test_unreviewed_is_preserved_and_not_indexed_by_default():
    q, candidate = observation(), observation()
    candidate["annotation"].update(origin="agent", review_status="unreviewed")
    assert search_records(q, [candidate]) == []
    assert len(search_records(q, [candidate], include_unreviewed=True)) == 1
    assert candidate["annotation"]["review_status"] == "unreviewed"


def test_bad_vector_is_rejected_before_matching():
    q = observation()
    q["directions"]["head"]["value"] = [float("nan"), 0]
    with pytest.raises(ValueError, match="finite unit vector"):
        compare(q, observation())


def test_legacy_null_is_not_relabelled_as_occlusion():
    record = from_legacy({"sample_id": "empty", "keypoints": {}},
                         source_path="fixture", source_sha256="0" * 64)
    assert set(record["directions"]) == set(EDGES)
    assert all(d["missing_reason"] == "legacy_unspecified" and d["visibility"] == "unknown"
               for d in record["directions"].values())
    assert compare(record, observation()) is None


def test_derived_data_detects_changed_points_and_rules():
    points, rules = {"point": [1, 2]}, {"from": "a", "to": "b"}
    derived = {"derivation": {"keypoints_content_sha256": content_fingerprint(points),
                               "rules_content_sha256": content_fingerprint(rules)}}
    assert derivation_errors(derived, points, rules) == []
    assert "keypoints changed" in derivation_errors(derived, {"point": [2, 2]}, rules)[0]
    assert "rules changed" in derivation_errors(derived, points, {"to": "a", "from": "b"})[0]
