#!/usr/bin/env python3
"""
Test Phase 6: Verify SPARQL query generation for relation queries with frame/slot filtering.

This script tests that the connection query builder correctly generates SPARQL queries
with frame and slot criteria for source and destination entities.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.sparql.kg_connection_query_builder import KGConnectionQueryBuilder
from vitalgraph.model.kgqueries_model import KGQueryCriteria
from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria


def test_basic_relation_query():
    """Test basic relation query without frame filtering (baseline)."""
    print("\n" + "=" * 80)
    print("Test 1: Basic Relation Query (No Frame Filtering)")
    print("=" * 80)
    
    builder = KGConnectionQueryBuilder()
    criteria = KGQueryCriteria(
        query_type="relation",
        relation_type_uris=["http://vital.ai/test/kgtype/MakesProductRelation"],
        direction="outgoing"
    )
    
    query = builder.build_relation_query(criteria, "urn:test_graph")
    print(query)
    
    # Verify basic patterns exist
    assert "?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation>" in query
    assert "?relation_edge vital:hasEdgeSource ?source_entity" in query
    assert "?relation_edge vital:hasEdgeDestination ?destination_entity" in query
    assert "VALUES ?relation_type { <http://vital.ai/test/kgtype/MakesProductRelation> }" in query
    
    print("\n✅ Basic query generation works")


def test_relation_with_source_frame_type():
    """Test relation query with source entity frame type filter."""
    print("\n" + "=" * 80)
    print("Test 2: Relation Query with Source Frame Type Filter")
    print("=" * 80)
    
    builder = KGConnectionQueryBuilder()
    criteria = KGQueryCriteria(
        query_type="relation",
        relation_type_uris=["http://vital.ai/test/kgtype/MakesProductRelation"],
        source_frame_criteria=[
            FrameCriteria(
                frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame"
            )
        ],
        direction="outgoing"
    )
    
    query = builder.build_relation_query(criteria, "urn:test_graph")
    print(query)
    
    # Verify frame patterns exist
    assert "?source_frame_edge_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame>" in query
    assert "?source_frame_edge_0 vital:hasEdgeSource ?source_entity" in query
    assert "?source_frame_edge_0 vital:hasEdgeDestination ?source_frame_0" in query
    assert "?source_frame_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame>" in query
    
    print("\n✅ Source frame type filtering works")


def test_relation_with_source_slot_value():
    """Test relation query with source entity slot value filter."""
    print("\n" + "=" * 80)
    print("Test 3: Relation Query with Source Slot Value Filter")
    print("=" * 80)
    
    builder = KGConnectionQueryBuilder()
    criteria = KGQueryCriteria(
        query_type="relation",
        relation_type_uris=["http://vital.ai/test/kgtype/MakesProductRelation"],
        source_frame_criteria=[
            FrameCriteria(
                frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
                slot_criteria=[
                    SlotCriteria(
                        slot_type="http://vital.ai/test/slot/revenue",
                        value=1000000,
                        comparator="gt"
                    )
                ]
            )
        ],
        direction="outgoing"
    )
    
    query = builder.build_relation_query(criteria, "urn:test_graph")
    print(query)
    
    # Verify slot patterns exist
    assert "?source_frame_0 haley:frameGraphURI ?source_frame_graph_0" in query
    assert "?source_slot_0_0 haley:hasFrameGraphURI ?source_frame_graph_0" in query
    assert "?source_slot_0_0 haley:hasKGSlotType <http://vital.ai/test/slot/revenue>" in query
    assert "?source_slot_0_0 haley:hasIntegerSlotValue ?source_slot_value_0_0" in query
    assert "FILTER(?source_slot_value_0_0 > 1000000)" in query
    
    print("\n✅ Source slot value filtering works")


def test_relation_with_both_source_and_dest_filters():
    """Test relation query with both source and destination filters."""
    print("\n" + "=" * 80)
    print("Test 4: Relation Query with Both Source and Destination Filters")
    print("=" * 80)
    
    builder = KGConnectionQueryBuilder()
    criteria = KGQueryCriteria(
        query_type="relation",
        relation_type_uris=["http://vital.ai/test/kgtype/CompetitorOfRelation"],
        source_frame_criteria=[
            FrameCriteria(
                slot_criteria=[
                    SlotCriteria(
                        slot_type="http://vital.ai/test/slot/revenue",
                        value=1000000,
                        comparator="gt"
                    )
                ]
            )
        ],
        destination_frame_criteria=[
            FrameCriteria(
                slot_criteria=[
                    SlotCriteria(
                        slot_type="http://vital.ai/test/slot/revenue",
                        value=1000000,
                        comparator="gt"
                    )
                ]
            )
        ],
        direction="outgoing"
    )
    
    query = builder.build_relation_query(criteria, "urn:test_graph")
    print(query)
    
    # Verify both source and destination patterns exist
    assert "?source_slot_0_0 haley:hasKGSlotType <http://vital.ai/test/slot/revenue>" in query
    assert "?dest_slot_0_0 haley:hasKGSlotType <http://vital.ai/test/slot/revenue>" in query
    assert "FILTER(?source_slot_value_0_0 > 1000000)" in query
    assert "FILTER(?dest_slot_value_0_0 > 1000000)" in query
    
    print("\n✅ Both source and destination filtering works")


def test_relation_with_text_slot_contains():
    """Test relation query with text slot contains filter."""
    print("\n" + "=" * 80)
    print("Test 5: Relation Query with Text Slot Contains Filter")
    print("=" * 80)
    
    builder = KGConnectionQueryBuilder()
    criteria = KGQueryCriteria(
        query_type="relation",
        source_frame_criteria=[
            FrameCriteria(
                slot_criteria=[
                    SlotCriteria(
                        slot_type="http://vital.ai/test/slot/industry",
                        value="Technology",
                        comparator="contains"
                    )
                ]
            )
        ],
        direction="outgoing"
    )
    
    query = builder.build_relation_query(criteria, "urn:test_graph")
    print(query)
    
    # Verify text slot patterns
    assert "?source_slot_0_0 haley:hasTextSlotValue ?source_slot_value_0_0" in query
    assert "FILTER(CONTAINS(LCASE(?source_slot_value_0_0), LCASE('Technology')))" in query
    
    print("\n✅ Text slot contains filtering works")


def main():
    """Run all SPARQL generation tests."""
    print("\n🚀 Phase 6: SPARQL Query Generation Tests")
    print("=" * 80)
    
    try:
        test_basic_relation_query()
        test_relation_with_source_frame_type()
        test_relation_with_source_slot_value()
        test_relation_with_both_source_and_dest_filters()
        test_relation_with_text_slot_contains()
        
        print("\n" + "=" * 80)
        print("🎉 All SPARQL generation tests passed!")
        print("=" * 80)
        return True
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
