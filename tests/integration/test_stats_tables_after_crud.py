"""Integration tests: `{space}_rdf_stats` counts stay true across CRUD.

The third derived structure, after the edge and frame_entity tables, and the one
with the worst repair story. It drives the join-reorder heuristic and the
semi-join selectivity gate, so a wrong count does not produce a wrong answer —
it produces a wrong *plan*, silently, and the query still returns the right rows
just far too slowly. Nothing about the result reveals it.

What is asserted
----------------
Every count STORED in rdf_stats must equal the true count of that
(predicate, object) pair in rdf_quad.

Not "rdf_stats contains every pair" — it deliberately does not. `prune_stats_tables`
keeps a bounded per-predicate slice, so absence is expected and fine. The claim
under test is narrower and is the one the planner relies on: if a row is there,
its number is right.

That framing also isolates the failure in `issues/062`, where pruning and
incremental maintenance interact — a pruned row that a later write resurrects
reappears holding only its post-prune delta, understating by orders of magnitude
while looking authoritative.

Covers the write MODES that derived state actually breaks in — update and
delete — not just create. Both the edge and frame_entity tables were correct on
create and broken on the other two, which is the pattern this file exists to
catch early for stats.

See planning/planning_performance/performance_regression_tracking_plan.md R6
"""

from __future__ import annotations

import pytest
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

PRED = URIRef("urn:test:stats:pred")
OTHER = URIRef("urn:test:stats:other")
GRAPH = URIRef("urn:test:stats_graph")


async def _mismatched_stats(conn, space_id: str) -> list:
    """Rows whose stored row_count disagrees with the actual quad count.

    Compares only pairs PRESENT in rdf_stats. Absence is a legitimate outcome of
    pruning; a wrong stored number never is.
    """
    return await conn.fetch(
        f"""
        SELECT s.predicate_uuid, s.object_uuid,
               s.row_count AS stored,
               COALESCE(q.n, 0) AS actual
        FROM {space_id}_rdf_stats s
        LEFT JOIN (
            SELECT predicate_uuid, object_uuid, count(*) AS n
            FROM {space_id}_rdf_quad GROUP BY 1, 2
        ) q ON q.predicate_uuid = s.predicate_uuid
           AND q.object_uuid = s.object_uuid
        WHERE s.row_count IS DISTINCT FROM COALESCE(q.n, 0)
        """
    )


async def _mismatched_pred_stats(conn, space_id: str) -> list:
    return await conn.fetch(
        f"""
        SELECT p.predicate_uuid, p.row_count AS stored, COALESCE(q.n, 0) AS actual
        FROM {space_id}_rdf_pred_stats p
        LEFT JOIN (
            SELECT predicate_uuid, count(*) AS n
            FROM {space_id}_rdf_quad GROUP BY 1
        ) q ON q.predicate_uuid = p.predicate_uuid
        WHERE p.row_count IS DISTINCT FROM COALESCE(q.n, 0)
        """
    )


def _describe(rows) -> str:
    return ", ".join(
        f"stored={r['stored']} actual={r['actual']}" for r in rows[:5])


class TestStatsTablesAfterCrud:

    async def test_batch_insert_records_true_counts(
        self, test_space, space_impl, pg_conn
    ):
        """Baseline: after a create, stored counts are true.

        Guards the rest of the file — if stats are never populated at all, every
        later assertion passes vacuously on an empty table.
        """
        quads = [(URIRef(f"urn:test:stats:s{i}"), PRED, Literal("shared"), GRAPH)
                 for i in range(6)]
        await space_impl.add_rdf_quads_batch(test_space, quads)

        stored = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_stats")
        assert stored > 0, (
            "rdf_stats is empty after an insert, so every assertion in this "
            "file would pass vacuously")

        bad = await _mismatched_stats(pg_conn, test_space)
        assert not bad, f"stored counts wrong after insert: {_describe(bad)}"

    async def test_counts_stay_true_after_sparql_delete(
        self, test_space, space_impl, pg_conn
    ):
        """DELETE through SPARQL UPDATE must not leave counts overstated.

        An overstated count makes a predicate look less selective than it is, so
        the join reorder seeds from the wrong leaf and the selectivity gate
        declines to probe — the queries get slower and nothing else changes.
        """
        quads = [(URIRef(f"urn:test:stats:d{i}"), PRED, Literal("del"), GRAPH)
                 for i in range(8)]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        assert not await _mismatched_stats(pg_conn, test_space)

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> "
            f"{{ ?s <{PRED}> \"del\" }} }}")

        bad = await _mismatched_stats(pg_conn, test_space)
        assert not bad, (
            f"rdf_stats still counts quads that were deleted: {_describe(bad)}. "
            f"The planner reads this as a less selective predicate, picks a "
            f"worse plan, and returns correct rows slowly — nothing about the "
            f"result reveals it.")

    async def test_counts_stay_true_after_sparql_insert(
        self, test_space, space_impl, pg_conn
    ):
        """INSERT through SPARQL UPDATE must not leave counts understated."""
        await space_impl.add_rdf_quads_batch(test_space, [
            (URIRef("urn:test:stats:i0"), OTHER, Literal("ins"), GRAPH)])
        assert not await _mismatched_stats(pg_conn, test_space)

        triples = " ".join(
            f"<urn:test:stats:i{i}> <{OTHER}> \"ins\" ." for i in range(1, 5))
        await space_impl.execute_sparql_update(
            test_space, f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}")

        bad = await _mismatched_stats(pg_conn, test_space)
        assert not bad, (
            f"rdf_stats did not record quads inserted via SPARQL UPDATE: "
            f"{_describe(bad)}")

    async def test_pred_stats_stay_true_across_crud(
        self, test_space, space_impl, pg_conn
    ):
        """`rdf_pred_stats` is the per-predicate total feeding the same heuristic.

        It is not pruned, so unlike rdf_stats every one of its rows should always
        be exactly right.
        """
        quads = [(URIRef(f"urn:test:stats:p{i}"), PRED, Literal(f"v{i}"), GRAPH)
                 for i in range(5)]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        assert not await _mismatched_pred_stats(pg_conn, test_space)

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> {{ ?s <{PRED}> ?o }} }}")

        bad = await _mismatched_pred_stats(pg_conn, test_space)
        assert not bad, (
            f"rdf_pred_stats disagrees with the quad table after a delete: "
            f"{_describe(bad)}")

    async def test_pruned_pair_is_not_resurrected_with_a_wrong_count(
        self, test_space, space_impl, pg_conn
    ):
        """A pruned pair must not reappear holding only its post-prune delta.

        The failure this reproduces (`issues/062`): `prune_stats_tables` DELETEs
        a row, then `sync_stats_after_insert` upserts
        `row_count = row_count + delta`, which on a missing row inserts the
        delta as the whole count. Measured at 100,000 -> 1 on a real pair.

        A wrong-but-present row is worse than an absent one, because the reader
        trusts what it finds and only counts what it does not — so the assertion
        is that the stored value is either right or gone, never small.
        """
        from vitalgraph.db.sparql_sql.sync_stats_tables import prune_stats_tables

        # A pair well above STATS_MAX_ROW_COUNT is unreachable in a test, so
        # force the same situation directly: a populated pair, then pruned.
        quads = [(URIRef(f"urn:test:stats:r{i}"), PRED, Literal("keep"), GRAPH)
                 for i in range(10)]
        await space_impl.add_rdf_quads_batch(test_space, quads)

        p_uuid, o_uuid = await pg_conn.fetchrow(
            f"SELECT predicate_uuid, object_uuid FROM {test_space}_rdf_stats "
            f"ORDER BY row_count DESC LIMIT 1")
        before = await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_stats "
            f"WHERE predicate_uuid=$1 AND object_uuid=$2", p_uuid, o_uuid)
        assert before >= 10

        # Prune everything, then keep writing to the pruned pair.
        await prune_stats_tables(pg_conn, test_space, keep_top_n=0,
                                 per_predicate_n=0)
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_stats") == 0

        await space_impl.add_rdf_quads_batch(test_space, [
            (URIRef("urn:test:stats:r99"), PRED, Literal("keep"), GRAPH)])

        stored = await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_stats "
            f"WHERE predicate_uuid=$1 AND object_uuid=$2", p_uuid, o_uuid)
        actual = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_quad "
            f"WHERE predicate_uuid=$1 AND object_uuid=$2", p_uuid, o_uuid)

        assert stored is None or stored == actual, (
            f"a pruned pair reappeared in rdf_stats holding {stored} against "
            f"{actual} actual quads. The planner reads that as a highly "
            f"selective predicate and seeds the join from it. Absent would "
            f"have been correct — the reader counts what it cannot find.")


class TestResyncAboveCapKeepsPrunedFlag:
    """A pair the rebuild could not cover must leave its predicate flagged.

    `resync_stats_tables` writes pairs `HAVING COUNT(*) <= STATS_MAX_ROW_COUNT`
    and used to clear `pruned` for EVERY predicate afterwards. For a predicate
    whose pair sits above that cap those two statements contradict each other:
    the row is absent, and the flag says absence means zero. The incremental
    sync then treats the next write as the whole truth and INSERTs a delta-only
    row over a pair holding hundreds of thousands.

    Observed on a 5.1M-quad space before the fix: (rdf:type, Edge_hasKGSlot)
    stored 37 against 304,859 actual, and (rdf:type, KGFrame) 6 against 60,054.
    The comment on the clearing statement argued the ambiguity was inert, having
    measured what a correct ABSENT value would change. The damage is done by a
    wrong PRESENT value, which is a different question — the semi-join gate read
    5/6 as 83% selective where the truth was 5/60,054, and probed 60,054 rows to
    return 5.

    The cap is patched down rather than writing 200k quads: the branch under
    test is "some pair exceeds the threshold", and the threshold's value is not
    what is being tested.
    """

    async def test_predicate_above_cap_stays_pruned(
        self, test_space, space_impl, pg_conn, monkeypatch
    ):
        from vitalgraph.db.sparql_sql import sync_stats_tables as sst

        monkeypatch.setattr(sst, "STATS_MAX_ROW_COUNT", 3)

        # One pair well above the patched cap, one comfortably below it.
        quads = [(URIRef(f"urn:test:s{i}"), PRED, OTHER, GRAPH) for i in range(8)]
        quads += [(URIRef("urn:test:lone"), PRED, URIRef("urn:test:rare"), GRAPH)]
        await space_impl.add_rdf_quads_batch(test_space, quads)

        await sst.resync_stats_tables(pg_conn, test_space)

        pred_uuid = await pg_conn.fetchval(
            f"SELECT term_uuid FROM {test_space}_term WHERE term_text = $1",
            str(PRED))
        pruned = await pg_conn.fetchval(
            f"SELECT pruned FROM {test_space}_rdf_pred_stats "
            f"WHERE predicate_uuid = $1", pred_uuid)
        assert pruned is True, (
            "a predicate with a pair above STATS_MAX_ROW_COUNT was left "
            "unflagged, so absence of that pair now reads as zero and the next "
            "write will store only its delta")

        # The write that used to corrupt it. With the flag set the sync stays
        # UPDATE-only, so no delta-only row appears for the over-cap pair.
        await space_impl.add_rdf_quads_batch(
            test_space, [(URIRef("urn:test:s99"), PRED, OTHER, GRAPH)])

        bad = await _mismatched_stats(pg_conn, test_space)
        assert not bad, (
            "rdf_stats holds a count that disagrees with rdf_quad after a write "
            f"following resync: {[dict(r) for r in bad]}")
