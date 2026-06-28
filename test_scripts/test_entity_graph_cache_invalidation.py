"""
Regression tests for EntityGraphCache.collect_invalidation_targets().

Covers:
  - Subject is a cached entity → entity invalidated
  - hasKGGraphURI in the SPARQL → parent entity invalidated
  - Sub-object modified (hasKGGraphURI NOT in SPARQL) → parent entity found
    via the subject→entity index built from all cached quad subjects

Also verifies the URINode.value fix (was .uri — a latent bug) and the
subject index lifecycle (cleanup on remove / evict).
"""

import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vitalgraph.cache.entity_graph_cache import EntityGraphCache
from vitalgraph.db.jena_sparql.jena_types import (
    URINode, VarNode, LiteralNode, QuadPattern,
    UpdateModify, UpdateDataInsert,
)
from vitalgraph.model.quad_model import Quad


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPACE = "test-space"
GRAPH = "http://example.com/graph/g1"
ENTITY_URI = "http://example.com/entity/e1"
FRAME_URI = "http://example.com/frame/f1"
SLOT_URI = "http://example.com/slot/s1"
MOD_TIME_URI = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
HAS_KG_GRAPH_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"


def _make_entity_graph_quads() -> list:
    """Build a small entity graph as Quad models (like endpoint caches)."""
    return [
        Quad(s=f"<{ENTITY_URI}>", p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>",
             o="<http://vital.ai/ontology/haley-ai-kg#KGEntity>", g=f"<{GRAPH}>"),
        Quad(s=f"<{ENTITY_URI}>", p="<http://vital.ai/ontology/vital-core#hasName>",
             o='"Test Entity"', g=f"<{GRAPH}>"),
        Quad(s=f"<{FRAME_URI}>", p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>",
             o="<http://vital.ai/ontology/haley-ai-kg#KGFrame>", g=f"<{GRAPH}>"),
        Quad(s=f"<{FRAME_URI}>", p=f"<{HAS_KG_GRAPH_URI}>",
             o=f"<{ENTITY_URI}>", g=f"<{GRAPH}>"),
        Quad(s=f"<{SLOT_URI}>", p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>",
             o="<http://vital.ai/ontology/haley-ai-kg#KGSlot>", g=f"<{GRAPH}>"),
        Quad(s=f"<{SLOT_URI}>", p=f"<{HAS_KG_GRAPH_URI}>",
             o=f"<{ENTITY_URI}>", g=f"<{GRAPH}>"),
    ]


def _quad(graph, subject, predicate, obj):
    """Build a QuadPattern from bare URI strings (or RDFNode instances)."""
    def _node(v):
        if isinstance(v, (URINode, VarNode, LiteralNode)):
            return v
        return URINode(v) if v else None
    return QuadPattern(graph=_node(graph), subject=_node(subject),
                       predicate=_node(predicate), object=_node(obj))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rule1_entity_property_change():
    """Rule 1: entity property change → entity invalidated."""
    cache = EntityGraphCache()
    cache.put(SPACE, GRAPH, ENTITY_URI, _make_entity_graph_quads())

    # Simulate a SPARQL UPDATE that changes a property on the entity itself:
    #   DELETE { GRAPH <g> { <entity> <modTime> ?old . } }
    #   INSERT { GRAPH <g> { <entity> <modTime> "2026-04-28T..." . } }
    op = UpdateModify(
        delete_quads=[_quad(GRAPH, ENTITY_URI, MOD_TIME_URI, VarNode("old"))],
        insert_quads=[_quad(GRAPH, ENTITY_URI, MOD_TIME_URI,
                            LiteralNode("2026-04-28T12:00:00"))],
    )
    targets = cache.collect_invalidation_targets([op], SPACE)
    assert (GRAPH, ENTITY_URI) in targets, f"Rule 1 missed entity: {targets}"
    print("  PASS  Rule 1: entity property change → entity invalidated")
    return True


def test_rule2_hasKGGraphURI_in_diff():
    """Rule 2: hasKGGraphURI predicate in diff → entity invalidated."""
    cache = EntityGraphCache()
    cache.put(SPACE, GRAPH, ENTITY_URI, _make_entity_graph_quads())

    # Simulate inserting a new frame with its hasKGGraphURI triple:
    new_frame = "http://example.com/frame/f2"
    op = UpdateDataInsert(quads=[
        _quad(GRAPH, new_frame, HAS_KG_GRAPH_URI, ENTITY_URI),
    ])
    targets = cache.collect_invalidation_targets([op], SPACE)
    assert (GRAPH, ENTITY_URI) in targets, f"Rule 2 missed entity: {targets}"
    print("  PASS  Rule 2: hasKGGraphURI in diff → entity invalidated")
    return True



def test_slot_change_no_kggraphuri_in_sparql():
    """Slot property change (hasKGGraphURI NOT in SPARQL) → parent entity invalidated via subject index."""
    cache = EntityGraphCache()
    cache.put(SPACE, GRAPH, ENTITY_URI, _make_entity_graph_quads())

    # SPARQL UPDATE changes a slot value — hasKGGraphURI is NOT in the SPARQL.
    slot_prop = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotValue"
    op = UpdateModify(
        delete_quads=[_quad(GRAPH, SLOT_URI, slot_prop, LiteralNode("old value"))],
        insert_quads=[_quad(GRAPH, SLOT_URI, slot_prop, LiteralNode("new value"))],
    )
    targets = cache.collect_invalidation_targets([op], SPACE)
    assert (GRAPH, ENTITY_URI) in targets, (
        f"Subject index missed parent entity for slot change: {targets}"
    )
    print("  PASS  Slot change (no hasKGGraphURI in SPARQL) → parent entity invalidated via subject index")
    return True


def test_frame_change_no_kggraphuri_in_sparql():
    """Frame property change (hasKGGraphURI NOT in SPARQL) → parent entity invalidated via subject index."""
    cache = EntityGraphCache()
    cache.put(SPACE, GRAPH, ENTITY_URI, _make_entity_graph_quads())

    frame_prop = "http://vital.ai/ontology/vital-core#hasName"
    op = UpdateModify(
        delete_quads=[_quad(GRAPH, FRAME_URI, frame_prop, LiteralNode("old"))],
        insert_quads=[_quad(GRAPH, FRAME_URI, frame_prop, LiteralNode("new"))],
    )
    targets = cache.collect_invalidation_targets([op], SPACE)
    assert (GRAPH, ENTITY_URI) in targets, (
        f"Subject index missed parent entity for frame change: {targets}"
    )
    print("  PASS  Frame change (no hasKGGraphURI in SPARQL) → parent entity invalidated via subject index")
    return True


def test_index_cleanup_on_invalidate():
    """Subject index is cleaned up when a cache entry is invalidated."""
    cache = EntityGraphCache()
    cache.put(SPACE, GRAPH, ENTITY_URI, _make_entity_graph_quads())

    # Verify index is populated
    assert (SPACE, SLOT_URI) in cache._sub_to_entity, "Index not populated for slot"
    assert (SPACE, FRAME_URI) in cache._sub_to_entity, "Index not populated for frame"
    assert (SPACE, ENTITY_URI) in cache._sub_to_entity, "Index not populated for entity itself"

    # Invalidate → should clean up index
    cache.invalidate(SPACE, GRAPH, ENTITY_URI)
    assert (SPACE, SLOT_URI) not in cache._sub_to_entity, "Index not cleaned for slot"
    assert (SPACE, FRAME_URI) not in cache._sub_to_entity, "Index not cleaned for frame"
    assert (SPACE, ENTITY_URI) not in cache._sub_to_entity, "Index not cleaned for entity"

    # Now a slot change should produce no targets
    slot_prop = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotValue"
    op = UpdateModify(
        delete_quads=[_quad(GRAPH, SLOT_URI, slot_prop, LiteralNode("old"))],
        insert_quads=[_quad(GRAPH, SLOT_URI, slot_prop, LiteralNode("new"))],
    )
    targets = cache.collect_invalidation_targets([op], SPACE)
    assert len(targets) == 0, f"Expected no targets after invalidation: {targets}"
    print("  PASS  Subject index cleaned up on invalidate")
    return True


def test_index_cleanup_on_evict():
    """Subject index is cleaned up when a cache entry is evicted by LRU."""
    cache = EntityGraphCache(max_entries=1)
    cache.put(SPACE, GRAPH, ENTITY_URI, _make_entity_graph_quads())

    assert (SPACE, FRAME_URI) in cache._sub_to_entity

    # Put a second entity → evicts the first
    entity2 = "http://example.com/entity/e2"
    cache.put(SPACE, GRAPH, entity2, [
        Quad(s=f"<{entity2}>", p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>",
             o="<http://vital.ai/ontology/haley-ai-kg#KGEntity>", g=f"<{GRAPH}>"),
    ])

    assert (SPACE, FRAME_URI) not in cache._sub_to_entity, "Index not cleaned on evict"
    assert (SPACE, SLOT_URI) not in cache._sub_to_entity, "Index not cleaned on evict"
    print("  PASS  Subject index cleaned up on LRU eviction")
    return True


def test_uri_node_value_attribute():
    """Verify that URINode.value (not .uri) is used for URI extraction."""
    cache = EntityGraphCache()
    cache.put(SPACE, GRAPH, ENTITY_URI, _make_entity_graph_quads())

    # URINode has .value, not .uri — the old code used getattr(node, 'uri')
    # which silently returned None, making all rules dead code.
    node = URINode(ENTITY_URI)
    assert hasattr(node, 'value'), "URINode should have 'value' attribute"
    assert not hasattr(node, 'uri'), "URINode should NOT have 'uri' attribute"

    # Rules should still work because we now use isinstance + .value
    op = UpdateModify(
        delete_quads=[_quad(GRAPH, ENTITY_URI, MOD_TIME_URI, VarNode("old"))],
        insert_quads=[_quad(GRAPH, ENTITY_URI, MOD_TIME_URI,
                            LiteralNode("2026-04-28T12:00:00"))],
    )
    targets = cache.collect_invalidation_targets([op], SPACE)
    assert len(targets) > 0, "URINode.value fix failed — no targets found"
    print("  PASS  URINode.value attribute fix verified")
    return True


def test_uncached_subject_no_false_positive():
    """Subject URI not in cache and not a sub-object → no targets."""
    cache = EntityGraphCache()
    # Cache is empty — no entities, no reverse index

    unknown = "http://example.com/entity/unknown"
    op = UpdateModify(
        delete_quads=[_quad(GRAPH, unknown, MOD_TIME_URI, VarNode("old"))],
        insert_quads=[_quad(GRAPH, unknown, MOD_TIME_URI,
                            LiteralNode("2026-04-28T12:00:00"))],
    )
    targets = cache.collect_invalidation_targets([op], SPACE)
    assert len(targets) == 0, f"Expected no targets for unknown URI: {targets}"
    print("  PASS  Unknown subject → no false positive")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    tests = [
        ("Entity property change", test_rule1_entity_property_change),
        ("hasKGGraphURI in SPARQL", test_rule2_hasKGGraphURI_in_diff),
        ("Slot change via subject index", test_slot_change_no_kggraphuri_in_sparql),
        ("Frame change via subject index", test_frame_change_no_kggraphuri_in_sparql),
        ("Index cleanup on invalidate", test_index_cleanup_on_invalidate),
        ("Index cleanup on LRU evict", test_index_cleanup_on_evict),
        ("URINode.value attribute fix", test_uri_node_value_attribute),
        ("No false positives for unknown URIs", test_uncached_subject_no_false_positive),
    ]

    print("\n=== EntityGraphCache Invalidation Regression Tests ===\n")
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            if fn():
                passed += 1
            else:
                failed += 1
                print(f"  FAIL  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")

    print(f"\n--- Results: {passed}/{passed + failed} passed ---\n")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
