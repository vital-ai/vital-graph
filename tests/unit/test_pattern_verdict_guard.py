"""A plan that relies on a stored pattern verdict runs only in a snapshot where
the space is unchanged since the verdict (`pattern_verdict`, planning_planner/09).

Driven through `execute_sparql_query` itself, with the compile, generation and
the guard check stubbed:

  * guard holds        -> the statement runs inside a REPEATABLE READ, read-only
                          transaction, on the plan that used the verdict;
  * guard fails        -> planned again with `planner_verdicts=False`, and that
                          plan runs, outside any verdict;
  * caller transaction -> no REPEATABLE READ to be had: planned again without
                          verdicts before anything runs.
"""

import asyncio
import contextlib
from types import SimpleNamespace

from vitalgraph.db.sparql_sql import sparql_sql_space_impl as impl_mod

GUARDED = "SELECT 'guarded'"
PLAIN = "SELECT 'plain'"


class _Tx:
    def __init__(self, conn, kw):
        self.conn, self.kw = conn, kw

    async def __aenter__(self):
        self.conn.txs.append(self.kw)
        self.conn.depth += 1
        return self

    async def __aexit__(self, *a):
        self.conn.depth -= 1
        return False


class _Conn:
    def __init__(self, in_caller_tx=False):
        self.txs, self.ran, self.depth = [], [], 0
        self.in_caller_tx = in_caller_tx

    def is_in_transaction(self):
        return self.in_caller_tx or self.depth > 0

    def transaction(self, **kw):
        return _Tx(self, kw)

    async def execute(self, *_a, **_k):
        return "SET"

    async def fetch(self, sql, *_a, **_k):
        self.ran.append((sql, dict(self.txs[-1]) if self.txs else None))
        return []


def _gen(sql, guard):
    return SimpleNamespace(ok=True, sql=sql, var_map={}, vector_requests=None, fuzzy_requests=None,
                           needs_ordered_scan=False, plan_advice=None, fixed_join_order=False,
                           plan_source="qtree", plan_decisions={}, verdict_guard=guard)


def _run(monkeypatch, conn, guard_ok):
    calls = []

    async def _compile(query, client):
        return {"ok": True}

    async def _generate(*_a, **kw):
        calls.append(kw.get("planner_verdicts", True))
        return _gen(GUARDED, ("sp", 7, 99)) if kw.get("planner_verdicts", True) else _gen(PLAIN, None)

    async def _guard_holds(_conn, space, guard):
        assert space == "sp" and tuple(guard) == (7, 99)
        return guard_ok

    @contextlib.asynccontextmanager
    async def _write_conn(pool, c):
        yield conn

    monkeypatch.setattr(impl_mod._compile_cache, "compile", _compile)
    monkeypatch.setattr(impl_mod, "write_conn", _write_conn)
    monkeypatch.setattr(
        "vitalgraph.db.jena_sparql.jena_ast_mapper.map_compile_response",
        lambda raw: SimpleNamespace(ok=True, meta=SimpleNamespace(query_type="SELECT")))
    monkeypatch.setattr("vitalgraph.db.sparql_sql.generator.generate_sql", _generate)
    monkeypatch.setattr("vitalgraph.db.sparql_sql.pattern_verdict.guard_holds", _guard_holds)

    space = impl_mod.SparqlSQLSpaceImpl.__new__(impl_mod.SparqlSQLSpaceImpl)
    space.db_impl = SimpleNamespace(_pool=None)
    space._get_sidecar_client = lambda: None
    asyncio.run(space.execute_sparql_query("sp", "SELECT ?s WHERE { ?s ?p ?o }"))
    return calls


def test_guard_holds_runs_the_guarded_plan_in_repeatable_read(monkeypatch):
    conn = _Conn()
    calls = _run(monkeypatch, conn, guard_ok=True)
    assert calls == [True]
    assert conn.ran == [(GUARDED, {"isolation": "repeatable_read", "readonly": True})]


def test_guard_fails_plans_again_without_verdicts(monkeypatch):
    conn = _Conn()
    calls = _run(monkeypatch, conn, guard_ok=False)
    assert calls == [True, False]
    assert [sql for sql, _ in conn.ran] == [PLAIN]
    assert conn.ran[0][1] == {}          # an ordinary transaction, not the guarded one


def test_inside_a_callers_transaction_never_uses_a_verdict(monkeypatch):
    conn = _Conn(in_caller_tx=True)
    calls = _run(monkeypatch, conn, guard_ok=True)
    assert calls == [True, False]
    assert [sql for sql, _ in conn.ran] == [PLAIN]
