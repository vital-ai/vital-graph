"""Integration tests: a VALUES block keeps join guards only on what it binds — issues/293.

`emit_join` drops a join's `(x IS NULL OR x = y)` guard when both sides always
bind `x`. It used to refuse whenever ANY VALUES block sat in the subtree,
because `compute_scope` does not model UNDEF. Now only a VALUES block that
binds `x` blocks it. A variable the block never mentions cannot be left
unbound by it.

The SPARQL conformance suite never reaches a case where the two rules differ,
so these shapes are checked here against pyoxigraph as the oracle. They
include VALUES rows with UNDEF on the very variables the guards protect.

Requires PostgreSQL + Jena sidecar.
"""

from __future__ import annotations

from collections import Counter

import pyoxigraph
import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

GRAPH = "http://example.org/graph/values_guard"
NS = "http://example.org/vg"

# Four decisions; d3 is not a Decision. Reasons carry codes a/b/c; d2 has none.
# d0 and d3 have a tier, for the OPTIONAL shapes.
TRIPLES = [
    ("d0", "type", "Decision"), ("d1", "type", "Decision"),
    ("d2", "type", "Decision"), ("d3", "type", "Other"),
    ("r0", "of", "d0"), ("r0", "code", '"a"'),
    ("r1", "of", "d0"), ("r1", "code", '"b"'),
    ("r2", "of", "d1"), ("r2", "code", '"b"'),
    ("r3", "of", "d1"), ("r3", "code", '"c"'),
    ("r4", "of", "d3"), ("r4", "code", '"a"'),
    ("d0", "tier", '"gold"'), ("d3", "tier", '"lead"'),
]


def _nt() -> str:
    def term(t):
        return t if t.startswith('"') else f"<{NS}/{t}>"
    return "\n".join(f"<{NS}/{s}> <{NS}/{p}> {term(o)} ." for s, p, o in TRIPLES)


QUERIES = {
    # category_page's shape: a typed ?d beside VALUES ?code, joined to the
    # reason on both. ?d's guard is the one the new rule drops.
    "typed_beside_values": f"""
        ?d <{NS}/type> <{NS}/Decision> .
        VALUES ?code {{ "a" "b" }}
        ?r <{NS}/of> ?d ; <{NS}/code> ?code .""",
    # The same with OPTIONAL fields stacked above it.
    "with_optional": f"""
        ?d <{NS}/type> <{NS}/Decision> .
        VALUES ?code {{ "a" "c" }}
        ?r <{NS}/of> ?d ; <{NS}/code> ?code .
        OPTIONAL {{ ?d <{NS}/tier> ?tier }}""",
    # UNDEF on the VALUES-bound variable: its guard must stay.
    "undef_on_values_var": f"""
        ?d <{NS}/type> <{NS}/Decision> .
        VALUES ?code {{ "a" UNDEF }}
        ?r <{NS}/of> ?d ; <{NS}/code> ?code .""",
    # The VALUES block binds ?d too, with UNDEF: ?d's guard must stay.
    "undef_on_triple_var": f"""
        ?d <{NS}/type> ?t .
        VALUES (?d ?code) {{ (<{NS}/d0> UNDEF) (UNDEF "b") }}
        ?r <{NS}/of> ?d ; <{NS}/code> ?code .""",
    # The VALUES block on the RIGHT side of the join.
    "values_on_right": f"""
        ?d <{NS}/type> <{NS}/Decision> .
        {{ ?r <{NS}/of> ?d ; <{NS}/code> ?code . VALUES ?code {{ "b" "c" }} }}""",
}


def _oracle(where: str) -> Counter:
    store = pyoxigraph.Store()
    store.load(_nt().encode(), "application/n-triples",
               to_graph=pyoxigraph.NamedNode(GRAPH))
    rows = store.query(f"SELECT * WHERE {{ GRAPH <{GRAPH}> {{ {where} }} }}")
    names = [v.value for v in rows.variables]
    return Counter(
        tuple(sorted((n, sol[n].value) for n in names if sol[n] is not None))
        for sol in rows)


@pytest.mark.parametrize("name", sorted(QUERIES))
async def test_matches_the_oracle(name, test_space, sparql_update, sparql_execute):
    await sparql_update(
        f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {_nt()} }} }}", test_space)
    where = QUERIES[name]
    expected = _oracle(where)
    assert expected, f"{name}: the oracle returned nothing, so the test proves nothing"
    rows = await sparql_execute(
        f"SELECT * WHERE {{ GRAPH <{GRAPH}> {{ {where} }} }}", test_space)
    got = Counter(tuple(sorted((k, v["value"]) for k, v in r.items())) for r in rows)
    assert got == expected, f"{name}: got {sorted(got)} expected {sorted(expected)}"
