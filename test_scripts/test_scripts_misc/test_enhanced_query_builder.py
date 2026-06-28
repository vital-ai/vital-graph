#!/usr/bin/env python3
"""
Test Enhanced Query Builder with Sorting Support

This test verifies that the enhanced KGQueryCriteriaBuilder correctly generates
SPARQL queries with sorting functionality.
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, '/Users/hadfield/Local/vital-git/vital-graph')

from vitalgraph.sparql.kg_query_builder import (
    KGQueryCriteriaBuilder, 
    EntityQueryCriteria, 
    FrameQueryCriteria,
    SortCriteria,
    SlotCriteria
)

def test_basic_entity_query_with_sorting():
    """Test basic entity query with single-level sorting."""
    print("🧪 Testing basic entity query with sorting...")
    
    builder = KGQueryCriteriaBuilder()
    
    # Create sort criteria for sorting by transaction date (descending)
    sort_criteria = [
        SortCriteria(
            sort_type="entity_frame_slot",
            frame_path=["http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrameType"],
            slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionDateSlot",
            sort_order="desc",
            priority=1
        )
    ]
    
    # Create entity query criteria
    criteria = EntityQueryCriteria(
        entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntityType",
        sort_criteria=sort_criteria
    )
    
    # Build query
    query = builder.build_entity_query_sparql(
        criteria=criteria,
        graph_id="test-graph",
        page_size=10,
        offset=0
    )
    
    print("Generated SPARQL Query:")
    print(query)
    print()
    
    # Verify query contains expected elements
    assert "ORDER BY DESC(?sort_val_0)" in query
    assert "hasKGEntityType" in query
    assert "CustomerEntityType" in query
    assert "LIMIT 10" in query
    assert "OFFSET 0" in query
    
    print("✅ Basic entity query with sorting test passed!")
    return True

def test_multi_level_sorting():
    """Test entity query with multi-level sorting."""
    print("🧪 Testing multi-level sorting...")
    
    builder = KGQueryCriteriaBuilder()
    
    # Create multi-level sort criteria
    sort_criteria = [
        SortCriteria(
            sort_type="entity_frame_slot",
            frame_path=["http://vital.ai/ontology/haley-ai-kg#EmploymentInfoFrameType"],
            slot_type="http://vital.ai/ontology/haley-ai-kg#DepartmentSlot",
            sort_order="asc",
            priority=1  # Primary sort
        ),
        SortCriteria(
            sort_type="entity_frame_slot",
            frame_path=["http://vital.ai/ontology/haley-ai-kg#EmploymentInfoFrameType"],
            slot_type="http://vital.ai/ontology/haley-ai-kg#HireDateSlot",
            sort_order="asc",
            priority=2  # Secondary sort
        ),
        SortCriteria(
            sort_type="entity_property",
            property_uri="http://vital.ai/ontology/vital-core#hasName",
            sort_order="asc",
            priority=3  # Tertiary sort
        )
    ]
    
    # Create entity query criteria
    criteria = EntityQueryCriteria(
        entity_type="http://vital.ai/ontology/haley-ai-kg#EmployeeEntityType",
        sort_criteria=sort_criteria
    )
    
    # Build query
    query = builder.build_entity_query_sparql(
        criteria=criteria,
        graph_id="test-graph",
        page_size=50,
        offset=0
    )
    
    print("Generated Multi-Level Sorting SPARQL Query:")
    print(query)
    print()
    
    # Verify query contains expected elements - includes tiebreaker ?entity
    assert "ASC(?sort_val_0)" in query
    assert "ASC(?sort_val_1)" in query  
    assert "ASC(?sort_val_2)" in query
    assert "?sort_val_0" in query
    assert "?sort_val_1" in query  
    assert "?sort_val_2" in query
    assert "LIMIT 50" in query
    
    print("✅ Multi-level sorting test passed!")
    return True

def test_frame_query_with_sorting():
    """Test frame query with sorting."""
    print("🧪 Testing frame query with sorting...")
    
    builder = KGQueryCriteriaBuilder()
    
    # Create sort criteria for sorting frames by slot value
    sort_criteria = [
        SortCriteria(
            sort_type="frame_slot",
            slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionAmountSlot",
            sort_order="desc",
            priority=1
        )
    ]
    
    # Create frame query criteria with filtering and sorting
    criteria = FrameQueryCriteria(
        frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrameType",
        entity_type="http://vital.ai/ontology/haley-ai-kg#AccountEntityType",
        sort_criteria=sort_criteria
    )
    
    # Build query
    query = builder.build_frame_query_sparql(
        criteria=criteria,
        graph_id="test-graph",
        page_size=20,
        offset=10
    )
    
    print("Generated Frame Query with Sorting:")
    print(query)
    print()
    
    # Verify query contains expected elements
    assert "ORDER BY DESC(?sort_val_0)" in query
    assert "?frame rdf:type haley:KGFrame" in query
    assert "TransactionAmountSlot" in query
    assert "LIMIT 20" in query
    assert "OFFSET 10" in query
    
    print("✅ Frame query with sorting test passed!")
    return True

def test_complex_criteria_with_sorting():
    """Test complex query with filtering and sorting."""
    print("🧪 Testing complex criteria with sorting...")
    
    builder = KGQueryCriteriaBuilder()
    
    # Create slot criteria for filtering
    slot_criteria = [
        SlotCriteria(
            slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionAmountSlot",
            value=1000,
            comparator="gte"
        ),
        SlotCriteria(
            slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionStatusSlot",
            value="completed",
            comparator="eq"
        )
    ]
    
    # Create sort criteria
    sort_criteria = [
        SortCriteria(
            sort_type="entity_frame_slot",
            frame_path=["http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrameType"],
            slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionDateSlot",
            sort_order="desc",
            priority=1
        )
    ]
    
    # Create complex entity query criteria
    from vitalgraph.sparql.kg_query_builder import FrameCriteria
    criteria = EntityQueryCriteria(
        search_string="premium",
        entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntityType",
        frame_criteria=[FrameCriteria(
            frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrameType"
        )],
        slot_criteria=slot_criteria,
        sort_criteria=sort_criteria
    )
    
    # Build query
    query = builder.build_entity_query_sparql(
        criteria=criteria,
        graph_id="test-graph",
        page_size=15,
        offset=5
    )
    
    print("Generated Complex Query with Filtering and Sorting:")
    print(query)
    print()
    
    # Verify query contains expected elements
    assert "premium" in query
    assert "ORDER BY DESC(?sort_val_0)" in query
    assert "CustomerEntityType" in query
    assert "FinancialTransactionFrameType" in query
    
    print("✅ Complex criteria with sorting test passed!")
    return True

def main():
    """Run all tests."""
    print("🚀 Testing Enhanced KGQueryCriteriaBuilder with Sorting Support")
    print("=" * 70)
    
    tests = [
        test_basic_entity_query_with_sorting,
        test_multi_level_sorting,
        test_frame_query_with_sorting,
        test_complex_criteria_with_sorting
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} failed with error: {e}")
            failed += 1
        print()
    
    print("=" * 70)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! Enhanced query builder is working correctly.")
        return True
    else:
        print("⚠️ Some tests failed. Please review the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
