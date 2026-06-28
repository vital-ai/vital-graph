#!/usr/bin/env python3
"""
Query Generation Demo

This script demonstrates the SPARQL query generation for various criteria
and sorting combinations without requiring data execution.
"""

import sys
sys.path.insert(0, '/Users/hadfield/Local/vital-git/vital-graph')

from vitalgraph.sparql.kg_query_builder import (
    KGQueryCriteriaBuilder, 
    EntityQueryCriteria, 
    FrameQueryCriteria,
    SlotCriteria, 
    SortCriteria
)

def demo_entity_contains_text():
    """Demo: Entity query with text contains + sorting."""
    print("🔍 **DEMO 1: Entity Query - Text Contains + Name Sorting**")
    print("=" * 70)
    
    builder = KGQueryCriteriaBuilder()
    
    criteria = EntityQueryCriteria(
        search_string="Premium",
        entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntity",
        sort_criteria=[
            SortCriteria(
                sort_type="property",
                property_uri="http://vital.ai/ontology/vital-core#name",
                sort_order="asc",
                priority=1
            )
        ]
    )
    
    query = builder.build_entity_query_sparql_with_sorting(
        criteria=criteria,
        graph_id="customer-graph",
        page_size=20,
        offset=0
    )
    
    print("**Query:** Find customers with 'Premium' in name, sorted by name")
    print("**Generated SPARQL:**")
    print(query)
    print()

def demo_entity_amount_greater_than():
    """Demo: Entity query with amount > threshold + multi-level sorting."""
    print("🔍 **DEMO 2: Entity Query - Amount > $1000 + Multi-Level Sorting**")
    print("=" * 70)
    
    builder = KGQueryCriteriaBuilder()
    
    criteria = EntityQueryCriteria(
        entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntity",
        frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
        slot_criteria=[
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                value=1000.0,
                comparator="gt"
            )
        ],
        sort_criteria=[
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
                slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                sort_order="desc",
                priority=1
            ),
            SortCriteria(
                sort_type="property",
                property_uri="http://vital.ai/ontology/vital-core#name",
                sort_order="asc",
                priority=2
            )
        ]
    )
    
    query = builder.build_entity_query_sparql_with_sorting(
        criteria=criteria,
        graph_id="transaction-graph",
        page_size=15,
        offset=0
    )
    
    print("**Query:** Find customers with transactions > $1000, sorted by amount (desc) then name (asc)")
    print("**Generated SPARQL:**")
    print(query)
    print()

def demo_frame_status_equals():
    """Demo: Frame query with status equals + date sorting."""
    print("🔍 **DEMO 3: Frame Query - Status = 'completed' + Date Sorting**")
    print("=" * 70)
    
    builder = KGQueryCriteriaBuilder()
    
    criteria = FrameQueryCriteria(
        frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
        slot_criteria=[
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#StatusSlot",
                value="completed",
                comparator="eq"
            )
        ],
        sort_criteria=[
            SortCriteria(
                sort_type="frame_slot",
                slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                sort_order="desc",
                priority=1
            )
        ]
    )
    
    query = builder.build_frame_query_sparql_with_sorting(
        criteria=criteria,
        graph_id="transaction-graph",
        page_size=10,
        offset=0
    )
    
    print("**Query:** Find completed transaction frames, sorted by date (newest first)")
    print("**Generated SPARQL:**")
    print(query)
    print()

def demo_entity_date_range():
    """Demo: Entity query with date range (between) + sorting."""
    print("🔍 **DEMO 4: Entity Query - Date Range (Between) + Sorting**")
    print("=" * 70)
    
    builder = KGQueryCriteriaBuilder()
    
    criteria = EntityQueryCriteria(
        entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntity",
        frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
        slot_criteria=[
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                value="2023-07-01",
                comparator="gte"
            ),
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                value="2023-08-31",
                comparator="lte"
            )
        ],
        sort_criteria=[
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
                slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                sort_order="asc",
                priority=1
            )
        ]
    )
    
    query = builder.build_entity_query_sparql_with_sorting(
        criteria=criteria,
        graph_id="transaction-graph",
        page_size=25,
        offset=10
    )
    
    print("**Query:** Find customers with transactions between July-August 2023, sorted by date")
    print("**Generated SPARQL:**")
    print(query)
    print()

def demo_frame_type_contains():
    """Demo: Frame query with type contains + multi-level sorting."""
    print("🔍 **DEMO 5: Frame Query - Type Contains 'purchase' + Multi-Level Sorting**")
    print("=" * 70)
    
    builder = KGQueryCriteriaBuilder()
    
    criteria = FrameQueryCriteria(
        frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
        slot_criteria=[
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#TypeSlot",
                value="purchase",
                comparator="contains"
            )
        ],
        sort_criteria=[
            SortCriteria(
                sort_type="frame_slot",
                slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                sort_order="desc",
                priority=1
            ),
            SortCriteria(
                sort_type="frame_slot",
                slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                sort_order="asc",
                priority=2
            )
        ]
    )
    
    query = builder.build_frame_query_sparql_with_sorting(
        criteria=criteria,
        graph_id="transaction-graph",
        page_size=10,
        offset=0
    )
    
    print("**Query:** Find purchase transaction frames, sorted by amount (desc) then date (asc)")
    print("**Generated SPARQL:**")
    print(query)
    print()

def demo_complex_multi_criteria():
    """Demo: Complex query with multiple criteria and 3-level sorting."""
    print("🔍 **DEMO 6: Complex Multi-Criteria Query with 3-Level Sorting**")
    print("=" * 70)
    
    builder = KGQueryCriteriaBuilder()
    
    criteria = EntityQueryCriteria(
        search_string="Premium",
        entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntity",
        frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
        slot_criteria=[
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#StatusSlot",
                value="completed",
                comparator="eq"
            ),
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                value=500.0,
                comparator="gt"
            ),
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                value="2023-01-01",
                comparator="gte"
            )
        ],
        sort_criteria=[
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
                slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                sort_order="desc",
                priority=1
            ),
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#TransactionFrame",
                slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                sort_order="desc",
                priority=2
            ),
            SortCriteria(
                sort_type="property",
                property_uri="http://vital.ai/ontology/vital-core#name",
                sort_order="asc",
                priority=3
            )
        ]
    )
    
    query = builder.build_entity_query_sparql_with_sorting(
        criteria=criteria,
        graph_id="customer-graph",
        page_size=10,
        offset=0
    )
    
    print("**Query:** Premium customers with completed transactions > $500 in 2023")
    print("**Sorting:** Amount (desc) → Date (desc) → Name (asc)")
    print("**Generated SPARQL:**")
    print(query)
    print()

def main():
    """Run all query generation demos."""
    print("🚀 **COMPREHENSIVE QUERY GENERATION DEMO**")
    print("=" * 80)
    print("Demonstrating SPARQL generation for various criteria and sorting patterns")
    print()
    
    demos = [
        demo_entity_contains_text,
        demo_entity_amount_greater_than,
        demo_frame_status_equals,
        demo_entity_date_range,
        demo_frame_type_contains,
        demo_complex_multi_criteria
    ]
    
    for demo in demos:
        demo()
        print()
    
    print("=" * 80)
    print("🎉 **ALL QUERY PATTERNS DEMONSTRATED SUCCESSFULLY!**")
    print()
    print("✅ **SUPPORTED CRITERIA TYPES:**")
    print("   • **Text Search:** CONTAINS filtering with case-insensitive matching")
    print("   • **Numeric Comparison:** GT, GTE, LT, LTE for amounts and numbers")
    print("   • **Date Range:** GTE/LTE combination for between date filtering")
    print("   • **String Equality:** EQ for exact status and type matching")
    print("   • **URI Matching:** EQ for exact URI-based filtering")
    print()
    print("✅ **SUPPORTED SORTING TYPES:**")
    print("   • **Property Sorting:** Direct entity properties (name, etc.)")
    print("   • **Frame Slot Sorting:** Sort by slot values within frames")
    print("   • **Entity Frame Slot Sorting:** Sort by slot values in entity's frames")
    print("   • **Multi-Level Sorting:** Primary, secondary, tertiary with priorities")
    print("   • **Sort Orders:** ASC (ascending) and DESC (descending)")
    print()
    print("✅ **QUERY PATTERNS:**")
    print("   • **Entity Queries:** Find entities with criteria and sorting")
    print("   • **Frame Queries:** Find frames with criteria and sorting")
    print("   • **Complex Queries:** Multiple criteria + multi-level sorting")
    print("   • **Pagination:** LIMIT/OFFSET support with sorting")
    print("   • **Graph Scoping:** Proper GRAPH clause handling")

if __name__ == "__main__":
    main()
