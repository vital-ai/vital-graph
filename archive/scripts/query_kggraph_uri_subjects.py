#!/usr/bin/env python3
"""Query subjects with specific kGGraphURI values via VitalGraph client."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest


SPACE_ID = "cardiff_kg"

SPARQL_QUERY = """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT DISTINCT ?subject ?graphURI WHERE {
  ?subject haley:hasKGGraphURI ?graphURI .
  FILTER(?graphURI IN (
    <urn:cardiff:campaign:cer:under30k_incomplete_1>,
    <urn:cardiff:campaign:cer:under30k_nurture_1>
  ))
}
ORDER BY ?graphURI ?subject
"""


async def main():
    client = VitalGraphClient()
    try:
        await client.open()
        print(f"Connected to VitalGraph\n")

        request = SPARQLQueryRequest(query=SPARQL_QUERY)
        response = await client.sparql.execute_sparql_query(SPACE_ID, request)

        bindings = []
        if response.results and isinstance(response.results, dict):
            bindings = response.results.get("bindings", [])
        elif hasattr(response, 'bindings'):
            bindings = response.bindings or []

        print(f"Found {len(bindings)} subjects\n")

        current_graph = None
        for b in bindings:
            graph_uri = b.get("graphURI", {}).get("value", "")
            subject = b.get("subject", {}).get("value", "")

            if graph_uri != current_graph:
                current_graph = graph_uri
                print(f"--- kGGraphURI: {graph_uri} ---")

            print(f"  {subject}")

        if not bindings:
            print("No subjects found.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
