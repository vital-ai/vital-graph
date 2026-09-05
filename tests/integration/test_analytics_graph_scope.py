"""Graph-scoped analytics must count that graph, and must run at all.

`issues/164`. `_graph_filter` emitted `AND q.graph_id = <n>` against the quad
table, which has no `graph_id` column — graphs are `context_uuid` there, and
`graph_id` is a serial on the separate `graph` registry. So EVERY analytics
request naming a graph failed with `column q.graph_id does not exist`, across
all four computations the clause is interpolated into.

It survived because the helper returns `""` when no graph is given, so the
broken text is only emitted on a path nothing exercised: the periodic job
computes whole-space analytics, and results are only persisted when no graph is
named. This file is the test that would have caught it.

The second assertion is the one with teeth. Running without error is not the
property — a filter that is silently dropped would also run without error, and
would report the whole space for a request scoped to a part of it.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql import sync_stats_tables as S
from vitalgraph.process.analytics_job import AnalyticsJob, _VITALTYPE

pytestmark = pytest.mark.asyncio(loop_scope="session")

_TYPE_A = "http://vital.ai/ontology/test#EntityAlpha"
_TYPE_B = "http://vital.ai/ontology/test#EntityBeta"


async def _term(conn, sp, text, ttype="U"):
    """Register a term and return its uuid, matching however this space spells
    the term table's required columns."""
    tid = uuid.uuid4()
    await conn.execute(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,$3) ON CONFLICT (term_uuid) DO NOTHING", tid, text, ttype)
    return tid


# MODULE-SCOPED, to match `test_space`, and it has to be. The space is created
# once per module and shared, so a function-scoped fixture seeds it again for
# every test: the space-wide total came out 24 instead of 8 (three rounds of
# 5+3), while the per-graph assertions still passed because each round mints
# fresh graph URIs. Exactly the kind of pollution a space-wide count hides and a
# graph-scoped one does not.
@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_graph_typed_space(pg_pool, test_space):
    """Two graphs whose entity type distributions differ.

        G1   EntityAlpha x 5,  EntityBeta x 2
        G2   EntityAlpha x 3

    Deliberately uneven, and Beta is absent from G2 entirely: a dropped filter
    reports Alpha 8 / Beta 2 for either graph, which no correct per-graph answer
    can equal.
    """
    sp = test_space
    async with pg_pool.acquire() as pg_conn:
        yield await _seed(pg_conn, sp)


async def _seed(pg_conn, sp):
    g1_uri = f"urn:g1:{uuid.uuid4()}"
    g2_uri = f"urn:g2:{uuid.uuid4()}"
    g1 = await _term(pg_conn, sp, g1_uri)
    g2 = await _term(pg_conn, sp, g2_uri)
    pred = await _term(pg_conn, sp, _VITALTYPE)
    a = await _term(pg_conn, sp, _TYPE_A)
    b = await _term(pg_conn, sp, _TYPE_B)

    quads = []
    quads += [(uuid.uuid4(), pred, a, g1) for _ in range(5)]
    quads += [(uuid.uuid4(), pred, b, g1) for _ in range(2)]
    quads += [(uuid.uuid4(), pred, a, g2) for _ in range(3)]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", quads)
    await pg_conn.execute(f"ANALYZE {sp}_rdf_quad")

    for uri in (g1_uri, g2_uri):
        await pg_conn.execute(
            "INSERT INTO graph (space_id, graph_uri, graph_name, created_time) "
            "VALUES ($1,$2,$2,now()) ON CONFLICT DO NOTHING", sp, uri)

    await S.recompute_stats_tables(pg_conn, sp)
    return sp, g1_uri, g2_uri


def _dist(result):
    ent = result["analytics"]["entity_analytics"]
    for key in ("entity_type_distribution", "type_distribution", "types"):
        if key in ent:
            d = ent[key]
            if isinstance(d, dict):
                return d
            return {r["type_uri"]: r["count"] for r in d}
    raise AssertionError(f"no type distribution in {list(ent)}")


async def test_a_graph_scoped_request_runs(pg_pool, two_graph_typed_space):
    """It did not. `column q.graph_id does not exist`, for every named graph."""
    sp, g1_uri, _ = two_graph_typed_space
    result = await AnalyticsJob(pg_pool).trigger_compute(sp, graph_uri=g1_uri)
    assert result is not None
    assert "error" not in result, result.get("error")


async def test_each_graph_reports_its_own_distribution(pg_pool, two_graph_typed_space):
    """The assertion with teeth: a dropped filter passes the test above."""
    sp, g1_uri, g2_uri = two_graph_typed_space
    job = AnalyticsJob(pg_pool)

    d1 = _dist(await job.trigger_compute(sp, graph_uri=g1_uri))
    d2 = _dist(await job.trigger_compute(sp, graph_uri=g2_uri))

    assert d1.get(_TYPE_A) == 5, f"G1 Alpha should be 5, got {d1}"
    assert d1.get(_TYPE_B) == 2, f"G1 Beta should be 2, got {d1}"
    assert d2.get(_TYPE_A) == 3, f"G2 Alpha should be 3, got {d2}"
    assert _TYPE_B not in d2 or d2[_TYPE_B] == 0, (
        f"Beta exists only in G1; G2 must not report it, got {d2}")


async def test_the_whole_space_is_the_sum(pg_pool, two_graph_typed_space):
    """Unscoped is still the space-wide answer — the per-graph rows summed, with
    no double counting from the one stored row per (pair, graph)."""
    sp, _, _ = two_graph_typed_space
    d = _dist(await AnalyticsJob(pg_pool).trigger_compute(sp))
    assert d.get(_TYPE_A) == 8, f"5 + 3 across graphs, got {d}"
    assert d.get(_TYPE_B) == 2, f"got {d}"
