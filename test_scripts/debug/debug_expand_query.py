#!/usr/bin/env python3
"""
Check the graph-visualization "Expand" query against wordnet_frames.

The UI's expand returned 0 rows for a KGEntity that clearly sits in frame slots.
The old query joined slots to frames through hasFrameGraphURI, a predicate that
does not exist in this dataset — frames reach their slots via Edge_hasKGSlot.
This runs the old and new shapes side by side.

Mirrors buildExpandQuery() in frontend/src/hooks/useGraphVisualization.ts.

Usage:  PGUSER=<user> python test_scripts/debug/debug_expand_query.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql_dev.jena_sparql_orchestrator import SparqlOrchestrator

SPACE = os.environ.get("SPACE", "wordnet_frames")
ENTITY = os.environ.get(
    "ENTITY", "http://vital.ai/haley.ai/app/KGEntity/1716488380982_691752735"
)

VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
REL_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGRelationTypeDescription"
FRAME_GRAPH_URI = "http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI"
SLOT_ROLE_SRC = "urn:hasSourceEntity"
SLOT_ROLE_DST = "urn:hasDestinationEntity"

OLD = f"""
SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {{
  {{
    BIND(<{ENTITY}> AS ?srcEntity)
    ?mySlot <{SLOT_VALUE}> ?srcEntity .
    ?mySlot <{FRAME_GRAPH_URI}> ?frame .
    ?frame <{FRAME_TYPE_DESC}> ?relationType .
    ?otherSlot <{FRAME_GRAPH_URI}> ?frame .
    ?otherSlot <{SLOT_VALUE}> ?dstEntity .
    FILTER(?otherSlot != ?mySlot)
    ?srcEntity <{VITAL_NAME}> ?srcName .
    ?dstEntity <{VITAL_NAME}> ?dstName .
  }}
}}
"""


def frame_branch(anchor):
    other = "dst" if anchor == "src" else "src"
    anchor_role = SLOT_ROLE_SRC if anchor == "src" else SLOT_ROLE_DST
    other_role = SLOT_ROLE_DST if anchor == "src" else SLOT_ROLE_SRC
    return f"""
  {{
    BIND(<{ENTITY}> AS ?{anchor}Entity)
    ?anchorSlot <{SLOT_VALUE}> <{ENTITY}> .
    ?anchorSlot <{SLOT_TYPE}> <{anchor_role}> .
    ?anchorSlotEdge <{EDGE_DST}> ?anchorSlot .
    ?anchorSlotEdge <{EDGE_SRC}> ?frame .
    ?otherSlotEdge <{EDGE_SRC}> ?frame .
    ?otherSlotEdge <{EDGE_DST}> ?otherSlot .
    ?otherSlot <{SLOT_TYPE}> <{other_role}> .
    ?otherSlot <{SLOT_VALUE}> ?{other}Entity .
    ?frame <{FRAME_TYPE_DESC}> ?relationType .
    <{ENTITY}> <{VITAL_NAME}> ?{anchor}Name .
    ?{other}Entity <{VITAL_NAME}> ?{other}Name .
  }}"""


NEW = f"""
SELECT ?srcEntity ?srcName ?dstEntity ?dstName ?frame ?relationType WHERE {{
  {frame_branch('src')}
  UNION
  {frame_branch('dst')}
  UNION
  {{
    BIND(<{ENTITY}> AS ?srcEntity)
    ?rel <{EDGE_SRC}> <{ENTITY}> .
    ?rel <{EDGE_DST}> ?dstEntity .
    ?rel <{REL_TYPE_DESC}> ?relationType .
    BIND(?rel AS ?frame)
    <{ENTITY}> <{VITAL_NAME}> ?srcName .
    ?dstEntity <{VITAL_NAME}> ?dstName .
  }}
  UNION
  {{
    BIND(<{ENTITY}> AS ?dstEntity)
    ?rel <{EDGE_DST}> <{ENTITY}> .
    ?rel <{EDGE_SRC}> ?srcEntity .
    ?rel <{REL_TYPE_DESC}> ?relationType .
    BIND(?rel AS ?frame)
    ?srcEntity <{VITAL_NAME}> ?srcName .
    <{ENTITY}> <{VITAL_NAME}> ?dstName .
  }}
}}
"""

_META_SUFFIXES = ("__type", "__uuid", "__lang", "__datatype", "__num", "__bool", "__dt")


async def run(orch, label, sparql):
    t0 = time.monotonic()
    result = await orch.execute(sparql)
    ms = (time.monotonic() - t0) * 1000
    if not result.ok:
        print(f"{label}: ERROR {result.error}")
        return
    print(f"{label}: {result.row_count} rows in {ms:.0f} ms")
    for row in result.rows[:5]:
        print("   ", {
            k: str(v)[-45:] for k, v in row.items()
            if not k.endswith(_META_SUFFIXES)
        })


async def main():
    async with SparqlOrchestrator(space_id=SPACE) as orch:
        await run(orch, "OLD (hasFrameGraphURI)", OLD)
        await run(orch, "NEW (Edge_hasKGSlot)  ", NEW)


if __name__ == "__main__":
    asyncio.run(main())
