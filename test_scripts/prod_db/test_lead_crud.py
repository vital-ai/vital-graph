#!/usr/bin/env python3
"""
Direct Lead Entity CRUD Test — Production RDS via sparql_sql Backend

Bypasses the REST API. Uses SparqlSQLSpaceImpl directly against the
production RDS with the local Jena sidecar (Docker, localhost:7070).

Lifecycle per lead file:
  1. Load .nt → RDFLib triples → quads → bulk insert
  2. Verify quad count + SPARQL SELECT for entity
  3. Query frames via SPARQL
  4. Update a slot via SPARQL UPDATE
  5. Delete entity quads by subject
  6. Verify deletion

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/prod_db/test_lead_crud.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

from rdflib import Graph as RDFGraph, URIRef

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from db_connect import get_prod_connection_params, print_connection_info
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Suppress chatty loggers
for name in (
    'vitalgraph.db.sparql_sql.sparql_sql_space_impl',
    'vitalgraph.db.sparql_sql.sparql_sql_db_impl',
    'vitalgraph.db.sparql_sql.sparql_sql_db_objects',
    'vitalgraph.db.sparql_sql.compile_cache',
    'vitalgraph.db.sparql_sql.db_provider',
    'vitalgraph.db.jena_sparql.jena_sidecar_client',
    'vitalgraph.utils.resource_manager',
):
    logging.getLogger(name).setLevel(logging.WARNING)

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "prod_lead_crud_test"
TEST_GRAPH_URI = "urn:prod_lead_crud"
LEAD_DATA_DIR = PROJECT_ROOT / "lead_test_data"
LEAD_FILE_LIMIT = 3
DELETE_SPACE_AT_END = True
SIDECAR_URL = "http://localhost:7070"


def get_lead_files(limit: int = None) -> List[Path]:
    nt_files = sorted(LEAD_DATA_DIR.glob("lead_*.nt"))
    if limit:
        nt_files = nt_files[:limit]
    return nt_files


def parse_nt_to_quads(nt_path: Path, graph_uri: str) -> Tuple[List[tuple], str]:
    """Parse .nt file → list of (s, p, o, g) rdflib quads.

    Returns (quads, entity_uri) where entity_uri is the KGEntity subject.
    """
    rdf_graph = RDFGraph()
    rdf_graph.parse(str(nt_path), format='nt')

    g = URIRef(graph_uri)
    quads = [(s, p, o, g) for s, p, o in rdf_graph]

    # Find the KGEntity URI
    KG_ENTITY_TYPE = URIRef("http://vital.ai/ontology/haley-ai-kg#KGEntity")
    RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    entity_uri = None
    for s, p, o in rdf_graph:
        if p == RDF_TYPE and o == KG_ENTITY_TYPE:
            entity_uri = str(s)
            break

    return quads, entity_uri


# ===========================================================================
# Test steps
# ===========================================================================

async def step_load(space_impl: SparqlSQLSpaceImpl, nt_path: Path) -> Dict[str, Any]:
    """Load a single .nt file into the test space."""
    result = {"name": f"Load {nt_path.name}", "passed": False, "error": None,
              "entity_uri": None, "triple_count": 0}
    try:
        quads, entity_uri = parse_nt_to_quads(nt_path, TEST_GRAPH_URI)
        result["triple_count"] = len(quads)
        result["entity_uri"] = entity_uri

        if not entity_uri:
            result["error"] = "No KGEntity found in .nt file"
            return result

        t0 = time.monotonic()
        inserted = await space_impl.add_rdf_quads_batch_bulk(TEST_SPACE_ID, quads)
        elapsed = time.monotonic() - t0

        logger.info(f"    Loaded {inserted}/{len(quads)} quads in {elapsed:.2f}s  entity={entity_uri}")
        result["passed"] = inserted > 0
        if inserted == 0:
            result["error"] = "Zero quads inserted"
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"    Load error: {e}")
    return result


async def step_verify(space_impl: SparqlSQLSpaceImpl, entity_uri: str,
                      expected_count: int) -> Dict[str, Any]:
    """Verify entity exists via quad count and SPARQL."""
    result = {"name": "Verify entity", "passed": False, "error": None}
    try:
        # 1. Direct quad count for the graph
        total = await space_impl.get_rdf_quad_count(TEST_SPACE_ID, graph_uri=TEST_GRAPH_URI)
        logger.info(f"    Total quads in graph: {total}")

        # 2. SPARQL: find the entity by type
        sparql = f"""
            SELECT ?entity WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                }}
            }}
        """
        resp = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql)
        bindings = resp.get('results', {}).get('bindings', [])
        found_uris = [b['entity']['value'] for b in bindings if 'entity' in b]
        logger.info(f"    SPARQL found {len(found_uris)} KGEntity(s)")

        if entity_uri in found_uris:
            result["passed"] = True
            logger.info(f"    ✅ Entity verified: {entity_uri}")
        else:
            result["error"] = f"Entity {entity_uri} not found in SPARQL results"
            logger.error(f"    ❌ {result['error']}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"    Verify error: {e}")
    return result


async def step_query_frames(space_impl: SparqlSQLSpaceImpl,
                            entity_uri: str) -> Dict[str, Any]:
    """Query frames and slots for the entity via SPARQL."""
    result = {"name": "Query frames", "passed": False, "error": None, "frame_count": 0}
    try:
        # Get all objects linked to the entity via edges
        sparql = f"""
            SELECT ?type (COUNT(?s) AS ?cnt) WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    ?s a ?type .
                }}
            }}
            GROUP BY ?type
            ORDER BY DESC(?cnt)
        """
        resp = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql)
        bindings = resp.get('results', {}).get('bindings', [])

        logger.info(f"    Type breakdown ({len(bindings)} types):")
        frame_count = 0
        for b in bindings:
            type_uri = b.get('type', {}).get('value', '?')
            cnt = b.get('cnt', {}).get('value', '0')
            short_type = type_uri.rsplit('#', 1)[-1] if '#' in type_uri else type_uri
            logger.info(f"      {short_type}: {cnt}")
            if 'Frame' in short_type and 'Edge' not in short_type:
                frame_count += int(cnt)

        result["frame_count"] = frame_count
        result["passed"] = len(bindings) > 0
        if not result["passed"]:
            result["error"] = "No types found"
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"    Query frames error: {e}")
    return result


async def step_update_slot(space_impl: SparqlSQLSpaceImpl,
                           entity_uri: str) -> Dict[str, Any]:
    """Update a text slot value via SPARQL UPDATE, then verify."""
    result = {"name": "Update slot", "passed": False, "error": None}
    try:
        HAS_NAME = "http://vital.ai/ontology/vital-core#hasName"

        # 1. Read current name
        sparql_read = f"""
            SELECT ?name WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    <{entity_uri}> <{HAS_NAME}> ?name .
                }}
            }}
        """
        resp = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_read)
        bindings = resp.get('results', {}).get('bindings', [])
        if not bindings:
            result["error"] = "Entity has no hasName property"
            return result

        old_name = bindings[0]['name']['value']
        new_name = f"TEST_UPDATE_{int(time.time())}"
        logger.info(f"    Updating hasName: '{old_name}' → '{new_name}'")

        # 2. SPARQL UPDATE
        sparql_update = f"""
            DELETE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    <{entity_uri}> <{HAS_NAME}> ?old .
                }}
            }}
            INSERT {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    <{entity_uri}> <{HAS_NAME}> "{new_name}" .
                }}
            }}
            WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    <{entity_uri}> <{HAS_NAME}> ?old .
                }}
            }}
        """
        ok = await space_impl.execute_sparql_update(TEST_SPACE_ID, sparql_update)
        if not ok:
            result["error"] = "SPARQL UPDATE returned failure"
            return result

        # 3. Verify
        resp2 = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_read)
        bindings2 = resp2.get('results', {}).get('bindings', [])
        if bindings2 and bindings2[0]['name']['value'] == new_name:
            result["passed"] = True
            logger.info(f"    ✅ Update verified")
        else:
            actual = bindings2[0]['name']['value'] if bindings2 else "(none)"
            result["error"] = f"Update not verified: expected '{new_name}', got '{actual}'"
            logger.error(f"    ❌ {result['error']}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"    Update error: {e}")
    return result


async def step_delete_entity(space_impl: SparqlSQLSpaceImpl,
                             entity_uri: str) -> Dict[str, Any]:
    """Delete all quads for the entity (as subject) and verify."""
    result = {"name": "Delete entity", "passed": False, "error": None}
    try:
        count_before = await space_impl.get_rdf_quad_count(TEST_SPACE_ID, graph_uri=TEST_GRAPH_URI)

        # Delete quads where entity is the subject
        await space_impl.db_ops.remove_quads_by_subject_uris(
            TEST_SPACE_ID, [entity_uri], graph_id=TEST_GRAPH_URI)

        count_after = await space_impl.get_rdf_quad_count(TEST_SPACE_ID, graph_uri=TEST_GRAPH_URI)
        removed = count_before - count_after
        logger.info(f"    Removed {removed} quads (subject={entity_uri})")

        # Verify entity gone via SPARQL
        sparql = f"""
            SELECT ?p ?o WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    <{entity_uri}> ?p ?o .
                }}
            }} LIMIT 1
        """
        resp = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql)
        bindings = resp.get('results', {}).get('bindings', [])

        if len(bindings) == 0:
            result["passed"] = True
            logger.info(f"    ✅ Entity deleted and verified gone")
        else:
            result["error"] = f"Entity still has {len(bindings)} triples after delete"
            logger.error(f"    ❌ {result['error']}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"    Delete error: {e}")
    return result


# ===========================================================================
# Main
# ===========================================================================

async def main():
    print("\n" + "=" * 80)
    print("  Direct Lead Entity CRUD Test — Production RDS")
    print("=" * 80)
    print_connection_info()
    print(f"  Sidecar: {SIDECAR_URL}")
    print(f"  Space:   {TEST_SPACE_ID}")
    print(f"  Graph:   {TEST_GRAPH_URI}")
    print(f"  Data:    {LEAD_DATA_DIR}")
    print(f"  Limit:   {LEAD_FILE_LIMIT} files")

    # Check data directory
    if not LEAD_DATA_DIR.exists():
        logger.error(f"❌ Lead data directory not found: {LEAD_DATA_DIR}")
        return False

    lead_files = get_lead_files(limit=LEAD_FILE_LIMIT)
    if not lead_files:
        logger.error(f"❌ No lead .nt files found")
        return False
    logger.info(f"  Found {len(lead_files)} lead file(s)\n")

    # Create SparqlSQLSpaceImpl with RDS config + local sidecar
    params = get_prod_connection_params()
    space_impl = SparqlSQLSpaceImpl(
        postgresql_config=params,
        sidecar_config={'url': SIDECAR_URL},
    )

    connected = await space_impl.connect()
    if not connected:
        logger.error("❌ Failed to connect to production RDS")
        return False
    logger.info("✅ Connected to production RDS\n")

    t0 = time.time()
    all_results: List[Dict[str, Any]] = []

    try:
        # Pre-test cleanup: if space already exists, delete it
        if await space_impl.space_exists(TEST_SPACE_ID):
            logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
            await space_impl.delete_space_storage(TEST_SPACE_ID)

        # Create space + metadata + graph
        ok = await space_impl.create_space_storage(TEST_SPACE_ID)
        if not ok:
            logger.error("❌ Failed to create space storage")
            return False
        await space_impl.create_space_metadata(TEST_SPACE_ID, {
            'space_name': 'Prod Lead CRUD Test',
            'space_description': 'Direct lead CRUD test on production RDS',
        })
        await space_impl.create_graph(TEST_SPACE_ID, TEST_GRAPH_URI)
        logger.info(f"  ✅ Space '{TEST_SPACE_ID}' + graph created\n")

        # Process each lead file
        for idx, lead_file in enumerate(lead_files, 1):
            print(f"\n{'#' * 80}")
            print(f"  Lead {idx}/{len(lead_files)}: {lead_file.name}")
            print(f"{'#' * 80}")

            # Step 1: Load
            load_result = await step_load(space_impl, lead_file)
            all_results.append(load_result)

            if not load_result["passed"]:
                logger.error(f"  ❌ Load failed — skipping remaining steps")
                continue

            entity_uri = load_result["entity_uri"]

            # Step 2: Verify
            verify_result = await step_verify(
                space_impl, entity_uri, load_result["triple_count"])
            all_results.append(verify_result)

            # Step 3: Query frames
            query_result = await step_query_frames(space_impl, entity_uri)
            all_results.append(query_result)

            # Step 4: Update slot
            update_result = await step_update_slot(space_impl, entity_uri)
            all_results.append(update_result)

            # Step 5: Delete entity
            delete_result = await step_delete_entity(space_impl, entity_uri)
            all_results.append(delete_result)

        # Summary
        elapsed = time.time() - t0
        total = len(all_results)
        passed = sum(1 for r in all_results if r["passed"])
        failed = total - passed

        print("\n" + "=" * 80)
        print("  RESULTS")
        print("=" * 80)
        for r in all_results:
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            err = f"  — {r['error']}" if r.get("error") else ""
            print(f"  {status}: {r['name']}{err}")
        print("=" * 80)
        print(f"  {passed}/{total} passed, {failed} failed")
        print(f"  ⏱️  Total elapsed: {elapsed:.2f}s")
        print("=" * 80)

        return failed == 0

    finally:
        if DELETE_SPACE_AT_END:
            logger.info(f"\n  Deleting test space '{TEST_SPACE_ID}'...")
            try:
                await space_impl.delete_space_storage(TEST_SPACE_ID)
                logger.info(f"  ✅ Test space deleted")
            except Exception as e:
                logger.warning(f"  ⚠️  Cleanup error: {e}")
        await space_impl.disconnect()
        logger.info(f"  ✅ Disconnected")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
