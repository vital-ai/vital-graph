"""Integration tests: Bulk data loading.

Verifies that large INSERT DATA batches are handled correctly
and that the data is fully queryable afterwards.

Requires PostgreSQL + Jena sidecar.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


# ---------------------------------------------------------------------------
# Batch insert
# ---------------------------------------------------------------------------

class TestBulkInsert:
    """Large INSERT DATA operations."""

    async def test_insert_100_triples(
        self, test_space, sparql_update, sparql_execute,
    ):
        """100 triples in a single INSERT DATA are all queryable."""
        triples = "\n".join(
            f'<http://example.org/bulk/s{i}> <http://example.org/bulk/value> "{i}" .'
            for i in range(100)
        )
        await sparql_update(f"""
        INSERT DATA {{
            {triples}
        }}
        """, test_space)

        bindings = await sparql_execute("""
        SELECT (COUNT(?s) AS ?count) WHERE {
            ?s <http://example.org/bulk/value> ?o .
        }
        """, test_space)
        assert len(bindings) == 1
        assert int(bindings[0]["count"]["value"]) >= 100

    async def test_insert_100_triples_queryable_individually(
        self, test_space, sparql_execute,
    ):
        """Each of the 100 inserted triples can be queried by subject."""
        # Uses data from previous test (same module-scoped space)
        bindings = await sparql_execute("""
        SELECT ?o WHERE {
            <http://example.org/bulk/s42> <http://example.org/bulk/value> ?o .
        }
        """, test_space)
        assert len(bindings) >= 1
        assert bindings[0]["o"]["value"] == "42"

    async def test_insert_multiple_predicates_per_subject(
        self, test_space, sparql_update, sparql_execute,
    ):
        """50 subjects with 3 predicates each = 150 triples."""
        triples = []
        for i in range(50):
            s = f"<http://example.org/bulk/mp{i}>"
            triples.append(f'{s} <http://example.org/bulk/name> "item{i}" .')
            triples.append(f'{s} <http://example.org/bulk/idx> "{i}" .')
            triples.append(f'{s} <http://example.org/bulk/type> "widget" .')

        await sparql_update(f"""
        INSERT DATA {{
            {chr(10).join(triples)}
        }}
        """, test_space)

        # Count all widget-typed items
        bindings = await sparql_execute("""
        SELECT (COUNT(?s) AS ?count) WHERE {
            ?s <http://example.org/bulk/type> "widget" .
        }
        """, test_space)
        assert int(bindings[0]["count"]["value"]) >= 50


# ---------------------------------------------------------------------------
# Batch insert with mixed types
# ---------------------------------------------------------------------------

class TestBulkMixedTypes:
    """Bulk inserts with mixed URI and literal objects."""

    async def test_mixed_uri_and_literal_objects(
        self, test_space, sparql_update, sparql_execute,
    ):
        """Insert batch with both URI references and literals."""
        triples = []
        for i in range(20):
            s = f"<http://example.org/bulk/mixed{i}>"
            triples.append(f'{s} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/bulk/Thing> .')
            triples.append(f'{s} <http://example.org/bulk/label> "thing{i}" .')
            if i > 0:
                triples.append(f'{s} <http://example.org/bulk/related> <http://example.org/bulk/mixed{i-1}> .')

        await sparql_update(f"""
        INSERT DATA {{
            {chr(10).join(triples)}
        }}
        """, test_space)

        # Check type assertions
        bindings = await sparql_execute("""
        SELECT (COUNT(?s) AS ?count) WHERE {
            ?s a <http://example.org/bulk/Thing> .
        }
        """, test_space)
        assert int(bindings[0]["count"]["value"]) >= 20

        # Check relationships
        bindings = await sparql_execute("""
        SELECT (COUNT(?s) AS ?count) WHERE {
            ?s <http://example.org/bulk/related> ?o .
        }
        """, test_space)
        assert int(bindings[0]["count"]["value"]) >= 19


# ---------------------------------------------------------------------------
# Incremental batch insert
# ---------------------------------------------------------------------------

class TestIncrementalBatch:
    """Multiple sequential INSERT DATA operations accumulate correctly."""

    async def test_sequential_batches_accumulate(
        self, test_space, sparql_update, sparql_execute,
    ):
        """Three separate INSERT DATA calls accumulate data."""
        for batch in range(3):
            triples = "\n".join(
                f'<http://example.org/bulk/seq_b{batch}_s{i}> <http://example.org/bulk/batch> "{batch}" .'
                for i in range(10)
            )
            await sparql_update(f"""
            INSERT DATA {{
                {triples}
            }}
            """, test_space)

        bindings = await sparql_execute("""
        SELECT (COUNT(?s) AS ?count) WHERE {
            ?s <http://example.org/bulk/batch> ?b .
        }
        """, test_space)
        assert int(bindings[0]["count"]["value"]) >= 30

    async def test_filter_by_batch(
        self, test_space, sparql_execute,
    ):
        """Can filter results by batch number."""
        bindings = await sparql_execute("""
        SELECT (COUNT(?s) AS ?count) WHERE {
            ?s <http://example.org/bulk/batch> "1" .
        }
        """, test_space)
        assert int(bindings[0]["count"]["value"]) >= 10
