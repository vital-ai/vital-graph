"""Integration tests: Space schema lifecycle.

Verifies that spaces can be created, queried, and dropped cleanly.
Tests the DDL generation and space isolation.

Requires PostgreSQL + Jena sidecar.
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import skip_no_infra, PROTECTED_SPACES, TEST_SPACE_PREFIX

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


# ---------------------------------------------------------------------------
# Space creation and teardown
# ---------------------------------------------------------------------------

class TestSpaceLifecycle:
    """Create and drop spaces programmatically."""

    async def test_create_space_creates_tables(self, pg_pool):
        """create_space creates term, rdf_quad, datatype tables."""
        space_id = f"{TEST_SPACE_PREFIX}lc_{uuid.uuid4().hex[:8]}"
        try:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.create_space(conn, space_id)

                # Verify tables exist
                rows = await conn.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name LIKE $1 "
                    "ORDER BY table_name",
                    f"{space_id}%",
                )
                table_names = [r["table_name"] for r in rows]
                assert f"{space_id}_term" in table_names
                assert f"{space_id}_rdf_quad" in table_names
                assert f"{space_id}_datatype" in table_names
        finally:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.drop_space(conn, space_id)

    async def test_drop_space_removes_tables(self, pg_pool):
        """drop_space removes core per-space tables."""
        space_id = f"{TEST_SPACE_PREFIX}lc_{uuid.uuid4().hex[:8]}"
        async with pg_pool.acquire() as conn:
            from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
            await SparqlSQLSchema.create_space(conn, space_id)
            await SparqlSQLSchema.drop_space(conn, space_id)

            # Verify core tables are gone
            core_tables = [
                f"{space_id}_term",
                f"{space_id}_rdf_quad",
                f"{space_id}_datatype",
                f"{space_id}_rdf_stats",
                f"{space_id}_rdf_pred_stats",
            ]
            rows = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY($1::text[])",
                core_tables,
            )
            assert len(rows) == 0

    async def test_space_tables_exist_check(self, pg_pool):
        """space_tables_exist returns correct boolean."""
        space_id = f"{TEST_SPACE_PREFIX}lc_{uuid.uuid4().hex[:8]}"
        async with pg_pool.acquire() as conn:
            from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

            # Before creation
            exists = await SparqlSQLSchema.space_tables_exist(conn, space_id)
            assert exists is False

            # After creation
            await SparqlSQLSchema.create_space(conn, space_id)
            exists = await SparqlSQLSchema.space_tables_exist(conn, space_id)
            assert exists is True

            # After drop
            await SparqlSQLSchema.drop_space(conn, space_id)
            exists = await SparqlSQLSchema.space_tables_exist(conn, space_id)
            assert exists is False

    async def test_create_space_seeds_datatypes(self, pg_pool):
        """create_space seeds standard XSD datatypes."""
        space_id = f"{TEST_SPACE_PREFIX}lc_{uuid.uuid4().hex[:8]}"
        try:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.create_space(conn, space_id)

                rows = await conn.fetch(
                    f"SELECT datatype_uri FROM {space_id}_datatype ORDER BY datatype_uri"
                )
                uris = {r["datatype_uri"] for r in rows}
                # Standard datatypes should be seeded
                assert "http://www.w3.org/2001/XMLSchema#string" in uris
                assert "http://www.w3.org/2001/XMLSchema#integer" in uris
                assert "http://www.w3.org/2001/XMLSchema#boolean" in uris
                assert "http://www.w3.org/2001/XMLSchema#dateTime" in uris
        finally:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.drop_space(conn, space_id)


# ---------------------------------------------------------------------------
# Space isolation
# ---------------------------------------------------------------------------

class TestSpaceIsolation:
    """Data in one space is invisible from another."""

    async def test_spaces_are_isolated(self, pg_pool, sparql_update, sparql_execute):
        """Data inserted into space A is not visible from space B."""
        space_a = f"{TEST_SPACE_PREFIX}iso_a_{uuid.uuid4().hex[:8]}"
        space_b = f"{TEST_SPACE_PREFIX}iso_b_{uuid.uuid4().hex[:8]}"

        try:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.create_space(conn, space_a)
                await SparqlSQLSchema.create_space(conn, space_b)

            # Insert into space A
            await sparql_update("""
            INSERT DATA {
                <http://example.org/iso/x> <http://example.org/iso/p> "only-in-A" .
            }
            """, space_a)

            # Query space A — should find it
            bindings_a = await sparql_execute("""
            SELECT ?o WHERE {
                <http://example.org/iso/x> <http://example.org/iso/p> ?o .
            }
            """, space_a)
            assert len(bindings_a) == 1
            assert bindings_a[0]["o"]["value"] == "only-in-A"

            # Query space B — should NOT find it
            bindings_b = await sparql_execute("""
            SELECT ?o WHERE {
                <http://example.org/iso/x> <http://example.org/iso/p> ?o .
            }
            """, space_b)
            assert len(bindings_b) == 0

        finally:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.drop_space(conn, space_a)
                await SparqlSQLSchema.drop_space(conn, space_b)


# ---------------------------------------------------------------------------
# Index verification
# ---------------------------------------------------------------------------

class TestIndexes:
    """Per-space indexes are created correctly."""

    async def test_indexes_created(self, pg_pool):
        """create_space creates expected indexes."""
        space_id = f"{TEST_SPACE_PREFIX}lc_{uuid.uuid4().hex[:8]}"
        try:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.create_space(conn, space_id)

                rows = await conn.fetch(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = $1",
                    f"{space_id}_rdf_quad",
                )
                index_names = {r["indexname"] for r in rows}
                # Should have at least predicate, subject, object indexes
                assert any("pred" in name for name in index_names)
                assert any("subj" in name for name in index_names)
                assert any("obj" in name for name in index_names)
        finally:
            async with pg_pool.acquire() as conn:
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                await SparqlSQLSchema.drop_space(conn, space_id)
