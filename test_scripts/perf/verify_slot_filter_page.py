"""Verify the slot-value FILTER fast path: correct URIs, and pages that partition.

The page half of `issues/161`. A `count_only` request never calls
`fast_slot_filter_page`, so a count-only check proves nothing about paging —
and a page path that repeats or skips rows across offsets is exactly the bug a
count test cannot see.

Asserts on BINDINGS (the returned entity URIs), not on SQL row counts, and
checks that successive pages PARTITION the result set. The path orders by
entity_uuid for that reason even though the caller asked for no sort.

Requires the space to have a `complete` slot_sort_coverage marker, or the fast
path declines and this measures the BGP fallback instead. Run
verify_slot_sort_coverage.py first.

    python test_scripts/perf/verify_slot_filter_page.py
"""
import asyncio, os, sys, time
sys.path.insert(0, os.getcwd())
os.environ.setdefault("LOCAL_CLIENT_SERVER_URL","http://localhost:8002")
os.environ.setdefault("LOCAL_CLIENT_AUTH_USERNAME","admin")
os.environ.setdefault("LOCAL_CLIENT_AUTH_PASSWORD","admin")
os.environ["LOCAL_CLIENT_TIMEOUT"]="180"
import logging; logging.disable(logging.CRITICAL)
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
KG="http://vital.ai/ontology/haley-ai-kg#"; NS="urn:acme:kg"
def sl(st,cls,v,c="eq"): return SlotCriteria(slot_type=st,slot_class_uri=cls,value=v,comparator=c)
def F(*s): return [FrameCriteria(frame_type=f"{NS}:frame:NurtureInfoFrame", slot_criteria=[x]) for x in s]
CAMP=lambda: sl(f"{NS}:slot:NurtureCampaignURI", KG+"KGURISlot","urn:acme:campaign:000")
LEAD=lambda v: sl(f"{NS}:slot:SFLeadId", KG+"KGTextSlot", v)

async def q(c, crit, page_size, offset):
    t0=time.monotonic()
    r=await c.kgqueries.query_entities(space_id="lead_nurture_100k",
        graph_id="urn:lead_nurture_100k", entity_type=f"{NS}:entity:Lead",
        frame_criteria=crit, page_size=page_size, offset=offset)
    return (time.monotonic()-t0)*1000, r

async def main():
    c=VitalGraphClient(); await c.open()
    try:
        ms, r = await q(c, F(LEAD("SYN000000000")), 10, 0)
        print(f"  rare value page: {ms:>6.0f} ms total={r.total_count} uris={len(r.entity_uris)}", flush=True)
        print(f"    uri: {(r.entity_uris or ['<none>'])[0]}", flush=True)

        ms, r = await q(c, F(CAMP()), 5, 0)
        print(f"  campaign page 1: {ms:>6.0f} ms total={r.total_count} uris={len(r.entity_uris)}", flush=True)
        seen, pages = [], []
        for off in (0, 5, 10):
            ms, r = await q(c, F(CAMP()), 5, off)
            pages.append((off, ms, list(r.entity_uris or [])))
            seen += list(r.entity_uris or [])
        for off, ms, u in pages:
            print(f"    offset {off:>3}: {ms:>6.0f} ms  {len(u)} uris", flush=True)
        print(f"  PARTITION: {len(seen)} collected, {len(set(seen))} distinct -> "
              f"{'OK (no overlap)' if len(seen)==len(set(seen)) else 'OVERLAP — pages repeat rows'}", flush=True)

        ms, r = await q(c, F(CAMP(), LEAD("ABSENT000000000")), 10, 0)
        print(f"  empty conjunction page: {ms:>6.0f} ms total={r.total_count} "
              f"uris={len(r.entity_uris or [])} {'OK' if r.total_count==0 else 'WRONG'}", flush=True)
    finally: await c.close()
asyncio.run(main())
