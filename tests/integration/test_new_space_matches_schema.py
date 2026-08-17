"""A space the manager creates carries the WHOLE schema — every table, every index.

`tests/performance/test_fixture_indexes_match_schema.py` compares long-lived
BENCHED spaces against the schema, which catches drift: a fixture that has fallen
behind. It cannot catch the other direction — a creation path that never built
the thing in the first place — because a fixture loaded years ago and a space
created this morning are indistinguishable once both are old.

This asks the creation path directly: make a space, compare it with the schema,
drop it. If a table or index is added to `SparqlSQLSchema` and not to whatever
`create_space_with_tables` runs, this fails on the next run rather than in a
benchmark six months later that measures a configuration no deployed space has.

WHAT PROMPTED IT

Eight spaces on the test stack were missing `{space}_entity_slot_sort` —
`wordnet_frames`, both `sp_graph_synth` fixtures, `sp_kg_types` and four others —
and one of them failed the drift test. Every one of those predates the table.
A space created today has all 24, so the creation path was never at fault, but
nothing in the suite could say that: establishing it took a throwaway space and a
hand-written comparison, which is exactly the check that should not be manual.

Tables are created ONLY by an explicit action — this creates its own space
through the space manager and drops it, and asserts nothing about spaces it did
not create.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

from .conftest import skip_no_infra

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def fresh_space(make_space):
    """A space created the way the application creates one.

    Through the conftest factory, which goes through `SpaceManager` — not by
    running the schema DDL directly, because the DDL agreeing with itself proves
    nothing. What is under test is whether the path the application takes runs
    all of it. The factory drops what it created at session end.
    """
    return await make_space()


async def _tables(conn, space_id):
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE $1", f"{space_id}\\_%")
    return {r["tablename"] for r in rows}


class TestANewSpaceIsComplete:

    async def test_every_schema_table_exists(self, pg_conn, fresh_space):
        want = SparqlSQLSchema.get_table_names(fresh_space)
        have = await _tables(pg_conn, fresh_space)
        missing = sorted(k for k, v in want.items() if v not in have)
        assert not missing, (
            f"{fresh_space} was created without {missing}. The schema defines "
            f"{len(want)} tables and the creation path built {len(have)} — a "
            f"table added to SparqlSQLSchema and not to the creation path "
            f"produces spaces that are silently a version behind.")

    async def test_every_schema_index_exists(self, pg_conn, fresh_space):
        """Indexes, not just tables — a table present but unindexed reads as
        complete and performs like a sequential scan."""
        import re
        create_re = re.compile(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
            r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[A-Za-z0-9_]+)\s+ON\s+"
            r"(?:public\.)?(?P<table>[A-Za-z0-9_]+)", re.IGNORECASE)
        expected = {}
        for stmt in SparqlSQLSchema().create_space_indexes_sql(fresh_space):
            m = create_re.search(stmt)
            if m:
                expected[m.group("name")] = m.group("table")
        assert expected, "schema produced no indexes to compare against"

        rows = await pg_conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
            "AND tablename LIKE $1", f"{fresh_space}\\_%")
        have = {r["indexname"] for r in rows}
        missing = sorted(n for n in expected if n not in have)
        assert not missing, (
            f"{fresh_space} is missing {len(missing)} schema index(es): "
            f"{missing[:8]}")

    async def test_the_comparison_is_not_vacuous(self, pg_conn, fresh_space):
        """The guard on the two above.

        Both compare a schema list against a database list, and both pass
        trivially if the schema list is empty or the LIKE pattern matches
        nothing. Either would turn this file into a test that cannot fail.
        """
        want = SparqlSQLSchema.get_table_names(fresh_space)
        have = await _tables(pg_conn, fresh_space)
        assert len(want) >= 20, f"schema defines only {len(want)} tables"
        assert len(have) >= 20, f"found only {len(have)} tables for {fresh_space}"
