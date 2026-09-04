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

Not "rdf_stats contains every pair" — it deliberately does not.
`recompute_stats_tables` keeps a bounded, per-predicate-fair slice, so absence is
expected and fine. The claim under test is narrower and is the one the planner
relies on: if a row is there, its number is right.

WHAT CHANGED, AND WHY THESE TESTS NOW RECOMPUTE. The write path no longer
maintains rdf_stats incrementally; `recompute_stats_tables` is the only writer
(`issues/142`). So a mutation alone leaves the table stale BY DESIGN, and the
end-to-end contract is "mutate, recompute, counts are true" — which is what each
test below drives. Asserting straight after the mutation would only re-assert
that the accumulator is gone.

This is not a weaker claim. Under the accumulator these same tests could pass
while the table was silently drifting, because a wrong count and a right count
are indistinguishable in isolation; the recompute is checked against the quads
themselves, so drift has nowhere to hide.

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


async def _refresh(conn, space_id: str) -> None:
    """Rebuild the stats the way production does, then assert against them.

    Production runs this from `MaintenanceJob`, not from the write path. Calling
    it inline is the same work on the same connection — it is the ONLY writer,
    so there is no second mechanism a test could be accidentally exercising.
    """
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    await recompute_stats_tables(conn, space_id)


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
        await _refresh(pg_conn, test_space)

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
        await _refresh(pg_conn, test_space)
        assert not await _mismatched_stats(pg_conn, test_space)

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> "
            f"{{ ?s <{PRED}> \"del\" }} }}")
        await _refresh(pg_conn, test_space)

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
        await _refresh(pg_conn, test_space)
        assert not await _mismatched_stats(pg_conn, test_space)

        triples = " ".join(
            f"<urn:test:stats:i{i}> <{OTHER}> \"ins\" ." for i in range(1, 5))
        await space_impl.execute_sparql_update(
            test_space, f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}")
        await _refresh(pg_conn, test_space)

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
        await _refresh(pg_conn, test_space)
        assert not await _mismatched_pred_stats(pg_conn, test_space)

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> {{ ?s <{PRED}> ?o }} }}")
        await _refresh(pg_conn, test_space)

        bad = await _mismatched_pred_stats(pg_conn, test_space)
        assert not bad, (
            f"rdf_pred_stats disagrees with the quad table after a delete: "
            f"{_describe(bad)}")

    async def test_an_emptied_table_is_rebuilt_to_truth_not_to_a_delta(
        self, test_space, space_impl, pg_conn
    ):
        """The `issues/062` failure mode, re-asserted against the replacement.

        THE OLD FAILURE. `prune_stats_tables` DELETEd a row, then
        `sync_stats_after_insert` upserted `row_count = row_count + delta`,
        which on a missing row inserted the DELTA as the whole count. Measured
        at 100,000 -> 1 on a real pair. A wrong-but-present row is worse than an
        absent one, because the reader trusts what it finds and only counts what
        it cannot find.

        WHY IT CANNOT RECUR, AND WHY THIS STILL RUNS. `recompute_stats_tables`
        has no delta arithmetic at all — it TRUNCATEs and rebuilds from the
        quads — so "existing row + delta" has no code path left to take. That
        makes this a REGRESSION test in the strict sense: it pins the property
        that any reintroduction of incremental maintenance would break, and it
        fails loudly if one appears. The scenario is driven the same way as
        before (empty the table, then write more quads) precisely so the two are
        comparable.
        """
        quads = [(URIRef(f"urn:test:stats:r{i}"), PRED, Literal("keep"), GRAPH)
                 for i in range(10)]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        await _refresh(pg_conn, test_space)

        p_uuid, o_uuid = await pg_conn.fetchrow(
            f"SELECT predicate_uuid, object_uuid FROM {test_space}_rdf_stats "
            f"ORDER BY row_count DESC LIMIT 1")
        assert await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_stats "
            f"WHERE predicate_uuid=$1 AND object_uuid=$2", p_uuid, o_uuid) >= 10

        # Empty it, exactly as the prune used to, then keep writing to the pair.
        await pg_conn.execute(f"TRUNCATE {test_space}_rdf_stats")
        await space_impl.add_rdf_quads_batch(test_space, [
            (URIRef("urn:test:stats:r99"), PRED, Literal("keep"), GRAPH)])

        # The write path must not have touched it: absence is the correct state
        # until a recompute runs, and a `1` here would be the old bug exactly.
        assert await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_stats "
            f"WHERE predicate_uuid=$1 AND object_uuid=$2",
            p_uuid, o_uuid) is None, (
            "a write re-created a stats row on its own. rdf_stats has exactly "
            "one writer; a row appearing outside a recompute means incremental "
            "maintenance is back, and with it the delta-as-whole-count bug.")

        await _refresh(pg_conn, test_space)

        stored = await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_stats "
            f"WHERE predicate_uuid=$1 AND object_uuid=$2", p_uuid, o_uuid)
        actual = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_quad "
            f"WHERE predicate_uuid=$1 AND object_uuid=$2", p_uuid, o_uuid)
        assert stored == actual == 11, (
            f"recompute rebuilt the pair as {stored} against {actual} actual "
            f"quads. The whole point of rebuilding from the quads is that the "
            f"previous contents — or their absence — cannot influence it.")


class TestLargePairsSurviveTheRebuild:
    """A pair above the OLD cap must be present, and its count must be right.

    THIS IS THE INVERSION OF WHAT THIS CLASS USED TO ASSERT, and the inversion
    is the fix. The old rebuild wrote pairs `HAVING COUNT(*) <=
    STATS_MAX_ROW_COUNT`, so an over-cap pair was ABSENT, and its predicate had
    to be flagged `pruned` to stop the incremental sync treating the next write
    as the whole truth and inserting a delta-only row over a pair holding
    hundreds of thousands.

    Observed on a 5.1M-quad space before that flag existed: (rdf:type,
    Edge_hasKGSlot) stored 37 against 304,859 actual, and (rdf:type, KGFrame) 6
    against 60,054 — the semi-join gate read 5/6 as 83% selective where the
    truth was 5/60,054, and probed 60,054 rows to return 5.

    `recompute_stats_tables` removes the upper bound entirely, so the pair is
    simply stored and there is nothing to flag. That matters beyond tidiness:
    on production the 24 pairs above the old cap cover 36% of all quads and are
    the structural anchors the join reorder most needs, and their absence is
    what sent the semi-join gate to a 10.4 s runtime probe that saturates and
    decides nothing.

    `pruned` is left alone here deliberately. Absence now means exactly one
    thing — "not in the top N" — so the flag has no work to do, and asserting on
    it would pin a column that is on its way out.
    """

    async def test_a_pair_above_the_old_cap_is_stored_with_a_true_count(
        self, test_space, space_impl, pg_conn
    ):
        # Nine quads on one pair. The old rule dropped any pair over
        # STATS_MAX_ROW_COUNT, and an earlier version of this test patched that
        # constant down to 3 to make "over the cap" reachable. The constant is
        # gone with the prune it belonged to, and there is nothing to patch:
        # the recompute has NO upper bound, so the pair is simply stored.
        quads = [(URIRef(f"urn:test:s{i}"), PRED, OTHER, GRAPH) for i in range(9)]
        quads += [(URIRef("urn:test:lone"), PRED, URIRef("urn:test:rare"), GRAPH)]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        await _refresh(pg_conn, test_space)

        pred_uuid = await pg_conn.fetchval(
            f"SELECT term_uuid FROM {test_space}_term WHERE term_text = $1",
            str(PRED))
        other_uuid = await pg_conn.fetchval(
            f"SELECT term_uuid FROM {test_space}_term WHERE term_text = $1",
            str(OTHER))
        stored = await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_stats "
            f"WHERE predicate_uuid = $1 AND object_uuid = $2",
            pred_uuid, other_uuid)
        assert stored == 9, (
            f"the over-cap pair stored {stored} against 9 actual quads. An "
            f"upper bound on row_count drops exactly the pairs the join reorder "
            f"most needs — absent, they cannot be priced at all")

        # And a following write must not corrupt it, which is the failure the
        # `pruned` flag existed to prevent. Nothing maintains stats on write any
        # more, so the count simply stays put until the next recompute.
        await space_impl.add_rdf_quads_batch(
            test_space, [(URIRef("urn:test:s99"), PRED, OTHER, GRAPH)])
        assert 9 == await pg_conn.fetchval(
            f"SELECT row_count FROM {test_space}_rdf_stats "
            f"WHERE predicate_uuid = $1 AND object_uuid = $2",
            pred_uuid, other_uuid), (
            "a write changed a stats row. There is one writer; a delta applied "
            "here is how a pair holding hundreds of thousands became 37")

        await _refresh(pg_conn, test_space)
        bad = await _mismatched_stats(pg_conn, test_space)
        assert not bad, (
            f"rdf_stats disagrees with rdf_quad after a write and a recompute: "
            f"{_describe(bad)}")
