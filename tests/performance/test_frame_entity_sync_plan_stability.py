"""The frame_entity sync must not get slower the longer a connection lives.

It did, and nothing else in the suite could see it.

PostgreSQL plans a prepared statement per-parameter for its first five
executions, then decides whether a GENERIC plan is competitive. For the
frame_entity insert it decided wrongly by roughly 5,000x. Measured on
`wordnet_frames`, syncing five touched frames on one connection:

    plan_cache_mode=auto           [4, 1, 2, 1, 1, 10186, 8094, 8885, 8581] ms
    plan_cache_mode=force_custom   [1, 1, 1, 1, 1,     1,    1,    1,    1] ms

Runs one to five are a millisecond; run six onwards is EIGHT SECONDS and stays
there, because a prepared statement lives as long as the connection. A pooled
connection therefore degraded permanently after its fifth write.

WHY THIS TEST IS HERE AND NOT IN tests/integration

It was written there first and PASSED with the fix reverted — proving nothing.
A freshly created test space holds a handful of rows, so even the generic plan
is fast; the eight seconds come from seq-scanning `wordnet_frames`' 570,696-row
edge table. The bug only exists at scale, so the guard has to run against a
loaded space.

The sync runs inside a transaction that is rolled back, so the space is left
exactly as found.
"""

from __future__ import annotations

import statistics
import time

import pytest

from .conftest import skip_no_pg, space_exists

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "wordnet_frames"


async def test_the_frame_entity_sync_does_not_degrade_after_five_calls(perf_conn):
    from vitalgraph.db.sparql_sql.sync_frame_entity_table import (
        sync_frame_entity_after_edge_insert)

    if not await space_exists(perf_conn, SPACE):
        pytest.skip(f"space {SPACE} not loaded")

    frames = [r["frame_uuid"] for r in await perf_conn.fetch(
        f"SELECT frame_uuid FROM {SPACE}_frame_entity LIMIT 5")]
    assert frames, "fixture has no frames to sync"

    times = []
    for _ in range(10):                    # must cross the five-execution line
        tr = perf_conn.transaction()
        await tr.start()
        try:
            t = time.perf_counter()
            await sync_frame_entity_after_edge_insert(perf_conn, SPACE, frames)
            times.append((time.perf_counter() - t) * 1000)
        finally:
            await tr.rollback()            # leave the space exactly as found

    early = statistics.median(times[:5])
    late = statistics.median(times[5:])

    # The regression was ~5,000x and eight seconds, so these thresholds catch it
    # by a wide margin while leaving room for ordinary variance.
    assert max(times) < 1000, (
        f"a single sync took {max(times):.0f} ms — the statement has reverted "
        f"to a generic plan. Timings: {[round(x) for x in times]}")
    assert late < max(early * 20, 100), (
        f"the sync got slower after the fifth call: {early:.1f} ms -> "
        f"{late:.1f} ms. That is the plan-cache switch, not the query. "
        f"Timings: {[round(x) for x in times]}")
