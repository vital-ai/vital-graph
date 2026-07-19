"""Integration: add_rdf_quads_batch_bulk's adaptive COPY/rebuild path.

A large batch (>= REBUILD_MIN_QUADS) into an empty space takes the
drop-indexes → COPY → rebuild path; a batch into a non-empty space takes
executemany. Verify both land identical data to a forced-executemany baseline,
leave the secondary indexes rebuilt, and keep the rdf_stats in sync.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import URIRef, Literal

from .conftest import skip_no_infra, TEST_SPACE_PREFIX
from vitalgraph.db.sparql_sql.bulk_load import REBUILD_MIN_QUADS

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

N = REBUILD_MIN_QUADS + 2_000   # comfortably over the rebuild threshold
G = "urn:bulkcopy:g"


def _quads(n):
    g = URIRef(G)
    preds = [URIRef(f"urn:p:{i}") for i in range(10)]
    out = []
    for i in range(n):
        out.append((URIRef(f"urn:s:{i}"), preds[i % 10],
                    Literal(f"value {i}"), g))
    return out


@pytest_asyncio.fixture(loop_scope="session")
async def two_spaces(make_space):
    return [await make_space(f"{TEST_SPACE_PREFIX}bulk_{k}_{uuid.uuid4().hex[:8]}")
            for k in ("auto", "em")]


async def _counts(conn, sid):
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    t = SparqlSQLSchema.get_table_names(sid)
    return (await conn.fetchval(f"SELECT count(*) FROM {t['rdf_quad']}"),
            await conn.fetchval(f"SELECT count(*) FROM {t['term']}"))


async def test_copy_rebuild_matches_executemany(space_impl, two_spaces):
    auto_sid, em_sid = two_spaces
    quads = _quads(N)

    # auto path: large batch into empty space -> copy+rebuild
    n_auto = await space_impl.add_rdf_quads_batch_bulk(auto_sid, quads)
    # baseline: force executemany
    n_em = await space_impl.add_rdf_quads_batch_bulk(
        em_sid, quads, rebuild_indexes=False)
    assert n_auto == n_em == N

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        auto_counts = await _counts(conn, auto_sid)
        em_counts = await _counts(conn, em_sid)
        assert auto_counts == em_counts, (auto_counts, em_counts)
        assert auto_counts[0] == N

        # Secondary indexes were rebuilt, not left dropped.
        for idx in (f"idx_{auto_sid}_quad_pred", f"idx_{auto_sid}_term_trgm",
                    f"idx_{auto_sid}_quad_ctx_pred"):
            assert await conn.fetchval(
                "SELECT 1 FROM pg_indexes WHERE indexname = $1", idx), idx

        # rdf_stats stayed in sync through the copy+rebuild path.
        t = __import__("vitalgraph.db.sparql_sql.sparql_sql_schema",
                       fromlist=["SparqlSQLSchema"]).SparqlSQLSchema.get_table_names(auto_sid)
        stat_total = await conn.fetchval(
            f"SELECT COALESCE(sum(row_count), 0) FROM {t['rdf_stats']}")
        assert stat_total == N, stat_total


async def test_second_batch_into_nonempty_uses_executemany(space_impl, two_spaces):
    auto_sid, _ = two_spaces
    # First batch (empty -> copy+rebuild)
    await space_impl.add_rdf_quads_batch_bulk(auto_sid, _quads(N))
    # Second, distinct batch into the now-non-empty space -> executemany path
    g = URIRef(G)
    more = [(URIRef(f"urn:s2:{i}"), URIRef("urn:p:x"), Literal(f"v{i}"), g)
            for i in range(N)]
    n2 = await space_impl.add_rdf_quads_batch_bulk(auto_sid, more)
    assert n2 == N
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        quads, _ = await _counts(conn, auto_sid)
        assert quads == 2 * N, quads
