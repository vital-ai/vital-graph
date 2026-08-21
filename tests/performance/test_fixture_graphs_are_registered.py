"""Every fixture's graph must exist in the `graph` catalog, not just in the data.

`sp_graph_synth_100k` held 19,632,351 quads under `urn:sp_graph_synth_100k`
with NO row in `graph`. The data was queryable by naming the URI, so every
bench that hardcodes the graph passed; but anything reading the catalog — a
graph listing, a UI picker, a sweep over "the graphs in this space" — saw an
empty space.

It was not one fixture. `sp_graph_synth_10k` and `wordnet_frames` were in the
same state, all three loaded through `scripts/load_wordnet_csv.py`, which
COPYs quads with a context_uuid and never registered anything.
`sp_lead_synth_100k`, loaded by another path, had its row — which is why the
gap survived: the fixture people looked at most was fine.

The loader now registers from the contexts actually present. This asserts the
result, in both directions:

  * every graph a fixture DECLARES is in the catalog, and
  * every context present in the quads is too, so a fixture that grows a second
    graph cannot half-register.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg
from .graph_fixtures import SYNTH, SKEW
from .lead_fixtures import ALL, DUP

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# (space, declared graph) for every fixture the perf suite draws from.
FIXTURES = sorted(
    {(fx.space, fx.graph) for fx in list(SYNTH) + [SKEW] + list(ALL) + [DUP]}
    | {("wordnet_frames", "urn:wordnet_frames")})


async def _skip_if_absent(perf_conn, space):
    """A fixture may legitimately not exist in every environment.

    The host cluster and the docker test stack do not carry the same set —
    `sp_graph_skew_2k` is vg-test only. Absence is not a registration gap, and
    the check that matters (data present, catalog silent) needs the data to be
    there to mean anything. Mirrors test_fixture_indexes_match_schema.
    """
    exists = await perf_conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        f"{space}_rdf_quad")
    if not exists:
        pytest.skip(f"space {space} not present in this environment")


@pytest.mark.parametrize("space,graph", FIXTURES)
async def test_declared_graph_is_registered(perf_conn, space, graph):
    await _skip_if_absent(perf_conn, space)
    row = await perf_conn.fetchrow(
        "SELECT graph_uri FROM graph WHERE space_id = $1 AND graph_uri = $2",
        space, graph)
    assert row is not None, (
        f"{space} holds data in {graph} but has no `graph` catalog row for it. "
        f"Register it — scripts/load_wordnet_csv.py does this at the end of a "
        f"load; a fixture loaded another way needs space_impl.create_graph.")


@pytest.mark.parametrize("space,graph", FIXTURES)
async def test_every_context_in_the_data_is_registered(perf_conn, space, graph):
    """Catches the half-registered case the declared-graph check cannot see."""
    await _skip_if_absent(perf_conn, space)
    unregistered = await perf_conn.fetch(
        f"""
        SELECT t.term_text
        FROM (SELECT DISTINCT context_uuid FROM {space}_rdf_quad) c
        JOIN {space}_term t ON t.term_uuid = c.context_uuid
        WHERE NOT EXISTS (SELECT 1 FROM graph g
                          WHERE g.space_id = $1 AND g.graph_uri = t.term_text)
        """, space)
    assert not unregistered, (
        f"{space} has quads in {[r['term_text'] for r in unregistered]}, "
        f"which the `graph` catalog does not list")
