"""An edge's `vitaltype` check is read off `edge.edge_type_uuid` only where that is exact.

`issues/293`: on the hop-wise walk, `?e vitaltype <T>` (a per-row quad probe, or
a 900,000- / 4,000,000-row set too large to hash) becomes `mv.edge_type_uuid =
<T>` in a space MARKED as maintaining the column (`sync_edge_table`): a graph
object has exactly one vitaltype, every write keeps the column in step, and a
SPARQL update that may change an edge's vitaltype (its edge sync runs after it)
unmarks the space in its own transaction until a reconcile.

The `rdf:type` form of this was reverted (`issues/182`) after returning zero rows
on 8 tests, so this checks, on a lead-shaped chain written the normal way:

  * a new space is marked; the rewrite fires; the count is the one without it;
  * an edge typed in a later write than its endpoints gets its type (the write
    path keeps the column in step) and the space stays marked;
  * a SPARQL update changing an edge's vitaltype unmarks the space, the rewrite
    stops, the answer stays right, and a reconcile marks it again;
  * an unmarked (legacy) space keeps the quad checks until reconciled;
  * a page is left alone.
"""

from __future__ import annotations

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import XSD

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

H = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"
G = "urn:inttest:edgetype:g"
N = 60
BARE = 2000


def _lead(i: int, flag: bool):
    e, fe, f0, fe2, f1, se, sl = (URIRef(f"urn:inttest:edgetype:{k}_{i}")
                                  for k in ("e", "fe", "f0", "fe2", "f1", "se", "s"))
    g, vt = URIRef(G), URIRef(f"{VC}vitaltype")
    src, dst = URIRef(f"{VC}hasEdgeSource"), URIRef(f"{VC}hasEdgeDestination")
    ft = URIRef(f"{H}hasKGFrameType")
    return [
        (e, vt, URIRef(f"{H}KGEntity"), g),
        (fe, vt, URIRef(f"{H}Edge_hasEntityKGFrame"), g), (fe, src, e, g), (fe, dst, f0, g),
        (f0, ft, URIRef("urn:inttest:edgetype:Status"), g),
        (fe2, vt, URIRef(f"{H}Edge_hasKGFrame"), g), (fe2, src, f0, g), (fe2, dst, f1, g),
        (f1, ft, URIRef("urn:inttest:edgetype:Qual"), g),
        (se, vt, URIRef(f"{H}Edge_hasKGSlot"), g), (se, src, f1, g), (se, dst, sl, g),
        (sl, URIRef(f"{H}hasKGSlotType"), URIRef("urn:inttest:edgetype:MQL"), g),
        (sl, URIRef(f"{H}hasBooleanSlotValue"), Literal(flag, datatype=XSD.boolean), g),
    ]


QUERY = f"""
SELECT (COUNT(*) AS ?count) WHERE {{ {{ SELECT DISTINCT ?entity WHERE {{ GRAPH <{G}> {{
  ?entity <{VC}vitaltype> <{H}KGEntity> .
  ?fe <{VC}vitaltype> <{H}Edge_hasEntityKGFrame> . ?fe <{VC}hasEdgeSource> ?entity .
  ?fe <{VC}hasEdgeDestination> ?f0 . ?f0 <{H}hasKGFrameType> <urn:inttest:edgetype:Status> .
  ?fe2 <{VC}vitaltype> <{H}Edge_hasKGFrame> . ?fe2 <{VC}hasEdgeSource> ?f0 .
  ?fe2 <{VC}hasEdgeDestination> ?f1 . ?f1 <{H}hasKGFrameType> <urn:inttest:edgetype:Qual> .
  ?se <{VC}vitaltype> <{H}Edge_hasKGSlot> . ?se <{VC}hasEdgeSource> ?f1 .
  ?se <{VC}hasEdgeDestination> ?s . ?s <{H}hasKGSlotType> <urn:inttest:edgetype:MQL> .
  ?s <{H}hasBooleanSlotValue> true .
}} }} }} }}"""

EXPECTED = sum(1 for i in range(N) if i % 3 != 0)


async def _setup(make_space, space_impl, pg_conn, extra=()):
    from vitalgraph.db.sparql_sql.generator import invalidate_stats_cache
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    space = await make_space()
    quads = [q for i in range(N) for q in _lead(i, i % 3 != 0)]
    # Entities with no chain, as most are: the entity anchor is then large
    # against the slot end, the semi-join split is reverted
    # (`semijoin_model_gate`) and the chain is walked hop-wise, as on lead 100k.
    quads += [(URIRef(f"urn:inttest:edgetype:bare_{i}"), URIRef(f"{VC}vitaltype"),
               URIRef(f"{H}KGEntity"), URIRef(G)) for i in range(BARE)]
    await space_impl.add_rdf_quads_batch(space, quads)
    for batch in extra:                    # each its own write, in order
        await space_impl.add_rdf_quads_batch(space, batch)
    await recompute_stats_tables(pg_conn, space)
    invalidate_stats_cache(space)
    return space


async def _generate(space, pg_pool, query=None):
    import httpx
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from .conftest import SIDECAR_URL
    async with httpx.AsyncClient(base_url=SIDECAR_URL, timeout=10.0) as client:
        resp = await client.post("/v1/sparql/compile", json={"sparql": query or QUERY})
        resp.raise_for_status()
    cr = map_compile_response(resp.json())
    async with pg_pool.acquire() as conn:
        return await generate_sql(cr, space, conn=conn)


async def _count(gen, pg_conn):
    async with pg_conn.transaction():
        if gen.work_mem_kb:
            await pg_conn.execute(f"SET LOCAL work_mem = '{gen.work_mem_kb}kB'")
        return int((await pg_conn.fetch(gen.sql))[0][0])


def _fired(gen):
    return "absorb_edge_types" in gen.plan_decisions.get("fired", [])


async def _marked(pg_conn, space):
    from vitalgraph.db.sparql_sql.sync_edge_table import edge_types_marked
    return (await edge_types_marked(pg_conn, space))[0]


async def test_a_new_space_reads_edge_types_off_the_column_with_the_same_count(
        make_space, space_impl, pg_conn, pg_pool, monkeypatch):
    from vitalgraph.db.sparql_sql import sync_edge_table as se
    space = await _setup(make_space, space_impl, pg_conn)
    assert await _marked(pg_conn, space)

    gen = await _generate(space, pg_pool)
    assert _fired(gen), gen.plan_decisions
    assert "edge_type_uuid =" in gen.sql
    assert gen.edge_types_guard is not None and gen.edge_types_guard[0] == space
    absorbed = await _count(gen, pg_conn)

    async def _no(conn, space_id):
        return False, None
    monkeypatch.setattr(se, "edge_types_marked", _no)
    plain = await _generate(space, pg_pool)
    assert not _fired(plain)
    assert absorbed == await _count(plain, pg_conn) == EXPECTED


async def test_an_edge_typed_after_its_endpoints_gets_its_type(
        make_space, space_impl, pg_conn, pg_pool):
    """`DO NOTHING` left such an edge NULL; the write path now keeps it in step."""
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    late, g = URIRef("urn:inttest:edgetype:late"), URIRef(G)
    extra = ([(late, URIRef(f"{VC}hasEdgeSource"), URIRef("urn:inttest:edgetype:f0_10"), g),
              (late, URIRef(f"{VC}hasEdgeDestination"), URIRef("urn:inttest:edgetype:fX"), g)],
             [(late, URIRef(f"{VC}vitaltype"), URIRef(f"{H}Edge_hasKGFrame"), g)])
    space = await _setup(make_space, space_impl, pg_conn, extra)
    p = space_prefix(space)
    typed = await pg_conn.fetchval(
        f"SELECT t.term_text FROM {p}_edge e JOIN {p}_term t ON t.term_uuid = e.edge_type_uuid "
        f"JOIN {p}_term s ON s.term_uuid = e.edge_uuid WHERE s.term_text = $1", str(late))
    assert typed == f"{H}Edge_hasKGFrame"
    assert await _marked(pg_conn, space)
    gen = await _generate(space, pg_pool)
    assert _fired(gen)
    assert await _count(gen, pg_conn) == EXPECTED


async def test_an_update_that_retypes_an_edge_unmarks_until_reconciled(
        make_space, space_impl, pg_conn, pg_pool):
    """The update's edge sync runs after it, so the update unmarks the space
    in its own transaction. Retyping one slot edge drops its lead from the
    count; the answer is right throughout."""
    from vitalgraph.db.sparql_sql.sync_edge_table import reconcile_edge_types
    space = await _setup(make_space, space_impl, pg_conn)
    se1 = "urn:inttest:edgetype:se_1"           # i = 1: a counted lead
    ok = await space_impl.execute_sparql_update(
        space,
        f"DELETE {{ GRAPH <{G}> {{ <{se1}> <{VC}vitaltype> <{H}Edge_hasKGSlot> }} }} "
        f"INSERT {{ GRAPH <{G}> {{ <{se1}> <{VC}vitaltype> <{H}Edge_hasKGFrame> }} }} "
        f"WHERE {{ GRAPH <{G}> {{ <{se1}> <{VC}vitaltype> <{H}Edge_hasKGSlot> }} }}")
    assert ok is not False
    assert not await _marked(pg_conn, space)

    gen = await _generate(space, pg_pool)
    assert not _fired(gen)
    assert await _count(gen, pg_conn) == EXPECTED - 1

    out = await reconcile_edge_types(pg_conn, space)
    assert out["marked"] is True
    gen = await _generate(space, pg_pool)
    assert _fired(gen)
    assert await _count(gen, pg_conn) == EXPECTED - 1


async def test_an_unmarked_space_keeps_the_quad_checks_until_reconciled(
        make_space, space_impl, pg_conn, pg_pool):
    """A space from before this (no marker row) is left to the migration."""
    from vitalgraph.db.sparql_sql.sync_edge_table import (
        EDGE_TYPES_TABLE, reconcile_edge_types)
    space = await _setup(make_space, space_impl, pg_conn)
    await pg_conn.execute(f"DELETE FROM {EDGE_TYPES_TABLE} WHERE space_id = $1", space)
    gen = await _generate(space, pg_pool)
    assert not _fired(gen)
    assert await _count(gen, pg_conn) == EXPECTED
    out = await reconcile_edge_types(pg_conn, space)
    assert out == {"fixed": 0, "marked": True}
    assert _fired(await _generate(space, pg_pool))


async def test_a_page_keeps_the_quad_checks(make_space, space_impl, pg_conn, pg_pool):
    """Under a LIMIT the column test made PostgreSQL drive the edge from its
    type index and lose the early sort that stops at the page
    (`rating_990_edge_page` on lead 100k: 18 -> 114 ms), so a page is left as
    it was."""
    space = await _setup(make_space, space_impl, pg_conn)
    page = QUERY.replace("SELECT (COUNT(*) AS ?count) WHERE { { SELECT DISTINCT ?entity",
                         "SELECT ?entity WHERE { { SELECT DISTINCT ?entity")
    page = page.rstrip() + " LIMIT 5"
    gen = await _generate(space, pg_pool, page)
    assert not _fired(gen)


async def test_the_executor_rechecks_the_mark_in_the_querys_snapshot(
        make_space, space_impl, pg_conn):
    """Through the server's own executor: a marked space answers with the
    column, and a space dirtied after planning is planned again without it
    (`edge_types_guard`), with the same answer either way."""
    from vitalgraph.db.sparql_sql import generator as G
    from vitalgraph.db.sparql_sql.sync_edge_table import dirty_edge_types
    space = await _setup(make_space, space_impl, pg_conn)

    def count(res):
        b = res["results"]["bindings"]
        return int(b[0]["count"]["value"])
    assert count(await space_impl.execute_sparql_query(space, QUERY)) == EXPECTED

    real = G.generate_sql
    seen = []

    async def dirty_after_planning(*a, **k):
        gen = await real(*a, **k)
        seen.append(gen.edge_types_guard)
        if gen.edge_types_guard:                    # the mark moves before execution
            await dirty_edge_types(pg_conn, space)
        return gen
    import vitalgraph.db.sparql_sql.sparql_sql_space_impl as impl_mod
    orig = getattr(impl_mod, "generate_sql", None)
    G.generate_sql = dirty_after_planning
    if orig is not None:
        impl_mod.generate_sql = dirty_after_planning
    try:
        assert count(await space_impl.execute_sparql_query(space, QUERY)) == EXPECTED
    finally:
        G.generate_sql = real
        if orig is not None:
            impl_mod.generate_sql = orig
    assert seen and seen[0] is not None, "the first plan read the column"
    assert seen[-1] is None, "the re-plan after the mark moved does not"
