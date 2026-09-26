#!/usr/bin/env python3
"""
Quick script to check what spaces exist in Fuseki directly.
"""

import asyncio
import aiohttp
import json

async def check_fuseki_spaces():
    """Check what spaces exist in Fuseki by querying for VitalSegments."""
    
    fuseki_url = "http://localhost:3030"
    query_url = f"{fuseki_url}/vitalgraph/sparql"
    
    # SPARQL query to find all VitalSegment objects (spaces)
    sparql_query = """
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    
    SELECT ?space ?name ?segmentID WHERE {
        GRAPH ?g {
            ?space a vital:VitalSegment .
            OPTIONAL { ?space vital:name ?name }
            OPTIONAL { ?space vital:segmentID ?segmentID }
        }
    }
    """
    
    try:
        # Use basic auth (admin/admin is common default for Fuseki)
        auth = aiohttp.BasicAuth('vitalgraph_user', 'vitalgraph_pass')
        
        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.get(
                query_url,
                params={'query': sparql_query},
                headers={
                    'Accept': 'application/sparql-results+json'
                }
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    bindings = result.get('results', {}).get('bindings', [])
                    
                    print(f"🔍 Found {len(bindings)} VitalSegment objects in Fuseki:")
                    for binding in bindings:
                        space_uri = binding.get('space', {}).get('value', 'N/A')
                        name = binding.get('name', {}).get('value', 'N/A')
                        segment_id = binding.get('segmentID', {}).get('value', 'N/A')
                        print(f"  - Space: {space_uri}")
                        print(f"    Name: {name}")
                        print(f"    Segment ID: {segment_id}")
                        print()
                    
                    return bindings
                else:
                    print(f"❌ Query failed with status {response.status}")
                    text = await response.text()
                    print(f"Response: {text}")
                    return []
                    
    except Exception as e:
        print(f"❌ Error querying Fuseki: {e}")
        return []

async def check_all_graphs():
    """Check what named graphs exist in Fuseki."""
    
    fuseki_url = "http://localhost:3030"
    query_url = f"{fuseki_url}/vitalgraph/sparql"
    
    # SPARQL query to find all named graphs
    sparql_query = """
    SELECT DISTINCT ?g WHERE {
        GRAPH ?g { ?s ?p ?o }
    }
    """
    
    try:
        # Use basic auth (admin/admin is common default for Fuseki)
        auth = aiohttp.BasicAuth('vitalgraph_user', 'vitalgraph_pass')
        
        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.get(
                query_url,
                params={'query': sparql_query},
                headers={
                    'Accept': 'application/sparql-results+json'
                }
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    bindings = result.get('results', {}).get('bindings', [])
                    
                    print(f"🔍 Found {len(bindings)} named graphs in Fuseki:")
                    for binding in bindings:
                        graph_uri = binding.get('g', {}).get('value', 'N/A')
                        print(f"  - {graph_uri}")
                    
                    return bindings
                else:
                    print(f"❌ Query failed with status {response.status}")
                    return []
                    
    except Exception as e:
        print(f"❌ Error querying Fuseki: {e}")
        return []

async def main():
    print("🔍 Checking Fuseki for existing spaces...")
    print("=" * 50)
    
    print("\n1. Checking for VitalSegment objects (spaces):")
    spaces = await check_fuseki_spaces()
    
    print("\n2. Checking for all named graphs:")
    graphs = await check_all_graphs()
    
    print("\n" + "=" * 50)
    print(f"Summary: {len(spaces)} spaces, {len(graphs)} graphs")

if __name__ == "__main__":
    asyncio.run(main())
