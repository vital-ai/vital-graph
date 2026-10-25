"""After slot-group CTEs, the remainder is ordered by the model, units included (issue 310).

category_page's reason BGP: three decision field units (slot-group CTEs, ~1,400
rows each) and the reason-kind slot's leaves. `reorder_joins` rooted the
remainder on a field unit and then probed `?k hasKGGraphURI ?d` by ?d: ~1,090
graph members per decision, 1.8M rows, frozen by the statement-wide pin (2.1 s).
The model sees each unit as one column leaf (`unit_model`) and roots on the
kind slot's pin instead.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.sparql_sql.bgp_cardinality import (
    Leaf, choose_order, estimate_order, unit_model,
)
from vitalgraph.db.sparql_sql.ir import KIND_BGP, PlanV2, VarSlot


def _leaf(a, *, scan=None, rows=None, objs=None, oconst=False):
    return Leaf(a, "p-" + a, oconst, False, scan, rows, objs)


def _shape():
    """q0: ?d type <Decision>
    field slot (one unit): g1 ?f graph ?d, g2 ?f slotType <Field> (the pin), g3 ?f value ?v
    reason-kind slot:      r1 ?k graph ?d, r2 ?k slotType <ReasonKind>, r3 ?k value ?kind"""
    plan = PlanV2(kind=KIND_BGP, var_slots={
        "d": VarSlot("d", [("q0", "subject_uuid"), ("g1", "object_uuid"), ("r1", "object_uuid")]),
        "f": VarSlot("f", [("g1", "subject_uuid"), ("g2", "subject_uuid"), ("g3", "subject_uuid")]),
        "v": VarSlot("v", [("g3", "object_uuid")]),
        "k": VarSlot("k", [("r1", "subject_uuid"), ("r2", "subject_uuid"), ("r3", "subject_uuid")]),
        "kind": VarSlot("kind", [("r3", "object_uuid")]),
    })
    graph = dict(rows=2_047_649, objs=4_048)            # ~506 members per graph
    leaves = {
        "q0": _leaf("q0", scan=1_159, rows=4_048, objs=8, oconst=True),
        "g1": _leaf("g1", **graph),
        "g2": _leaf("g2", scan=1_159, rows=858_544, objs=1_010, oconst=True),
        "g3": _leaf("g3", rows=1_000_000, objs=900_000),
        "r1": _leaf("r1", **graph),
        "r2": _leaf("r2", scan=6_950, rows=858_544, objs=1_010, oconst=True),
        "r3": _leaf("r3", rows=1_000_000, objs=207),
    }
    return plan, leaves, [("sg_g1_cte", {"g1", "g2", "g3"}, "g2")]


def test_a_unit_is_one_column_leaf_on_its_cte_columns():
    plan, leaves, units = _shape()
    shim, out = unit_model(plan, leaves, units)
    unit = out["sg_g1_cte"]
    assert unit.scan_rows == 1_159                      # its members joined from the pin
    # one column per variable: ?d through the graph link, ?f, ?v
    assert set(unit.cols) == {"g1__object_uuid", "g1__subject_uuid", "g3__object_uuid"}
    assert unit.cols["g1__object_uuid"] == 1_159        # at most the unit's rows
    # the BGP's positions now point at the unit, not at its members
    assert ("sg_g1_cte", "g1__object_uuid") in shim.var_slots["d"].positions
    assert not any(a in ("g1", "g2", "g3") for a, _ in shim.var_slots["d"].positions)
    assert {"g1", "g2", "g3"}.isdisjoint(out)


def test_the_remainder_roots_on_the_kind_pin_not_on_a_unit():
    plan, leaves, units = _shape()
    shim, out = unit_model(plan, leaves, units)
    remainder = ["q0", "sg_g1_cte", "r1", "r2", "r3"]
    order, cost = choose_order(shim, out, remainder)
    # The order the heuristic wrote: the smallest relation first, then the graph link by ?d.
    heuristic = ["sg_g1_cte", "q0", "r1", "r2", "r3"]
    est = estimate_order(shim, out, heuristic)
    assert est[2] > 500_000                             # 1,159 decisions x ~506 members
    assert order[0] != "sg_g1_cte"
    assert order.index("r2") < order.index("r1")        # the kind pin before its graph link
    assert cost < sum(est) / 10


def test_an_unpriced_member_leaves_the_unit_unpriced():
    plan, leaves, units = _shape()
    leaves["g2"] = _leaf("g2", scan=None, rows=858_544, objs=1_010, oconst=True)
    assert unit_model(plan, leaves, units) is None
