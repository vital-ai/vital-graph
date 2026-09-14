"""Cold-vs-warm bench for the 25-wide entity-graph fan-out.

`issues/192` carried "entity-graph" as a surface with correctness tests and zero
bench cells. Establishing the concurrency baseline covered it only in the WARM
state, and that is worth stating plainly because it is the whole reason the cost
here went unnoticed: `_entity_graph_cache` holds 10,000 entries for 900 seconds,
so a load driver hitting a bounded set of entities measures the cache from its
second request onward and never touches the path this file benches.

What the flag actually does (corrected here, because `issues/192` first recorded
it wrong): `include_entity_graph=True` on a KGQuery does NOT call
`build_entity_graph_collection_query`, and it does not issue one query per
entity. `_fetch_entity_graphs` filters the page against the cache and issues ONE
SPARQL query for all misses, with a `VALUES ?entity_uri { ... }` clause and a
two-branch UNION:

    branch 1   ?entity_uri ?p ?o                     the entity's own triples
    branch 2   ?s haley:hasKGGraphURI ?entity_uri    everything pointing BACK at
               FILTER(?s != ?entity_uri) . ?s ?p ?o  it: frames, slots, edges

Branch 2 is the expensive half and the whole product value of the flag.

WHICH FIXTURE, and why this bench nearly measured nothing
---------------------------------------------------------
`sp_lead_synth_100k` holds 50.5M quads and looks like the obvious fixture. It
has ZERO `hasKGGraphURI` quads, so branch 2 matches nothing there and the flag
returns 8 quads per entity — the entity's own triples and no graph at all. A
bench written against it reports the fan-out at ~100ms with a plausible-looking
latency attached to a query that did nothing, which is the exact failure the
lead bench's `min_results` gate exists to prevent.

Only `lead_nurture_grouped` (74.5M quads, 10.65M `hasKGGraphURI`) carries the
shape at scale, so this bench requires it and skips rather than quietly
measuring a degenerate one. `quads_returned` is asserted for the same reason:
the cheapest possible fan-out is one that collects nothing.

COLD IS ONE-SHOT
----------------
A given page can only be measured cold once — reading it warms it. So there is
no median-of-repetitions available the way other benches take one. Each offset
yields exactly ONE cold sample, and the spread comes from several well-separated
offsets instead. Do not "stabilise" this by repeating an offset; that measures
the cache and would turn the bench green by deleting its subject.

TWO REGIMES, and only one of them is gateable
---------------------------------------------
There are two independent caches in play and conflating them produced a number
that was wrong by a factor of twenty. Measured on this fixture:

    FIRST TOUCH of the space (PostgreSQL buffers cold too)
        base ~0.7-1.2s, cold fan-out 3.2-4.3s, warm ~1.0s
    STEADY STATE (same data, PostgreSQL buffers warm)
        base ~0.78-0.85s, cold fan-out 0.86-1.14s, warm ~0.97-1.05s

So the ~3.5s figure is a FIRST-TOUCH cost — cold PostgreSQL buffers — and not
what the fan-out costs once the working set is resident. In steady state the
fan-out adds roughly 80-290ms for ~18,600 quads.

This bench measures the STEADY STATE, because that is the only regime it can
reproduce: emptying PostgreSQL's buffer cache needs a restart, so a first-touch
number cannot be re-measured on demand and would drift to the steady-state
value the moment anything else read the fixture first.

It also means `warm < cold` IS NOT TRUE HERE and must not be asserted. Once the
buffers are warm the application cache saves little or nothing — the two are
within noise of each other, and warm is sometimes the slower of the two. An
earlier draft gated on `warm < cold` and failed on its first honest run. That
assertion encoded the first-touch regime as though it were universal.

Query tier: read-only, no writes, no fixture construction.
"""
from __future__ import annotations

import statistics
import time

import pytest

from .conftest import skip_no_api, api_space_exists

pytestmark = [pytest.mark.performance, skip_no_api,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "lead_nurture_grouped"
GRAPH = "urn:lead_nurture_grouped"
KGENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"

PAGE_SIZE = 25

# Well separated so no two pages share entities, and deep enough that the base
# query is doing ordinary paging work rather than answering from the first rows.
OFFSETS = [1000, 1500, 2000, 2500, 3000]

# A page of this fixture returns ~745 quads per entity. Far below that means
# branch 2 stopped matching -- a fixture or predicate change, not a speedup.
MIN_QUADS = 25 * 100


async def _page(client, offset, include_graph):
    """One request. Returns (wall_ms, n_uris, n_graphs, n_quads)."""
    t0 = time.perf_counter()
    resp = await client.kgqueries.query_entities(
        space_id=SPACE, graph_id=GRAPH, entity_type=KGENTITY,
        include_entity_graph=include_graph, page_size=PAGE_SIZE, offset=offset)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    graphs = resp.entity_graphs or {}
    return (wall_ms, len(resp.entity_uris or []), len(graphs),
            sum(len(v) for v in graphs.values()))


@pytest.mark.bench("query.entity_graph.fanout")
async def test_entity_graph_fanout_cold_vs_warm(perf_client, perf_record):
    if not await api_space_exists(perf_client, SPACE):
        pytest.skip(f"space {SPACE} not known to the API — this bench needs the "
                    f"only fixture carrying hasKGGraphURI at scale")

    # Warm the connection, the auth token, AND the buffers behind branch 2 of
    # the UNION. The last one matters: this bench measures the STEADY STATE by
    # design (see the module docstring), and on a freshly restarted stack the
    # first fan-out pays a cold-buffer cost 4x the steady-state one. Issuing a
    # real fan-out at an offset that is never measured puts the run in the
    # regime it claims to report, instead of letting the first sample decide.
    await _page(perf_client, OFFSETS[0] - PAGE_SIZE, True)

    base, cold, warm = [], [], []
    quads_seen = uris_seen = graphs_seen = 0

    for off in OFFSETS:
        # Base FIRST: it does not populate the entity-graph cache (the flag is
        # off, so `_fetch_entity_graphs` is never called), so it cannot warm the
        # cold sample that follows it.
        b_ms, n_uris, _, _ = await _page(perf_client, off, False)
        c_ms, _, n_graphs, n_quads = await _page(perf_client, off, True)
        w_ms, _, _, _ = await _page(perf_client, off, True)

        base.append(b_ms)
        cold.append(c_ms)
        warm.append(w_ms)
        uris_seen = max(uris_seen, n_uris)
        graphs_seen = max(graphs_seen, n_graphs)
        quads_seen = max(quads_seen, n_quads)

    med_base = statistics.median(base)
    med_cold = statistics.median(cold)
    med_warm = statistics.median(warm)

    perf_record(
        kind="api", dataset=SPACE,
        metrics={
            "page_no_graph_ms": round(med_base, 1),
            "page_cold_ms": round(med_cold, 1),
            "page_warm_ms": round(med_warm, 1),
            # The fan-out's OWN cost, which is the number the flag is
            # responsible for and the only one a caller can avoid by not
            # setting it. Separated from the page cost because the base query
            # dominates the absolute figure and would mask a fan-out
            # regression inside its own noise.
            "fanout_cold_ms": round(med_cold - med_base, 1),
            "cold_min_ms": round(min(cold), 1),
            "cold_max_ms": round(max(cold), 1),
            "quads_returned": quads_seen,
            "page_size": PAGE_SIZE,
            "samples": len(OFFSETS),
        },
        notes=(f"25-wide entity-graph fan-out on {SPACE}: cold vs cached. "
               f"Each offset gives ONE cold sample; cold cannot be repeated."))

    # A fan-out that collected nothing is the cheapest possible one. See the
    # module docstring -- the obvious fixture fails exactly this way.
    assert uris_seen == PAGE_SIZE, f"page returned {uris_seen} uris, expected {PAGE_SIZE}"
    assert graphs_seen == PAGE_SIZE, (
        f"only {graphs_seen} of {PAGE_SIZE} entities came back with a graph")
    assert quads_seen >= MIN_QUADS, (
        f"fan-out returned {quads_seen} quads for {PAGE_SIZE} entities "
        f"(expected >= {MIN_QUADS}). Branch 2 of the UNION has stopped "
        f"matching -- check hasKGGraphURI in {SPACE} before reading the timing "
        f"as an improvement.")

    # Deliberately NOT asserting warm < cold. In the steady state the two are
    # within noise and warm is sometimes slower; see the module docstring. The
    # cache's value is avoiding a cold-buffer read, which shows up on first
    # touch and not here.
    #
    # What IS gateable is that the fan-out stays bounded relative to the page it
    # decorates. A wide band, because the base query dominates the absolute
    # figure and both move with machine load -- this catches the fan-out
    # becoming the dominant cost, not a 20% drift.
    assert med_cold < med_base * 6, (
        f"cold fan-out ({med_cold:.0f}ms) is more than 6x the same page without "
        f"it ({med_base:.0f}ms). In steady state the fan-out adds a fraction of "
        f"the base query; this size of gap means either the buffers were cold "
        f"(re-run) or branch 2 of the UNION has lost its index.")
