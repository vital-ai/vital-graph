"""Integration tests: constrained DELETEs must not widen — issue 023.

The reported failure: a `VALUES` clause in an update's WHERE was dropped, so

    DELETE { GRAPH <g> { ?s ?p ?o } }
    WHERE  { GRAPH <g> { VALUES ?s { <doc0> } ?s ?p ?o } }

left `?s ?p ?o` unconstrained and deleted every triple in the graph — silently,
with a success response.

Each test here seeds N subjects, deletes exactly one, and asserts N-1 survive.
The surviving-count assertion is the point: a test that only checks the target
was removed passes just as happily when everything else was removed too.

Covers the shapes the issue recorded as already-correct (bound subject,
`FILTER(?s IN ...)`) alongside the broken one, so the correct shapes stay
correct.

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

GRAPH = "http://example.org/graph/issue023"
NS = "http://example.org/probe"
N_DOCS = 4


async def _seed(sparql_update, space: str) -> None:
    """Seed N_DOCS subjects, 2 triples each, in GRAPH."""
    triples = "\n".join(
        f"""
        <{NS}/doc{i}> <{NS}/name> "doc{i}" .
        <{NS}/doc{i}> <{NS}/kind> <{NS}/Document> .
        """
        for i in range(N_DOCS)
    )
    await sparql_update(
        f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}", space
    )


async def _surviving_subjects(sparql_execute, space: str) -> set:
    rows = await sparql_execute(
        f"SELECT DISTINCT ?s WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}", space
    )
    return {r["s"]["value"] for r in rows}


ALL_DOCS = {f"{NS}/doc{i}" for i in range(N_DOCS)}
EXPECTED_AFTER_DELETING_DOC0 = ALL_DOCS - {f"{NS}/doc0"}


class TestValuesConstrainedDelete:
    """The reported bug."""

    async def test_values_delete_removes_only_the_named_subject(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        assert await _surviving_subjects(sparql_execute, test_space) == ALL_DOCS

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{
                VALUES ?s {{ <{NS}/doc0> }}
                ?s ?p ?o .
            }} }}
        """, test_space)

        survivors = await _surviving_subjects(sparql_execute, test_space)
        assert survivors == EXPECTED_AFTER_DELETING_DOC0, (
            "VALUES constraint was dropped — the DELETE widened to the whole graph"
        )

    async def test_values_with_multiple_subjects(
        self, test_space, sparql_update, sparql_execute
    ):
        """The idiomatic 'delete these N subjects' form."""
        await _seed(sparql_update, test_space)

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{
                VALUES ?s {{ <{NS}/doc0> <{NS}/doc2> }}
                ?s ?p ?o .
            }} }}
        """, test_space)

        survivors = await _surviving_subjects(sparql_execute, test_space)
        assert survivors == {f"{NS}/doc1", f"{NS}/doc3"}

    async def test_values_matching_nothing_deletes_nothing(
        self, test_space, sparql_update, sparql_execute
    ):
        """An empty match must be a no-op, not a wildcard."""
        await _seed(sparql_update, test_space)

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{
                VALUES ?s {{ <{NS}/does-not-exist> }}
                ?s ?p ?o .
            }} }}
        """, test_space)

        survivors = await _surviving_subjects(sparql_execute, test_space)
        assert survivors == ALL_DOCS, "no-match VALUES deleted real data"

    async def test_values_in_select_still_correct(
        self, test_space, sparql_update, sparql_execute
    ):
        """The query path was never broken — keep it that way."""
        await _seed(sparql_update, test_space)

        rows = await sparql_execute(f"""
            SELECT DISTINCT ?s WHERE {{ GRAPH <{GRAPH}> {{
                VALUES ?s {{ <{NS}/doc0> }}
                ?s ?p ?o .
            }} }}
        """, test_space)
        assert {r["s"]["value"] for r in rows} == {f"{NS}/doc0"}


class TestOtherConstraintShapes:
    """Shapes the issue recorded as correct, plus ones that hit the same
    fall-through in the element mapper."""

    async def test_filter_in_delete(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{
                ?s ?p ?o .
                FILTER(?s IN (<{NS}/doc0>))
            }} }}
        """, test_space)

        assert await _surviving_subjects(sparql_execute, test_space) == \
            EXPECTED_AFTER_DELETING_DOC0

    async def test_bound_subject_delete(
        self, test_space, sparql_update, sparql_execute
    ):
        """The current mitigation's shape (segment_deletion.py)."""
        await _seed(sparql_update, test_space)

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ <{NS}/doc0> ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{ <{NS}/doc0> ?p ?o }} }}
        """, test_space)

        assert await _surviving_subjects(sparql_execute, test_space) == \
            EXPECTED_AFTER_DELETING_DOC0

    async def test_minus_constrained_delete(
        self, test_space, sparql_update, sparql_execute
    ):
        """MINUS hit the same mapper fall-through as VALUES: dropping it
        widens the delete to everything."""
        await _seed(sparql_update, test_space)

        # Delete every subject EXCEPT doc0 → doc0 is the sole survivor.
        minus_where = f"""
            ?s ?p ?o .
            MINUS {{ ?s <{NS}/name> "doc0" }}
        """
        # Sanity-check the same pattern on the query path first, so a failure
        # below is unambiguously update-specific.
        rows = await sparql_execute(
            f"SELECT DISTINCT ?s WHERE {{ GRAPH <{GRAPH}> {{ {minus_where} }} }}",
            test_space,
        )
        assert {r["s"]["value"] for r in rows} == EXPECTED_AFTER_DELETING_DOC0

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{ {minus_where} }} }}
        """, test_space)

        survivors = await _surviving_subjects(sparql_execute, test_space)
        assert survivors == {f"{NS}/doc0"}, "MINUS exclusion was dropped"

    async def test_not_exists_constrained_delete(
        self, test_space, sparql_update, sparql_execute
    ):
        """NOT EXISTS guard must not be dropped."""
        await _seed(sparql_update, test_space)
        # Mark doc0 as protected.
        await sparql_update(
            f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
            f"<{NS}/doc0> <{NS}/protected> true . }} }}", test_space
        )

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{
                ?s ?p ?o .
                FILTER NOT EXISTS {{ ?s <{NS}/protected> true }}
            }} }}
        """, test_space)

        survivors = await _surviving_subjects(sparql_execute, test_space)
        assert survivors == {f"{NS}/doc0"}, (
            "NOT EXISTS guard was dropped — protected subject was deleted"
        )


class TestFailClosed:
    """An untranslatable construct must reject the update, never widen it."""

    async def test_unsupported_construct_raises_and_deletes_nothing(
        self, test_space, sparql_update, sparql_execute
    ):
        """SERVICE has no SQL translation. The update must fail, and the data
        must be intact afterwards."""
        await _seed(sparql_update, test_space)

        with pytest.raises(Exception):
            await sparql_update(f"""
                DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
                WHERE  {{ GRAPH <{GRAPH}> {{
                    ?s ?p ?o .
                    SERVICE <http://remote.example/sparql> {{ ?s ?p2 ?o2 }}
                }} }}
            """, test_space)

        assert await _surviving_subjects(sparql_execute, test_space) == ALL_DOCS, (
            "a rejected update still deleted data"
        )

    async def test_unbound_template_var_deletes_nothing(
        self, test_space, sparql_update, sparql_execute
    ):
        """?missing is not bound by the WHERE clause.

        Per SPARQL 1.1 §3.1.3 that template yields no triple, so the update is
        a spec-legal no-op — it must neither become a wildcard nor be rejected.
        The W3C suite checks this directly ("Simple DELETE 7"); an earlier pass
        at this issue raised here and failed four conformance tests.
        """
        await _seed(sparql_update, test_space)

        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?missing ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{ ?s <{NS}/name> ?o }} }}
        """, test_space)

        assert await _surviving_subjects(sparql_execute, test_space) == ALL_DOCS, (
            "an unbound template variable acted as a wildcard"
        )
