"""The incremental stats writer must not invent a row for a pruned pair.

`sync_stats_after_insert` splits its work by `rdf_pred_stats.pruned`: unpruned
predicates take an upsert, pruned ones take UPDATE-only, so a pair the prune
removed stays absent instead of coming back holding only a delta (`issues/062`).

The split is decided in Python from a snapshot read of the flag, and the read is
not serialised against `prune_stats_tables`. A predicate that becomes pruned
between the read and the write lands on the upsert path, finds no row to
conflict with, and CREATES one — a pair whose true count is 76,346 recorded as
80. Nothing detects it afterwards: a wrong LOW value sorts away from the
integrity check's sample (`issues/141`).

These tests pin the SQL, which now re-checks the flag in-statement. See
`issues/142`.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    # session loop scope, matching the rest of the suite: the pool fixture is
    # session-scoped, and a per-test loop makes asyncpg raise "attached to a
    # different loop" before any assertion runs.
    pytest.mark.asyncio(loop_scope="session"),
]

_INSERT = """
    INSERT INTO t_stats (predicate_uuid, object_uuid, row_count)
    SELECT $1, $2, $3 WHERE NOT EXISTS (
        SELECT 1 FROM t_pred p WHERE p.predicate_uuid = $1 AND p.pruned)
    ON CONFLICT (predicate_uuid, object_uuid)
    DO UPDATE SET row_count = t_stats.row_count + EXCLUDED.row_count
"""


async def _setup(conn):
    """Minimal stand-ins for {space}_rdf_pred_stats and {space}_rdf_stats.

    Done inline rather than in an async fixture: wrapping the session-scoped
    `pg_conn` in another async fixture runs it on a different event loop and
    asyncpg raises "attached to a different loop".
    """
    await conn.execute("DROP TABLE IF EXISTS t_stats, t_pred")
    await conn.execute(
        "CREATE TABLE t_pred (predicate_uuid text PRIMARY KEY, "
        "pruned boolean NOT NULL DEFAULT false)")
    await conn.execute(
        "CREATE TABLE t_stats (predicate_uuid text, object_uuid text, "
        "row_count bigint, PRIMARY KEY (predicate_uuid, object_uuid))")
    await conn.execute(
        "INSERT INTO t_pred VALUES ('P_ok', false), ('P_pruned', true)")
    await conn.execute(
        "INSERT INTO t_stats VALUES ('P_ok', 'o_existing', 1000)")


async def _count(conn, p, o):
    return await conn.fetchval(
        "SELECT row_count FROM t_stats WHERE predicate_uuid=$1 AND object_uuid=$2",
        p, o)


async def test_existing_pair_is_still_incremented(pg_conn):
    """The guard must not break the case this path exists for."""
    conn = pg_conn
    await _setup(conn)
    await conn.execute(_INSERT, "P_ok", "o_existing", 5)
    assert await _count(conn, "P_ok", "o_existing") == 1005


async def test_a_genuinely_new_pair_is_still_recorded(pg_conn):
    """An unpruned predicate's new pair is new data, and its delta IS its count."""
    conn = pg_conn
    await _setup(conn)
    await conn.execute(_INSERT, "P_ok", "o_new", 5)
    assert await _count(conn, "P_ok", "o_new") == 5


async def test_a_pruned_predicate_cannot_gain_a_row(pg_conn):
    """The race, and the whole point: absent + pruned must stay absent.

    Without the in-statement re-check this writes row_count=5 for a pair whose
    true count is whatever the prune removed — the wrong-LOW value that the
    join reorder then reads as a rare pair.
    """
    conn = pg_conn
    await _setup(conn)
    await conn.execute(_INSERT, "P_pruned", "o_absent", 5)
    assert await _count(conn, "P_pruned", "o_absent") is None
