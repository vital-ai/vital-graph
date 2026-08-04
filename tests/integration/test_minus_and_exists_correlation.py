"""Integration tests: MINUS and EXISTS must actually constrain — issues 026, 027.

Both defects were silently-dropped constraints, the same failure family as
issue 023: the query returned the unfiltered left side and a guarded DELETE
took everything.

- **026** — `emit_minus` compared only on `__uuid` columns. `BIND`, `VALUES` and
  aggregates emit a literal `NULL::uuid` there while carrying the real value in
  the text/type columns, so a bound value read as unbound, the
  domain-intersection test was unsatisfiable, and the whole MINUS became a
  no-op.
- **027** — `_exists_to_sql` correlated only on scope-visible variables. An
  outer variable referenced solely from a FILTER inside the EXISTS pattern
  compiled to the literal `NULL`, so the subquery returned no rows: EXISTS
  always false, NOT EXISTS always true.

The correct shapes are asserted alongside the broken ones on purpose — in both
issues the difference between working and broken is a detail (where the shared
variable is bound, where the outer variable is referenced), so a test suite that
only covers the broken shapes cannot tell a real fix from one that breaks the
neighbours.

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

GRAPH = "http://example.org/graph/minus_exists"
NS = "http://example.org/probe"
N_DOCS = 4

ALL_DOCS = {f"doc{i}" for i in range(N_DOCS)}
WITHOUT_DOC0 = ALL_DOCS - {"doc0"}


async def _seed(sparql_update, space: str) -> None:
    triples = "\n".join(
        f'<{NS}/doc{i}> <{NS}/name> "doc{i}" .' for i in range(N_DOCS)
    )
    await sparql_update(
        f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}", space
    )


async def _subjects(sparql_execute, space: str, where: str) -> set:
    rows = await sparql_execute(
        f"SELECT DISTINCT ?s WHERE {{ GRAPH <{GRAPH}> {{ {where} }} }}", space
    )
    return {r["s"]["value"].rsplit("/", 1)[-1] for r in rows}


# ---------------------------------------------------------------------------
# Issue 026 — MINUS
# ---------------------------------------------------------------------------

class TestMinusSharedVarWithoutTermUuid:
    """A shared variable bound by BIND/VALUES must still constrain."""

    async def test_bind_bound_shared_var(self, test_space, sparql_update, sparql_execute):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            MINUS {{ ?x ?y ?z . BIND(<{NS}/doc0> AS ?s) }}
        """)
        assert got == WITHOUT_DOC0, "MINUS with a BIND-bound shared var was ignored"

    async def test_values_bound_shared_var(self, test_space, sparql_update, sparql_execute):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            MINUS {{ VALUES ?s {{ <{NS}/doc0> }} }}
        """)
        assert got == WITHOUT_DOC0, "MINUS with a VALUES-bound shared var was ignored"

    async def test_values_multiple_rows(self, test_space, sparql_update, sparql_execute):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            MINUS {{ VALUES ?s {{ <{NS}/doc0> <{NS}/doc1> }} }}
        """)
        assert got == {"doc2", "doc3"}

    async def test_literal_valued_shared_var(self, test_space, sparql_update, sparql_execute):
        """Exercises the derived-UUID path for literals, where lang/datatype
        must be folded in exactly as the term table did."""
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s <{NS}/name> ?nm .
            MINUS {{ VALUES ?nm {{ "doc0" "doc1" }} }}
        """)
        assert got == {"doc2", "doc3"}

    async def test_values_matching_nothing_removes_nothing(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            MINUS {{ VALUES ?s {{ <{NS}/nope> }} }}
        """)
        assert got == ALL_DOCS


class TestMinusShapesThatAlreadyWorked:
    """Guard the neighbours — these were correct before the fix."""

    async def test_plain_bgp_shared_var(self, test_space, sparql_update, sparql_execute):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o . MINUS {{ ?s <{NS}/name> "doc0" }}
        """)
        assert got == WITHOUT_DOC0

    async def test_bind_present_but_shared_var_from_bgp(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o . MINUS {{ ?s <{NS}/name> "doc0" . BIND(1 AS ?n) }}
        """)
        assert got == WITHOUT_DOC0

    async def test_no_shared_vars_removes_nothing(
        self, test_space, sparql_update, sparql_execute
    ):
        """SPARQL §18.5: with no shared variables MINUS removes nothing."""
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o . MINUS {{ ?a <{NS}/name> "doc0" }}
        """)
        assert got == ALL_DOCS

    async def test_unbound_var_still_reads_as_unbound(
        self, test_space, sparql_update, sparql_execute
    ):
        """The derived UUID must not resurrect a genuinely unbound variable
        into a non-NULL identity."""
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            MINUS {{ ?s2 <{NS}/name> "doc0" . OPTIONAL {{ ?s2 <{NS}/absent> ?w }} }}
        """)
        assert got == ALL_DOCS


# ---------------------------------------------------------------------------
# Issue 027 — EXISTS / NOT EXISTS
# ---------------------------------------------------------------------------

class TestExistsCorrelationViaInnerFilter:
    """An outer variable referenced only from an inner FILTER must correlate."""

    async def test_not_exists_correlated_filter(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            FILTER NOT EXISTS {{ ?s2 <{NS}/name> "doc0" . FILTER(?s = ?s2) }}
        """)
        assert got == WITHOUT_DOC0, "NOT EXISTS guard was dropped"

    async def test_exists_correlated_filter(
        self, test_space, sparql_update, sparql_execute
    ):
        """The EXISTS direction fails differently — it matches nothing — so a
        fix for only NOT EXISTS would not satisfy this."""
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            FILTER EXISTS {{ ?s2 <{NS}/name> "doc0" . FILTER(?s = ?s2) }}
        """)
        assert got == {"doc0"}, "EXISTS matched nothing"

    async def test_sameterm_correlation(self, test_space, sparql_update, sparql_execute):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            FILTER NOT EXISTS {{ ?s2 <{NS}/name> "doc0" . FILTER(sameTerm(?s, ?s2)) }}
        """)
        assert got == WITHOUT_DOC0

    async def test_literal_valued_outer_var(
        self, test_space, sparql_update, sparql_execute
    ):
        """?nm is referenced ONLY inside the EXISTS filter, so the outer BGP
        must still materialize its text column — otherwise the correlation
        compares against NULL."""
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s <{NS}/name> ?nm .
            FILTER NOT EXISTS {{
                ?s3 <{NS}/name> ?n3 . FILTER(?nm = ?n3 && ?n3 = "doc0")
            }}
        """)
        assert got == WITHOUT_DOC0

    async def test_literal_correlation_matches_itself(
        self, test_space, sparql_update, sparql_execute
    ):
        """Every ?nm equals some ?n3 (itself), so NOT EXISTS excludes all."""
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s <{NS}/name> ?nm .
            FILTER NOT EXISTS {{ ?s3 <{NS}/name> ?n3 . FILTER(?nm = ?n3) }}
        """)
        assert got == set()

    async def test_nested_not_exists(self, test_space, sparql_update, sparql_execute):
        """Nesting relies on the same correlation, one level down: the inner
        NOT EXISTS is false for every middle row (each ?n2 equals itself), so
        the middle pattern is empty and the outer NOT EXISTS holds for every
        row. Pre-fix the inner correlated filter compared against NULL, so the
        middle pattern was non-empty and this returned nothing.
        """
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            FILTER NOT EXISTS {{
                ?s2 <{NS}/name> ?n2 .
                FILTER NOT EXISTS {{ ?s3 <{NS}/name> ?n3 . FILTER(?n2 = ?n3) }}
            }}
        """)
        assert got == ALL_DOCS


class TestExistsShapesThatAlreadyWorked:
    """Guard the neighbours — these were correct before the fix."""

    async def test_not_exists_outer_var_in_inner_bgp(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o . FILTER NOT EXISTS {{ ?s <{NS}/name> "doc0" }}
        """)
        assert got == WITHOUT_DOC0

    async def test_exists_outer_var_in_inner_bgp(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o . FILTER EXISTS {{ ?s <{NS}/name> "doc0" }}
        """)
        assert got == {"doc0"}

    async def test_inner_local_filter_only(
        self, test_space, sparql_update, sparql_execute
    ):
        """No outer variable inside the EXISTS: the inner pattern matches for
        every outer row, so NOT EXISTS excludes everything."""
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o .
            FILTER NOT EXISTS {{ ?s2 <{NS}/name> ?n2 . FILTER(?n2 = "doc0") }}
        """)
        assert got == set()

    async def test_correlated_filter_outside_exists(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, f"""
            ?s ?p ?o . ?s2 <{NS}/name> "doc0" . FILTER(?s = ?s2)
        """)
        assert got == {"doc0"}

    async def test_exists_with_no_filter_at_all(
        self, test_space, sparql_update, sparql_execute
    ):
        await _seed(sparql_update, test_space)
        got = await _subjects(sparql_execute, test_space, """
            ?s ?p ?o . FILTER EXISTS { ?s ?p2 ?o2 }
        """)
        assert got == ALL_DOCS


# ---------------------------------------------------------------------------
# The data-loss shape both issues share
# ---------------------------------------------------------------------------

class TestGuardedDeletesDoNotWiden:
    """A dropped constraint in an update WHERE is a whole-graph delete."""

    async def _survivors(self, sparql_execute, space) -> set:
        return await _subjects(sparql_execute, space, "?s ?p ?o")

    async def test_minus_guarded_delete(self, test_space, sparql_update, sparql_execute):
        """Delete everything except doc0, excluded via VALUES in a MINUS."""
        await _seed(sparql_update, test_space)
        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{
                ?s ?p ?o .
                MINUS {{ VALUES ?s {{ <{NS}/doc0> }} }}
            }} }}
        """, test_space)
        assert await self._survivors(sparql_execute, test_space) == {"doc0"}

    async def test_not_exists_guarded_delete(
        self, test_space, sparql_update, sparql_execute
    ):
        """doc0 is protected by a correlated NOT EXISTS guard."""
        await _seed(sparql_update, test_space)
        await sparql_update(f"""
            DELETE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}
            WHERE  {{ GRAPH <{GRAPH}> {{
                ?s ?p ?o .
                FILTER NOT EXISTS {{ ?s2 <{NS}/name> "doc0" . FILTER(?s = ?s2) }}
            }} }}
        """, test_space)
        assert await self._survivors(sparql_execute, test_space) == {"doc0"}, (
            "the guard was dropped and the protected subject was deleted"
        )
