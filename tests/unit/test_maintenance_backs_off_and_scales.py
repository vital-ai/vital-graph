"""Maintenance stops repeating work that cannot finish or does not need doing — issue 270.

Production, 2026-10-16, while a bulk lead load grew the main KG space's quad table
from 50M to 79M rows and the database sat at its 3,000-IOPS limit:

* `edge_integrity`'s drift probe hit its statement timeout 59 times in 48 hours,
  and the type-agreement refresh 54 times. Nothing recorded the failure, so every
  cycle ran the same multi-minute scan again;
* the 79M-row table was re-ANALYZEd 57 times in 24 hours at 0.02% modified, each
  pass reading ~2.1 GB, because the trigger was an absolute 10,000 modifications.
  PostgreSQL's autovacuum (on, at 0.5% / 1%) never got to act on it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from vitalgraph.process import maintenance_job as M
from vitalgraph.db.sparql_sql import edge_type_agreement as eta


@pytest.fixture(autouse=True)
def _clean():
    M.reset_probe_gate()
    yield
    M.reset_probe_gate()


# --------------------------------------------------------------------------
# 1. A probe that times out is backed off
# --------------------------------------------------------------------------

class TestAProbeThatTimesOutIsBackedOff:

    def test_a_statement_timeout_backs_the_probe_off(self):
        M.log_probe_failure("edge_integrity", "kg",
                            asyncpg.QueryCanceledError("canceling statement due to statement timeout"))
        assert M.probe_backed_off("edge_integrity", "kg")
        assert not M.probe_backed_off("edge_integrity", "other_space")
        assert not M.probe_backed_off("frame_slot_integrity", "kg")

    def test_a_driver_timeout_counts_too(self):
        M.log_probe_failure("edge_integrity", "kg", asyncio.TimeoutError())
        assert M.probe_backed_off("edge_integrity", "kg")

    def test_any_other_failure_is_retried_next_cycle(self):
        M.log_probe_failure("edge_integrity", "kg", RuntimeError("a bug"))
        assert M.probe_backed_off("edge_integrity", "kg") is None

    def test_the_backoff_doubles_and_is_capped(self):
        delays = [M.note_probe_timeout("p", "kg") for _ in range(12)]
        assert delays[:3] == [M.PROBE_FAILURE_BACKOFF_S * k for k in (1, 2, 4)]
        assert max(delays) == M.PROBE_FAILURE_BACKOFF_MAX_S

    def test_one_success_clears_it(self):
        M.note_probe_timeout("edge_integrity", "kg")
        M.clear_probe_backoff("edge_integrity", "kg")
        assert M.probe_backed_off("edge_integrity", "kg") is None
        # and the next timeout starts the doubling again
        assert M.note_probe_timeout("edge_integrity", "kg") == M.PROBE_FAILURE_BACKOFF_S

    def test_the_integrity_loops_consult_it(self):
        import inspect
        for name, probe in (("_run_edge_integrity", "edge_integrity"),
                            ("_run_frame_slot_integrity", "frame_slot_integrity"),
                            ("_run_frame_slot_backfill", "frame_entity_integrity")):
            src = inspect.getsource(getattr(M.MaintenanceJob, name))
            assert f'probe_backed_off("{probe}", space_id)' in src, name
            assert f'clear_probe_backoff("{probe}", space_id)' in src, name


# --------------------------------------------------------------------------
# 2. A type-agreement refresh that times out is stored, and backed off
# --------------------------------------------------------------------------

class _RefreshConn:
    """Enough of a connection for `refresh_type_agreement` to reach its scan."""

    def __init__(self):
        self.executed = []

    async def fetchrow(self, sql, *args):
        return None                                   # no stored verdict yet

    async def fetchval(self, sql, *args, timeout=None):
        if sql.startswith("SELECT count(*)"):
            return 4_442_598
        if sql.strip().startswith("SELECT term_uuid FROM"):
            return "f947f06c-bd0c-5ae0-bcd6-6db005605b0a"
        if sql.startswith("SHOW "):
            return "60s"
        raise asyncpg.QueryCanceledError("canceling statement due to statement timeout")

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


def test_a_timed_out_refresh_is_recorded_as_unknown(monkeypatch):
    async def token(conn, table):
        return "tok"
    monkeypatch.setattr(eta, "change_token", token)
    conn = _RefreshConn()
    out = asyncio.run(eta.refresh_type_agreement(conn, "kg"))
    assert all("QueryCanceledError" in r["error"] for r in out)
    stored = [args for sql, args in conn.executed if "INSERT INTO type_agreement" in sql]
    assert len(stored) == 2, "one unknown verdict per kind"
    for args in stored:
        assert "agrees = NULL" in [sql for sql, a in conn.executed if a is args][0]
        assert args[-1] >= eta.REFRESH_TIMEOUT_MS, "the elapsed time marks it as a timeout"


class _StoredConn:
    def __init__(self, compute_ms, age_s):
        self.row = {"agrees": None, "change_token": "tok",
                    "compute_ms": compute_ms, "age_s": age_s}

    async def fetchrow(self, sql, *args):
        return self.row


def test_a_timed_out_verdict_is_backed_off_for_the_timeout_period():
    conn = _StoredConn(compute_ms=eta.REFRESH_TIMEOUT_MS, age_s=eta.BORN_STALE_BACKOFF_S + 60)
    why = asyncio.run(eta._refresh_not_needed(conn, "kg", "edge", "kg_edge"))
    assert why and "ran out" in why, "past the born-stale wait, still inside the timeout wait"
    conn = _StoredConn(compute_ms=eta.REFRESH_TIMEOUT_MS, age_s=eta.TIMEOUT_BACKOFF_S + 1)
    assert asyncio.run(eta._refresh_not_needed(conn, "kg", "edge", "kg_edge")) is None


def test_a_born_stale_verdict_keeps_its_own_shorter_wait():
    conn = _StoredConn(compute_ms=1_200, age_s=60)
    why = asyncio.run(eta._refresh_not_needed(conn, "kg", "frame", "kg_frame_slot"))
    assert why and "write rate" in why
    conn = _StoredConn(compute_ms=1_200, age_s=eta.BORN_STALE_BACKOFF_S + 1)
    assert asyncio.run(eta._refresh_not_needed(conn, "kg", "frame", "kg_frame_slot")) is None


# --------------------------------------------------------------------------
# 3. ANALYZE and VACUUM are due at a fraction of the table, not a fixed count
# --------------------------------------------------------------------------

def _space(mods=0, dead=0, live=0, minutes_ago=60):
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {"n_mod_since_analyze": mods, "n_dead_tup": dead, "n_live_tup": live,
            "last_analyze": t, "last_vacuum": t}


def _job():
    return M.MaintenanceJob.__new__(M.MaintenanceJob)


class TestTheGatesScaleWithTheTable:

    def test_the_production_table_is_not_reanalyzed_at_point_zero_two_percent(self):
        stats = {"prod_scale": _space(mods=14_206, dead=10_500, live=79_000_000)}
        assert _job()._pick_worst_for_analyze(stats) is None
        assert _job()._pick_worst_for_vacuum(stats) is None

    def test_it_is_due_once_two_percent_has_changed(self):
        stats = {"big": _space(mods=1_600_000, dead=1_600_000, live=79_000_000)}
        assert _job()._pick_worst_for_analyze(stats) == "big"
        assert _job()._pick_worst_for_vacuum(stats) == "big"

    def test_a_small_table_keeps_the_absolute_floor(self):
        stats = {"small": _space(mods=M.ANALYZE_MOD_THRESHOLD, dead=M.VACUUM_DEAD_THRESHOLD,
                                 live=50_000)}
        assert _job()._pick_worst_for_analyze(stats) == "small"
        assert _job()._pick_worst_for_vacuum(stats) == "small"

    def test_a_never_analyzed_space_is_still_picked(self):
        stats = {"new": {"n_mod_since_analyze": 0, "n_dead_tup": 0, "n_live_tup": 79_000_000,
                         "last_analyze": None, "last_vacuum": None}}
        assert _job()._pick_worst_for_analyze(stats) == "new"

    def test_the_per_table_gate_scales_too(self):
        row = {"relname": "kg_rdf_quad", "n_mod_since_analyze": 14_206, "n_dead_tup": 0,
               "n_live_tup": 79_000_000, "ever_analyzed": True, "ever_vacuumed": True}
        assert not M.MaintenanceJob._needs("ANALYZE", row)
        row["n_mod_since_analyze"] = 1_600_000
        assert M.MaintenanceJob._needs("ANALYZE", row)

    def test_the_stats_rows_carry_live_rows(self):
        rows = [{"relname": "kg_rdf_quad", "n_mod_since_analyze": 5, "n_dead_tup": 1,
                 "n_live_tup": 79_000_000, "last_analyze": None, "last_autoanalyze": None,
                 "last_vacuum": None, "last_autovacuum": None},
                {"relname": "kg_term", "n_mod_since_analyze": 5, "n_dead_tup": 1,
                 "n_live_tup": 13_000_000, "last_analyze": None, "last_autoanalyze": None,
                 "last_vacuum": None, "last_autovacuum": None}]
        assert M.MaintenanceJob._aggregate_space_stats(rows)["kg"]["n_live_tup"] == 92_000_000
