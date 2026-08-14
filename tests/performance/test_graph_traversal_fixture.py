"""The traversal fixture answers what its manifest says it answers.

Every bench built on `graph_synth` asserts against manifest numbers, so the
manifest has to be right. It is produced by a BFS in the generator over the same
edge list the N-Triples are rendered from; this checks that walk against what
the SQL pipeline returns for the same question.

Two independent implementations of "reachable at exactly depth N" agreeing is
the point. If they diverge, one of them is wrong and neither the benches nor the
correctness tests downstream mean anything — which is worth catching here rather
than as a puzzling bench result later.

Filtered walks matter more than open ones. An open traversal is rarely the
question, and a filtered one is where a query can silently return a SUBSET and
still look like a plausible answer. So each criterion datatype is checked
against the answers computed for that same filter.

Skips cleanly when the fixture has not been generated and loaded — see
`graph_fixtures` for how.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg, space_exists
from .graph_fixtures import (
    SMALL, CRITERIA, chain_query, frame_hop, relation_hop, entity_indexes)

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

DEPTHS = [1, 2, 3]


async def _require(conn, fx):
    if not fx.available:
        pytest.skip(f"{fx.manifest_path} not generated")
    if not await space_exists(conn, fx.space):
        pytest.skip(f"space {fx.space} not loaded")


async def _run(conn, fx, sparql):
    """Generate SQL the way the server does and return the entity indexes."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from .test_kgquery_growth_curve import SIDECAR_URL

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    assert cr.ok, f"SPARQL failed to compile: {cr.error}\n{sparql}"
    gen = await generate_sql(cr, fx.space, conn=conn)
    return entity_indexes(await conn.fetch(gen.sql)), gen.sql


@pytest.mark.parametrize("depth", DEPTHS)
async def test_open_frame_traversal_matches_the_manifest(perf_conn, depth):
    """entity -> frame -> entity, no criterion, at exactly this depth."""
    fx = SMALL
    await _require(perf_conn, fx)
    checked = 0
    for start in fx.sample_starts()[:4]:
        expected = fx.expected("frame_traversal", start, depth)
        got, _sql = await _run(perf_conn, fx, chain_query(fx, start, depth))
        assert got == expected, (
            f"depth {depth} from entity {start}: manifest says "
            f"{len(expected)} entities, query returned {len(got)}; "
            f"missing={sorted(expected - got)[:5]} "
            f"extra={sorted(got - expected)[:5]}")
        checked += 1
    assert checked, "no sample starts were checked"


@pytest.mark.parametrize("depth", DEPTHS)
async def test_relation_traversal_matches_the_manifest(perf_conn, depth):
    """entity -> entity over Edge_hasKGRelation — no frame, no slots.

    Kept separate because the two shapes are served by different machinery:
    frame_entity cannot apply here, so this is the edge table's job.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    for start in fx.sample_starts()[:4]:
        expected = fx.expected("relation_traversal", start, depth)
        got, _sql = await _run(
            perf_conn, fx, chain_query(fx, start, depth, hop=relation_hop))
        assert got == expected, (
            f"relation depth {depth} from {start}: expected {len(expected)}, "
            f"got {len(got)}")


@pytest.mark.parametrize("name", sorted(CRITERIA))
@pytest.mark.parametrize("depth", [2, 3])
async def test_filtered_traversal_matches_the_manifest(perf_conn, name, depth):
    """A criterion on the frame decides which hops are followed.

    One case per datatype — integer threshold, string IN, dateTime range — each
    against the answers computed for that same filter. A criterion silently
    dropped returns the OPEN traversal, which is a superset and therefore looks
    like a working query until it is compared with what it should be.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    criterion, manifest_key = CRITERIA[name]

    for start in fx.sample_starts()[:4]:
        expected = fx.expected(manifest_key, start, depth)
        got, _sql = await _run(
            perf_conn, fx, chain_query(fx, start, depth, criterion=criterion))
        assert got == expected, (
            f"{name} depth {depth} from {start}: expected {len(expected)} "
            f"entities, got {len(got)}; extra={sorted(got - expected)[:5]}")


async def test_a_filter_actually_narrows(perf_conn):
    """Guards the fixture itself.

    If a criterion admitted every hop, the tests above would pass while
    asserting nothing — the filtered answer would equal the open one. The
    generator picks distributions and sample starts to avoid that; this is what
    would notice if it stopped being true.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    start = fx.sample_starts()[0]
    open_set = fx.expected("frame_traversal", start, 3)
    narrowed = [
        fx.expected(key, start, 3)
        for _c, key in CRITERIA.values()
    ]
    assert open_set, "the open traversal reaches nothing — fixture is degenerate"
    assert any(len(n) < len(open_set) for n in narrowed), (
        "no criterion narrowed the depth-3 reachable set, so the filtered "
        "tests are comparing a query against the open answer")


async def test_the_collapse_applies_per_hop(perf_conn):
    """Each hop is its own 6-table group and should become one frame_entity
    join. One join at depth 3 would mean only the first hop collapsed while the
    rest stayed raw quads — a failure that still reads as a working
    optimisation (issues/048)."""
    fx = SMALL
    await _require(perf_conn, fx)
    start = fx.sample_starts()[0]
    for depth in (1, 2, 3):
        _got, sql = await _run(perf_conn, fx, chain_query(fx, start, depth))
        assert sql.count(f"{fx.space}_frame_entity") == depth, (
            f"depth {depth} collapsed "
            f"{sql.count(f'{fx.space}_frame_entity')} hop(s)")
