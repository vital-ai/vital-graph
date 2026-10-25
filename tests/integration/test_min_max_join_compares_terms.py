"""A join on a MIN / MAX result compares RDF terms, not text (issue 307).

MIN/MAX return one term of the group (SPARQL §18.5.1), and joining on the result
requires the SAME term (compatible mappings, §18.3). The aggregate used to carry no
term uuid, so the join fell back to `CAST(a AS TEXT) = CAST(b AS TEXT)`, and a
dateTime matched a plain string with the same text. The shape is the UW dashboard's
`latest_per_deal_by_outcome`: a grouped sub-SELECT joined back on its MAX.

What must NOT change: an aggregate that is unbound is compatible with anything.
That happens for an ungrouped MAX over no rows, and for a grouped MAX whose group's
input is OPTIONAL.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

EX = "http://example.org/mm/"
DT = "http://www.w3.org/2001/XMLSchema#dateTime"
T = "2026-01-01T00:00:00"
PFX = f"PREFIX ex: <{EX}>\n"

# ?m = MAX per key, over dateTimes
SUB = "{ SELECT ?k (MAX(?v) AS ?m) WHERE { ?x ex:k ?k ; ex:p ?v } GROUP BY ?k }"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space):
    """One space per test: `space` is module-scoped, and these tests' data
    must not meet (each asserts the exact rows of its own)."""
    return await make_space()


def _vals(bindings, var):
    return sorted(b[var]["value"] for b in bindings if var in b)


async def _load(sparql_update, space, triples: str):
    await sparql_update(PFX + "INSERT DATA {\n" + triples + "\n}", space)


async def test_max_joins_the_same_term_not_the_same_text(space, sparql_update, sparql_execute):
    await _load(sparql_update, space, f'''
        ex:x1 ex:k "k1" ; ex:p "{T}"^^<{DT}> .
        ex:s_dt  ex:q "{T}"^^<{DT}> .
        ex:s_str ex:q "{T}" .
        ex:s_en  ex:q "{T}"@en .''')
    rows = await sparql_execute(PFX + f"SELECT ?s WHERE {{ ?s ex:q ?m . {SUB} }}", space)
    assert _vals(rows, "s") == [f"{EX}s_dt"]


async def test_a_tie_joins_exactly_the_picked_term(space, sparql_update, sparql_execute):
    """Two terms with the same text in one group sort equal; MAX picks one, and
    the join must match that one only."""
    await _load(sparql_update, space, f'''
        ex:x1 ex:k "k1" ; ex:p "{T}"^^<{DT}> .
        ex:x2 ex:k "k1" ; ex:p "{T}" .
        ex:s_dt  ex:q "{T}"^^<{DT}> .
        ex:s_str ex:q "{T}" .''')
    rows = await sparql_execute(PFX + f"SELECT ?s ?m WHERE {{ ?s ex:q ?m . {SUB} }}", space)
    assert len(rows) == 1, rows
    picked = await sparql_execute(PFX + f"SELECT ?m WHERE {SUB}", space)
    assert len(picked) == 1
    assert rows[0]["m"].get("datatype") == picked[0]["m"].get("datatype")


async def test_the_max_is_still_the_max(space, sparql_update, sparql_execute):
    await _load(sparql_update, space, f'''
        ex:x1 ex:k "k1" ; ex:p "2026-01-01T00:00:00"^^<{DT}> .
        ex:x2 ex:k "k1" ; ex:p "2026-03-01T00:00:00"^^<{DT}> .
        ex:x3 ex:k "k2" ; ex:p "2026-02-01T00:00:00"^^<{DT}> .
        ex:s1 ex:q "2026-01-01T00:00:00"^^<{DT}> .
        ex:s3 ex:q "2026-03-01T00:00:00"^^<{DT}> .
        ex:s2 ex:q "2026-02-01T00:00:00"^^<{DT}> .''')
    rows = await sparql_execute(PFX + f"SELECT ?s ?k WHERE {{ ?s ex:q ?m . {SUB} }}", space)
    assert sorted((b["k"]["value"], b["s"]["value"]) for b in rows) == [
        ("k1", f"{EX}s3"), ("k2", f"{EX}s2")]


async def test_an_ungrouped_max_over_nothing_is_unbound_and_joins_everything(
        space, sparql_update, sparql_execute):
    await _load(sparql_update, space, '''
        ex:s1 ex:q "a" .
        ex:s2 ex:q "b" .''')
    rows = await sparql_execute(PFX + """SELECT ?s WHERE {
        ?s ex:q ?m .
        { SELECT (MAX(?v) AS ?m) WHERE { ?x ex:none ?v } } }""", space)
    assert _vals(rows, "s") == [f"{EX}s1", f"{EX}s2"]


async def test_a_grouped_max_over_an_optional_can_be_unbound(space, sparql_update, sparql_execute):
    """Key k3 has no ex:p: its MAX is unbound, compatible with every ?s. The join
    must keep its compatible-mapping test, not become a plain equality."""
    await _load(sparql_update, space, f'''
        ex:x1 ex:k "k1" ; ex:p "{T}"^^<{DT}> .
        ex:x3 ex:k "k3" .
        ex:s_dt  ex:q "{T}"^^<{DT}> .
        ex:s_str ex:q "{T}" .''')
    rows = await sparql_execute(PFX + """SELECT ?k ?s WHERE {
        ?s ex:q ?m .
        { SELECT ?k (MAX(?v) AS ?m) WHERE { ?x ex:k ?k OPTIONAL { ?x ex:p ?v } } GROUP BY ?k } }""",
                                space)
    assert sorted((b["k"]["value"], b["s"]["value"]) for b in rows) == [
        ("k1", f"{EX}s_dt"), ("k3", f"{EX}s_dt"), ("k3", f"{EX}s_str")]


async def test_a_union_with_a_max_branch(space, sparql_update, sparql_execute):
    await _load(sparql_update, space, f'''
        ex:x1 ex:k "k1" ; ex:p "{T}"^^<{DT}> .
        ex:s_dt  ex:q "{T}"^^<{DT}> .
        ex:s_str ex:q "{T}" .
        ex:z ex:r "{T}"^^<{DT}> .''')
    rows = await sparql_execute(PFX + f"""SELECT ?m WHERE {{
        {{ {SUB} }} UNION {{ ?s ex:q ?m }}
        ?z ex:r ?m }}""", space)
    assert len(rows) == 2, rows
    assert all(b["m"].get("datatype") == DT for b in rows), rows


async def test_a_bind_copy_joins_by_term(space, sparql_update, sparql_execute):
    """BIND(?x AS ?y) is the same term as ?x: a join on ?y compares terms too."""
    await _load(sparql_update, space, f'''
        ex:a ex:p "{T}"^^<{DT}> .
        ex:s_dt  ex:q "{T}"^^<{DT}> .
        ex:s_str ex:q "{T}" .''')
    rows = await sparql_execute(PFX + """SELECT ?s WHERE {
        { ?a ex:p ?v BIND(?v AS ?w) }
        ?s ex:q ?w }""", space)
    assert _vals(rows, "s") == [f"{EX}s_dt"]
