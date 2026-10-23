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
