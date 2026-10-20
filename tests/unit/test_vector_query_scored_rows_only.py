"""A vector query returns only scored rows, without losing the top-K rewrite (`issues/288`).

* A document query under the default `exclude_managed_segments=True` over a
  segment-only index returned the originals, which have no vector, with
  `score=None` in arbitrary order. A single-vector query now carries
  `FILTER(BOUND(?score))`, as the multi-vector form already did.
* That filter sits between the ORDER and the score's EXTEND, where the vector
  top-K rewrite REFUSES on any restriction (`issues/220`). It is exempt: the
  rewrite's join yields only rows with a vector, so every one is bound.
* `exclude_managed_segments` now drops `urn:segtype:paragraph` too; the
  builder's copy of the list lacked it.
"""

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprValue, ExprVar, LiteralNode,
)
from vitalgraph.db.sparql_sql.ir import (
    KIND_BGP, KIND_EXTEND, KIND_FILTER, KIND_ORDER, KIND_SLICE, PlanV2,
)
from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_SIMILARITY
from vitalgraph.db.sparql_sql.vg_optimize import vg_optimize
from vitalgraph.sparql.kg_query_builder import (
    DocumentQueryCriteria, KGQueryCriteriaBuilder, VectorCriteria,
)


def _top_k_plan(filter_expr):
    extend = PlanV2(
        kind=KIND_EXTEND, children=[PlanV2(kind=KIND_BGP)], extend_var="score",
        extend_expr=ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[ExprVar(var="entity"), ExprValue(node=LiteralNode(value="q")),
                  ExprValue(node=LiteralNode(value="idx"))]))
    filt = PlanV2(kind=KIND_FILTER, children=[extend], filter_exprs=[filter_expr])
    order = PlanV2(kind=KIND_ORDER, children=[filt],
                   order_conditions=[(ExprVar(var="score"), "DESC")])
    return PlanV2(kind=KIND_SLICE, children=[order], limit=5), extend


class TestTheTopKRewrite:

    def test_bound_on_the_score_does_not_block_it(self):
        plan, extend = _top_k_plan(ExprFunction(name="bound", args=[ExprVar(var="score")]))
        vg_optimize(plan)
        assert extend.hints.get("vg_top_k") == {"limit": 5, "direction": "DESC"}

    def test_another_filter_still_does(self):
        # issues/220: a real restriction above the EXTEND must still refuse.
        plan, extend = _top_k_plan(ExprFunction(
            name="eq", args=[ExprVar(var="name"), ExprValue(node=LiteralNode(value="x"))]))
        vg_optimize(plan)
        assert "vg_top_k" not in extend.hints

    def test_bound_on_another_variable_still_does(self):
        plan, extend = _top_k_plan(ExprFunction(name="bound", args=[ExprVar(var="other")]))
        vg_optimize(plan)
        assert "vg_top_k" not in extend.hints


class TestTheGeneratedQuery:

    def test_a_vector_query_keeps_only_scored_rows(self):
        b = KGQueryCriteriaBuilder()
        where, _sel, _order, _limit = b._build_vector_geo_clauses(
            VectorCriteria(search_text="roof repair", index_name="document_segments"),
            None, anchor_var="entity")
        assert "FILTER(BOUND(?vg_score))" in where, where

    def test_exclude_managed_segments_drops_paragraph_segments(self):
        where = KGQueryCriteriaBuilder()._build_document_where_clause(
            DocumentQueryCriteria(exclude_managed_segments=True))
        for t in ("segmentation_parent", "markdown_section", "text_chunk", "paragraph"):
            assert f"<urn:segtype:{t}>" in where, t
