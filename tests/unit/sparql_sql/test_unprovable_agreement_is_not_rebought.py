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
        if "FROM type_agreement" in sql:
            # This double models an UNMIGRATED database, so the legacy in-query
            # check is what runs. The stored-verdict path has its own below.
            import asyncpg
            raise asyncpg.UndefinedTableError("no such table")
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


class _StoredConn(_Conn):
    """A database that HAS `type_agreement`, so the stored verdict rules."""

    def __init__(self, agrees=True, token="100:5", live_token="100:5", **kw):
        super().__init__(**kw)
        self.agrees = agrees
        self.token = token
        self.live_token = live_token
        self.reads = 0

    async def fetchval(self, sql, *args):
        if "FROM type_agreement" in sql:
            # The real query compares the token IN SQL and returns a row only
            # when it still matches, so the double does the same.
            self.reads += 1
            if self.agrees is _MISSING or self.token != self.live_token:
                return None
            return self.agrees
        return await super().fetchval(sql, *args)


_MISSING = object()


@pytest.mark.asyncio
async def test_a_stored_verdict_answers_without_touching_the_source_tables():
    """The point of the whole exercise: no count, no two-minute scan."""
    conn = _StoredConn(agrees=True)
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is True
    assert (conn.counts, conn.agreements) == (0, 0)


@pytest.mark.asyncio
async def test_a_verdict_whose_table_moved_is_not_used():
    """A stale TRUE is the one direction that returns wrong rows."""
    conn = _StoredConn(agrees=True, token="100:5", live_token="101:5")
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
    assert (conn.counts, conn.agreements) == (0, 0)


@pytest.mark.asyncio
async def test_a_truncated_table_is_not_used_either():
    """TRUNCATE keeps the churn counters but moves relfilenode — the vacuous
    agreement `issues/182` hit, caught by the other half of the token."""
    conn = _StoredConn(agrees=True, token="100:5", live_token="100:9")
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None


@pytest.mark.asyncio
async def test_no_row_yet_means_do_not_absorb_and_do_not_ask():
    """Absent means the job has not looked. It must NOT fall through to the
    question the query path cannot answer."""
    conn = _StoredConn(agrees=_MISSING)
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
    assert (conn.counts, conn.agreements) == (0, 0)


@pytest.mark.asyncio
async def test_an_unmigrated_database_keeps_its_old_behaviour():
    """No `type_agreement` table: the in-query check still runs, so a
    deployment that has not migrated is not silently de-optimised."""
    conn = _Conn(blow_up_on_agreement=False)   # `_Conn` has no type_agreement
    assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is True
    assert conn.counts == 1 and conn.agreements == 1


class TestTheRefreshRaisesBOTHFences:
    """A long read on this pool is bounded twice, and raising one does nothing.

    Shipped with only the server fence raised, the production refresh died at
    almost exactly 60 s on 2026-09-23 with an EMPTY error message — which is
    what `str(asyncio.TimeoutError())` is. asyncpg's `command_timeout=60` fires
    in the DRIVER, so `SET statement_timeout` cannot reach it. The small space
    (13.3 s) succeeded and the two needing ~120 s never could: it worked exactly
    where it was not needed, which is why no local test caught it.
    """

    @pytest.mark.asyncio
    async def test_every_long_read_passes_a_client_timeout(self):
        seen = []

        class _Conn:
            async def fetchval(self, sql, *args, timeout=None):
                if sql.startswith("SELECT count(*)") or "IS DISTINCT FROM" in sql:
                    seen.append((sql.split()[1], timeout))
                    return 5 if sql.startswith("SELECT count(*)") else None
                if sql == "SHOW statement_timeout":
                    return "60s"
                return "pred-uuid"

            async def fetchrow(self, sql, *args):
                return {"churn": 1, "relfilenode": 2}

            async def execute(self, sql, *a):
                return None

        await eta.refresh_type_agreement(_Conn(), "sp")
        assert seen, "no long read was issued"
        for what, timeout in seen:
            assert timeout == eta.REFRESH_CLIENT_TIMEOUT_S, (
                f"{what} was issued without the client bound; asyncpg's "
                f"command_timeout=60 would kill it regardless of the server")

    def test_the_client_bound_sits_above_the_server_one(self):
        """So PostgreSQL cancels first and says what it cancelled. A driver
        timeout arrives as a bare TimeoutError with no message at all."""
        assert eta.REFRESH_CLIENT_TIMEOUT_S > eta.REFRESH_TIMEOUT_MS / 1000.0


class TestTheReadDoesNotPayPerQuery:
    """`_stored_verdict`'s cost is the ROUND TRIP, not the SQL.

    Measured server-side on production the query is 0.11 ms; it showed 20.9 ms
    in `timings_ms`. So the saving is in not asking. Only the negative is
    cached: "no usable verdict" means do not absorb, so a stale one costs an
    optimisation for seconds. A cached POSITIVE would be the stale TRUE the
    change token exists to prevent.
    """

    @pytest.mark.asyncio
    async def test_a_miss_is_not_re_asked_every_query(self):
        conn = _StoredConn(agrees=_MISSING)
        for _ in range(5):
            assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
        assert conn.reads == 1, f"asked the database {conn.reads} times for one miss"

    @pytest.mark.asyncio
    async def test_a_positive_is_revalidated_every_query(self):
        """Never cached: this is the direction that returns wrong rows."""
        conn = _StoredConn(agrees=True)
        for _ in range(5):
            assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is True
        assert conn.reads == 5

    @pytest.mark.asyncio
    async def test_a_written_verdict_is_picked_up_when_the_miss_expires(self):
        conn = _StoredConn(agrees=_MISSING)
        assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
        conn.agrees = True                      # an explicit refresh ran
        assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is None
        eta._NO_VERDICT["sp", "frame", RDF_TYPE] -= eta.NO_VERDICT_TTL_S + 1
        assert await eta.frame_type_absorbable("sp", RDF_TYPE, conn) is True
