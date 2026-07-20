"""Concurrent write→read consistency through the real SPARQL-UPDATE code path.

Regression coverage for the connection-poisoning bug behind the E2E triples
"appears in the list" flake (issues 003 / 019):

    Concurrent ``INSERT DATA`` operations that reference a *shared* term
    (a common predicate, the graph URI, a shared type) each emitted an
    ``INSERT ... WHERE NOT EXISTS`` for that term. The existence-check and the
    insert are not atomic, so two sessions both insert the same deterministic
    ``term_uuid`` → ``UniqueViolationError`` on ``term_pkey``. That aborts the
    statement's implicit transaction and poisons the pooled connection; on
    release ``conn.reset()`` stalls and the connection pool bleeds out, so
    unrelated reads (the triples list) hang or come back empty.

The fix makes the emitted term insert ``ON CONFLICT (term_uuid) DO NOTHING``
(``emit_update._term_upsert``). These tests drive many concurrent writers that
deliberately collide on shared terms and assert (a) every update succeeds and
(b) every write is immediately readable — which fails (duplicate-key +
read-after-write miss) without the fix.

Uses a dedicated space_impl with a realistic pool so the test exercises the term
race without artificially exhausting a tiny pool.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from .conftest import (
    skip_no_infra, PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD, SIDECAR_URL,
)

pytestmark = [pytest.mark.integration, skip_no_infra]

GRAPH = "urn:inttest:raw:graph"
PRED = "http://vital.ai/ontology/vital-core#hasName"


@pytest_asyncio.fixture(loop_scope="session")
async def raw_impl():
    """A dedicated SparqlSQLSpaceImpl with a realistic pool (not the shared,
    intentionally-tiny session fixture) so high writer concurrency exercises the
    term race rather than plain pool saturation."""
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    impl = SparqlSQLSpaceImpl(
        postgresql_config={
            "host": PG_HOST, "port": PG_PORT, "database": PG_DATABASE,
            "username": PG_USER, "password": PG_PASSWORD,
            "min_pool_size": 4, "max_pool_size": 16,
        },
        sidecar_config={"url": SIDECAR_URL},
    )
    assert await impl.connect(), "space_impl failed to connect"
    yield impl
    await impl.disconnect()


@pytest_asyncio.fixture(loop_scope="session")
async def raw_space(raw_impl):
    """Ephemeral space created via the space manager (catalog row + tables)."""
    from vitalgraph.space.space_manager import SpaceManager

    sm = SpaceManager(db_impl=getattr(raw_impl, "db_impl", None), space_backend=raw_impl)
    space_id = "inttest_raw_concurrency"
    try:
        await sm.delete_space_with_tables(space_id)
    except Exception:
        pass
    assert await sm.create_space_with_tables(space_id, space_id)
    yield space_id
    try:
        await sm.delete_space_with_tables(space_id)
    except Exception:
        pass


def _subject_query(subject: str) -> str:
    return (
        f"SELECT ?s ?p ?o WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} "
        f"FILTER(?s = <{subject}>) }} LIMIT 10"
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_insert_data_shared_terms_read_after_write(raw_impl, raw_space):
    """16 writers, all sharing the same predicate + graph terms, each read back
    its own just-inserted triple. Every update must succeed and be visible.

    Without the ON CONFLICT term insert, the shared predicate/graph terms race
    into a duplicate-key error that fails the update and drops the write.
    """
    space_id = raw_space
    failures: list = []
    misses: list = []

    async def worker(wid: int):
        for i in range(12):
            subj = f"urn:inttest:raw:s:{wid}:{i}"
            update = (
                f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
                f'<{subj}> <{PRED}> "val-{wid}-{i}" . }} }}'
            )
            ok = await raw_impl.execute_sparql_update(space_id, update)
            if not ok:
                failures.append(subj)
                continue
            rows = await raw_impl.query_quads(space_id, _subject_query(subj))
            if len(rows) == 0:
                misses.append(subj)

    await asyncio.gather(*[worker(w) for w in range(16)])

    assert not failures, f"{len(failures)} INSERT DATA calls failed (term race?): {failures[:5]}"
    assert not misses, f"{len(misses)} writes not visible to their own read-back: {misses[:5]}"


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrent_writers_do_not_exhaust_pool(raw_impl, raw_space):
    """A committed write must never vanish from a concurrent independent reader,
    and the pool must not bleed out (which would surface here as a timeout)."""
    space_id = raw_space
    committed: set = set()
    done = asyncio.Event()
    misses: list = []

    async def writer(wid: int):
        for i in range(15):
            subj = f"urn:inttest:pool:s:{wid}:{i}"
            update = (
                f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
                f'<{subj}> <{PRED}> "m-{wid}-{i}" . }} }}'
            )
            assert await raw_impl.execute_sparql_update(space_id, update), f"update failed {subj}"
            committed.add(subj)

    async def reader():
        while not done.is_set():
            for subj in list(committed):
                rows = await raw_impl.query_quads(space_id, _subject_query(subj))
                if len(rows) == 0:
                    misses.append(subj)
            await asyncio.sleep(0)

    readers = [asyncio.create_task(reader()) for _ in range(4)]
    # Guard against a pool-exhaustion regression manifesting as a hang.
    await asyncio.wait_for(asyncio.gather(*[writer(w) for w in range(10)]), timeout=120)
    done.set()
    await asyncio.gather(*readers, return_exceptions=True)

    assert not misses, f"{len(misses)} committed subjects vanished from concurrent reads: {sorted(set(misses))[:5]}"
