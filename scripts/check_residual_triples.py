#!/usr/bin/env python3
"""Check if any triples remain for subjects under the two campaign kGGraphURIs."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPACE_ID = "cardiff_kg"

# Check for any triple whose subject contains these prefixes
QUERIES = [
    ("Subjects with kGGraphURI property", """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT DISTINCT ?subject ?graphURI WHERE {
  ?subject haley:hasKGGraphURI ?graphURI .
  FILTER(?graphURI IN (
    <urn:cardiff:campaign:cer:under30k_incomplete_1>,
    <urn:cardiff:campaign:cer:under30k_nurture_1>
  ))
}
"""),
    ("Any triples with under30k_incomplete_1 in subject", """\
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  FILTER(CONTAINS(STR(?s), "under30k_incomplete_1"))
} LIMIT 20
"""),
    ("Any triples with under30k_nurture_1 in subject", """\
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  FILTER(CONTAINS(STR(?s), "under30k_nurture_1"))
} LIMIT 20
"""),
    ("Any triples with under30k_incomplete_1 in object", """\
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  FILTER(CONTAINS(STR(?o), "under30k_incomplete_1"))
} LIMIT 20
"""),
    ("Any triples with under30k_nurture_1 in object", """\
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  FILTER(CONTAINS(STR(?o), "under30k_nurture_1"))
} LIMIT 20
"""),
]


async def main():
    client = VitalGraphClient()
    try:
        await client.open()
        print("Connected to VitalGraph\n")

        for label, query in QUERIES:
            print(f"=== {label} ===")
            resp = await client.sparql.execute_sparql_query(
                SPACE_ID, SPARQLQueryRequest(query=query)
            )
            bindings = []
            if resp.results and isinstance(resp.results, dict):
                bindings = resp.results.get("bindings", [])

            print(f"  Results: {len(bindings)}")
            for b in bindings:
                parts = []
                for var in ["s", "subject", "p", "o", "graphURI"]:
                    if var in b:
                        parts.append(f"{var}={b[var]['value']}")
                print(f"    {' | '.join(parts)}")
            print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
