"""The prewarm job keeps named spaces resident, and only those — issues/271."""

from __future__ import annotations

import asyncio
import logging

from vitalgraph.process import prewarm_job as P


def _rel(table, name, is_index, size):
    return {"rel": name, "relname": name, "table_name": table,
            "is_index": is_index, "bytes": size}


TABLES = {"rdf_quad": "uw_rdf_quad", "term": "uw_term", "edge": "uw_edge"}


def test_the_write_path_indexes_are_warmed_first():
    rows = [_rel("uw_edge", "uw_edge", False, 9_000),
            _rel("uw_rdf_quad", "uw_rdf_quad", False, 5_000),
            _rel("uw_rdf_quad", "uw_quad_pkey", True, 3_000),
            _rel("uw_term", "uw_term_pkey", True, 4_000),
            _rel("uw_edge", "uw_edge_src", True, 8_000)]
    order = [r["relname"] for r in P.order_relations(rows, TABLES)]
    assert order == ["uw_term_pkey", "uw_quad_pkey", "uw_rdf_quad",
                     "uw_edge", "uw_edge_src"]


def test_the_cap_skips_whole_relations_and_reports_them():
    rows = [_rel("t", "a", True, 600), _rel("t", "b", True, 500),
            _rel("t", "c", True, 300), _rel("t", "empty", True, 0)]
    kept, skipped = P.apply_cap(rows, 1_000)
    assert [r["relname"] for r in kept] == ["a", "c"]
    assert [r["relname"] for r in skipped] == ["b"]


def test_spaces_are_opt_in(monkeypatch):
    monkeypatch.delenv("VG_PREWARM_SPACES", raising=False)
    assert P.prewarm_spaces_from_env() == []
    monkeypatch.setenv("VG_PREWARM_SPACES", " prod_uw , ,other ")
    assert P.prewarm_spaces_from_env() == ["prod_uw", "other"]


def test_it_is_registered_single_runner_and_only_when_configured():
    # READ the module, do not import it: `vitalgraphapp_impl` pulls in the whole
    # server chain (itsdangerous and the rest), which the unit tier does not
    # install — CI failed on exactly that import.
    from pathlib import Path
    src = (Path(P.__file__).parent.parent / "impl" / "vitalgraphapp_impl.py").read_text()
    block = src[src.index('name="space_prewarm"') - 400: src.index('name="space_prewarm"') + 400]
    assert "if prewarm_spaces:" in block
    assert "single_runner=True" in block
    assert "bg_pool" in block, "must not take request-serving connections"


class _Conn:
    def __init__(self, has_ext=True, rows=()):
        self.has_ext, self.rows, self.prewarmed = has_ext, list(rows), []

    async def fetchval(self, sql, *args, timeout=None):
        if "pg_extension" in sql:
            return self.has_ext
        if "pg_prewarm(" in sql:
            self.prewarmed.append(args[0])
            return 10
        if "pg_statio_user_tables" in sql:
            return 0
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        return self.rows


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


def test_a_missing_extension_warns_once_and_does_nothing(caplog):
    conn = _Conn(has_ext=False)
    job = P.PrewarmJob(_Pool(conn), ["uw"])
    with caplog.at_level(logging.WARNING):
        asyncio.run(job.run())
        asyncio.run(job.run())
    assert sum("pg_prewarm is not installed" in r.getMessage() for r in caplog.records) == 1
    assert conn.prewarmed == []


def test_a_pass_prewarms_every_relation_of_the_space(caplog):
    conn = _Conn(rows=[_rel("uw_rdf_quad", "uw_rdf_quad", False, 8192),
                       _rel("uw_rdf_quad", "uw_rdf_quad_pkey", True, 8192)])
    job = P.PrewarmJob(_Pool(conn), ["uw"])
    with caplog.at_level(logging.INFO):
        out = asyncio.run(job.run())
    assert conn.prewarmed == ["uw_rdf_quad_pkey", "uw_rdf_quad"]
    assert out["spaces"]["uw"]["blocks"] == 20
    assert any("prewarm uw:" in r.getMessage() for r in caplog.records)
