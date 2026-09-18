"""An empty coverage sweep means two different things, and only one releases.

Eleven dev spaces sat blocked from the instant an upgrade seeded them
(2026-09-06, all in the same microsecond) with no way out:

    entity_slot_sort STALE BLOCK: test123 type None held since 2026-09-06
    (coverage never measured (seeded at upgrade)). The fast path stays OFF
    until it clears; the repair is not converging, or nothing is working on it.

Every one measured ZERO types, because every one is a slot-free test space.
`release_whole_space_block_if_complete` held the block on any empty sweep, on
the reasoning that an empty sweep "is a space whose types could not be
measured". That is right for a space with data and wrong for a space with none:
a space with no slots has nothing to cover, so the table is complete by vacuity.

The cost was never the disabled fast path — there was nothing for it to serve.
It was the alarm firing every cycle for eleven spaces, which is how a warning
that matters gets tuned out.

BOTH directions are asserted. Releasing on any empty sweep would pass the first
cell alone, so the second — a space that HAS slots but measured nothing, i.e. a
probe that genuinely failed — is what keeps the fix honest.
"""

from __future__ import annotations

import pytest


class _Conn:
    def __init__(self, has_slots: bool, probe_raises: bool = False):
        self.has_slots = has_slots
        self.probe_raises = probe_raises
        self.released = False

    async def fetchval(self, sql, *args):
        if self.probe_raises:
            raise RuntimeError("probe exploded")
        assert "EXISTS" in sql and "_rdf_quad" in sql
        return self.has_slots

    async def execute(self, *a, **k):
        self.released = True
        return "DELETE 1"

    async def fetch(self, *a, **k):
        self.released = True
        return []


async def _release(conn, rows):
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        release_whole_space_block_if_complete)
    return await release_whole_space_block_if_complete(conn, "sp_x", rows)


@pytest.mark.asyncio
async def test_empty_sweep_on_a_slotless_space_releases():
    """Nothing to measure — complete by vacuity."""
    conn = _Conn(has_slots=False)
    assert await _release(conn, []) is True, (
        "a space with no slots has nothing to cover; holding the block there "
        "buys nothing and alarms forever")


@pytest.mark.asyncio
async def test_empty_sweep_on_a_space_WITH_slots_holds():
    """Could not measure — the original reasoning, still correct."""
    conn = _Conn(has_slots=True)
    assert await _release(conn, []) is False, (
        "a space that HAS slots but measured no types is a failed probe, not "
        "an empty space — releasing would hand the fast path an unverified table")


@pytest.mark.asyncio
async def test_a_failed_probe_holds_the_block():
    """Absence of evidence must never read as evidence of absence."""
    conn = _Conn(has_slots=False, probe_raises=True)
    assert await _release(conn, []) is False, (
        "if the slot probe itself fails we do not know whether the space is "
        "empty, so the block must stay")


@pytest.mark.asyncio
async def test_a_short_type_still_holds_the_block():
    """The pre-existing rule is untouched by the empty-sweep change."""
    conn = _Conn(has_slots=True)
    rows = [{"in_table": 5, "of_type": 9}]
    assert await _release(conn, rows) is False


@pytest.mark.asyncio
async def test_complete_types_still_release():
    conn = _Conn(has_slots=True)
    rows = [{"in_table": 9, "of_type": 9}, {"in_table": 3, "of_type": 3}]
    assert await _release(conn, rows) is True
