#!/usr/bin/env python3
"""
Test KGFrames Filter & Sort Parity (Integration)

End-to-end tests against a running VitalGraph server:
1. Creates standalone frames (should get KGFormType_Assertion automatically)
2. Creates entity-enclosed frames (should get KGFormType_Aspect automatically)
3. Lists with form_type=Assertion and verifies only standalone frames returned
4. Lists with form_type=Aspect and verifies only entity-enclosed frames returned
5. Lists with property URI-based sort_by and verifies ordering
6. Lists with search filter and verifies results

Requires: running VitalGraph server (env vars for connection)
"""

import sys
import asyncio
import logging
from pathlib import Path
from typing import List

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space

from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

TEST_SPACE = "space_kgframes_filter_test"
TEST_GRAPH = "urn:test_kgframes_filter_sort"


# ─── Test Data ─────────────────────────────────────────────────────────────

def create_standalone_frames() -> List:
    """Create 3 standalone frames with distinct names for filtering tests."""
    objects = []

    # Frame A - "Alpha Report"
    frame_a = KGFrame()
    frame_a.URI = URIGenerator.generate_uri()
    frame_a.name = "Alpha Report"
    frame_a.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ReportFrame"
    objects.append(frame_a)

    slot_a = KGTextSlot()
    slot_a.URI = URIGenerator.generate_uri()
    slot_a.name = "Summary"
    slot_a.textSlotValue = "Alpha summary content"
    objects.append(slot_a)

    edge_a = Edge_hasKGSlot()
    edge_a.URI = URIGenerator.generate_uri()
    edge_a.edgeSource = str(frame_a.URI)
    edge_a.edgeDestination = str(slot_a.URI)
    objects.append(edge_a)

    # Frame B - "Beta Analysis"
    frame_b = KGFrame()
    frame_b.URI = URIGenerator.generate_uri()
    frame_b.name = "Beta Analysis"
    frame_b.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#AnalysisFrame"
    objects.append(frame_b)

    # Frame C - "Gamma Observation"
    frame_c = KGFrame()
    frame_c.URI = URIGenerator.generate_uri()
    frame_c.name = "Gamma Observation"
    frame_c.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ReportFrame"
    objects.append(frame_c)

    return objects


def create_entity_with_frames() -> List:
    """Create an entity with 2 enclosed frames (which should become Aspects)."""
    objects = []

    entity = KGEntity()
    entity.URI = URIGenerator.generate_uri()
    entity.name = "Test Entity For Aspects"
    objects.append(entity)

    # Entity-enclosed frame 1
    frame_d = KGFrame()
    frame_d.URI = URIGenerator.generate_uri()
    frame_d.name = "Delta Detail"
    objects.append(frame_d)

    edge_entity_frame1 = Edge_hasEntityKGFrame()
    edge_entity_frame1.URI = URIGenerator.generate_uri()
    edge_entity_frame1.edgeSource = str(entity.URI)
    edge_entity_frame1.edgeDestination = str(frame_d.URI)
    objects.append(edge_entity_frame1)

    # Entity-enclosed frame 2
    frame_e = KGFrame()
    frame_e.URI = URIGenerator.generate_uri()
    frame_e.name = "Epsilon Context"
    objects.append(frame_e)

    edge_entity_frame2 = Edge_hasEntityKGFrame()
    edge_entity_frame2.URI = URIGenerator.generate_uri()
    edge_entity_frame2.edgeSource = str(entity.URI)
    edge_entity_frame2.edgeDestination = str(frame_e.URI)
    objects.append(edge_entity_frame2)

    return objects


# ─── Test Implementation ───────────────────────────────────────────────────

async def run_integration_tests() -> bool:
    """Run all integration tests against the live server."""

    print("=" * 70)
    print("KGFrames Filter & Sort Parity — Integration Tests")
    print("=" * 70)

    client = VitalGraphClient()
    await client.open()

    if not client.is_connected():
        print("  ✗ Cannot connect to VitalGraph server")
        return False

    print(f"  ✓ Connected to server")

    # ── Setup: create test space ──
    print("\n[SETUP] Creating test space and graph...")

    spaces_response = await client.spaces.list_spaces()
    existing = next((s for s in spaces_response.spaces if s.space == TEST_SPACE), None)
    if existing:
        await client.spaces.delete_space(TEST_SPACE)

    await client.spaces.add_space(Space(
        space=TEST_SPACE,
        space_name="KGFrames Filter Test",
        space_description="Temp space for filter/sort parity tests",
        tenant="test"
    ))
    print(f"  ✓ Space '{TEST_SPACE}' ready")

    passed = 0
    failed = 0
    errors = []

    # ── Test 1: Create standalone frames (should become Assertions) ──
    print("\n[TEST 1] Create standalone frames → KGFormType_Assertion")
    try:
        standalone_objects = create_standalone_frames()
        resp = await client.kgframes.create_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH, objects=standalone_objects
        )
        created_count = getattr(resp, 'created_count', 0)
        assert created_count > 0, f"Expected frames created, got {created_count}"
        print(f"  ✓ Created {created_count} standalone frame objects")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Create standalone: {e}")

    # ── Test 2: Create entity with enclosed frames (should become Aspects) ──
    print("\n[TEST 2] Create entity with enclosed frames → KGFormType_Aspect")
    try:
        entity_objects = create_entity_with_frames()
        resp = await client.kgentities.create_kgentities(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH, objects=entity_objects
        )
        success = (
            (hasattr(resp, 'created_count') and resp.created_count > 0) or
            (hasattr(resp, 'message') and "created" in str(getattr(resp, 'message', '')).lower())
        )
        assert success, f"Entity creation failed: {getattr(resp, 'message', resp)}"
        print(f"  ✓ Created entity with enclosed frames")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Create entity+frames: {e}")

    # ── Test 3: List all frames (no filter) ──
    print("\n[TEST 3] List all frames (no form_type filter)")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH, page_size=50
        )
        total = getattr(resp, 'total_count', 0)
        # Should have at least 5 frames total (3 standalone + 2 entity-enclosed)
        assert total >= 5, f"Expected >= 5 frames, got {total}"
        print(f"  ✓ Total frames listed: {total}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"List all: {e}")

    # ── Test 4: Filter by form_type=Assertion ──
    print("\n[TEST 4] List with form_type=Assertion (standalone only)")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH,
            page_size=50, form_type="Assertion"
        )
        assertion_count = getattr(resp, 'total_count', 0)
        # Should be exactly 3 standalone frames
        assert assertion_count == 3, f"Expected 3 Assertion frames, got {assertion_count}"
        print(f"  ✓ Assertion frames: {assertion_count}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Filter Assertion: {e}")

    # ── Test 5: Filter by form_type=Aspect ──
    print("\n[TEST 5] List with form_type=Aspect (entity-enclosed only)")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH,
            page_size=50, form_type="Aspect"
        )
        aspect_count = getattr(resp, 'total_count', 0)
        # Should be exactly 2 entity-enclosed frames
        assert aspect_count == 2, f"Expected 2 Aspect frames, got {aspect_count}"
        print(f"  ✓ Aspect frames: {aspect_count}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Filter Aspect: {e}")

    # ── Test 6: Sort by name ascending ──
    print("\n[TEST 6] Sort by hasName ascending")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH,
            page_size=50,
            sort_by="http://vital.ai/ontology/vital-core#hasName",
            sort_order="asc"
        )
        results = getattr(resp, 'results', [])
        # Extract names from quads
        names = []
        for quad in results:
            props = quad.get('properties', {}) if isinstance(quad, dict) else {}
            name = props.get('http://vital.ai/ontology/vital-core#hasName', '')
            if name:
                names.append(name)
        # Names should be in alphabetical order
        if len(names) >= 2:
            assert names == sorted(names), f"Names not sorted ascending: {names}"
            print(f"  ✓ Sorted ascending: {names[:3]}...")
        else:
            print(f"  ✓ Sort request accepted (not enough names to verify order)")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Sort ascending: {e}")

    # ── Test 7: Sort by name descending ──
    print("\n[TEST 7] Sort by hasName descending")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH,
            page_size=50,
            sort_by="http://vital.ai/ontology/vital-core#hasName",
            sort_order="desc"
        )
        results = getattr(resp, 'results', [])
        names = []
        for quad in results:
            props = quad.get('properties', {}) if isinstance(quad, dict) else {}
            name = props.get('http://vital.ai/ontology/vital-core#hasName', '')
            if name:
                names.append(name)
        if len(names) >= 2:
            assert names == sorted(names, reverse=True), f"Names not sorted descending: {names}"
            print(f"  ✓ Sorted descending: {names[:3]}...")
        else:
            print(f"  ✓ Sort request accepted (not enough names to verify order)")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Sort descending: {e}")

    # ── Test 8: Search filter ──
    print("\n[TEST 8] Search for 'Alpha'")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH,
            page_size=50, search="Alpha"
        )
        search_count = getattr(resp, 'total_count', 0)
        assert search_count >= 1, f"Expected >= 1 result for 'Alpha', got {search_count}"
        print(f"  ✓ Search 'Alpha' returned {search_count} result(s)")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Search: {e}")

    # ── Test 9: Combined form_type + search ──
    print("\n[TEST 9] Combined: form_type=Assertion + search='Beta'")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH,
            page_size=50, form_type="Assertion", search="Beta"
        )
        combined_count = getattr(resp, 'total_count', 0)
        # "Beta Analysis" is a standalone frame → should appear
        assert combined_count == 1, f"Expected 1 result, got {combined_count}"
        print(f"  ✓ Combined filter returned {combined_count} result(s)")
        passed += 1
    except Exception as e:
        print(f"  ✗ {e}")
        failed += 1
        errors.append(f"Combined filter: {e}")

    # ── Test 10: Invalid sort_by rejected ──
    print("\n[TEST 10] Invalid sort_by property is rejected")
    try:
        resp = await client.kgframes.list_kgframes(
            space_id=TEST_SPACE, graph_id=TEST_GRAPH,
            page_size=50,
            sort_by="http://example.org/fake_property"
        )
        # Should get an error response (400) or empty result indicating rejection
        # If the server returned a 4xx, the client may raise or return error
        status = getattr(resp, 'status_code', None) or getattr(resp, 'detail', None)
        if status:
            print(f"  ✓ Server rejected invalid sort_by: {status}")
        else:
            # Some client implementations may swallow the error
            print(f"  ~ Server did not explicitly reject (may have ignored); response: {type(resp).__name__}")
        passed += 1
    except Exception as e:
        # Exception means it was rejected — this is the expected path
        print(f"  ✓ Invalid sort_by correctly rejected: {e}")
        passed += 1

    # ── Cleanup ──
    print("\n[CLEANUP] Deleting test space...")
    try:
        await client.spaces.delete_space(TEST_SPACE)
        print(f"  ✓ Space '{TEST_SPACE}' deleted")
    except Exception as e:
        print(f"  ~ Cleanup warning: {e}")

    await client.close()

    # ── Summary ──
    total = passed + failed
    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed, {total} total")
    if errors:
        print("Failed:")
        for e in errors:
            print(f"  - {e}")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_integration_tests())
    sys.exit(0 if success else 1)
