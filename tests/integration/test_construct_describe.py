"""Integration tests: CONSTRUCT and DESCRIBE return triples — issue 025.

Both forms used to execute as a plain SELECT and return the WHERE-pattern
bindings. For a template that echoes the pattern (`CONSTRUCT { ?s ?p ?o }
WHERE { ?s ?p ?o }`) that looks almost right, which is what kept it hidden —
so the tests here deliberately use templates that are *not* echoes.

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

GRAPH = "http://example.org/graph/construct"
NS = "http://example.org/probe"


async def _seed(sparql_update, space: str) -> None:
    await sparql_update(f"""INSERT DATA {{ GRAPH <{GRAPH}> {{
        <{NS}/a> <{NS}/friend> <{NS}/b> .
        <{NS}/a> <{NS}/name>   "alice" .
        <{NS}/b> <{NS}/friend> <{NS}/c> .
        <{NS}/b> <{NS}/name>   "bob" .
    }} }}""", space)


def _triples(result):
    return result.get("triples")


def _as_tuples(triples):
    return sorted(
        (t["subject"]["value"], t["predicate"]["value"], t["object"]["value"])
        for t in triples
    )


class TestConstruct:

    async def test_constant_predicate_is_the_templates_not_the_patterns(
        self, test_space, sparql_update, space_impl
    ):
        """The headline case: template predicate differs from the pattern's."""
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            CONSTRUCT {{ ?s <{NS}/knows> ?o }}
            WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/friend> ?o }} }}
        """)
        assert res["success"], res.get("error")
        assert _as_tuples(_triples(res)) == [
            (f"{NS}/a", f"{NS}/knows", f"{NS}/b"),
            (f"{NS}/b", f"{NS}/knows", f"{NS}/c"),
        ]

    async def test_bindings_are_not_returned_as_results(
        self, test_space, sparql_update, space_impl
    ):
        """A CONSTRUCT must not also present the WHERE bindings — that is the
        shape that made the defect invisible."""
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            CONSTRUCT {{ ?s <{NS}/knows> ?o }}
            WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/friend> ?o }} }}
        """)
        assert res["query_type"] == "CONSTRUCT"
        assert res["results"]["bindings"] == []

    async def test_reordered_template(self, test_space, sparql_update, space_impl):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            CONSTRUCT {{ ?o <{NS}/friendOf> ?s }}
            WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/friend> ?o }} }}
        """)
        assert _as_tuples(_triples(res)) == [
            (f"{NS}/b", f"{NS}/friendOf", f"{NS}/a"),
            (f"{NS}/c", f"{NS}/friendOf", f"{NS}/b"),
        ]

    async def test_deduplicates_across_solutions(
        self, test_space, sparql_update, space_impl
    ):
        """Two solutions, one constant triple — a graph, not a bag."""
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            CONSTRUCT {{ <{NS}/marker> a <{NS}/Seen> }}
            WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/friend> ?o }} }}
        """)
        assert len(_triples(res)) == 1

    async def test_blank_node_is_fresh_per_solution(
        self, test_space, sparql_update, space_impl
    ):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            CONSTRUCT {{ _:link <{NS}/about> ?s }}
            WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/friend> ?o }} }}
        """)
        triples = _triples(res)
        assert len(triples) == 2
        subjects = {t["subject"]["value"] for t in triples}
        assert all(t["subject"]["type"] == "bnode" for t in triples)
        assert len(subjects) == 2, f"blank node shared across solutions: {subjects}"

    async def test_literal_object_preserved_with_datatype(
        self, test_space, sparql_update, space_impl
    ):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            CONSTRUCT {{ ?s <{NS}/label> ?n }}
            WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/name> ?n }} }}
        """)
        objs = sorted(t["object"]["value"] for t in _triples(res))
        assert objs == ["alice", "bob"]
        assert all(t["object"]["type"] == "literal" for t in _triples(res))

    async def test_empty_result_set(self, test_space, sparql_update, space_impl):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            CONSTRUCT {{ ?s <{NS}/knows> ?o }}
            WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/nosuch> ?o }} }}
        """)
        assert res["success"]
        assert _triples(res) == []


class TestDescribe:

    async def test_describe_constant_uri(self, test_space, sparql_update, space_impl):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(
            test_space, f"DESCRIBE <{NS}/a>")
        assert res["success"], res.get("error")
        got = _as_tuples(_triples(res))
        assert got == [
            (f"{NS}/a", f"{NS}/friend", f"{NS}/b"),
            (f"{NS}/a", f"{NS}/name", "alice"),
        ]

    async def test_describe_variable_from_where(
        self, test_space, sparql_update, space_impl
    ):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(test_space, f"""
            DESCRIBE ?s WHERE {{ GRAPH <{GRAPH}> {{ ?s <{NS}/name> "bob" }} }}
        """)
        assert _as_tuples(_triples(res)) == [
            (f"{NS}/b", f"{NS}/friend", f"{NS}/c"),
            (f"{NS}/b", f"{NS}/name", "bob"),
        ]

    async def test_describe_returns_no_bindings(
        self, test_space, sparql_update, space_impl
    ):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(
            test_space, f"DESCRIBE <{NS}/a>")
        assert res["query_type"] == "DESCRIBE"
        assert res["results"]["bindings"] == []

    async def test_describe_unknown_uri_is_empty_not_an_error(
        self, test_space, sparql_update, space_impl
    ):
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(
            test_space, f"DESCRIBE <{NS}/nonexistent>")
        assert res["success"]
        assert _triples(res) == []

    async def test_describe_is_forward_only(
        self, test_space, sparql_update, space_impl
    ):
        """Documented strategy: triples where the target is the *subject*.
        `<a> friend <b>` must not appear when describing `<b>`."""
        await _seed(sparql_update, test_space)
        res = await space_impl.execute_sparql_query(
            test_space, f"DESCRIBE <{NS}/c>")
        assert _triples(res) == [], (
            "describing <c> returned triples where it is only the object — "
            "the strategy is forward CBD"
        )
