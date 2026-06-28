"""
Test script for GET /api/graphs/kgtypes/relationships endpoint.

Tests the relationships endpoint directly via SparqlSQLSpaceImpl (no REST server needed).
Uses the FrameNet test space (framenet_kgtypes_test).
"""

import asyncio
import sys
import time
import logging

logging.basicConfig(level=logging.WARNING)

# ── Configuration ─────────────────────────────────────────────────────────

PG_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "sparql_sql_graph",
    "user": "postgres",
    "password": "password",
}
SIDECAR_URL = "http://localhost:7070"

SPACE_ID = "framenet_kgtypes_test"
GRAPH_URI = "urn:vitalgraph:framenet_kgtypes_test:kg_types"

# Test URIs from the FrameNet dataset
TEST_INTENTIONALLY_ACT = "urn:vitalgraph:framenet:frame-type:Intentionally_act"
TEST_COMMERCE_BUY = "urn:vitalgraph:framenet:frame-type:Commerce_buy"
TEST_SLOT_AGENT = "urn:vitalgraph:framenet:slot-type:Agent"


async def main():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
    from vitalgraph.kg_impl.kgtypes_read_impl import KGTypesReadProcessor

    space_impl = SparqlSQLSpaceImpl(
        postgresql_config=PG_CONFIG,
        sidecar_config={"url": SIDECAR_URL},
    )
    connected = await space_impl.connect()
    if not connected:
        print("❌ Failed to connect")
        return False

    backend = space_impl
    adapter = create_backend_adapter(backend)
    processor = KGTypesReadProcessor()

    passed = 0
    failed = 0

    # ── Test 1: Intentionally_act (should have ~45 outgoing children + 1 parent) ──
    print("\n" + "=" * 70)
    print("  T1: Relationships for Intentionally_act")
    print("=" * 70)
    t0 = time.perf_counter()
    result = await processor.get_type_relationships(
        backend=adapter, space_id=SPACE_ID, graph_id=GRAPH_URI,
        type_uri=TEST_INTENTIONALLY_ACT,
    )
    elapsed = time.perf_counter() - t0
    n_edges = len(result['edges'])
    n_connected = len(result['connected_types'])
    print(f"  Source: {result['source_type']['name']} ({result['source_type']['vitaltype']})")
    print(f"  Edges: {n_edges}, Connected types: {n_connected}, Time: {elapsed:.3f}s")

    outgoing = [e for e in result['edges'] if e['direction'] == 'outgoing']
    incoming = [e for e in result['edges'] if e['direction'] == 'incoming']
    print(f"  Outgoing: {len(outgoing)}, Incoming: {len(incoming)}")

    if n_edges >= 2 and result['source_type']['name'] == 'Intentionally_act':
        print("  ✅ PASSED")
        passed += 1
    else:
        print("  ❌ FAILED")
        failed += 1

    # Show first 5 connected types
    for ct in result['connected_types'][:5]:
        print(f"    - {ct['name']} ({ct['vitaltype'].split('#')[-1]})")
    if n_connected > 5:
        print(f"    ... and {n_connected - 5} more")

    # ── Test 2: Commerce_buy (should have parent via incoming edge) ──
    print("\n" + "=" * 70)
    print("  T2: Relationships for Commerce_buy")
    print("=" * 70)
    t0 = time.perf_counter()
    result2 = await processor.get_type_relationships(
        backend=adapter, space_id=SPACE_ID, graph_id=GRAPH_URI,
        type_uri=TEST_COMMERCE_BUY,
    )
    elapsed2 = time.perf_counter() - t0
    n_edges2 = len(result2['edges'])
    print(f"  Source: {result2['source_type']['name']}")
    print(f"  Edges: {n_edges2}, Time: {elapsed2:.3f}s")
    incoming2 = [e for e in result2['edges'] if e['direction'] == 'incoming']
    outgoing2 = [e for e in result2['edges'] if e['direction'] == 'outgoing']
    print(f"  Outgoing: {len(outgoing2)}, Incoming: {len(incoming2)}")

    if n_edges2 >= 1 and result2['source_type']['name'] == 'Commerce_buy':
        print("  ✅ PASSED")
        passed += 1
    else:
        print("  ❌ FAILED")
        failed += 1

    for ct in result2['connected_types']:
        print(f"    - {ct['name']} [{ct['uri']}]")

    # ── Test 3: Slot type (should have no type-level edges) ──
    print("\n" + "=" * 70)
    print("  T3: Relationships for slot type Agent (expect 0 edges)")
    print("=" * 70)
    t0 = time.perf_counter()
    result3 = await processor.get_type_relationships(
        backend=adapter, space_id=SPACE_ID, graph_id=GRAPH_URI,
        type_uri=TEST_SLOT_AGENT,
    )
    elapsed3 = time.perf_counter() - t0
    n_edges3 = len(result3['edges'])
    print(f"  Source: {result3['source_type']['name']}")
    print(f"  Edges: {n_edges3}, Time: {elapsed3:.3f}s")

    if n_edges3 == 0 and result3['source_type']['name'] == 'Agent':
        print("  ✅ PASSED")
        passed += 1
    else:
        print("  ❌ FAILED")
        failed += 1

    # ── Summary ──
    total = passed + failed
    print(f"\n{'=' * 70}")
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 70}")

    await space_impl.disconnect()
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
