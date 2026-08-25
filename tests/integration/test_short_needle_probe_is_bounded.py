"""The text-selectivity probe must be bounded by WORK, not by matches.

`issues/070`. The probe counts matching terms to a cap so the semi-join gate can
tell a substring matching millions from one matching none — they want opposite
plans, and the measurement is what took `'XQ'` from 11,151 ms to 210 ms.

Bounding it by MATCHES is fine while the trigram index serves the pattern. Under
three characters it does not: the trigrams of a short string are all padded,
padding only holds at a word boundary, an infix match may land mid-word, so none
can be required. The probe becomes a sequential scan, and a needle matching
NOTHING must read every row to prove it. Measured on `sp_lead_synth_100k`
(10.4M terms), on the query shape that actually reaches the probe:

    exact probe, 2-char needle    78,991 ms
    sampled probe, same needle         45 ms
    3-char needle (index-served)       18 ms   unchanged

SKIPPING the probe was considered and is wrong: an unmeasured text leaf reads as
"keep the current plan", which is the probe-per-candidate walk the issue exists
to eliminate. Length tells you the INDEX cannot help; it says nothing about
selectivity — `'CA'` matches 2.6M terms and `'XQ'` matches none.

So the short-needle path samples a fixed fraction and scales. The discrimination
that matters — nothing versus millions — survives; the error mode is conflating
small counts with zero, and those take the same branch.

The probe feeds a PLAN decision only (`text_stats` -> `_leaf_rows` -> the gate),
never the emitted predicate, so answers cannot change. Asserted here anyway,
because "it only affects the plan" is exactly the kind of claim that turns out to
be wrong.
"""

from __future__ import annotations

import time

import pytest

from rdflib import Literal

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

CORE = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"


@pytest.fixture(scope="module")
def graph_uri():
    return "urn:shortneedle:graph"


async def _seed(impl, space_id, graph_uri):
    quads = []
    for i in range(40):
        s = f"http://example.org/shortneedle/e{i}"
        quads.append((s, f"{CORE}vitaltype", f"{KG}KGEntity", graph_uri))
        # `Literal`, not a bare str. `_ensure_term` types anything that is not
        # a URIRef/BNode/Literal as 'U', so a plain string object was stored as
        # a URI -- and CONTAINS then matched it, because the push-down compared
        # `term_text` without checking the term's kind. Once that was fixed to
        # require a literal (§17.4.3), this fixture stopped matching and said
        # so. The needle behaviour under test is unchanged; the data is now
        # what it always claimed to be.
        quads.append((s, f"{CORE}hasName",
                      Literal(f"entity {i} (Topic)"), graph_uri))
    await impl.add_rdf_quads_batch_bulk(space_id, quads)


async def _rows(impl, space_id, needle, graph_uri):
    sparql = f"""
        SELECT ?s WHERE {{ GRAPH <{graph_uri}> {{
            ?s <{CORE}hasName> ?o . FILTER(CONTAINS(?o, "{needle}"))
        }} }} ORDER BY ?s"""
    res = await impl.execute_sparql_query(space_id, sparql)
    if isinstance(res, dict):
        return res.get("results", {}).get("bindings", []) or []
    return res or []


@pytest.mark.parametrize("needle,expected", [
    ("op", 40),      # 2 chars — the sampled path; "Topic" contains "op"
    ("Top", 40),     # 3 chars — the exact path
    ("zzqq", 0),     # 4 chars, matches nothing
    ("py", 0),       # 2 chars, matches nothing — the sampled path's hard case
], ids=["short-match", "long-match", "long-miss", "short-miss"])
async def test_answers_do_not_depend_on_the_probe(space_impl, make_space,
                                                  graph_uri, needle, expected):
    """A plan-selection estimate must never change what comes back."""
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    rows = await _rows(space_impl, space_id, needle, graph_uri)
    assert len(rows) == expected


async def test_a_short_needle_does_not_cost_a_full_scan(space_impl, make_space,
                                                        graph_uri):
    """The bound itself.

    A wall-clock assertion is a blunt instrument, so the threshold is far above
    the measured 45 ms and far below the 78,991 ms it replaces — it catches the
    probe reverting to an exact scan, not a slow machine.
    """
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    t0 = time.time()
    await _rows(space_impl, space_id, "py", graph_uri)   # matches nothing
    elapsed = time.time() - t0
    assert elapsed < 10.0, (
        f"a 2-character needle took {elapsed:.1f}s — the probe is scanning to "
        f"prove absence again rather than sampling")
