"""A missing SLOT TYPE must be detectable, even when the entity has other rows.

`issues/194`. `entity_slot_sort_coverage` tests presence per ENTITY, so an
entity holding rows for slot type A while missing type B reads as fully covered
and a sort on B returns a short page with nothing reporting it. Its sibling
`entity_prop_sort_coverage` had the identical flaw and was measured certifying a
60%-empty table as complete.

WHY THIS IS AN ALARM AND NOT A GATE, unlike the prop-sort fix. The cheap count
cannot attribute a shortfall to an entity type -- a missing slot has no row, so
the table cannot say whose it was -- and blocks are per entity type. And the
number is an UPPER BOUND: a slot carrying a type but no value derives nothing
and is CORRECTLY absent, 10 of 304,933 on a real space. Blocking over that would
be a regression, and failing closed is only safe on an exact number. So the
expensive exact count runs only to explain a nonzero cheap one, which is what
`test_a_valueless_slot_is_not_reported_as_a_gap` pins.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

_HALEY = "http://vital.ai/ontology/haley-ai-kg#"
_G = "urn:sfs:graph"
_E = "urn:sfs:entity:E"
_F = "urn:sfs:frame:F"
_A, _B = "urn:sfs:slot:A", "urn:sfs:slot:B"


def _u(text):
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import _u as _uu
    return _uu(text)


async def _load(pg_conn, sp, tag, n=3, with_b=True, valueless=0):
    """`n` entities, each with a frame carrying slot A (and optionally B).

    Rows go straight into `entity_slot_sort` -- this test is about the PROBE, and
    driving the real derivation would need the whole edge/frame scaffolding.
    `valueless` adds slots that carry a TYPE in the quads and no value, which the
    derivation legitimately excludes.
    """
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        _SLOT_TYPE, _SLOT_VALUE_PREDS)
    ctx, ent_t = _u(_G), _u(_E)
    fpath = [_u(_F)]
    quads, rows, terms = [], [], [(ctx, _G, "U")]

    for i in range(n):
        e = _u(f"urn:sfs:{tag}:e:{i}")
        frame = _u(f"urn:sfs:{tag}:fr:{i}")
        for slot_uri, include in ((_A, True), (_B, with_b)):
            sl = _u(f"urn:sfs:{tag}:sl:{i}:{slot_uri}")
            val = uuid.uuid4()
            terms.append((val, f"v{i}", "L"))
            # The quad side always has the slot: a type AND a value.
            quads += [(sl, _SLOT_TYPE, _u(slot_uri), ctx),
                      (sl, _SLOT_VALUE_PREDS[0], val, ctx)]
            if include:
                rows.append((sl, ctx, e, frame, ent_t, fpath,
                             _u(slot_uri), f"v{i}"))
    for j in range(valueless):
        sl = _u(f"urn:sfs:{tag}:noval:{j}")
        quads.append((sl, _SLOT_TYPE, _u(_A), ctx))   # type, but NO value

    await pg_conn.executemany(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,$3) ON CONFLICT (term_uuid) DO NOTHING", terms)
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    await pg_conn.executemany(
        f"INSERT INTO {sp}_entity_slot_sort (slot_uuid, context_uuid,"
        f" entity_uuid, frame_uuid, entity_type_uuid, frame_type_path,"
        f" slot_type_uuid, value_text) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
        f"ON CONFLICT DO NOTHING", rows)
    return n


async def _sf(pg_conn, sp):
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        entity_slot_sort_row_shortfall)
    return await entity_slot_sort_row_shortfall(pg_conn, sp)


async def _valueless(pg_conn, sp):
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        entity_slot_sort_valueless_slots)
    return await entity_slot_sort_valueless_slots(pg_conn, sp)


# MEASURED AS DELTAS, because these two counts are SPACE-WIDE and `test_space` is
# shared across the session. Asserting absolutes made two of these tests depend
# on which others had already run; deleting rows to get exclusivity would break
# the tests that share the space. A delta is what each fixture actually claims.


async def test_a_complete_table_adds_no_shortfall(pg_conn, test_space):
    before = (await _sf(pg_conn, test_space))["shortfall"]
    await _load(pg_conn, test_space, "complete")
    after = (await _sf(pg_conn, test_space))["shortfall"]
    assert after - before == 0


async def test_a_missing_SLOT_TYPE_is_reported(pg_conn, test_space):
    """THE ASSERTION THE PER-ENTITY PROBE CANNOT MAKE.

    Every entity keeps its slot-A row, so entity-presence is 100% and
    `entity_slot_sort_coverage` reports the type complete. Only counting at the
    table's own key sees that every B row is gone.
    """
    before = (await _sf(pg_conn, test_space))["shortfall"]
    n = await _load(pg_conn, test_space, "missingb", with_b=False)
    after = (await _sf(pg_conn, test_space))["shortfall"]
    assert after - before == n, (
        "one missing row per entity — the slot-B rows")

    # NOT ASSERTED HERE: that `entity_slot_sort_coverage` stays silent on the
    # same fixture. It would pass, and vacuously — this fixture never writes the
    # `hasKGEntityType` / `vitaltype` quads, so these entities are not in that
    # probe's denominator at all and it would report nothing whatever the table
    # held. Building the full entity/frame/edge scaffolding to make the
    # comparison real belongs with a test of that probe, not this counter.
    #
    # The blindness itself is not in doubt: its presence test is
    # `EXISTS (... WHERE e.entity_uuid = o.entity_uuid)`, and the identical
    # pattern on `entity_prop_sort` was measured reporting 0 gaps and every type
    # COMPLETE against a table missing 329,235 rows.


async def test_a_valueless_slot_is_not_reported_as_a_gap(pg_conn, test_space):
    """The upper-bound caveat, and why this cannot gate.

    A slot with a type and no value derives nothing, so it is correctly absent.
    The cheap count still counts it, and the expensive count is what separates
    the two causes.
    """
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        entity_slot_sort_valueless_slots)
    before_sf = (await _sf(pg_conn, test_space))["shortfall"]
    before_vl = await _valueless(pg_conn, test_space)
    await _load(pg_conn, test_space, "valueless", valueless=4)
    d_sf = (await _sf(pg_conn, test_space))["shortfall"] - before_sf
    d_vl = await _valueless(pg_conn, test_space) - before_vl
    assert d_sf == 4, "the cheap number counts them"
    assert d_vl == 4
    assert d_sf - d_vl == 0, (
        "and subtracting them leaves no real gap, so nothing is reported")


async def test_the_two_causes_are_separable(pg_conn, test_space):
    """A real gap AND value-less slots at once: the difference is the real gap."""
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        entity_slot_sort_valueless_slots)
    before_sf = (await _sf(pg_conn, test_space))["shortfall"]
    before_vl = await _valueless(pg_conn, test_space)
    n = await _load(pg_conn, test_space, "both", with_b=False, valueless=2)
    d_sf = (await _sf(pg_conn, test_space))["shortfall"] - before_sf
    d_vl = await _valueless(pg_conn, test_space) - before_vl
    assert d_vl == 2
    assert d_sf - d_vl == n, "the missing slot-B rows, exactly"
