"""An FTS-pinned leaf is PRICED by its measured match count, and a small match
set is emitted as a literal array.

`push_text_search` narrows a leaf to `subject_uuid IN (SELECT ... WHERE tsv @@
q)`. Nothing priced that leaf, so join ordering saw only its (hasKGSlotType,
MsgContent) pair — every message slot — and the entity-type leaf rooted the
chain. PostgreSQL could not rescue it: it estimated a 14-row phrase at 27,316.
Measured on a 49.7M-quad space, that phrase took 34 s sorted by modification
date and 20 s under a 30-day filter; with this, 4.9 ms and 1.7 ms, with the
full ordered result identical.

Two mechanisms, pinned separately because either can regress alone:

* the COUNT reaches `_leaf_cardinality`, which enters the alias into the same
  anchor contest range leaves use — so a 14-row FTS leaf beats a broad range;
* a small FETCHED set is emitted as `= ANY('{...}'::uuid[])`, which PostgreSQL
  estimates at exactly its length. Only the number changes, never the set.

And one refusal that matters most: a count AT the cap is a lower bound and must
never re-price the leaf, or a broad term would displace a narrow range.
"""
from __future__ import annotations

from types import SimpleNamespace

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode,
)
from vitalgraph.db.sparql_sql.emit_bgp import _leaf_cardinality
from vitalgraph.db.sparql_sql.filter_pushdown import (
    push_text_search, _fts_index_and_query,
)
from vitalgraph.db.sparql_sql.generator import FTS_LEAF_COUNT_CAP
from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, KIND_BGP, KIND_FILTER,
)
from vitalgraph.db.sparql_sql.vg_functions import VG_TEXT_MATCH, _context_clause

SPACE = "test_space"
U1 = "11111111-1111-5111-8111-111111111111"
U2 = "22222222-2222-5222-8222-222222222222"


class _Ctx:
    def __init__(self, stats=None, ids=None):
        self.space_id = SPACE
        self.in_correlated_subquery = False
        self.graph_lock_uri = None
        self.aliases = SimpleNamespace(fts_leaf_stats=stats or {},
                                       fts_leaf_ids=ids or {})


def _match(text="saved application"):
    return ExprFunction(
        name="", function_iri=VG_TEXT_MATCH,
        args=[ExprVar(var="slot"), ExprValue(node=LiteralNode(value=text)),
              ExprValue(node=LiteralNode(value="message_content"))])


def _plan(expr):
    bgp = PlanV2(kind=KIND_BGP,
                 tables=[TableRef(ref_id="q1", kind="quad",
                                  table_name=f"{SPACE}_rdf_quad", alias="q1")],
                 var_slots={"slot": VarSlot(name="slot",
                                            positions=[("q1", "subject_uuid")])})
    return PlanV2(kind=KIND_FILTER, children=[bgp], filter_exprs=[expr]), bgp


def _key(expr, ctx):
    table, tsquery = _fts_index_and_query(expr, ctx)
    return (table, tsquery, _context_clause(ctx))


class TestTheSmallSetIsInlined:
    def test_fetched_ids_become_a_literal_array(self):
        expr = _match(); probe = _Ctx()
        ctx = _Ctx(stats={_key(expr, probe): 2}, ids={_key(expr, probe): [U1, U2]})
        plan, bgp = _plan(expr)
        assert push_text_search(plan, SPACE, ctx) == 1
        _ref, sql = bgp.tagged_constraints[0]
        assert sql == f"q1.subject_uuid = ANY('{{{U1},{U2}}}'::uuid[])"
        assert "tsv @@" not in sql

    def test_an_empty_match_is_false_not_an_empty_array_scan(self):
        expr = _match("zzzz_absent"); probe = _Ctx()
        ctx = _Ctx(stats={_key(expr, probe): 0}, ids={_key(expr, probe): []})
        plan, bgp = _plan(expr)
        push_text_search(plan, SPACE, ctx)
        assert bgp.tagged_constraints[0][1] == "FALSE"

    def test_no_measurement_keeps_the_subquery(self):
        """No connection at generate time, or measurement failed: old form."""
        plan, bgp = _plan(_match())
        push_text_search(plan, SPACE, _Ctx())
        sql = bgp.tagged_constraints[0][1]
        assert "IN (SELECT subject_uuid FROM" in sql and "tsv @@" in sql


class TestTheLeafIsPriced:
    def test_an_exact_count_is_recorded_on_the_pinned_alias(self):
        expr = _match(); probe = _Ctx()
        plan, bgp = _plan(expr)
        push_text_search(plan, SPACE, _Ctx(stats={_key(expr, probe): 14}))
        assert bgp.fts_leaf_rows == {"q1": 14}

    def test_a_count_at_the_cap_is_a_lower_bound_and_is_dropped(self):
        """The refusal that keeps a broad term from displacing a narrow range."""
        expr = _match("app"); probe = _Ctx()
        plan, bgp = _plan(expr)
        push_text_search(plan, SPACE,
                         _Ctx(stats={_key(expr, probe): FTS_LEAF_COUNT_CAP + 1}))
        assert bgp.fts_leaf_rows == {}

    def test_leaf_cardinality_makes_it_an_anchor(self):
        bgp = PlanV2(kind=KIND_BGP, fts_leaf_rows={"q1": 14})
        ctx = SimpleNamespace(aliases=SimpleNamespace(
            constants={}, resolved_constants={}, quad_stats={},
            extra_quad_stats={}, pred_stats={}, range_stats={}))
        out = _leaf_cardinality(bgp, ctx)
        assert out["q1"] == 14
        # In the anchor contest, not merely ranked by rows: a range leaf roots
        # the chain OUTRIGHT, so an FTS leaf outside that set could never win
        # against one however few rows it matched.
        assert "q1" in out["__range_aliases__"]
