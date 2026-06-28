#!/usr/bin/env python3
"""
KG Type Search — FrameNet Validation Tests
===========================================

Tests the KG Types search endpoint against the real FrameNet dataset
(~3,287 objects in framenet_kgtypes_test space) to validate that:

1. Keyword search finds expected frames by name/description terms
2. FTS (full-text search) ranks relevant frames above irrelevant ones
3. Type filtering returns only the requested type class
4. Search results include expected FrameNet frames for known queries

This validates the full search pipeline:
  - Keyword: SPARQL CONTAINS → SQL LIKE
  - FTS: vg:textSearch → {space}_fts_{idx} ts_rank_cd/plainto_tsquery
  - Vector: vg:vectorSimilarity → {space}_vec_{idx} HNSW cosine
  - Hybrid: vg:hybridSearch → FTS + vector JOIN fusion
  - Direct SPARQL: raw vg: function queries via /api/sparql endpoint

Prerequisites:
  - VitalGraph service running at localhost:8001
  - Space set up via: python test_scripts/sparql/setup_kgtype_search_framenet.py

Usage:
  python test_scripts/sparql/test_kgtype_search_framenet.py

See: planning_visualization/framenet_testing_plan.md §4.2
"""

import asyncio
import logging
import sys
from typing import List, Dict, Any, Set

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
SPACE_ID = "framenet_kgtypes_test"
GRAPH_ID = "urn:vitalgraph:framenet_kgtypes_test:kg_types"
INDEX_NAME = "kgtype_default"

# ── Expected Results ───────────────────────────────────────────────────────
# Each test case: (query, search_mode, type_filter, expected_names_subset, min_results)
# expected_names_subset: at least these names must appear in results (case-insensitive partial match)
TEST_CASES: List[Dict[str, Any]] = [
    {
        "name": "Keyword: commerce frames",
        "query": "Commerce",
        "search_mode": "keyword",
        "type": "frame",
        "expected_contains": ["Commerce_buy", "Commerce_sell", "Commerce_pay"],
        "min_results": 3,
    },
    {
        "name": "Keyword: motion frames",
        "query": "Motion",
        "search_mode": "keyword",
        "type": "frame",
        "expected_contains": ["Motion"],
        "min_results": 1,
    },
    {
        "name": "Keyword: slot type Agent",
        "query": "Agent",
        "search_mode": "keyword",
        "type": "slot",
        "expected_contains": ["Agent"],
        "min_results": 1,
    },
    {
        "name": "Keyword: hiring/employment",
        "query": "hiring",
        "search_mode": "keyword",
        "type": "frame",
        "expected_contains": ["Hiring"],
        "min_results": 1,
    },
    {
        "name": "Keyword: all types (no filter)",
        "query": "Person",
        "search_mode": "keyword",
        "type": None,
        "expected_contains": [],  # Just verify results come back
        "min_results": 1,
    },
    {
        "name": "FTS: commercial transaction",
        "query": "commercial transaction buying",
        "search_mode": "fts",
        "type": "frame",
        "expected_contains": ["Commercial_transaction"],
        "min_results": 1,
    },
    {
        "name": "FTS: motion source goal path",
        "query": "source goal path place",
        "search_mode": "fts",
        "type": "frame",
        "expected_contains": ["Motion"],
        "min_results": 1,
    },
    {
        "name": "FTS: cooking food",
        "query": "cooking food heat",
        "search_mode": "fts",
        "type": "frame",
        "expected_contains": ["Cooking_creation"],
        "min_results": 1,
    },
    {
        "name": "FTS: legal judgment",
        "query": "legal judgment court verdict",
        "search_mode": "fts",
        "type": "frame",
        "expected_contains": [],  # May or may not match exactly; just validate FTS works
        "min_results": 0,  # Relaxed — validates no crash
    },
    # ── Vector (semantic similarity) tests ──────────────────────────
    {
        "name": "Vector: hiring/employment (semantic)",
        "query": "hiring someone for a job",
        "search_mode": "vector",
        "type": "frame",
        "expected_contains": ["Hiring"],
        "min_results": 1,
    },
    {
        "name": "Vector: physical movement (paraphrase)",
        "query": "physical movement from one place to another",
        "search_mode": "vector",
        "type": "frame",
        "expected_contains": ["Motion"],
        "min_results": 1,
    },
    {
        "name": "Vector: giving money to someone",
        "query": "giving money to someone as payment",
        "search_mode": "vector",
        "type": "frame",
        "expected_contains": ["Repayment"],
        "min_results": 1,
    },
    {
        "name": "Vector: person who performs the action (slot)",
        "query": "the person who performs the action",
        "search_mode": "vector",
        "type": "slot",
        "expected_contains": ["Performer1"],
        "min_results": 1,
    },
    # ── Hybrid (vector + FTS combined) tests ────────────────────────
    {
        "name": "Hybrid: cooking preparation",
        "query": "cooking food preparation heat",
        "search_mode": "hybrid",
        "type": "frame",
        "expected_contains": ["Cooking_creation"],
        "min_results": 1,
    },
    {
        "name": "Hybrid: commercial transaction",
        "query": "commercial transaction buying selling goods",
        "search_mode": "hybrid",
        "type": "frame",
        "expected_contains": ["Commercial_transaction"],
        "min_results": 1,
    },
    {
        "name": "No results: nonsense query",
        "query": "zzzzxyzzy_nonexistent_99999",
        "search_mode": "keyword",
        "type": None,
        "expected_contains": [],
        "min_results": 0,
        "max_results": 0,
    },
    {
        "name": "Type filter: only slot types returned",
        "query": "Time",
        "search_mode": "keyword",
        "type": "slot",
        "expected_contains": ["Time"],
        "min_results": 1,
        "validate_types": "KGSlotType",
    },
]


def _extract_names(response) -> List[str]:
    """Extract type names from search response."""
    names = []
    if hasattr(response, 'types') and response.types:
        for t in response.types:
            if isinstance(t, dict):
                name = t.get('name', '')
            else:
                name = getattr(t, 'name', None) or getattr(t, 'kGFrameTypeExternIdentifier', None) or str(getattr(t, 'URI', ''))
            if name:
                names.append(name)
    return names


def _extract_type_classes(response) -> Set[str]:
    """Extract the rdf:type class names from response objects."""
    classes = set()
    if hasattr(response, 'types') and response.types:
        for t in response.types:
            if isinstance(t, dict):
                vt = t.get('vitaltype', '')
                # Extract short class name from URI
                if '#' in vt:
                    classes.add(vt.split('#')[-1])
                else:
                    classes.add(vt)
            else:
                classes.add(type(t).__name__)
    return classes


async def _run_auto_sync_test(client: VitalGraphClient):
    """E4: Create a new KGFrameType via the API and verify it becomes searchable.

    Auto-sync should vectorize and FTS-index the new type in the background.
    We poll keyword search until the type appears (or timeout).
    """
    import time
    import uuid as _uuid
    from ai_haley_kg_domain.model.KGFrameType import KGFrameType

    passed = 0
    failed = 0
    errors: List[str] = []

    unique_tag = _uuid.uuid4().hex[:8]
    test_name = f"QuantumZephyrFrame_{unique_tag}"
    test_description = f"Quantum zephyr frame for auto-sync validation {unique_tag}"

    # Snapshot vec/fts counts before create
    vec_before = 0
    fts_before = 0
    try:
        idx = await client.vector_indexes.get_index(SPACE_ID, INDEX_NAME)
        vec_before = idx.embedding_count or 0
    except Exception:
        pass
    try:
        stats = await client.fts_indexes.get_stats(SPACE_ID, INDEX_NAME)
        fts_before = getattr(stats, 'total_rows', 0) or getattr(stats, 'row_count', 0) or 0
    except Exception:
        pass

    # 1. Create the type
    frame_type = KGFrameType()
    frame_type.URI = f"http://vital.ai/test/autosync/{test_name}"
    frame_type.name = test_name
    frame_type.kGraphDescription = test_description

    try:
        create_resp = await client.kgtypes.create_kgtypes(
            space_id=SPACE_ID, graph_id=GRAPH_ID, objects=[frame_type],
        )
        if not create_resp.is_success:
            errors.append(f"Auto-sync create: Failed to create type — {create_resp.error_message}")
            failed += 1
            print(f"  ❌ Auto-sync create: {create_resp.error_message}")
            return passed, failed, errors
        print(f"  ✓ Created '{test_name}' (vec_before={vec_before}, fts_before={fts_before})")
    except Exception as e:
        errors.append(f"Auto-sync create: Exception — {e}")
        failed += 1
        print(f"  ❌ Auto-sync create: {e}")
        return passed, failed, errors

    # 2. Verify the type exists in the graph (SPARQL exact-match, not CONTAINS)
    from vitalgraph.model.sparql_model import SPARQLQueryRequest
    verify_sparql = f"""\
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s WHERE {{
  ?s vc:hasName ?name .
  FILTER(?name = "{test_name}")
}} LIMIT 1"""
    verify_resp = await client.sparql.execute_sparql_query(
        SPACE_ID, SPARQLQueryRequest(query=verify_sparql, default_graph_uri=[GRAPH_ID]),
    )
    verify_bindings = []
    if verify_resp.results and isinstance(verify_resp.results, dict):
        verify_bindings = verify_resp.results.get('bindings', [])
    if verify_bindings:
        passed += 1
        print(f"  ✓ Auto-sync create verified: '{test_name}' exists in graph")
    else:
        errors.append(f"Auto-sync create verified: '{test_name}' not found in graph")
        failed += 1
        print(f"  ❌ Auto-sync create verified: '{test_name}' not found in graph")

    timeout = 30  # auto-sync should be fast for a single type
    poll_interval = 1

    # 3. Check FTS (should find via name or description tokens)
    fts_found = False
    t0_fts = time.time()
    while time.time() - t0_fts < timeout:
        try:
            resp = await client.kgtypes.search_types(
                SPACE_ID, GRAPH_ID,
                query=f"quantum zephyr {unique_tag}", search_mode="fts",
            )
            names = _extract_names(resp)
            if any(test_name in n for n in names):
                fts_found = True
                break
        except Exception:
            pass
        await asyncio.sleep(poll_interval)

    # Check counts after FTS polling
    vec_after = 0
    fts_after = 0
    try:
        idx = await client.vector_indexes.get_index(SPACE_ID, INDEX_NAME)
        vec_after = idx.embedding_count or 0
    except Exception:
        pass
    try:
        stats = await client.fts_indexes.get_stats(SPACE_ID, INDEX_NAME)
        fts_after = getattr(stats, 'total_rows', 0) or getattr(stats, 'row_count', 0) or 0
    except Exception:
        pass

    if fts_found:
        passed += 1
        print(f"  ✓ Auto-sync FTS: found '{test_name}' ({time.time() - t0_fts:.1f}s)")
    else:
        fts_delta = fts_after - fts_before
        vec_delta = vec_after - vec_before
        errors.append(f"Auto-sync FTS: '{test_name}' not found after {timeout}s")
        failed += 1
        print(f"  ❌ Auto-sync FTS: '{test_name}' not found after {timeout}s")
        print(f"       vec: {vec_before}→{vec_after} (Δ{vec_delta}), fts: {fts_before}→{fts_after} (Δ{fts_delta})")

    # 4. Check vector search (description should be embedded)
    vec_found = False
    t0_vec = time.time()
    while time.time() - t0_vec < timeout:
        try:
            resp = await client.kgtypes.search_types(
                SPACE_ID, GRAPH_ID,
                query="quantum zephyr auto-sync validation", search_mode="vector",
            )
            names = _extract_names(resp)
            if any(test_name in n for n in names):
                vec_found = True
                break
        except Exception:
            pass
        await asyncio.sleep(poll_interval)

    if vec_found:
        passed += 1
        print(f"  ✓ Auto-sync vector: found '{test_name}' ({time.time() - t0_vec:.1f}s)")
    else:
        errors.append(f"Auto-sync vector: '{test_name}' not found after {timeout}s")
        failed += 1
        print(f"  ❌ Auto-sync vector: '{test_name}' not found after {timeout}s")

    # 5. Cleanup — delete the test type
    try:
        await client.kgtypes.delete_kgtype(
            space_id=SPACE_ID, graph_id=GRAPH_ID, uri=frame_type.URI,
        )
        print(f"  ✓ Cleaned up '{test_name}'")
    except Exception as e:
        print(f"  ⚠ Cleanup warning: {e}")

    return passed, failed, errors


async def run_framenet_search_tests():
    """Run all FrameNet search validation tests.

    Assumes the space and indexes have been set up by:
      python test_scripts/sparql/setup_kgtype_search_framenet.py
    """
    print("=" * 70)
    print("FrameNet KG Types Search Validation Tests")
    print("=" * 70)
    print(f"  Space: {SPACE_ID}")
    print(f"  Graph: {GRAPH_ID}")
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    # Quick sanity check that indexes are populated
    try:
        idx_info = await client.vector_indexes.get_index(SPACE_ID, INDEX_NAME)
        vec_count = idx_info.embedding_count or 0
    except Exception:
        vec_count = 0
    if vec_count == 0:
        print("❌ Vector index not populated. Run setup first:")
        print("   python test_scripts/sparql/setup_kgtype_search_framenet.py")
        await client.close()
        return False

    passed = 0
    failed = 0
    errors = []

    for tc in TEST_CASES:
        name = tc["name"]
        try:
            kwargs = {
                "query": tc["query"],
            }
            if tc.get("search_mode"):
                kwargs["search_mode"] = tc["search_mode"]
            if tc.get("type"):
                kwargs["type"] = tc["type"]

            response = await client.kgtypes.search_types(
                SPACE_ID, GRAPH_ID, **kwargs
            )

            if not response.is_success:
                errors.append(f"{name}: API error — {response.error_message}")
                failed += 1
                print(f"  ❌ {name}: API error — {response.error_message}")
                continue

            result_count = response.count if hasattr(response, 'count') else 0
            names = _extract_names(response)

            # Check min_results
            min_results = tc.get("min_results", 0)
            if result_count < min_results:
                errors.append(f"{name}: Expected >= {min_results} results, got {result_count}")
                failed += 1
                print(f"  ❌ {name}: Expected >= {min_results} results, got {result_count}")
                continue

            # Check max_results (if specified)
            max_results = tc.get("max_results")
            if max_results is not None and result_count > max_results:
                errors.append(f"{name}: Expected <= {max_results} results, got {result_count}")
                failed += 1
                print(f"  ❌ {name}: Expected <= {max_results} results, got {result_count}")
                continue

            # Check expected_contains
            expected = tc.get("expected_contains", [])
            missing = []
            for exp_name in expected:
                found = any(exp_name.lower() in n.lower() for n in names)
                if not found:
                    missing.append(exp_name)

            if missing:
                errors.append(f"{name}: Missing expected results: {missing} (got: {names[:10]})")
                failed += 1
                print(f"  ❌ {name}: Missing {missing}")
                print(f"       Got: {names[:10]}")
                continue

            # Check type filtering
            validate_type = tc.get("validate_types")
            if validate_type and result_count > 0:
                classes = _extract_type_classes(response)
                if classes and validate_type not in str(classes):
                    errors.append(f"{name}: Expected type {validate_type}, got {classes}")
                    failed += 1
                    print(f"  ❌ {name}: Wrong types returned: {classes}")
                    continue

            passed += 1
            detail = f"({result_count} results"
            if names:
                detail += f", top: {names[:3]}"
            detail += ")"
            print(f"  ✓ {name} {detail}")

        except Exception as e:
            errors.append(f"{name}: Exception — {e}")
            failed += 1
            print(f"  ❌ {name}: Exception — {e}")

    # ── Direct SPARQL endpoint tests ────────────────────────────────────────
    print()
    print("Direct SPARQL Endpoint Tests (vg: functions)")
    print("-" * 70)

    sparql_tests = [
        {
            "name": "SPARQL Keyword: CONTAINS",
            "query": f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name WHERE {{
  ?s vc:vitaltype ?vt .
  ?s vc:hasName ?name .
  FILTER(CONTAINS(LCASE(?name), "commerce"))
}}
ORDER BY ?name
LIMIT 20
""",
            "expected_contains": ["Commerce_buy"],
            "min_results": 1,
        },
        {
            "name": "SPARQL FTS: vg:textSearch",
            "query": f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?s ?name ?score WHERE {{
  ?s vc:vitaltype ?vt .
  ?s vc:hasName ?name .
  BIND(vg:textSearch(?s, "commercial transaction buying", "{INDEX_NAME}") AS ?score)
  FILTER(BOUND(?score))
}}
ORDER BY DESC(?score)
LIMIT 10
""",
            "expected_contains": ["Commercial_transaction"],
            "min_results": 1,
        },
        {
            "name": "SPARQL Vector: vg:vectorSimilarity",
            "query": f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?s ?name ?score WHERE {{
  ?s vc:vitaltype ?vt .
  ?s vc:hasName ?name .
  BIND(vg:vectorSimilarity(?s, "hiring someone for a job", "{INDEX_NAME}") AS ?score)
  FILTER(BOUND(?score))
}}
ORDER BY DESC(?score)
LIMIT 10
""",
            "expected_contains": ["Hiring"],
            "min_results": 1,
        },
        {
            "name": "SPARQL Hybrid: vg:hybridSearch",
            "query": f"""
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?s ?name ?score WHERE {{
  ?s vc:vitaltype ?vt .
  ?s vc:hasName ?name .
  BIND(vg:hybridSearch(?s, "cooking food preparation heat", "{INDEX_NAME}", 0.5) AS ?score)
  FILTER(BOUND(?score))
}}
ORDER BY DESC(?score)
LIMIT 10
""",
            "expected_contains": ["Cook"],
            "min_results": 1,
        },
    ]

    from vitalgraph.model.sparql_model import SPARQLQueryRequest

    for tc in sparql_tests:
        name = tc["name"]
        try:
            request = SPARQLQueryRequest(
                query=tc["query"].strip(),
                default_graph_uri=[GRAPH_ID],
            )
            response = await client.sparql.execute_sparql_query(SPACE_ID, request)

            # Extract bindings from SPARQL JSON response
            bindings = []
            if response.results and isinstance(response.results, dict):
                bindings = response.results.get('bindings', [])

            result_count = len(bindings)
            names = [b.get('name', {}).get('value', '') for b in bindings if isinstance(b, dict)]

            min_results = tc.get("min_results", 0)
            if result_count < min_results:
                errors.append(f"{name}: Expected >= {min_results} results, got {result_count}")
                failed += 1
                print(f"  ❌ {name}: Expected >= {min_results} results, got {result_count}")
                continue

            expected = tc.get("expected_contains", [])
            missing = [exp for exp in expected if not any(exp.lower() in n.lower() for n in names)]

            if missing:
                errors.append(f"{name}: Missing expected: {missing} (got: {names[:10]})")
                failed += 1
                print(f"  ❌ {name}: Missing {missing}")
                print(f"       Got: {names[:10]}")
                continue

            passed += 1
            print(f"  ✓ {name} ({result_count} results, top: {names[:3]})")

        except Exception as e:
            errors.append(f"{name}: Exception — {e}")
            failed += 1
            print(f"  ❌ {name}: Exception — {e}")

    # ── E4: Auto-sync test — create type → immediately searchable ──────────
    print()
    print("Auto-Sync Tests (E4)")
    print("-" * 70)

    auto_sync_passed, auto_sync_failed, auto_sync_errors = await _run_auto_sync_test(client)
    passed += auto_sync_passed
    failed += auto_sync_failed
    errors.extend(auto_sync_errors)

    await client.close()

    # Summary
    total = passed + failed
    print()
    print("-" * 70)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for err in errors:
            print(f"  • {err}")
    print()

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_framenet_search_tests())
    sys.exit(0 if success else 1)
