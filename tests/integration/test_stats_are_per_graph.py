"""`rdf_stats` counts per GRAPH, because every query is scoped to one.

`issues/163`. The table was keyed `(predicate, object)` and counted across the
whole space, so the planner read a number no query would ever see — inflated by
however many graphs share the pair. That is not a reporting error: these counts
are what `choose_direction` compares, and two ends inflated by DIFFERENT factors
can invert the comparison and send the walk down the larger one.

The change has to earn its keep on a single-graph space, which is what nearly
every deployment and every fixture here actually is. It does, exactly:
`test_a_single_graph_space_is_unchanged` pins that the context in the GROUP BY
adds no rows at all. That was measured across all seventeen fixtures in the test
database before the change landed — identical on the sixteen single-graph ones,
up to 1,086,774 pairs — and this keeps it true.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql import sync_stats_tables as S

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _insert(conn, sp, quads):
    await conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    await conn.execute(f"ANALYZE {sp}_rdf_quad")


@pytest_asyncio.fixture(loop_scope="session")
async def two_graph_space(pg_conn, test_space):
    """One pair split unevenly across two graphs, plus a per-graph-only pair.

        (P0, shared)  ->  G1: 30 rows,  G2: 5 rows      space-wide 35
        (P1, only1)   ->  G1: 10 rows                   space-wide 10
        (P1, only2)   ->            G2: 7 rows          space-wide  7

    The uneven split is the point. An equal one would let a space-wide count be
    rescaled by the graph count and still land in the right place, which is
    exactly the reasoning this replaces.
    """
    sp = test_space
    # Registered as terms, because a graph lock names its graph by URI and the
    # loader resolves it through the term table.
    g1_uri, g2_uri = f"urn:g1:{uuid.uuid4()}", f"urn:g2:{uuid.uuid4()}"
    g1, g2 = uuid.uuid4(), uuid.uuid4()
    for gid, uri in ((g1, g1_uri), (g2, g2_uri)):
        await pg_conn.execute(
            f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", gid, uri)
    P0, P1 = uuid.uuid4(), uuid.uuid4()
    shared, only1, only2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    quads = []
    quads += [(uuid.uuid4(), P0, shared, g1) for _ in range(30)]
    quads += [(uuid.uuid4(), P0, shared, g2) for _ in range(5)]
    quads += [(uuid.uuid4(), P1, only1, g1) for _ in range(10)]
    quads += [(uuid.uuid4(), P1, only2, g2) for _ in range(7)]
    await _insert(pg_conn, sp, quads)
    yield sp, (g1, g2), (g1_uri, g2_uri), (P0, P1), (shared, only1, only2)


async def test_a_single_graph_space_is_unchanged(pg_conn, test_space):
    """THE INVARIANT THE CHANGE RESTS ON.

    Adding `context_uuid` to the group key costs nothing where a space has one
    graph, because the context is then a constant and cannot split any group.
    If this ever fails, the per-graph key has started charging every deployment
    for a property only multi-graph ones use.
    """
    sp = test_space
    ctx = uuid.uuid4()
    P = [uuid.uuid4() for _ in range(3)]
    quads = []
    for p in P:
        for _ in range(40):
            o = uuid.uuid4()
            quads += [(uuid.uuid4(), p, o, ctx) for _ in range(3)]
    await _insert(pg_conn, sp, quads)

    await S.recompute_stats_tables(pg_conn, sp)

    stored = await pg_conn.fetchval(f"SELECT count(*) FROM {sp}_rdf_stats")
    # What the OLD, space-wide group key would have produced, computed the old
    # way rather than asserted as a literal.
    space_wide = await pg_conn.fetchval(f"""
        SELECT count(*) FROM (SELECT 1 FROM {sp}_rdf_quad
          GROUP BY predicate_uuid, object_uuid
          HAVING count(*) >= {S.STATS_MIN_ROW_COUNT}) x""")
    assert stored == space_wide, (
        f"per-graph key changed the row count of a SINGLE-graph space "
        f"({stored} vs {space_wide}); it must be free where there is only one "
        f"graph to split by")
    assert await pg_conn.fetchval(
        f"SELECT count(DISTINCT context_uuid) FROM {sp}_rdf_stats") == 1


async def test_counts_are_per_graph_and_sum_to_the_space(pg_conn, two_graph_space):
    """One row per (pair, graph), each holding that graph's own count."""
    sp, (g1, g2), (g1_uri, g2_uri), (P0, _), (shared, _, _) = two_graph_space
    await S.recompute_stats_tables(pg_conn, sp)

    rows = {r["context_uuid"]: r["row_count"] for r in await pg_conn.fetch(
        f"SELECT context_uuid, row_count FROM {sp}_rdf_stats "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2", P0, shared)}
    assert rows == {g1: 30, g2: 5}, (
        f"expected each graph's own count, got {rows} — a space-wide 35 would "
        f"over-price the G2 end sevenfold")
    assert sum(rows.values()) == 35, "the sum must still be the space-wide count"


async def test_a_pair_in_one_graph_is_not_credited_to_the_other(
        pg_conn, two_graph_space):
    """The failure that matters: pricing an end that is not there at all.

    `(P1, only1)` exists only in G1. Space-wide it reads as 10 rows for any
    query, including one scoped to G2 where it matches nothing.
    """
    sp, (g1, g2), _uris, (_, P1), (_, only1, _) = two_graph_space
    await S.recompute_stats_tables(pg_conn, sp)

    ctxs = [r["context_uuid"] for r in await pg_conn.fetch(
        f"SELECT context_uuid FROM {sp}_rdf_stats "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2", P1, only1)]
    assert ctxs == [g1], f"expected a G1 row only, got {ctxs}"


async def test_the_cap_is_fair_per_graph_not_just_per_predicate(pg_conn, test_space):
    """Why the window partitions by (predicate, context).

    `absence_bounds` reads a missing pair as "<= the smallest STORED pair of the
    same predicate", which says nothing unless that predicate HAS a stored pair
    to compare against. Now the counts are per graph the bound is per
    (predicate, graph), so the round-robin has to guarantee a floor per
    (predicate, graph) — partitioning by predicate alone lets one busy graph
    take every slot and leaves the others unpriced, which is `issues/147` one
    dimension over.

    G_BUSY holds far more pairs than the cap; G_QUIET holds a handful. Under a
    predicate-only partition the budget goes to G_BUSY and G_QUIET vanishes.
    """
    sp = test_space
    busy, quiet = uuid.uuid4(), uuid.uuid4()
    P = uuid.uuid4()
    quads = []
    for _ in range(400):
        o = uuid.uuid4()
        quads += [(uuid.uuid4(), P, o, busy) for _ in range(2)]
    for _ in range(3):
        o = uuid.uuid4()
        quads += [(uuid.uuid4(), P, o, quiet) for _ in range(2)]
    await _insert(pg_conn, sp, quads)

    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=50)

    ctxs = {r["context_uuid"]: r["n"] for r in await pg_conn.fetch(
        f"SELECT context_uuid, count(*) n FROM {sp}_rdf_stats GROUP BY 1")}
    assert quiet in ctxs, (
        f"the quiet graph got no stored pair at all, so every query scoped to "
        f"it prices this predicate as unknown; got {ctxs}")
    assert busy in ctxs


async def test_a_graph_locked_query_loads_that_graph_s_counts(pg_conn, two_graph_space):
    """The planner actually READS the per-graph number, not the space-wide sum.

    Storing the counts per graph buys nothing on its own — the value is in what
    `_load_quad_stats` puts on `aliases.quad_stats`, which is what
    `choose_direction` and the semi-join gate price from. `graph_lock_uri` is
    applied to every quad alias by `collect`, so under a lock no pattern can
    read outside that graph and the narrowed counts describe exactly the
    reachable rows.

    Asserted on the loaded values rather than on a log line or a timing: an
    optimisation that never fires reads identically to one that does.
    """
    from vitalgraph.db.sparql_sql.generator import (
        _load_quad_stats, invalidate_stats_cache)
    from vitalgraph.db.sparql_sql.ir import AliasGenerator

    sp, (g1, g2), (g1_uri, g2_uri), (P0, _), (shared, _, _) = two_graph_space
    await S.recompute_stats_tables(pg_conn, sp)

    async def counts_for(lock):
        invalidate_stats_cache(sp)
        a = AliasGenerator()
        a.graph_lock_uri = lock
        await _load_quad_stats(a, sp, conn=pg_conn)
        return a.quad_stats.get((str(P0), str(shared)))

    assert await counts_for(g1_uri) == 30, "locked to G1, must be G1's 30"
    assert await counts_for(g2_uri) == 5, (
        "locked to G2 the pair holds 5 rows; 35 would be the space-wide sum, "
        "seven times what the query can reach")
    assert await counts_for(None) == 35, (
        "unlocked, the space-wide sum is still the honest answer — a query with "
        "a GRAPH ?g block is not confined to any one graph")


async def test_the_stats_cache_does_not_serve_one_graph_s_counts_to_another(
        pg_conn, two_graph_space):
    """`_stats_cache` was keyed by space alone, which is now not enough.

    Two queries against the same space under different locks want different
    entries. Keyed by space, the first would serve its graph's counts to the
    second — silently, and in whichever direction the graphs happen to differ.
    """
    from vitalgraph.db.sparql_sql.generator import (
        _load_quad_stats, invalidate_stats_cache)
    from vitalgraph.db.sparql_sql.ir import AliasGenerator

    sp, (g1, g2), (g1_uri, g2_uri), (P0, _), (shared, _, _) = two_graph_space
    await S.recompute_stats_tables(pg_conn, sp)
    invalidate_stats_cache(sp)

    # NO invalidation between these two — the cache is what is under test.
    a1 = AliasGenerator(); a1.graph_lock_uri = g1_uri
    await _load_quad_stats(a1, sp, conn=pg_conn)
    a2 = AliasGenerator(); a2.graph_lock_uri = g2_uri
    await _load_quad_stats(a2, sp, conn=pg_conn)

    assert a1.quad_stats.get((str(P0), str(shared))) == 30
    assert a2.quad_stats.get((str(P0), str(shared))) == 5, (
        "the second load was served G1's cached counts")
