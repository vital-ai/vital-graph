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


# --------------------------------------------------------------------------
# issues/346: the warm set is ranked by MEASURED access, not by size
# --------------------------------------------------------------------------
#
# Production 2026-11-16: the prewarmed space had grown to 23.1 GiB against a 12 GiB
# cap, and "core first, largest first" filled the cap with the biggest relations.
# Over 30 minutes the warm set covered 37.6 % of the space's block accesses; ranked by
# accesses per byte the same cap covers 97.9 %. The write path's sync lookups read
# relations that were never warmed: 0.2-0.8 ms warm, 173 / 80 ms on production.

class _CountingConn:
    """A space with a big cold core index and a small hot non-core one, cap fits one."""

    def __init__(self, rows):
        self.rows = rows
        self.acc = {r["rel"]: 1_000 for r in rows}
        self.prewarmed = []
        self.passes = []
        self.unreadable = False

    async def fetchval(self, sql, *args, timeout=None):
        if "pg_extension" in sql:
            return True
        if "pg_prewarm(" in sql:
            rel = args[0]
            self.prewarmed.append(rel)
            blocks = next(int(r["bytes"]) // 8192 for r in self.rows if r["rel"] == rel)
            self.acc[rel] += blocks           # the job's own touches count, as in PostgreSQL
            return blocks
        if "pg_statio_user_tables" in sql:
            return 0
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        if "pg_statio_user_indexes" in sql:
            if self.unreadable:
                raise RuntimeError("permission denied for pg_statio")
            return [{"rel": rel, "acc": self.acc[rel]} for rel in args[0]]
        return self.rows

    def cycle(self, real_accesses):
        """Accesses by everything else between two passes."""
        for rel, n in real_accesses.items():
            self.acc[rel] += n


MIB = 2**20
COLD_CORE = _rel("uw_rdf_quad", "uw_quad_ctx_pred", True, 300 * MIB)   # big, core, barely read
HOT_SYNC = _rel("uw_edge", "uw_edge_dst_src", True, 40 * MIB)          # small, non-core, hot


def _run(job):
    before = len(job._pool.conn.prewarmed)
    asyncio.run(job.run())
    return job._pool.conn.prewarmed[before:]


def test_the_first_pass_uses_the_default_order():
    conn = _CountingConn([COLD_CORE, HOT_SYNC])
    job = P.PrewarmJob(_Pool(conn), ["uw"], max_bytes=310 * MIB)
    assert _run(job) == ["uw_quad_ctx_pred"], "unmeasured: core first, as before"


def test_measured_access_per_byte_decides_the_next_pass():
    conn = _CountingConn([COLD_CORE, HOT_SYNC])
    job = P.PrewarmJob(_Pool(conn), ["uw"], max_bytes=310 * MIB)
    _run(job)
    conn.cycle({"uw_quad_ctx_pred": 1_000, "uw_edge_dst_src": 50_000})
    _run(job)                                 # this pass measures; the next one uses it
    conn.cycle({"uw_quad_ctx_pred": 1_000, "uw_edge_dst_src": 50_000})
    assert _run(job) == ["uw_edge_dst_src"]


def test_the_jobs_own_touches_are_not_counted_as_use():
    """Without the subtraction the warmed relation looks hottest because it was warmed:
    pg_prewarm touches every block of it every pass."""
    conn = _CountingConn([COLD_CORE, HOT_SYNC])
    job = P.PrewarmJob(_Pool(conn), ["uw"], max_bytes=310 * MIB)
    _run(job)
    _run(job)                                 # nothing else touched either relation
    assert job.access_rate["uw_quad_ctx_pred"] == 0.0
    assert job.access_rate["uw_edge_dst_src"] == 0.0


def test_a_stats_reset_changes_nothing():
    conn = _CountingConn([COLD_CORE, HOT_SYNC])
    job = P.PrewarmJob(_Pool(conn), ["uw"], max_bytes=310 * MIB)
    _run(job)
    conn.cycle({"uw_edge_dst_src": 50_000})
    _run(job)
    rate = dict(job.access_rate)
    conn.acc = {rel: 0 for rel in conn.acc}   # pg_stat_reset()
    _run(job)
    assert job.access_rate == rate, "a counter moving backwards must not read as idle or as hot"


def test_unreadable_counters_keep_the_default_order():
    conn = _CountingConn([COLD_CORE, HOT_SYNC])
    conn.unreadable = True
    job = P.PrewarmJob(_Pool(conn), ["uw"], max_bytes=310 * MIB)
    for _ in range(3):
        assert _run(job) == ["uw_quad_ctx_pred"]


def test_one_burst_does_not_reorder_the_set():
    """A decayed rate: one pass of heavy use on a cold relation does not displace a
    relation that has been hot for many passes."""
    conn = _CountingConn([COLD_CORE, HOT_SYNC])
    job = P.PrewarmJob(_Pool(conn), ["uw"], max_bytes=310 * MIB)
    _run(job)
    for _ in range(10):
        conn.cycle({"uw_edge_dst_src": 50_000})
        _run(job)
    conn.cycle({"uw_quad_ctx_pred": 200_000})  # one maintenance scan's worth
    _run(job)
    conn.cycle({"uw_edge_dst_src": 50_000})
    assert _run(job) == ["uw_edge_dst_src"]


def test_a_new_relation_is_ranked_after_the_measured_ones():
    new = _rel("uw_edge", "uw_edge_new_idx", True, 10 * MIB)
    rate = {"uw_edge_dst_src": 5.0, "uw_quad_ctx_pred": 1.0}
    order = [r["relname"] for r in P.order_by_access([COLD_CORE, HOT_SYNC, new], TABLES, rate)]
    assert order == ["uw_edge_dst_src", "uw_quad_ctx_pred", "uw_edge_new_idx"]
