"""The batched, per-type backfill must derive exactly what the full walk does.

`issues/151` S3. The O(graph) backfill re-walks the whole graph to add whatever
is missing, measured at 216-303s on production and consuming 54% of wall-clock
(`issues/150`). It cannot be run often enough to converge without starving
reads, which is why the table sat at 40k rows against a ~2.83M target.

`backfill_entity_slot_sort_batch` seeds the SAME walk with a bounded set of
entity UUIDs of one type. These tests pin the two properties that make that
substitution safe:

  1. EQUIVALENCE — the seeded batch derives the same rows the full walk does
     for the entities it covered. Under-derivation here is a WRONG page later,
     not a slow one.
  2. TERMINATION — it reports both `selected` and `inserted`, because an entity
     that derives nothing stays absent and would be re-selected forever.

THE TRAP, recorded because this fixture has produced it twice: a comparison that
passes because both sides are empty. Every equivalence assertion below asserts
the full-walk side is NON-EMPTY first.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql import sync_entity_slot_sort as E

# `loop_scope="session"` on BOTH the fixture and the tests, or asyncpg raises
# "attached to a different loop" before any assertion runs — the pool is
# session-scoped. Recorded in the deploy runbook §14 as a trap this exact
# fixture family has produced before, and it produced it again here.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def typed_space(pg_conn, test_space):
    """Three entities of one type, each with a nested frame->slot->value chain.

    Nested to depth 2 so a walk that fails to recurse loses `slot2` — the
    under-derivation this exists to catch. Slot VALUES and their term rows are
    present because the outer SELECT joins both as INNER; without them every
    assertion here would be vacuously true.
    """
    sp = test_space
    ctx = uuid.uuid4()
    etype = uuid.uuid4()
    entities = []
    for _ in range(3):
        ids = {k: uuid.uuid4() for k in
               ("entity", "frame1", "frame2", "slot1", "slot2",
                "e_ef", "e_cf", "e_s1", "e_s2", "val1", "val2")}
        await pg_conn.executemany(
            f"INSERT INTO {sp}_edge (edge_uuid, source_node_uuid, dest_node_uuid,"
            f" context_uuid, edge_type_uuid) VALUES ($1,$2,$3,$4,$5)",
            [(ids["e_ef"], ids["entity"], ids["frame1"], ctx, E._ENTITY_FRAME_EDGE),
             (ids["e_cf"], ids["frame1"], ids["frame2"], ctx, E._CHILD_FRAME_EDGE),
             (ids["e_s1"], ids["frame1"], ids["slot1"], ctx, E._SLOT_EDGE),
             (ids["e_s2"], ids["frame2"], ids["slot2"], ctx, E._SLOT_EDGE)])
        await pg_conn.executemany(
            f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1,$2,'L') ON CONFLICT DO NOTHING",
            [(ids["val1"], "alpha"), (ids["val2"], "beta")])
        vp = E._SLOT_VALUE_PREDS[0]
        await pg_conn.executemany(
            f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid,"
            f" object_uuid, context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
            [(ids["frame1"], E._FRAME_TYPE, uuid.uuid4(), ctx),
             (ids["frame2"], E._FRAME_TYPE, uuid.uuid4(), ctx),
             (ids["slot1"], E._SLOT_TYPE, uuid.uuid4(), ctx),
             (ids["slot2"], E._SLOT_TYPE, uuid.uuid4(), ctx),
             (ids["entity"], E._ENTITY_TYPE, etype, ctx),
             (ids["slot1"], vp, ids["val1"], ctx),
             (ids["slot2"], vp, ids["val2"], ctx)])
        entities.append(ids["entity"])
    yield sp, etype, entities


async def _full_walk_rows(conn, sp):
    """What the unseeded backfill would derive — the reference."""
    args = await E._type_args(sp)
    rows = await conn.fetch(
        f"SELECT slot_uuid, entity_uuid FROM ({E._select_rows(sp, 'TRUE')}) s", *args)
    return {(r["slot_uuid"], r["entity_uuid"]) for r in rows}


async def test_p3_batched_equals_full_walk(pg_conn, typed_space):
    """P3. The property the whole substitution rests on."""
    sp, etype, entities = typed_space

    reference = await _full_walk_rows(pg_conn, sp)
    assert reference, "the fixture derived nothing — every assertion below would be vacuous"
    assert len(reference) == 6, f"3 entities x 2 slots expected, got {len(reference)}"

    selected, inserted = await E.backfill_entity_slot_sort_batch(
        pg_conn, sp, etype, batch_size=100)
    assert selected == 3
    assert inserted == 6

    got = {(r["slot_uuid"], r["entity_uuid"]) for r in await pg_conn.fetch(
        f"SELECT slot_uuid, entity_uuid FROM {sp}_entity_slot_sort")}
    assert got == reference, "the seeded batch must derive exactly the full walk"


async def test_a_nested_slot_survives_the_batch(pg_conn, typed_space):
    """Depth-2 slots are what a non-recursing walk loses."""
    sp, etype, _ = typed_space
    await E.backfill_entity_slot_sort_batch(pg_conn, sp, etype, batch_size=100)
    per_entity = await pg_conn.fetch(
        f"SELECT entity_uuid, count(*) n FROM {sp}_entity_slot_sort GROUP BY 1")
    assert per_entity, "nothing derived"
    assert all(r["n"] == 2 for r in per_entity), (
        f"each entity has a depth-1 and a depth-2 slot: {[r['n'] for r in per_entity]}")


async def test_batch_size_bounds_the_work(pg_conn, typed_space):
    """P2's mechanism: the batch is what makes this O(batch), not O(graph)."""
    sp, etype, _ = typed_space
    selected, inserted = await E.backfill_entity_slot_sort_batch(
        pg_conn, sp, etype, batch_size=1)
    assert selected == 1 and inserted == 2, (selected, inserted)


async def test_it_converges_and_then_reports_done(pg_conn, typed_space):
    """TERMINATION. Repeated batches finish, and `selected == 0` is the signal."""
    sp, etype, _ = typed_space
    total = 0
    for _ in range(10):
        selected, inserted = await E.backfill_entity_slot_sort_batch(
            pg_conn, sp, etype, batch_size=1)
        if selected == 0:
            break
        total += inserted
    else:
        pytest.fail("did not converge in 10 batches")
    assert total == 6
    assert await E.backfill_entity_slot_sort_batch(
        pg_conn, sp, etype, batch_size=100) == (0, 0), "done means (0, 0)"


async def test_an_entity_that_derives_nothing_is_reported_not_hidden(
        pg_conn, typed_space):
    """The termination hazard, made explicit.

    An entity with a type but no frames derives no rows. It therefore stays
    absent from the table and is re-selected on every subsequent batch. The
    caller must be able to see that — `selected > 0, inserted == 0` — or the
    maintenance job spins on the same batch forever.
    """
    sp, etype, _ = typed_space
    await E.backfill_entity_slot_sort_batch(pg_conn, sp, etype, batch_size=100)

    barren = uuid.uuid4()
    await pg_conn.execute(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
        barren, E._ENTITY_TYPE, etype, uuid.uuid4())

    selected, inserted = await E.backfill_entity_slot_sort_batch(
        pg_conn, sp, etype, batch_size=100)
    assert selected == 1, "the barren entity is still absent, so still selected"
    assert inserted == 0, "and it derives nothing"
