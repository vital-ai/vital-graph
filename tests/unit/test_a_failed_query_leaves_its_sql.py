"""A query that fails leaves its SPARQL, its SQL and its timings — `issues/259`.

`report_slow_query` is reached only when a query FINISHES, so a statement
cancelled by `statement_timeout` left three log lines naming the space and
nothing about the query. `issues/258` had to be diagnosed from SPARQL supplied by
hand and SQL regenerated locally.

Driven through `execute_sparql_query` itself, with the compile and generation
stubbed and a connection whose `fetch` raises the cancellation PostgreSQL
raises, so what is asserted is what the failure path actually logs.
"""

import asyncio
import contextlib
import json
import logging
from types import SimpleNamespace

import asyncpg
import pytest

from vitalgraph.db.sparql_sql import sparql_sql_space_impl as impl_mod
from vitalgraph.db.sparql_sql.plan_shape import sql_fingerprint

SPARQL = "SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } } # " + "x" * 600
SQL = "SELECT q.subject_uuid FROM sp_rdf_quad q /* " + "y" * 5000 + " */"


class _Conn:
    def __init__(self, exc):
        self.exc = exc

    def transaction(self):
        return _Tx()

    async def execute(self, *_a, **_k):
        return "SET"

    async def fetch(self, *_a, **_k):
        raise self.exc


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _run(monkeypatch, caplog, exc):
    gen = SimpleNamespace(ok=True, sql=SQL, var_map={}, vector_requests=None,
                          fuzzy_requests=None, needs_ordered_scan=False,
                          plan_decisions={"stage_ms": {"load_pair_stats": 1.5}})

    async def _compile(query, client):
        return {"ok": True}

    async def _generate(*_a, **_k):
        return gen

    @contextlib.asynccontextmanager
    async def _write_conn(pool, conn):
        yield _Conn(exc)

    monkeypatch.setattr(impl_mod._compile_cache, "compile", _compile)
    monkeypatch.setattr(impl_mod, "write_conn", _write_conn)
    monkeypatch.setattr(
        "vitalgraph.db.jena_sparql.jena_ast_mapper.map_compile_response",
        lambda raw: SimpleNamespace(ok=True, meta=SimpleNamespace(query_type="SELECT")))
    monkeypatch.setattr("vitalgraph.db.sparql_sql.generator.generate_sql", _generate)

    space = impl_mod.SparqlSQLSpaceImpl.__new__(impl_mod.SparqlSQLSpaceImpl)
    space.db_impl = SimpleNamespace(_pool=None)
    space._get_sidecar_client = lambda: None

    caplog.set_level(logging.WARNING, logger="vitalgraph.db.sparql_sql.plan_shape")
    result = asyncio.run(space.execute_sparql_query("sp", SPARQL))
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("failed_query ")]
    return result, lines


def test_a_cancelled_query_logs_what_it_was(monkeypatch, caplog):
    result, lines = _run(monkeypatch, caplog, asyncpg.QueryCanceledError(
        "canceling statement due to statement timeout"))

    assert result["success"] is False and result["timed_out"] is True
    assert len(lines) == 1, "a cancelled query must leave one failed_query line"
    rec = json.loads(lines[0][len("failed_query "):])
    assert rec["sparql"] == SPARQL, "the SPARQL, untruncated at this length"
    assert rec["sql"] == SQL, "the whole generated SQL, so the plan can be had later"
    assert rec["sql_fingerprint"] == sql_fingerprint(SQL)
    assert rec["stage"] == "execute"
    assert rec["timed_out"] is True
    assert rec["plan_decisions"]["stage_ms"] == {"load_pair_stats": 1.5}
    assert "failed_after_ms" in rec["timing"] and "generate_ms" in rec["timing"]
    assert "execute_ms_until_failure" in rec["timing"]


def test_any_failure_is_recorded_not_only_a_timeout(monkeypatch, caplog):
    result, lines = _run(monkeypatch, caplog, RuntimeError("connection reset"))
    assert result["timed_out"] is False
    rec = json.loads(lines[0][len("failed_query "):])
    assert rec["timed_out"] is False and "connection reset" in rec["error"]


def test_a_successful_query_does_not_log_its_text(monkeypatch, caplog):
    # The change is to the FAILURE path only: the request volume is why. A
    # guard: passes before and after the fix.

    class _OkConn(_Conn):
        async def fetch(self, *_a, **_k):
            return []

    @contextlib.asynccontextmanager
    async def _write_conn(pool, conn):
        yield _OkConn(None)

    gen = SimpleNamespace(ok=True, sql=SQL, var_map={}, vector_requests=None,
                          fuzzy_requests=None, needs_ordered_scan=False,
                          plan_decisions=None)

    async def _compile(query, client):
        return {"ok": True}

    async def _generate(*_a, **_k):
        return gen

    monkeypatch.setattr(impl_mod._compile_cache, "compile", _compile)
    monkeypatch.setattr(impl_mod, "write_conn", _write_conn)
    monkeypatch.setattr(
        "vitalgraph.db.jena_sparql.jena_ast_mapper.map_compile_response",
        lambda raw: SimpleNamespace(ok=True, meta=SimpleNamespace(query_type="SELECT")))
    monkeypatch.setattr("vitalgraph.db.sparql_sql.generator.generate_sql", _generate)
    monkeypatch.setattr("vitalgraph.db.sparql_sql.plan_shape.schedule_slow_query_report",
                        lambda **k: None)
    space = impl_mod.SparqlSQLSpaceImpl.__new__(impl_mod.SparqlSQLSpaceImpl)
    space.db_impl = SimpleNamespace(_pool=None)
    space._get_sidecar_client = lambda: None
    space._rows_to_sparql_bindings = lambda rows, var_map: []

    caplog.set_level(logging.INFO)
    result = asyncio.run(space.execute_sparql_query("sp", SPARQL))
    assert result["success"] is True
    assert not [r for r in caplog.records if "failed_query" in r.getMessage()]
    assert not [r for r in caplog.records if SPARQL[:40] in r.getMessage()]
