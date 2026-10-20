"""`vg:hybridSearch` scores through EITHER arm (`issues/288`).

Reported on 0.0.48: alpha 0.5 returned no rows where alpha 0 worked. The SQL
admitted a row only if `tsv @@ q OR cosine distance < 0.6`. On an OpenAI
`text-embedding-3-small` index good paraphrases score 0.2-0.35 similarity, so
the vector arm admitted nothing, and a phrase without an all-terms lexical
match returned no rows.

The text-search NARROWING was checked and is not involved: it never applies to
a hybrid score (pinned below), so the vector arm is not cut off upstream.
"""

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprValue, ExprVar, LiteralNode,
)
from vitalgraph.db.sparql_sql.filter_pushdown import _fts_index_and_query
from vitalgraph.db.sparql_sql.vg_functions import VG_HYBRID_SEARCH, hybrid_search_sql

SPACE = "test_space"


class _Types:
    def get(self, var):
        class I:
            uuid_col = "v0__uuid"
        return I()


class _Ctx:
    def __init__(self):
        self.space_id = SPACE
        self.graph_lock_uri = None
        self.in_correlated_subquery = False
        self.fts_index_meta = {"idx": {"languages": ["english"]}}
        self.types = _Types()
        self.vg_hints = {}


def _hybrid(alpha="0.5", var="s"):
    return ExprFunction(
        name="", function_iri=VG_HYBRID_SEARCH,
        args=[ExprVar(var=var), ExprValue(node=LiteralNode(value="fresh bread pastries")),
              ExprValue(node=LiteralNode(value="idx")),
              ExprValue(node=LiteralNode(value=alpha))])


class TestTheScore:

    def test_no_model_dependent_distance_cutoff(self):
        sql, _req = hybrid_search_sql(_hybrid(), _Ctx())
        assert "< 0.6" not in sql, sql

    def test_a_subject_without_a_vector_still_scores_lexically(self):
        # A document with vectorization off (issues/285) has an FTS row and no
        # vector; the lexical arm must still find it.
        sql, _req = hybrid_search_sql(_hybrid(), _Ctx())
        assert "LEFT JOIN test_space_vec_idx v" in sql, sql
        assert "COALESCE(1 - (v.embedding <=>" in sql, sql

    def test_the_weights_follow_alpha(self):
        sql, _req = hybrid_search_sql(_hybrid("0.25"), _Ctx())
        assert "0.750000 *" in sql and "0.250000 *" in sql, sql


def test_the_text_narrowing_never_applies_to_a_hybrid_score():
    """`push_text_search` turns `FILTER(BOUND(?score))` into a hard `tsv @@ q`
    constraint. Applied to a hybrid score it would drop every row only the
    vector arm reaches. It resolves only `vg:textSearch` / `vg:textMatch`, so
    a hybrid score is never narrowed -- pinned so that stays true."""
    assert _fts_index_and_query(_hybrid(), _Ctx()) is None
