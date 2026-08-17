"""Which end a traversal is driven from, against real statistics (issues/090).

`tests/unit/sparql_sql/test_traversal_direction.py` tests the decision on made-up
numbers. This tests it on a loaded space, where three things can go wrong that a
unit test cannot see:

  * the statistic the gate reads may not exist, or may be keyed differently from
    the constraint the chain carries. Three separate wiring failures did exactly
    that during development, every one of them failing CLOSED — the gate
    declined, the query stayed correct, and nothing reported a thing;
  * the chain builder may not produce a chain at all for the shape under test;
  * the rewrite may change the answers.

WHY THIS FIXTURE AND NOT THE OTHER TWO

`sp_graph_synth_10k` and `sp_graph_synth_100k` draw their five entity kinds
uniformly, so a kind-constrained end is ~20% of the entity set either way and
"which end is smaller" has no interesting answer. `sp_graph_skew_2k` adds a sixth
kind at 2%. It is small because the question is a distribution, not a size.

WHAT IS NOT ASSERTED HERE, AND WHY

That hop-wise emission is faster. On this shape it is not — a constrained
driving end measured 2.5x to 6.3x WORSE than the flat plan, because the
constraint lands inside the criteria fence and the outer relation stays the whole
link table. `emit_hop_wise` therefore declines a constrained drive, and the
numbers are in the decline's own comment. A test asserting a speedup here would
be asserting something false; a test asserting the decline is asserting the
truth, and will fail the day the hoist lands, which is when it should be reread.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg, space_exists
from .graph_fixtures import HALEY, SKEW, VITAL, kind_uri

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

RARE = "Rare"
COMMON = "Person"


async def _require(conn):
    if not SKEW.available:
        pytest.skip(f"{SKEW.manifest_path} not generated — see graph_fixtures")
    if not await space_exists(conn, SKEW.space):
        pytest.skip(f"space {SKEW.space} not loaded")
    if not SKEW.manifest().get("n_rare_entities"):
        pytest.skip(f"{SKEW.manifest_path} has no rare entities — regenerate "
                    f"with --rare-entity-fraction")


def _hop(n: int, frm: str, to: str) -> str:
    """One entity -> frame -> entity hop, with a criterion on the frame.

    The criterion is not decoration: `decide` requires a MEASURED one, so a
    chain without it never reaches the direction question at all.
    """
    return f"""
        ?f{n} a <{HALEY}KGFrame> .
        ?se{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?se{n} <{VITAL}hasEdgeDestination> ?ss{n} .
        ?ss{n} <{HALEY}hasKGSlotType> <urn:hasSourceEntity> .
        ?ss{n} <{HALEY}hasEntitySlotValue> {frm} .
        ?de{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?de{n} <{VITAL}hasEdgeDestination> ?ds{n} .
        ?ds{n} <{HALEY}hasKGSlotType> <urn:hasDestinationEntity> .
        ?ds{n} <{HALEY}hasEntitySlotValue> {to} .
        ?f{n} <{HALEY}hasScore> ?sc{n} . FILTER(?sc{n} >= 50)"""


def _query(depth: int, end: str, kind: str) -> str:
    body = "".join(_hop(i, f"?e{i}", f"?e{i + 1}") for i in range(depth))
    pinned_var = "?e0" if end == "head" else f"?e{depth}"
    body += f"\n        {pinned_var} <{HALEY}hasKGEntityType> <{kind_uri(kind)}> ."
    return (f"SELECT ?e0 ?e{depth} WHERE {{ GRAPH <{SKEW.graph}> {{{body}\n"
            f"    }} }} ORDER BY ?e0 ?e{depth}")


async def _generate(conn, sparql):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from .test_kgquery_growth_curve import SIDECAR_URL

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        cr = map_compile_response(await client.compile(sparql))
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    assert cr.ok, f"SPARQL failed to compile: {cr.error}\n{sparql}"
    gen = await generate_sql(cr, SKEW.space, conn=conn)
    assert gen.ok, f"SQL generation failed: {gen.error}\n{sparql}"
    return gen


async def _pair_rows(conn, kind: str) -> int:
    """What `rdf_stats` says the kind-constrained end admits."""
    row = await conn.fetchrow(
        f"""SELECT s.row_count FROM {SKEW.space}_rdf_stats s
            JOIN {SKEW.space}_term p ON p.term_uuid = s.predicate_uuid
            JOIN {SKEW.space}_term o ON o.term_uuid = s.object_uuid
            WHERE p.term_text = $1 AND o.term_text = $2""",
        f"{HALEY}hasKGEntityType", kind_uri(kind))
    return row["row_count"] if row else None


class TestTheFixtureCarriesTheSkew:
    """The space, not the manifest. The manifest describing a skew the loaded
    space does not have is how eighteen assertions once failed for a reason
    nowhere near where they failed (issues/099)."""

    async def test_the_rare_kind_is_rare_in_the_space(self, perf_conn):
        await _require(perf_conn)
        manifest = SKEW.manifest()
        rows = await perf_conn.fetch(
            f"""SELECT count(*) AS n FROM {SKEW.space}_rdf_quad q
                JOIN {SKEW.space}_term p ON p.term_uuid = q.predicate_uuid
                JOIN {SKEW.space}_term o ON o.term_uuid = q.object_uuid
                WHERE p.term_text = $1 AND o.term_text = $2""",
            f"{HALEY}hasKGEntityType", kind_uri(RARE))
        assert rows[0]["n"] == manifest["n_rare_entities"], (
            f"space holds {rows[0]['n']} rare entities, manifest says "
            f"{manifest['n_rare_entities']} — is {SKEW.space} loaded from THIS "
            f"manifest's data, and in the cluster this suite reads?")

    async def test_the_rare_kind_is_priced_far_below_a_common_one(self, perf_conn):
        """The whole point of the fixture, read from the statistics the gate
        reads — not from the data, and not from the manifest."""
        await _require(perf_conn)
        rare, common = (await _pair_rows(perf_conn, RARE),
                        await _pair_rows(perf_conn, COMMON))
        assert rare is not None, (
            f"no rdf_stats row for hasKGEntityType={kind_uri(RARE)}. The gate "
            f"prices ends from this table; with no row it declines silently.")
        assert common is not None
        assert rare * 5 < common, (
            f"rare={rare} common={common} — not skewed enough for the "
            f"direction to be a real choice")


class TestTheGateReadsRealStatistics:

    async def test_the_query_reaches_the_gate_at_all(self, perf_conn):
        """Before asserting WHAT it decided, that it decided.

        `decide` needs a chain AND a measured criterion. If either goes missing
        — a rewrite that stops producing a chain for this shape, a criterion the
        stats no longer cover — every direction assertion below would pass by
        never running, which is the failure mode this whole suite exists to
        avoid.
        """
        await _require(perf_conn)
        gen = await _generate(perf_conn, _query(2, "head", RARE))
        assert gen.traversal_decision is not None, (
            "no traversal decision for a two-hop filtered walk — the chain "
            "builder or the criterion measurement stopped covering this shape")

    @pytest.mark.parametrize("end", ["head", "tail"])
    async def test_it_drives_from_the_constrained_end(self, perf_conn, end):
        """Whichever end carries the kind, that is the end chosen.

        This is the assertion the unit tests cannot make: it exercises the
        `leaf_terms` -> term-uuid -> `rdf_stats` lookup end to end. Every wiring
        failure found in that path failed CLOSED — the gate declined, the query
        stayed correct, and nothing said a word.
        """
        await _require(perf_conn)
        gen = await _generate(perf_conn, _query(2, end, RARE))
        decision = gen.traversal_decision
        assert decision is not None
        assert decision.direction == end, (
            f"constrained the {end} end and the gate chose "
            f"{decision.direction!r}: {decision.reason}")

    async def test_the_direction_follows_the_data_not_the_query_text(self, perf_conn):
        """The same shape, the same end, a DIFFERENT kind — and still a
        direction, because both kinds are priced. This is what separates a gate
        reading statistics from one keying off where the constraint was typed.
        """
        await _require(perf_conn)
        for kind in (RARE, COMMON):
            gen = await _generate(perf_conn, _query(2, "tail", kind))
            assert gen.traversal_decision.direction == "tail", (
                f"kind={kind}: {gen.traversal_decision.reason}")

    @pytest.mark.parametrize("end", ["head", "tail"])
    async def test_the_rewrite_does_not_change_the_answers(self, perf_conn, end):
        """The only property that must hold no matter what the gate decides.

        A traversal that returns a subset looks exactly like a correct answer,
        which is why this compares against the flat plan rather than eyeballing
        a row count.
        """
        await _require(perf_conn)
        from vitalgraph.db.sparql_sql import traversal_decision as td

        sparql = _query(2, end, RARE)
        gated = await _generate(perf_conn, sparql)

        original = td.decide
        try:
            td.decide = lambda *a, **k: td.Decision(
                hop_wise=False, reason="forced off by the test")
            flat = await _generate(perf_conn, sparql)
        finally:
            td.decide = original

        got = [tuple(r) for r in await perf_conn.fetch(gated.sql)]
        want = [tuple(r) for r in await perf_conn.fetch(flat.sql)]
        assert got == want
        assert want, ("the flat plan returned nothing, so the comparison "
                      "proves nothing — the query or the fixture has drifted")


class TestAConstrainedDriveIsStillDeclined:
    """Delete this when the hoist lands; it records today's limit, not a goal.

    A constrained driving end is priced correctly and then NOT emitted, because
    the constraint lands inside the criteria fence and the outer relation stays
    the whole link table. Measured at depth 2 on this fixture: 108,900 shared
    buffers hop-wise against 17,237 flat, for identical answers.
    """

    async def test_the_emitted_sql_is_the_flat_plan(self, perf_conn):
        await _require(perf_conn)
        gen = await _generate(perf_conn, _query(2, "head", RARE))
        assert "OFFSET 0\n)" not in gen.sql, (
            "hop-wise fired for a constrained driving end. If the hoist has "
            "landed, this class should be deleted and a timing assertion put "
            "in its place — see issues/090.")
