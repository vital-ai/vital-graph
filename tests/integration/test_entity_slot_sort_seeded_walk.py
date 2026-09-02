"""The seeded frame walk must derive exactly what the unseeded one derives.

`_select_rows` builds a `WITH RECURSIVE frame_walk`. Its base case used to
select EVERY entity->frame edge in the space, with the touched-set filter in
the outer SELECT — where PostgreSQL cannot push it into a recursive CTE. So an
incremental write materialised the whole frame graph and discarded nearly all
of it. Measured on production: 9,147 ms to derive 15 rows for 16 subjects, mean
9,575 ms and max 58,173 ms across 1,396 calls, 3.7 hours of database time
within hours of the deploy. Cost tracked the SPACE, not the change.

`sync_entity_slot_sort_after_edge_insert` now seeds the base case from
`_frame_roots`. The risk that buys is UNDER-derivation: the caller's WHERE has
six disjuncts (touched slot, touched entity, touched frame in the path, touched
slot edge, and two edge_uuid -> dest_node_uuid indirections), and a root set
that misses one silently drops rows — which `issues/096` records as wrong SORT
RESULTS, not a slow query.

`_frame_roots` is therefore a deliberate SUPERSET: it climbs up from every
touched node and from the destination of every touched edge, without trying to
mirror the disjuncts. Extra seeds only add candidate walks and the outer WHERE
is unchanged, so a superset cannot lose a row.

These tests pin that equivalence per touched-set SHAPE, because the shapes
reach different disjuncts and a fixture that only ever passes entity uuids
would never exercise 4, 5 or 6.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql import sync_entity_slot_sort as E

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]




@pytest_asyncio.fixture(loop_scope="session")
async def frame_space(pg_conn, test_space):
    """A space holding a small but genuinely NESTED frame graph.

    The ephemeral `test_space` is empty, and an empty space makes every
    equivalence assertion vacuous — it would skip, and skipping reads as
    "infrastructure absent" rather than "nothing was compared" (`issues/130`).

    Shape, chosen so the walk actually recurses rather than terminating at
    depth 1:

        entity ──entity_frame──▶ frame1 ──child_frame──▶ frame2
                                   │                       │
                              slot_edge                slot_edge
                                   ▼                       ▼
                                 slot1                   slot2

    `slot2` is only reachable at depth 2, so a walk that failed to recurse, or
    a root set that stopped climbing early, loses it — which is exactly the
    under-derivation this test exists to catch.
    """
    sp = test_space
    ctx = uuid.uuid4()
    ids = {k: uuid.uuid4() for k in
           ("entity", "frame1", "frame2", "slot1", "slot2",
            "e_ef", "e_cf", "e_s1", "e_s2")}

    await pg_conn.executemany(
        f"INSERT INTO {sp}_edge "
        f"(edge_uuid, source_node_uuid, dest_node_uuid, context_uuid, edge_type_uuid) "
        f"VALUES ($1,$2,$3,$4,$5)",
        [
            (ids["e_ef"], ids["entity"], ids["frame1"], ctx, E._ENTITY_FRAME_EDGE),
            (ids["e_cf"], ids["frame1"], ids["frame2"], ctx, E._CHILD_FRAME_EDGE),
            (ids["e_s1"], ids["frame1"], ids["slot1"],  ctx, E._SLOT_EDGE),
            (ids["e_s2"], ids["frame2"], ids["slot2"],  ctx, E._SLOT_EDGE),
        ])
    # Slot VALUES, and the term rows they point at. Both joins in the outer
    # SELECT are INNER (`val_q` on a slot-value predicate, `val_t` on the term),
    # so a slot with a type but no value derives NOTHING — which is how the
    # first version of this fixture produced an empty set and made every
    # equivalence assertion vacuously true.
    ids["val1"], ids["val2"] = uuid.uuid4(), uuid.uuid4()
    await pg_conn.executemany(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,'L') ON CONFLICT DO NOTHING",
        [(ids["val1"], "alpha"), (ids["val2"], "beta")])

    # Frame and slot TYPE quads, plus the slot values.
    value_pred = E._SLOT_VALUE_PREDS[0]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) VALUES ($1,$2,$3,$4) "
        f"ON CONFLICT DO NOTHING",
        [
            (ids["frame1"], E._FRAME_TYPE, uuid.uuid4(), ctx),
            (ids["frame2"], E._FRAME_TYPE, uuid.uuid4(), ctx),
            (ids["slot1"],  E._SLOT_TYPE,  uuid.uuid4(), ctx),
            (ids["slot2"],  E._SLOT_TYPE,  uuid.uuid4(), ctx),
            (ids["entity"], E._ENTITY_TYPE, uuid.uuid4(), ctx),
            (ids["slot1"],  value_pred,    ids["val1"], ctx),
            (ids["slot2"],  value_pred,    ids["val2"], ctx),
        ])
    yield sp, ids


def _where(space_id: str) -> str:
    """The filter `sync_entity_slot_sort_after_edge_insert` applies, verbatim."""
    return f"""
        (slot_e.dest_node_uuid = ANY($8)
         OR frame_w.entity_uuid = ANY($8)
         OR frame_w.frame_uuid_path && $8
         OR slot_e.edge_uuid = ANY($8)
         OR slot_e.dest_node_uuid IN (
              SELECT dest_node_uuid FROM {space_id}_edge WHERE edge_uuid = ANY($8))
         OR frame_w.frame_uuid_path && ARRAY(
              SELECT dest_node_uuid FROM {space_id}_edge WHERE edge_uuid = ANY($8)))
    """


async def _derive(conn, space_id, touched, *, seeded):
    args = await E._type_args(space_id)
    where = _where(space_id)
    if not seeded:
        sql = E._select_rows(space_id, where)
        rows = await conn.fetch(
            f"SELECT slot_uuid, context_uuid FROM ({sql}) x", *args, touched)
    else:
        roots = await E._frame_roots(conn, space_id, touched)
        if not roots:
            return set()
        sql = E._select_rows(space_id, where, seed_param="$9")
        rows = await conn.fetch(
            f"SELECT slot_uuid, context_uuid FROM ({sql}) x", *args, touched, roots)
    return {tuple(r) for r in rows}


async def _sample(conn, space_id, column, n=24):
    return [r["u"] for r in await conn.fetch(
        f"SELECT {column} AS u FROM {space_id}_edge LIMIT {n}")]


@pytest.mark.parametrize("column,reaches", [
    ("source_node_uuid", "entities — disjunct 2"),
    ("edge_uuid",        "edge uuids — disjuncts 4, 5 and 6"),
    ("dest_node_uuid",   "frames and slots — disjuncts 1 and 3"),
])
async def test_seeded_walk_matches_unseeded(pg_conn, frame_space, column, reaches):
    """Same rows, whichever disjunct the touched set reaches."""
    space_id, _ids = frame_space
    touched = await _sample(pg_conn, space_id, column)
    assert touched, "the fixture must have seeded edges"

    full = await _derive(pg_conn, space_id, touched, seeded=False)
    seeded = await _derive(pg_conn, space_id, touched, seeded=True)
    assert full, "nothing was derived — the comparison would be vacuous"

    assert seeded == full, (
        f"seeded walk disagrees for {reaches}: "
        f"{len(full - seeded)} missing, {len(seeded - full)} extra")


async def test_seeded_walk_matches_on_a_mixed_touched_set(pg_conn, frame_space):
    """A real write touches entities, frames and edges at once."""
    space_id, _ids = frame_space
    touched = (await _sample(pg_conn, space_id, "source_node_uuid", 8)
               + await _sample(pg_conn, space_id, "dest_node_uuid", 8)
               + await _sample(pg_conn, space_id, "edge_uuid", 8))
    full = await _derive(pg_conn, space_id, touched, seeded=False)
    assert full, "nothing was derived — the comparison would be vacuous"
    assert await _derive(pg_conn, space_id, touched, seeded=True) == full


async def test_roots_are_a_superset_not_a_guess(pg_conn, frame_space):
    """Every touched node must itself appear among the roots.

    The climb starts from the touched set, so this is the weakest possible
    statement of the superset property — but it is the one that fails loudly if
    someone later "optimises" `_frame_roots` into a targeted lookup that tries
    to mirror the disjuncts instead.
    """
    space_id, _ids = frame_space
    touched = await _sample(pg_conn, space_id, "dest_node_uuid", 12)
    roots = set(await E._frame_roots(pg_conn, space_id, touched))
    assert set(touched) <= roots, "the climb dropped one of its own seeds"


async def test_a_nested_slot_is_derived_at_all(pg_conn, frame_space):
    """The depth-2 slot must appear, seeded or not.

    Without this the suite could pass on a graph one hop deep, where seeding
    and not seeding are trivially the same and the recursion is never tested.
    """
    space_id, ids = frame_space
    derived = await _derive(pg_conn, space_id, [ids["entity"]], seeded=True)
    slots = {row[0] for row in derived}
    assert ids["slot1"] in slots, "depth-1 slot missing"
    assert ids["slot2"] in slots, "depth-2 slot missing — the walk did not recurse"
