"""Integration: streaming COPY export → import round-trips a space exactly.

Export the core tables of a loaded space via binary COPY, restore them into a
fresh space, and assert identical row counts, byte-exact quad_uuids, and that
the derived edge/stats tables were rebuilt on import (space is queryable again).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import URIRef, Literal
from rdflib.namespace import XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX
from vitalgraph.db.sparql_sql.bulk_export import (
    export_space, import_space, export_space_to_nquads, read_export_manifest)
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

HES = URIRef("http://vital.ai/ontology/vital-core#hasEdgeSource")
HED = URIRef("http://vital.ai/ontology/vital-core#hasEdgeDestination")
G = URIRef("urn:export:g")
N_EDGES = 30


@pytest_asyncio.fixture(loop_scope="session")
async def two_spaces(make_space):
    return [await make_space(f"{TEST_SPACE_PREFIX}exp_{k}_{uuid.uuid4().hex[:8]}")
            for k in ("src", "dst")]


async def _counts(conn, sid):
    t = SparqlSQLSchema.get_table_names(sid)
    return {k: await conn.fetchval(f"SELECT count(*) FROM {t[k]}")
            for k in ("datatype", "term", "rdf_quad", "edge")}


async def _quad_uuids(conn, sid):
    return {r["quad_uuid"] for r in
            await conn.fetch(f"SELECT quad_uuid FROM {sid}_rdf_quad")}


async def test_export_import_round_trip(space_impl, two_spaces, tmp_path):
    src, dst = two_spaces

    quads = []
    for i in range(N_EDGES):
        e = URIRef(f"urn:export:e:{i}")
        quads += [
            (e, HES, URIRef(f"urn:export:s:{i}"), G),
            (e, HED, URIRef(f"urn:export:d:{i}"), G),
            (URIRef(f"urn:export:n:{i}"), URIRef("urn:export:age"),
             Literal(i, datatype=XSD.integer), G),
        ]
    await space_impl.add_rdf_quads_batch_bulk(src, quads)

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        src_counts = await _counts(conn, src)
        src_quads = await _quad_uuids(conn, src)
        paths = await export_space(conn, src, str(tmp_path))

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        async with conn.transaction():
            await import_space(conn, dst, paths)
        dst_counts = await _counts(conn, dst)
        dst_quads = await _quad_uuids(conn, dst)

    assert dst_counts == src_counts, (src_counts, dst_counts)
    assert src_counts["edge"] == N_EDGES        # derived table populated in src...
    assert dst_counts["edge"] == N_EDGES        # ...and rebuilt on import
    assert dst_quads == src_quads               # byte-exact quad_uuid fidelity


async def test_nquads_export_roundtrips_terms_and_escaping(space_impl, two_spaces, tmp_path):
    """DB → N-Quads → rdflib reparse preserves URIs, langs, datatypes, and
    literals with N-Triples special characters."""
    import rdflib
    from rdflib.namespace import XSD

    sid = two_spaces[0]
    g = URIRef("urn:nq:g")
    s = URIRef("urn:nq:s1")
    quads = [
        (s, URIRef("urn:nq:pu"), URIRef("urn:nq:obj"), g),
        (s, URIRef("urn:nq:plain"), Literal("hello world"), g),
        (s, URIRef("urn:nq:lang"), Literal("bonjour", lang="fr"), g),
        (s, URIRef("urn:nq:int"), Literal(42), g),                    # xsd:integer
        (s, URIRef("urn:nq:esc"), Literal('a "quote"\nand\\slash\ttab'), g),
    ]
    await space_impl.add_rdf_quads_batch_bulk(sid, quads)

    out = str(tmp_path / "export.nq")
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        n = await export_space_to_nquads(conn, sid, out, graph_uri=str(g))
    assert n == len(quads)

    ds = rdflib.Dataset()
    ds.parse(out, format="nquads")
    got = {(str(qs), str(qp), str(qo)) for qs, qp, qo, _ in ds.quads()}
    want = {(str(a), str(b), str(c)) for a, b, c, _ in quads}
    assert got == want, (got ^ want)

    # datatype + lang survived (not just lexical form)
    objs = {p: o for _, p, o, _ in ds.quads()}
    assert objs[rdflib.URIRef("urn:nq:int")].datatype == XSD.integer
    assert objs[rdflib.URIRef("urn:nq:lang")].language == "fr"


# ---------------------------------------------------------------------------
# Snapshot watermark — export consistency + catch-up sync anchor
# ---------------------------------------------------------------------------


async def test_export_manifest_records_snapshot_watermark(
        space_impl, two_spaces, tmp_path):
    """The export writes a manifest whose snapshot is a usable pg_snapshot."""
    src = two_spaces[0]
    await space_impl.add_rdf_quads_batch_bulk(
        src, [(URIRef("urn:wm:s"), URIRef("urn:wm:p"), Literal(1), G)])

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        paths = await export_space(conn, src, str(tmp_path))
        manifest = read_export_manifest(str(tmp_path))
        # Round-trips through Postgres as a real pg_snapshot, not just a string.
        assert await conn.fetchval(
            "SELECT $1::text::pg_snapshot::text", manifest["snapshot"])

    assert manifest["space_id"] == src
    assert manifest["version"] == 1
    assert set(manifest["tables"]) == {"datatype", "term", "rdf_quad"}
    assert paths["manifest"].endswith("manifest.json")


async def test_snapshot_watermark_identifies_post_export_delta(
        space_impl, two_spaces, tmp_path):
    """The recorded snapshot selects exactly the quads written after the export.

    This is the primitive a catch-up sync is built on: rows invisible to the
    export's snapshot are precisely the ones the target is missing.
    """
    src = two_spaces[0]
    await space_impl.add_rdf_quads_batch_bulk(src, [
        (URIRef(f"urn:d:pre:{i}"), URIRef("urn:d:p"), Literal(i), G)
        for i in range(5)])

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        before = await _quad_uuids(conn, src)
        await export_space(conn, src, str(tmp_path))
    snap = read_export_manifest(str(tmp_path))["snapshot"]

    # ... and now the source moves on.
    await space_impl.add_rdf_quads_batch_bulk(src, [
        (URIRef(f"urn:d:post:{i}"), URIRef("urn:d:p"), Literal(i), G)
        for i in range(3)])

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        after = await _quad_uuids(conn, src)
        delta = {r["quad_uuid"] for r in await conn.fetch(
            f"SELECT quad_uuid FROM {src}_rdf_quad "
            f"WHERE NOT pg_visible_in_snapshot(xmin::text::xid8, $1::text::pg_snapshot)",
            snap)}

    assert delta == after - before, "delta must be exactly the post-export quads"
    assert len(delta) == 3


class _CommitBetweenCopies:
    """Connection proxy that commits a concurrent write between two COPYs.

    Racing the export with a background task is timing-dependent and does not
    reliably reproduce the bug (the COPYs finish before the writer commits), so
    the interleave is forced: the hook fires in the window that matters — after
    the ``term`` COPY, before the ``rdf_quad`` one.
    """

    def __init__(self, conn, hook):
        self._conn, self._hook = conn, hook

    def __getattr__(self, name):
        return getattr(self._conn, name)

    async def copy_from_table(self, table, **kw):
        result = await self._conn.copy_from_table(table, **kw)
        if table.endswith("_term"):
            await self._hook()
        return result


async def test_export_is_self_consistent_under_concurrent_writes(
        space_impl, two_spaces, tmp_path):
    """Regression: every exported quad's terms are present in the same export.

    The three COPYs used to run in separate implicit transactions, each with its
    own snapshot — so a write committing between the `term` and `rdf_quad` COPYs
    produced an export whose quads referenced terms that were never exported.
    One REPEATABLE READ snapshot for all three makes that impossible: the later
    COPY cannot see a transaction that committed after the export began.
    """
    src, dst = two_spaces
    await space_impl.add_rdf_quads_batch_bulk(src, [
        (URIRef(f"urn:cc:seed:{i}"), URIRef("urn:cc:p"), Literal(i), G)
        for i in range(20)])

    async def write_new_terms_and_quads():
        """Commits on its own connection, mid-export."""
        await space_impl.add_rdf_quads_batch_bulk(src, [
            (URIRef(f"urn:cc:live:{i}"), URIRef(f"urn:cc:pred:{i}"),
             Literal(f"v{i}"), G)
            for i in range(50)])

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        paths = await export_space(
            _CommitBetweenCopies(conn, write_new_terms_and_quads),
            src, str(tmp_path))

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        async with conn.transaction():
            await import_space(conn, dst, paths)
        dangling = await conn.fetchval(f"""
            SELECT count(*) FROM {dst}_rdf_quad q
            WHERE NOT EXISTS (SELECT 1 FROM {dst}_term WHERE term_uuid = q.subject_uuid)
               OR NOT EXISTS (SELECT 1 FROM {dst}_term WHERE term_uuid = q.predicate_uuid)
               OR NOT EXISTS (SELECT 1 FROM {dst}_term WHERE term_uuid = q.object_uuid)
               OR NOT EXISTS (SELECT 1 FROM {dst}_term WHERE term_uuid = q.context_uuid)
        """)

    assert dangling == 0, f"{dangling} exported quads reference unexported terms"
