#!/usr/bin/env python3
"""
Debug script: Check kGGraphURI distribution in the multi-org test space.

Uses VitalGraphClient SPARQL endpoint to understand which subjects
share the same kGGraphURI, to diagnose why delete_entity_graph deletes too much.
"""

import asyncio
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.WARNING)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPACE_ID = "space_multi_org_crud_test"
GRAPH_ID = "urn:multi_org_crud_graph"


async def sparql_query(client: VitalGraphClient, query: str) -> list:
    """Execute SPARQL SELECT via client and return bindings."""
    req = SPARQLQueryRequest(query=query)
    resp = await client.sparql.execute_sparql_query(SPACE_ID, req)
    results = resp.results if hasattr(resp, 'results') and resp.results else {}
    return results.get("bindings", [])


async def main():
    client = VitalGraphClient()
    await client.open()

    print("=" * 80)
    print("  kGGraphURI Distribution Analysis")
    print("=" * 80)

    # Query 1: Count subjects per kGGraphURI value
    bindings1 = await sparql_query(client, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?graphURI (COUNT(DISTINCT ?s) AS ?subjectCount) WHERE {{
            GRAPH <{GRAPH_ID}> {{
                ?s haley:hasKGGraphURI ?graphURI .
            }}
        }}
        GROUP BY ?graphURI
        ORDER BY DESC(?subjectCount)
    """)

    print("\n--- Subjects per kGGraphURI ---")
    total = 0
    for b in bindings1:
        uri = b["graphURI"]["value"]
        cnt = int(b["subjectCount"]["value"])
        total += cnt
        short = uri.split("/")[-1] if "/" in uri else uri
        print(f"  {cnt:4d} subjects  {short}")
    print(f"\n  Total subjects with kGGraphURI: {total}")
    print(f"  Distinct kGGraphURI values: {len(bindings1)}")

    # Query 2: For Global Finance Group, show types of objects sharing its kGGraphURI
    gf_uri = "http://vital.ai/test/kgentity/organization/global_finance_group"
    bindings2 = await sparql_query(client, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT ?s ?vtype WHERE {{
            GRAPH <{GRAPH_ID}> {{
                ?s haley:hasKGGraphURI <{gf_uri}> .
                ?s vital:vitaltype ?vtype .
            }}
        }}
        ORDER BY ?vtype ?s
    """)

    print(f"\n--- Objects with kGGraphURI = global_finance_group ---")
    type_counts = Counter()
    for b in bindings2:
        vtype = b["vtype"]["value"].split("#")[-1]
        subj = b["s"]["value"]
        for prefix in ["http://vital.ai/test/kgentity/", "urn:"]:
            if subj.startswith(prefix):
                subj = subj[len(prefix):]
                break
        type_counts[vtype] += 1
        print(f"  {vtype:35s}  {subj}")

    print(f"\n  Summary by type:")
    for vtype, cnt in type_counts.most_common():
        print(f"    {cnt:3d}  {vtype}")
    print(f"  Total: {sum(type_counts.values())} subjects")

    # Query 3: Total KGEntity count (same as endpoint _build_count_query)
    bindings3 = await sparql_query(client, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
            GRAPH <{GRAPH_ID}> {{
                {{
                  ?entity vital-core:vitaltype haley:KGEntity .
                }} UNION {{
                  ?entity vital-core:vitaltype haley:KGNewsEntity .
                }} UNION {{
                  ?entity vital-core:vitaltype haley:KGProductEntity .
                }} UNION {{
                  ?entity vital-core:vitaltype haley:KGWebEntity .
                }}
            }}
        }}
    """)
    if bindings3:
        print(f"\n--- Endpoint count query result: {bindings3[0]['count']['value']} ---")

    # Query 4: Run the exact count query from KGEntityListProcessor._build_count_query
    exact_count_query = (
        "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>\n"
        "PREFIX vital-core: <http://vital.ai/ontology/vital-core#>\n"
        "SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {\n"
        f"  GRAPH <{GRAPH_ID}> {{\n"
        "    {\n"
        "      ?entity vital-core:vitaltype haley:KGEntity .\n"
        "    } UNION {\n"
        "      ?entity vital-core:vitaltype haley:KGNewsEntity .\n"
        "    } UNION {\n"
        "      ?entity vital-core:vitaltype haley:KGProductEntity .\n"
        "    } UNION {\n"
        "      ?entity vital-core:vitaltype haley:KGWebEntity .\n"
        "    }\n"
        "  }\n"
        "}"
    )
    print(f"\n--- Exact endpoint count query ---")
    print(f"  Query:\n{exact_count_query}")
    bindings4 = await sparql_query(client, exact_count_query)
    if bindings4:
        print(f"  Result: {bindings4[0].get('count', {}).get('value', 'N/A')}")
    else:
        print(f"  Result: no bindings!")

    # Query 5a: Show TechCorp's predicates with "modification" or "DateTime"
    techcorp_uri = "http://vital.ai/test/kgentity/organization/techcorp_industries"
    bindings5a = await sparql_query(client, f"""
        SELECT ?p ?o WHERE {{
            GRAPH <{GRAPH_ID}> {{
                <{techcorp_uri}> ?p ?o .
                FILTER(CONTAINS(STR(?p), "odification") || CONTAINS(STR(?p), "reation"))
            }}
        }}
    """)
    print(f"\n--- TechCorp datetime predicates ---")
    if bindings5a:
        for b in bindings5a:
            pred = b["p"]["value"]
            obj = b["o"]
            print(f"  pred={pred.split('#')[-1]}  type={obj.get('type')}  datatype={obj.get('datatype','N/A')}  value={obj.get('value')}")
    else:
        print("  None found!")

    # Query 5b: Run the exact delete query used by update_entity
    bindings5b = await sparql_query(client, f"""
        SELECT DISTINCT ?subject ?predicate ?object WHERE {{
            GRAPH <{GRAPH_ID}> {{
                {{
                    <{techcorp_uri}> ?predicate ?object .
                    BIND(<{techcorp_uri}> AS ?subject)
                }}
                UNION
                {{
                    ?subject <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{techcorp_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
        }}
    """)
    print(f"\n--- Delete query bindings for TechCorp (datetime predicates only) ---")
    if bindings5b:
        for b in bindings5b:
            pred = b["predicate"]["value"]
            if "odification" in pred or "reation" in pred:
                obj = b["object"]
                print(f"  pred={pred.split('#')[-1]}  type={obj.get('type')}  datatype={obj.get('datatype','MISSING')}  value={obj.get('value')}")
    else:
        print("  No bindings!")

    # Query 5: Find entities with duplicate values for any property
    bindings5 = await sparql_query(client, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        SELECT ?s ?p (COUNT(?o) AS ?cnt) WHERE {{
            GRAPH <{GRAPH_ID}> {{
                {{
                  ?s vital-core:vitaltype haley:KGEntity .
                }} UNION {{
                  ?s vital-core:vitaltype haley:KGProductEntity .
                }}
                ?s ?p ?o .
            }}
        }}
        GROUP BY ?s ?p
        HAVING (COUNT(?o) > 1)
        ORDER BY DESC(?cnt)
    """)
    print(f"\n--- Entities with duplicate property values ---")
    if bindings5:
        for b in bindings5:
            subj = b["s"]["value"].split("/")[-1]
            pred = b["p"]["value"].split("#")[-1]
            cnt = b["cnt"]["value"]
            print(f"  {subj:40s}  {pred:35s}  {cnt} values")
    else:
        print("  None found!")

    # Query 6: Raw HTTP call to list endpoint via client's internal method
    print(f"\n--- Raw HTTP list endpoint ---")
    try:
        server_url = client.config.get_server_url()
        url = f"{server_url}/api/graphs/kgentities"
        raw_resp = await client._make_authenticated_request(
            'GET', url, 
            params={"space_id": SPACE_ID, "graph_id": GRAPH_ID, "page_size": 100},
        )
        raw_json = raw_resp.json()
        print(f"  HTTP status: {raw_resp.status_code}")
        print(f"  total_count: {raw_json.get('total_count')}")
        print(f"  results len: {len(raw_json.get('results', []))}")
        print(f"  page_size:   {raw_json.get('page_size')}")
        print(f"  offset:      {raw_json.get('offset')}")
        if raw_json.get('total_count', -1) == 0 and not raw_json.get('results'):
            print(f"  FULL RESPONSE: {raw_json}")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()

    # Query 6: Call list_kgentities endpoint directly
    print(f"\n--- list_kgentities endpoint result ---")
    try:
        resp = await client.kgentities.list_kgentities(
            space_id=SPACE_ID,
            graph_id=GRAPH_ID,
            page_size=100,
        )
        print(f"  total_count = {resp.total_count}")
        print(f"  objects     = {len(resp.objects) if resp.objects else 0}")
        print(f"  is_success  = {resp.is_success}")
        if hasattr(resp, 'error_message') and resp.error_message:
            print(f"  error       = {resp.error_message}")
    except Exception as e:
        print(f"  ERROR: {e}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
