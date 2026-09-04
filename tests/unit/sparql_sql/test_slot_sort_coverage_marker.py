"""The completeness marker that gates the slot-value FILTER path.

`issues/161`. The filter path is only sound if the table is known to cover the
entity type. This is what "known" means, and every default here points at
DECLINING, because the two failure directions are not comparable:

    false NO   a slow, correct answer down the general pipeline
    false YES  a silently short answer with a plausible count and no error

`issues/149` measured a production type at 1.05% while its own drift probe
reported converged, so "assume fine" is not available.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.fast_slot_filter import (
    record_slot_sort_coverage, slot_sort_coverage_is_complete)


class _Conn:
    """Records what it was asked, answers what it was told to."""

    def __init__(self, row=None, raises=False):
        self._row, self._raises = row, raises
        self.executed = []

    async def fetchrow(self, sql, *args):
        if self._raises:
            raise RuntimeError("relation does not exist")
        return self._row

    async def execute(self, sql, *args):
        if self._raises:
            raise RuntimeError("relation does not exist")
        self.executed.append(args)


@pytest.mark.asyncio
async def test_a_recorded_complete_type_is_served():
    assert await slot_sort_coverage_is_complete(
        _Conn(row={"complete": True}), "sp", "urn:e") is True


@pytest.mark.asyncio
async def test_a_recorded_incomplete_type_is_refused():
    assert await slot_sort_coverage_is_complete(
        _Conn(row={"complete": False}), "sp", "urn:e") is False


@pytest.mark.asyncio
async def test_no_marker_refuses():
    """The default for a space nothing has verified yet."""
    assert await slot_sort_coverage_is_complete(
        _Conn(row=None), "sp", "urn:e") is False


@pytest.mark.asyncio
async def test_an_unreadable_marker_table_refuses():
    """A space predating the table must not be read as 'complete'."""
    assert await slot_sort_coverage_is_complete(
        _Conn(raises=True), "sp", "urn:e") is False


@pytest.mark.asyncio
async def test_full_coverage_records_complete():
    c = _Conn()
    await record_slot_sort_coverage(c, "sp", "u", 100, 100)
    assert c.executed[0][4] is True


@pytest.mark.asyncio
async def test_short_coverage_records_incomplete():
    c = _Conn()
    await record_slot_sort_coverage(c, "sp", "u", 809, 76996)
    assert c.executed[0][4] is False


@pytest.mark.asyncio
async def test_a_surplus_still_counts_as_complete():
    """in_table >= of_type, not ==.

    The table can hold rows for entities whose type quad was deleted while their
    slot rows await the sync. That direction costs the filter no matches; only
    SHORT is dangerous.
    """
    c = _Conn()
    await record_slot_sort_coverage(c, "sp", "u", 101, 100)
    assert c.executed[0][4] is True


@pytest.mark.asyncio
async def test_a_type_with_no_entities_is_not_complete():
    """0 of 0 must not read as 'complete'.

    An empty type is how an unpopulated space looks before anything derives, and
    calling that complete would open the fast path on exactly the state the
    marker exists to catch.
    """
    c = _Conn()
    await record_slot_sort_coverage(c, "sp", "u", 0, 0)
    assert c.executed[0][4] is False


@pytest.mark.asyncio
async def test_recording_never_raises_into_the_maintenance_loop():
    """It is advisory. A failure leaves the marker unset, which declines."""
    await record_slot_sort_coverage(_Conn(raises=True), "sp", "u", 1, 1)
