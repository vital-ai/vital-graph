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

import pytest

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


class TestThePairOfGenerationsShareOneCount:
    """One request generates SQL TWICE — the page and the count — and each
    measured the same leaf. Production shows the pair as near-identical timings
    in the same second (3,534 ms and 3,531 ms; 2,500 ms and 2,498 ms), against a
    201 ms mean and a 3,676 ms max for the statement.

    The capped count is memoised; the INLINED ID SET never is. The count is an
    optimiser input, already a lower bound at its cap, and a stale one can only
    mis-order a join. The id set becomes `= ANY(ARRAY[...])` — the rows the
    caller receives — so a stale one would silently drop messages indexed since
    it was taken.
    """

    @staticmethod
    def _run(monkeypatch, n_rows, calls):
        import asyncio
        from vitalgraph.db.sparql_sql import db_provider, generator as gen

        async def fake_execute_query(sql, **kw):
            calls.append(sql)
            if sql.lstrip().startswith("SELECT subject_uuid"):
                return [{"u": U1}] * n_rows
            return [{"n": n_rows}]

        # `_measure_fts_leaves` imports db_provider inside the function.
        monkeypatch.setattr(db_provider, "execute_query", fake_execute_query)
        expr = _match("app")
        plan, _bgp = _plan(expr)
        ctx = _Ctx()
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            gen._measure_fts_leaves(plan, ctx, conn=object()))
        return ctx

    @pytest.mark.asyncio
    async def test_concurrent_generations_share_one_measurement(self, monkeypatch):
        """THE case this exists for, and the one a plain memo does not cover.

        `_gather_cancelling(page, count)` starts both generations at once, so
        both miss a completed-only memo. Production logs show the pair finishing
        1 ms apart having taken 3,531 ms and 3,534 ms — side by side, not one
        after the other.
        """
        import asyncio
        from vitalgraph.db.sparql_sql import db_provider, generator as gen
        gen._FTS_COUNT_MEMO.clear(); gen._FTS_COUNT_INFLIGHT.clear()
        calls: list = []
        started = asyncio.Event()

        async def slow_query(sql, **kw):
            calls.append(sql)
            if sql.lstrip().startswith("SELECT subject_uuid"):
                return [{"u": U1}] * (gen.FTS_INLINE_MAX + 1)
            started.set()
            await asyncio.sleep(0.05)       # the other generation starts here
            return [{"n": 4600}]

        monkeypatch.setattr(db_provider, "execute_query", slow_query)
        expr = _match("app")
        plan_a, _ = _plan(expr)
        plan_b, _ = _plan(expr)
        ctx_a, ctx_b = _Ctx(), _Ctx()
        await asyncio.gather(
            gen._measure_fts_leaves(plan_a, ctx_a, conn=object()),
            gen._measure_fts_leaves(plan_b, ctx_b, conn=object()))
        counts = [c for c in calls if "count(*)" in c]
        assert len(counts) == 1, f"both generations measured: {len(counts)} counts"
        assert list(ctx_a.aliases.fts_leaf_stats.values()) == [4600]
        assert list(ctx_b.aliases.fts_leaf_stats.values()) == [4600]
        gen._FTS_COUNT_MEMO.clear()

    @pytest.mark.asyncio
    async def test_a_waiter_measures_for_itself_when_the_owner_fails(self):
        """A shared failure must not become two callers with no price."""
        import asyncio
        from vitalgraph.db.sparql_sql import generator as gen
        gen._FTS_COUNT_MEMO.clear(); gen._FTS_COUNT_INFLIGHT.clear()
        key = ("t", "q", "")
        loop = asyncio.get_running_loop()
        doomed = loop.create_future()
        doomed.add_done_callback(lambda f: f.cancelled() or f.exception())
        gen._FTS_COUNT_INFLIGHT[key] = doomed
        doomed.set_exception(RuntimeError("owner lost its connection"))

        async def ok(sql, **kw):
            return [{"n": 7}]

        from vitalgraph.db.sparql_sql import db_provider
        orig = db_provider.execute_query
        db_provider.execute_query = ok
        try:
            assert await gen._fts_capped_count(key, "SELECT 1", conn=object()) == 7
        finally:
            db_provider.execute_query = orig
            gen._FTS_COUNT_MEMO.clear(); gen._FTS_COUNT_INFLIGHT.clear()

    def test_a_broad_count_is_reused_by_the_second_generation(self, monkeypatch):
        from vitalgraph.db.sparql_sql import generator as gen
        gen._FTS_COUNT_MEMO.clear()
        calls: list = []
        # Above FTS_INLINE_MAX, so the id fetch overflows and the separate
        # capped COUNT runs — the expensive statement.
        big = gen.FTS_INLINE_MAX + 1
        self._run(monkeypatch, big, calls)
        first = [c for c in calls if "count(*)" in c]
        self._run(monkeypatch, big, calls)
        second = [c for c in calls if "count(*)" in c]
        assert len(first) == 1, "the first generation must measure"
        assert len(second) == 1, "the second must reuse it, not re-measure"
        gen._FTS_COUNT_MEMO.clear()

    def test_the_inlined_id_set_is_never_reused(self, monkeypatch):
        """A memoised id set would return a page missing anything indexed since.
        The ids are also the cheap half, sharing their round trip with the
        count they replace, so there is nothing to win by caching them."""
        from vitalgraph.db.sparql_sql import generator as gen
        gen._FTS_COUNT_MEMO.clear()
        calls: list = []
        small = 2
        ctx1 = self._run(monkeypatch, small, calls)
        ctx2 = self._run(monkeypatch, small, calls)
        fetches = [c for c in calls if c.lstrip().startswith("SELECT subject_uuid")]
        assert len(fetches) == 2, "every generation re-reads the ids it will inline"
        assert ctx1.aliases.fts_leaf_ids and ctx2.aliases.fts_leaf_ids
        gen._FTS_COUNT_MEMO.clear()
