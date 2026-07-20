#!/usr/bin/env python3
"""Delete all graph objects whose kGGraphURI matches the specified campaign URIs.

Uses SPARQL to discover subjects, then the objects endpoint for deletion.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest


SPACE_ID = "acme_kg"

SUBJECTS_QUERY = """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT DISTINCT ?subject ?graphURI WHERE {
  ?subject haley:hasKGGraphURI ?graphURI .
  FILTER(?graphURI IN (
    <urn:acme:campaign:cer:under30k_incomplete_1>,
    <urn:acme:campaign:cer:under30k_nurture_1>
  ))
}
ORDER BY ?graphURI ?subject
"""

BATCH_SIZE = 20
DRY_RUN = True


async def main():
    client = VitalGraphClient()
    try:
        await client.open()
        print(f"Connected to VitalGraph\n")

        # Step 1: Find the graph_id
        print("Step 1: Listing graphs in space...")
        graphs_resp = await client.graphs.list_graphs(SPACE_ID)
        if not graphs_resp.graphs:
            print("  No graphs found in space. Exiting.")
            return

        for g in graphs_resp.graphs:
            print(f"  Graph: {g.graph_uri}")

        graph_id = str(graphs_resp.graphs[0].graph_uri)
        print(f"  Using graph: {graph_id}\n")

        # Step 2: Query for subjects
        print("Step 2: Querying subjects to delete...")
        resp = await client.sparql.execute_sparql_query(
            SPACE_ID, SPARQLQueryRequest(query=SUBJECTS_QUERY)
        )
        bindings = []
        if resp.results and isinstance(resp.results, dict):
            bindings = resp.results.get("bindings", [])

        subject_uris = [b["subject"]["value"] for b in bindings]
        print(f"  Found {len(subject_uris)} subjects\n")

        if not subject_uris:
            print("Nothing to delete.")
            return

        # Show grouped by kGGraphURI
        current_graph = None
        for b in bindings:
            gu = b["graphURI"]["value"]
            su = b["subject"]["value"]
            if gu != current_graph:
                current_graph = gu
                print(f"  --- {gu} ---")
            print(f"    {su}")

        # Step 3: Delete in batches via objects endpoint
        if DRY_RUN:
            print("\n[DRY RUN] Would delete the above objects. Set DRY_RUN = False to execute.")
            return

        print(f"\nStep 3: Deleting objects in batches of {BATCH_SIZE}...")
        total_deleted = 0
        total_errors = 0

        for i in range(0, len(subject_uris), BATCH_SIZE):
            batch = subject_uris[i:i + BATCH_SIZE]
            uri_list = ",".join(batch)
            del_resp = await client.objects.delete_objects_batch(SPACE_ID, graph_id, uri_list)

            if del_resp.is_success:
                total_deleted += len(batch)
                print(f"  Batch {i // BATCH_SIZE + 1}: deleted {len(batch)} objects")
            else:
                total_errors += len(batch)
                print(f"  Batch {i // BATCH_SIZE + 1}: FAILED - {del_resp.message}")

        print(f"\nDeleted: {total_deleted}, Errors: {total_errors}")

        # Step 5: Verify
        print("\nStep 4: Verifying deletion...")
        verify_resp = await client.sparql.execute_sparql_query(
            SPACE_ID, SPARQLQueryRequest(query=SUBJECTS_QUERY)
        )
        vbindings = []
        if verify_resp.results and isinstance(verify_resp.results, dict):
            vbindings = verify_resp.results.get("bindings", [])
        remaining = len(vbindings)
        print(f"  Remaining subjects: {remaining}")

        if remaining == 0:
            print("\nAll objects deleted successfully.")
        else:
            print(f"\nWARNING: {remaining} subjects still remain.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
