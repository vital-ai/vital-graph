"""ORDER BY a variable the projection drops sorts on its values (issue 324).

Found by a differential sweep against Oxigraph, on the default path:

- An ordering variable the projection drops had no text: `SELECT ?k … ORDER BY ?n`
  sorted on NULLs, so the order (and a LIMIT's page) came from the next key alone.
- `ORDER BY` a variable nothing binds failed with an SQL error.

An unbound value sorts lowest, first ascending and last descending (SPARQL 15.1,
issues/326). Kept as they are (issues/324): equal numbers in different lexical
forms (10, 1.0E1) are ordered by their text before the next key.
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

EX = "http://example.org/obs/"
PFX = f"PREFIX ex: <{EX}>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:i1 ex:kind ex:a ; ex:name "delta" ; ex:score 5 .
        ex:i2 ex:kind ex:b ; ex:name "alpha" ; ex:score 10 .
        ex:i3 ex:kind ex:a ; ex:name "charlie" ; ex:score "1.0E1"^^xsd:double .
        ex:i4 ex:kind ex:c ; ex:name "bravo" .
    }""", s)
    return s


def _last(rows, var):
    return [b[var]["value"].rsplit("/", 1)[-1] if var in b else None for b in rows]


async def test_order_by_a_variable_the_projection_drops(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE { ?s ex:name ?n } ORDER BY ?n""", space)
    assert _last(rows, "s") == ["i2", "i4", "i3", "i1"]          # alpha, bravo, charlie, delta


async def test_order_by_a_dropped_variable_pages(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE { ?s ex:name ?n } ORDER BY DESC(?n) LIMIT 2""", space)
    assert _last(rows, "s") == ["i1", "i3"]                      # delta, charlie


async def test_unbound_sorts_first_ascending(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE { ?s ex:kind ?k OPTIONAL { ?s ex:score ?v } }
        ORDER BY ?v ?s""", space)
    assert _last(rows, "s") == ["i4", "i1", "i3", "i2"]          # none, 5, 1.0E1 / 10 (by text)


async def test_unbound_sorts_last_descending(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE { ?s ex:kind ?k OPTIONAL { ?s ex:score ?v } }
        ORDER BY DESC(?v) ?s LIMIT 3""", space)
    assert _last(rows, "s") == ["i2", "i3", "i1"]                # 10 / 1.0E1 (by text), 5; none last


async def test_order_by_a_variable_nothing_binds(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s ?x WHERE { ?s ex:name ?n } ORDER BY ?x ?n""", space)
    assert _last(rows, "s") == ["i2", "i4", "i3", "i1"]
