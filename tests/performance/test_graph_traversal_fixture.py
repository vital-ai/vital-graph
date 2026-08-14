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
    SMALL, CRITERIA, HALEY, VITAL, chain_query, frame_hop, relation_hop,
    entity_indexes)

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


# ---------------------------------------------------------------------------
# The multi-valued criterion
# ---------------------------------------------------------------------------

async def test_a_multi_valued_criterion_estimates_quads_not_subjects(perf_conn):
    """`rdf_stats.row_count` counts QUADS, so an `IN` sum over a multi-valued
    predicate exceeds the number of matching SUBJECTS.

    Every other criterion predicate in this fixture is single-valued, where the
    two are identical and the difference cannot be observed — which is why
    `hasTag` exists. It carries one to four values per edge, so the gap is real
    and measurable rather than argued about.

    Asserted in the direction that matters: the estimate must equal the quad
    count exactly (it is a stored sum, not an approximation) AND must be shown
    to differ from the subject count, so nobody later mistakes it for a count of
    matching frames. The error direction is "looks less selective than it is",
    which is conservative for choosing a plan shape and wrong for ranking two
    criteria against each other.
    """
    from .graph_fixtures import TAG
    fx = SMALL
    await _require(perf_conn, fx)
    S = fx.space

    tag_pred = await perf_conn.fetchval(
        f"SELECT term_uuid FROM {S}_term WHERE term_text = $1", TAG)
    if tag_pred is None:
        pytest.skip("fixture predates the multi-valued tag criterion; regenerate")

    quads = await perf_conn.fetchval(
        f"SELECT count(*) FROM {S}_rdf_quad WHERE predicate_uuid = $1", tag_pred)
    subjects = await perf_conn.fetchval(
        f"SELECT count(DISTINCT subject_uuid) FROM {S}_rdf_quad "
        f"WHERE predicate_uuid = $1", tag_pred)
    assert quads > subjects, (
        f"hasTag is not multi-valued in this fixture ({quads} quads over "
        f"{subjects} subjects) — the case this test exists for is not present")

    pair = [fx.tag_uri("urgent"), fx.tag_uri("review")]
    in_quads = await perf_conn.fetchval(
        f"SELECT count(*) FROM {S}_rdf_quad q JOIN {S}_term t "
        f"ON t.term_uuid = q.object_uuid "
        f"WHERE q.predicate_uuid = $1 AND t.term_text = ANY($2::text[])",
        tag_pred, pair)
    in_subjects = await perf_conn.fetchval(
        f"SELECT count(DISTINCT q.subject_uuid) FROM {S}_rdf_quad q "
        f"JOIN {S}_term t ON t.term_uuid = q.object_uuid "
        f"WHERE q.predicate_uuid = $1 AND t.term_text = ANY($2::text[])",
        tag_pred, pair)

    # What the estimator would report: the stored per-(predicate, object) sum.
    estimate = await perf_conn.fetchval(
        f"SELECT COALESCE(sum(s.row_count), 0)::bigint FROM {S}_term t "
        f"JOIN {S}_rdf_stats s ON s.object_uuid = t.term_uuid "
        f" AND s.predicate_uuid = $1 "
        f"WHERE t.term_text = ANY($2::text[])", tag_pred, pair)

    assert estimate == in_quads, (
        f"the estimate ({estimate}) should be the exact QUAD count "
        f"({in_quads}) — it is a stored sum, not an approximation")
    assert in_quads > in_subjects, (
        "the chosen tags never co-occur on one subject, so this asserts "
        "nothing; pick a pair that does")
    assert estimate > in_subjects, (
        f"estimate {estimate} vs {in_subjects} matching subjects: the "
        f"overcount is the documented behaviour, and it being ABSENT would "
        f"mean the counting semantics changed")


async def test_the_fixture_has_hub_structure(perf_conn):
    """Guards the fixture's TOPOLOGY, which is what the criterion gate needs.

    `traversal_decision` refuses hop-wise emission for a walk with no measured
    criterion, because an unfiltered walk fans out and a nested-loop plan loses.
    That gate was calibrated on `wordnet_frames` alone for one reason: every
    open traversal on graph_synth reached 4, 16 and 64 entities at depths 1-3.
    A fixture that cannot fan out cannot exercise the gate, and nothing noticed
    because every correctness test still passed.

    Two generator defects caused it — sample starts seeded by IN-degree where a
    forward walk fans out by OUT-degree, and an out-degree cap fixed at 200
    while the in-degree cap already scaled with the dataset. This asserts on the
    outcome rather than on either fix, so it stays honest if the generator
    changes again.

    The thresholds are deliberately far below what the generator now produces
    (max out-degree 200 at 10k, open depth-3 reach in the hundreds), so ordinary
    variation between seeds does not trip it.
    """
    fx = SMALL
    await _require(perf_conn, fx)

    top_out = await perf_conn.fetchval(
        f"SELECT max(n) FROM (SELECT count(DISTINCT dest_entity_uuid) n "
        f"FROM {fx.space}_frame_entity GROUP BY source_entity_uuid) d")
    assert top_out >= 25, (
        f"largest out-degree is {top_out}: the graph has no hubs, so a forward "
        f"traversal cannot fan out and the criterion gate is untestable here")

    walks = fx.manifest()["traversal"]["frame_traversal"]
    best = max(len(walks[str(s)]["3"]) for s in fx.sample_starts())
    assert best >= 100, (
        f"the widest open depth-3 walk from any sample start reaches {best} "
        f"entities. Sample starts must SPAN the degree distribution — seeding "
        f"them by in-degree picks a fan-IN hub, which a forward walk does not "
        f"exercise")


# `vitaltype` rather than `a` (rdf:type): the column holds vitaltype, and it is
# what the product queries with — `kgframes_endpoint` emits
# `<frame> vital-core:vitaltype <KGFrame>`. The fixture helpers use `a`, which
# makes them the unrepresentative ones for this particular check.
_VT = "http://vital.ai/ontology/vital-core#vitaltype"


def _typed_hop_query(fx, start, frame_type):
    """A one-hop walk whose frame is constrained by vitaltype."""
    from .graph_fixtures import HALEY, VITAL, SRC_ROLE, DST_ROLE
    return f"""
    SELECT DISTINCT ?e1 WHERE {{ GRAPH <{fx.graph}> {{
        ?f1 <{_VT}> <{frame_type}> .
        ?se1 <{VITAL}hasEdgeSource> ?f1 .
        ?se1 <{VITAL}hasEdgeDestination> ?ss1 .
        ?ss1 <{HALEY}hasKGSlotType> <{SRC_ROLE}> .
        ?ss1 <{HALEY}hasEntitySlotValue> ?e0 .
        ?de1 <{VITAL}hasEdgeSource> ?f1 .
        ?de1 <{VITAL}hasEdgeDestination> ?ds1 .
        ?ds1 <{HALEY}hasKGSlotType> <{DST_ROLE}> .
        ?ds1 <{HALEY}hasEntitySlotValue> ?e1 .
        FILTER(?e0 = <{fx.entity_uri(start)}>)
    }} }}"""


async def test_a_vitaltype_constraint_is_absorbed_into_the_column(perf_conn):
    """`<frame> vitaltype <Type>` becomes a `frame_type_uuid` predicate.

    The whole point of the column: on wordnet_frames at depth 3 the type probe
    was 79% of all buffers, run once per output row. Absorbing it measured
    48.1 ms -> 20.3 ms on the identical query.

    Asserts the SQL, not the timing — whether the rewrite FIRED is invisible in
    results, and a rewrite that silently stops firing is correct-but-slow, which
    is how this whole area has gone wrong repeatedly.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    start = fx.sample_starts()[0]
    got, sql = await _run(perf_conn, fx,
                          _typed_hop_query(fx, start, f"{HALEY}KGFrame"))
    assert "frame_type_uuid" in sql, (
        "the vitaltype triple was not absorbed into frame_entity.frame_type_uuid "
        "— the rewrite is declining, which is slower and invisible in results")
    assert got == fx.expected("frame_traversal", start, 1)


async def test_a_type_that_matches_nothing_returns_nothing(perf_conn):
    """The test the absorption actually needs, and the one the fixtures cannot
    provide on their own.

    Every frame in both fixtures IS a KGFrame, so a type constraint is a
    tautology here and DROPPING it returns exactly the right answer. A first
    version of the absorption did precisely that — the rewrite removed the quad
    table and the filter went with it — and every differential still passed.

    Constraining on a type nothing has is the only cheap way to tell "absorbed"
    from "lost": it must return zero rows.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    start = fx.sample_starts()[0]
    got, sql = await _run(
        perf_conn, fx,
        _typed_hop_query(fx, start, f"{HALEY}NoSuchFrameTypeXYZ"))
    assert "frame_type_uuid" in sql, "absorption did not fire for this shape"
    assert got == set(), (
        f"a vitaltype that matches no frame returned {len(got)} entities — the "
        f"type filter was LOST in the rewrite, not absorbed")
