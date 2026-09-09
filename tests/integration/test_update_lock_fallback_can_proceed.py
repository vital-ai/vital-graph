"""The UNSERIALISED fallback has to be able to actually proceed.

`issues/174` made SPARQL updates take a grouping lock, with a documented
best-effort fallback: if the lock cannot be acquired, run unserialised "rather
than failing a write that would have succeeded".

That fallback could not work. A `lock_timeout` is a SERVER-side error, so it
aborts the whole transaction; the `conn.execute(sql)` that followed then raised
InFailedSQLTransactionError and the write failed anyway — the exact outcome the
except clause existed to prevent. Observed in production during the v0.0.60
rollout, when an update contended with the draining generation.

The fix is a SAVEPOINT around the acquisition. These tests pin the two
PostgreSQL properties it depends on, because the fix is worthless if either is
false, and neither is obvious:

  * an advisory xact lock SURVIVES `RELEASE SAVEPOINT` — it lives until the
    transaction ends, so a successful acquisition is not discarded;
  * `ROLLBACK TO SAVEPOINT` leaves the transaction USABLE after a lock timeout,
    which is what lets the write proceed at all.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KEY = 0x5107_5A17          # arbitrary, distinct from application keys


async def test_an_advisory_lock_survives_release_savepoint(pg_pool):
    """If it did not, wrapping the acquisition would silently un-serialise
    every write while appearing to lock."""
    async with pg_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            sp = conn.transaction()
            await sp.start()
            await conn.fetchval("SELECT pg_advisory_xact_lock($1)", KEY)
            await sp.commit()                      # RELEASE SAVEPOINT

            held = await conn.fetchval(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                "   AND objid = $1", KEY % (2 ** 31))
            assert held > 0, (
                "the advisory lock was dropped by RELEASE SAVEPOINT — the "
                "savepoint wrapper would then serialise nothing while looking "
                "correct")
        finally:
            await tr.rollback()


async def test_a_lock_timeout_leaves_the_transaction_usable(pg_pool):
    """The property the whole fallback rests on."""
    async with pg_pool.acquire() as holder, pg_pool.acquire() as waiter:
        htr = holder.transaction()
        await htr.start()
        try:
            await holder.fetchval("SELECT pg_advisory_xact_lock($1)", KEY)

            await waiter.execute("SET lock_timeout = '300ms'")
            wtr = waiter.transaction()
            await wtr.start()
            try:
                sp = waiter.transaction()
                await sp.start()
                timed_out = False
                try:
                    await waiter.fetchval("SELECT pg_advisory_xact_lock($1)", KEY)
                except Exception:
                    timed_out = True
                    await sp.rollback()          # ROLLBACK TO SAVEPOINT
                assert timed_out, "the contended lock did not time out"

                # THE POINT: the write can still run, unserialised.
                assert await waiter.fetchval("SELECT 1") == 1, (
                    "the transaction is still aborted after rolling back to the "
                    "savepoint, so 'proceeding UNSERIALISED' cannot proceed")
            finally:
                await wtr.rollback()
        finally:
            await htr.rollback()


def test_the_acquisition_is_wrapped_in_a_savepoint():
    """Structural: without the savepoint the fallback is unreachable in
    practice, and nothing at runtime would say so — the warning is logged and
    then the next statement fails with a different error entirely."""
    import inspect
    from vitalgraph.db.sparql_sql import sparql_sql_space_impl as m

    src = inspect.getsource(m)
    # Anchored on the ROLLBACK, which exists only for this purpose. An earlier
    # version of this test looked for `conn.transaction()` in a window before
    # the call and passed with the savepoint REMOVED, because it matched the
    # enclosing transaction — a check that cannot fail is not a check.
    i = src.index("acquire_update_locks(\n") if "acquire_update_locks(\n" in src \
        else src.index("acquire_update_locks(")
    window = src[max(0, i - 500):i + 500]
    assert "_sp.rollback()" in window, (
        "acquire_update_locks is not wrapped in a savepoint that rolls back on "
        "failure; a lock_timeout aborts the transaction and the UNSERIALISED "
        "fallback then dies with InFailedSQLTransactionError instead of "
        "proceeding")
    assert "_sp.commit()" in window, (
        "the savepoint is never released on success, so the locks are held "
        "under an open savepoint for the rest of the write")
