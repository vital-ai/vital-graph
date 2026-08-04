#!/usr/bin/env python3
"""
Debug script to test the KG Types SPARQL query against the service.

Tests both the BIND version and the direct-variable version to see
which one properly returns entityTypeDesc.
"""

import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPACE_ID = "sp_kg_types"

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"

KGTYPE_CLASSES = [
    "http://vital.ai/ontology/haley-ai-kg#KGType",
    "http://vital.ai/ontology/haley-ai-kg#KGEntityType",
    "http://vital.ai/ontology/haley-ai-kg#KGFrameType",
    "http://vital.ai/ontology/haley-ai-kg#KGSlotType",
    "http://vital.ai/ontology/haley-ai-kg#KGRelationType",
]

VALUES_CLAUSE = " ".join(f"<{c}>" for c in KGTYPE_CLASSES)

# Query 1: Using BIND (original)
QUERY_BIND = f"""
SELECT ?entity ?name ?entityTypeDesc WHERE {{
  VALUES ?type {{ {VALUES_CLAUSE} }}
  ?entity <{RDF_TYPE}> ?type .
  ?entity <{VITAL_NAME}> ?name .
  BIND(?type AS ?entityTypeDesc)
}}
LIMIT 10
"""

# Query 2: Using variable directly (fixed version)
QUERY_DIRECT = f"""
SELECT ?entity ?name ?entityTypeDesc WHERE {{
  VALUES ?entityTypeDesc {{ {VALUES_CLAUSE} }}
  ?entity <{RDF_TYPE}> ?entityTypeDesc .
  ?entity <{VITAL_NAME}> ?name .
}}
LIMIT 10
"""

# Query 3: Select ?type directly without renaming
QUERY_TYPE_VAR = f"""
SELECT ?entity ?name ?type WHERE {{
  VALUES ?type {{ {VALUES_CLAUSE} }}
  ?entity <{RDF_TYPE}> ?type .
  ?entity <{VITAL_NAME}> ?name .
}}
LIMIT 10
"""


async def run_query(client: VitalGraphClient, label: str, sparql: str):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"Query:\n{sparql.strip()}\n")

    try:
        request = SPARQLQueryRequest(query=sparql)
        response = await client.sparql.execute_sparql_query(SPACE_ID, request)

        # Print raw response structure
        if hasattr(response, 'model_dump'):
            raw = response.model_dump()
        else:
            raw = response

        # Extract bindings
        bindings = None
        if isinstance(raw, dict):
            if 'results' in raw and isinstance(raw['results'], dict):
                bindings = raw['results'].get('bindings', [])
            elif 'bindings' in raw:
                bindings = raw['bindings']

        if bindings is None:
            print(f"  Raw response keys: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}")
            print(f"  Full response (first 500 chars): {json.dumps(raw, indent=2, default=str)[:500]}")
            return

        print(f"  Result count: {len(bindings)}")
        print(f"  Variables in first result: {list(bindings[0].keys()) if bindings else 'N/A'}")
        print()

        for i, row in enumerate(bindings[:5]):
            print(f"  Row {i}:")
            for k, v in row.items():
                if isinstance(v, dict):
                    print(f"    {k}: {v.get('value', v)} (type={v.get('type', '?')})")
                else:
                    print(f"    {k}: {v}")
            print()

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")


VITAL_TYPE = "http://vital.ai/ontology/vital-core#vitaltype"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"

KGTYPE_EDGE_CLASSES = [
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGFrameType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasPartOfKGFrameType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityTypePartOfKGFrameType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasSameAsKGType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelationType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasOutgoingKGRelationType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasIncomingKGRelationType",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGAnnotation",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlotType",
]

EDGE_VALUES = " ".join(f"<{c}>" for c in KGTYPE_EDGE_CLASSES)

# Query 4: Expand query with srcType/dstType
# Use a known entity from Query 1 results
QUERY_EXPAND = f"""
SELECT ?srcEntity ?srcName ?srcType ?dstEntity ?dstName ?dstType ?frame ?relationType WHERE {{
  {{
    BIND(<urn:vitalgraph:framenet:frame-type:Filling> AS ?srcEntity)
    ?frame <{VITAL_TYPE}> ?relationType .
    ?frame <{VITAL_EDGE_SRC}> ?srcEntity .
    ?frame <{VITAL_EDGE_DST}> ?dstEntity .
    ?dstEntity <{VITAL_NAME}> ?dstName .
    ?srcEntity <{VITAL_NAME}> ?srcName .
    VALUES ?relationType {{ {EDGE_VALUES} }}
    ?srcEntity <{RDF_TYPE}> ?srcType . VALUES ?srcType {{ {VALUES_CLAUSE} }}
    ?dstEntity <{RDF_TYPE}> ?dstType . VALUES ?dstType {{ {VALUES_CLAUSE} }}
  }}
  UNION
  {{
    BIND(<urn:vitalgraph:framenet:frame-type:Filling> AS ?dstEntity)
    ?frame <{VITAL_TYPE}> ?relationType .
    ?frame <{VITAL_EDGE_SRC}> ?srcEntity .
    ?frame <{VITAL_EDGE_DST}> ?dstEntity .
    ?srcEntity <{VITAL_NAME}> ?srcName .
    ?dstEntity <{VITAL_NAME}> ?dstName .
    VALUES ?relationType {{ {EDGE_VALUES} }}
    ?srcEntity <{RDF_TYPE}> ?srcType . VALUES ?srcType {{ {VALUES_CLAUSE} }}
    ?dstEntity <{RDF_TYPE}> ?dstType . VALUES ?dstType {{ {VALUES_CLAUSE} }}
  }}
}}
LIMIT 10
"""


async def main():
    print("Connecting to VitalGraph...")
    client = VitalGraphClient()
    await client.open()
    print("Connected.\n")

    try:
        await run_query(client, "Query 1: BIND(?type AS ?entityTypeDesc)", QUERY_BIND)
        await run_query(client, "Query 2: Direct ?entityTypeDesc variable", QUERY_DIRECT)
        await run_query(client, "Query 3: Select ?type directly", QUERY_TYPE_VAR)
        await run_query(client, "Query 4: Expand with srcType/dstType", QUERY_EXPAND)
    finally:
        await client.close()
        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
