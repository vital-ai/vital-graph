"""The generator's BGP cardinality model (`issues/293`, stage 2).

PostgreSQL priced the UW dashboard's join at 1 row per step where it held
1,159, then 1,033,972, then 6,950. The model's rules, and the numbers it gives
on that chain, are pinned here. Accuracy across workloads is measured, not
asserted: `test_scripts_internal/kg_uw_decision_reasons/model_vs_pg.py`.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.bgp_cardinality import (
    Leaf, _CONTAIN, estimate_order, step_factor,
)
from vitalgraph.db.sparql_sql.ir import KIND_BGP, PlanV2, VarSlot


def _leaf(a, *, scan=None, rows=None, objs=None, oconst=False):
    return Leaf(a, "p-" + a, oconst, False, scan, rows, objs)


class TestStepFactor:

    def test_a_probe_by_object_is_the_mean_fanout(self):
        assert step_factor(_leaf("g", rows=2_047_649, objs=4_048), False, True) == \
            pytest.approx(505.8, rel=1e-3)

    def test_a_probe_by_subject_is_one_value(self):
        assert step_factor(_leaf("v", rows=100, objs=10), True, False) == 1.0

    def test_a_constant_object_on_a_bound_subject_is_containment(self):
        assert step_factor(_leaf("t", scan=9_318, rows=858_544, objs=1_010, oconst=True),
                           True, False) is _CONTAIN

    def test_both_ends_bound_is_a_membership_check(self):
        assert step_factor(_leaf("c", rows=1_000, objs=250), True, True) == 1 / 250

    def test_unknown_statistics_are_unknown_not_guessed(self):
        assert step_factor(_leaf("g", rows=None, objs=None), False, True) is None


def _by_reason_shape():
    """q0: ?d type <Decision>   q1: ?s graph ?d   q2: ?s slotType <ReasonKind>
    q3: ?s value ?kind"""
    return PlanV2(kind=KIND_BGP, var_slots={
        "d": VarSlot("d", [("q0", "subject_uuid"), ("q1", "object_uuid")]),
        "s": VarSlot("s", [("q1", "subject_uuid"), ("q2", "subject_uuid"),
                           ("q3", "subject_uuid")]),
        "kind": VarSlot("kind", [("q3", "object_uuid")]),
    })


def test_the_dashboard_chain():
    """The numbers measured on `uw_prodshape`: actual 1,159 -> 1,033,972 ->
    6,950 -> 6,950. Postgres: 1, 1, 1, 1."""
    leaves = {
        "q0": _leaf("q0", scan=1_159, rows=4_048, objs=8, oconst=True),
        "q1": _leaf("q1", rows=2_047_649, objs=4_048),
        "q2": _leaf("q2", scan=6_950, rows=858_544, objs=1_010, oconst=True),
        "q3": _leaf("q3", rows=226_000, objs=900),
    }
    est = estimate_order(_by_reason_shape(), leaves, ["q0", "q1", "q2", "q3"])
    assert est[0] == 1_159
    assert est[1] == pytest.approx(1_159 * 505.8, rel=1e-3)   # mean graph size
    assert est[2] == 6_950        # contained in the pin: exactly the actual
    assert est[3] == 6_950        # one value per slot


def test_driving_from_the_pin_prices_the_same_answer():
    """Order independence where it should hold: the same join, the pin first."""
    leaves = {
        "q0": _leaf("q0", scan=1_159, rows=4_048, objs=8, oconst=True),
        "q1": _leaf("q1", rows=2_047_649, objs=4_048),
        "q2": _leaf("q2", scan=6_950, rows=858_544, objs=1_010, oconst=True),
        "q3": _leaf("q3", rows=226_000, objs=900),
    }
    est = estimate_order(_by_reason_shape(), leaves, ["q2", "q1", "q3", "q0"])
    assert est[:3] == [6_950, 6_950, 6_950]
    # Actual 6,950: every slot's graph is a decision, so joining the type keeps
    # every row. Containment caps DISTINCT ?d, not rows. A first version capped
    # rows and said 1,159. The remaining gap is the distinct-?d estimate: the
    # predicate's 4,048 graphs overall, where these slots reach 1,159.
    assert est[3] == pytest.approx(6_950 * 1_159 / 4_048, rel=1e-3)


def test_an_unpriceable_step_makes_the_rest_unknown():
    leaves = {
        "q0": _leaf("q0", scan=1_159, oconst=True),
        "q1": _leaf("q1", rows=None, objs=None),
        "q2": _leaf("q2", scan=6_950, rows=858_544, objs=1_010, oconst=True),
        "q3": _leaf("q3", rows=226_000, objs=900),
    }
    est = estimate_order(_by_reason_shape(), leaves, ["q0", "q1", "q2", "q3"])
    assert est == [1_159, None, None, None]


# ---------------------------------------------------------------------------
# The enforcement gate (`issues/293` stage 3)
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from vitalgraph.db.sparql_sql import bgp_cardinality as BC  # noqa: E402
from vitalgraph.db.sparql_sql.ir import AliasGenerator, TableRef  # noqa: E402


def _gate(monkeypatch, leaves, default):
    plan = _by_reason_shape()
    tables = [TableRef(ref_id=a, kind="quad", table_name="t", alias=a)
              for a in ("q0", "q1", "q2", "q3")]
    monkeypatch.setattr(BC, "leaves_from", lambda *a, **k: leaves)
    aliases = AliasGenerator()
    order = BC.enforced_order(plan, aliases, tables, {}, lambda t: None, default)
    [d] = [d for d in aliases.plan_decisions.decisions if d.name == BC.NAME]
    return order, d


_DASHBOARD = {
    "q0": _leaf("q0", scan=1_159, rows=4_048, objs=8, oconst=True),
    "q1": _leaf("q1", rows=2_047_649, objs=4_048),
    "q2": _leaf("q2", scan=6_950, rows=858_544, objs=1_010, oconst=True),
    "q3": _leaf("q3", rows=226_000, objs=900),
}


def test_the_gate_enforces_a_large_predicted_gain(monkeypatch):
    """by_reason: the default roots on the entity type and expands every graph."""
    order, d = _gate(monkeypatch, _DASHBOARD, ["q0", "q1", "q2", "q3"])
    assert order and order[0] == "q2" and d.fired
    assert d.detail["gain"] >= BC.ENFORCE_MIN_GAIN


def test_the_gate_keeps_the_default_inside_the_error_band(monkeypatch):
    """Already rooted on the pin: nothing to gain, nothing enforced."""
    order, d = _gate(monkeypatch, _DASHBOARD, ["q2", "q1", "q3", "q0"])
    assert order is None and not d.fired and "error band" in d.reason


def test_the_gate_declines_what_it_cannot_price(monkeypatch):
    leaves = dict(_DASHBOARD, q1=_leaf("q1", rows=None, objs=None))
    order, d = _gate(monkeypatch, leaves, ["q0", "q1", "q2", "q3"])
    assert order is None and not d.fired


# ---------------------------------------------------------------------------
# EXISTS bodies: correlated variables bound per outer row (`issues/293`)
# ---------------------------------------------------------------------------

def test_a_bound_variable_prices_one_probe_not_the_whole_body():
    """With ?d bound (an EXISTS body correlated on it) the chain starts at one
    row: the work of one probe, not the 1,159 decisions."""
    est = estimate_order(_by_reason_shape(), _DASHBOARD, ["q1", "q2", "q3"],
                         bound_vars=["d"])
    assert est[0] == pytest.approx(505.8, rel=1e-3)   # ?d's graph members
    assert est[1] <= est[0]                           # contained in the pin


def test_the_gate_prices_both_orders_with_the_bound_variables(monkeypatch):
    """`enforced_order` hands `bound_vars` to both the model's order and the
    default's, and records them, so a body is not priced as a full scan."""
    plan = _by_reason_shape()
    tables = [TableRef(ref_id=a, kind="quad", table_name="t", alias=a)
              for a in ("q0", "q1", "q2", "q3")]
    monkeypatch.setattr(BC, "leaves_from", lambda *a, **k: _DASHBOARD)
    aliases = AliasGenerator()
    BC.enforced_order(plan, aliases, tables, {}, lambda t: None,
                      ["q0", "q1", "q2", "q3"], ["d"])
    [d] = [d for d in aliases.plan_decisions.decisions if d.name == BC.NAME]
    assert d.detail.get("bound") == ["d"]


def test_an_exists_body_gets_the_outer_planning_stats():
    """A body's AliasGenerator is born empty. Without the outer statistics it
    was ordered blind: only_cause's NOT EXISTS ran 3,551,621 probes (25.8 s),
    6,950 (2.3 s) with them."""
    from vitalgraph.db.sparql_sql.emit_expressions import _share_planning_stats
    outer, inner = AliasGenerator(), AliasGenerator(alias_prefix="ex_")
    outer.quad_stats = {("p", "o"): 7}
    outer.pred_stats = {"p": 70}
    outer.pred_object_counts = {"p": 10}
    inner.pred_stats = {"own": 1}          # a body's own value is not overwritten
    _share_planning_stats(outer, inner)
    assert inner.quad_stats == {("p", "o"): 7}
    assert inner.pred_object_counts == {"p": 10}
    assert inner.pred_stats == {"own": 1}


# ---------------------------------------------------------------------------
# Edge and frame_slot leaves (`issues/293` stage 6 coverage)
# ---------------------------------------------------------------------------

def _edge_plan():
    """?e (mv0) from ?entity to ?frame; ?frame (q1) has a constant type."""
    return PlanV2(kind=KIND_BGP, var_slots={
        "entity": VarSlot("entity", [("mv0", "source_node_uuid")]),
        "frame": VarSlot("frame", [("mv0", "dest_node_uuid"), ("q1", "subject_uuid")]),
        "e": VarSlot("e", [("mv0", "edge_uuid")]),
    })


def _edge_leaf(rows=5_277_000, n_src=1_300_000, n_dst=5_277_000):
    return Leaf("mv0", None, False, False, rows, rows, None,
                cols={"edge_uuid": rows, "source_node_uuid": n_src, "dest_node_uuid": n_dst})


def test_an_edge_probed_by_source_is_edges_per_source():
    leaves = {"q1": _leaf("q1", scan=900_000, rows=1_200_000, objs=12, oconst=True),
              "mv0": _edge_leaf()}
    est = estimate_order(_edge_plan(), leaves, ["mv0"], bound_vars=["entity"])
    assert est[0] == pytest.approx(5_277_000 / 1_300_000)


def test_an_edge_probed_by_its_destination_is_one_edge():
    leaves = {"q1": _leaf("q1", scan=900_000, rows=1_200_000, objs=12, oconst=True),
              "mv0": _edge_leaf()}
    est = estimate_order(_edge_plan(), leaves, ["q1", "mv0"])
    assert est == [900_000, pytest.approx(900_000)]


def test_derived_leaves_come_from_the_predicates_they_replace():
    """An edge from hasEdgeSource/hasEdgeDestination's rows and distinct
    objects; a frame_slot arm from its role's slot count. Without
    object_count there is no edge leaf: rdf_stats keeps only the largest
    pairs, and an edge's are never among them."""
    src, dst = BC._iri_uuid(BC._VC + "hasEdgeSource"), BC._iri_uuid(BC._VC + "hasEdgeDestination")
    st = BC._iri_uuid(BC._HK + "hasKGSlotType")
    edge = TableRef(ref_id="mv0", kind="edge", table_name="t", alias="mv0")
    fs = TableRef(ref_id="fsmv0", kind="frame_slot", table_name="t", alias="fsmv0")
    tagged = [("fsmv0", "fsmv0.role_uuid = __CONST_c_7__")]
    resolved = {"c_7": "role-1"}
    leaf = BC._derived_leaf(edge, tagged, {src: 100}, {src: 25, dst: 100}, {}, {}, resolved)
    assert leaf.cols == {"edge_uuid": 100.0, "source_node_uuid": 25.0, "dest_node_uuid": 100.0}
    assert BC._derived_leaf(edge, tagged, {src: 100}, {}, {}, {}, resolved) is None
    arm = BC._derived_leaf(fs, tagged, {}, {}, {(st, "role-1"): 40}, {}, resolved)
    assert arm.scan_rows == 40 and arm.cols["frame_uuid"] == 40
    assert BC._derived_leaf(fs, [], {}, {}, {(st, "role-1"): 40}, {}, resolved) is None


# ---------------------------------------------------------------------------
# The semijoin gate stands aside under a LIMIT it can stop early (`semijoin`)
# ---------------------------------------------------------------------------

def test_a_split_under_a_limit_is_left_to_stop_early():
    """KGQuery's `ORDER BY ?entity LIMIT 25` probes ~25 anchors: 9 ms as a
    split, 25 s when the gate reverted it to the merged join (mql_edge_page).
    An ORDER BY on anything else, or a GROUP BY, needs every row."""
    from vitalgraph.db.jena_sparql.jena_types import ExprVar
    from vitalgraph.db.sparql_sql.ir import KIND_ORDER, KIND_SLICE, KIND_GROUP
    from vitalgraph.db.sparql_sql.semijoin import _under_limit

    def tree(mid):
        split = PlanV2(kind=KIND_BGP)
        node = split if mid is None else PlanV2(kind=mid.kind, order_conditions=mid.order_conditions,
                                                 children=[split])
        return PlanV2(kind=KIND_SLICE, limit=25, children=[node]), split

    root, split = tree(None)
    assert _under_limit(root, split, "entity")
    root, split = tree(PlanV2(kind=KIND_ORDER, order_conditions=[("entity", "ASC")]))
    assert _under_limit(root, split, "entity")
    root, split = tree(PlanV2(kind=KIND_ORDER, order_conditions=[(ExprVar(var="entity"), "ASC")]))
    assert _under_limit(root, split, "entity")
    root, split = tree(PlanV2(kind=KIND_ORDER, order_conditions=[("rating", "DESC")]))
    assert not _under_limit(root, split, "entity")
    root, split = tree(PlanV2(kind=KIND_GROUP))
    assert not _under_limit(root, split, "entity")
    assert not _under_limit(PlanV2(kind=KIND_ORDER, children=[split]), split, "entity")


# ---------------------------------------------------------------------------
# The semijoin model gate (`issues/293` stage 6)
# ---------------------------------------------------------------------------

def _split_case(monkeypatch, leaves, extra_tables=()):
    plan = _by_reason_shape()
    plan.tables = [TableRef(ref_id=a, kind="quad", table_name="t", alias=a)
                   for a in ("q0", "q1", "q2", "q3")] + list(extra_tables)
    anchor = PlanV2(kind=KIND_BGP, tables=[plan.tables[0]])
    rest = PlanV2(kind=KIND_BGP, tables=plan.tables[1:])
    split = PlanV2(kind="join", children=[anchor, rest])
    monkeypatch.setattr(BC, "leaves_from", lambda *a, **k: leaves)
    monkeypatch.setattr("vitalgraph.db.sparql_sql.emit_bgp._leaf_cardinality",
                        lambda plan, ctx: {})
    aliases = AliasGenerator()
    keep = BC.semijoin_is_cheaper(plan, split, "d", aliases)
    [d] = [d for d in aliases.plan_decisions.decisions if d.name == BC.SEMIJOIN_NAME]
    return keep, d


def test_the_gate_reverts_a_split_that_probes_every_graph(monkeypatch):
    """Anchored on the 1,159 decisions, each probe walks ~506 graph members;
    the merged join driven from the 6,950 slot pins is far cheaper."""
    keep, d = _split_case(monkeypatch, _DASHBOARD)
    assert not keep and d.fired
    assert d.detail["gain"] >= BC.ENFORCE_MIN_GAIN


def test_the_gate_keeps_a_split_with_an_unpriced_leaf(monkeypatch):
    edge = TableRef(ref_id="mv0", kind="edge", table_name="t", alias="mv0")
    keep, d = _split_case(monkeypatch, _DASHBOARD, extra_tables=[edge])
    assert keep and not d.fired and "no statistics" in d.reason


def test_an_absorbed_frame_type_restricts_the_frame_slot_arm():
    """The frame_slot rewrite absorbs `?frame vitaltype <C>` into
    `frame_type_uuid`; the arm is then at most the frames of that type."""
    st, vt = BC._iri_uuid(BC._HK + "hasKGSlotType"), BC._iri_uuid(BC._VC + "vitaltype")
    fs = TableRef(ref_id="fsmv0", kind="frame_slot", table_name="t", alias="fsmv0")
    tagged = [("fsmv0", "fsmv0.role_uuid = __CONST_c_7__"),
              ("fsmv0", "fsmv0.frame_type_uuid = __CONST_c_8__")]
    resolved = {"c_7": "role-1", "c_8": "type-C"}
    stats = {(st, "role-1"): 40_000, (vt, "type-C"): 300}
    arm = BC._derived_leaf(fs, tagged, {}, {}, stats, {}, resolved)
    assert arm.scan_rows == 300
    # An unknown type count is unpriced, not guessed.
    assert BC._derived_leaf(fs, tagged, {}, {}, {(st, "role-1"): 40_000}, {}, resolved) is None


# ---------------------------------------------------------------------------
# Hop-wise stands aside when its walk starts far dearer than the flat join
# ---------------------------------------------------------------------------

def _hop_guard(monkeypatch, start_alias):
    from vitalgraph.db.sparql_sql import emit_bgp as E
    from .emit_helpers import _make_ctx
    plan = _by_reason_shape()
    tables = [TableRef(ref_id=a, kind="quad", table_name="t", alias=a)
              for a in ("q0", "q1", "q2", "q3")]
    monkeypatch.setattr(BC, "leaves_from", lambda *a, **k: _DASHBOARD)
    monkeypatch.setattr(E, "_leaf_cardinality", lambda plan, ctx: {})
    decision = SimpleNamespace(direction="head", chain=SimpleNamespace(
        head_constraint_alias=start_alias, tail_constraint_alias=None))
    return E._hop_wise_start_dearer(plan, _make_ctx({}), tables, decision)


def test_hop_wise_declines_a_walk_from_an_unselective_end(monkeypatch):
    """wordnet_frames, destination entity fixed: the chain's head was every
    KGFrame (285,348) while the flat join cost 13,420; hop-wise ran
    1,141,392 loops, flat 1,342."""
    unselective = dict(_DASHBOARD, q0=_leaf("q0", scan=5_000_000, rows=5_000_000,
                                             objs=8, oconst=True))
    monkeypatch.setattr(BC, "leaves_from", lambda *a, **k: unselective)
    from vitalgraph.db.sparql_sql import emit_bgp as E
    from .emit_helpers import _make_ctx
    decision = SimpleNamespace(direction="head", chain=SimpleNamespace(
        head_constraint_alias="q0", tail_constraint_alias=None))
    monkeypatch.setattr(E, "_leaf_cardinality", lambda plan, ctx: {})
    tables = [TableRef(ref_id=a, kind="quad", table_name="t", alias=a)
              for a in ("q0", "q1", "q2", "q3")]
    facts = E._hop_wise_start_dearer(_by_reason_shape(), _make_ctx({}), tables, decision)
    assert facts and facts["start_rows"] == 5_000_000


def test_hop_wise_keeps_a_walk_from_a_selective_end(monkeypatch):
    assert _hop_guard(monkeypatch, "q0") is None       # 1,159 rows: cheap start


def test_hop_wise_keeps_its_decision_when_an_end_is_unpriced(monkeypatch):
    assert _hop_guard(monkeypatch, None) is None
