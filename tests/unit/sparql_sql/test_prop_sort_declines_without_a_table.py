"""A space with no `entity_prop_sort` must DECLINE, not raise and get caught.

Observed on the dev instance, once per listing request:

    WARNING - prop_sort page failed, caller will fall back
    Traceback (most recent call last):
      ...
    asyncpg.exceptions.UndefinedTableError:
        relation "sp_lead_synth_100k_entity_prop_sort" does not exist

The FALLBACK was correct — the caller went to the quad joins and answered. The
REPORT was not. A space deliberately excluded from maintenance has no derived
tables by design, so this is an expected condition being logged at WARNING with
a full asyncpg traceback, once per request, burying the real errors near it.

`prop_sort_blocked` asks whether a table that EXISTS is currently at risk.
Nothing asked whether it exists at all. These cells pin the weaker question.

Only the POSITIVE is cached: a space that gains the table by migration or
resync must be picked up without a restart, which the last cell asserts.
"""

from __future__ import annotations

import pytest


class _Conn:
    """Minimal stand-in: records to_regclass lookups and answers them."""

    def __init__(self, present: bool):
        self.present = present
        self.lookups: list[str] = []

    async def fetchval(self, sql, *args):
        assert "to_regclass" in sql, f"unexpected probe: {sql}"
        self.lookups.append(args[0])
        return "some.oid" if self.present else None


@pytest.mark.asyncio
async def test_absent_table_reports_absent():
    from vitalgraph.db.sparql_sql.fast_prop_sort import (
        prop_sort_table_present, reset_prop_sort_present_cache)
    reset_prop_sort_present_cache()
    conn = _Conn(present=False)
    assert await prop_sort_table_present(conn, "sp_lead_synth_100k") is False
    assert conn.lookups == ["public.sp_lead_synth_100k_entity_prop_sort"], (
        "the probe must name the space's own table")


@pytest.mark.asyncio
async def test_a_present_table_is_cached_and_an_absent_one_is_not():
    """The asymmetry is the point.

    Caching the negative would make a space that gains the table keep declining
    until the process restarts — which is how a derived table gets built and
    then quietly not used.
    """
    from vitalgraph.db.sparql_sql.fast_prop_sort import (
        prop_sort_table_present, reset_prop_sort_present_cache)
    reset_prop_sort_present_cache()

    absent = _Conn(present=False)
    await prop_sort_table_present(absent, "sp_x")
    await prop_sort_table_present(absent, "sp_x")
    assert len(absent.lookups) == 2, (
        "an absent table must be re-checked; caching the negative strands a "
        "space that later gains one")

    present = _Conn(present=True)
    await prop_sort_table_present(present, "sp_y")
    await prop_sort_table_present(present, "sp_y")
    assert len(present.lookups) == 1, "a present table need only be found once"


@pytest.mark.asyncio
async def test_the_frame_sibling_guards_too():
    """dev measured 0 of 41 spaces with a frame_prop_sort, so it is noisier."""
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import (
        frame_prop_sort_table_present, reset_frame_prop_sort_present_cache)
    reset_frame_prop_sort_present_cache()
    conn = _Conn(present=False)
    assert await frame_prop_sort_table_present(conn, "sp_z") is False
    assert conn.lookups == ["public.sp_z_frame_prop_sort"]
