"""`vg:textSearch` narrows the BGP instead of only scoring it — plan §7.1.

`vg:textSearch` emits a CORRELATED scalar subquery keyed on the searched
variable's uuid. It scores rows the BGP has already produced and cannot drive
from the GIN index, so the probe count tracks the candidate set rather than the
match count — and adding more BGP patterns makes that worse, not better.

`push_text_search` adds the match to the BGP as a leaf constraint so
`reorder_joins` can pin it first, exactly as `push_filters` already does for
`CONTAINS`.

Most of what follows tests the REFUSALS. Pushing a match narrows the row set,
so a push under the wrong filter deletes rows the query asked for — and does it
silently, as a wrong answer rather than an error.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode,
)
from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, KIND_BGP, KIND_FILTER, KIND_EXTEND,
)
from vitalgraph.db.sparql_sql.filter_pushdown import push_text_search
from vitalgraph.db.sparql_sql.vg_functions import VG_TEXT_SEARCH

SPACE = "test_space"


class _Ctx:
    """Minimal EmitContext stand-in for the push."""

    def __init__(self, in_correlated_subquery=False, graph_lock_uri=None):
        self.space_id = SPACE
        self.in_correlated_subquery = in_correlated_subquery
        self.graph_lock_uri = graph_lock_uri


def _bgp(var="slot", alias="q0", col="subject_uuid"):
    return PlanV2(
        kind=KIND_BGP,
        tables=[TableRef(ref_id=alias, kind="quad",
                         table_name=f"{SPACE}_rdf_quad", alias=alias)],
        var_slots={var: VarSlot(name=var, positions=[(alias, col)])},
    )


def _search(entity_var="slot", text="saved application", index="message_content"):
    return ExprFunction(
        name="", function_iri=VG_TEXT_SEARCH,
        args=[ExprVar(var=entity_var),
              ExprValue(node=LiteralNode(value=text)),
              ExprValue(node=LiteralNode(value=index))],
    )


def _plan(filter_expr, search_expr=None, score_var="score", bgp=None):
    """FILTER -> EXTEND(score = vg:textSearch) -> BGP, the shape that reaches us."""
    bgp = bgp if bgp is not None else _bgp()
    extend = PlanV2(kind=KIND_EXTEND, children=[bgp], extend_var=score_var,
                    extend_expr=search_expr if search_expr is not None else _search())
    return PlanV2(kind=KIND_FILTER, children=[extend],
                  filter_exprs=[filter_expr]), bgp


def _bound(var="score"):
    return ExprFunction(name="bound", args=[ExprVar(var=var)])


def _cmp(name, var="score", value="0"):
    return ExprFunction(name=name, args=[ExprVar(var=var),
                                         ExprValue(node=LiteralNode(value=value))])


class TestItPushes:

    def test_bound_filter_adds_a_constraint(self):
        plan, bgp = _plan(_bound())
        assert push_text_search(plan, SPACE, _Ctx()) == 1
        assert len(bgp.tagged_constraints) == 1
        ref_id, sql = bgp.tagged_constraints[0]
        assert ref_id == "q0"
        assert "q0.subject_uuid IN" in sql
        assert f"FROM {SPACE}_fts_message_content" in sql
        assert "tsv @@" in sql

    def test_it_uses_the_same_parser_as_the_scorer(self):
        # If the push and the scorer disagreed on what the query MEANS, the
        # push would narrow to a different set than the filter keeps.
        plan, bgp = _plan(_bound())
        push_text_search(plan, SPACE, _Ctx())
        assert "websearch_to_tsquery" in bgp.tagged_constraints[0][1]

    def test_the_filter_IS_consumed(self):
        # The whole win is that the score subquery in the SELECT list then
        # evaluates on the rows that SURVIVE rather than on every candidate.
        # Measured warm on a 48.1M-quad space: 1,139-1,370 ms correlated,
        # 1,708 ms pushed-with-filter-kept, 56-77 ms pushed-with-filter-gone.
        # Keeping the filter runs both and is net negative.
        plan, _bgp_ = _plan(_bound())
        assert push_text_search(plan, SPACE, _Ctx()) == 1
        assert not plan.filter_exprs

    def test_an_unrelated_filter_survives_the_push(self):
        # Only the consumed BOUND goes; anything else must stay.
        other = _cmp("eq", var="name", value="x")
        bgp = _bgp()
        extend = PlanV2(kind=KIND_EXTEND, children=[bgp], extend_var="score",
                        extend_expr=_search())
        plan = PlanV2(kind=KIND_FILTER, children=[extend],
                      filter_exprs=[_bound(), other])
        assert push_text_search(plan, SPACE, _Ctx()) == 1
        assert plan.filter_exprs == [other]

    def test_constraint_is_inline_not_a_cte(self):
        # `_term_set` in this module records the measurement: fencing the
        # equivalent set in a MATERIALIZED CTE cost 41x, because the inline
        # form early-terminates under two-phase paging.
        plan, bgp = _plan(_bound())
        push_text_search(plan, SPACE, _Ctx())
        sql = bgp.tagged_constraints[0][1]
        assert "WITH" not in sql.upper()
        assert "MATERIALIZED" not in sql.upper()

    def test_escapes_a_quote_in_the_search_text(self):
        plan, bgp = _plan(_bound(), _search(text="it's saved"))
        push_text_search(plan, SPACE, _Ctx())
        assert "it''s saved" in bgp.tagged_constraints[0][1]

    def test_constraint_lands_in_both_lists(self):
        # `reorder_joins` reads tagged_constraints; the emitter reads
        # constraints. A constraint in only one is invisible to the other.
        plan, bgp = _plan(_bound())
        push_text_search(plan, SPACE, _Ctx())
        assert len(bgp.constraints) == 1
        assert bgp.constraints[0] == bgp.tagged_constraints[0][1]


class TestItRefuses:
    """Each of these would return a WRONG ROW SET, not an error."""

    def test_not_bound_is_refused(self):
        # `FILTER(!BOUND(?score))` asks for the NON-matches. Narrowing the BGP
        # to the matches would return exactly the rows it excluded.
        neg = ExprFunction(name="not", args=[_bound()])
        plan, bgp = _plan(neg)
        assert push_text_search(plan, SPACE, _Ctx()) == 0
        assert bgp.tagged_constraints == []

    def test_a_bind_with_no_score_filter_is_refused(self):
        # Projecting the score without filtering on it wants EVERY row, with
        # an unbound score on the non-matches.
        bgp = _bgp()
        extend = PlanV2(kind=KIND_EXTEND, children=[bgp], extend_var="score",
                        extend_expr=_search())
        plan = PlanV2(kind=KIND_FILTER, children=[extend],
                      filter_exprs=[_cmp("eq", var="other", value="1")])
        assert push_text_search(plan, SPACE, _Ctx()) == 0
        assert bgp.tagged_constraints == []

    def test_score_gt_zero_is_refused(self):
        # `?score > 0` keeps a SUBSET of the matches, so the push cannot
        # REPLACE it — and pushing while keeping it measured SLOWER than not
        # pushing at all (1,708 ms vs 1,139 ms warm). Refused on cost, having
        # been accepted in an earlier revision on a cache-warmed measurement.
        plan, bgp = _plan(_cmp("gt"))
        assert push_text_search(plan, SPACE, _Ctx()) == 0
        assert bgp.tagged_constraints == []
        assert plan.filter_exprs  # and the filter is left alone

    def test_negative_threshold_is_refused(self):
        plan, bgp = _plan(_cmp("gt", value="-1"))
        assert push_text_search(plan, SPACE, _Ctx()) == 0

    def test_filter_on_an_unrelated_variable_is_refused(self):
        plan, bgp = _plan(_bound(var="something_else"))
        assert push_text_search(plan, SPACE, _Ctx()) == 0

    def test_inside_a_correlated_subquery_is_refused(self):
        # Same reason the rest of this stage refuses: an uncorrelated IN inside
        # a correlated EXISTS body is re-executed per outer row.
        plan, bgp = _plan(_bound())
        assert push_text_search(plan, SPACE, _Ctx(in_correlated_subquery=True)) == 0

    def test_unbound_search_variable_is_refused(self):
        # The BGP binds ?slot; the search names ?other, so there is no column
        # to constrain.
        plan, bgp = _plan(_bound(), _search(entity_var="other"))
        assert push_text_search(plan, SPACE, _Ctx()) == 0

    def test_a_non_textsearch_bind_is_refused(self):
        other = ExprFunction(name="strlen", args=[ExprVar(var="slot")])
        plan, bgp = _plan(_bound(), other)
        assert push_text_search(plan, SPACE, _Ctx()) == 0


class TestGraphScoping:

    def test_graph_lock_scopes_the_pushed_set(self):
        # The FTS table is per-space, not per-graph: without the context
        # clause a graph-locked query would match rows from another graph.
        plan, bgp = _plan(_bound())
        push_text_search(plan, SPACE, _Ctx(graph_lock_uri="urn:g"))
        sql = bgp.tagged_constraints[0][1]
        assert "context_uuid" in sql
