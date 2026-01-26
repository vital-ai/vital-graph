#!/usr/bin/env python3
"""
VitalSigns Test Data Utility Module

This module provides utilities for creating test data for VitalSigns graph objects
with comprehensive multi-frame test scenarios.
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

# Set up logger
logger = logging.getLogger(__name__)


def create_vitalsigns_entity_graphs(set_grouping_uris: bool = True):
    """Create proper VitalSigns entity graphs for testing.
    
    Creates a comprehensive test dataset with:
    - 5 customer entities (3 premium, 1 standard, 1 basic)
    - Multiple frame types per customer:
      - FinancialTransactionFrame (4 per customer)
      - AddressFrame (1 per customer)
      - EmploymentFrame (1 per customer)
    - Various slot types with realistic test data
    - Proper edge relationships between entities, frames, and slots
    
    Args:
        set_grouping_uris: If True (default), sets hasKGGraphURI and hasFrameGraphURI 
                          properties for proper entity graph retrieval. If False, 
                          omits these grouping properties.
    
    Returns:
        List[List[GraphObject]]: List of entity graphs, each containing all objects for one entity
    """
    logger.info("Creating VitalSigns test data...")
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Base URIs
    base_uri = "http://example.com/test"
    
    # Create list to hold entity graphs (each entity graph is a separate list)
    entity_graphs = []
    
    # Create test customers
    customers_data = [
        {"id": "customer1", "name": "Premium Customer Alpha", "tier": "premium"},
        {"id": "customer2", "name": "Standard Customer Beta", "tier": "standard"},
        {"id": "customer3", "name": "Premium Customer Gamma", "tier": "premium"},
        {"id": "customer4", "name": "Basic Customer Delta", "tier": "basic"},
        {"id": "customer5", "name": "Premium Customer Epsilon", "tier": "premium"}
    ]
    
    for customer_data in customers_data:
        # Create KGEntity for customer
        customer = KGEntity()
        customer.URI = f"{base_uri}/entity/{customer_data['id']}"
        customer.name = customer_data["name"]
        customer.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#CustomerEntity"
        # Set kGGraphURI to the entity URI - this groups all related objects
        entity_graph_uri = customer.URI
        if set_grouping_uris:
            customer.kGGraphURI = entity_graph_uri
        
        # Create a new entity graph for this customer
        entity_graph_objects = []
        entity_graph_objects.append(customer)
        
        # Create financial transaction frames for each customer
        transactions_data = [
            {"amount": 1500.00, "date": "2023-06-15T10:30:00Z", "status": "completed", "type": "purchase"},
            {"amount": 750.50, "date": "2023-07-20T14:15:00Z", "status": "completed", "type": "refund"},
            {"amount": 2200.75, "date": "2023-08-10T09:45:00Z", "status": "pending", "type": "purchase"},
            {"amount": 450.25, "date": "2023-09-05T16:20:00Z", "status": "completed", "type": "purchase"}
        ]
        
        for i, transaction_data in enumerate(transactions_data):
            # Create KGFrame for transaction
            frame = KGFrame()
            frame.URI = f"{base_uri}/frame/{customer_data['id']}_transaction_{i+1}"
            frame.name = f"Transaction {i+1} for {customer_data['name']}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame"
            # All frames should reference the same entity graph URI
            if set_grouping_uris:
                frame.frameGraphURI = frame.URI
            
            entity_graph_objects.append(frame)
            
            # Create Edge_hasEntityKGFrame to connect customer to frame
            edge_frame = Edge_hasEntityKGFrame()
            edge_frame.URI = f"{base_uri}/edge/frame/{customer_data['id']}_transaction_{i+1}"
            edge_frame.edgeSource = customer.URI
            edge_frame.edgeDestination = frame.URI
            # Set grouping URIs for the edge
            if set_grouping_uris:
                if hasattr(edge_frame, 'kGGraphURI'):
                    edge_frame.kGGraphURI = entity_graph_uri
            
            entity_graph_objects.append(edge_frame)
            
            # Create slots for the transaction frame
            slots_data = [
                {"type": "AmountSlot", "value": transaction_data["amount"], "slot_class": KGDoubleSlot},
                {"type": "DateSlot", "value": transaction_data["date"], "slot_class": KGDateTimeSlot},
                {"type": "StatusSlot", "value": transaction_data["status"], "slot_class": KGTextSlot},
                {"type": "TypeSlot", "value": transaction_data["type"], "slot_class": KGTextSlot}
            ]
            
            for j, slot_data in enumerate(slots_data):
                # Create appropriate slot type
                slot = slot_data["slot_class"]()
                slot.URI = f"{base_uri}/slot/{customer_data['id']}_transaction_{i+1}_{slot_data['type']}"
                slot.name = f"{slot_data['type']} for Transaction {i+1}"
                slot.kGSlotType = f"http://vital.ai/ontology/haley-ai-kg#{slot_data['type']}"
                # Set grouping URIs
                if set_grouping_uris:
                    # Set entity-level grouping URI
                    if hasattr(slot, 'kGGraphURI'):
                        slot.kGGraphURI = entity_graph_uri
                    
                    # Set frame-level grouping URI
                    if hasattr(slot, 'frameGraphURI'):
                        slot.frameGraphURI = frame.URI
                
                # Set the value based on slot type (using actual VitalSigns property names)
                if isinstance(slot, KGDoubleSlot):
                    slot.doubleSlotValue = slot_data["value"]
                elif isinstance(slot, KGDateTimeSlot):
                    slot.dateTimeSlotValue = slot_data["value"]
                elif isinstance(slot, KGTextSlot):
                    slot.textSlotValue = slot_data["value"]
                
                entity_graph_objects.append(slot)
                
                # Create Edge_hasKGSlot to connect frame to slot
                edge_slot = Edge_hasKGSlot()
                edge_slot.URI = f"{base_uri}/edge/slot/{customer_data['id']}_transaction_{i+1}_{slot_data['type']}"
                edge_slot.edgeSource = frame.URI
                edge_slot.edgeDestination = slot.URI
                # Set grouping URIs for the slot edge
                if set_grouping_uris:
                    if hasattr(edge_slot, 'kGGraphURI'):
                        edge_slot.kGGraphURI = entity_graph_uri
                    if hasattr(edge_slot, 'frameGraphURI'):
                        edge_slot.frameGraphURI = frame.URI
                
                entity_graph_objects.append(edge_slot)
        
        # Add Address frame for this customer
        address_frame = KGFrame()
        address_frame.URI = f"{base_uri}/frame/{customer_data['id']}_address"
        address_frame.name = f"Address for {customer_data['name']}"
        address_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#AddressFrame"
        if set_grouping_uris:
            address_frame.frameGraphURI = address_frame.URI
        entity_graph_objects.append(address_frame)
        
        # Address frame edge
        address_frame_edge = Edge_hasEntityKGFrame()
        address_frame_edge.URI = f"{base_uri}/edge/frame/{customer_data['id']}_address"
        address_frame_edge.edgeSource = f"{base_uri}/entity/{customer_data['id']}"
        address_frame_edge.edgeDestination = address_frame.URI
        # Set grouping URIs for the address frame edge
        if set_grouping_uris:
            if hasattr(address_frame_edge, 'kGGraphURI'):
                address_frame_edge.kGGraphURI = entity_graph_uri
        entity_graph_objects.append(address_frame_edge)
        
        # Postal code slot for address
        postal_slot = KGTextSlot()
        postal_slot.URI = f"{base_uri}/slot/{customer_data['id']}_postal_code"
        postal_slot.name = f"Postal Code for {customer_data['name']}"
        postal_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#PostalCodeSlot"
        postal_slot.textSlotValue = "10001" if customer_data['tier'] == 'premium' else "90210"
        # Set grouping URIs for postal slot
        if set_grouping_uris:
            if hasattr(postal_slot, 'kGGraphURI'):
                postal_slot.kGGraphURI = entity_graph_uri
            if hasattr(postal_slot, 'frameGraphURI'):
                postal_slot.frameGraphURI = address_frame.URI
        entity_graph_objects.append(postal_slot)
        
        postal_edge = Edge_hasKGSlot()
        postal_edge.URI = f"{base_uri}/edge/slot/{customer_data['id']}_postal_code"
        postal_edge.edgeSource = address_frame.URI
        postal_edge.edgeDestination = postal_slot.URI
        # Set grouping URIs for postal edge
        if set_grouping_uris:
            if hasattr(postal_edge, 'kGGraphURI'):
                postal_edge.kGGraphURI = entity_graph_uri
            if hasattr(postal_edge, 'frameGraphURI'):
                postal_edge.frameGraphURI = address_frame.URI
        entity_graph_objects.append(postal_edge)
        
        # Add Employment frame for this customer
        employment_frame = KGFrame()
        employment_frame.URI = f"{base_uri}/frame/{customer_data['id']}_employment"
        employment_frame.name = f"Employment for {customer_data['name']}"
        employment_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#EmploymentFrame"
        if set_grouping_uris:
            employment_frame.frameGraphURI = employment_frame.URI
        entity_graph_objects.append(employment_frame)
        
        # Employment frame edge
        employment_frame_edge = Edge_hasEntityKGFrame()
        employment_frame_edge.URI = f"{base_uri}/edge/frame/{customer_data['id']}_employment"
        employment_frame_edge.edgeSource = f"{base_uri}/entity/{customer_data['id']}"
        employment_frame_edge.edgeDestination = employment_frame.URI
        # Set grouping URIs for employment frame edge
        if set_grouping_uris:
            if hasattr(employment_frame_edge, 'kGGraphURI'):
                employment_frame_edge.kGGraphURI = entity_graph_uri
        entity_graph_objects.append(employment_frame_edge)
        
        # Salary slot for employment
        salary_slot = KGDoubleSlot()
        salary_slot.URI = f"{base_uri}/slot/{customer_data['id']}_salary"
        salary_slot.name = f"Salary for {customer_data['name']}"
        salary_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#SalarySlot"
        salary_slot.doubleSlotValue = 75000.0 if customer_data['tier'] == 'premium' else 45000.0
        # Set grouping URIs for salary slot
        if set_grouping_uris:
            if hasattr(salary_slot, 'kGGraphURI'):
                salary_slot.kGGraphURI = entity_graph_uri
            if hasattr(salary_slot, 'frameGraphURI'):
                salary_slot.frameGraphURI = employment_frame.URI
        entity_graph_objects.append(salary_slot)
        
        salary_edge = Edge_hasKGSlot()
        salary_edge.URI = f"{base_uri}/edge/slot/{customer_data['id']}_salary"
        salary_edge.edgeSource = employment_frame.URI
        salary_edge.edgeDestination = salary_slot.URI
        # Set grouping URIs for salary edge
        if set_grouping_uris:
            if hasattr(salary_edge, 'kGGraphURI'):
                salary_edge.kGGraphURI = entity_graph_uri
            if hasattr(salary_edge, 'frameGraphURI'):
                salary_edge.frameGraphURI = employment_frame.URI
        entity_graph_objects.append(salary_edge)
        
        # Add this complete entity graph to the list
        entity_graphs.append(entity_graph_objects)
    
    # Calculate totals for logging
    total_objects = sum(len(graph) for graph in entity_graphs)
    total_entities = len(entity_graphs)
    all_objects_flat = [obj for graph in entity_graphs for obj in graph]
    
    logger.info("Created %d entity graphs with %d total objects:", total_entities, total_objects)
    logger.info("  - %d customer entities", total_entities)
    logger.info("  - %d frames", len([obj for obj in all_objects_flat if isinstance(obj, KGFrame)]))
    logger.info("  - %d slots", len([obj for obj in all_objects_flat if isinstance(obj, KGSlot)]))
    logger.info("  - %d frame edges", len([obj for obj in all_objects_flat if isinstance(obj, Edge_hasEntityKGFrame)]))
    logger.info("  - %d slot edges", len([obj for obj in all_objects_flat if isinstance(obj, Edge_hasKGSlot)]))
    
    return entity_graphs


def create_vitalsigns_test_data(set_grouping_uris: bool = True):
    """Create proper VitalSigns graph objects for testing (backward compatibility).
    
    This function maintains backward compatibility by returning a flat list of all objects
    from all entity graphs merged together.
    
    Args:
        set_grouping_uris: If True (default), sets hasKGGraphURI and hasFrameGraphURI 
                          properties for proper entity graph retrieval. If False, 
                          omits these grouping properties.
    
    Returns:
        List[GraphObject]: List of all VitalSigns objects ready for RDF conversion
    """
    # Get entity graphs
    entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris)
    
    # Flatten into single list for backward compatibility
    all_objects = []
    for entity_graph in entity_graphs:
        all_objects.extend(entity_graph)
    
    return all_objects


def create_kg_connection_test_data(set_grouping_uris: bool = True) -> List[GraphObject]:
    """
    Create comprehensive test data for KG connection queries.
    
    Generates entities connected via:
    1. Direct relations (Edge_hasKGRelation)
    2. Shared frames (Edge_hasEntityKGFrame)
    
    Args:
        set_grouping_uris: If True, set hasKGGraphURI for server-side loading. 
                          If False, generate clean data for client-side posting to endpoints.
    
    Returns:
        List of VitalSigns GraphObjects (entities, relations, frames, slots, edges)
    """
    
    objects = []
    
    # Create test entities
    person1 = KGEntity()
    person1.URI = "http://example.com/person1"
    person1.name = "John Doe"
    person1.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
    if set_grouping_uris:
        person1.kGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(person1)
    
    person2 = KGEntity()
    person2.URI = "http://example.com/person2"
    person2.name = "Jane Smith"
    person2.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
    if set_grouping_uris:
        person2.kGGraphURI = "http://example.com/graph/person2_graph"
    objects.append(person2)
    
    company1 = KGEntity()
    company1.URI = "http://example.com/company1"
    company1.name = "Tech Corp"
    company1.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#CompanyEntity"
    if set_grouping_uris:
        company1.kGGraphURI = "http://example.com/graph/company1_graph"
    objects.append(company1)
    
    # Create relation-based connections
    works_for_relation = Edge_hasKGRelation()
    works_for_relation.URI = "http://example.com/relation/person1_works_for_company1"
    works_for_relation.edgeSource = person1.URI
    works_for_relation.edgeDestination = company1.URI
    works_for_relation.kGRelationType = "urn:WorksFor"
    objects.append(works_for_relation)
    
    knows_relation = Edge_hasKGRelation()
    knows_relation.URI = "http://example.com/relation/person1_knows_person2"
    knows_relation.edgeSource = person1.URI
    knows_relation.edgeDestination = person2.URI
    knows_relation.kGRelationType = "urn:KnowsPerson"
    objects.append(knows_relation)
    
    # Create frame-based connections (shared employment frame)
    employment_frame = KGFrame()
    employment_frame.URI = "http://example.com/frame/employment1"
    employment_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#EmploymentFrame"
    if set_grouping_uris:
        # Frames should belong to the same grouping URI as their primary entity
        employment_frame.kGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(employment_frame)
    
    # Connect person1 to employment frame
    person1_frame_edge = Edge_hasEntityKGFrame()
    person1_frame_edge.URI = "http://example.com/edge/person1_employment"
    person1_frame_edge.edgeSource = person1.URI
    person1_frame_edge.edgeDestination = employment_frame.URI
    objects.append(person1_frame_edge)
    
    # Connect company1 to same employment frame
    company1_frame_edge = Edge_hasEntityKGFrame()
    company1_frame_edge.URI = "http://example.com/edge/company1_employment"
    company1_frame_edge.edgeSource = company1.URI
    company1_frame_edge.edgeDestination = employment_frame.URI
    objects.append(company1_frame_edge)
    
    # Add slots to employment frame
    position_slot = KGTextSlot()
    position_slot.URI = "http://example.com/slot/position"
    position_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#PositionSlot"
    position_slot.textSlotValue = "Software Engineer"
    if set_grouping_uris:
        position_slot.kGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(position_slot)
    
    salary_slot = KGDoubleSlot()
    salary_slot.URI = "http://example.com/slot/salary"
    salary_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#SalarySlot"
    salary_slot.doubleSlotValue = 75000.0
    if set_grouping_uris:
        salary_slot.kGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(salary_slot)
    
    # Connect slots to frame
    position_edge = Edge_hasKGSlot()
    position_edge.URI = "http://example.com/edge/frame_position"
    position_edge.edgeSource = employment_frame.URI
    position_edge.edgeDestination = position_slot.URI
    objects.append(position_edge)
    
    salary_edge = Edge_hasKGSlot()
    salary_edge.URI = "http://example.com/edge/frame_salary"
    salary_edge.edgeSource = employment_frame.URI
    salary_edge.edgeDestination = salary_slot.URI
    objects.append(salary_edge)
    
    logger.info(f"Created {len(objects)} KG connection test objects (grouping_uris={set_grouping_uris})")
    
    return objects

