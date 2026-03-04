#!/usr/bin/env python3
"""
Analyze lead_exp PostgreSQL tables to derive direct properties from edge objects.

Direct properties bypass edge objects for fast hierarchical queries:
  - vg-direct:hasEntityFrame  (Entity → Frame,  from Edge_hasEntityKGFrame)
  - vg-direct:hasFrame        (Frame  → Frame,  from Edge_hasKGFrame)
  - vg-direct:hasSlot         (Frame  → Slot,   from Edge_hasKGSlot)

This script:
  1. Finds all edge objects of the three types in the quad table
  2. Extracts hasEdgeSource and hasEdgeDestination for each
  3. Outputs the derived direct property triples to a file
"""

import sys
import os
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph_sparql_sql import db

# --- Constants (from edge_materialization.py) ---

EDGE_TYPE_TO_DIRECT = {
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame":
        "http://vital.ai/vitalgraph/direct#hasEntityFrame",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame":
        "http://vital.ai/vitalgraph/direct#hasFrame",
    "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot":
        "http://vital.ai/vitalgraph/direct#hasSlot",
}

VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
EDGE_SOURCE = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"

SPACE_ID = os.environ.get("SPACE_ID", "lead_exp")
GRAPH_URI = os.environ.get("GRAPH_URI", "urn:lead_test")
OUTPUT_FILE = os.environ.get("OUTPUT_FILE",
    str(Path(__file__).parent / "direct_properties_output.ttl"))


def analyze_direct_properties(space_id: str, graph_uri: str) -> list:
    """
    Query PostgreSQL to find edge objects and derive direct properties.

    Returns list of (source_uri, direct_predicate, dest_uri, graph_uri) tuples.
    """
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    # Step 1: Find all edge URIs with their edge types
    # An edge object has a vitaltype quad matching one of the three edge types
    edge_type_uris = list(EDGE_TYPE_TO_DIRECT.keys())
    placeholders = ", ".join(["%s"] * len(edge_type_uris))

    print(f"Step 1: Finding edge objects in {quad_table}...")
    t0 = time.time()

    edge_type_sql = f"""
        SELECT
            subj_t.term_text  AS edge_uri,
            type_t.term_text  AS edge_type,
            ctx_t.term_text   AS graph
        FROM {quad_table} q
        JOIN {term_table} subj_t ON q.subject_uuid   = subj_t.term_uuid AND subj_t.term_type = 'U'
        JOIN {term_table} pred_t ON q.predicate_uuid  = pred_t.term_uuid
        JOIN {term_table} type_t ON q.object_uuid     = type_t.term_uuid
        JOIN {term_table} ctx_t  ON q.context_uuid    = ctx_t.term_uuid AND ctx_t.term_type = 'U'
        WHERE pred_t.term_text = %s
          AND type_t.term_text IN ({placeholders})
    """
    params = (VITALTYPE, *edge_type_uris)
    edge_rows = db.execute_query(edge_type_sql, params)
    print(f"  Found {len(edge_rows)} edge objects in {time.time()-t0:.2f}s")

    # Group by edge type
    by_type = {}
    for row in edge_rows:
        et = row["edge_type"]
        by_type.setdefault(et, []).append(row)
    for et, rows in by_type.items():
        short = et.split("#")[-1]
        print(f"    {short}: {len(rows)}")

    if not edge_rows:
        print("  No edge objects found. Nothing to derive.")
        return []

    # Step 2: For each edge object, find hasEdgeSource and hasEdgeDestination
    edge_uris = [row["edge_uri"] for row in edge_rows]

    # Build a lookup: edge_uri → {type, graph}
    edge_info = {}
    for row in edge_rows:
        edge_info[row["edge_uri"]] = {
            "edge_type": row["edge_type"],
            "graph": row["graph"],
            "source": None,
            "dest": None,
        }

    print(f"\nStep 2: Resolving source/destination for {len(edge_uris)} edges...")
    t0 = time.time()

    # Batch query: get all source and dest properties for these edge URIs
    # Use a chunked approach for large sets
    CHUNK_SIZE = 5000
    for chunk_start in range(0, len(edge_uris), CHUNK_SIZE):
        chunk = edge_uris[chunk_start:chunk_start + CHUNK_SIZE]
        ph = ", ".join(["%s"] * len(chunk))

        src_dest_sql = f"""
            SELECT
                subj_t.term_text AS edge_uri,
                pred_t.term_text AS predicate,
                obj_t.term_text  AS value
            FROM {quad_table} q
            JOIN {term_table} subj_t ON q.subject_uuid   = subj_t.term_uuid AND subj_t.term_type = 'U'
            JOIN {term_table} pred_t ON q.predicate_uuid  = pred_t.term_uuid
            JOIN {term_table} obj_t  ON q.object_uuid     = obj_t.term_uuid
            WHERE subj_t.term_text IN ({ph})
              AND pred_t.term_text IN (%s, %s)
        """
        params = (*chunk, EDGE_SOURCE, EDGE_DEST)
        prop_rows = db.execute_query(src_dest_sql, params)

        for row in prop_rows:
            uri = row["edge_uri"]
            if uri in edge_info:
                if row["predicate"] == EDGE_SOURCE:
                    edge_info[uri]["source"] = row["value"]
                elif row["predicate"] == EDGE_DEST:
                    edge_info[uri]["dest"] = row["value"]

    elapsed = time.time() - t0
    print(f"  Resolved in {elapsed:.2f}s")

    # Step 3: Build direct property triples
    print(f"\nStep 3: Building direct property triples...")
    direct_triples = []
    incomplete = 0

    for edge_uri, info in edge_info.items():
        if info["source"] and info["dest"]:
            direct_pred = EDGE_TYPE_TO_DIRECT[info["edge_type"]]
            direct_triples.append((
                info["source"],
                direct_pred,
                info["dest"],
                info["graph"],
            ))
        else:
            incomplete += 1

    print(f"  Derived {len(direct_triples)} direct property triples")
    if incomplete:
        print(f"  Skipped {incomplete} incomplete edges (missing source or dest)")

    # Summarize by predicate
    by_pred = {}
    for _, pred, _, _ in direct_triples:
        short = pred.split("#")[-1]
        by_pred[short] = by_pred.get(short, 0) + 1
    for pred, count in sorted(by_pred.items()):
        print(f"    {pred}: {count}")

    return direct_triples


def write_turtle(triples: list, output_path: str, graph_uri: str):
    """Write direct property triples to a Turtle file with GRAPH wrapping."""
    print(f"\nWriting {len(triples)} triples to {output_path}...")

    # Group by graph
    by_graph = {}
    for s, p, o, g in triples:
        by_graph.setdefault(g, []).append((s, p, o))

    with open(output_path, "w") as f:
        f.write("# Direct properties derived from edge objects in PostgreSQL\n")
        f.write("# Generated by analyze_direct_properties.py\n")
        f.write(f"# Space: {SPACE_ID}\n")
        f.write(f"# Source tables: {SPACE_ID}_rdf_quad, {SPACE_ID}_term\n\n")
        f.write("@prefix vg-direct: <http://vital.ai/vitalgraph/direct#> .\n")
        f.write("@prefix vital-core: <http://vital.ai/ontology/vital-core#> .\n")
        f.write("@prefix haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#> .\n\n")

        for g, graph_triples in sorted(by_graph.items()):
            f.write(f"# Graph: {g}  ({len(graph_triples)} triples)\n")
            # Group by subject for compact Turtle
            by_subject = {}
            for s, p, o in graph_triples:
                by_subject.setdefault(s, []).append((p, o))

            for subj, po_list in sorted(by_subject.items()):
                for pred, obj in sorted(po_list):
                    f.write(f"<{subj}> <{pred}> <{obj}> .\n")
            f.write("\n")

    print(f"  Done. File size: {os.path.getsize(output_path):,} bytes")


def main():
    print("=" * 70)
    print("Direct Property Analyzer")
    print(f"  Space:  {SPACE_ID}")
    print(f"  Graph:  {GRAPH_URI}")
    print(f"  Output: {OUTPUT_FILE}")
    print("=" * 70)
    print()

    t_start = time.time()
    triples = analyze_direct_properties(SPACE_ID, GRAPH_URI)

    if triples:
        write_turtle(triples, OUTPUT_FILE, GRAPH_URI)

    elapsed = time.time() - t_start
    print(f"\nTotal time: {elapsed:.2f}s")
    print(f"Direct property triples: {len(triples)}")


if __name__ == "__main__":
    main()
