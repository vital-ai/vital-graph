"""A drift probe that cannot answer must skip LOUDLY, and get the time to answer.

`issues/144`. All three derived-table integrity checks sat under:

    except Exception:
        continue  # space predates the table, or is not a KG space

Skipping is the right action — a probe that cannot answer must not trigger a
repair — but the comment asserts a benign cause, and the clause catches every
other one identically. What actually happened on prod: `entity_slot_sort_drift`
computes its expected count with the full unseeded `WITH RECURSIVE frame_walk`,
measured at 76s against the read path's 60s `statement_timeout`. So it timed out
every cycle, was read as "not a KG space", and the backfill never ran. The table
it should maintain is 0.6% populated, which is why the entity listing page sorts
its whole population to return 25 rows.

Two properties, and the fix needs both — raising the budget without reporting
failure would just move the silence, and reporting without raising the budget
would report every cycle forever.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import asyncpg
import pytest

from vitalgraph.process import maintenance_job as M


class _Conn:
    def __init__(self, statement_timeout="60s"):
        self.statements: list[str] = []
        self._st = statement_timeout

    async def fetchval(self, sql, *_a):
        self.statements.append(sql)
        return self._st if "statement_timeout" in sql else None

    async def execute(self, sql, *_a):
        self.statements.append(sql)
        return "SET"


@pytest.mark.asyncio
async def test_a_probe_gets_the_maintenance_budget_not_the_read_path_fence():
    conn = _Conn(statement_timeout="60s")
    async with M.probe_timeouts(conn):
        pass

    assert conn.statements[0] == "SHOW statement_timeout"
    assert conn.statements[1] == (
        f"SET statement_timeout = {M.MAINTENANCE_STATEMENT_TIMEOUT_MS}")
    assert M.MAINTENANCE_STATEMENT_TIMEOUT_MS > 76_000, (
        "the measured probe takes 76s on prod; a budget below that leaves "
        "issues/144 in place")


@pytest.mark.asyncio
async def test_the_budget_does_not_outlive_the_probe():
    """The connection goes back to a pool that also serves user queries."""
    conn = _Conn(statement_timeout="60s")
    async with M.probe_timeouts(conn):
        pass
    assert conn.statements[-1] == "SET statement_timeout = '60s'"


@pytest.mark.asyncio
async def test_the_budget_is_restored_when_the_probe_raises():
    conn = _Conn(statement_timeout="60s")
    with pytest.raises(asyncpg.QueryCanceledError):
        async with M.probe_timeouts(conn):
            raise asyncpg.QueryCanceledError("canceling statement")
    assert conn.statements[-1] == "SET statement_timeout = '60s'"


def test_a_timeout_is_reported_at_warning_with_its_consequence(caplog):
    """The message has to name what was skipped. "probe failed" alone reads as
    cosmetic; the reader needs to know a REPAIR did not happen."""
    with caplog.at_level("WARNING"):
        M.log_probe_failure(
            "entity_slot_sort_integrity", "sp_x",
            asyncpg.QueryCanceledError("canceling statement due to timeout"))

    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "sp_x" in msg
    assert "QueryCanceledError" in msg
    assert "not be repaired" in msg.lower(), (
        "must name the consequence, not just the error")


def test_the_benign_case_stays_quiet():
    """A non-KG space has no such table, and that is not news every 300s."""
    import inspect
    src = inspect.getsource(M)
    assert src.count("except asyncpg.UndefinedTableError:") == 3, (
        "all three drift probes must distinguish 'no table' from 'could not "
        "answer'; a bare except on any of them is issues/144 again")
    assert src.count("log_probe_failure(") == 4, (
        "3 call sites + 1 definition — every probe reports its non-benign "
        "failures")
