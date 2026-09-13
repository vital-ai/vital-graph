"""General traversal: node -edge-> node, with no frames and no slots anywhere.

    ?e0 -Edge_hasKGRelation-> ?e1 -Edge_hasKGRelation-> ?e2 -...-> ?e3

The frame shape has a lot of coverage and this one had almost none: three test
functions, no depth-3 chain, and NO criterion coverage at all. That gap is not
cosmetic. `frame_entity` was retired for `frame_slot` and the chain detector
stopped recognising frame walks entirely (`issues/197`), which killed the
set-based emission for them silently. The general shape rides on `{space}_edge`,
a different table and a different entry in `_TRAVERSAL_KINDS`, so it can break —
or stay working — completely independently, and nothing was watching.

WHY THE CRITERIA ARE DEFINED SEPARATELY. `graph_fixtures.CRITERIA` cannot be
used here: every entry binds `?f{n}`, the FRAME variable, which `relation_hop`
never introduces. Pairing them leaves it unbound, the query becomes a cross
product, and the result looks like a criterion that simply matched nothing.
`RELATION_CRITERIA` binds `?r{n}` (the edge) or the hop's destination node.

WHY THE CRITERION TESTS AGGREGATE OVER STARTS. The frame criteria each name a
precomputed walk in the manifest; these have none. So they are asserted
differentially — a filtered walk must be a subset of the open walk from the SAME
start, which needs no ground truth. Non-emptiness is asserted over ALL sample
starts together because single starts are legitimately degenerate: entity 45's
three edges score 3, 17 and 11, so `score >= 50` correctly returns nothing
there. Scores are lognormal(mu=2.9), NOT the "uniform [0,100)" that
`criteria_predicates` claims — `value_distributions` in the same manifest is the
accurate field — so ~10% of edges pass 50, not half.
"""
from __future__ import annotations

import pytest

from .conftest import skip_no_pg
from .graph_fixtures import (
    SMALL, RELATION_CRITERIA, chain_query, relation_hop)
from .test_graph_traversal_fixture import _require, _run

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

DEPTHS = [1, 2, 3]


def _hub(fx):
    """The sample start with the widest depth-3 reach."""
    walks = fx.manifest()["traversal"]["relation_traversal"]
    return max(fx.sample_starts(), key=lambda s: len(walks[str(s)]["3"]))


@pytest.mark.parametrize("depth", DEPTHS)
async def test_the_open_walk_matches_the_manifest(perf_conn, depth):
    """Every sample start, not just one: a walk that is right from a hub and
    wrong from a leaf is a bug this would otherwise report as a pass."""
    fx = SMALL
    await _require(perf_conn, fx)
    for start in fx.sample_starts():
        got, _ = await _run(perf_conn, fx,
                            chain_query(fx, start, depth, hop=relation_hop))
        assert got == fx.expected("relation_traversal", start, depth), (
            f"depth {depth} from entity {start} disagrees with the manifest")


@pytest.mark.parametrize("depth", [2, 3])
async def test_a_multi_hop_walk_takes_the_set_based_path(perf_conn, depth):
    """The emission that vanished for frames must not vanish here.

    `emit_dedup_chain` produces `AS MATERIALIZED` CTEs, one per hop, and it is
    reached only when the detector links a chain. When `_TRAVERSAL_KINDS` lost
    the frame table, `_try_hop_wise` returned before the dedup attempt and
    nothing was logged, because there was no decline to record — the whole
    optimisation disappeared in silence. This asserts the general shape still
    gets it.

    Depth 1 is excluded deliberately: dedup declines a single hop as too
    shallow, so asserting it there would pin the wrong behaviour.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    _got, sql = await _run(perf_conn, fx,
                           chain_query(fx, _hub(fx), depth, hop=relation_hop))
    assert "MATERIALIZED" in sql, (
        f"a depth-{depth} general traversal did not take the set-based path — "
        f"the chain detector is not linking {{space}}_edge hops")


@pytest.mark.parametrize("name", sorted(RELATION_CRITERIA))
async def test_a_criterion_never_admits_a_row_the_open_walk_excludes(
        perf_conn, name):
    """Subset per start, and narrowing in aggregate.

    The subset check is the correctness one and holds at every start. The
    aggregate is what proves the criterion is WIRED — an unbound variable or a
    dropped FILTER shows up as a walk that narrowed nothing, and comparing
    totals catches it without needing a precomputed answer.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    criterion = RELATION_CRITERIA[name]
    total_open = total_filtered = 0
    for start in fx.sample_starts():
        open_set, _ = await _run(perf_conn, fx,
                                 chain_query(fx, start, 1, hop=relation_hop))
        got, _ = await _run(perf_conn, fx,
                            chain_query(fx, start, 1, hop=relation_hop,
                                        criterion=criterion))
        assert got <= open_set, (
            f"{name} from entity {start} returned entities the open walk does "
            f"not reach: {sorted(got - open_set)[:5]}")
        total_open += len(open_set)
        total_filtered += len(got)

    assert total_filtered, (
        f"{name} matched nothing from any of the {len(fx.sample_starts())} "
        f"sample starts — the criterion is not selecting, or its variable is "
        f"unbound and the query is a cross product")
    assert total_filtered < total_open, (
        f"{name} admitted every reachable node ({total_filtered} of "
        f"{total_open}), so it is not constraining anything")


async def test_an_edge_criterion_survives_two_hops(perf_conn):
    """A criterion on the EDGE, applied at BOTH hops.

    The multi-hop case is its own risk: the criterion is numbered per hop, and a
    template that binds one variable for every hop returns empty for a reason
    that has nothing to do with the data. `edge_type_is_Knows` is used because
    it is the one criterion with enough density to stay non-empty at depth 2 —
    score and weight are both skewed low, and requiring either at both hops
    leaves nothing on this fixture.
    """
    fx = SMALL
    await _require(perf_conn, fx)
    criterion = RELATION_CRITERIA["edge_type_is_Knows"]
    total_open = total_filtered = 0
    for start in fx.sample_starts():
        open_set, _ = await _run(perf_conn, fx,
                                 chain_query(fx, start, 2, hop=relation_hop))
        got, _ = await _run(perf_conn, fx,
                            chain_query(fx, start, 2, hop=relation_hop,
                                        criterion=criterion))
        assert got <= open_set, f"two-hop Knows from {start} left the open walk"
        total_open += len(open_set)
        total_filtered += len(got)
    assert total_filtered, (
        "no two-hop walk survived a Knows-at-every-hop criterion; if the "
        "fixture changed, check the per-hop numbering before the data")
    assert total_filtered < total_open
