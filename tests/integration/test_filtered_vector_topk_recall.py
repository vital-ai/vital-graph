"""Filtered vector top-k returns the k nearest MATCHING rows.

THE DEFECT. `WHERE <filter> ORDER BY embedding <=> q LIMIT k` is served from
the HNSW index, which yields `hnsw.ef_search` (40) candidates; the filter runs on
those alone. A type holding 1% of rows then returns 0-1 rows of the 20 asked
for (recall 0.015, measured on 100k real MiniLM embeddings). Nothing errors: the search simply finds less, and
"fewer results for an uncommon type" reads as a property of the data.

THE FIX (`vectorization/hnsw_scan.py`): iterative scan for the statement, top k
taken in a subquery, the certainty cutoff and the re-sort applied outside it.

HOW THIS IS TESTED. Real registry tables, inside ONE transaction that is
rolled back, so nothing is written: 4,000 entities whose vectors all sit near
the query, 40 of them (1%) of a rare type. `enable_sort = off` in that
transaction makes the planner choose the HNSW plan it chooses on production-
sized tables (see the fixture). `EntityRegistrySearch` runs on that
transaction's connection. The control test runs the PREVIOUS statement against
the same rows and must lose results; if it ever stops losing them (the planner
chose an exact scan), the other tests here prove nothing and it says so.
"""

from __future__ import annotations

import contextlib
import random
import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

DIM = 384
COLUMN = "embedding_vitalsigns_onnx"
N_ROWS = 4000
RARE_SHARE = 0.01
K = 20


def _unit(v):
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def _vec_literal(v):
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class _OneConnPool:
    """A pool whose every acquire() is the test's transaction connection."""

    def __init__(self, conn):
        self._conn = conn

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self._conn


class _FixedProvider:
    def __init__(self, vec):
        self._vec = vec

    async def vectorize_text(self, text):
        return self._vec


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seeded(pg_pool):
    """(conn, query vector, rare type key, {entity_id: distance} for rare rows).

    Everything is inserted inside a transaction that is rolled back on exit.
    """
    rng = random.Random(20261115)
    q = _unit([rng.gauss(0, 1) for _ in range(DIM)])
    tag = uuid.uuid4().hex[:8]
    common_key, rare_key = f"t_common_{tag}", f"t_rare_{tag}"

    async with pg_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            ids = {}
            for key in (common_key, rare_key):
                ids[key] = await conn.fetchval(
                    "INSERT INTO entity_type (type_key, type_label) VALUES ($1, $1) "
                    "RETURNING type_id", key)
            n_rare = int(N_ROWS * RARE_SHARE)
            ent_rows, vec_rows, rare = [], [], {}
            for i in range(N_ROWS):
                key = rare_key if i % (N_ROWS // n_rare) == 0 else common_key
                # Near the query: cosine similarity ~0.75-0.95, so the default
                # certainty cutoff (0.7) keeps every row and recall is what is
                # measured, not the cutoff.
                noise = rng.uniform(0.35, 0.9)
                v = _unit([a + noise * rng.gauss(0, 1) / DIM ** 0.5 for a in q])
                eid = f"vk-{tag}-{i}"
                ent_rows.append((eid, ids[key], f"probe {i}"))
                vec_rows.append((uuid.uuid4(), eid, _vec_literal(v), f"probe {i}"))
                if key == rare_key:
                    rare[eid] = 1.0 - sum(a * b for a, b in zip(q, v))
            await conn.executemany(
                "INSERT INTO entity (entity_id, entity_type_id, primary_name) "
                "VALUES ($1, $2, $3)", ent_rows)
            await conn.executemany(
                f"INSERT INTO entity_registry_vec_entity "
                f"(subject_uuid, entity_id, {COLUMN}, search_text) "
                f"VALUES ($1, $2, $3::vector, $4)", vec_rows)
            # At 4,000 rows the planner serves the rare type EXACTLY (type ->
            # entities -> sort), which is right at this size and hides the
            # defect. On production-sized tables it picks the HNSW scan (every
            # type filter tested in the vitalsigns measurement did). Make it pick
            # that here: an exact plan needs a Sort, so discourage sorting.
            # Transaction-local, rolled back with everything else.
            await conn.execute("SET LOCAL enable_sort = off")
            yield conn, q, rare_key, rare
        finally:
            await tx.rollback()


def _search(conn, q):
    from vitalgraph.entity_registry.entity_registry_search import EntityRegistrySearch
    s = EntityRegistrySearch.__new__(EntityRegistrySearch)
    s.pool = _OneConnPool(conn)
    s._provider = _FixedProvider(q)
    s._embedding_column = COLUMN
    return s


def _expected(rare, k=K, max_distance=None):
    ranked = sorted(rare.items(), key=lambda kv: kv[1])
    if max_distance is not None:
        ranked = [kv for kv in ranked if kv[1] <= max_distance]
    return [eid for eid, _ in ranked[:k]]


class TestTheControlLosesRows:

    async def test_previous_statement_misses_rare_type_rows(self, seeded):
        """The statement before the fix, on the same rows. If this passes the
        planner served it exactly and the recall tests below are vacuous."""
        conn, q, rare_key, rare = seeded
        rows = await conn.fetch(
            f"""
            SELECT e.entity_id
            FROM entity_registry_vec_entity v
            JOIN entity e ON e.entity_id = v.entity_id
            JOIN entity_type et ON et.type_id = e.entity_type_id
            WHERE (v.{COLUMN} <=> $1::vector) <= 0.3
              AND e.status = 'active' AND et.type_key = $2
            ORDER BY v.{COLUMN} <=> $1::vector
            LIMIT {K}
            """, _vec_literal(q), rare_key)
        assert len(rows) < K // 2, (
            f"the old statement returned {len(rows)} of {K}: the planner did not "
            "use HNSW here, so this file no longer tests the fix")


class TestSearchTopic:

    async def test_rare_type_returns_its_nearest_k(self, seeded):
        conn, q, rare_key, rare = seeded
        got = await _search(conn, q).search_topic("ignored", type_key=rare_key, limit=K)
        got_ids = [r["entity_id"] for r in got]
        expected = _expected(rare)
        recall = len(set(got_ids) & set(expected)) / len(expected)
        assert len(got_ids) == K
        assert recall >= 0.9, f"recall {recall:.2f}"

    async def test_scores_are_non_increasing(self, seeded):
        conn, q, rare_key, _ = seeded
        got = await _search(conn, q).search_topic("ignored", type_key=rare_key, limit=K)
        scores = [r["score"] for r in got]
        assert scores == sorted(scores, reverse=True)

    async def test_cutoff_leaving_fewer_than_k(self, seeded):
        """The cutoff is applied outside the scan; the rows it keeps are exactly
        the rare rows within it (top k of them)."""
        conn, q, rare_key, rare = seeded
        dists = sorted(rare.values())
        max_distance = (dists[4] + dists[5]) / 2       # 5 rows qualify
        got = await _search(conn, q).search_topic(
            "ignored", type_key=rare_key, limit=K, min_certainty=1.0 - max_distance)
        assert sorted(r["entity_id"] for r in got) == sorted(
            _expected(rare, max_distance=max_distance))

    async def test_result_columns_unchanged(self, seeded):
        conn, q, rare_key, _ = seeded
        got = await _search(conn, q).search_topic("ignored", type_key=rare_key, limit=3)
        assert set(got[0]) == {
            "entity_id", "primary_name", "description", "country", "region",
            "locality", "latitude", "longitude", "type_key", "type_label",
            "search_text", "score"}

    async def test_the_setting_does_not_outlive_the_statement(self, seeded):
        conn, q, rare_key, _ = seeded
        before = await conn.fetchval("SELECT current_setting('hnsw.iterative_scan', true)")
        await _search(conn, q).search_topic("ignored", type_key=rare_key, limit=3)
        after = await conn.fetchval("SELECT current_setting('hnsw.iterative_scan', true)")
        # The search's transaction is a savepoint inside the fixture's, so
        # SET LOCAL would survive into it: the helper must not rely on that.
        assert after == before
