"""GROUP BY an expression whose language or datatype comes from its input (issue 314).

`GROUP BY (SUBSTR(?n, 1, 1) AS ?i)`: SUBSTR keeps its argument's language tag, so
the key's `__lang` companion is a COLUMN of the input (`g0.v1__lang`), not a
constant. The generator grouped by the key's value and by its companion
OVERRIDES only, so PostgreSQL refused the statement: `column "g0.v1__lang" must
appear in the GROUP BY clause`. Found by the planner's contract check, which runs
today's SQL beside its own.

Grouping by the language (and a column datatype) is also the right semantics:
"a"@en and "a" are different terms, so they are different groups.
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

EX = "http://example.org/gbx/"
PFX = f"PREFIX ex: <{EX}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:a ex:name "alice" .
        ex:b ex:name "anna" .
        ex:c ex:name "bob" .
        ex:d ex:name "amelie"@fr .
    }""", s)
    return s


async def test_group_by_substr_runs_and_counts(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?i (COUNT(*) AS ?c) WHERE { ?s ex:name ?n }
        GROUP BY (SUBSTR(?n, 1, 1) AS ?i)""", space)
    got = sorted((b["i"]["value"], b["i"].get("xml:lang") or b["i"].get("lang") or "", int(b["c"]["value"]))
                 for b in rows)
    # "a" twice, "b" once, and "a"@fr apart from "a"
    assert got == [("a", "", 2), ("a", "fr", 1), ("b", "", 1)], got


async def test_group_by_ucase_runs(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?u (COUNT(*) AS ?c) WHERE { ?s ex:name ?n }
        GROUP BY (UCASE(?n) AS ?u)""", space)
    assert len(rows) == 4
