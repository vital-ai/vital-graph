"""Does a fast-path entity query lose `include_entity_graph`? (issues/209)

The issue is written from the dispatch: `kgquery_endpoint.py:876` hydrates
`entity_graphs`, and both fast paths return at `:488` / `:595` ABOVE it. This
runs it instead, because `issues/206` is what a code reading costs when it is
not checked against what executes.

Four requests against `lead_nurture_grouped`, all with include_entity_graph=True:

    baseline   entity_type only        -> general pipeline, graphs EXPECTED
    sort       + a slot-value sort     -> `can_serve`, graphs in question
    filter     + frame-criteria eq     -> `can_serve_filter`, graphs in question
    control    the sort, flag OFF      -> proves the fast path is what served

Reads the server log after each to name the path that actually ran, so a
"no graphs" result cannot be confused with a query that fell through.
"""
import asyncio, os, subprocess, sys, time
sys.path.insert(0, os.getcwd())
os.environ.setdefault("LOCAL_CLIENT_SERVER_URL", "http://localhost:8002")
os.environ.setdefault("LOCAL_CLIENT_AUTH_USERNAME", "admin")
os.environ.setdefault("LOCAL_CLIENT_AUTH_PASSWORD", "admin")
os.environ["LOCAL_CLIENT_TIMEOUT"] = "600"
import logging; logging.disable(logging.CRITICAL)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.kgentities_model import (
    FrameCriteria, SlotCriteria, SortCriteria)

KG = "http://vital.ai/ontology/haley-ai-kg#"
NS = "urn:acme:kg"
SPACE = "lead_nurture_grouped"
GRAPH = f"urn:{SPACE}"
ENTITY = f"{NS}:entity:Lead"

SORT = [SortCriteria(
    sort_type="entity_frame_slot",
    frame_path=[f"{NS}:frame:CompanyFrame", f"{NS}:frame:CompanyIdentityFrame"],
    slot_type=f"{NS}:slot:CompanyName",
    slot_class_uri=f"{KG}KGTextSlot", sort_order="asc")]

FILTER = [FrameCriteria(
    frame_type=f"{NS}:frame:LeadStatusFrame",
    frame_criteria=[FrameCriteria(
        frame_type=f"{NS}:frame:LeadStatusCurrentFrame",
        slot_criteria=[SlotCriteria(
            slot_type=f"{NS}:slot:LeadStatus",
            slot_class_uri=f"{KG}KGURISlot",
            value=f"{NS}:enum:LeadStatus:Qualified", comparator="eq")])])]

CASES = [
    ("baseline  (no sort, no filter)", None, None, True),
    ("sort      (can_serve)",          SORT, None, True),
    ("filter    (can_serve_filter)",   None, FILTER, True),
    ("control   (sort, flag OFF)",     SORT, None, False),
]


def log_tail(since):
    out = subprocess.run(
        ["docker", "logs", "--since", since, "vitalgraph-test-app"],
        capture_output=True, text=True)
    lines = (out.stdout + out.stderr).splitlines()
    for key in ("Entity slot sort via entity_slot_sort",
                "Entity slot filter via entity_slot_sort",
                "Entity graph fetch", "FILTER fast path declined",
                "Entity query:"):
        hit = [l for l in lines if key in l]
        if hit:
            yield hit[-1].strip()[-140:]


async def main():
    c = VitalGraphClient(); await c.open()
    print(f"  {'case':<34}{'uris':>6}{'total':>9}{'graphs':>8}{'quads':>9}"
          f"{'ms':>9}")
    try:
        for label, sort, frames, flag in CASES:
            since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 1))
            t0 = time.monotonic()
            r = await c.kgqueries.query_entities(
                space_id=SPACE, graph_id=GRAPH, entity_type=ENTITY,
                sort_criteria=sort, frame_criteria=frames,
                include_entity_graph=flag, page_size=25, offset=0)
            ms = (time.monotonic() - t0) * 1000
            graphs = r.entity_graphs or {}
            quads = sum(len(v) for v in graphs.values())
            print(f"  {label:<34}{len(r.entity_uris or []):>6}"
                  f"{r.total_count if r.total_count is not None else -1:>9}"
                  f"{len(graphs):>8}{quads:>9}{ms:>9.0f}")
            for line in log_tail(since):
                print(f"        | {line}")
    finally:
        await c.close()

asyncio.run(main())
