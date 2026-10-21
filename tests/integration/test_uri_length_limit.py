"""No URI over the limit is stored (`issues/283`).

`entity_uri` / `frame_uri` are the tie-break key column of the prop-sort
indexes, and a btree entry is capped at 2,704 bytes. A long enough entity URI
failed its write there, the way a long value did before `value_key`. The limit
is on every URI term: refused by the Python writers, and by a CHECK on the term
table for the writes that intern terms in SQL alone.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
GRAPH = "http://example.org/urilimit/graph"


def _entity(uri: str):
    from rdflib import Literal, URIRef
    g = URIRef(GRAPH)
    return [(URIRef(uri), URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (URIRef(uri), URIRef(f"{CORE}hasName"), Literal("x" * 300), g)]


def _uri(n_bytes: int) -> str:
    base = "http://example.org/urilimit/"
    return base + "a" * (n_bytes - len(base))


async def _stored(conn, space, uri) -> bool:
    return bool(await conn.fetchval(
        f"SELECT 1 FROM {space_prefix(space)}_term WHERE term_text = $1 AND term_type = 'U'", uri))


async def test_a_uri_at_the_limit_is_stored(test_space, space_impl, pg_pool):
    from vitalgraph.db.sparql_sql.uri_limit import MAX_URI_BYTES
    uri = _uri(MAX_URI_BYTES)
    await space_impl.add_rdf_quads_batch(test_space, _entity(uri))
    async with pg_pool.acquire() as conn:
        assert await _stored(conn, test_space, uri)


async def test_a_uri_over_the_limit_is_refused_and_nothing_is_written(
        test_space, space_impl, pg_pool):
    from vitalgraph.db.sparql_sql.uri_limit import MAX_URI_BYTES, UriTooLong
    from vitalgraph.kg_impl.refusals import RequestRefused
    uri = _uri(MAX_URI_BYTES + 1)
    for write in (space_impl.add_rdf_quads_batch, space_impl.add_rdf_quads_batch_bulk):
        with pytest.raises(UriTooLong) as e:
            await write(test_space, _entity(uri))
        assert isinstance(e.value, RequestRefused), "a refusal, not a server error"
        assert f"{MAX_URI_BYTES + 1} bytes" in str(e.value)
    async with pg_pool.acquire() as conn:
        assert not await _stored(conn, test_space, uri)


async def test_multibyte_characters_count_as_bytes(test_space, space_impl):
    from vitalgraph.db.sparql_sql.uri_limit import MAX_URI_BYTES, UriTooLong
    base = "http://example.org/urilimit/"
    uri = base + "é" * ((MAX_URI_BYTES - len(base)) // 2 + 1)   # 2 bytes each
    assert len(uri) <= MAX_URI_BYTES < len(uri.encode())
    with pytest.raises(UriTooLong):
        await space_impl.add_rdf_quads_batch(test_space, _entity(uri))


async def test_a_sparql_insert_data_is_refused(test_space, space_impl, pg_pool):
    """`execute_sparql_update` reports failure as False, not by raising."""
    from vitalgraph.db.sparql_sql.uri_limit import MAX_URI_BYTES
    uri = _uri(MAX_URI_BYTES + 1)
    assert await space_impl.execute_sparql_update(
        test_space,
        f'INSERT DATA {{ GRAPH <{GRAPH}> {{ <{uri}> <{CORE}hasName> "n" }} }}') is False
    async with pg_pool.acquire() as conn:
        assert not await _stored(conn, test_space, uri)


async def test_the_table_refuses_a_uri_interned_in_sql(test_space, pg_pool):
    """The backstop, for a value bound in a WHERE clause that no Python
    builder sees."""
    import asyncpg
    from vitalgraph.db.sparql_sql.uri_limit import MAX_URI_BYTES
    async with pg_pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                f"INSERT INTO {space_prefix(test_space)}_term (term_uuid, term_text, term_type) "
                f"VALUES (gen_random_uuid(), $1, 'U')", _uri(MAX_URI_BYTES + 1))
        # A literal of any length is not a URI and is not limited.
        await conn.execute(
            f"INSERT INTO {space_prefix(test_space)}_term (term_uuid, term_text, term_type) "
            f"VALUES (gen_random_uuid(), $1, 'L')", "v" * 5000)
