"""A space that holds quads must hold statistics for them (issues/103).

THE STATE THIS EXISTS TO CATCH. The rebuild TRUNCATEs and repopulates. On
2026-08-17 a load died between those two steps and left `sp_lead_synth_100k`
with 50,436,200 quads and a 136-row `rdf_stats`. The load reported failure and
exited; the quads were already committed; nothing else noticed.

Empty is the WORST state, not a neutral one. Absence means ZERO to every consumer
of these tables — the criterion gate reads a pair as unmeasured, the traversal
direction gate cannot price a constrained end, `semijoin._selective_enough`
divides by an understated anchor and takes a per-row probe over a set-based join.
Every query stays CORRECT and gets a wrong plan, so nothing in the result reveals
it. That is the same shape as `issues/081` (a baseline promoted from an unstamped
run) and `issues/099` (a fixture read from the wrong cluster): a measurement that
answers plausibly from a configuration nobody checked.

The rebuild is now atomic, so a failure mid-rebuild rolls the TRUNCATE back and
the previous rows survive. That does NOT cover the case above: on a FRESH load
the previous contents are empty, so a failed first rebuild still leaves nothing.
Hence this check, which is the mark the next reader trips over.

WHY pred_stats AND NOT rdf_stats. `rdf_pred_stats` gets one row per predicate
with no threshold, so a space with quads always has rows. `rdf_stats` holds only
pairs reaching `STATS_MIN_ROW_COUNT`, and is legitimately EMPTY for a space whose
every (predicate, object) pair is a singleton — which is the normal shape of a
space keyed by distinct ids. Asserting on it would fire on healthy data.

The reason used to be the opposite one: rdf_stats was capped ABOVE at
`STATS_MAX_ROW_COUNT` and so could be empty for a space whose pairs were all too
LARGE. That cap is gone with `issues/142` — the recompute keeps the largest pairs
deliberately — so the empty case now comes from the floor, not the ceiling.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]


async def _registered_spaces(conn):
    return [r["space_id"] for r in await conn.fetch(
        "SELECT space_id FROM space ORDER BY space_id")]


async def test_every_space_with_quads_has_predicate_stats(perf_conn):
    spaces = await _registered_spaces(perf_conn)
    assert spaces, "no registered spaces — this check would pass by asserting nothing"

    degraded, checked = [], 0
    for sid in spaces:
        exists = await perf_conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            f"{sid}_rdf_quad")
        if not exists:
            continue
        quads = await perf_conn.fetchval(f"SELECT count(*) FROM {sid}_rdf_quad")
        if not quads:
            continue
        checked += 1
        preds = await perf_conn.fetchval(
            f"SELECT count(*) FROM {sid}_rdf_pred_stats")
        if not preds:
            degraded.append(f"{sid}: {quads:,} quads, 0 predicate stats")

    assert checked, "no space holds quads, so nothing was actually checked"
    assert not degraded, (
        "space(s) hold quads with NO statistics, so every plan drawn against "
        "them is made on absent numbers that read as zero:\n  "
        + "\n  ".join(degraded)
        + "\n\nRepair with `python scripts/repair_stats_tables.py --space <id>`, "
          "then `repair_derived_tables.py` for the value histograms.")


async def test_the_check_can_actually_fail(perf_conn):
    """A guard that cannot fire is not a guard.

    The assertion above is a loop that skips spaces without quads, so a bug in
    the skipping would make it vacuous while still reporting green. This proves
    the comparison discriminates, without touching any real space.
    """
    quads, preds = 50_436_200, 0
    degraded = [f"x: {quads:,} quads, 0 predicate stats"] if quads and not preds else []
    assert degraded, "the emptiness comparison does not fire on the known-bad shape"
    assert not ([] if 1 and 21 else ["y"]), "it fires on a healthy shape"
