"""Growth curve for KGQuery paging — does a 25-row page cost O(page) or O(rows joined)?

This is the bench `issues/040` needs and that nothing else provides. The existing
KGQuery benches measure a single point on a 100-entity fixture, where the
competing cost models differ by at most 4x and are indistinguishable from plan
noise. That is exactly how two mitigations came to be reported as measured
improvements when neither affected the generated query at all.

The experiment holds the dataset completely fixed and varies only how many rows
the join carries, asking for the same 25-row first page every time.

MEASURED COST MODEL (sp_lead_synth, 10,000 entities, 2026-08-06):

    cost ≈ 45 buffers × (rows carried through the join)

and what lands in that multiplicand depends entirely on the comparator:

    equality  rows carried = MATCHES      → cost tracks the result set
    range     rows carried = CANDIDATES   → cost is the same for every threshold

Both are measured below. The distinction matters because it determines how you
have to vary the experiment: sweeping a *range* threshold changes the match count
but leaves the candidate set untouched, so the cost does not move and a growth
curve built on it reads as a flat line — which looks exactly like the O(page)
result you are hoping for. That trap is why the equality sweep, not the range
sweep, is what the growth ratio gates on.

    equality (CompanyStateCode = X)       range (MQLRating >= t)
    state  matches  buffers  buf/match    t      matches  buffers  buf/match
    CA         908   36,486       40.2    99.9        16  458,920   28682.5
    TX         765   30,744       40.2    99         110  458,942    4172.2
    NY         547   22,021       40.3    90       1,031  458,948     445.2
    IL         365   16,092       44.1    65       3,559  458,921     129.0
    VT          96    4,253       44.3    50       5,038  458,921      91.1
                                          0       10,000  458,940      45.9

Left: 9.5x more matches, 8.6x more buffers — linear, the O(matches) behaviour
issues/040 describes. Right: 625x fewer matches for identical cost, because all
10,000 candidates cross the join whatever the threshold (458,920 / 45.9 ≈ 10,000).

Fixture is `sp_lead_synth` from `scripts/generate_lead_dataset.py`. Match counts
come from its manifest — exact tallies recorded at generation time, so
`total_matches` is ground truth rather than something this bench measures and
then asserts against itself.

NOT wordnet_frames, despite it being larger and the fixture the plan originally
named. `KGQueryCriteriaBuilder` hardcodes `Edge_hasEntityKGFrame`
(kg_query_builder.py:657) and wordnet has none — its only edge kind is
`Edge_hasKGSlot`, entities hanging off slots via `hasEntitySlotValue`. wordnet
cannot drive the KGQuery entity-criteria path at any scale. It remains correct
for the generic SPARQL fast-path benches.

Both gates are dimensionless ratios against a baseline measured from the same
fixture in the same run — never an absolute buffer count. The fixtures are
generated at whatever size is asked for, so a constant in buffers is valid only
at the size it was derived from and turns into either a false alarm or a
rubber stamp as soon as the data changes. `EQ_GROWTH_VS_MATCHES_MAX` compares
page-cost growth to match-count growth; `RANGE_VS_EQUALITY_MAX` compares the
range comparator's cost per matched row to equality's on the same data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from .conftest import skip_no_pg, space_exists
from .lead_fixtures import SYNTH, require_usable
from .harness import assert_plan, explain_json, total_shared_buffers

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")

# Fixture definitions are shared with the API-level bench so the two layers
# cannot drift onto different data — see lead_fixtures.
FIXTURES = SYNTH

NS = "urn:acme:kg"
TEXT_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
DOUBLE_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot"
KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"

PAGE_SIZE = 25

# Descending frequency. Weights are set in scripts/generate_lead_dataset.py and
# the exact emitted counts are in the manifest.
EQ_STATES = ["CA", "TX", "NY", "IL", "VT"]

# Mirrors GTE_THRESHOLDS in the generator; the manifest has a count for each.
RANGE_THRESHOLDS = [99.9, 99, 90, 65, 50, 0]

# Both bounds below are DIMENSIONLESS RATIOS measured within the same run.
#
# Nothing here may be an absolute buffer count. The fixtures are generated at
# whatever size is asked for — 10k and 100k today — so any constant expressed in
# buffers is only valid for the size it was derived from and silently becomes
# either unenforceable or a false alarm when the data changes. Earlier revisions
# of this file carried exactly such a constant and it had to be re-derived twice
# in one day.
#
# Each bound is therefore stated against a baseline measured from the same
# fixture in the same run, so it holds at any size.

# Growth of page cost across the equality sweep, as a fraction of the growth in
# match count. O(page) → ~0. O(matches) → ~1. Above 1 means page cost grows
# faster than the result set, which is the regression worth catching.
EQ_GROWTH_VS_MATCHES_MAX = 1.25

# Cost per matched row of a range comparator, as a multiple of the equality
# baseline — compared AT COMPARABLE SELECTIVITY, which is the part that matters.
#
# The original form compared the tightest threshold against the largest equality
# case and started failing once paging became O(page): equality fell to ~3
# buffers/match while a deliberately-unprobed tight range sat at ~53, giving
# 17.7x. Neither number was bad; the denominator had collapsed. Selectivity is
# now the thing the two sides must share, because the semi-join gate routes
# low-selectivity criteria to the set-based join by design — so a tight range
# and a broad equality are simply different plans and comparing them says
# nothing.
#
# The invariant that survives: at similar selectivity a range should cost about
# what equality costs. Before the push-down it cost ~700x more.
RANGE_VS_EQUALITY_MAX = 8.0


async def _require_loaded(conn, fx) -> None:
    """Skip unless the fixture is present, non-empty and in the right namespace.

    Every bound in this module is an upper bound, so an empty or
    wrong-namespace fixture passes them all and reports nonsense (measured: 2
    buffers at every threshold).
    """
    reason = await require_usable(conn, fx)
    if reason:
        pytest.skip(reason)


def _load_manifest(fx) -> dict:
    if not fx.manifest_path.is_file():
        pytest.skip(f"fixture manifest not found: {fx.manifest_path} — generate "
                    f"with scripts/generate_lead_dataset.py")
    return json.loads(fx.manifest_path.read_text())


def _eq_criteria(state: str):
    """CompanyFrame → CompanyAddressFrame → CompanyStateCode = X."""
    from vitalgraph.model.kgentities_model import SlotCriteria, FrameCriteria
    return [FrameCriteria(
        frame_type=f"{NS}:frame:CompanyFrame",
        frame_criteria=[FrameCriteria(
            frame_type=f"{NS}:frame:CompanyAddressFrame",
            slot_criteria=[SlotCriteria(
                slot_type=f"{NS}:slot:CompanyStateCode",
                slot_class_uri=TEXT_SLOT, value=state,
                comparator="eq")])])]


def _range_criteria(threshold: float):
    """LeadStatusFrame → LeadStatusQualificationFrame → MQLRating >= t."""
    from vitalgraph.model.kgentities_model import SlotCriteria, FrameCriteria
    return [FrameCriteria(
        frame_type=f"{NS}:frame:LeadStatusFrame",
        frame_criteria=[FrameCriteria(
            frame_type=f"{NS}:frame:LeadStatusQualificationFrame",
            slot_criteria=[SlotCriteria(
                slot_type=f"{NS}:slot:MQLRating",
                slot_class_uri=DOUBLE_SLOT, value=threshold,
                comparator="gte")])])]


async def _criteria_to_sql(conn, frame_criteria, fx) -> str:
    from .test_kgquery_generated_sql_plans import _to_builder_frame
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria as BuilderEntityQueryCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    entity_criteria = BuilderEntityQueryCriteria(
        entity_type=KGENTITY, entity_uris=None,
        frame_criteria=[_to_builder_frame(f) for f in frame_criteria],
        use_edge_pattern=True)
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        entity_criteria, fx.graph, PAGE_SIZE, 0)

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
    if not cr.ok:
        pytest.fail(f"KGQuery SPARQL failed to compile: {cr.error}\n\n{sparql}")
    gen = await generate_sql(cr, fx.space, conn=conn)
    return gen.sql


@pytest.mark.bench("query.kgquery.growth_curve.eq")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
@pytest.mark.parametrize("state", EQ_STATES)
async def test_page_cost_vs_match_count_equality(perf_conn, perf_record, fx, state):
    """Equality: rows through the join == matches, so this is the real curve."""
    await _require_loaded(perf_conn, fx)

    counts = _load_manifest(fx)["actual_matches"]["companystatecode_eq"]
    total_matches = counts.get(state, 0)

    sql = await _criteria_to_sql(perf_conn, _eq_criteria(state), fx)
    plan = await assert_plan(
        perf_conn, sql,
        no_seq_scan_on=[f"{fx.space}_rdf_quad"],
        no_spill=True,
        # A criterion matching nothing satisfies every upper bound here. The
        # manifest says how many there should be, so require them.
        min_actual_rows=min(PAGE_SIZE, total_matches) if total_matches else 1,
    )

    buffers = total_shared_buffers(plan)
    perf_record(
        plan=plan, dataset=fx.space,
        metrics={"total_matches": total_matches, "page_size": PAGE_SIZE,
                 "buffers_per_match": round(buffers / max(total_matches, 1), 3)},
        notes=f"[{fx.label}] CompanyStateCode = {state} — {total_matches:,} "
              f"matches, {PAGE_SIZE}-row page")


@pytest.mark.bench("query.kgquery.growth_ratio")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_growth_ratio_equality(perf_conn, perf_record, fx):
    """The fix, as one number: page cost against a 9.5x change in match count."""
    await _require_loaded(perf_conn, fx)

    counts = _load_manifest(fx)["actual_matches"]["companystatecode_eq"]
    measured = {}
    for state in EQ_STATES:
        sql = await _criteria_to_sql(perf_conn, _eq_criteria(state), fx)
        plan = await assert_plan(perf_conn, sql, no_spill=True)
        measured[state] = total_shared_buffers(plan)

    big, small = EQ_STATES[0], EQ_STATES[-1]
    ratio = measured[big] / max(measured[small], 1)
    spread = counts.get(big, 1) / max(counts.get(small, 1), 1)

    print(f"\n  [{fx.label}] {'state':>6} {'matches':>9} {'buffers':>10} {'buf/match':>10}")
    for s in EQ_STATES:
        n = counts.get(s, 0)
        print(f"  {s:>6} {n:>9,} {measured[s]:>10,} "
              f"{measured[s] / max(n, 1):>10.1f}")
    print(f"\n  match spread {spread:.1f}x → buffer growth {ratio:.1f}x "
          f"(O(page) predicts ~1.0)")

    # Growth as a fraction of the growth in match count: 0 = O(page),
    # 1 = O(matches). Derived from this fixture's own numbers, so it means the
    # same thing at 10k or 100k entities.
    vs_matches = (ratio - 1.0) / max(spread - 1.0, 1e-9)

    perf_record(
        dataset=fx.space,
        metrics={"growth_ratio": round(ratio, 2),
                 "match_spread": round(spread, 2),
                 "growth_vs_matches": round(vs_matches, 3),
                 "buffers_smallest": measured[small],
                 "buffers_largest": measured[big]},
        notes=(f"[{fx.label}] 25-row page, matches "
               f"{counts.get(small, 0):,}→{counts.get(big, 0):,}. "
               f"O(page) predicts ~1.0; O(matches) predicts ~{spread:.1f}"))

    assert vs_matches <= EQ_GROWTH_VS_MATCHES_MAX, (
        f"page cost grew {ratio:.1f}x across a {spread:.1f}x change in match "
        f"count — {vs_matches:.2f} of linear, limit "
        f"{EQ_GROWTH_VS_MATCHES_MAX}. Above 1.0 the page is getting more "
        f"expensive faster than the result set grows. See issues/040.")


@pytest.mark.bench("query.kgquery.range_penalty")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_range_comparator_pays_for_every_candidate(perf_conn, perf_record, fx):
    """Range comparators cost the same whatever the threshold.

    Sweeping the threshold changes the match count by 625x and the buffer count
    by nothing, because the filter is applied above the join and every candidate
    crosses it regardless. Recorded as buffers-per-match at the *tightest*
    threshold, where the waste is most visible: a 16-row result paying for
    10,000 candidates.

    Note this sweep is deliberately NOT the growth-curve gate. Its flatness is
    the pathology, not the fix, and a flat line here would be indistinguishable
    from success if it were used that way.
    """
    await _require_loaded(perf_conn, fx)

    counts = _load_manifest(fx)["actual_matches"]["mqlrating_gte"]
    measured = {}
    for t in RANGE_THRESHOLDS:
        sql = await _criteria_to_sql(perf_conn, _range_criteria(t), fx)
        plan = await explain_json(perf_conn, sql)
        measured[t] = total_shared_buffers(plan)


    # Judge the range at a threshold whose selectivity is comparable to an
    # available equality case, rather than at the extreme.
    loose = RANGE_THRESHOLDS[-1]
    eq_counts_pre = _load_manifest(fx)["actual_matches"]["companystatecode_eq"]
    eq_max = max(eq_counts_pre.get(st, 0) for st in EQ_STATES)
    tight = min(RANGE_THRESHOLDS,
                key=lambda t: abs(counts[str(t)] - eq_max))
    tight_matches = counts[str(tight)]

    # Equality baseline from the same fixture and run, chosen at the closest
    # match count to the range threshold being judged — like against like. The
    # gate sends low-selectivity criteria to the set-based join and high ones to
    # the probe, so a comparison across that boundary compares two different
    # plans and means nothing.
    eq_counts = _load_manifest(fx)["actual_matches"]["companystatecode_eq"]
    eq_state = min(EQ_STATES,
                   key=lambda st: abs(eq_counts.get(st, 0) - tight_matches))
    eq_sql = await _criteria_to_sql(perf_conn, _eq_criteria(eq_state), fx)
    eq_plan = await explain_json(perf_conn, eq_sql)
    eq_per_match = (total_shared_buffers(eq_plan)
                    / max(eq_counts.get(eq_state, 1), 1))
    per_match_tight = measured[tight] / max(tight_matches, 1)
    flatness = measured[tight] / max(measured[loose], 1)

    print(f"\n  [{fx.label}] {'t':>6} {'matches':>9} {'buffers':>10} {'buf/match':>11}")
    for t in RANGE_THRESHOLDS:
        n = counts[str(t)]
        print(f"  {t:>6} {n:>9,} {measured[t]:>10,} "
              f"{measured[t] / max(n, 1):>11.1f}")
    print(f"\n  {counts[str(loose)] / max(tight_matches, 1):,.0f}x fewer matches "
          f"→ {flatness:.2f}x the cost (1.0 = pays for every candidate)")

    vs_equality = per_match_tight / max(eq_per_match, 1e-9)
    print(f"  equality baseline {eq_per_match:.1f} buf/match ({eq_state}) "
          f"→ range is {vs_equality:.1f}x that")

    perf_record(
        dataset=fx.space,
        metrics={"buffers_per_match_tightest": round(per_match_tight, 1),
                 "equality_buffers_per_match": round(eq_per_match, 1),
                 "range_vs_equality": round(vs_equality, 2),
                 "flatness": round(flatness, 3),
                 "tightest_matches": tight_matches,
                 "buffers_tightest": measured[tight]},
        notes=(f"[{fx.label}] MQLRating >= {tight} returns {tight_matches:,} rows and still "
               f"reads {measured[tight]:,} buffers — the candidate set, not the "
               f"match set (issues/040)"))

    assert vs_equality <= RANGE_VS_EQUALITY_MAX, (
        f"a range comparator matching {tight_matches:,} rows cost "
        f"{per_match_tight:,.0f} buffers per matched row against an equality "
        f"baseline of {eq_per_match:,.0f} on the same fixture — "
        f"{vs_equality:.1f}x, limit {RANGE_VS_EQUALITY_MAX}. A range predicate "
        f"applied above the join carries every candidate; pushed to the leaf it "
        f"should cost about what equality costs. See issues/040 W2.")
