"""The slot projection, end to end through the API (`issues/208`).

The SQL was measured at 0.76 ms for a 25-entity page and eight columns
(`measure_slot_projection.py`). This runs the same eight columns through
`POST /kgqueries` so the number includes the round trip, and against all THREE
entity paths, because the contract `issues/209` cost us is that a field must not
depend on which path served the page.

Then it prices the alternative a list view uses today: the same page with
`include_entity_graph=True`, which returns ~18,000 quads to render 8 columns.
"""
import asyncio, os, sys, time
sys.path.insert(0, os.getcwd())
os.environ.setdefault("LOCAL_CLIENT_SERVER_URL", "http://localhost:8002")
os.environ.setdefault("LOCAL_CLIENT_AUTH_USERNAME", "admin")
os.environ.setdefault("LOCAL_CLIENT_AUTH_PASSWORD", "admin")
import logging; logging.disable(logging.CRITICAL)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.kgentities_model import (
    FrameCriteria, SlotCriteria, SortCriteria)
from vitalgraph.model.kgqueries_model import PropertyProjection, SlotProjection

KG = "http://vital.ai/ontology/haley-ai-kg#"
NS = "urn:acme:kg"
SPACE, GRAPH = "lead_nurture_grouped", "urn:lead_nurture_grouped"
ENTITY = f"{NS}:entity:Lead"

COMPANY = [f"{NS}:frame:CompanyFrame", f"{NS}:frame:CompanyIdentityFrame"]
ADDRESS = [f"{NS}:frame:CompanyFrame", f"{NS}:frame:CompanyAddressFrame"]
FINANCE = [f"{NS}:frame:CompanyFrame", f"{NS}:frame:CompanyFinancialFrame"]
OPS = [f"{NS}:frame:CompanyFrame", f"{NS}:frame:CompanyOperationsFrame"]
STATUS = [f"{NS}:frame:LeadStatusFrame", f"{NS}:frame:LeadStatusCurrentFrame"]
QUAL = [f"{NS}:frame:LeadStatusFrame", f"{NS}:frame:LeadStatusQualificationFrame"]
METRICS = [f"{NS}:frame:LeadStatusFrame", f"{NS}:frame:LeadStatusMetricsFrame"]


def col(alias, path, slot, cls="KGTextSlot"):
    return SlotProjection(alias=alias, frame_path=path,
                          slot_type=f"{NS}:slot:{slot}", slot_class_uri=KG + cls)


# The eight columns the SQL probe measured, across seven frame paths.
COLUMNS = [
    col("company", COMPANY, "CompanyName"),
    col("status", STATUS, "LeadStatus", "KGURISlot"),
    col("mql", QUAL, "MQLRating"),
    col("city", ADDRESS, "CompanyCity"),
    col("state", ADDRESS, "CompanyState"),
    col("started", OPS, "StartDate", "KGDateTimeSlot"),
    col("sales", FINANCE, "MonthlyGrossSales", "KGDoubleSlot"),
    col("age", METRICS, "LeadAge"),
]

CORE = "http://vital.ai/ontology/vital-core#"
VITAL = "http://vital.ai/ontology/vital#"
AIMP = "http://vital.ai/ontology/vital-aimp#"

# Direct entity properties, read from the quads rather than entity_prop_sort.
PROPERTIES = [
    PropertyProjection(alias="name", property_uri=f"{CORE}hasName"),
    PropertyProjection(alias="obj_status", property_uri=f"{AIMP}hasObjectStatusType"),
    PropertyProjection(alias="modified",
                       property_uri=f"{VITAL}hasObjectModificationDateTime"),
]

SORT = [SortCriteria(sort_type="entity_frame_slot", frame_path=COMPANY,
                     slot_type=f"{NS}:slot:CompanyName",
                     slot_class_uri=KG + "KGTextSlot", sort_order="asc")]
FILTER = [FrameCriteria(
    frame_type=f"{NS}:frame:LeadStatusFrame",
    frame_criteria=[FrameCriteria(
        frame_type=f"{NS}:frame:LeadStatusCurrentFrame",
        slot_criteria=[SlotCriteria(
            slot_type=f"{NS}:slot:LeadStatus", slot_class_uri=KG + "KGURISlot",
            value=f"{NS}:enum:LeadStatus:Qualified", comparator="eq")])])]

# (label, sort, frames, slot columns, property columns, entity graph)
CASES = [
    ("general  + both",          None, None,   True,  True,  False),
    ("fast sort + both",         SORT, None,   True,  True,  False),
    ("fast filter + both",       None, FILTER, True,  True,  False),
    ("fast sort + slots only",   SORT, None,   True,  False, False),
    ("fast sort + props only",   SORT, None,   False, True,  False),
    ("fast sort, entity_graph",  SORT, None,   False, False, True),
    ("fast sort, neither",       SORT, None,   False, False, False),
]


async def main():
    c = VitalGraphClient(); await c.open()
    print(f"  {'case':<28}{'uris':>5}{'ents':>6}{'filled':>8}{'quads':>8}{'ms':>9}")
    first = None
    try:
        for label, sort, frames, project, props, graphs in CASES:
            t0 = time.monotonic()
            r = await c.kgqueries.query_entities(
                space_id=SPACE, graph_id=GRAPH, entity_type=ENTITY,
                sort_criteria=sort, frame_criteria=frames,
                slot_projection=COLUMNS if project else None,
                property_projection=PROPERTIES if props else None,
                include_entity_graph=graphs, page_size=25, offset=0)
            ms = (time.monotonic() - t0) * 1000
            vals = r.entity_values or {}
            filled = sum(1 for per in vals.values()
                         for v in per.values() if v)
            quads = sum(len(v) for v in (r.entity_graphs or {}).values())
            print(f"  {label:<28}{len(r.entity_uris or []):>5}{len(vals):>6}"
                  f"{filled:>8}{quads:>8}{ms:>9.0f}")
            if project and props and first is None and vals:
                first = (r.entity_uris[0], vals[r.entity_uris[0]])
    finally:
        await c.close()
    if first:
        uri, row = first
        print(f"\n  first row  {uri}")
        for k, v in row.items():
            print(f"      {k:<10} {v}")

asyncio.run(main())
