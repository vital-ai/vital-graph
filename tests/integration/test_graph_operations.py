"""Integration tests: Named graph operations.

Verifies SPARQL GRAPH clause behavior, named graph isolation,
and multi-graph queries.

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
# Named graph INSERT + SELECT
# ---------------------------------------------------------------------------

class TestNamedGraphInsert:
    """Data inserted into a named graph is queryable via GRAPH clause."""

    async def test_insert_into_named_graph(
        self, test_space, sparql_update, sparql_execute,
    ):
        """INSERT DATA with GRAPH clause stores data in the named graph."""
        graph_uri = "http://example.org/graph/named1"
        await sparql_update(f"""
        INSERT DATA {{
            GRAPH <{graph_uri}> {{
                <http://example.org/ng/s1> <http://example.org/ng/p1> "value1" .
            }}
        }}
        """, test_space)

        bindings = await sparql_execute(f"""
        SELECT ?o WHERE {{
            GRAPH <{graph_uri}> {{
                <http://example.org/ng/s1> <http://example.org/ng/p1> ?o .
            }}
        }}
        """, test_space)
        assert len(bindings) >= 1
        assert bindings[0]["o"]["value"] == "value1"

    async def test_default_graph_vs_named(
        self, test_space, sparql_update, sparql_execute,
    ):
        """Data in default graph is distinct from named graph."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/ng/default_s> <http://example.org/ng/p2> "default_val" .
        }
        """, test_space)

        await sparql_update("""
        INSERT DATA {
            GRAPH <http://example.org/graph/other> {
                <http://example.org/ng/other_s> <http://example.org/ng/p2> "other_val" .
            }
        }
        """, test_space)

        # Query default graph — should find default_val
        bindings_default = await sparql_execute("""
        SELECT ?o WHERE {
            <http://example.org/ng/default_s> <http://example.org/ng/p2> ?o .
        }
        """, test_space)
        assert len(bindings_default) >= 1
        assert bindings_default[0]["o"]["value"] == "default_val"

        # Query named graph — should find other_val
        bindings_named = await sparql_execute("""
        SELECT ?o WHERE {
            GRAPH <http://example.org/graph/other> {
                <http://example.org/ng/other_s> <http://example.org/ng/p2> ?o .
            }
        }
        """, test_space)
        assert len(bindings_named) >= 1
        assert bindings_named[0]["o"]["value"] == "other_val"


# ---------------------------------------------------------------------------
# Multi-graph queries
# ---------------------------------------------------------------------------

class TestMultiGraph:
    """Queries spanning multiple graphs."""

    async def test_query_across_graphs(
        self, test_space, sparql_update, sparql_execute,
    ):
        """SELECT without GRAPH clause finds data from default graph."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/mg/s1> <http://example.org/mg/name> "Alice" .
        }
        """, test_space)

        # Query without GRAPH clause
        bindings = await sparql_execute("""
        SELECT ?name WHERE {
            <http://example.org/mg/s1> <http://example.org/mg/name> ?name .
        }
        """, test_space)
        assert len(bindings) >= 1
        values = [b["name"]["value"] for b in bindings]
        assert "Alice" in values

    async def test_multiple_triples_same_graph(
        self, test_space, sparql_update, sparql_execute,
    ):
        """Multiple triples in same named graph are all queryable."""
        graph = "http://example.org/graph/multi"
        await sparql_update(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <http://example.org/mg/s2> <http://example.org/mg/name> "Bob" .
                <http://example.org/mg/s2> <http://example.org/mg/age> "30" .
                <http://example.org/mg/s3> <http://example.org/mg/name> "Carol" .
            }}
        }}
        """, test_space)

        bindings = await sparql_execute(f"""
        SELECT ?s ?name WHERE {{
            GRAPH <{graph}> {{
                ?s <http://example.org/mg/name> ?name .
            }}
        }}
        """, test_space)
        assert len(bindings) >= 2
        names = {b["name"]["value"] for b in bindings}
        assert "Bob" in names
        assert "Carol" in names


# ---------------------------------------------------------------------------
# DELETE from named graph
# ---------------------------------------------------------------------------

class TestNamedGraphDelete:
    """DELETE DATA operations on named graphs."""

    async def test_delete_from_named_graph(
        self, test_space, sparql_update, sparql_execute,
    ):
        """DELETE DATA removes specific triple from named graph."""
        graph = "http://example.org/graph/del"
        await sparql_update(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <http://example.org/ng/del_s> <http://example.org/ng/p> "keep" .
                <http://example.org/ng/del_s> <http://example.org/ng/p> "remove" .
            }}
        }}
        """, test_space)

        await sparql_update(f"""
        DELETE DATA {{
            GRAPH <{graph}> {{
                <http://example.org/ng/del_s> <http://example.org/ng/p> "remove" .
            }}
        }}
        """, test_space)

        bindings = await sparql_execute(f"""
        SELECT ?o WHERE {{
            GRAPH <{graph}> {{
                <http://example.org/ng/del_s> <http://example.org/ng/p> ?o .
            }}
        }}
        """, test_space)
        values = [b["o"]["value"] for b in bindings]
        assert "keep" in values
        assert "remove" not in values
