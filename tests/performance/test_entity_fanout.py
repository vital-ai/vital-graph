"""The hub list must be correct, bounded, and cheap.

`{space}_entity_fanout` records how wide a traversal gets from one entity —
the statistic `edge_fanout` cannot give, because that one is an aggregate over
the whole space. See `sync_entity_fanout` for why it is a LIST of hubs rather
than a row per entity.

The property that matters is not "the table has rows". It is that an entity
ABSENT from the list is genuinely not a hub, because that is what lets a caller
read absence as "small" instead of "unknown" — the opposite of how every other
statistic in this package behaves.
"""

from __future__ import annotations

import time

import pytest

from .conftest import skip_no_pg, space_exists
from .graph_fixtures import SMALL

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]


async def _rebuilt(conn, space):
    from vitalgraph.db.sparql_sql.sync_entity_fanout import (
        resync_entity_fanout, MIN_FANOUT_DEFAULT, TOP_N_DEFAULT)
    written = await resync_entity_fanout(conn, space)
    return written, MIN_FANOUT_DEFAULT, TOP_N_DEFAULT


async def test_the_hub_list_matches_the_real_fanout(perf_conn):
    """The recorded fan-out is the actual DISTINCT neighbour count.

    Checked against the source table rather than against itself, so a wrong
    GROUP BY or a count of edges instead of neighbours is visible. Two frames
    connecting the same pair of entities are ONE step of a walk.
    """
    fx = SMALL
    if not await space_exists(perf_conn, fx.space):
        pytest.skip(f"space {fx.space} not loaded")
    await _rebuilt(perf_conn, fx.space)

    rows = await perf_conn.fetch(
        f"SELECT entity_uuid, context_uuid, fanout FROM {fx.space}_entity_fanout "
        f"WHERE direction='forward' ORDER BY fanout DESC LIMIT 20")
    assert rows, "no hubs recorded"
    for r in rows:
        actual = await perf_conn.fetchval(
            f"SELECT count(DISTINCT dest_entity_uuid) FROM {fx.space}_frame_entity "
            f"WHERE source_entity_uuid=$1 AND context_uuid=$2",
            r["entity_uuid"], r["context_uuid"])
        assert r["fanout"] == actual, (
            f"recorded {r['fanout']} but the entity has {actual} distinct "
            f"neighbours — the statistic is counting the wrong thing")


async def test_absence_from_the_list_means_not_a_hub(perf_conn):
    """The property a caller depends on.

    Absence has to be a positive statement — "this entity's fan-out is below the
    threshold" — or reading None as "small" would be unsound. That holds only if
    the list is complete down to its own cut-off, which is what this checks: the
    widest entity NOT in the list must be below the threshold.
    """
    fx = SMALL
    if not await space_exists(perf_conn, fx.space):
        pytest.skip(f"space {fx.space} not loaded")
    _w, min_fanout, top_n = await _rebuilt(perf_conn, fx.space)

    n_hubs = await perf_conn.fetchval(
        f"SELECT count(*) FROM {fx.space}_entity_fanout WHERE direction='forward'")
    if n_hubs >= top_n:
        pytest.skip("list hit the top-N cap, so absence is a cap artefact here")

    widest_absent = await perf_conn.fetchval(f"""
        SELECT COALESCE(max(n), 0) FROM (
            SELECT source_entity_uuid s, context_uuid c,
                   count(DISTINCT dest_entity_uuid) n
            FROM {fx.space}_frame_entity
            WHERE source_entity_uuid IS NOT NULL AND dest_entity_uuid IS NOT NULL
            GROUP BY 1, 2) d
        WHERE NOT EXISTS (
            SELECT 1 FROM {fx.space}_entity_fanout f
            WHERE f.entity_uuid=d.s AND f.context_uuid=d.c AND f.direction='forward')
    """)
    assert widest_absent < min_fanout, (
        f"an entity with fan-out {widest_absent} is missing from the list while "
        f"the threshold is {min_fanout} — absence no longer means 'not a hub'")


async def test_the_list_is_bounded_and_the_rebuild_is_cheap(perf_conn):
    """It must not scale with the entity count; that is the whole design.

    A row per entity would be millions. The generous time bound is a smoke test
    for an accidental per-entity scan, not a performance assertion.
    """
    fx = SMALL
    if not await space_exists(perf_conn, fx.space):
        pytest.skip(f"space {fx.space} not loaded")

    t = time.perf_counter()
    written, _min_f, top_n = await _rebuilt(perf_conn, fx.space)
    elapsed = (time.perf_counter() - t) * 1000

    for direction, n in written.items():
        assert n <= top_n, f"{direction} kept {n} rows, above the {top_n} cap"
    assert elapsed < 30_000, (
        f"rebuilding the hub list took {elapsed:.0f} ms — it should be a couple "
        f"of GROUP BYs, not a per-entity scan")
