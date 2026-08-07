"""API latency benches for the lead-dataset KGQuery scenarios.

Ported from `test_scripts/vitalgraph_client_test/entity_graph_lead_dataset/
case_kgquery_lead_queries.py`, which stays in place as a manual exploration
tool. The query criteria are carried over verbatim; if you change one, change it
in both (see planning/planning_performance/
folding_query_timing_tests_into_the_framework.md §7.5).

What this adds over the original: the timings are recorded and compared against
a baseline instead of printed and lost.

**Every bench asserts a result count.** The original suite spent a cycle
reporting ten of these queries as passing-and-fast while they matched zero rows
(a fixture namespace mismatch). A latency-only bench would have scored that as
an improvement — the query got faster precisely because it stopped matching
anything. `min_results` is what makes these benches mean something.
"""

from __future__ import annotations

import time

import pytest

from .conftest import skip_no_api, api_space_exists

pytestmark = [pytest.mark.performance, skip_no_api,
              pytest.mark.asyncio(loop_scope="session")]

SPACE_ID = "sp_sql_lead_dataset"
GRAPH_ID = "urn:sql_lead_dataset"
QUERY_MODE = "edge"

NS = "urn:acme:kg"
BOOLEAN_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot"
TEXT_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
DOUBLE_SLOT = "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot"
KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"


def _criteria(frame_criteria):
    from vitalgraph.model.kgqueries_model import KGQueryCriteria
    from vitalgraph.model.kgentities_model import EntityQueryCriteria
    return KGQueryCriteria(
        query_type="frame",
        query_mode=QUERY_MODE,
        source_entity_criteria=EntityQueryCriteria(entity_type=KGENTITY),
        frame_criteria=frame_criteria,
        exclude_self_connections=True,
    )


def _slot(slot_type, slot_class_uri, value, comparator="eq"):
    from vitalgraph.model.kgentities_model import SlotCriteria
    return SlotCriteria(slot_type=slot_type, slot_class_uri=slot_class_uri,
                        value=value, comparator=comparator)


def _frame(frame_type, slots=None, children=None):
    from vitalgraph.model.kgentities_model import FrameCriteria
    kwargs = {"frame_type": frame_type}
    if slots:
        kwargs["slot_criteria"] = slots
    if children:
        kwargs["frame_criteria"] = children
    return FrameCriteria(**kwargs)


# (bench_suffix, description, frame_criteria factory, min_results)
#
# min_results are set below the counts observed on the 100-entity fixture, so
# they catch "matches nothing" without being brittle to the data being
# regenerated. Observed at time of writing: MQL 99, hierarchical 100, CA 13,
# LA 3, high-rated 73, biz accounts 53, converted 9, abandoned 100,
# multi-criteria 10, range 88.
CASES = [
    (
        "mql", "Find MQL leads",
        lambda: [_frame(f"{NS}:frame:LeadStatusFrame", children=[
            _frame(f"{NS}:frame:LeadStatusQualificationFrame",
                   slots=[_slot(f"{NS}:slot:MQLv2", BOOLEAN_SLOT, True)])])],
        50,
    ),
    (
        "hierarchical", "Hierarchical frame query",
        lambda: [_frame(f"{NS}:frame:LeadStatusFrame", children=[
            _frame(f"{NS}:frame:LeadStatusQualificationFrame")])],
        50,
    ),
    (
        "state_ca", "Find leads in California",
        # Note the CompanyFrame parent — the address frame is nested, and
        # querying CompanyAddressFrame at top level matches nothing.
        lambda: [_frame(f"{NS}:frame:CompanyFrame", children=[
            _frame(f"{NS}:frame:CompanyAddressFrame",
                   slots=[_slot(f"{NS}:slot:CompanyStateCode",
                                TEXT_SLOT, "CA")])])],
        5,
    ),
    (
        "high_rated", "Find high-rated leads (MQLRating >= 65)",
        # MQLRating is a KGDoubleSlot compared against 65.0, not an integer.
        lambda: [_frame(f"{NS}:frame:LeadStatusFrame", children=[
            _frame(f"{NS}:frame:LeadStatusQualificationFrame",
                   slots=[_slot(f"{NS}:slot:MQLRating", DOUBLE_SLOT, 65.0,
                                comparator="gte")])])],
        20,
    ),
]


async def _run_case(client, frame_criteria):
    """Issue one KGQuery, return (wall_ms, result_count)."""
    t0 = time.perf_counter()
    resp = await client.kgqueries.query_connections(
        space_id=SPACE_ID, graph_id=GRAPH_ID,
        criteria=_criteria(frame_criteria), page_size=100, offset=0)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    count = len(resp.frame_connections) if resp.frame_connections else 0
    return wall_ms, count


@pytest.mark.bench("query.lead.kgquery")
@pytest.mark.parametrize("suffix,description,factory,min_results", CASES,
                         ids=[c[0] for c in CASES])
async def test_lead_kgquery_latency(perf_client, perf_record, suffix,
                                    description, factory, min_results):
    if not await api_space_exists(perf_client, SPACE_ID):
        pytest.skip(f"space {SPACE_ID} not loaded")

    wall_ms, count = await _run_case(perf_client, factory())

    perf_record(kind="api", dataset=SPACE_ID,
                metrics={"wall_ms": round(wall_ms, 1), "results": count},
                notes=description)

    # The gate that matters: a query matching nothing is a failure however fast
    # it was. See the module docstring.
    assert count >= min_results, (
        f"{description}: {count} results (< {min_results}) — the query matched "
        f"little or nothing. Check the fixture namespace and slot types before "
        f"reading anything into the timing.")
