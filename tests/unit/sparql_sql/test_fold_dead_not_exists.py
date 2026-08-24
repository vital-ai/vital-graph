"""A `FILTER NOT EXISTS` whose body can never match must be dropped.

If the EXISTS body requires a term that is not in the term table, it matches
nothing for any outer row, so `NOT EXISTS` over it is always true. Leaving it in
is not merely untidy — the absent constant compiles to a scalar subquery over an
empty `_const` CTE, so every comparison is NULL, the planner cannot fold it, and
it builds the correlated anti-join and runs it per candidate row.

This is what made the frames "Assertion" tab slow. Assertion is defined by
ABSENCE — a frame with neither `hasKGFormType` nor `hasFrameGraphURI` — and in a
space where neither predicate occurs at all, both anti-joins were pure cost over
every frame:

    anchor + re-anchor                          0.4 ms
    anchor + re-anchor + 2 dead NOT EXISTS  4,506.1 ms

The tests build the IR directly. The fold reads each body's OWN
AliasGenerator — `prepare_exists_subplans` gives every body its own, because its
constants are its own — and confusing the two namespaces is the one mistake that
would call a LIVE body dead and silently drop a real filter. That case has its
own test below.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import ExprExists, ExprVar
from vitalgraph.db.sparql_sql.ir import (
    AliasGenerator, PlanV2, TableRef,
    KIND_BGP, KIND_FILTER, KIND_JOIN,
)
from vitalgraph.db.sparql_sql.prune_union import fold_dead_not_exists

pytestmark = pytest.mark.unit


def _bgp(constraint: str, alias: str = "q0") -> PlanV2:
    return PlanV2(
        kind=KIND_BGP,
        tables=[TableRef(ref_id=alias, kind="quad",
                         table_name="rdf_quad", alias=alias)],
        constraints=[constraint],
    )


def _aliases(col: str, resolved: bool) -> AliasGenerator:
    gen = AliasGenerator()
    gen.constants[(f"http://example.org/{col}", "U")] = col
    if resolved:
        gen.resolved_constants[col] = "1a2b3c4d-0000-0000-0000-000000000000"
    return gen


def _exists(col: str, *, resolved: bool, negated: bool = True) -> ExprExists:
    """A prepared EXISTS whose body requires constant `col`."""
    e = ExprExists(graph_pattern=object(), negated=negated)
    e.prepared_plan = _bgp(f"ex_q0.predicate_uuid = __CONST_{col}__")
    e.prepared_aliases = _aliases(col, resolved)
    return e


def _filtered(*exprs) -> PlanV2:
    """FILTER(exprs) over an anchor BGP."""
    return PlanV2(kind=KIND_FILTER,
                  filter_exprs=list(exprs),
                  children=[_bgp("q1.object_uuid = __CONST_c_9__", alias="q1")])


class TestFolding:

    def test_a_dead_not_exists_is_dropped(self):
        plan = _filtered(_exists("c_0", resolved=False))
        assert fold_dead_not_exists(plan) == 1

    def test_the_filter_node_becomes_its_child_when_nothing_is_left(self):
        """An identity FILTER wrapper would still be carried through emit."""
        plan = _filtered(_exists("c_0", resolved=False))
        fold_dead_not_exists(plan)
        assert plan.kind == KIND_BGP, (
            "a FILTER with no expressions left must become its child")
        assert plan.constraints == ["q1.object_uuid = __CONST_c_9__"], (
            "the child's own constraints must survive being promoted")

    def test_a_live_not_exists_is_kept(self):
        """The body's constant resolves, so the anti-join is real work."""
        plan = _filtered(_exists("c_0", resolved=True))
        assert fold_dead_not_exists(plan) == 0
        assert plan.kind == KIND_FILTER and len(plan.filter_exprs) == 1

    def test_only_the_dead_conjunct_goes(self):
        plan = _filtered(_exists("c_0", resolved=False),
                         _exists("c_1", resolved=True))
        assert fold_dead_not_exists(plan) == 1
        assert len(plan.filter_exprs) == 1
        assert plan.filter_exprs[0].prepared_aliases.resolved_constants, (
            "the surviving expression must be the LIVE one")


class TestWhatMustNotBeFolded:

    def test_a_plain_exists_is_never_folded(self):
        """`EXISTS { dead }` is constant-FALSE, not constant-true. Dropping it
        would turn a query that matches nothing into one that matches
        everything — the failure that is silent, because it returns rows."""
        plan = _filtered(_exists("c_0", resolved=False, negated=False))
        assert fold_dead_not_exists(plan) == 0
        assert len(plan.filter_exprs) == 1

    def test_an_unprepared_body_is_left_alone(self):
        """No prepared plan means no resolution information. Emit collects such
        a body inline; guessing here would be guessing."""
        e = ExprExists(graph_pattern=object(), negated=True)
        plan = _filtered(e)
        assert fold_dead_not_exists(plan) == 0

    def test_a_non_exists_filter_is_untouched(self):
        plan = _filtered(ExprVar(var="x"))
        assert fold_dead_not_exists(plan) == 0
        assert len(plan.filter_exprs) == 1

    def test_a_body_is_judged_by_its_own_aliases_not_the_outer_ones(self):
        """Each EXISTS body owns its constants, and `c_0` in one namespace is
        unrelated to `c_0` in another. If the fold reached for an outer
        AliasGenerator it would drop this live filter."""
        live = _exists("c_0", resolved=True)
        plan = _filtered(live)
        # An outer generator where the SAME column name is dead.
        outer_dead = _aliases("c_0", resolved=False)
        assert outer_dead.resolved_constants == {}
        assert fold_dead_not_exists(plan) == 0, (
            "the fold consulted something other than the body's own aliases")


class TestTraversal:

    def test_it_reaches_filters_below_a_join(self):
        """The frames query puts the NOT EXISTS under a JOIN with the anchor,
        which is the shape that actually occurs."""
        filt = _filtered(_exists("c_0", resolved=False))
        plan = PlanV2(kind=KIND_JOIN,
                      children=[_bgp("q0.object_uuid = __CONST_c_1__"), filt])
        assert fold_dead_not_exists(plan) == 1
        assert plan.children[1].kind == KIND_BGP

    def test_it_counts_every_fold_in_the_tree(self):
        plan = PlanV2(kind=KIND_JOIN, children=[
            _filtered(_exists("c_0", resolved=False)),
            _filtered(_exists("c_1", resolved=False)),
        ])
        assert fold_dead_not_exists(plan) == 2
