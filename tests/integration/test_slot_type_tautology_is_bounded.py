"""The slot-type tautology check must not cost a user a minute of their query.

`excludes_nothing` is an optimisation INPUT: knowing that no role slot lacks a
type lets `rewrite_frame_slot_table` drop the per-row check, worth 7.4x. The
anti-join that answers it carries `LIMIT 1`, which short-circuits as soon as a
counterexample appears — but that is the verdict which DISABLES the
optimisation. Proving the useful answer means scanning every role slot, so the
outcome worth having is by construction the expensive one.

Measured on `wordnet_frames` (`issues/178`): 58s, 26s and 3.9s in three
successive COLD processes and ~20ms warm. The spread is PostgreSQL's buffer
cache, so 58s is the post-deploy cost, and it was charged inside the query of
whichever user arrived first.

These pin the bound and the two properties it rests on. The second one is the
`issues/177` lesson arrived at from the other direction: a statement_timeout is
enforced SERVER-side and ABORTS the transaction, so a bound without a savepoint
to roll back to would leave the connection unusable — trading a slow query for a
broken one.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import slot_type_tautology as stt

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

ROLES = ("urn:hasSourceEntity", "urn:hasDestinationEntity")
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
SOME_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntitySlot"
SPACE = "wordnet_frames"


async def _require_loaded(pg_conn):
    """Skip unless the space is actually there, with rows.

    Without this the timeout tests pass for the WRONG reason: a missing table
    raises, the same `except` swallows it, and `excludes_nothing` returns None —
    which is exactly what a successful timeout returns. The assertion would hold
    on an empty database and the check would be worthless.

    A plain helper rather than a fixture: an async fixture here runs on a
    different event loop than these session-scoped tests, and asyncpg refuses a
    connection reached from two loops.
    """
    ok = await pg_conn.fetchval(
        "SELECT to_regclass($1) IS NOT NULL", f"{SPACE}_rdf_quad")
    if not ok:
        pytest.skip(f"{SPACE} not loaded")
    if not await pg_conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM {SPACE}_rdf_quad)"):
        pytest.skip(f"{SPACE} is empty")
    return SPACE


async def test_a_statement_timeout_aborts_the_transaction(pg_conn):
    """The property the savepoint exists for.

    If this were false the wrapper would be unnecessary. It is not false, and a
    bound written without it would produce InFailedSQLTransactionError on every
    later statement — a slow query turned into a broken connection.
    """
    import asyncpg

    await pg_conn.execute("SET statement_timeout = '50ms'")
    try:
        tr = pg_conn.transaction()
        await tr.start()
        with pytest.raises(asyncpg.QueryCanceledError):
            await pg_conn.execute("SELECT pg_sleep(5)")
        # The transaction is now aborted: any statement fails until rollback.
        with pytest.raises(asyncpg.InFailedSQLTransactionError):
            await pg_conn.execute("SELECT 1")
        await tr.rollback()
        # ...and after the rollback it is usable again.
        assert await pg_conn.fetchval("SELECT 1") == 1
    finally:
        await pg_conn.execute("SET statement_timeout = 0")


async def test_the_bound_leaves_the_connection_usable(pg_conn, monkeypatch):
    """A 1ms budget makes the anti-join give up; the caller must survive it.

    This is the whole point: `excludes_nothing` returning None means "keep the
    check", which is correct-but-slower. It must not mean "the connection is
    dead".
    """
    space = await _require_loaded(pg_conn)
    monkeypatch.setattr(stt, "TAUTOLOGY_TIMEOUT_MS", 1)
    stt.clear_cache()

    verdict = await stt.excludes_nothing(
        space, SOME_TYPE, ROLES, RDF_TYPE, pg_conn)

    # None is the safe direction — keep the constraint rather than drop one that
    # might exclude something.
    assert verdict is None
    # The connection survived, which a bound without the savepoint would not.
    assert await pg_conn.fetchval("SELECT 1") == 1


async def test_statement_timeout_is_restored(pg_conn, monkeypatch):
    """It must not leak to the next user of a pooled connection."""
    space = await _require_loaded(pg_conn)
    monkeypatch.setattr(stt, "TAUTOLOGY_TIMEOUT_MS", 1)
    stt.clear_cache()
    before = await pg_conn.fetchval("SHOW statement_timeout")

    await stt.excludes_nothing(
        space, SOME_TYPE, ROLES, RDF_TYPE, pg_conn)

    assert await pg_conn.fetchval("SHOW statement_timeout") == before


async def test_the_giving_up_verdict_is_cached(pg_conn, monkeypatch):
    """Otherwise every query of this shape re-pays the full timeout.

    Caching None loses the 7.4x for the life of the process, which is the
    better trade: the check is an optimisation input, the timeout is not.
    """
    space = await _require_loaded(pg_conn)
    monkeypatch.setattr(stt, "TAUTOLOGY_TIMEOUT_MS", 1)
    stt.clear_cache()

    await stt.excludes_nothing(
        space, SOME_TYPE, ROLES, RDF_TYPE, pg_conn)
    assert stt._CACHE, "gave up without recording it, so the next query re-pays"
    assert all(v[1] is None for v in stt._CACHE.values())



async def test_the_success_path_actually_runs(pg_conn, monkeypatch):
    """The verdict path must not raise. It did.

    Every other test in this file forces a TIMEOUT, so all four exercised the
    early `return None` and none of them ever reached the code after it. A
    refactor left the success-path log line referencing `row`, a local that had
    moved into `_anti_join`, and it raised NameError on every successful
    verdict — swallowed by the caller's blanket `except`, which silently
    disabled the optimisation it exists to enable.

    Found by a probe, not by the suite. This is the test that would have caught
    it: a real verdict, computed, with the default budget.
    """
    space = await _require_loaded(pg_conn)
    stt.clear_cache()
    # A GENEROUS budget, deliberately. The first version of this test used the
    # default 2s, the anti-join expired on a cold cache, and it took the same
    # early `return None` as every other test here — so it passed with the bug
    # reintroduced. Verified: with the bug back, this now FAILS.
    monkeypatch.setattr(stt, "TAUTOLOGY_TIMEOUT_MS", 600_000)

    verdict = await stt.excludes_nothing(
        space, SOME_TYPE, ROLES, RDF_TYPE, pg_conn)

    assert isinstance(verdict, bool), (
        "the success path did not complete — it must not raise, and a raised "
        "exception here is swallowed by the caller's blanket except")
    assert stt._CACHE, "computed a verdict without caching it"
