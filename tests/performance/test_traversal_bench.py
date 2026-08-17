"""Traversal benches — the shapes the hop-wise gate decides between.

WHY THIS EXISTS, stated plainly: on 2026-08-17 a change that made filtered
traversals **6.2x slower** was written, tested and committed with the entire
suite green. Nothing caught it because none of the 105 benches in the baseline
touched traversal at all. It was found by measuring by hand, which is not a
process. The 3.7x/4.6x improvement that replaced it had nothing guarding it
either.

`shared_buffers` is the gate here, not wall-clock. It is deterministic on a
pinned fixture, `thresholds.toml` fails it at +15%, and every regression in this
area has shown up as buffers first: 17,237 -> 106,040 for the fenced form,
2.6M -> 8.1M on the large fixture. Wall-clock on the same runs straddled — three
repetitions of one case gave 2,902/3,158 ms against 2,614/3,305 ms — so timing
would have reported nothing while the buffer count reported 6.2x.

THE SHAPES, and what each one is here to catch:

    pinned drive          hop-wise, driving from one uri. 33x better than flat,
                          the case that justified the whole rewrite
    constrained + hoist   hop-wise, driving from a kind-constrained end. 3.7x on
                          the head, 4.6x through the reversal on the tail. Needs
                          the constraint HOISTED out of the criteria fence;
                          fenced it was the 6.2x regression
    constrained, common   the same shape on a 20%-of-entities end, where hoisted
                          and flat are at parity. Here so that "make the rare
                          case fast" cannot quietly cost the common one
    set-based dedup       a DISTINCT above the walk collapses each hop to an
                          entity set — 35x on wordnet depth 3, and it runs
                          whatever the hop-wise gate decided, so it needs its own
                          bench or a regression in it hides behind the others
    unfiltered walk       must NOT go hop-wise. An unfiltered depth-3 walk
                          measured 865 ms flat against 2,044 ms hop-wise, which
                          is why `decide` requires a measured criterion. A change
                          that loosens that gate shows up here as a regression
                          rather than as a mystery months later

Each bench also asserts the SHAPE it measured — fenced or flat — because a
number recorded against the wrong plan is worse than no number: it makes a
silent decline look like an improvement.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg, space_exists
from .graph_fixtures import (CRITERIA, SKEW, chain_query,
                             kind_constrained_query)
from .harness import explain_json, total_shared_buffers

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

RARE, COMMON = "Rare", "Person"
SCORE = CRITERIA["score_gte_50"][0]

# Starts with a NON-EMPTY answer at the depth each bench walks. A pinned bench on
# a dead-end start measures an early exit — fast for a reason that has nothing to
# do with the plan under test, and stable, so it looks like a healthy bench
# forever. The first version of this file used one start for both depths and the
# depth-3 bench recorded 0 rows and 478 buffers, which is exactly that trap.
#
# The fixture's `sample_starts` are chosen rather than drawn uniformly, for the
# same reason: at ~50% selectivity a random start usually reaches nothing by
# depth 3.
PINNED_START_D2 = 42        # 1 row at depth 2 with score >= 50
PINNED_START_D3 = 1992      # 17 rows at depth 3 with score >= 50


async def _require(conn):
    if not SKEW.available:
        pytest.skip(f"{SKEW.manifest_path} not generated — see graph_fixtures")
    if not await space_exists(conn, SKEW.space):
        pytest.skip(f"space {SKEW.space} not loaded")


async def _sql(conn, sparql):
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


def _shape(sql: str) -> str:
    """Which of the THREE traversal emissions this is.

    Naming only two of them is how the first version of this file failed: a
    pinned walk with DISTINCT takes neither the flat nor the hop-wise path but
    `emit_dedup_chain`, worth 35x on `wordnet_frames` depth 3 and — like the
    other two before today — carrying no bench at all.

        dedup     a chain of `dN AS MATERIALIZED` CTEs, one entity SET per hop
        hop-wise  nested laterals with the `OFFSET 0` criteria fence
        flat      the plan every rewrite declines back to
    """
    if "d0 AS MATERIALIZED" in sql:
        return "dedup"
    return "hop-wise" if "OFFSET 0\n)" in sql else "flat"


async def _measure(conn, gen, *, shape: str):
    """Buffers and rows for one plan, with the emission asserted first.

    Shape before number: a decline emits the flat plan, which is correct and
    slower, and recording its buffers under a hop-wise bench id would show a
    regression as an improvement the moment the two plans swap.
    """
    got = _shape(gen.sql)
    assert got == shape, (
        f"expected the {shape} emission and got {got}; this bench would be "
        f"measuring a different plan than its name says. Decision: "
        f"{getattr(gen, 'traversal_decision', None)}")
    rows = await conn.fetch(gen.sql)
    plan = await explain_json(conn, gen.sql)
    return total_shared_buffers(plan), len(rows), plan


class TestDrivenFromAPin:
    """Hop-wise with a pinned end — the case the rewrite was built for."""

    @pytest.mark.bench("traversal.skew2k.pinned.depth2")
    async def test_pinned_depth_2(self, perf_conn, perf_record):
        await _require(perf_conn)
        gen = await _sql(perf_conn, chain_query(
            SKEW, PINNED_START_D2, 2, criterion=SCORE, distinct=False))
        buffers, rows, plan = await _measure(perf_conn, gen, shape="hop-wise")
        perf_record(plan=plan, dataset=SKEW.space,
                    metrics={"rows": rows},
                    notes="pinned start, score>=50, hop-wise (issues/090)")
        assert rows > 0, "the pinned start reaches nothing, so this measures an "\
                         "early exit rather than a traversal"
        assert buffers > 0


class TestTheSetBasedChain:
    """The third emission, and the one nothing measured either.

    A DISTINCT above the traversal lets `dedup_feasible` collapse each hop to an
    entity SET, which was 35x on `wordnet_frames` depth 3 — 2,129 ms to 61 ms.
    It runs regardless of what the hop-wise gate decided, so without a bench of
    its own a regression here would be invisible in every other case in this
    file.
    """

    @pytest.mark.bench("traversal.skew2k.dedup.depth3")
    async def test_dedup_depth_3(self, perf_conn, perf_record):
        await _require(perf_conn)
        gen = await _sql(perf_conn, chain_query(
            SKEW, PINNED_START_D3, 3, criterion=SCORE))
        buffers, rows, plan = await _measure(perf_conn, gen, shape="dedup")
        perf_record(plan=plan, dataset=SKEW.space, metrics={"rows": rows},
                    notes="DISTINCT above a depth-3 walk — set-based emission")
        assert rows > 0, ("the start reaches nothing at depth 3, so this "
                          "measures an early exit rather than a traversal")


class TestDrivenFromAConstrainedEnd:
    """The hoist. Fenced, these were 2.5-6.3x WORSE than flat; hoisted, the rare
    end is 3.7x better and the common one is at parity."""

    @pytest.mark.bench("traversal.skew2k.constrained_rare_head.depth2")
    async def test_rare_head(self, perf_conn, perf_record):
        await _require(perf_conn)
        gen = await _sql(perf_conn, kind_constrained_query(
            SKEW, 2, "head", RARE, criterion=SCORE))
        buffers, rows, plan = await _measure(perf_conn, gen, shape="hop-wise")
        perf_record(plan=plan, dataset=SKEW.space, metrics={"rows": rows},
                    notes="40-entity kind on the head, hoisted (issues/090)")
        assert rows > 0

    @pytest.mark.bench("traversal.skew2k.constrained_rare_tail.depth2")
    async def test_rare_tail(self, perf_conn, perf_record):
        """The reversal: the gate flips the chain, then the same hoist applies.
        This is the only bench covering `TraversalChain.reversed`."""
        await _require(perf_conn)
        gen = await _sql(perf_conn, kind_constrained_query(
            SKEW, 2, "tail", RARE, criterion=SCORE))
        buffers, rows, plan = await _measure(perf_conn, gen, shape="hop-wise")
        perf_record(plan=plan, dataset=SKEW.space, metrics={"rows": rows},
                    notes="40-entity kind on the tail, reversed + hoisted")
        assert rows > 0

    @pytest.mark.bench("traversal.skew2k.constrained_common_head.depth2")
    async def test_common_head(self, perf_conn, perf_record):
        """Parity today. Here because "make the rare end fast" must not be paid
        for by the common one, and nothing else would notice if it were."""
        await _require(perf_conn)
        gen = await _sql(perf_conn, kind_constrained_query(
            SKEW, 2, "head", COMMON, criterion=SCORE))
        buffers, rows, plan = await _measure(perf_conn, gen, shape="hop-wise")
        perf_record(plan=plan, dataset=SKEW.space, metrics={"rows": rows},
                    notes="394-entity kind on the head, hoisted — parity case")
        assert rows > 0


class TestTheUnfilteredWalkStaysFlat:
    """The gate's other half, and the one with no advocate.

    Every bench above rewards hop-wise firing, so a change that makes it fire
    MORE looks like an improvement everywhere. An unfiltered depth-3 walk
    measured 865 ms flat against 2,044 ms hop-wise — this is where loosening the
    criterion requirement shows up as the regression it is.
    """

    @pytest.mark.bench("traversal.skew2k.unfiltered.depth3")
    async def test_unfiltered_depth_3_is_not_hop_wise(self, perf_conn, perf_record):
        await _require(perf_conn)
        gen = await _sql(perf_conn, chain_query(
            SKEW, PINNED_START_D3, 3, distinct=False))
        buffers, rows, plan = await _measure(perf_conn, gen, shape="flat")
        perf_record(plan=plan, dataset=SKEW.space, metrics={"rows": rows},
                    notes="no criterion — must stay flat (traversal_decision)")
        decision = getattr(gen, "traversal_decision", None)
        assert decision is None or not decision.hop_wise, (
            f"an unfiltered walk was sent hop-wise: {decision}")
        assert rows > 0, ("the start reaches nothing, so this measures an early "
                          "exit rather than the fan-out it exists to price")
