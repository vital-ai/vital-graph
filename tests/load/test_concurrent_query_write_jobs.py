"""The realistic-production test: reads, writes and jobs at the same time.

`issues/171` Part 2. Opt-in, because it writes to the 53M-quad dataset and takes
minutes:

    VG_RUN_LOAD_TEST=1 python -m pytest tests/load/ -q -s

WHY IT IS NOT IN THE DEFAULT SUITE. It mutates a shared perf fixture and its
value is a measurement, not a boolean — running it accidentally on a contended
machine produces numbers that mean nothing, which is the exact failure mode the
test exists to stop the repository making.

THE JOBS ARE THE POINT. The nurture fixture sits in
`VG_MAINTENANCE_EXCLUDE_SPACES` so periodic work does not perturb benchmarks
(`issues/112`). That exclusion is what makes every other measurement clean and
unrealistic. Here the maintenance work is invoked DELIBERATELY, concurrently
with the query load, because "what happens with the jobs running" is the
question production was asking.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import os
import uuid

import pytest

from tests.load.concurrent_load import run_load
from tests.load.entity_graph_reads import (
    prepare_entity_graph_sql, sample_entity_uris, sql_rotation)
from tests.load.run_scoped_data import (
    RunScope, cleanup, snapshot, verify_clean)

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(os.environ.get("VG_RUN_LOAD_TEST") != "1",
                       reason="load test is opt-in: set VG_RUN_LOAD_TEST=1"),
]

SPACE = os.environ.get("VG_LOAD_SPACE", "lead_nurture_grouped")
GRAPH = os.environ.get("VG_LOAD_GRAPH", "urn:lead_nurture_grouped")
# A MINIMUM, not a bound: the harness keeps the readers running until the jobs
# finish, so a slow maintenance pass extends the measured window rather than
# escaping it.
DURATION_S = float(os.environ.get("VG_LOAD_SECONDS", "60"))

# Thresholds. Deliberately stated as constants rather than buried in asserts,
# because they are a claim about the product and should be arguable.
P99_MS = float(os.environ.get("VG_LOAD_P99_MS", "1000"))
CEILING_MS = float(os.environ.get("VG_LOAD_CEILING_MS", "5000"))

_NS, _KG = "urn:acme:kg", "http://vital.ai/ontology/haley-ai-kg#"
SIDECAR = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")

# THE MIX. Real usage is two things: FIND entities, and OPEN one. The find half
# is served by the slot-sort fast path; the open half is a four-way UNION
# through the general pipeline. Measuring only the first was measuring the half
# that had just been optimised.
N_ENTITY_SAMPLES = int(os.environ.get("VG_LOAD_ENTITY_SAMPLES", "20"))


def _criteria(slot, cls, value):
    from vitalgraph.sparql.kg_query_builder import (
        EntityQueryCriteria, FrameCriteria, SlotCriteria)
    return EntityQueryCriteria(
        entity_type=f"{_NS}:entity:Lead", entity_uris=None,
        frame_criteria=[FrameCriteria(
            frame_type=f"{_NS}:frame:NurtureInfoFrame",
            slot_criteria=[SlotCriteria(slot_type=f"{_NS}:slot:{slot}",
                                        slot_class_uri=_KG + cls,
                                        value=value, comparator="eq")])],
        use_edge_pattern=True)


@pytest.fixture(scope="module")
def scope():
    return RunScope.new(SPACE)


async def test_reads_stay_fast_while_writes_and_jobs_run(pg_pool, scope):
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        fast_slot_filter_count, fast_slot_filter_page)
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        entity_slot_sort_all_types)

    async with pg_pool.acquire() as c:
        before = await snapshot(c, scope)
    print(f"\n  space={SPACE} before={before}", flush=True)

    campaign = _criteria("NurtureCampaignURI", "KGURISlot",
                         "urn:acme:campaign:000")
    absent = _criteria("SFLeadId", "KGTextSlot", "ABSENT000000000")

    async def count_campaign():
        async with pg_pool.acquire() as c:
            await c.execute("SET statement_timeout = '30s'")
            await fast_slot_filter_count(c, SPACE, GRAPH, campaign)

    async def page_campaign():
        async with pg_pool.acquire() as c:
            await c.execute("SET statement_timeout = '30s'")
            await fast_slot_filter_page(c, SPACE, GRAPH, campaign, 25, 0)

    async def count_absent():
        async with pg_pool.acquire() as c:
            await c.execute("SET statement_timeout = '30s'")
            await fast_slot_filter_count(c, SPACE, GRAPH, absent)

    async def write_one():
        """Ingest into THIS RUN'S GRAPH, so cleanup is bounded by the run."""
        async with pg_pool.acquire() as c:
            g = await c.fetchval(
                f"SELECT term_uuid FROM {SPACE}_term WHERE term_text=$1 LIMIT 1",
                scope.graph_uri)
            if g is None:
                g = uuid.uuid4()
                await c.execute(
                    f"INSERT INTO {SPACE}_term (term_uuid, term_text, term_type)"
                    f" VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING",
                    g, scope.graph_uri)
            await c.execute(
                f"INSERT INTO {SPACE}_rdf_quad (subject_uuid, predicate_uuid,"
                f" object_uuid, context_uuid) VALUES ($1,$2,$3,$4)"
                f" ON CONFLICT DO NOTHING",
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), g)

    # Prepared BEFORE the load so the sidecar is not on the hot path — see
    # `entity_graph_reads`. Failing to prepare any is fatal: the run would
    # silently become a find-only workload again, which is the gap this closes.
    async with pg_pool.acquire() as c:
        uris = await sample_entity_uris(c, SPACE, limit=N_ENTITY_SAMPLES)
        graph_sql = await prepare_entity_graph_sql(c, SPACE, uris, SIDECAR)
    assert graph_sql, (
        f"prepared 0 entity-graph statements from {len(uris)} URIs — the mix "
        f"would silently degrade to find-only")
    print(f"  entity-graph statements prepared: {len(graph_sql)} "
          f"from {len(uris)} URIs", flush=True)
    rotation = sql_rotation(graph_sql)

    async def open_entity_graph():
        """The other main component: fetch one entity's whole graph."""
        stmt = next(rotation)
        async with pg_pool.acquire() as c:
            await c.execute("SET statement_timeout = '30s'")
            await c.fetch(stmt)

    async def job_stats():
        async with pg_pool.acquire() as c:
            await c.execute("SET statement_timeout = '600s'")
            await recompute_stats_tables(c, SPACE)

    async def job_coverage():
        async with pg_pool.acquire() as c:
            await c.execute("SET statement_timeout = '600s'")
            await entity_slot_sort_all_types(c, SPACE)

    try:
        res = await run_load(
            readers={"find:count_campaign": count_campaign,
                     "find:page_campaign": page_campaign,
                     "find:count_absent": count_absent,
                     "open:entity_graph": open_entity_graph},
            writer=write_one,
            jobs=[job_stats, job_coverage],
            duration_s=DURATION_S, read_concurrency=3, write_pace_s=0.02)

        print(f"  summary: {res.summary()}", flush=True)
        for label, st in res.by_label().items():
            print(f"    {label:<18} {st}", flush=True)

        assert not res.timeouts, (
            f"{len(res.timeouts)} query timeout(s) under concurrent load — the "
            f"production symptom. First: {res.timeouts[0].error[:160]}")
        assert not res.failures, (
            f"{len(res.failures)} query failure(s): "
            f"{res.failures[0].error[:160]}")
        assert res.writes > 0, "no writes completed — ingest was starved"
        assert res.pct(99) <= P99_MS, (
            f"p99 {res.pct(99):.0f}ms exceeds {P99_MS:.0f}ms. The mean hides "
            f"this: p50 is {res.pct(50):.0f}ms.")
        assert res.summary()["max_ms"] <= CEILING_MS, (
            f"slowest query {res.summary()['max_ms']:.0f}ms exceeds the "
            f"{CEILING_MS:.0f}ms ceiling")
    finally:
        async with pg_pool.acquire() as c:
            removed = await cleanup(c, scope)
            findings = await verify_clean(c, scope)
        print(f"  cleanup removed={removed}", flush=True)
        assert findings == [], f"cleanup left residue: {findings}"
