"""One active segmentation job per document. `issues/174` item 3.

`enqueue` cancels any pending/in_progress job for a document and then inserts.
Under READ COMMITTED a second enqueue does not see the first one's uncommitted
INSERT, so its cancel matches nothing and both rows land. `claim_next` then hands
two workers two jobs for one document — its `FOR UPDATE SKIP LOCKED` stops two
workers taking the SAME job, and cannot stop this.

The partial unique index is what actually enforces it; the transaction around
the pair is not enough on its own, which is why both exist.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACTIVE = "('pending', 'in_progress')"


async def _table(conn, name):
    await conn.execute(f"""
        CREATE TABLE {name} (
            job_id SERIAL PRIMARY KEY, space_id TEXT, graph_id TEXT,
            document_uri TEXT, status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW())""")
    await conn.execute(f"""
        CREATE UNIQUE INDEX {name}_one_active ON {name} (document_uri)
         WHERE status IN {ACTIVE}""")


def _insert(name):
    """The statement `enqueue` issues, conflict clause and all."""
    return (f"INSERT INTO {name} (space_id, graph_id, document_uri, status) "
            f"VALUES ('s','g',$1,'pending') "
            f"ON CONFLICT (document_uri) WHERE status IN {ACTIVE} "
            f"DO NOTHING RETURNING job_id")


async def test_a_second_active_job_for_one_document_is_refused(pg_conn):
    name = f"segtest_{uuid.uuid4().hex[:8]}"
    await _table(pg_conn, name)
    try:
        first = await pg_conn.fetchval(_insert(name), "urn:doc:1")
        second = await pg_conn.fetchval(_insert(name), "urn:doc:1")
        assert first is not None
        assert second is None, (
            "a second active job was created for the same document — the "
            "partial unique index is missing or its predicate does not match "
            "the ON CONFLICT clause")
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {name} WHERE status IN {ACTIVE}") == 1
    finally:
        await pg_conn.execute(f"DROP TABLE IF EXISTS {name}")


async def test_a_finished_job_does_not_block_re_enqueueing(pg_conn):
    """The half that keeps the constraint from being too strong.

    A document must be re-segmentable once its previous job has finished. An
    index over ALL rows rather than only the active ones would forbid that, and
    the failure would look like segmentation silently never running again.
    """
    name = f"segtest_{uuid.uuid4().hex[:8]}"
    await _table(pg_conn, name)
    try:
        assert await pg_conn.fetchval(_insert(name), "urn:doc:1") is not None
        await pg_conn.execute(f"UPDATE {name} SET status = 'completed'")
        assert await pg_conn.fetchval(_insert(name), "urn:doc:1") is not None
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {name} WHERE status IN {ACTIVE}") == 1
    finally:
        await pg_conn.execute(f"DROP TABLE IF EXISTS {name}")


async def test_different_documents_are_independent(pg_conn):
    name = f"segtest_{uuid.uuid4().hex[:8]}"
    await _table(pg_conn, name)
    try:
        for i in range(4):
            assert await pg_conn.fetchval(_insert(name), f"urn:doc:{i}") is not None
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {name} WHERE status IN {ACTIVE}") == 4
    finally:
        await pg_conn.execute(f"DROP TABLE IF EXISTS {name}")


async def test_the_schema_ships_the_index(pg_conn):
    """The migration covers existing spaces; the schema must cover new ones.

    Without this the invariant would hold only where someone remembered to run
    the migration — the silent-absence failure these issues keep finding.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    ddl = " ".join(SparqlSQLSchema().create_space_indexes_sql("probe_space"))
    assert "active_doc_uq" in ddl
    assert "CREATE UNIQUE INDEX" in ddl
    assert "WHERE status IN ('pending', 'in_progress')" in ddl


def test_every_space_index_name_fits_postgres_identifier_limit():
    """PostgreSQL truncates identifiers at 63 bytes, silently.

    An index whose generated name overflows is still CREATED — under the
    truncated name — so it enforces correctly while every lookup by the intended
    name misses it. That is how the first version of the index above passed on
    production, whose space ids are short, and failed only against a test space
    with a longer one.

    Checked against a deliberately long space id rather than a typical one,
    since the limit is only reached at the long end.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    import re

    long_space = "inttest_" + "0" * 12          # the shape the suite generates
    ddl = SparqlSQLSchema().create_space_indexes_sql(long_space)
    names = [m.group(1) for stmt in ddl
             for m in [re.search(r"INDEX (?:CONCURRENTLY )?(?:IF NOT EXISTS )?(\w+)", stmt)]
             if m]
    over = [(n, len(n)) for n in names if len(n) > 63]
    assert not over, (
        f"index name(s) exceed PostgreSQL's 63-byte identifier limit and will be "
        f"silently truncated: {over}")
