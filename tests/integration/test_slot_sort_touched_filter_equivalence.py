"""Integration tests: the `entity_slot_sort` touched-filter rewrite — issue 238.

`_TOUCHED_FILTER` used to carry two `IN (SELECT dest_node_uuid FROM edge ...)`
arms. A BitmapOr can only combine INDEXABLE conditions and a subquery arm
compiles to a hashed SubPlan, so one such arm forced the whole five-armed
disjunction to a SEQUENTIAL SCAN — 647,255 calls and 59.6 hours on production,
with the per-call cost tracking TABLE SIZE while deleting eleven rows. The two
arms are now resolved into a `$2` array first.

WHY EQUIVALENCE, NOT SPOT CHECKS
--------------------------------
The comment above the filter records what a missing arm costs: "repointing a
slot's value touches only the slot, so a delete keyed on the entity would match
nothing, the re-derive would hit ON CONFLICT DO NOTHING, and the row would keep
the OLD value forever. The row COUNT never changes in that failure, so no drift
check can see it." A rewrite that drops an arm therefore produces WRONG SORT
RESULTS (`issues/096`) and no count, no drift probe and no smoke test can see
it.

So the pre-rewrite SQL is kept here verbatim as an ORACLE and the two forms are
compared on the same data — once per arm so a failure names which arm broke,
and once over randomised data so the comparison is not limited to the cases
someone thought to enumerate.
"""

from __future__ import annotations

import random
import uuid

import pytest

from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
    _TOUCHED_FILTER,
    sync_entity_slot_sort_before_delete,
)

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


#: The filter EXACTLY as it stood before `issues/238`. This is the oracle; it
#: must not be "kept in sync" with the implementation — the whole point is that
#: it is an independent statement of the same intent.
_SUBQUERY_FILTER_ORACLE = """
    (slot_uuid = ANY($1)
     OR entity_uuid = ANY($1)
     OR frame_uuid = ANY($1)
     OR slot_uuid IN (SELECT dest_node_uuid FROM {t_edge}
                      WHERE edge_uuid = ANY($1))
     OR frame_uuid IN (SELECT dest_node_uuid FROM {t_edge}
                       WHERE edge_uuid = ANY($1)))
"""


async def _oracle_matches(conn, space_id, touched, context_uuid=None):
    """The slot_uuids the PRE-REWRITE filter would have deleted."""
    where = _SUBQUERY_FILTER_ORACLE.format(t_edge=f"{space_id}_edge")
    sql = f"SELECT slot_uuid FROM {space_id}_entity_slot_sort WHERE {where}"
    args = [touched]
    if context_uuid is not None:
        sql += " AND context_uuid = $2"
        args.append(context_uuid)
    return {r["slot_uuid"] for r in await conn.fetch(sql, *args)}


async def _remaining(conn, space_id):
    return {r["slot_uuid"] for r in
            await conn.fetch(f"SELECT slot_uuid FROM {space_id}_entity_slot_sort")}


async def _add_row(conn, space_id, ctx, *, slot=None, entity=None, frame=None):
    """Insert one row. `ON CONFLICT DO NOTHING` because the randomised case
    draws slot uuids from a small pool and (slot_uuid, context_uuid) is the
    primary key — a collision there is the test repeating itself, not a case
    worth failing on. Every assertion reads the table back rather than trusting
    what was inserted, so a skipped insert cannot hide a wrong answer."""
    slot = slot or uuid.uuid4()
    await conn.execute(
        f"INSERT INTO {space_id}_entity_slot_sort "
        f"(slot_uuid, context_uuid, entity_uuid, frame_uuid, value_text) "
        f"VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
        slot, ctx, entity or uuid.uuid4(), frame or uuid.uuid4(), "v")
    return slot


async def _add_edge(conn, space_id, ctx, edge_uuid, dest):
    await conn.execute(
        f"INSERT INTO {space_id}_edge "
        f"(edge_uuid, source_node_uuid, dest_node_uuid, context_uuid) "
        f"VALUES ($1, $2, $3, $4)",
        edge_uuid, uuid.uuid4(), dest, ctx)


@pytest.fixture
def ctx():
    return uuid.uuid4()


class TestEveryReachabilityArmStillDeletes:
    """One row reachable by exactly one arm, so a failure names the arm."""

    async def test_touched_slot_uuid(self, pg_conn, make_space, ctx):
        sp = await make_space()
        t = uuid.uuid4()
        slot = await _add_row(pg_conn, sp, ctx, slot=t)
        keep = await _add_row(pg_conn, sp, ctx)
        assert await sync_entity_slot_sort_before_delete(pg_conn, sp, [t]) == 1
        assert await _remaining(pg_conn, sp) == {keep}
        assert slot not in await _remaining(pg_conn, sp)

    async def test_touched_entity_uuid(self, pg_conn, make_space, ctx):
        sp = await make_space()
        t = uuid.uuid4()
        await _add_row(pg_conn, sp, ctx, entity=t)
        keep = await _add_row(pg_conn, sp, ctx)
        assert await sync_entity_slot_sort_before_delete(pg_conn, sp, [t]) == 1
        assert await _remaining(pg_conn, sp) == {keep}

    async def test_touched_frame_uuid(self, pg_conn, make_space, ctx):
        sp = await make_space()
        t = uuid.uuid4()
        await _add_row(pg_conn, sp, ctx, frame=t)
        keep = await _add_row(pg_conn, sp, ctx)
        assert await sync_entity_slot_sort_before_delete(pg_conn, sp, [t]) == 1
        assert await _remaining(pg_conn, sp) == {keep}

    async def test_touched_edge_reaching_a_slot(self, pg_conn, make_space, ctx):
        """The arm that only an edge indirection reaches — arm 4.

        This is the one the rewrite could most easily have lost: the touched
        uuid is an EDGE, and nothing in the row matches it directly.
        """
        sp = await make_space()
        edge, dest_slot = uuid.uuid4(), uuid.uuid4()
        await _add_edge(pg_conn, sp, ctx, edge, dest_slot)
        await _add_row(pg_conn, sp, ctx, slot=dest_slot)
        keep = await _add_row(pg_conn, sp, ctx)
        assert await sync_entity_slot_sort_before_delete(pg_conn, sp, [edge]) == 1
        assert await _remaining(pg_conn, sp) == {keep}

    async def test_touched_edge_reaching_a_frame(self, pg_conn, make_space, ctx):
        """Arm 5 — same indirection, resolved against `frame_uuid`."""
        sp = await make_space()
        edge, dest_frame = uuid.uuid4(), uuid.uuid4()
        await _add_edge(pg_conn, sp, ctx, edge, dest_frame)
        await _add_row(pg_conn, sp, ctx, frame=dest_frame)
        keep = await _add_row(pg_conn, sp, ctx)
        assert await sync_entity_slot_sort_before_delete(pg_conn, sp, [edge]) == 1
        assert await _remaining(pg_conn, sp) == {keep}

    async def test_an_unreachable_row_survives(self, pg_conn, make_space, ctx):
        sp = await make_space()
        keep = await _add_row(pg_conn, sp, ctx)
        assert await sync_entity_slot_sort_before_delete(
            pg_conn, sp, [uuid.uuid4()]) == 0
        assert await _remaining(pg_conn, sp) == {keep}


class TestItMatchesTheSubqueryFormExactly:

    async def test_all_five_arms_at_once(self, pg_conn, make_space, ctx):
        sp = await make_space()
        t_slot, t_entity, t_frame = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        e_slot, e_frame = uuid.uuid4(), uuid.uuid4()
        d_slot, d_frame = uuid.uuid4(), uuid.uuid4()
        await _add_edge(pg_conn, sp, ctx, e_slot, d_slot)
        await _add_edge(pg_conn, sp, ctx, e_frame, d_frame)

        await _add_row(pg_conn, sp, ctx, slot=t_slot)
        await _add_row(pg_conn, sp, ctx, entity=t_entity)
        await _add_row(pg_conn, sp, ctx, frame=t_frame)
        await _add_row(pg_conn, sp, ctx, slot=d_slot)
        await _add_row(pg_conn, sp, ctx, frame=d_frame)
        keep = await _add_row(pg_conn, sp, ctx)

        touched = [t_slot, t_entity, t_frame, e_slot, e_frame]
        expected = await _oracle_matches(pg_conn, sp, touched)
        before = await _remaining(pg_conn, sp)

        deleted_n = await sync_entity_slot_sort_before_delete(pg_conn, sp, touched)

        actually_deleted = before - await _remaining(pg_conn, sp)
        assert actually_deleted == expected
        assert deleted_n == len(expected) == 5
        assert keep not in actually_deleted

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
    async def test_randomised_graphs_agree(self, pg_conn, make_space, ctx, seed):
        """Random rows, random edges, a random touched set — same answer.

        Enumerated cases only cover what someone imagined. This covers overlap
        between arms, rows reachable by two arms at once, touched uuids that
        reach nothing, and edges whose destination is in no row.
        """
        rng = random.Random(seed)
        sp = await make_space()

        pool = [uuid.uuid4() for _ in range(12)]
        edges = [uuid.uuid4() for _ in range(5)]
        for e in edges:
            await _add_edge(pg_conn, sp, ctx, e, rng.choice(pool))

        for _ in range(40):
            await _add_row(
                pg_conn, sp, ctx,
                slot=rng.choice(pool) if rng.random() < 0.4 else None,
                entity=rng.choice(pool) if rng.random() < 0.4 else None,
                frame=rng.choice(pool) if rng.random() < 0.4 else None)

        touched = rng.sample(pool, 4) + rng.sample(edges, 2)
        expected = await _oracle_matches(pg_conn, sp, touched)
        before = await _remaining(pg_conn, sp)

        await sync_entity_slot_sort_before_delete(pg_conn, sp, touched)

        assert before - await _remaining(pg_conn, sp) == expected

    async def test_the_context_scoped_form_agrees_too(self, pg_conn, make_space):
        """The `context_uuid` argument moved from `$2` to `$3` in the rewrite.

        An off-by-one in parameter numbering does not raise — it compares the
        context against the wrong array — so it needs its own case.
        """
        sp = await make_space()
        ctx_a, ctx_b = uuid.uuid4(), uuid.uuid4()
        t = uuid.uuid4()
        in_a = await _add_row(pg_conn, sp, ctx_a, entity=t)
        in_b = await _add_row(pg_conn, sp, ctx_b, entity=t)

        expected = await _oracle_matches(pg_conn, sp, [t], context_uuid=ctx_a)
        assert expected == {in_a}

        n = await sync_entity_slot_sort_before_delete(
            pg_conn, sp, [t], context_uuid=ctx_a)

        assert n == 1
        assert await _remaining(pg_conn, sp) == {in_b}


class TestThePlanNoLongerScansTheTable:

    async def test_no_sequential_scan_on_a_populated_table(
            self, pg_conn, make_space, ctx):
        """The performance claim, asserted rather than described.

        Seeded past the point where a seq scan is the cheap answer, then
        ANALYZEd so the planner is choosing on real statistics. Before the
        rewrite this plan was `Seq Scan` with an estimate of ~75% of the table;
        after it, a `BitmapOr` of index scans.
        """
        sp = await make_space()
        await pg_conn.execute(
            f"INSERT INTO {sp}_entity_slot_sort "
            f"(slot_uuid, context_uuid, entity_uuid, frame_uuid) "
            f"SELECT gen_random_uuid(), $1, gen_random_uuid(), gen_random_uuid() "
            f"FROM generate_series(1, 20000)", ctx)
        await pg_conn.execute(f"ANALYZE {sp}_entity_slot_sort")

        touched = [uuid.uuid4() for _ in range(20)]
        dests = [uuid.uuid4() for _ in range(5)]
        plan = "\n".join(r["QUERY PLAN"] for r in await pg_conn.fetch(
            f"EXPLAIN DELETE FROM {sp}_entity_slot_sort WHERE {_TOUCHED_FILTER}",
            touched, dests))

        assert "Seq Scan" not in plan, plan
        assert "BitmapOr" in plan, plan

    async def test_the_subquery_form_would_still_scan(self, pg_conn, make_space, ctx):
        """The guard above has teeth only if the old shape fails it.

        Same table, same statistics, the pre-rewrite SQL: a `Seq Scan`, because
        the two hashed SubPlans cannot join a BitmapOr. This is the defect
        `issues/238` records, pinned so the rewrite cannot be undone as a
        tidy-up — the two forms return identical rows, so nothing else would
        notice.
        """
        sp = await make_space()
        await pg_conn.execute(
            f"INSERT INTO {sp}_entity_slot_sort "
            f"(slot_uuid, context_uuid, entity_uuid, frame_uuid) "
            f"SELECT gen_random_uuid(), $1, gen_random_uuid(), gen_random_uuid() "
            f"FROM generate_series(1, 20000)", ctx)
        await pg_conn.execute(f"ANALYZE {sp}_entity_slot_sort")

        where = _SUBQUERY_FILTER_ORACLE.format(t_edge=f"{sp}_edge")
        plan = "\n".join(r["QUERY PLAN"] for r in await pg_conn.fetch(
            f"EXPLAIN DELETE FROM {sp}_entity_slot_sort WHERE {where}",
            [uuid.uuid4() for _ in range(20)]))

        assert "Seq Scan" in plan, plan
        assert "BitmapOr" not in plan, plan
