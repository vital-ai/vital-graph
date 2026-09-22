"""A type-agreement verdict that cannot be reached is not bought again per query.

`frame_type_absorbable` keys its verdict on the table's row count so that a
changed table re-derives it. For a verdict of UNKNOWN that is exactly backwards.
Measured on production 2026-09-22, the frame check needs **122,488 ms** — it
scans 3,007,724 mirror rows against 7,143,296 type quads — against its 250 ms
budget, so it always times out. The row count of a space taking writes changes
constantly, so every change re-derived the same unknown: `plan_decisions`
carried `"type": null` on every single generation, each having paid the full
budget to learn nothing, plus ~236 ms for the `count(*)` that invalidated it.
Together, the largest single cost in SQL generation — a 512 ms median on EVERY
query. Across both checks and all spaces, 11.4 hours of cumulative database time
on the counts alone.

Believing an unknown is safe in the one direction that matters: unknown means DO
NOT ABSORB, so a stale one costs an optimisation and can never produce a wrong
row. A stale TRUE could, and that is still keyed on the count.
"""
from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import edge_type_agreement as eta

RDF_TYPE = eta.RDF_TYPE_URI
VITALTYPE = eta.VITALTYPE_URI


class _Conn:
    """Counts what reaches the database."""

    def __init__(self, count_value=3_007_724, blow_up_on_agreement=True):
        self.count_value = count_value
        self.blow_up_on_agreement = blow_up_on_agreement
        self.counts = 0
        self.agreements = 0

    async def fetchval(self, sql, *args):
        if sql.startswith("SELECT count(*)"):
            self.counts += 1
            return self.count_value
        if sql.strip().startswith("SELECT term_uuid FROM"):
            # NOT a substring test on "term_text": the edge agreement query
            # resolves the predicate in a SUBQUERY, so it contains that too.
            return "f947f06c-bd0c-5ae0-bcd6-6db005605b0a"
        if sql.startswith("SHOW "):
            # bounded_lock_wait saves and restores lock_timeout around the
            # count; swallowing it here would make the count look free.
            return "30s"
        self.agreements += 1
        if self.blow_up_on_agreement:
            raise TimeoutError("canceling statement due to statement timeout")
        return None

    async def execute(self, sql):
        return None

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False

        return _Tx()


@pytest.fixture(autouse=True)
def _clean():
    eta.clear_cache()
    yield
    eta.clear_cache()


@pytest.mark.asyncio
async def test_a_timed_out_verdict_is_not_recomputed_when_rows_change():
    conn = _Conn()
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
    assert (conn.counts, conn.agreements) == (1, 1)

    # The space takes writes, so the count moves. That must NOT buy the same
    # failure again -- and must not even pay for the count to discover it.
    for extra in (1, 2, 3):
        conn.count_value += extra
        assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
    assert (conn.counts, conn.agreements) == (1, 1)


@pytest.mark.asyncio
async def test_the_unknown_expires_so_a_reachable_verdict_is_still_found():
    conn = _Conn()
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
    eta._UNKNOWN["sp", "frame", RDF_TYPE] -= eta.UNKNOWN_TTL_S + 1
    conn.blow_up_on_agreement = False
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is True


@pytest.mark.asyncio
async def test_the_edge_check_gets_the_same_treatment():
    conn = _Conn()
    assert await eta.edge_type_absorbable("sp", RDF_TYPE, conn) is None
    before = (conn.counts, conn.agreements)
    conn.count_value += 10
    assert await eta.edge_type_absorbable("sp", RDF_TYPE, conn) is None
    assert (conn.counts, conn.agreements) == before


@pytest.mark.asyncio
async def test_vitaltype_never_asked_the_database_and_still_does_not():
    conn = _Conn()
    assert await eta.frame_type_absorbable("sp", VITALTYPE, conn) is True
    assert (conn.counts, conn.agreements) == (0, 0)
