#!/usr/bin/env python3
"""One-time repair of frame form types and frame groupings — `issues/257`, step 4.

THE RULE (decided 2026-10-03, `issues/256` / `issues/257`). `hasFrameGraphURI`
IS the frame graph, and a frame update or upsert REPLACES it (`issues/256`), so
a wrong grouping now loses or keeps data:

    KGFrame                 hasFrameGraphURI = ITSELF, and an explicit
                            hasKGFormType
    Edge_hasKGSlot          hasFrameGraphURI = its source frame
    a slot                  hasFrameGraphURI = the frame whose Edge_hasKGSlot
                            links it
    Edge_hasKGFrame         NO hasFrameGraphURI (structural links are in no
                            frame's graph)

FORM TYPE FIRST (option 2). A frame without `hasKGFormType` is classified by
grouping: no `hasFrameGraphURI` -> Assertion, has one -> Aspect. Giving every
frame its self-grouping would FLIP every unset-and-ungrouped frame from
Assertion to Aspect. So step 1 writes the classification each frame has TODAY
as an explicit value, and only then does anything touch groupings. Nothing
reclassifies.

THROUGH THE SERVER, BY SPARQL UPDATE (decided 2026-10-03). Every change goes
through `/api/graphs/sparql/update`, which takes the grouping locks in the
write's transaction and re-derives the edge, frame_slot, slot-sort and
prop-sort tables for the subjects it touches. Nothing here touches the
database directly. Two cautions from that path's own code: an edge-table sync
failure after an update is logged as non-critical, not raised; and under heavy
concurrent writes its lock acquisition can give up and proceed unlocked
(`issues/174`). Run it in a quiet window.

BOUNDED. Each step SELECTs up to `--batch` subjects that break the rule, fixes
exactly those with one UPDATE (`VALUES`), and repeats until none remain, so
every UPDATE has a fixed size. A step whose SELECT keeps returning the same
subjects is stopped and reported rather than looped on.

DRY RUN BY DEFAULT. Without `--apply` it only counts what each step would
change: that count IS the census, in the rule's own terms. With `--apply` it
counts, repairs, and counts again; every count after must be 0.

For the very large GENERATED spaces (`sp_lead_synth_100k`, 50M quads),
regenerating from the fixed generators may be cheaper than repairing.

    python scripts/repair_frame_groupings.py --space lead_test
    python scripts/repair_frame_groupings.py --space lead_test --apply

Talks to the server named by LOCAL_CLIENT_SERVER_URL (or --server).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KG = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"
PREFIX = f"PREFIX haley: <{KG}>\nPREFIX vital: <{VC}>\n"
ASSERTION = f"<{KG}KGFormType_Assertion>"
ASPECT = f"<{KG}KGFormType_Aspect>"

# Each step: what breaks the rule (a SELECT pattern binding ?x and ?g, plus
# ?f where the fix needs the owning frame), and how to fix one batch.
STEPS = [
    {
        "name": "1a. form type: unset and grouped -> Aspect (today's default)",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:KGFrame .
                    FILTER NOT EXISTS { ?x haley:hasKGFormType ?t }
                    FILTER EXISTS { ?x haley:hasFrameGraphURI ?o } }""",
        "update": f"""INSERT {{ GRAPH ?g {{ ?x haley:hasKGFormType {ASPECT} }} }}
                    WHERE {{ VALUES (?x ?g) {{ %s }} }}""",
    },
    {
        "name": "1b. form type: unset and ungrouped -> Assertion (today's default)",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:KGFrame .
                    FILTER NOT EXISTS { ?x haley:hasKGFormType ?t }
                    FILTER NOT EXISTS { ?x haley:hasFrameGraphURI ?o } }""",
        "update": f"""INSERT {{ GRAPH ?g {{ ?x haley:hasKGFormType {ASSERTION} }} }}
                    WHERE {{ VALUES (?x ?g) {{ %s }} }}""",
    },
    {
        "name": "2. frames grouped with themselves",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:KGFrame .
                    FILTER ( NOT EXISTS { ?x haley:hasFrameGraphURI ?x }
                             || EXISTS { ?x haley:hasFrameGraphURI ?o FILTER (?o != ?x) } ) }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    INSERT { GRAPH ?g { ?x haley:hasFrameGraphURI ?x } }
                    WHERE { VALUES (?x ?g) { %s }
                            OPTIONAL { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } } }""",
    },
    {
        "name": "3. slot edges grouped with their source frame",
        "vars": "?x ?g ?f",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:Edge_hasKGSlot ;
                                  vital:hasEdgeSource ?f .
                    FILTER ( NOT EXISTS { ?x haley:hasFrameGraphURI ?f }
                             || EXISTS { ?x haley:hasFrameGraphURI ?o FILTER (?o != ?f) } ) }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    INSERT { GRAPH ?g { ?x haley:hasFrameGraphURI ?f } }
                    WHERE { VALUES (?x ?g ?f) { %s }
                            OPTIONAL { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } } }""",
    },
    {
        "name": "4. slots grouped with the frame that links them",
        "vars": "?x ?g ?f",
        # A slot linked from more than one frame has no single owner: it is
        # excluded here and reported by `shared_slots` instead of guessed at.
        "where": """GRAPH ?g { ?e vital:vitaltype haley:Edge_hasKGSlot ;
                                  vital:hasEdgeSource ?f ;
                                  vital:hasEdgeDestination ?x .
                    FILTER NOT EXISTS { ?e2 vital:vitaltype haley:Edge_hasKGSlot ;
                                            vital:hasEdgeDestination ?x ;
                                            vital:hasEdgeSource ?f2 . FILTER (?f2 != ?f) }
                    FILTER ( NOT EXISTS { ?x haley:hasFrameGraphURI ?f }
                             || EXISTS { ?x haley:hasFrameGraphURI ?o FILTER (?o != ?f) } ) }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    INSERT { GRAPH ?g { ?x haley:hasFrameGraphURI ?f } }
                    WHERE { VALUES (?x ?g ?f) { %s }
                            OPTIONAL { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } } }""",
    },
    {
        "name": "5. parent -> child edges carry no grouping",
        "vars": "?x ?g",
        "where": """GRAPH ?g { ?x vital:vitaltype haley:Edge_hasKGFrame ;
                                  haley:hasFrameGraphURI ?o }""",
        "update": """DELETE { GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }
                    WHERE { VALUES (?x ?g) { %s }
                            GRAPH ?g { ?x haley:hasFrameGraphURI ?old } }""",
    },
]

SHARED_SLOTS = """SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { GRAPH ?g {
    ?e1 vital:vitaltype haley:Edge_hasKGSlot ; vital:hasEdgeDestination ?s ; vital:hasEdgeSource ?f1 .
    ?e2 vital:vitaltype haley:Edge_hasKGSlot ; vital:hasEdgeDestination ?s ; vital:hasEdgeSource ?f2 .
    FILTER (?f1 != ?f2) } }"""


def _bindings(resp) -> list:
    results = getattr(resp, "results", None) or {}
    return results.get("bindings", []) if isinstance(results, dict) else []


async def _select(client, space, query) -> list:
    from vitalgraph.model.sparql_model import SPARQLQueryRequest
    resp = await client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=PREFIX + query))
    if getattr(resp, "error", None):
        raise RuntimeError(f"query failed: {resp.error}")
    return _bindings(resp)


async def _count(client, space, step) -> int:
    rows = await _select(client, space, f"SELECT (COUNT(*) AS ?n) WHERE {{ {step['where']} }}")
    return int(rows[0]["n"]["value"]) if rows else 0


async def _repair_step(client, space, step, batch) -> int:
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest
    names = step["vars"].split()
    fixed, last = 0, None
    while True:
        rows = await _select(client, space,
                             f"SELECT DISTINCT {step['vars']} WHERE {{ {step['where']} }} LIMIT {batch}")
        if not rows:
            return fixed
        key = tuple(sorted(tuple(r[n.lstrip('?')]["value"] for n in names) for r in rows))
        if key == last:
            raise RuntimeError(f"{step['name']}: the same {len(rows)} subject(s) still break "
                               f"the rule after an update; stopping rather than looping")
        last = key
        values = " ".join("(" + " ".join(f"<{r[n.lstrip('?')]['value']}>" for n in names) + ")"
                          for r in rows)
        resp = await client.sparql.execute_sparql_update(
            space, SPARQLUpdateRequest(update=PREFIX + step["update"] % values))
        if getattr(resp, "error", None) or getattr(resp, "is_success", True) is False:
            raise RuntimeError(f"{step['name']}: update failed: "
                               f"{getattr(resp, 'error', None) or getattr(resp, 'message', resp)}")
        fixed += len(rows)
        print(f"      {step['name'][:2]} batch of {len(rows)} written ({fixed} so far)", flush=True)


async def census(client, space) -> dict:
    out = {}
    for step in STEPS:
        out[step["name"]] = await _count(client, space, step)
    rows = await _select(client, space, SHARED_SLOTS)
    out["slots linked from more than one frame (not repaired)"] = (
        int(rows[0]["n"]["value"]) if rows else 0)
    return out


def _print(label, counts):
    print(f"  {label}:")
    for k, v in counts.items():
        print(f"    {v:>10,}  {k}")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True, action="append",
                    help="space to census/repair; repeat for several")
    ap.add_argument("--apply", action="store_true", help="write; without it, count only")
    ap.add_argument("--batch", type=int, default=500,
                    help="subjects per UPDATE. 925 slots in one update took ~90s "
                         "on a 309k-slot space (the update path re-evaluates its "
                         "bindings per lock pass)")
    ap.add_argument("--timeout", type=float, default=600,
                    help="client read timeout and request budget, seconds. The "
                         "client's default (30s) gives up on an update the server "
                         "then COMMITS, and does not retry a write, so a timed-out "
                         "batch ends the run with the batch applied")
    ap.add_argument("--server", help="server URL (overrides LOCAL_CLIENT_SERVER_URL)")
    a = ap.parse_args()
    if a.server:
        os.environ["LOCAL_CLIENT_SERVER_URL"] = a.server
    profile = os.environ.get("VITALGRAPH_CLIENT_ENVIRONMENT", "local").upper()
    os.environ[f"{profile}_CLIENT_TIMEOUT"] = str(a.timeout)
    os.environ[f"{profile}_CLIENT_REQUEST_BUDGET"] = str(a.timeout)

    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    client = VitalGraphClient()
    await client.open()
    rc = 0
    try:
        print(f"server: {os.environ.get('LOCAL_CLIENT_SERVER_URL')}  "
              f"mode: {'APPLY' if a.apply else 'dry run (counts only)'}")
        for space in a.space:
            print(f"\n== {space}")
            t0 = time.monotonic()
            before = await census(client, space)
            _print("before", before)
            if not a.apply:
                continue
            for step in STEPS:
                if before[step["name"]]:
                    print(f"    {step['name']}")
                    await _repair_step(client, space, step, a.batch)
            after = await census(client, space)
            _print("after", after)
            left = {k: v for k, v in after.items() if v and "not repaired" not in k}
            if left:
                print(f"  NOT CLEAN: {left}")
                rc = 1
            print(f"  {time.monotonic() - t0:.1f}s")
    finally:
        await client.close()
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
