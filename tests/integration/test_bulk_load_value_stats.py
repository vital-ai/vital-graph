"""A bulk load builds the value histograms; a small write does not.

Nothing on any write path used to build `{space}_rdf_value_stats` — only an
explicit `resync_all`. So a space loaded through the product API had no
histograms at all: `estimate_range` returned None for every range, and the
traversal criterion gate, which requires a MEASURED criterion, declined every
range criterion it saw. The range-selectivity machinery was dormant on exactly
the spaces whose data arrived through the product.

There is no incremental form — bucket boundaries move as the distribution does
(`stats_table_freshness_plan.md`, candidate 4, rejected for that reason) — so
the rebuild is all-or-nothing and has to be gated by size. Measured: 1.3 s on
2.5M quads, 9.3 s on 19.6M. Trivial after a bulk load, absurd per small write.

The two halves of the gate are both asserted here, because the failure modes
are opposite: without the rebuild a bulk-loaded space silently has no
statistics, and with it ungated every small insert pays a full rebuild.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef
from rdflib.namespace import XSD

from vitalgraph.db.sparql_sql.bulk_load import REBUILD_MIN_QUADS

pytestmark = pytest.mark.asyncio(loop_scope="session")

GRAPH = "urn:sp_test_value_stats"
SCORE = "http://vital.ai/ontology/haley-ai-kg#hasScore"
NAME = "http://vital.ai/ontology/vital-core#hasName"


def _quads(n):
    """n entities, each with a numeric score and a name — 2n quads."""
    g = URIRef(GRAPH)
    out = []
    for i in range(n):
        e = URIRef(f"urn:vs:entity:{i}")
        out.append((e, URIRef(SCORE), Literal(i % 100, datatype=XSD.integer), g))
        out.append((e, URIRef(NAME), Literal(f"entity {i}"), g))
    return out


@pytest_asyncio.fixture(loop_scope="session")
async def fresh_space(space_impl):
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    sid = f"spt_vstats_{uuid.uuid4().hex[:8]}"
    async with space_impl.get_db_connection() as conn:
        await conn.execute(
            "INSERT INTO space (space_id, space_name, update_time) "
            "VALUES ($1,$1,CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING", sid)
        await SparqlSQLSchema.create_space(conn, sid)
    try:
        yield sid
    finally:
        async with space_impl.get_db_connection() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, sid)
                await conn.execute("DELETE FROM space WHERE space_id=$1", sid)
            except Exception:
                pass


async def test_a_bulk_load_builds_the_histograms(space_impl, fresh_space):
    sid = fresh_space
    n = (REBUILD_MIN_QUADS // 2) + 500          # comfortably over the gate
    await space_impl.add_rdf_quads_batch_bulk(sid, _quads(n))

    async with space_impl.get_db_connection() as conn:
        rows = await conn.fetchval(f"SELECT count(*) FROM {sid}_rdf_value_stats")
        assert rows > 0, (
            "a bulk load left no value histograms, so every range criterion on "
            "this space reads as unmeasured")

        # The freshness reference must be captured too, or the histogram is
        # built but neither scalable nor guardable.
        unref = await conn.fetchval(
            f"SELECT count(*) FROM {sid}_rdf_value_stats WHERE pred_rows IS NULL")
        assert unref == 0, f"{unref} histogram row(s) have no freshness reference"


async def test_the_histogram_actually_estimates(space_impl, fresh_space):
    """Built is not the same as usable — a range must return a number.

    Scores are i % 100 over the batch, so `>= 50` is about half. The assertion
    is deliberately loose: this is checking the histogram is wired up and
    returns a live estimate, not re-testing its accuracy, which
    `bench_histogram_drift_curve.py` measures properly.
    """
    from vitalgraph.db.sparql_sql.sync_value_stats import (
        estimate_range, load_value_stats)

    sid = fresh_space
    n = (REBUILD_MIN_QUADS // 2) + 500
    await space_impl.add_rdf_quads_batch_bulk(sid, _quads(n))

    async with space_impl.get_db_connection() as conn:
        stats = await load_value_stats(conn, sid)
        pred = await conn.fetchval(
            f"SELECT term_uuid::text FROM {sid}_term WHERE term_text=$1", SCORE)
        assert (pred, "num") in stats, "no numeric histogram for hasScore"
        est = estimate_range(stats, pred, "num", ">=", 50)
        assert est is not None, "the histogram is present but estimates nothing"
        assert 0 < est <= n, f"estimate {est} is outside 1..{n}"


async def test_a_small_write_does_not_trigger_a_rebuild(space_impl, fresh_space):
    """The other half of the gate.

    A full rebuild is 1.3-9.3 s depending on the space. Paying that on every
    small insert would be a far worse defect than the missing statistics this
    fixes, so the gate is asserted from both sides.
    """
    sid = fresh_space
    small = _quads(10)                           # 20 quads, well under the gate
    assert len(small) < REBUILD_MIN_QUADS
    await space_impl.add_rdf_quads_batch_bulk(sid, small)

    async with space_impl.get_db_connection() as conn:
        rows = await conn.fetchval(f"SELECT count(*) FROM {sid}_rdf_value_stats")
        assert rows == 0, (
            "a 20-quad insert rebuilt the value histograms; the size gate is "
            "not holding and every small write now pays a full rebuild")
