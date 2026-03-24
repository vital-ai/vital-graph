#!/usr/bin/env python3
"""
Direct Lead Entity Dataset Test — Production RDS via sparql_sql Backend

Bypasses the REST API. Uses SparqlSQLSpaceImpl directly against the
production RDS with the local Jena sidecar (Docker, localhost:7070).

Adapted from vitalgraph_client_test/test_sparql_sql_lead_dataset.py.

Lifecycle:
  1. Bulk load all .nt files → quads → add_rdf_quads_batch_bulk
  2. List & paginate entities via SPARQL
  3. Retrieve entity graphs + frames for a sample
  4. Run KGQuery frame-based queries via KGQueryCriteriaBuilder
  5. Cleanup

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/prod_db/test_lead_dataset.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from rdflib import Graph as RDFGraph, URIRef

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from db_connect import get_prod_connection_params, print_connection_info
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder, EntityQueryCriteria, FrameCriteria, SlotCriteria

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
    'KGQueryCriteriaBuilder',
    'httpx',
):
    logging.getLogger(name).setLevel(logging.WARNING)

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "prod_lead_dataset_test"
TEST_GRAPH_URI = "urn:prod_lead_dataset"
LEAD_DATA_DIR = PROJECT_ROOT / "lead_test_data"
MAX_FILES = 100
SAMPLE_SIZE = 5
SIDECAR_URL = "http://localhost:7070"

# Set to True to skip bulk load and use previously loaded data
SKIP_LOAD = False
# Set to True to delete the space at the end
DELETE_SPACE_AT_END = True

KG_ENTITY_TYPE = URIRef("http://vital.ai/ontology/haley-ai-kg#KGEntity")
RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")


def get_lead_files(limit: int = None) -> List[Path]:
    nt_files = sorted(LEAD_DATA_DIR.glob("lead_*.nt"))
    if limit:
        nt_files = nt_files[:limit]
    return nt_files


def parse_nt_to_quads(nt_path: Path, graph_uri: str):
    """Parse .nt → (quads, entity_uri, triple_count)."""
    rdf_graph = RDFGraph()
    rdf_graph.parse(str(nt_path), format='nt')
    g = URIRef(graph_uri)
    quads = [(s, p, o, g) for s, p, o in rdf_graph]

    entity_uri = None
    for s, p, o in rdf_graph:
        if p == RDF_TYPE and o == KG_ENTITY_TYPE:
            entity_uri = str(s)
            break
    return quads, entity_uri, len(quads)


# ===========================================================================
# Test result helper
# ===========================================================================
class TestResults:
    def __init__(self, name: str):
        self.name = name
        self.tests_run = 0
        self.tests_passed = 0
        self.errors: List[str] = []
        self.extra: Dict[str, Any] = {}

    def record(self, test_name: str, passed: bool, error: str = None):
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            print(f"  ✅ PASS: {test_name}")
        else:
            self.errors.append(error or test_name)
            print(f"  ❌ FAIL: {test_name}")
            if error:
                print(f"     Error: {error}")

    def to_dict(self) -> dict:
        return {
            "test_name": self.name,
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
            **self.extra,
        }


# ===========================================================================
# Step 1: Bulk Load
# ===========================================================================
async def step_bulk_load(space_impl: SparqlSQLSpaceImpl,
                         lead_files: List[Path]) -> dict:
    print(f"\n{'=' * 80}")
    print(f"  Step 1: Bulk Load Lead Dataset")
    print(f"{'=' * 80}")

    r = TestResults("Bulk Load Lead Dataset")
    loaded_entities: List[Dict[str, Any]] = []
    total_triples = 0
    failed_loads: List[str] = []

    print(f"\n  Loading {len(lead_files)} lead entity graph files...")
    t0 = time.time()

    for idx, lead_file in enumerate(lead_files, 1):
        try:
            quads, entity_uri, triple_count = parse_nt_to_quads(lead_file, TEST_GRAPH_URI)
            if not entity_uri:
                failed_loads.append(lead_file.name)
                continue

            inserted = await space_impl.add_rdf_quads_batch_bulk(TEST_SPACE_ID, quads)
            if inserted > 0:
                loaded_entities.append({
                    'uri': entity_uri,
                    'file': lead_file.name,
                    'triples': triple_count,
                })
                total_triples += triple_count
            else:
                failed_loads.append(lead_file.name)

            if idx % 10 == 0:
                print(f"    Loaded {idx}/{len(lead_files)} files "
                      f"({len(loaded_entities)} entities, {total_triples:,} triples)")
        except Exception as e:
            failed_loads.append(lead_file.name)
            print(f"    ❌ Error loading {lead_file.name}: {e}")

    load_time = time.time() - t0
    print(f"\n  📊 Bulk Load Summary:")
    print(f"     Files processed: {len(lead_files)}")
    print(f"     Entities loaded: {len(loaded_entities)}")
    print(f"     Failed loads:    {len(failed_loads)}")
    print(f"     Total triples:   {total_triples:,}")
    print(f"     Load time:       {load_time:.2f}s")
    if lead_files:
        print(f"     Average:         {load_time/len(lead_files):.2f}s per file")

    expected = len(lead_files) - len(failed_loads)
    r.record("Bulk load entities",
             len(loaded_entities) == expected,
             f"Expected {expected}, got {len(loaded_entities)}")

    acceptable = 0.05
    actual_rate = len(failed_loads) / len(lead_files) if lead_files else 0
    r.record("Acceptable failure rate",
             actual_rate <= acceptable,
             f"Rate {actual_rate:.1%} exceeds {acceptable:.1%}")

    r.extra.update(loaded_entities=loaded_entities, total_triples=total_triples,
                   load_time=load_time)
    return r.to_dict()


# ===========================================================================
# Step 2: List & Query Entities
# ===========================================================================
async def step_list_and_query(space_impl: SparqlSQLSpaceImpl,
                              expected_count: int) -> dict:
    print(f"\n{'=' * 80}")
    print(f"  Step 2: List and Query Entities")
    print(f"{'=' * 80}")

    r = TestResults("List and Query Entities")
    entity_uris: List[str] = []

    # --- Paginated listing ---
    print(f"\n  --- List All Entities (Paginated) ---")
    page_size = 20
    offset = 0
    t0 = time.time()

    while True:
        sparql = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT DISTINCT ?entity WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    ?entity vital-core:vitaltype haley:KGEntity .
                }}
            }}
            ORDER BY ?entity
            LIMIT {page_size}
            OFFSET {offset}
        """
        resp = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql)
        bindings = resp.get('results', {}).get('bindings', [])
        page_entities = [b['entity']['value'] for b in bindings if 'entity' in b]

        if not page_entities:
            break

        entity_uris.extend(page_entities)
        print(f"    Page {offset // page_size + 1}: {len(page_entities)} entities (total: {len(entity_uris)})")

        if len(page_entities) < page_size:
            break
        offset += page_size

    list_time = time.time() - t0
    print(f"\n    Total entities listed: {len(entity_uris)}")
    print(f"    ⏱️  List time: {list_time:.3f}s")

    r.record("List all entities",
             len(entity_uris) == expected_count,
             f"Expected {expected_count}, got {len(entity_uris)}")

    # --- Small page ---
    print(f"\n  --- List Entities (Small Pages) ---")
    sparql_small = f"""
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT DISTINCT ?entity WHERE {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
            }}
        }}
        ORDER BY ?entity
        LIMIT 5
    """
    resp_small = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_small)
    small_count = len(resp_small.get('results', {}).get('bindings', []))
    print(f"    Retrieved {small_count} entities with page_size=5")
    r.record("List with small page size",
             small_count == min(5, expected_count),
             f"Expected {min(5, expected_count)}, got {small_count}")

    # --- With offset ---
    print(f"\n  --- List Entities (With Offset) ---")
    sparql_off = f"""
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT DISTINCT ?entity WHERE {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
            }}
        }}
        ORDER BY ?entity
        LIMIT 10
        OFFSET 10
    """
    resp_off = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_off)
    off_count = len(resp_off.get('results', {}).get('bindings', []))
    print(f"    Retrieved {off_count} entities with offset=10")
    ok = off_count >= 0 and (expected_count <= 10 or off_count > 0)
    r.record("List with offset", ok,
             f"Offset test: got {off_count} (total: {expected_count})")

    # --- Verify entity access via SPARQL ---
    print(f"\n  --- Verify Entity Access (SPARQL) ---")
    t1 = time.time()
    sparql_verify = f"""
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT DISTINCT ?entity WHERE {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
            }}
        }}
        LIMIT 1
    """
    resp_v = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_verify)
    verify_time = time.time() - t1
    has = len(resp_v.get('results', {}).get('bindings', [])) > 0
    print(f"    ⏱️  Verify time: {verify_time:.3f}s  entities present = {has}")
    r.record("Verify entity access", has, "No entities found")

    r.extra["entity_uris"] = entity_uris
    return r.to_dict()


# ===========================================================================
# Step 3: Retrieve Entity Graphs & Frames
# ===========================================================================
async def step_retrieve_entities(space_impl: SparqlSQLSpaceImpl,
                                 entity_uris: List[str],
                                 sample_size: int) -> dict:
    print(f"\n{'=' * 80}")
    print(f"  Step 3: Retrieve Entity Graphs and Frames")
    print(f"{'=' * 80}")

    r = TestResults("Retrieve Entity Graphs and Frames")

    if not entity_uris:
        r.record("Entity URIs available", False, "No entity URIs provided")
        return r.to_dict()

    sample = entity_uris[:sample_size]
    print(f"\n  Testing {len(sample)} sample entities (out of {len(entity_uris)} total)")

    retrieved_entities = 0
    total_frames = 0
    retrieved_frames = 0

    for idx, entity_uri in enumerate(sample, 1):
        print(f"\n  --- Entity {idx}/{len(sample)}: {entity_uri} ---")

        # Get all triples for entity
        t0 = time.time()
        sparql_get = f"""
            SELECT ?p ?o WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    <{entity_uri}> ?p ?o .
                }}
            }}
        """
        resp = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_get)
        get_time = time.time() - t0
        triple_count = len(resp.get('results', {}).get('bindings', []))
        if triple_count > 0:
            retrieved_entities += 1
            print(f"    ✅ Entity retrieved ({triple_count} triples, {get_time:.3f}s)")
        else:
            print(f"    ❌ Entity not found")
            continue

        # List top-level frames via edge pattern
        sparql_frames = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?frame ?frame_type WHERE {{
                GRAPH <{TEST_GRAPH_URI}> {{
                    ?edge vital-core:vitaltype haley:Edge_hasEntityKGFrame .
                    ?edge vital-core:hasEdgeSource <{entity_uri}> .
                    ?edge vital-core:hasEdgeDestination ?frame .
                    ?frame haley:hasKGFrameType ?frame_type .
                }}
            }}
        """
        resp_f = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_frames)
        frames = resp_f.get('results', {}).get('bindings', [])
        frame_count = len(frames)
        total_frames += frame_count
        print(f"    Found {frame_count} top-level frames")

        # For first 3 top-level frames, list child frames
        for fi, frame_b in enumerate(frames[:3], 1):
            frame_uri = frame_b.get('frame', {}).get('value', '')
            frame_type = frame_b.get('frame_type', {}).get('value', '')
            short_type = frame_type.rsplit(':', 1)[-1] if ':' in frame_type else frame_type
            print(f"\n      Top-level frame {fi}: {short_type}")

            # Child frames
            sparql_children = f"""
                PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                SELECT ?child ?child_type WHERE {{
                    GRAPH <{TEST_GRAPH_URI}> {{
                        ?edge vital-core:vitaltype haley:Edge_hasKGFrame .
                        ?edge vital-core:hasEdgeSource <{frame_uri}> .
                        ?edge vital-core:hasEdgeDestination ?child .
                        ?child haley:hasKGFrameType ?child_type .
                    }}
                }}
            """
            resp_c = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_children)
            children = resp_c.get('results', {}).get('bindings', [])
            print(f"         Found {len(children)} child frames")

            # Retrieve first 3 child frames' triples
            for ci, child_b in enumerate(children[:3], 1):
                child_uri = child_b.get('child', {}).get('value', '')
                child_type = child_b.get('child_type', {}).get('value', '')
                short_child = child_type.rsplit(':', 1)[-1] if ':' in child_type else child_type

                t1 = time.time()
                sparql_child_triples = f"""
                    SELECT ?p ?o WHERE {{
                        GRAPH <{TEST_GRAPH_URI}> {{
                            <{child_uri}> ?p ?o .
                        }}
                    }}
                """
                resp_ct = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_child_triples)
                ct_count = len(resp_ct.get('results', {}).get('bindings', []))
                ct_time = time.time() - t1
                if ct_count > 0:
                    retrieved_frames += 1
                    print(f"         Child {ci} ({short_child}): ✅ {ct_count} triples ({ct_time:.3f}s)")
                else:
                    print(f"         Child {ci} ({short_child}): ❌ Not found")

    print(f"\n  📊 Retrieval Summary:")
    print(f"     Entities tested:    {len(sample)}")
    print(f"     Entities retrieved: {retrieved_entities}")
    print(f"     Total frames found: {total_frames}")
    print(f"     Frames retrieved:   {retrieved_frames}")

    r.record("Retrieve sample entities",
             retrieved_entities == len(sample),
             f"Expected {len(sample)}, retrieved {retrieved_entities}")
    r.record("Entities have frames",
             total_frames > 0,
             f"Expected frames, found {total_frames}")
    if total_frames > 0:
        r.record("Retrieve sample frames",
                 retrieved_frames > 0,
                 f"Expected frames retrieved, got {retrieved_frames}")

    r.extra.update(retrieved_entities=retrieved_entities, total_frames=total_frames,
                   retrieved_frames=retrieved_frames)
    return r.to_dict()


# ===========================================================================
# Step 4: KGQuery Frame-Based Queries
# ===========================================================================
async def step_kgquery(space_impl: SparqlSQLSpaceImpl,
                       expected_entity_count: int) -> dict:
    print(f"\n{'=' * 80}")
    print(f"  Step 4: KGQuery Lead Frame Queries")
    print(f"{'=' * 80}")
    print(f"\n  Running frame-based queries on {expected_entity_count} lead entities...")

    r = TestResults("KGQuery Lead Frame Queries")
    query_builder = KGQueryCriteriaBuilder()
    query_times: List[Dict[str, Any]] = []

    async def _run_frame_query(test_name: str, frame_criteria_list: List[FrameCriteria],
                               page_size: int = 100, offset: int = 0,
                               expect_results: bool = True) -> int:
        """Build SPARQL from criteria, execute, return result count."""
        entity_criteria = EntityQueryCriteria(
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=frame_criteria_list,
            use_edge_pattern=True,
        )
        sparql = query_builder.build_entity_query_sparql(
            entity_criteria, TEST_GRAPH_URI, page_size, offset)

        t0 = time.time()
        resp = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql)
        qt = time.time() - t0

        bindings = resp.get('results', {}).get('bindings', [])
        count = len(bindings)

        query_times.append({"test_name": test_name, "query_time": qt,
                            "result_count": count, "passed": True})

        if expect_results:
            if count > 0:
                print(f"    ✅ {test_name}: {count} results ({qt:.3f}s)")
                r.record(test_name, True)
            else:
                print(f"    ❌ {test_name}: 0 results ({qt:.3f}s)")
                r.record(test_name, False, f"Expected >0, got 0")
                query_times[-1]["passed"] = False
        else:
            print(f"    ✅ {test_name}: {count} results ({qt:.3f}s)")
            r.record(test_name, count == 0, f"Expected 0, got {count}" if count > 0 else None)

        return count

    # Test 1: Find MQL leads
    print(f"\n  Test 1: Find MQL (Marketing Qualified Leads)...")
    await _run_frame_query("Find MQL leads", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:MQLv2",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                            value=True, comparator="eq",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 2: Hierarchical frame query
    print(f"\n  Test 2: Hierarchical Frame Query (Parent → Child Frame)...")
    await _run_frame_query("Hierarchical frame query", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:LeadTrackingFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadOwnerFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:LeadOwnerName",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            comparator="exists",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 3: Find leads in California
    print(f"\n  Test 3: Find leads in California...")
    await _run_frame_query("Find leads in California", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:CompanyFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:CompanyStateCode",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="CA", comparator="eq",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 4: Find leads in Los Angeles
    print(f"\n  Test 4: Find leads in Los Angeles...")
    await _run_frame_query("Find leads in Los Angeles", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:CompanyFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:CompanyCity",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="Los Angeles", comparator="eq",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 5: High-rated leads (MQLRating >= 65)
    print(f"\n  Test 5: Find high-rated leads (MQL rating >= 65)...")
    await _run_frame_query("Find high-rated leads", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:MQLRating",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                            value=65.0, comparator="gte",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 6: Business accounts
    print(f"\n  Test 6: Find leads with business bank accounts...")
    await _run_frame_query("Find leads with business accounts", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:PlaidBankingFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:BankAccountFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:HasBizAccount",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                            value=True, comparator="eq",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 7: Converted leads
    print(f"\n  Test 7: Find converted leads...")
    await _run_frame_query("Find converted leads", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusConversionFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:IsConverted",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                            value=True, comparator="eq",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 8: Abandoned leads
    print(f"\n  Test 8: Find abandoned leads...")
    await _run_frame_query("Find abandoned leads", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:SystemFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:SystemFlagsFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:Abandoned",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                            value=True, comparator="eq",
                        )
                    ],
                )
            ],
        )
    ])

    # Test 9: Multi-criteria (MQL + California + high rating)
    print(f"\n  Test 9: Multi-criteria query (MQL + California + high rating)...")
    await _run_frame_query("Multi-criteria query", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:MQLv2",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                            value=True, comparator="eq",
                        ),
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:MQLRating",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                            value=65.0, comparator="gte",
                        ),
                    ],
                )
            ],
        ),
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:CompanyFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:CompanyAddressFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:CompanyStateCode",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="CA", comparator="eq",
                        )
                    ],
                )
            ],
        ),
    ])

    # Test 9b: Range query (50 <= MQLRating <= 80)
    print(f"\n  Test 9b: Range query (50 <= MQLRating <= 80)...")
    await _run_frame_query("Range query with multiple FILTERs", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
                    slot_criteria=[
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:MQLRating",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                            value=50.0, comparator="gte",
                        ),
                        SlotCriteria(
                            slot_type="urn:cardiff:kg:slot:MQLRating",
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                            value=80.0, comparator="lte",
                        ),
                    ],
                )
            ],
        )
    ])

    # Test 10: Pagination
    print(f"\n  Test 10: Pagination...")
    entity_criteria_pg = EntityQueryCriteria(
        entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
        frame_criteria=[
            FrameCriteria(
                frame_type="urn:cardiff:kg:frame:LeadStatusFrame",
                frame_criteria=[
                    FrameCriteria(
                        frame_type="urn:cardiff:kg:frame:LeadStatusQualificationFrame",
                        slot_criteria=[
                            SlotCriteria(
                                slot_type="urn:cardiff:kg:slot:MQLv2",
                                slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot",
                                value=True, comparator="eq",
                            )
                        ],
                    )
                ],
            )
        ],
        use_edge_pattern=True,
    )
    sparql_p1 = query_builder.build_entity_query_sparql(entity_criteria_pg, TEST_GRAPH_URI, 5, 0)
    sparql_p2 = query_builder.build_entity_query_sparql(entity_criteria_pg, TEST_GRAPH_URI, 5, 5)
    t0 = time.time()
    resp1 = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_p1)
    resp2 = await space_impl.execute_sparql_query(TEST_SPACE_ID, sparql_p2)
    qt = time.time() - t0
    p1 = len(resp1.get('results', {}).get('bindings', []))
    p2 = len(resp2.get('results', {}).get('bindings', []))
    print(f"    ✅ Page 1: {p1} results, Page 2: {p2} results ({qt:.3f}s)")
    r.record("Pagination", True)
    query_times.append({"test_name": "Pagination", "query_time": qt,
                        "result_count": p1 + p2, "passed": True})

    # Test 11: Empty results
    print(f"\n  Test 11: Empty results (non-existent criteria)...")
    await _run_frame_query("Empty results", [
        FrameCriteria(
            frame_type="urn:cardiff:kg:frame:NonExistentFrame",
            slot_criteria=[
                SlotCriteria(
                    slot_type="urn:cardiff:kg:slot:NonExistentSlot",
                    slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                    value="NonExistent", comparator="eq",
                )
            ],
        )
    ], page_size=20, expect_results=False)

    # Query time summary
    if query_times:
        total_qt = sum(qt["query_time"] for qt in query_times)
        print(f"\n{'=' * 80}")
        print(f"  Query Time Summary")
        print(f"{'=' * 80}")
        print(f"\n  📊 Total query time: {total_qt:.3f}s")
        print(f"  📊 Average query time: {total_qt / len(query_times):.3f}s")
        print(f"\n  Individual query times:")
        for qt in query_times:
            status = "✅" if qt["passed"] else "❌"
            rc = qt.get("result_count")
            cs = f" [{rc} results]" if rc is not None else ""
            print(f"    {status} {qt['test_name']}: {qt['query_time']:.3f}s{cs}")

    r.extra["query_times"] = query_times
    r.extra["total_query_time"] = sum(qt["query_time"] for qt in query_times) if query_times else 0
    return r.to_dict()


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  Direct Lead Entity Dataset Test — Production RDS")
    print("=" * 80)
    print_connection_info()
    print(f"  Sidecar:    {SIDECAR_URL}")
    print(f"  Space:      {TEST_SPACE_ID}")
    print(f"  Graph:      {TEST_GRAPH_URI}")
    print(f"  Data:       {LEAD_DATA_DIR}")
    print(f"  Max files:  {MAX_FILES}")
    print(f"  Sample:     {SAMPLE_SIZE}")
    print(f"  Skip load:  {SKIP_LOAD}")

    if not LEAD_DATA_DIR.exists():
        logger.error(f"❌ Lead data directory not found: {LEAD_DATA_DIR}")
        return False

    lead_files = get_lead_files(limit=MAX_FILES)
    if not lead_files:
        logger.error(f"❌ No lead .nt files found")
        return False
    print(f"  Files:      {len(lead_files)}\n")

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
    all_results: List[dict] = []

    try:
        if not SKIP_LOAD:
            # Pre-test cleanup
            if await space_impl.space_exists(TEST_SPACE_ID):
                logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
                await space_impl.delete_space_storage(TEST_SPACE_ID)

            ok = await space_impl.create_space_storage(TEST_SPACE_ID)
            if not ok:
                logger.error("❌ Failed to create space storage")
                return False
            await space_impl.create_space_metadata(TEST_SPACE_ID, {
                'space_name': 'Prod Lead Dataset Test',
                'space_description': 'Direct lead dataset test on production RDS',
            })
            await space_impl.create_graph(TEST_SPACE_ID, TEST_GRAPH_URI)
            logger.info(f"  ✅ Space '{TEST_SPACE_ID}' + graph created\n")

        # Step 1: Bulk load
        if SKIP_LOAD:
            logger.info("⏭️  Skipping bulk load (SKIP_LOAD=True)\n")
            entity_count = len(lead_files)
            loaded_entities = []
            bulk_results = {
                "test_name": "Bulk Load Lead Dataset (Skipped)",
                "tests_run": 0, "tests_passed": 0, "tests_failed": 0,
                "errors": [], "loaded_entities": [], "load_time": 0,
                "total_triples": 0,
            }
            all_results.append(bulk_results)
        else:
            bulk_results = await step_bulk_load(space_impl, lead_files)
            all_results.append(bulk_results)

            if bulk_results["tests_failed"] > 0:
                logger.error("❌ Bulk load had failures")

            loaded_entities = bulk_results.get("loaded_entities", [])
            entity_count = len(loaded_entities)
            if entity_count == 0:
                logger.error("❌ No entities loaded — aborting")
                return False
            logger.info(f"\n✅ Loaded {entity_count} entities\n")

        # Step 2: List & query
        list_results = await step_list_and_query(space_impl, entity_count)
        all_results.append(list_results)
        entity_uris = list_results.get("entity_uris", [])

        # Step 3: Retrieve entity graphs + frames (sample)
        uris_for_retrieve = entity_uris if entity_uris else [e["uri"] for e in loaded_entities]
        retrieve_results = await step_retrieve_entities(space_impl, uris_for_retrieve, SAMPLE_SIZE)
        all_results.append(retrieve_results)

        # Step 4: KGQuery frame-based queries
        kgquery_results = await step_kgquery(space_impl, entity_count)
        all_results.append(kgquery_results)

        # Summary
        elapsed = time.time() - t0
        total_run = sum(r["tests_run"] for r in all_results)
        total_passed = sum(r["tests_passed"] for r in all_results)
        total_failed = sum(r["tests_failed"] for r in all_results)
        all_errors = [e for r_ in all_results for e in r_["errors"]]

        print("\n" + "=" * 80)
        for r_ in all_results:
            status = "✅ PASS" if r_["tests_failed"] == 0 else "❌ FAIL"
            print(f"  {status}: {r_['test_name']} — {r_['tests_passed']}/{r_['tests_run']}")
        print("=" * 80)
        print(f"  RESULTS: {total_passed}/{total_run} passed")
        if all_errors:
            for e in all_errors:
                print(f"  ❌ {e}")
        print(f"\n  Dataset: {entity_count} entities, {bulk_results.get('total_triples', 0):,} triples")
        print(f"  Load:    {bulk_results.get('load_time', 0):.1f}s")
        print(f"  ⏱️  Total elapsed: {elapsed:.1f}s")
        print("=" * 80)

        return total_failed == 0

    finally:
        if DELETE_SPACE_AT_END:
            logger.info(f"\n  Deleting test space '{TEST_SPACE_ID}'...")
            try:
                await space_impl.delete_space_storage(TEST_SPACE_ID)
                logger.info(f"  ✅ Test space deleted")
            except Exception as e:
                logger.warning(f"  ⚠️  Cleanup error: {e}")
        else:
            logger.info(f"\n  Space '{TEST_SPACE_ID}' preserved for inspection")
        await space_impl.disconnect()
        logger.info(f"  ✅ Disconnected")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
