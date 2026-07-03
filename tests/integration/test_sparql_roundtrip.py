"""Integration tests: SPARQL INSERT DATA → SELECT roundtrip.

Verifies that data inserted via SPARQL UPDATE can be correctly
retrieved by SPARQL SELECT through the full V2 pipeline.

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
# Basic triple roundtrip
# ---------------------------------------------------------------------------

class TestBasicRoundtrip:
    """INSERT DATA → SELECT with URIs and literals."""

    async def test_insert_and_select_uri_triple(
        self, test_space, sparql_update, sparql_execute
    ):
        """Insert a URI triple and retrieve it."""
        insert = """
        INSERT DATA {
            <http://example.org/s1> <http://example.org/p1> <http://example.org/o1> .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?s ?p ?o WHERE {
            ?s <http://example.org/p1> ?o .
        }
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) >= 1

        row = bindings[0]
        assert row["s"]["type"] == "uri"
        assert row["s"]["value"] == "http://example.org/s1"
        assert row["o"]["type"] == "uri"
        assert row["o"]["value"] == "http://example.org/o1"

    async def test_insert_and_select_literal(
        self, test_space, sparql_update, sparql_execute
    ):
        """Insert a plain literal and retrieve it."""
        insert = """
        INSERT DATA {
            <http://example.org/s2> <http://example.org/name> "Alice" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?name WHERE {
            <http://example.org/s2> <http://example.org/name> ?name .
        }
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 1
        assert bindings[0]["name"]["value"] == "Alice"
        assert bindings[0]["name"]["type"] == "literal"

    async def test_insert_multiple_triples(
        self, test_space, sparql_update, sparql_execute
    ):
        """Insert multiple triples in one INSERT DATA."""
        insert = """
        INSERT DATA {
            <http://example.org/multi/a> <http://example.org/val> "1" .
            <http://example.org/multi/b> <http://example.org/val> "2" .
            <http://example.org/multi/c> <http://example.org/val> "3" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?s ?v WHERE {
            ?s <http://example.org/val> ?v .
        } ORDER BY ?v
        """
        bindings = await sparql_execute(select, test_space)
        values = [b["v"]["value"] for b in bindings]
        assert "1" in values
        assert "2" in values
        assert "3" in values

    async def test_select_with_filter(
        self, test_space, sparql_update, sparql_execute
    ):
        """INSERT then FILTER on literal value."""
        insert = """
        INSERT DATA {
            <http://example.org/filt/a> <http://example.org/score> "10" .
            <http://example.org/filt/b> <http://example.org/score> "20" .
            <http://example.org/filt/c> <http://example.org/score> "30" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?s ?score WHERE {
            ?s <http://example.org/score> ?score .
            FILTER(?score = "20")
        }
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 1
        assert bindings[0]["score"]["value"] == "20"


# ---------------------------------------------------------------------------
# OPTIONAL / LEFT JOIN
# ---------------------------------------------------------------------------

class TestOptional:
    """SPARQL OPTIONAL produces LEFT JOIN."""

    async def test_optional_present(
        self, test_space, sparql_update, sparql_execute
    ):
        """OPTIONAL matches — bound variable present."""
        insert = """
        INSERT DATA {
            <http://example.org/opt/a> <http://example.org/label> "A" .
            <http://example.org/opt/a> <http://example.org/desc> "Description A" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?s ?label ?desc WHERE {
            ?s <http://example.org/label> ?label .
            OPTIONAL { ?s <http://example.org/desc> ?desc }
        }
        """
        bindings = await sparql_execute(select, test_space)
        match = [b for b in bindings if b.get("s", {}).get("value") == "http://example.org/opt/a"]
        assert len(match) >= 1
        assert "desc" in match[0]
        assert match[0]["desc"]["value"] == "Description A"

    async def test_optional_absent(
        self, test_space, sparql_update, sparql_execute
    ):
        """OPTIONAL doesn't match — variable unbound (absent from binding)."""
        insert = """
        INSERT DATA {
            <http://example.org/opt/b> <http://example.org/label> "B" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?s ?label ?desc WHERE {
            ?s <http://example.org/label> ?label .
            OPTIONAL { ?s <http://example.org/desc> ?desc }
            FILTER(?s = <http://example.org/opt/b>)
        }
        """
        bindings = await sparql_execute(select, test_space)
        match = [b for b in bindings if b.get("s", {}).get("value") == "http://example.org/opt/b"]
        assert len(match) >= 1
        # desc should be unbound (absent from the binding dict)
        assert "desc" not in match[0]


# ---------------------------------------------------------------------------
# DELETE DATA
# ---------------------------------------------------------------------------

class TestDelete:
    """SPARQL DELETE DATA removes triples."""

    async def test_delete_removes_triple(
        self, test_space, sparql_update, sparql_execute
    ):
        """DELETE DATA removes a triple so it's no longer queryable."""
        insert = """
        INSERT DATA {
            <http://example.org/del/x> <http://example.org/temp> "gone" .
        }
        """
        await sparql_update(insert, test_space)

        # Verify it's there
        select = """
        SELECT ?o WHERE {
            <http://example.org/del/x> <http://example.org/temp> ?o .
        }
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 1

        # Delete it
        delete = """
        DELETE DATA {
            <http://example.org/del/x> <http://example.org/temp> "gone" .
        }
        """
        await sparql_update(delete, test_space)

        # Verify it's gone
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 0


# ---------------------------------------------------------------------------
# UNION
# ---------------------------------------------------------------------------

class TestUnion:
    """SPARQL UNION combines result sets."""

    async def test_union_combines_patterns(
        self, test_space, sparql_update, sparql_execute
    ):
        """UNION of two patterns returns rows from both."""
        insert = """
        INSERT DATA {
            <http://example.org/u/a> <http://example.org/type> "typeA" .
            <http://example.org/u/b> <http://example.org/kind> "kindB" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?s ?val WHERE {
            { ?s <http://example.org/type> ?val }
            UNION
            { ?s <http://example.org/kind> ?val }
        }
        """
        bindings = await sparql_execute(select, test_space)
        values = {b["val"]["value"] for b in bindings}
        assert "typeA" in values
        assert "kindB" in values


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestAggregation:
    """SPARQL aggregates (COUNT, SUM, etc.)."""

    async def test_count(
        self, test_space, sparql_update, sparql_execute
    ):
        """COUNT returns correct number."""
        insert = """
        INSERT DATA {
            <http://example.org/agg/a> <http://example.org/tag> "x" .
            <http://example.org/agg/b> <http://example.org/tag> "x" .
            <http://example.org/agg/c> <http://example.org/tag> "x" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT (COUNT(?s) AS ?cnt) WHERE {
            ?s <http://example.org/tag> "x" .
        }
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 1
        assert int(bindings[0]["cnt"]["value"]) == 3


# ---------------------------------------------------------------------------
# LIMIT / OFFSET
# ---------------------------------------------------------------------------

class TestSlice:
    """SPARQL LIMIT and OFFSET."""

    async def test_limit(
        self, test_space, sparql_update, sparql_execute
    ):
        """LIMIT restricts result count."""
        insert = """
        INSERT DATA {
            <http://example.org/lim/a> <http://example.org/seq> "1" .
            <http://example.org/lim/b> <http://example.org/seq> "2" .
            <http://example.org/lim/c> <http://example.org/seq> "3" .
            <http://example.org/lim/d> <http://example.org/seq> "4" .
            <http://example.org/lim/e> <http://example.org/seq> "5" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?s WHERE {
            ?s <http://example.org/seq> ?v .
        } LIMIT 3
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 3

    async def test_offset(
        self, test_space, sparql_update, sparql_execute
    ):
        """OFFSET + LIMIT returns correct slice."""
        select = """
        SELECT ?v WHERE {
            ?s <http://example.org/seq> ?v .
        } ORDER BY ?v LIMIT 2 OFFSET 2
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 2
        values = [b["v"]["value"] for b in bindings]
        assert "3" in values
        assert "4" in values


# ---------------------------------------------------------------------------
# DISTINCT
# ---------------------------------------------------------------------------

class TestDistinct:
    """SPARQL DISTINCT deduplicates."""

    async def test_distinct_deduplicates(
        self, test_space, sparql_update, sparql_execute
    ):
        """DISTINCT removes duplicate bindings."""
        insert = """
        INSERT DATA {
            <http://example.org/dup/a> <http://example.org/color> "red" .
            <http://example.org/dup/b> <http://example.org/color> "red" .
            <http://example.org/dup/c> <http://example.org/color> "blue" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT DISTINCT ?color WHERE {
            ?s <http://example.org/color> ?color .
        }
        """
        bindings = await sparql_execute(select, test_space)
        values = {b["color"]["value"] for b in bindings}
        assert values == {"red", "blue"}


# ---------------------------------------------------------------------------
# BIND / expressions
# ---------------------------------------------------------------------------

class TestBind:
    """SPARQL BIND creates computed variables."""

    async def test_bind_concat(
        self, test_space, sparql_update, sparql_execute
    ):
        """BIND(CONCAT(...)) produces computed value."""
        insert = """
        INSERT DATA {
            <http://example.org/bind/a> <http://example.org/first> "Hello" .
            <http://example.org/bind/a> <http://example.org/last> "World" .
        }
        """
        await sparql_update(insert, test_space)

        select = """
        SELECT ?full WHERE {
            <http://example.org/bind/a> <http://example.org/first> ?f .
            <http://example.org/bind/a> <http://example.org/last> ?l .
            BIND(CONCAT(?f, " ", ?l) AS ?full)
        }
        """
        bindings = await sparql_execute(select, test_space)
        assert len(bindings) == 1
        assert bindings[0]["full"]["value"] == "Hello World"
