"""`entity_prop_sort` coverage must be measured in PAIRS, and repaired.

`issues/194`. Both halves of the self-healing loop were keyed per SUBJECT, and
the table is keyed (entity, context, property):

  * the PROBE tested `EXISTS (... WHERE f.entity_uuid = o.entity_uuid)`, so any
    single row made an entity covered. Run against a prod space missing three of
    five properties for every one of its 109,745 entities -- 329,235 absent rows
    -- it reported 0 gaps and all four types COMPLETE. Because
    `record_prop_sort_coverage` takes or releases the block from the number it is
    handed, that reading would have RELEASED the block over a 60%-empty table.
  * and there was no repair on the maintenance loop at all: the task measured and
    gated and never added a row, while every sibling table had a backfill.

The test that matters here is `test_a_missing_PROPERTY_is_reported_short`. It is
the one the old probe failed, and it fails again the moment presence stops being
keyed on the pair -- which is exactly how this regressed into shipping.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

_HALEY = "http://vital.ai/ontology/haley-ai-kg#"
_CORE = "http://vital.ai/ontology/vital-core#"
_AIMP = "http://vital.ai/ontology/vital-aimp#"
_G = "urn:eps:graph"
_NAME = _CORE + "hasName"
_STATUS = _AIMP + "hasObjectStatusType"


def _u(text):
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import _u as _uu
    return _uu(text)


async def _load(pg_conn, sp, n=4):
    """`n` entities, each with hasKGEntityType, hasName AND hasObjectStatusType.

    Three sortable pairs per entity, so a probe that counts entities and one that
    counts pairs give different answers the moment one property is removed.
    """
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import (
        _ENTITY_TYPE, _VITALTYPE, _KGENTITY_TYPES)
    ctx = _u(_G)
    ent_cls = _KGENTITY_TYPES[0]
    terms, quads = [], []

    def term(uu, text, tt="U"):
        terms.append((uu, text, tt))

    term(ctx, _G)
    term(_VITALTYPE, "http://vital.ai/ontology/vital-core#vitaltype")
    term(_ENTITY_TYPE, _HALEY + "hasKGEntityType")
    term(ent_cls, _HALEY + "KGEntity")
    term(_u(_NAME), _NAME)
    term(_u(_STATUS), _STATUS)
    ty = _u("urn:eps:type:T")
    term(ty, "urn:eps:type:T")
    active = _u(_AIMP + "ObjectStatusType_ACTIVE")
    term(active, _AIMP + "ObjectStatusType_ACTIVE")

    for i in range(n):
        e_uri = f"urn:eps:e:{i}"
        e = _u(e_uri)
        term(e, e_uri)
        nm = uuid.uuid4()
        term(nm, f"name {i:03d}", "L")
        quads += [
            (e, _VITALTYPE, ent_cls, ctx),      # population membership
            (e, _ENTITY_TYPE, ty, ctx),         # the type, itself a sortable prop
            (e, _u(_NAME), nm, ctx),
            (e, _u(_STATUS), active, ctx),
        ]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,$3) ON CONFLICT (term_uuid) DO NOTHING", terms)
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    return n


async def _cov(pg_conn, sp):
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import (
        entity_prop_sort_coverage)
    covs = await entity_prop_sort_coverage(pg_conn, sp, limit=50,
                                           only_gaps=False)
    return (sum(c["in_table"] for c in covs), sum(c["of_type"] for c in covs))


async def _fill(pg_conn, sp):
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import (
        backfill_entity_prop_sort_batch)
    return await backfill_entity_prop_sort_batch(pg_conn, sp)


# --- the frame twin --------------------------------------------------------
#
# Same defect, same shape, and its population rule is simply "it is a frame":
# `_select_rows`'s `form` CTE resolves form type to a COLUMN rather than using it
# for membership. (`scripts/migrate_frame_prop_sort.py` still describes the table
# as Assertion-scoped; that docstring predates the change.)


async def _load_frames(pg_conn, sp, n=4):
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
        _VITALTYPE as FV, _KGFRAME, _FRAME_TYPE)
    ctx = _u(_G)
    terms, quads = [], []

    def term(uu, text, tt="U"):
        terms.append((uu, text, tt))

    term(ctx, _G)
    term(FV, "http://vital.ai/ontology/vital-core#vitaltype")
    term(_KGFRAME, _HALEY + "KGFrame")
    term(_FRAME_TYPE, _HALEY + "hasKGFrameType")
    term(_u(_NAME), _NAME)
    term(_u(_STATUS), _STATUS)
    fty = _u("urn:fps:type:F")
    term(fty, "urn:fps:type:F")
    active = _u(_AIMP + "ObjectStatusType_ACTIVE")
    term(active, _AIMP + "ObjectStatusType_ACTIVE")

    for i in range(n):
        f_uri = f"urn:fps:f:{i}"
        f = _u(f_uri)
        term(f, f_uri)
        nm = uuid.uuid4()
        term(nm, f"frame {i:03d}", "L")
        quads += [
            (f, FV, _KGFRAME, ctx),          # membership: it is a frame
            (f, _FRAME_TYPE, fty, ctx),      # itself a sortable property
            (f, _u(_NAME), nm, ctx),
            (f, _u(_STATUS), active, ctx),
        ]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,$3) ON CONFLICT (term_uuid) DO NOTHING", terms)
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    return n


async def _fcov(pg_conn, sp):
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
        frame_prop_sort_coverage)
    covs = await frame_prop_sort_coverage(pg_conn, sp, limit=50, only_gaps=False)
    return (sum(c["in_table"] for c in covs), sum(c["of_type"] for c in covs))


async def _ffill(pg_conn, sp):
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
        backfill_frame_prop_sort_batch)
    return await backfill_frame_prop_sort_batch(pg_conn, sp)


async def test_the_frame_backfill_fills_an_empty_table(pg_conn, test_space):
    n = await _load_frames(pg_conn, test_space)
    selected, written = await _ffill(pg_conn, test_space)
    assert selected == n and written > 0
    in_table, of_type = await _fcov(pg_conn, test_space)
    assert of_type == n * 3 and in_table == of_type


async def test_a_missing_frame_PROPERTY_is_reported_short(pg_conn, test_space):
    """The frame half of the assertion the old probe failed."""
    n = await _load_frames(pg_conn, test_space)
    await _ffill(pg_conn, test_space)
    await pg_conn.execute(
        f"DELETE FROM {test_space}_frame_prop_sort WHERE property_uuid = $1",
        _u(_STATUS))
    still = await pg_conn.fetchval(
        f"SELECT count(DISTINCT frame_uuid) FROM {test_space}_frame_prop_sort")
    assert still == n, "the per-frame view must be indistinguishable from whole"
    in_table, of_type = await _fcov(pg_conn, test_space)
    assert of_type == n * 3
    assert in_table == n * 2, "the probe must count PAIRS"


async def test_the_frame_backfill_repairs_a_missing_PROPERTY(pg_conn, test_space):
    n = await _load_frames(pg_conn, test_space)
    await _ffill(pg_conn, test_space)
    await pg_conn.execute(
        f"DELETE FROM {test_space}_frame_prop_sort WHERE property_uuid = $1",
        _u(_STATUS))
    selected, written = await _ffill(pg_conn, test_space)
    assert selected == n and written > 0
    in_table, of_type = await _fcov(pg_conn, test_space)
    assert in_table == of_type == n * 3


async def test_a_complete_frame_table_selects_nothing(pg_conn, test_space):
    await _load_frames(pg_conn, test_space)
    await _ffill(pg_conn, test_space)
    assert await _ffill(pg_conn, test_space) == (0, 0)


async def test_the_backfill_fills_an_empty_table(pg_conn, test_space):
    n = await _load(pg_conn, test_space)
    selected, written = await _fill(pg_conn, test_space)
    assert selected == n and written > 0
    in_table, of_type = await _cov(pg_conn, test_space)
    assert of_type == n * 3, "three sortable pairs per entity"
    assert in_table == of_type, "and all of them present after the backfill"


async def test_a_missing_PROPERTY_is_reported_short(pg_conn, test_space):
    """THE ASSERTION THE OLD PROBE FAILED.

    Every entity keeps rows for two properties, so a per-entity probe sees each
    one as covered and reports complete. Only a pair-keyed probe can see that a
    third of the rows are gone.
    """
    n = await _load(pg_conn, test_space)
    await _fill(pg_conn, test_space)
    await pg_conn.execute(
        f"DELETE FROM {test_space}_entity_prop_sort WHERE property_uuid = $1",
        _u(_STATUS))

    # Precondition: every entity STILL has rows, so entity-presence is 100%.
    still = await pg_conn.fetchval(
        f"SELECT count(DISTINCT entity_uuid) FROM {test_space}_entity_prop_sort")
    assert still == n, "the per-entity view must be indistinguishable from whole"

    in_table, of_type = await _cov(pg_conn, test_space)
    assert of_type == n * 3
    assert in_table == n * 2, (
        "the probe must count PAIRS — a per-subject EXISTS reports this table "
        "complete, which is how a 60%-empty table was certified on prod")


async def test_the_backfill_repairs_a_missing_PROPERTY(pg_conn, test_space):
    """The other half: the seed must select entities that have SOME rows.

    Seeding on entities with NO rows — which is what the slot-sort batch does —
    selects nothing here and the table never heals.
    """
    n = await _load(pg_conn, test_space)
    await _fill(pg_conn, test_space)
    await pg_conn.execute(
        f"DELETE FROM {test_space}_entity_prop_sort WHERE property_uuid = $1",
        _u(_STATUS))
    selected, written = await _fill(pg_conn, test_space)
    assert selected == n, "entities with a missing PAIR must still be selected"
    assert written > 0
    in_table, of_type = await _cov(pg_conn, test_space)
    assert in_table == of_type == n * 3


async def test_a_complete_table_selects_nothing(pg_conn, test_space):
    """Termination. A backfill that keeps selecting a converged space spins."""
    await _load(pg_conn, test_space)
    await _fill(pg_conn, test_space)
    selected, written = await _fill(pg_conn, test_space)
    assert (selected, written) == (0, 0)


async def test_only_gaps_is_empty_when_complete(pg_conn, test_space):
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import (
        entity_prop_sort_coverage)
    await _load(pg_conn, test_space)
    await _fill(pg_conn, test_space)
    assert await entity_prop_sort_coverage(
        pg_conn, test_space, only_gaps=True) == []
