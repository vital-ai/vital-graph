"""Integration tests: Concurrency and connection pool safety.

Verifies that concurrent SPARQL operations don't corrupt data,
deadlock, or exhaust the connection pool.

Requires PostgreSQL + Jena sidecar.
"""

from __future__ import annotations

import asyncio

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


# ---------------------------------------------------------------------------
# Concurrent writes
# ---------------------------------------------------------------------------

class TestConcurrentWrites:
    """Parallel INSERT DATA operations produce correct results."""

    @pytest.mark.xfail(
        reason="emit_update.py term INSERT uses WHERE NOT EXISTS which races "
               "under concurrent transactions — shared predicate URIs collide "
               "(see issues/003)",
        strict=False,
    )
    async def test_parallel_inserts_no_data_loss(
        self, test_space, sparql_update, sparql_execute,
    ):
        """10 concurrent INSERT DATA operations — all triples survive."""
        n = 10
        tasks = []
        for i in range(n):
            sparql = f"""
            INSERT DATA {{
                <http://example.org/cw/s{i}> <http://example.org/cw/idx> "{i}" .
            }}
            """
            tasks.append(sparql_update(sparql, test_space))

        await asyncio.gather(*tasks)

        bindings = await sparql_execute("""
        SELECT ?s ?idx WHERE {
            ?s <http://example.org/cw/idx> ?idx .
        }
        """, test_space)
        found_indices = {b["idx"]["value"] for b in bindings}
        expected = {str(i) for i in range(n)}
        assert expected.issubset(found_indices), (
            f"Missing indices: {expected - found_indices}"
        )

    @pytest.mark.xfail(
        reason="emit_update.py term INSERT uses WHERE NOT EXISTS which races "
               "under concurrent transactions (see issues/003)",
        strict=False,
    )
    async def test_parallel_inserts_different_predicates(
        self, test_space, sparql_update, sparql_execute,
    ):
        """Concurrent inserts on different predicates don't interfere."""
        subject = "http://example.org/cw/multi_pred"
        tasks = []
        for i in range(5):
            sparql = f"""
            INSERT DATA {{
                <{subject}> <http://example.org/cw/prop{i}> "val{i}" .
            }}
            """
            tasks.append(sparql_update(sparql, test_space))

        await asyncio.gather(*tasks)

        bindings = await sparql_execute(f"""
        SELECT ?p ?o WHERE {{
            <{subject}> ?p ?o .
        }}
        """, test_space)
        props = {b["p"]["value"] for b in bindings}
        for i in range(5):
            assert f"http://example.org/cw/prop{i}" in props


# ---------------------------------------------------------------------------
# Concurrent reads + writes
# ---------------------------------------------------------------------------

class TestConcurrentReadWrite:
    """Concurrent readers and writers don't deadlock or return errors."""

    async def test_read_during_write(
        self, test_space, sparql_update, sparql_execute,
    ):
        """SELECTs executing concurrently with INSERTs complete without error."""
        # Seed some data
        await sparql_update("""
        INSERT DATA {
            <http://example.org/crw/s1> <http://example.org/crw/p> "seed" .
        }
        """, test_space)

        async def writer(idx):
            await sparql_update(f"""
            INSERT DATA {{
                <http://example.org/crw/w{idx}> <http://example.org/crw/p> "written{idx}" .
            }}
            """, test_space)

        async def reader():
            return await sparql_execute("""
            SELECT ?s WHERE {
                ?s <http://example.org/crw/p> ?o .
            }
            """, test_space)

        # Mix 5 writers and 5 readers
        tasks = []
        for i in range(5):
            tasks.append(writer(i))
            tasks.append(reader())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # No exceptions should have occurred
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Concurrent read/write exceptions: {exceptions}"


# ---------------------------------------------------------------------------
# Connection pool behavior
# ---------------------------------------------------------------------------

class TestPoolBehavior:
    """Connection pool handles concurrent demand correctly."""

    async def test_many_concurrent_queries(
        self, test_space, sparql_execute,
    ):
        """20 concurrent SELECT queries all complete without pool exhaustion."""
        async def query(idx):
            return await sparql_execute(f"""
            SELECT ?o WHERE {{
                <http://example.org/pool/s{idx}> <http://example.org/pool/p> ?o .
            }}
            """, test_space)

        tasks = [query(i) for i in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Pool exhaustion errors: {exceptions}"

    async def test_sequential_after_concurrent(
        self, test_space, sparql_update, sparql_execute,
    ):
        """Pool recovers after burst of concurrent queries."""
        # Burst
        tasks = [
            sparql_execute("""
            SELECT ?s WHERE { ?s ?p ?o } LIMIT 1
            """, test_space)
            for _ in range(10)
        ]
        await asyncio.gather(*tasks)

        # Sequential should still work
        await sparql_update("""
        INSERT DATA {
            <http://example.org/pool/recovery> <http://example.org/pool/p> "ok" .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?o WHERE {
            <http://example.org/pool/recovery> <http://example.org/pool/p> ?o .
        }
        """, test_space)
        assert len(bindings) >= 1
        assert bindings[0]["o"]["value"] == "ok"
