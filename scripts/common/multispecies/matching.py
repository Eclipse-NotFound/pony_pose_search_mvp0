"""Explicit projections and one-to-one whole-chain matching for variable bodies."""
import copy
import math

from .catalog import require, number
from .records import usable, validate_observation


def _assignment(values):
    """Maximum-weight square assignment, O(n^3), deterministic ties. No limb cap."""
    n = len(values)
    if not n:
        return []
    u, v, p, way = [0.]*(n+1), [0.]*(n+1), [0]*(n+1), [0]*(n+1)
    for row in range(1, n+1):
        p[0], col = row, 0
        distances, used = [float("inf")]*(n+1), [False]*(n+1)
        while True:
            used[col] = True
            i, delta, next_col = p[col], float("inf"), 0
            for j in range(1, n+1):
                if used[j]:
                    continue
                cost = -values[i-1][j-1] - u[i] - v[j]
                if cost < distances[j]:
                    distances[j], way[j] = cost, col
                if distances[j] < delta:
                    delta, next_col = distances[j], j
            for j in range(n+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    distances[j] -= delta
            col = next_col
            if p[col] == 0:
                break
        while col:
            last = way[col]
            p[col], col = p[last], last
    result = [0]*n
    for j in range(1, n+1):
        result[p[j]-1] = j-1
    return result


def _same_identity(query, candidate, qkey, ckey):
    qi = query["annotation"]["parts"][qkey.split(".")[0]]["identity"]
    ci = candidate["annotation"]["parts"][ckey.split(".")[0]]["identity"]
    known = [(qi.get(k), ci.get(k)) for k in ("anatomical_side", "camera_depth") if qi.get(k) is not None and ci.get(k) is not None]
    return bool(known) and all(a == b for a, b in known)


def compare(query, candidate, catalog, *, contract_ref, allow_mirror=False,
            allow_whole_limb_exchange=True, strict_identity=False, include_unreviewed=False,
            allow_draft=False, group_weights=None, view_weight=.10, layout_weight=.05):
    validate_observation(query, catalog)
    validate_observation(candidate, catalog)
    contract = catalog.get("contracts", contract_ref)
    require(allow_draft or contract["status"] == "confirmed", "此比较约定尚为草案；需明确开启草案试用")
    for name, value in (("view_weight", view_weight), ("layout_weight", layout_weight)):
        require(number(value) and 0 <= value <= .25, f"{name}必须在0与0.25之间")
    require(view_weight+layout_weight <= .25, "辅助项总权重不能超过0.25")
    group_weights = group_weights or {}
    require(isinstance(group_weights, dict) and set(group_weights) <= {g["id"] for g in contract["groups"]}, "有未知比较组权重")
    require(all(number(v) and v >= 0 for v in group_weights.values()), "权重必须是有限非负数")
    projections = contract["projections"]
    require(query["profile_ref"] in projections, "查询的身体结构不适用此比较约定")
    qm = projections[query["profile_ref"]]
    if candidate["profile_ref"] not in projections:
        return {"status": "incompatible", "contract_ref": contract_ref, "reason": "未定义该身体之间的对应"}
    cm = projections[candidate["profile_ref"]]
    q_known = {k for k, actual in qm.items() if usable(query, actual)}
    requested, query_absent, query_weight = [], [], 0.
    prepared = []
    for group in contract["groups"]:
        budget = group_weights.get(group["id"], group["weight"])
        if budget == 0:
            continue
        chains = group["chains"]
        for chain in chains:
            for key in chain["channels"]:
                presence = query["annotation"]["parts"][qm[key].split(".")[0]]["presence"]
                (query_absent if presence == "absent" else requested).append(key)
        active = sum(any(k in q_known for k in chain["channels"]) for chain in chains)
        if not active:
            continue
        weights = [{k: budget*w/(active*sum(chain["segment_weights"])) for k, w in zip(chain["channels"], chain["segment_weights"])} for chain in chains]
        query_weight += sum(w for row in weights for k, w in row.items() if k in q_known)
        prepared.append((group, weights))
    require(query_weight > 0, "查询没有可用且权重为正的方向")

    def evaluate(mirrored):
        numerator, covered_weight = 0., 0.
        matched, mapping, inapplicable = [], {}, []
        for group, weights in prepared:
            chains = group["chains"]
            n = len(chains)

            def pair(i, j):
                score, covered, hits, missing_parts = 0., 0., [], []
                pairs = []
                for qkey, ckey in zip(chains[i]["channels"], chains[j]["channels"]):
                    if qkey not in q_known:
                        continue
                    actual_q, actual_c = qm[qkey], cm[ckey]
                    pairs.append((actual_q, actual_c))
                    part = candidate["annotation"]["parts"][actual_c.split(".")[0]]
                    if part["presence"] == "absent":
                        missing_parts.append(actual_c.split(".")[0])
                    identity_ok = not strict_identity or not group.get("exchange") or _same_identity(query, candidate, actual_q, actual_c)
                    if usable(candidate, actual_c, reviewed_only=not include_unreviewed) and identity_ok:
                        q = query["annotation"]["directions"][actual_q]["value"]
                        c = candidate["annotation"]["directions"][actual_c]["value"]
                        dot = q[0]*c[0]*(-1 if mirrored else 1)+q[1]*c[1]
                        similarity = max(0., min(1., (dot+1)/2))
                        score += weights[i][qkey]*similarity
                        covered += weights[i][qkey]
                        hits.append(actual_q)
                return score, covered, hits, pairs, missing_parts

            pairs = [[pair(i, j) for j in range(n)] for i in range(n)]
            if group.get("exchange") and allow_whole_limb_exchange:
                # Tiny tie-breaks prefer evidence then the original correspondence.
                values = [[p[0] + p[1]*1e-12 - abs(i-j)*1e-15 - (1e6 if p[4] else 0.) for j, p in enumerate(row)] for i, row in enumerate(pairs)]
                assigned = _assignment(values)
            else:
                assigned = list(range(n))
            for i, j in enumerate(assigned):
                score, covered, hits, actual, missing_parts = pairs[i][j]
                numerator += score
                covered_weight += covered
                matched.extend(hits)
                mapping.update(actual)
                inapplicable.extend(missing_parts)
        qv, cv = query["annotation"]["view"], candidate["annotation"]["view"]
        views, distances = [], []
        order = ["front", "front_oblique", "side", "rear_oblique", "rear"]
        for name in contract.get("context", {}).get("view_parts", []):
            a, b = qv.get(name), cv.get(name)
            if a and b and a["definition_ref"] == b["definition_ref"]:
                views.append(abs(order.index(a["value"])-order.index(b["value"]))/4)
        ql, cl = query["annotation"].get("layout"), candidate["annotation"].get("layout")
        allowed_layout = contract.get("context", {}).get("layout_definitions", [])
        if ql and cl and ql["definition_ref"] == cl["definition_ref"] and ql["definition_ref"] in allowed_layout:
            for name in sorted(ql["anchors"].keys() & cl["anchors"].keys()):
                x, y = cl["anchors"][name]
                distances.append(min(1., math.dist(ql["anchors"][name], [-x if mirrored else x, y])))
        vp = view_weight*sum(views)/len(views) if views else 0.
        lp = layout_weight*sum(distances)/len(distances) if distances else 0.
        known_count = sum(k in q_known for k in requested)
        raw = numerator/query_weight
        return {"status": "not_applicable" if inapplicable else "matched", "contract_ref": contract_ref,
                "contract_status": contract["status"], "score": max(0., raw-vp-lp), "direction_score": raw,
                "view_penalty": vp, "layout_penalty": lp, "compared_views": len(views),
                "compared_layout_anchors": len(distances), "mirrored": mirrored, "assignment": mapping,
                "query_known": known_count, "query_requested": len(requested), "query_not_applicable": query_absent,
                "query_coverage": known_count/len(requested), "candidate_compared": len(matched),
                "candidate_coverage": len(matched)/known_count,
                "candidate_weighted_coverage": covered_weight/query_weight,
                "not_applicable_parts": sorted(set(inapplicable)), "query_weight_denominator": query_weight}

    original = evaluate(False)
    if allow_mirror:
        mirrored = evaluate(True)
        if mirrored["score"] > original["score"]+1e-9:
            return mirrored
    return original


def search(query, records, catalog, *, contract_ref, top_n=15, character_ref=None,
           species_ref=None, minimum_coverage=0., collections=("official", "manual"), **options):
    require(isinstance(top_n, int) and not isinstance(top_n, bool) and 1 <= top_n <= 1000, "结果数量必须为1至1000")
    require(number(minimum_coverage) and 0 <= minimum_coverage <= 1, "覆盖门槛必须为0至1")
    # Validate the query even when the database is empty or every candidate is filtered.
    compare(query, query, catalog, contract_ref=contract_ref, **{**options, "include_unreviewed": True})
    results, excluded = [], {"filtered": 0, "incompatible": 0, "not_applicable": 0, "insufficient": 0}
    for record in records:
        subject = record["subject"]
        form = catalog.get("forms", subject["form_ref"]) if subject.get("form_ref") else {}
        if (record["observation_id"] == query["observation_id"] or record.get("example_only") or record.get("test_only") or
            record["collection"] in {"query", "test"} or
            character_ref and subject.get("character_ref") != character_ref or
            species_ref and form.get("species_ref") != species_ref or
            collections is not None and record["collection"] not in collections):
            excluded["filtered"] += 1
            continue
        result = compare(query, record, catalog, contract_ref=contract_ref, **options)
        if result["status"] != "matched":
            excluded[result["status"]] += 1
        elif result["candidate_compared"] == 0 or result["candidate_coverage"] < minimum_coverage:
            excluded["insufficient"] += 1
        else:
            results.append({"observation_id": record["observation_id"], "annotation_id": record["annotation"]["id"],
                            "image_ref": record["image_ref"], "subject": copy.deepcopy(subject),
                            "source": copy.deepcopy(record["source"]), "collection": record["collection"], **result})
    results.sort(key=lambda r: (-r["score"], -r["candidate_coverage"], r["observation_id"]))
    return {"matcher_version": "multispecies_matching_v2.0", "catalog_sha256": catalog.sha256,
            "contract_ref": contract_ref, "query_revision": query["annotation"]["id"], "results": results[:top_n],
            "excluded": excluded, "total_eligible": len(results)}
