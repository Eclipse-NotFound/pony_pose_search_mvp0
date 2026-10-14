"""Behavioral regressions from the data/algorithm review, using artificial poses."""
import copy
import importlib.util
import json
import math
import csv
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("m08_contract", ROOT / "scripts/m08/search_similar_poses.py")
m08 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m08)
RULES = json.loads((ROOT / "data/meta/keypoint_schemas.json").read_text(encoding="utf-8"))["schemas"]["pony_unicorn_no_wings_mvp0_v3"]["vector_rules"]


def leg(name, direction):
    return {"leg_id": name, "directions": {
        f"leg_direction{i}": {"available": True, "vector": list(direction)} for i in (1, 2)}}


def pose(direction):
    return {"available": {"head": True}, "head_direction": [1, 0],
            "front_legs": [leg("a", direction), leg("b", direction)], "back_legs": []}


@pytest.mark.parametrize("weight,expected", [(0, 1), (1, .5), (10, 1 / 11)])
def test_leg_group_slider_changes_ranking_contribution(weight, expected):
    score, _ = m08.compute_similarity_v2(pose([1, 0]), pose([-1, 0]), RULES,
                                        {"head": 1, "front_legs": weight})
    assert score == pytest.approx(expected)


def test_two_legs_share_one_group_budget():
    q = pose([1, 0])
    n, d, _ = m08.score_leg_group_v2(q["front_legs"], q["front_legs"], "front_legs", RULES, 3, 1)
    assert n == pytest.approx(3)
    assert d == pytest.approx(3)


def test_single_candidate_leg_is_assigned_once_and_ignores_slot_name():
    q = [leg("a", [1, 0]), leg("b", [-1, 0])]
    scores = []
    for name in ("a", "b", "unidentified"):
        n, d, _ = m08.score_leg_group_v2(q, [leg(name, [-1, 0])], "front_legs", RULES, 1, 1)
        scores.append(n / d)
    assert scores == pytest.approx([.5, .5, .5])


def test_strict_matching_does_not_select_another_leg():
    rules = copy.deepcopy(RULES)
    rules["front_legs"]["unordered_group"] = False
    n, d, _ = m08.score_leg_group_v2([leg("a", [1, 0])],
                                    [leg("a", [-1, 0]), leg("b", [1, 0])],
                                    "front_legs", rules, 1, 1)
    assert n / d == 0


@pytest.mark.parametrize("vector", [[math.nan, 0], [math.inf, 0], [0, 0], [1], ["1", 0]])
def test_invalid_direction_never_becomes_a_perfect_match(vector):
    assert m08.direction_similarity(vector, [1, 0]) is None


def test_vector_length_does_not_change_angle_score():
    assert m08.direction_similarity([2, 0], [.5, math.sqrt(3) / 2]) == pytest.approx(.75)


def test_mirror_is_opt_in_whole_pose_and_does_not_mutate_source():
    q = {"vectors": {"available": {"head": True}, "head_direction": [-1, 0]}}
    db = {"items": [{"sample_id": "one", "vectors": {
        "available": {"head": True}, "head_direction": [1, 0]}}]}
    original = copy.deepcopy(db)
    strict = m08.search(q, db, RULES, version="v2")[0]
    flipped = m08.search(q, db, RULES, version="v2", allow_mirror=True)[0]
    assert strict["similarity_score"] == 0 and strict["mirrored"] is False
    assert flipped["similarity_score"] == 1 and flipped["mirrored"] is True
    assert "左右翻转" in flipped["match_note"]
    assert db == original








