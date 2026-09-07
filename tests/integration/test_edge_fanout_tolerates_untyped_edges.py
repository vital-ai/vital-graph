"""One untyped edge must not destroy a space's fan-out statistics.

`issues/170`. `compute_edge_fanout` checked that `edge_type_uuid` EXISTS as a
column and not that it is POPULATED. An edge carrying `hasEdgeSource` and
`hasEdgeDestination` but no `vitaltype` derives a NULL type; the aggregate
propagated it and the insert violated the fan-out table's NOT NULL, so a single
such row threw away the whole space's statistics.

It failed on every `bulk_export` round trip, because that fixture builds edges
from exactly those two predicates and no type — and it went unnoticed for a
while because it was the first line of a four-warning cascade that read like one
failure (`issues/168` fixed the cascade, which is what made this legible).

Real data carries a vitaltype, which is why no populated space showed it: three
checked at 5,277,000 / 570,696 / 4,977,000 edges, zero NULLs. So this is a shape
that is rare, legal, and was fatal.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.sync_edge_fanout import compute_edge_fanout

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _edge(conn, sp, ctx, typed=True):
    await conn.execute(
        f"INSERT INTO {sp}_edge (edge_uuid, source_node_uuid, dest_node_uuid,"
        f" context_uuid, edge_type_uuid) VALUES ($1,$2,$3,$4,$5)"
        f" ON CONFLICT DO NOTHING",
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), ctx,
        uuid.uuid4() if typed else None)


async def test_an_untyped_edge_does_not_fail_the_derivation(pg_conn, test_space):
    sp = test_space
    ctx = uuid.uuid4()
    for _ in range(3):
        await _edge(pg_conn, sp, ctx, typed=True)
    await _edge(pg_conn, sp, ctx, typed=False)

    # Must not raise. Before the fix this was a NotNullViolationError.
    written = await compute_edge_fanout(pg_conn, sp)
    assert written >= 0


async def test_the_typed_edges_are_still_counted(pg_conn, test_space):
    """Excluding the untyped row must not discard its neighbours.

    The failure mode this guards against is over-correcting: a WHERE that
    accidentally filtered typed rows too would also "not fail", and would
    silently produce an empty statistic.
    """
    sp = test_space
    ctx = uuid.uuid4()
    for _ in range(4):
        await _edge(pg_conn, sp, ctx, typed=True)
    await compute_edge_fanout(pg_conn, sp)
    n = await pg_conn.fetchval(f"SELECT count(*) FROM {sp}_edge_fanout")
    assert n > 0, "typed edges produced no fan-out rows at all"

    await _edge(pg_conn, sp, ctx, typed=False)
    await compute_edge_fanout(pg_conn, sp)
    n_after = await pg_conn.fetchval(f"SELECT count(*) FROM {sp}_edge_fanout")
    assert n_after > 0, (
        "adding one untyped edge emptied the fan-out table — the exclusion is "
        "filtering more than it should")


async def test_no_row_is_written_for_the_untyped_bucket(pg_conn, test_space):
    """Excluded, not given a sentinel.

    `relation_type_uuid` uses an all-zero sentinel meaning "not a relation",
    which is a real category. "No type at all" is not one this statistic answers
    questions about — pooling untyped edges under a zero uuid would invent a
    type and report a fan-out for it.
    """
    sp = test_space
    ctx = uuid.uuid4()
    await _edge(pg_conn, sp, ctx, typed=True)
    await _edge(pg_conn, sp, ctx, typed=False)
    await compute_edge_fanout(pg_conn, sp)
    zero = await pg_conn.fetchval(
        f"SELECT count(*) FROM {sp}_edge_fanout "
        f" WHERE edge_type_uuid = '00000000-0000-0000-0000-000000000000'::uuid")
    assert zero == 0, "untyped edges were pooled under a sentinel type"
