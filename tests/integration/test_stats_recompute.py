"""The recompute must cover every predicate and keep the large pairs.

`planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`.

Replaces an accumulator that could not validate itself and, under normal update
churn, ratcheted to zero: the write path decremented on delete and — for a
`pruned` predicate — refused to re-increment on insert, so every pruned pair
drained monotonically and was then deleted. A table of millions collapsed to
single digits. That is `issues/142`, and it is why `rdf_stats` kept
"mysteriously" emptying.

Two properties make the replacement correct, and both are measured here rather
than argued:

  1. FAIRNESS — every predicate is represented, however small the cap. A global
     `ORDER BY row_count ASC LIMIT n` fills the whole budget with the smallest
     pairs from a handful of predicates; measured on production, 10,000 rows
     drawn from 6 of 22 predicates, none above row_count 2.
  2. NO UPPER BOUND — the large pairs are kept. On production the 24 pairs above
     the old 200,000 cap cover 36% of all quads, and their absence sent the
     semi-join gate to a 10.4 s runtime probe that saturates and decides nothing.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql import sync_stats_tables as S

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def skewed_space(pg_conn, test_space):
    """Three predicates with deliberately unequal shapes.

        P0   one pair of 3,000        <- a "large" pair; dies under a global cap
        P1   one pair of 40
        P2   600 pairs of 2 each      <- would monopolise a global ASC LIMIT

    Chosen so that a fairness failure is unambiguous: under the old ordering the
    whole budget goes to P2 and P0/P1 vanish.
    """
    sp = test_space
    ctx = uuid.uuid4()
    P = [uuid.uuid4() for _ in range(3)]
    quads = []
    big, mid = uuid.uuid4(), uuid.uuid4()
    quads += [(uuid.uuid4(), P[0], big, ctx) for _ in range(3000)]
    quads += [(uuid.uuid4(), P[1], mid, ctx) for _ in range(40)]
    for _ in range(600):
        o = uuid.uuid4()
        quads += [(uuid.uuid4(), P[2], o, ctx) for _ in range(2)]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    await pg_conn.execute(f"ANALYZE {sp}_rdf_quad")
    yield sp, P


async def test_every_predicate_is_represented_even_under_a_tight_cap(
        pg_conn, skewed_space):
    """The property a global ASC LIMIT cannot provide."""
    sp, P = skewed_space
    result = await S.recompute_stats_tables(pg_conn, sp, keep_top_n=100)
    assert result["quad_stats"] == 100

    rows = await pg_conn.fetch(
        f"SELECT predicate_uuid, count(*) n, max(row_count) mx "
        f"FROM {sp}_rdf_stats GROUP BY 1")
    by_pred = {r["predicate_uuid"]: (r["n"], r["mx"]) for r in rows}
    assert set(by_pred) == set(P), (
        f"all three predicates must appear; got {len(by_pred)} — a global "
        f"ORDER BY row_count ASC LIMIT would have returned only P2")


async def test_large_pairs_survive_there_is_no_upper_bound(pg_conn, skewed_space):
    """The 200,000 cap is gone. Its absence is what removes the 10.4s probe."""
    sp, P = skewed_space
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=100)
    mx = await pg_conn.fetchval(
        f"SELECT max(row_count) FROM {sp}_rdf_stats WHERE predicate_uuid = $1",
        P[0])
    assert mx == 3000, (
        "the large pair must be recorded with its TRUE count; absent, the "
        "semi-join gate falls back to a saturating runtime probe")


async def test_it_is_idempotent(pg_conn, skewed_space):
    """A recompute has no state to corrupt — running it again is the recovery
    for any bad outcome, which is what makes a direct switch safe."""
    sp, _ = skewed_space
    first = await S.recompute_stats_tables(pg_conn, sp, keep_top_n=100)
    second = await S.recompute_stats_tables(pg_conn, sp, keep_top_n=100)
    assert first == second


async def test_it_replaces_rather_than_accumulates(pg_conn, skewed_space):
    """The whole point. Deliberately corrupt a row, recompute, and it is gone —
    where the accumulator would have added a delta to the wrong value and kept
    it forever."""
    sp, P = skewed_space
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=100)
    await pg_conn.execute(
        f"UPDATE {sp}_rdf_stats SET row_count = 999999 WHERE predicate_uuid = $1",
        P[0])
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=100)
    mx = await pg_conn.fetchval(
        f"SELECT max(row_count) FROM {sp}_rdf_stats WHERE predicate_uuid = $1",
        P[0])
    assert mx == 3000, "a recompute must not inherit the previous contents"


async def test_pred_stats_is_rebuilt_too(pg_conn, skewed_space):
    sp, P = skewed_space
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=100)
    n = await pg_conn.fetchval(
        f"SELECT row_count FROM {sp}_rdf_pred_stats WHERE predicate_uuid = $1",
        P[0])
    assert n == 3000


async def test_below_the_cap_it_matches_the_quads_exactly(pg_conn, skewed_space):
    """With room to spare, the table IS the truth — no drift, in either direction.

    This is the property the accumulator could not hold and could not check.
    Measured on the vg-test stack across five real spaces (193K-1.01M quads),
    the recompute reproduced `GROUP BY predicate, object HAVING count(*) >= 2`
    exactly; on the same data the accumulator was ~40% short. Nothing detected
    that, because a wrong count and a right count look identical in isolation.

    Asserting set equality rather than a row total matters: an off-by-a-few
    total can be two errors cancelling. Compare the pairs AND their counts.
    """
    sp, P = skewed_space
    # 602 distinct pairs qualify; 10,000 leaves the cap far out of reach, so any
    # difference here is the recompute being wrong rather than the cap biting.
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=10_000)

    truth = {(r["predicate_uuid"], r["object_uuid"]): r["rc"] for r in
             await pg_conn.fetch(
                 f"SELECT predicate_uuid, object_uuid, count(*) AS rc "
                 f"FROM {sp}_rdf_quad GROUP BY 1, 2 HAVING count(*) >= 2")}
    got = {(r["predicate_uuid"], r["object_uuid"]): r["row_count"] for r in
           await pg_conn.fetch(
               f"SELECT predicate_uuid, object_uuid, row_count FROM {sp}_rdf_stats")}

    assert got == truth, (
        f"missing={len(set(truth) - set(got))} extra={len(set(got) - set(truth))} "
        f"wrong_count={sum(1 for k in set(truth) & set(got) if truth[k] != got[k])}")


async def test_singletons_are_excluded_and_that_is_the_only_exclusion(
        pg_conn, skewed_space):
    """`row_count = 1` is out by STATS_MIN_ROW_COUNT; nothing else is.

    Absence has to mean exactly one thing. Under the accumulator it meant
    "zero, or pruned, or drifted" — which is why a collapse could not be told
    from a correct empty table. Pinning both directions keeps that.
    """
    sp, P = skewed_space
    ctx = uuid.uuid4()
    lone = uuid.uuid4()
    await pg_conn.execute(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
        uuid.uuid4(), P[0], lone, ctx)
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=10_000)

    assert not await pg_conn.fetchval(
        f"SELECT EXISTS(SELECT 1 FROM {sp}_rdf_stats WHERE object_uuid = $1)", lone), \
        "a row_count=1 pair must not be stored"
    assert 0 == await pg_conn.fetchval(
        f"SELECT count(*) FROM {sp}_rdf_stats WHERE row_count < $1",
        S.STATS_MIN_ROW_COUNT), "nothing below the floor may survive"


@pytest_asyncio.fixture(loop_scope="session")
async def anchor_space(pg_conn, test_space):
    """A HIGH-CARDINALITY predicate that also holds one enormous pair.

        P   one pair of 5,000     <- the anchor
        P   3,000 pairs of 2      <- the long tail, on the SAME predicate

    This shape is what separates "keep each predicate's biggest" from "keep each
    predicate's smallest". The `skewed_space` fixture cannot: its big pair is the
    only pair its predicate has, so it is rank 1 in either direction and survives
    both. That is precisely why the direction defect went unnoticed.

    It is also the production shape. `(rdf:type, Edge_hasKGSlot)` held 304,859
    rows on a predicate with many distinct objects.
    """
    sp = test_space
    ctx, P, anchor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    quads = [(uuid.uuid4(), P, anchor, ctx) for _ in range(5000)]
    for _ in range(3000):
        o = uuid.uuid4()
        quads += [(uuid.uuid4(), P, o, ctx) for _ in range(2)]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    await pg_conn.execute(f"ANALYZE {sp}_rdf_quad")
    yield sp, P, anchor


async def test_the_anchor_survives_a_cap_far_below_its_predicates_pair_count(
        pg_conn, anchor_space):
    """The biggest pair is kept, not the smallest. This is the point of the table.

    The planner reads rdf_stats to RECOGNISE a huge end so it does not drive
    from it, so the two directions of error are not symmetric: a missing small
    pair costs a missed optimisation, a missing anchor leaves the semi-join gate
    unable to price it at all and falling back to a 10.4 s runtime probe that
    saturates and decides nothing.

    Ranking `count(*) ASC` kept this predicate's 3,000 pairs of 2 and dropped
    its 5,000-row anchor. Removing the `<= STATS_MAX_ROW_COUNT` bound does NOT
    cover this: that bound only decides what is eligible, and the ordering then
    discarded the anchor anyway.
    """
    sp, P, anchor = anchor_space
    # 1,000 is far below the predicate's 3,001 qualifying pairs, so the cut
    # certainly bites and the only question is which side of it the anchor is on.
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=1000)

    stored = await pg_conn.fetchval(
        f"SELECT row_count FROM {sp}_rdf_stats "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2", P, anchor)
    assert stored == 5000, (
        f"the anchor is {stored!r}, not 5000. The cap is keeping this "
        f"predicate's SMALLEST pairs; an anchor the planner cannot see is an "
        f"anchor it cannot avoid driving from")

    # And what it kept is the top of the distribution, not the bottom.
    assert 2 != await pg_conn.fetchval(
        f"SELECT max(row_count) FROM {sp}_rdf_stats WHERE predicate_uuid = $1", P)


async def test_every_predicate_gets_its_biggest_before_any_gets_its_second(
        pg_conn, anchor_space):
    """Fairness still applies, and DESC is what it orders.

    Descending alone is not enough: a global `ORDER BY row_count DESC LIMIT n`
    would spend the whole budget on whichever predicate holds the largest pairs.
    `ORDER BY rn ASC` takes rank 1 of EVERY predicate first.

    Sized to the space rather than to a constant, because `test_space` is shared
    and carries predicates from other tests — which is exactly the condition the
    first version of this test got wrong.
    """
    sp, P, anchor = anchor_space

    truth = {r["predicate_uuid"]: r["mx"] for r in await pg_conn.fetch(
        f"SELECT predicate_uuid, max(rc) AS mx FROM ("
        f"  SELECT predicate_uuid, object_uuid, count(*) AS rc "
        f"  FROM {sp}_rdf_quad GROUP BY 1, 2 HAVING count(*) >= 2) x "
        f"GROUP BY 1")}
    assert len(truth) >= 2, "need at least two predicates to show fairness"

    # Exactly one slot per predicate: every rank-1 fits and nothing else does.
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=len(truth))

    kept = await pg_conn.fetch(
        f"SELECT predicate_uuid, row_count FROM {sp}_rdf_stats")
    assert {r["predicate_uuid"] for r in kept} == set(truth), (
        f"{len(truth) - len({r['predicate_uuid'] for r in kept})} predicate(s) "
        f"got nothing while another took a second slot")

    wrong = [(r["predicate_uuid"], r["row_count"], truth[r["predicate_uuid"]])
             for r in kept if r["row_count"] != truth[r["predicate_uuid"]]]
    assert not wrong, (
        f"a predicate's stored row is not its LARGEST pair: {wrong[:3]}. "
        f"rank 1 must be the biggest — that is the pair the planner needs to "
        f"see in order to avoid driving from it")


async def test_recompute_streams_the_aggregate_and_restores_the_setting(
        pg_conn, skewed_space):
    """The pair aggregate must not hash, and must not leak the fence.

    Grouping by (predicate, object) makes one group per distinct pair — 16.6M on
    a 50M-quad space — so the hash cannot fit in work_mem and spills. Measured
    on `sp_lead_synth_100k`: 3.5 GB through temp files, 48.2 s, against 13.7 s
    for a streaming GroupAggregate over `idx_{space}_quad_po`. Raising work_mem
    to 1 GB changed nothing, because the groups do not fit at any sane setting.

    The setting is saved and restored rather than `SET LOCAL`, because a caller
    can already hold a transaction — the import endpoint and the migration
    scripts call this directly — and inside one
    asyncpg opens a SAVEPOINT, so `SET LOCAL` would outlive this call and
    silently disable hashing for the caller's remaining work. That is the part
    worth pinning: a leaked planner setting is invisible until something else
    plans badly.
    """
    sp, _P = skewed_space
    before = await pg_conn.fetchval("SHOW enable_hashagg")
    await S.recompute_stats_tables(pg_conn, sp, keep_top_n=1000)
    assert await pg_conn.fetchval("SHOW enable_hashagg") == before, (
        "recompute leaked enable_hashagg to the caller's session")


async def test_the_index_the_streaming_aggregate_needs_is_still_created(pg_conn):
    """`idx_{space}_quad_po` is the precondition, not an optimisation.

    Without it, disabling the hash forces a SORT of the whole quad table, which
    is worse than the spill it replaces. The index is emitted for every space by
    `create_space_indexes_sql`; if that ever stops, the fence above turns from a
    3.5x win into a large regression, and nothing else would say so.
    """
    import inspect
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    src = inspect.getsource(SparqlSQLSchema.create_space_indexes_sql)
    assert "(predicate_uuid, object_uuid)" in src, (
        "the (predicate_uuid, object_uuid) index is no longer created; the "
        "recompute's streaming aggregate has nothing to stream from")
