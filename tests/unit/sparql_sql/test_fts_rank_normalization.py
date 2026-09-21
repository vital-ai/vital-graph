"""`ts_rank_cd` normalization is read from the index, and 0 emits no argument.

Measured on a 321,276-row message index: the term `app` matched 118,702
documents and the DEFAULT normalization (0, which ignores document length)
gave them THREE distinct scores — a "top 25 by relevance" that is arbitrary.
norm=1 gave 101. It is stored per index because it changes every score the
index produces and because favouring short documents is an editorial choice,
not a universal improvement.
"""

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode,
)
from vitalgraph.db.sparql_sql.vg_functions import (
    VG_TEXT_SEARCH, text_search_sql, _rank_expr, _resolve_fts_normalization,
)

SPACE = "test_space"


class _Ctx:
    def __init__(self, norm=None):
        self.space_id = SPACE
        self.graph_lock_uri = None
        meta = {"languages": ["english"]}
        if norm is not None:
            meta["rank_normalization"] = norm
        self.fts_index_meta = {"idx": meta}
        self.types = _Types()
        self.vg_hints = {}


class _Types:
    def get(self, var):
        class I:
            uuid_col = "v0__uuid"
        return I()


def _expr():
    return ExprFunction(
        name="", function_iri=VG_TEXT_SEARCH,
        args=[ExprVar(var="s"), ExprValue(node=LiteralNode(value="app")),
              ExprValue(node=LiteralNode(value="idx"))])


def test_zero_emits_no_normalization_argument():
    # Unchanged SQL for every index that has not opted in, so recorded plans
    # and baselines stay comparable.
    sql = text_search_sql(_expr(), _Ctx(norm=0))
    assert "ts_rank_cd(tsv, websearch_to_tsquery" in sql
    assert ", 0)" not in sql


def test_absent_metadata_behaves_as_zero():
    sql = text_search_sql(_expr(), _Ctx(norm=None))
    assert "ts_rank_cd(tsv, websearch_to_tsquery" in sql
    assert _resolve_fts_normalization("idx", _Ctx(norm=None)) == 0


def test_non_zero_is_emitted():
    sql = text_search_sql(_expr(), _Ctx(norm=1))
    assert ", 1)" in sql, sql


def test_the_scorer_and_the_order_by_agree():
    # text_search_sql emits the rank twice under the top-K hint — in the
    # SELECT and in the ORDER BY. A normalization applied to one and not the
    # other would order by a different number than it returns.
    ctx = _Ctx(norm=1)
    ctx.vg_hints = {"vg_top_k": {"limit": 25, "direction": "DESC"}}
    sql = text_search_sql(_expr(), ctx)
    assert sql.count("ts_rank_cd(tsv, websearch_to_tsquery('english'::regconfig, 'app'), 1)") == 2, sql


def test_bad_metadata_falls_back_rather_than_raising():
    c = _Ctx(norm=None)
    c.fts_index_meta = {"idx": {"languages": ["english"],
                                "rank_normalization": "not-a-number"}}
    assert _resolve_fts_normalization("idx", c) == 0


def test_rank_expr_shape():
    assert _rank_expr("tsv", "Q", 0) == "ts_rank_cd(tsv, Q)"
    assert _rank_expr("f.tsv", "Q", 1) == "ts_rank_cd(f.tsv, Q, 1)"
