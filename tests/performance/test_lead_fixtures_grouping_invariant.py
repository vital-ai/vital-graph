"""Guard: a lead fixture's declared grouping state must match its loaded data.

`issues/204`. Every object the application writes carries `hasKGGraphURI`, so a
fixture without it holds data the write path could not have produced. Seven of
the eight lead datasets on disk predate the `issues/171` generator fix and lack
it entirely.

The reason this needs a guard rather than a fix-and-forget is the failure mode.
Entity-graph retrieval is a two-branch UNION and the first branch pins the
entity's own URI, so an ungrouped fixture still answers — with ~8 quads per
entity instead of ~745. No error, no warning, just a fast green number that
means nothing. `repair_grouping_self_link.py` recorded the same shape: "619
broken URIs across 12 spaces produced no visible symptom."

KNOWN_UNGROUPED is an allowlist that must SHRINK. It exists so this test can be
honest about today's state without turning the suite red for a data problem
that takes hours of regeneration to fix, while still failing the moment
something NEW loses the invariant — which is the case a silent UNION would
otherwise hide until someone benched it.
"""
from __future__ import annotations

import pytest

from .conftest import skip_no_pg
from .lead_fixtures import ALL, DUP, DEPTH1, EMPTY, TYPES, has_grouping_uris

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

CANDIDATES = ALL + [DUP, DEPTH1, EMPTY, TYPES]

# Stale as of 2026-09-14. Remove a name when its data is regenerated -- and set
# `grouped=True` on the fixture in the same change, or this test will fail on
# the mismatch, which is the point.
KNOWN_UNGROUPED = {
    "sp_lead_synth",
    "sp_lead_synth_10k",
    "sp_lead_synth_100k",
    "sp_lead_types",
    "sp_lead_dup",
    "sp_lead_depth1",
    "sp_lead_empty",
    "sp_sql_lead_dataset",
}


@pytest.mark.parametrize("fx", CANDIDATES, ids=[f.label for f in CANDIDATES])
async def test_declared_grouping_matches_loaded_data(perf_conn, fx):
    exists = await perf_conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        f"{fx.space}_rdf_quad")
    if not exists:
        pytest.skip(f"space {fx.space} is not loaded here")

    actual = await has_grouping_uris(perf_conn, fx)

    if fx.grouped:
        assert actual, (
            f"{fx.label} is DECLARED grouped but its loaded data has no "
            f"hasKGGraphURI. Entity-graph retrieval against it will return the "
            f"entity's own triples only -- roughly 8 quads instead of ~745 -- "
            f"and report it as a fast success. See issues/204.")
        return

    if actual:
        pytest.fail(
            f"{fx.label} HAS grouping URIs but is declared ungrouped. If it was "
            f"regenerated, set grouped=True on the fixture and drop it from "
            f"KNOWN_UNGROUPED so entity-graph work can find it. See issues/204.")

    assert fx.space in KNOWN_UNGROUPED, (
        f"{fx.label} has lost the grouping invariant and is not a known-stale "
        f"fixture. Something regenerated or reloaded it WITHOUT the dual "
        f"grouping URIs the write path always sets. Entity-graph queries "
        f"against it will now silently return the entity's own triples only. "
        f"See issues/204.")
