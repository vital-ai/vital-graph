"""A bulk import stamps server-managed properties, and the stats agree.

These four are server-managed, so every KGEntity acquires them eventually. They
used to be added afterwards by `backfill_server_properties_task`, which writes
quads with raw SQL and maintains no derived table — so on two freshly loaded
fixtures `rdf_pred_stats` held 21 of 24 predicates, missing exactly
hasObjectCreationTime, hasObjectModificationDateTime and hasObjectStatusType at
10,000 rows each.

That is not a cosmetic gap. Everything keyed on pred_stats loses those
predicates silently: the join reorder's cardinality lookup, the traversal
criterion gate (which reports "unmeasured" with no predicate total, so a filter
on entity status can never be measured), and the value-histogram freshness
reference. A missing statistic reads exactly like a statistic saying "nothing
here".

Stamping during the import puts them in the same batch the loader already hands
to `sync_stats_after_insert`, so they are counted like any other quad.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef
from rdflib.namespace import XSD

from vitalgraph.kg_impl.kg_server_properties import (
    CREATION_TIME_URI, DEFAULT_STATUS, ENTITY_TYPE_URI, KGENTITY_CLASS_URI,
    MODIFICATION_TIME_URI, RDF_TYPE_URI, STATUS_TYPE_URI)

pytestmark = pytest.mark.asyncio(loop_scope="session")

GRAPH = "urn:sp_test_server_props"
N_ENTITIES = 25


def _quads(n):
    g = URIRef(GRAPH)
    out = []
    for i in range(n):
        e = URIRef(f"urn:spt:entity:{i}")
        out.append((e, URIRef(RDF_TYPE_URI), URIRef(KGENTITY_CLASS_URI), g))
        out.append((e, URIRef("http://vital.ai/ontology/vital-core#hasName"),
                    Literal(f"entity {i}"), g))
    return out


@pytest_asyncio.fixture(loop_scope="session")
async def loaded_space(space_impl):
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    sid = f"spt_srvprop_{uuid.uuid4().hex[:8]}"
    async with space_impl.get_db_connection() as conn:
        await conn.execute(
            "INSERT INTO space (space_id, space_name, update_time) "
            "VALUES ($1,$1,CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING", sid)
        await SparqlSQLSchema.create_space(conn, sid)
    try:
        await space_impl.add_rdf_quads_batch_bulk(sid, _quads(N_ENTITIES))
        yield sid
    finally:
        async with space_impl.get_db_connection() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, sid)
                await conn.execute("DELETE FROM space WHERE space_id=$1", sid)
            except Exception:
                pass


async def _pred_count(conn, sid, uri):
    return await conn.fetchval(f"""
        SELECT count(*) FROM {sid}_rdf_quad q
        JOIN {sid}_term t ON t.term_uuid = q.predicate_uuid
        WHERE t.term_text = $1""", uri)


async def test_every_entity_is_stamped(space_impl, loaded_space):
    sid = loaded_space
    async with space_impl.get_db_connection() as conn:
        for uri in (CREATION_TIME_URI, MODIFICATION_TIME_URI,
                    STATUS_TYPE_URI, ENTITY_TYPE_URI):
            n = await _pred_count(conn, sid, uri)
            assert n == N_ENTITIES, f"{uri}: {n} quads for {N_ENTITIES} entities"


async def test_the_timestamp_is_a_TYPED_literal(space_impl, loaded_space):
    """Untyped, it stores as a URI: no dt_val, no histogram, no range query.

    The loader classifies a term by its rdflib class and falls back to 'U', so
    this is the difference between a creation time a query can filter on and one
    that silently matches nothing.
    """
    sid = loaded_space
    async with space_impl.get_db_connection() as conn:
        row = await conn.fetchrow(f"""
            SELECT t.term_type, t.dt_val, d.datatype_uri
            FROM {sid}_rdf_quad q
            JOIN {sid}_term tp ON tp.term_uuid = q.predicate_uuid
            JOIN {sid}_term t ON t.term_uuid = q.object_uuid
            LEFT JOIN {sid}_datatype d ON d.datatype_id = t.datatype_id
            WHERE tp.term_text = $1 LIMIT 1""", CREATION_TIME_URI)
        assert row is not None, "no creation time was written"
        assert row["term_type"] == "L", "stored as a URI, not a literal"
        assert row["datatype_uri"] == str(XSD.dateTime)
        assert row["dt_val"] is not None, (
            "dt_val is NULL, so the value histogram cannot see it and a range "
            "query over creation time matches nothing")


async def test_the_status_uri_is_the_documented_default(space_impl, loaded_space):
    sid = loaded_space
    async with space_impl.get_db_connection() as conn:
        val = await conn.fetchval(f"""
            SELECT t.term_text FROM {sid}_rdf_quad q
            JOIN {sid}_term tp ON tp.term_uuid = q.predicate_uuid
            JOIN {sid}_term t ON t.term_uuid = q.object_uuid
            WHERE tp.term_text = $1 LIMIT 1""", STATUS_TYPE_URI)
        assert val == DEFAULT_STATUS


async def test_pred_stats_counts_the_stamped_predicates(space_impl, loaded_space):
    """The whole point: the import's own stats sync must see these quads.

    This is what was broken. Asserted against the live quad table rather than
    against a constant, so it fails the same way whether the stamp goes missing
    or the sync does.
    """
    sid = loaded_space
    async with space_impl.get_db_connection() as conn:
        rows = await conn.fetch(f"""
            SELECT t.term_text AS predicate, a.n AS actual, ps.row_count AS in_stats
            FROM (SELECT predicate_uuid, count(*) n FROM {sid}_rdf_quad GROUP BY 1) a
            JOIN {sid}_term t ON t.term_uuid = a.predicate_uuid
            LEFT JOIN {sid}_rdf_pred_stats ps ON ps.predicate_uuid = a.predicate_uuid
            ORDER BY t.term_text""")
        missing = [r["predicate"] for r in rows if r["in_stats"] is None]
        assert not missing, f"predicates absent from rdf_pred_stats: {missing}"
        wrong = [(r["predicate"], r["actual"], r["in_stats"])
                 for r in rows if r["in_stats"] != r["actual"]]
        assert not wrong, f"pred_stats disagrees with the quad table: {wrong}"


async def test_a_supplied_value_is_not_overwritten(space_impl):
    """Single-valued: a second creation time is a wrong answer, not a duplicate."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    sid = f"spt_srvprop_{uuid.uuid4().hex[:8]}"
    supplied = "2020-01-01T00:00:00+00:00"
    g = URIRef(GRAPH)
    e = URIRef("urn:spt:entity:supplied")
    async with space_impl.get_db_connection() as conn:
        await conn.execute(
            "INSERT INTO space (space_id, space_name, update_time) "
            "VALUES ($1,$1,CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING", sid)
        await SparqlSQLSchema.create_space(conn, sid)
    try:
        await space_impl.add_rdf_quads_batch_bulk(sid, [
            (e, URIRef(RDF_TYPE_URI), URIRef(KGENTITY_CLASS_URI), g),
            (e, URIRef(CREATION_TIME_URI),
             Literal(supplied, datatype=XSD.dateTime), g),
        ])
        async with space_impl.get_db_connection() as conn:
            vals = [r["term_text"] for r in await conn.fetch(f"""
                SELECT t.term_text FROM {sid}_rdf_quad q
                JOIN {sid}_term tp ON tp.term_uuid = q.predicate_uuid
                JOIN {sid}_term t ON t.term_uuid = q.object_uuid
                WHERE tp.term_text = $1""", CREATION_TIME_URI)]
            assert vals == [supplied], (
                f"expected only the supplied creation time, got {vals}")
    finally:
        async with space_impl.get_db_connection() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, sid)
                await conn.execute("DELETE FROM space WHERE space_id=$1", sid)
            except Exception:
                pass
