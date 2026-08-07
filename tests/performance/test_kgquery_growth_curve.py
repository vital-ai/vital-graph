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

AFTER W1/W3 both curves should flatten to ~1: tighten EQ_GROWTH_RATIO_MAX and
RANGE_PENALTY_MAX then. They are loose now on purpose, so the bench records the
status quo rather than failing on it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from .conftest import skip_no_pg, space_exists
from .harness import assert_plan, explain_json, total_shared_buffers

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE_ID = "sp_lead_synth"
GRAPH_ID = "urn:lead_synth"
SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")
MANIFEST = (Path(__file__).resolve().parents[2]
            / "internal_data" / "lead_synth" / "manifest.json")

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

# Buffers at the largest match set / buffers at the smallest, over the equality
# sweep. O(page) → ~1. O(matches) → tracks the ~9.5x match spread.
EQ_GROWTH_RATIO_MAX = 30.0

# Buffers per matched row at the tightest threshold.
#
# History, because the number alone is not interpretable:
#   28,683  original — predicate applied above the join, every candidate carried
#    1,536  after W2 (range push-down): leaf semi-join, but an unindexed scan
#      274  after W4 (partial expression index on the numeric term expression)
#
# 274 at 16 matches is the fixed per-query floor (~4,400 buffers), not per-row
# work: by 10,000 matches the figure is 45.0, which is the equality baseline to
# one decimal place. The range comparator no longer costs more per matched row
# than equality does.
#
# NOTE this bound is proportional to candidates/matches and so is tied to the
# fixture's size and threshold set. Re-derive it if either changes rather than
# nudging it upward — an unexplained increase is the regression it exists to
# catch.
RANGE_PENALTY_MAX = 400.0


def _load_manifest() -> dict:
    if not MANIFEST.is_file():
        pytest.skip(f"fixture manifest not found: {MANIFEST} — generate with "
                    f"scripts/generate_lead_dataset.py")
    return json.loads(MANIFEST.read_text())


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


async def _criteria_to_sql(conn, frame_criteria) -> str:
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
        entity_criteria, GRAPH_ID, PAGE_SIZE, 0)

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
    gen = await generate_sql(cr, SPACE_ID, conn=conn)
    return gen.sql


@pytest.mark.bench("query.kgquery.growth_curve.eq")
@pytest.mark.parametrize("state", EQ_STATES)
async def test_page_cost_vs_match_count_equality(perf_conn, perf_record, state):
    """Equality: rows through the join == matches, so this is the real curve."""
    if not await space_exists(perf_conn, SPACE_ID):
        pytest.skip(f"space {SPACE_ID} not loaded — see "
                    f"scripts/generate_lead_dataset.py")

    counts = _load_manifest()["actual_matches"]["companystatecode_eq"]
    total_matches = counts.get(state, 0)

    sql = await _criteria_to_sql(perf_conn, _eq_criteria(state))
    plan = await assert_plan(
        perf_conn, sql,
        no_seq_scan_on=[f"{SPACE_ID}_rdf_quad"],
        no_spill=True,
        # A criterion matching nothing satisfies every upper bound here. The
        # manifest says how many there should be, so require them.
        min_actual_rows=min(PAGE_SIZE, total_matches) if total_matches else 1,
    )

    buffers = total_shared_buffers(plan)
    perf_record(
        plan=plan, dataset=SPACE_ID,
        metrics={"total_matches": total_matches, "page_size": PAGE_SIZE,
                 "buffers_per_match": round(buffers / max(total_matches, 1), 3)},
        notes=f"CompanyStateCode = {state} — {total_matches:,} matches, "
              f"{PAGE_SIZE}-row page")


@pytest.mark.bench("query.kgquery.growth_ratio")
async def test_growth_ratio_equality(perf_conn, perf_record):
    """The fix, as one number: page cost against a 9.5x change in match count."""
    if not await space_exists(perf_conn, SPACE_ID):
        pytest.skip(f"space {SPACE_ID} not loaded")

    counts = _load_manifest()["actual_matches"]["companystatecode_eq"]
    measured = {}
    for state in EQ_STATES:
        sql = await _criteria_to_sql(perf_conn, _eq_criteria(state))
        plan = await assert_plan(perf_conn, sql, no_spill=True)
        measured[state] = total_shared_buffers(plan)

    big, small = EQ_STATES[0], EQ_STATES[-1]
    ratio = measured[big] / max(measured[small], 1)
    spread = counts.get(big, 1) / max(counts.get(small, 1), 1)

    print(f"\n  {'state':>6} {'matches':>9} {'buffers':>10} {'buf/match':>10}")
    for s in EQ_STATES:
        n = counts.get(s, 0)
        print(f"  {s:>6} {n:>9,} {measured[s]:>10,} "
              f"{measured[s] / max(n, 1):>10.1f}")
    print(f"\n  match spread {spread:.1f}x → buffer growth {ratio:.1f}x "
          f"(O(page) predicts ~1.0)")

    perf_record(
        dataset=SPACE_ID,
        metrics={"growth_ratio": round(ratio, 2),
                 "match_spread": round(spread, 2),
                 "buffers_smallest": measured[small],
                 "buffers_largest": measured[big]},
        notes=(f"25-row page, matches {counts.get(small, 0):,}→{counts.get(big, 0):,}. "
               f"O(page) predicts ~1.0; O(matches) predicts ~{spread:.1f}"))

    assert ratio <= EQ_GROWTH_RATIO_MAX, (
        f"page cost grew {ratio:.1f}x across a {spread:.1f}x change in match "
        f"count (limit {EQ_GROWTH_RATIO_MAX}). A 25-row page should not scale "
        f"with the size of the match set — see issues/040.")


@pytest.mark.bench("query.kgquery.range_penalty")
async def test_range_comparator_pays_for_every_candidate(perf_conn, perf_record):
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
    if not await space_exists(perf_conn, SPACE_ID):
        pytest.skip(f"space {SPACE_ID} not loaded")

    counts = _load_manifest()["actual_matches"]["mqlrating_gte"]
    measured = {}
    for t in RANGE_THRESHOLDS:
        sql = await _criteria_to_sql(perf_conn, _range_criteria(t))
        plan = await explain_json(perf_conn, sql)
        measured[t] = total_shared_buffers(plan)

    tight = RANGE_THRESHOLDS[0]
    loose = RANGE_THRESHOLDS[-1]
    tight_matches = counts[str(tight)]
    per_match_tight = measured[tight] / max(tight_matches, 1)
    flatness = measured[tight] / max(measured[loose], 1)

    print(f"\n  {'t':>6} {'matches':>9} {'buffers':>10} {'buf/match':>11}")
    for t in RANGE_THRESHOLDS:
        n = counts[str(t)]
        print(f"  {t:>6} {n:>9,} {measured[t]:>10,} "
              f"{measured[t] / max(n, 1):>11.1f}")
    print(f"\n  {counts[str(loose)] / max(tight_matches, 1):,.0f}x fewer matches "
          f"→ {flatness:.2f}x the cost (1.0 = pays for every candidate)")

    perf_record(
        dataset=SPACE_ID,
        metrics={"buffers_per_match_tightest": round(per_match_tight, 1),
                 "flatness": round(flatness, 3),
                 "tightest_matches": tight_matches,
                 "buffers_tightest": measured[tight]},
        notes=(f"MQLRating >= {tight} returns {tight_matches:,} rows and still "
               f"reads {measured[tight]:,} buffers — the candidate set, not the "
               f"match set (issues/040)"))

    assert per_match_tight <= RANGE_PENALTY_MAX, (
        f"a range comparator matching {tight_matches:,} rows read "
        f"{measured[tight]:,} buffers ({per_match_tight:,.0f} per matched row, "
        f"limit {RANGE_PENALTY_MAX:,.0f}). The predicate is applied above the "
        f"join so every candidate is carried — see issues/040 W2.")
