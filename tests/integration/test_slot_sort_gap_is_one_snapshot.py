"""The slot-sort gap counts share a snapshot and tell entity slots from empty ones — issues/277.

Production, 2026-10-17, during a cleanup deleting ~60 entity graphs a minute:
the maintenance job reported "<space> has N absent slots with no
frame_slot row — both mirrors are short" every cycle (N 57-207). Nothing was
missing. Its counts were separate statements, so they drifted apart under the
deletes (shortfall 3,368 against valueless 3,339: a phantom gap of 29; in one
snapshot both were 3,339). The repair then filled its batch with valueless
slots, which can never have a row, and reported the ones under nested frames as
unattributed.

Checked against a real database:

* `entity_slot_sort_gap` splits the shortfall into no-value slots, entity slots
  (an `hasEntitySlotValue`, here naming an entity in ANOTHER space — still a
  value) and the real gap, in one statement;
* the repair selects only absent slots carrying a value the table sorts on.
"""

from __future__ import annotations

import uuid

import pytest
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = pytest.mark.asyncio(loop_scope="session")

_HALEY = "http://vital.ai/ontology/haley-ai-kg#"
_G = "urn:t277:graph"


async def _seed(pg_conn, sp, tag):
    """Four slots of one type, none of them in `entity_slot_sort`:
    `valued` (a text value — the real gap), `empty` (no value), `entity_here`
    and `entity_elsewhere` (an entity slot naming an entity in this space, and
    one naming an entity in another space)."""
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        _SLOT_TYPE, _SLOT_VALUE_PREDS, _ENTITY_SLOT_VALUE, _u)
    ctx = _u(_G)
    stype = _u(f"urn:t277:{tag}:slottype")
    val = uuid.uuid4()
    slots = {k: _u(f"urn:t277:{tag}:slot:{k}") for k in
             ("valued", "empty", "entity_here", "entity_elsewhere")}
    quads = [(s, _SLOT_TYPE, stype, ctx) for s in slots.values()]
    quads += [(slots["valued"], _SLOT_VALUE_PREDS[0], val, ctx),
              (slots["entity_here"], _ENTITY_SLOT_VALUE, _u(f"urn:t277:{tag}:entity:local"), ctx),
              # An entity that is NOT in this space: no quad, no term here.
              (slots["entity_elsewhere"], _ENTITY_SLOT_VALUE,
               _u(f"urn:other-space:{tag}:entity:remote"), ctx)]
    await pg_conn.execute(
        f"INSERT INTO {space_prefix(sp)}_term (term_uuid, term_text, term_type) VALUES ($1,$2,'L') "
        f"ON CONFLICT DO NOTHING", val, f"value {tag}")
    await pg_conn.executemany(
        f"INSERT INTO {space_prefix(sp)}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    return slots


async def _gap(pg_conn, sp):
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import entity_slot_sort_gap
    return await entity_slot_sort_gap(pg_conn, sp)


async def test_the_gap_splits_entity_slots_from_empty_ones(pg_conn, test_space):
    before = await _gap(pg_conn, test_space)
    await _seed(pg_conn, test_space, "split")
    after = await _gap(pg_conn, test_space)
    assert after["shortfall"] - before["shortfall"] == 4
    assert after["no_value"] - before["no_value"] == 1
    assert after["entity_slots"] - before["entity_slots"] == 2, (
        "an entity slot is NOT valueless — including one naming an entity in "
        "another space, which has no quads here")
    assert after["real"] - before["real"] == 1, "only the valued slot is a gap"


async def test_the_counts_come_from_one_statement(pg_conn, test_space):
    """One snapshot: the gap is computed by a single statement, so a write
    landing mid-way cannot move one count and not the other."""
    from vitalgraph.db.sparql_sql import sync_entity_slot_sort as E

    class _Spy:
        def __init__(self, c):
            self.c, self.statements = c, 0

        async def fetchrow(self, *a, **k):
            self.statements += 1
            return await self.c.fetchrow(*a, **k)

        async def fetchval(self, *a, **k):
            self.statements += 1
            return await self.c.fetchval(*a, **k)

    for fn in (E.entity_slot_sort_gap, E.entity_slot_sort_row_shortfall):
        spy = _Spy(pg_conn)
        await fn(spy, test_space)
        assert spy.statements == 1, f"{fn.__name__} used {spy.statements} statements"


async def test_the_repair_selects_only_slots_that_can_have_a_row(pg_conn, test_space):
    from vitalgraph.db.sparql_sql import sync_entity_slot_sort as E
    slots = await _seed(pg_conn, test_space, "repair")
    picked = []
    orig = pg_conn.fetch

    class _Grab:
        def __getattr__(self, n):
            return getattr(pg_conn, n)

        async def fetch(self, sql, *a, **k):
            rows = await orig(sql, *a, **k)
            if "AS slot_uuid FROM" in sql:
                picked.extend(r["slot_uuid"] for r in rows)
            return rows

    await E.backfill_entity_slot_sort_missing_slots(_Grab(), test_space, batch_size=10_000)
    ours = set(slots.values())
    assert set(picked) & ours == {slots["valued"]}, (
        "the repair picked slots that cannot derive a row: "
        f"{sorted(k for k, v in slots.items() if v in set(picked))}")
