#!/usr/bin/env python3
"""
profile_lead_insert.py — Profile inserting one lead entity graph.

Uses SparqlSQLSpaceImpl directly (same code path as production).
Two modes:
  --raw     : Parse .nt directly with RDFLib (fewer quads, no grouping URIs)
  (default) : Parse .nt → VitalSigns GraphObjects → to_rdf() → RDFLib
              (same path as server: produces more quads with grouping URIs)

Measures: RDFLib parse, add_rdf_quads_batch, total wall-clock.
Also reports PostgreSQL transaction/WAL settings.

Usage:
    python vitalgraph_sparql_sql/scripts/profile_lead_insert.py
    python vitalgraph_sparql_sql/scripts/profile_lead_insert.py --raw
    python vitalgraph_sparql_sql/scripts/profile_lead_insert.py --transactional
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from rdflib import Graph, URIRef

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

# ---------------------------------------------------------------------------
SPACE_ID = "sp_profile_insert"
GRAPH_URI = "urn:profile_insert"

PG_CONFIG = {
    "host": os.getenv("SPARQL_SQL_DB_HOST", "localhost"),
    "port": int(os.getenv("SPARQL_SQL_DB_PORT", "5432")),
    "database": os.getenv("SPARQL_SQL_DB_NAME", "sparql_sql_graph"),
    "username": os.getenv("SPARQL_SQL_DB_USERNAME", "postgres"),
    "password": os.getenv("SPARQL_SQL_DB_PASSWORD", "postgres"),
}


def load_quads_raw(nt_path: Path) -> list:
    """Parse .nt directly — raw triples, no VitalSigns."""
    rdf_graph = Graph()
    rdf_graph.parse(str(nt_path), format="nt")
    graph_uri = URIRef(GRAPH_URI)
    return [(s, p, o, graph_uri) for s, p, o in rdf_graph]


def load_quads_via_vitalsigns(nt_path: Path) -> list:
    """Parse .nt → VitalSigns GraphObjects → to_rdf() → RDFLib.
    Same path as the server's SparqlSQLBackendAdapter.store_objects()."""
    from vital_ai_vitalsigns.vitalsigns import VitalSigns

    # Step 1: parse .nt into RDFLib graph
    raw_graph = Graph()
    raw_graph.parse(str(nt_path), format="nt")
    print(f"  Raw triples from .nt: {len(raw_graph):,}")

    # Step 2: convert to VitalSigns GraphObjects (same as case_load_lead_graph)
    vs = VitalSigns()
    triples = list(raw_graph)
    graph_objects = vs.from_triples_list(triples)
    print(f"  VitalSigns objects:   {len(graph_objects):,}")

    # Step 3: set grouping URIs (same as server create path)
    from vitalgraph.kg_impl.kg_validation_utils import KGGroupingURIManager
    from ai_haley_kg_domain.model.KGEntity import KGEntity
    entities = [obj for obj in graph_objects if isinstance(obj, KGEntity)]
    if entities:
        mgr = KGGroupingURIManager()
        mgr.set_dual_grouping_uris_with_frame_separation(graph_objects, str(entities[0].URI))
    print(f"  Entities found:       {len(entities)}")

    # Step 4: to_rdf() + RDFLib parse per object (same as backend adapter)
    rdf_graph = Graph()
    for obj in graph_objects:
        try:
            rdf_graph.parse(data=obj.to_rdf(), format='turtle')
        except Exception as e:
            print(f"  Warning: to_rdf failed for {type(obj).__name__}: {e}")
            continue

    graph_uri = URIRef(GRAPH_URI)
    quads = [(s, p, o, graph_uri) for s, p, o in rdf_graph]
    print(f"  Final quads:          {len(quads):,}")
    return quads


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default=None)
    parser.add_argument("--raw", action="store_true",
                        help="Parse .nt directly (skip VitalSigns)")
    parser.add_argument("--transactional", action="store_true",
                        help="Wrap all inserts in one transaction")
    args = parser.parse_args()

    # Find lead file
    if args.file:
        nt_path = Path(args.file)
    else:
        nt_files = sorted((project_root / "lead_test_data").glob("lead_*.nt"))
        if not nt_files:
            print("No lead .nt files found"); return
        nt_path = nt_files[0]
    if not nt_path.exists():
        print(f"Not found: {nt_path}"); return

    # Initialize VitalSigns early (loads ontologies once)
    from vital_ai_vitalsigns.vitalsigns import VitalSigns
    vs = VitalSigns()

    mode_label = "RAW .nt" if args.raw else "VitalSigns (server path)"
    print("\n" + "=" * 70)
    print("  Profile: Single Lead Entity Graph Insert")
    print("=" * 70)
    print(f"  File:          {nt_path.name}")
    print(f"  Mode:          {mode_label}")
    print(f"  DB:            {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")
    print(f"  Transactional: {args.transactional}")

    # --- Build quads ---
    print(f"\n--- Step 1: Build quads ({mode_label}) ---")
    t0 = time.monotonic()
    if args.raw:
        quads = load_quads_raw(nt_path)
    else:
        quads = load_quads_via_vitalsigns(nt_path)
    t_build = time.monotonic() - t0
    print(f"  Build time:    {t_build:.3f}s")
    print(f"  Quad count:    {len(quads):,}")

    # Count literals with datatypes
    from rdflib import Literal
    n_literals = sum(1 for s, p, o, g in quads if isinstance(o, Literal))
    n_typed = sum(1 for s, p, o, g in quads if isinstance(o, Literal) and o.datatype)
    print(f"  Literals:      {n_literals:,}  (with datatype: {n_typed:,})")

    # --- Connect via SparqlSQLSpaceImpl ---
    impl = SparqlSQLSpaceImpl(PG_CONFIG)
    ok = await impl.connect()
    if not ok:
        print("Failed to connect"); return

    try:
        # --- PostgreSQL settings ---
        print("\n--- PostgreSQL Settings ---")
        async with impl.db_impl.connection_pool.acquire() as conn:
            for s in ["synchronous_commit", "fsync", "wal_level",
                       "default_transaction_isolation"]:
                val = await conn.fetchval(f"SHOW {s}")
                print(f"  {s:40s} = {val}")

        # --- Create space ---
        print(f"\n--- Step 2: Create space ---")
        if await impl.space_exists(SPACE_ID):
            await impl.delete_space_storage(SPACE_ID)
        await impl.create_space_storage(SPACE_ID)
        await impl.create_space_metadata(SPACE_ID, {"space_name": "Profile Insert Test"})
        await impl.create_graph(SPACE_ID, GRAPH_URI)
        print(f"  Space '{SPACE_ID}' ready")

        # --- Insert quads ---
        txn_label = "WITH txn" if args.transactional else "NO txn (autocommit)"
        print(f"\n--- Step 3: Insert {len(quads):,} quads ({txn_label}) ---")

        t_start = time.monotonic()

        if args.transactional:
            async with impl.db_impl.connection_pool.acquire() as conn:
                tr = conn.transaction()
                await tr.start()
                try:
                    inserted = await impl.add_rdf_quads_batch(
                        SPACE_ID, quads, connection=conn)
                    await tr.commit()
                except Exception:
                    await tr.rollback()
                    raise
        else:
            inserted = await impl.add_rdf_quads_batch(SPACE_ID, quads)

        t_total = time.monotonic() - t_start

        # --- Verify ---
        t = impl.schema.get_table_names(SPACE_ID)
        async with impl.db_impl.connection_pool.acquire() as conn:
            db_quads = await conn.fetchval(f"SELECT COUNT(*) FROM {t['rdf_quad']}")
            db_terms = await conn.fetchval(f"SELECT COUNT(*) FROM {t['term']}")

        # --- Report ---
        # Estimate SQL statements: 4 _ensure_term + 1 insert per quad,
        # plus extra _resolve_datatype_id for each typed literal
        base_stmts = len(quads) * 5
        extra_dt = n_typed  # each typed literal = 1 extra SELECT
        total_stmts = base_stmts + extra_dt

        print(f"\n--- Results ---")
        print(f"  Quads inserted:    {inserted:,} / {len(quads):,}")
        print(f"  Terms in DB:       {db_terms:,}")
        print(f"  Quads in DB:       {db_quads:,}")
        print(f"  Total wall-clock:  {t_total:.3f}s")
        print(f"  SQL statements:    ~{total_stmts:,}  (base {base_stmts:,} + {extra_dt:,} datatype lookups)")
        print(f"  Avg per stmt:      {t_total / total_stmts * 1000:.3f}ms")
        print(f"  Throughput:        {len(quads) / t_total:.0f} quads/sec")
        if not args.transactional:
            print(f"\n  ⚠️  NO TRANSACTION — each conn.execute() auto-commits individually")

        # --- Cleanup ---
        print(f"\n--- Cleanup ---")
        await impl.delete_space_storage(SPACE_ID)
        print(f"  Space '{SPACE_ID}' deleted")

    finally:
        await impl.disconnect()

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
