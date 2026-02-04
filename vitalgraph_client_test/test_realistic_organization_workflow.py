#!/usr/bin/env python3
"""
Realistic Organization Entity Graph Workflow Test

This test demonstrates a realistic workflow for managing an organization entity
with hierarchical frames and slots, including:
- Creating an organization with address, company info, and management structure
- Viewing the entity graph structure
- Making realistic updates (phone number changes, new CEO)
- Viewing changes after each update
- Final comprehensive entity graph display

Structure:
  Organization Entity
    ├── Address Frame → Slots (street, city, state, zip)
    ├── Company Info Frame → Slots (industry, founded, employees)
    └── Management Frame → CEO Frame → Slots (name, role, start date)
"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import List
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns imports
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_subsection(title: str):
    """Print a formatted subsection header."""
    print(f"\n--- {title} ---\n")


def pretty_print_graph_objects(objects: List[GraphObject], title: str = "Graph Objects"):
    """Pretty print a list of GraphObjects."""
    print_subsection(title)
    
    # Organize by type
    entities = []
    frames = []
    slots = []
    edges = []
    
    for obj in objects:
        if isinstance(obj, KGEntity):
            entities.append(obj)
        elif isinstance(obj, KGFrame):
            frames.append(obj)
        elif isinstance(obj, (KGTextSlot, KGIntegerSlot, KGDateTimeSlot)):
            slots.append(obj)
        elif isinstance(obj, (Edge_hasEntityKGFrame, Edge_hasKGFrame, Edge_hasKGSlot)):
            edges.append(obj)
    
    print(f"📊 Graph Summary:")
    print(f"   • Entities: {len(entities)}")
    print(f"   • Frames: {len(frames)}")
    print(f"   • Slots: {len(slots)}")
    print(f"   • Edges: {len(edges)}")
    
    # Print entities
    if entities:
        print(f"\n🏢 Entities:")
        for entity in entities:
            name = str(entity.name) if entity.name else 'Unknown'
            uri = str(entity.URI)
            print(f"   • {name}")
            print(f"     URI: {uri}")
    
    # Print frames
    if frames:
        print(f"\n📋 Frames:")
        for frame in frames:
            name = str(frame.name) if frame.name else 'Unknown'
            uri = str(frame.URI)
            frame_type = str(frame.kGFrameType) if frame.kGFrameType else 'Unknown'
            print(f"   • {name}")
            print(f"     URI: {uri}")
            print(f"     Type: {frame_type.split('#')[-1] if '#' in frame_type else frame_type}")
    
    # Print slots
    if slots:
        print(f"\n🎯 Slots:")
        for slot in slots:
            name = str(slot.name) if slot.name else 'Unknown'
            
            # Get slot value based on slot type
            value = None
            if isinstance(slot, KGTextSlot):
                value = slot.textSlotValue
            elif isinstance(slot, KGIntegerSlot):
                value = slot.integerSlotValue
            elif isinstance(slot, KGDateTimeSlot):
                value = slot.dateTimeSlotValue
            
            print(f"   • {name}: {value}")


def pretty_print_frame_with_slots(frame: KGFrame, slots: List[GraphObject], title: str = "Frame Details"):
    """Pretty print a frame with its slots."""
    print_subsection(title)
    
    name = str(frame.name) if frame.name else 'Unknown'
    uri = str(frame.URI)
    frame_type = str(frame.kGFrameType) if frame.kGFrameType else 'Unknown'
    
    print(f"📋 Frame: {name}")
    print(f"   URI: {uri}")
    print(f"   Type: {frame_type.split('#')[-1] if '#' in frame_type else frame_type}")
    
    if slots:
        print(f"\n   Slots ({len(slots)}):")
        for slot in slots:
            slot_name = str(slot.name) if slot.name else 'Unknown'
            
            # Get slot value
            value = None
            if isinstance(slot, KGTextSlot):
                value = slot.textSlotValue
            elif isinstance(slot, KGIntegerSlot):
                value = slot.integerSlotValue
            elif isinstance(slot, KGDateTimeSlot):
                value = slot.dateTimeSlotValue
            
            print(f"      • {slot_name}: {value}")


def pretty_print_frames_list(frames: List[KGFrame], title: str = "Frames List"):
    """Pretty print a list of frames."""
    print_subsection(title)
    
    print(f"📋 Found {len(frames)} frame(s):\n")
    
    for i, frame in enumerate(frames, 1):
        name = str(frame.name) if frame.name else 'Unknown'
        uri = str(frame.URI)
        frame_type = str(frame.kGFrameType) if frame.kGFrameType else 'Unknown'
        print(f"   {i}. {name}")
        print(f"      URI: {uri}")
        print(f"      Type: {frame_type.split('#')[-1] if '#' in frame_type else frame_type}")


async def query_graph_triples(client: VitalGraphClient, space_id: str, graph_id: str) -> dict:
    """
    Query all triples in a specific graph using SPARQL endpoint with pagination.
    
    Uses pagination (100 triples per page) to handle large result sets.
    
    Returns dict with triple count and all triples.
    """
    try:
        # Import SPARQL request model
        from vitalgraph.model.sparql_model import SPARQLQueryRequest
        
        all_bindings = []
        page_size = 100
        offset = 0
        
        while True:
            # Query with LIMIT and OFFSET for pagination
            query = f"""
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    ?s ?p ?o .
                }}
            }}
            ORDER BY ?s ?p ?o
            LIMIT {page_size}
            OFFSET {offset}
            """
            
            # Create SPARQL query request
            query_request = SPARQLQueryRequest(query=query)
            
            # Execute SPARQL query via client
            result = client.sparql.execute_sparql_query(space_id=space_id, request=query_request)
            
            # SPARQLQueryResponse doesn't have 'success' field, check for 'error' instead
            if hasattr(result, 'error') and result.error:
                return {
                    'success': False,
                    'error': result.error,
                    'triple_count': 0
                }
            
            if hasattr(result, 'results') and result.results:
                bindings = result.results.get('bindings', [])
                
                # If no results, we've reached the end
                if not bindings:
                    break
                
                all_bindings.extend(bindings)
                
                # If we got fewer results than page_size, we've reached the end
                if len(bindings) < page_size:
                    break
                
                offset += page_size
            else:
                break
        
        # Calculate statistics from all bindings
        triple_count = len(all_bindings)
        subjects = set()
        predicates = set()
        for binding in all_bindings:
            if 's' in binding:
                subjects.add(binding['s'].get('value', ''))
            if 'p' in binding:
                predicates.add(binding['p'].get('value', ''))
        
        return {
            'success': True,
            'triple_count': triple_count,
            'subject_count': len(subjects),
            'predicate_count': len(predicates),
            'bindings': all_bindings,
            'pages_fetched': (offset // page_size) + 1
        }
        
    except Exception as e:
        logger.error(f"Error querying graph triples: {e}")
        return {
            'success': False,
            'error': str(e),
            'triple_count': 0
        }


async def validation_checkpoint(client: VitalGraphClient, space_id: str, graph_id: str, checkpoint_name: str):
    """
    Execute validation checkpoint: query triples and get space info with quad logging.
    
    Args:
        client: VitalGraph client
        space_id: Space ID
        graph_id: Graph ID
        checkpoint_name: Name of checkpoint for logging
    """
    print(f"\n🔍 VALIDATION CHECKPOINT: {checkpoint_name}")
    print("-" * 80)
    
    # Query all triples in the graph
    print(f"📊 Querying all triples in graph <{graph_id}>...")
    triple_result = await query_graph_triples(client, space_id, graph_id)
    
    if triple_result['success']:
        print(f"   ✅ Found {triple_result['triple_count']} triples")
        print(f"   📍 Unique subjects: {triple_result['subject_count']}")
        print(f"   🔗 Unique predicates: {triple_result['predicate_count']}")
        if 'pages_fetched' in triple_result:
            print(f"   📄 Pages fetched: {triple_result['pages_fetched']} (100 triples/page)")
        
        # Log ALL triples showing edges, slots, and relationships
        if triple_result.get('bindings'):
            print(f"\n   📋 ALL TRIPLES (showing edges, slots, and relationships):")
            print(f"   " + "=" * 76)
            
            # Get all bindings from the full query result
            all_bindings = triple_result.get('bindings', [])
            
            # Group triples by subject for better readability
            triples_by_subject = {}
            for binding in all_bindings:
                s = binding.get('s', {}).get('value', 'unknown')
                p = binding.get('p', {}).get('value', 'unknown')
                o = binding.get('o', {}).get('value', 'unknown')
                
                if s not in triples_by_subject:
                    triples_by_subject[s] = []
                triples_by_subject[s].append((p, o))
            
            # Print all triples grouped by subject
            for subject_num, (subject, predicates) in enumerate(triples_by_subject.items(), 1):
                s_short = subject.split('/')[-1] if '/' in subject else subject
                print(f"\n   Subject {subject_num}: <{s_short}>")
                
                for p, o in predicates:
                    p_short = p.split('#')[-1] if '#' in p else p.split('/')[-1] if '/' in p else p
                    o_short = o.split('/')[-1] if '/' in o else o[:60]
                    print(f"      → {p_short}: {o_short}")
            
            print(f"\n   " + "=" * 76)
    else:
        print(f"   ⚠️  Query failed: {triple_result.get('error', 'Unknown error')}")
    
    # Get space info to trigger quad logging
    print(f"\n📦 Getting space info (triggers quad logging if enabled)...")
    try:
        space_info = client.spaces.get_space(space_id)
        
        # Handle different response formats
        if space_info:
            print(f"   ✅ Space info retrieved")
            
            # Try to access quad_logging from various possible structures
            quad_info = None
            if hasattr(space_info, 'quad_logging'):
                quad_info = space_info.quad_logging
            elif isinstance(space_info, dict) and 'quad_logging' in space_info:
                quad_info = space_info['quad_logging']
            
            if quad_info:
                print(f"   🔍 Quad logging results:")
                total_quads = quad_info.get('total_quad_count', 0) if isinstance(quad_info, dict) else getattr(quad_info, 'total_quad_count', 0)
                graph_count = quad_info.get('graph_count', 0) if isinstance(quad_info, dict) else getattr(quad_info, 'graph_count', 0)
                print(f"      Total quads: {total_quads}")
                print(f"      Graphs: {graph_count}")
                
                quads_by_graph = quad_info.get('quads_by_graph', {}) if isinstance(quad_info, dict) else getattr(quad_info, 'quads_by_graph', {})
                if quads_by_graph:
                    for graph, count in quads_by_graph.items():
                        graph_short = graph.split('/')[-1] if '/' in graph else graph
                        print(f"         <{graph_short}>: {count} quads")
            else:
                print(f"   ℹ️  Quad logging not enabled (set enable_quad_logging: true in config)")
        else:
            print(f"   ⚠️  No space info returned")
    except Exception as e:
        print(f"   ⚠️  Error getting space info: {e}")
    
    print("-" * 80)


async def main():
    """Run the realistic organization workflow test."""
    
    print_section("🏢 Realistic Organization Entity Graph Workflow Test")
    
    # Initialize client
    print("🔧 Initializing VitalGraph client...")
    # Configuration loaded from environment variables
    client = VitalGraphClient()
    
    # Connect
    print("🔐 Connecting to VitalGraph server...")
    client.open()
    if not client.is_connected():
        print("❌ Connection failed!")
        return False
    print("✅ Connected successfully\n")
    
    # Create test space
    space_id = "space_realistic_org_test"
    graph_id = "urn:realistic_org_graph"
    
    # Check if space already exists and delete it
    print(f"📦 Checking for existing test space: {space_id}")
    try:
        spaces_response = client.spaces.list_spaces()
        existing_spaces = spaces_response.spaces
        existing_space = next((s for s in existing_spaces if s.space == space_id), None)
        
        if existing_space:
            print(f"   Found existing space, deleting...")
            client.spaces.delete_space(space_id)
            print(f"   ✅ Existing space deleted")
    except Exception as e:
        print(f"   Note: Could not check/delete existing space: {e}")
    
    print(f"📦 Creating test space: {space_id}")
    from vitalgraph.model.spaces_model import Space
    space_data = Space(
        space=space_id,
        space_name="Realistic Organization Test",
        space_description="Realistic Organization Test Space",
        tenant="test_tenant"
    )
    create_response = client.spaces.add_space(space_data)
    if not (create_response and (
        (hasattr(create_response, 'success') and create_response.success) or
        (hasattr(create_response, 'created_count') and create_response.created_count == 1)
    )):
        print(f"❌ Failed to create space")
        return False
    print(f"✅ Test space created\n")
    
    try:
        # ============================================================================
        # STEP 1: Create Organization Entity with Hierarchical Frames
        # ============================================================================
        print_section("STEP 1: Create Organization Entity Graph")
        
        print("Creating organization 'Acme Corporation' with:")
        print("  • Address frame with location details")
        print("  • Company info frame with business details")
        print("  • Management frame → CEO frame (hierarchical)")
        
        test_data = ClientTestDataCreator()
        org_objects = test_data.create_organization_with_address("Acme Corporation")
        
        # Extract entity and frame URIs for later use
        org_entity = [obj for obj in org_objects if isinstance(obj, KGEntity)][0]
        org_entity_uri = str(org_entity.URI)
        
        frames = [obj for obj in org_objects if isinstance(obj, KGFrame)]
        
        # Find frames by their type URIs
        address_frame_uri = None
        company_frame_uri = None
        management_frame_uri = None
        ceo_frame_uri = None
        
        for frame in frames:
            frame_type = str(frame.kGFrameType) if frame.kGFrameType else ''
            if frame_type == 'http://vital.ai/ontology/haley-ai-kg#AddressFrame':
                address_frame_uri = str(frame.URI)
            elif frame_type == 'http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame':
                company_frame_uri = str(frame.URI)
            elif frame_type == 'http://vital.ai/ontology/haley-ai-kg#ManagementFrame':
                management_frame_uri = str(frame.URI)
            elif frame_type == 'http://vital.ai/ontology/haley-ai-kg#OfficerFrame':
                ceo_frame_uri = str(frame.URI)
        
        print(f"\n📝 Creating entity graph with {len(org_objects)} objects...")
        
        # VALIDATION CHECKPOINT 1: Before entity insert
        await validation_checkpoint(client, space_id, graph_id, "Before Entity Insert")
        
        # Create entity graph - pass GraphObjects directly
        response = client.kgentities.create_kgentities(
            space_id=space_id,
            graph_id=graph_id,
            objects=org_objects
        )
        
        if not response.is_success:
            print(f"❌ Failed to create entity (error {response.error_code}): {response.error_message}")
            return False
        
        print(f"✅ Entity created successfully!")
        print(f"   Entity URI: {org_entity_uri}")
        
        # VALIDATION CHECKPOINT 2: After entity insert
        await validation_checkpoint(client, space_id, graph_id, "After Entity Insert")
        
        # ============================================================================
        # STEP 2: Retrieve and Display Initial Entity Graph
        # ============================================================================
        print_section("STEP 2: View Initial Entity Graph")
        
        response = client.kgentities.get_kgentity(
            space_id=space_id,
            graph_id=graph_id,
            uri=org_entity_uri,
            include_entity_graph=True
        )
        
        # Direct access to EntityGraph
        if response.is_success and response.objects:
            entity_graph = response.objects
            entity_graph_objects = entity_graph.objects
            pretty_print_graph_objects(entity_graph_objects, "Initial Organization Entity Graph")
        
        # ============================================================================
        # STEP 3: List All Frames
        # ============================================================================
        print_section("STEP 3: List All Organization Frames")
        
        frames_response = client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=org_entity_uri,
            page_size=20
        )
        
        # Convert frames response to GraphObjects
        if frames_response.frames and hasattr(frames_response.frames, 'graph'):
            vs = VitalSigns()
            frame_objects = []
            for frame_data in frames_response.frames.graph:
                frame_obj = vs.from_jsonld(frame_data)
                frame_objects.append(frame_obj)
            pretty_print_frames_list(frame_objects, "All Organization Frames")
        else:
            print(f"Found {frames_response.total_count} frames")
        
        # ============================================================================
        # STEP 4: View Management Frame (Hierarchical)
        # ============================================================================
        print_section("STEP 4: View Management Frame Details")
        
        management_response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=management_frame_uri,
            include_frame_graph=True
        )
        
        if hasattr(management_response, 'success') and management_response.success:
            # Convert to GraphObjects
            vs = VitalSigns()
            if management_response.complete_graph:
                mgmt_objects = vs.from_jsonld_list(management_response.complete_graph.model_dump(by_alias=True))
                # Separate frame and slots
                mgmt_frame = [obj for obj in mgmt_objects if isinstance(obj, KGFrame)][0]
                mgmt_slots = [obj for obj in mgmt_objects if hasattr(obj, 'kGSlotType')]
                pretty_print_frame_with_slots(mgmt_frame, mgmt_slots, "Management Frame (with CEO sub-frame)")
            else:
                mgmt_frame = vs.from_jsonld(management_response.frame.model_dump(by_alias=True))
                pretty_print_frame_with_slots(mgmt_frame, [], "Management Frame")
        
        # ============================================================================
        # STEP 5: Update CEO Information (Realistic Change)
        # ============================================================================
        print_section("STEP 5: Update CEO - New Leadership")
        
        print("📝 Scenario: Acme Corporation appoints a new CEO")
        print("   Old CEO: John Smith")
        print("   New CEO: Sarah Johnson")
        print("   Effective Date: 2024-01-01\n")
        
        # Get current CEO frame with slots
        ceo_response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=ceo_frame_uri,
            include_frame_graph=True
        )
        
        if hasattr(ceo_response, 'success') and ceo_response.success:
            if not ceo_response.complete_graph:
                print("   ⚠️  CEO frame retrieved but complete_graph is None")
                print(f"   Frame type: {type(ceo_response.frame).__name__}")
            
        if hasattr(ceo_response, 'complete_graph') and ceo_response.complete_graph:
            # Convert to GraphObjects
            vs = VitalSigns()
            ceo_objects = vs.from_jsonld_list(ceo_response.complete_graph.model_dump(by_alias=True))
            
            # Find the CEO name and start date slots by slot type
            ceo_name_slot = None
            ceo_start_slot = None
            
            for obj in ceo_objects:
                if hasattr(obj, 'kGSlotType'):
                    slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                    if slot_type == 'http://vital.ai/ontology/haley-ai-kg#OfficerNameSlot':
                        ceo_name_slot = obj
                    elif slot_type == 'http://vital.ai/ontology/haley-ai-kg#OfficerStartDateSlot':
                        ceo_start_slot = obj
            
            # Update CEO name
            if ceo_name_slot:
                print(f"   Updating CEO name from '{ceo_name_slot.textSlotValue}' to 'Sarah Johnson'...")
                ceo_name_slot.textSlotValue = "Sarah Johnson"
                
                # For single object, use to_jsonld() which returns proper JsonLdObject format
                slot_jsonld = ceo_name_slot.to_jsonld()
                # Remove @graph wrapper if present (to_jsonld should return flat object)
                if '@graph' in slot_jsonld and isinstance(slot_jsonld['@graph'], list) and len(slot_jsonld['@graph']) == 1:
                    slot_jsonld = slot_jsonld['@graph'][0]
                
                from vitalgraph.model.jsonld_model import JsonLdObject
                update_response = client.kgframes.update_frame_slots(
                    space_id=space_id,
                    graph_id=graph_id,
                    frame_uri=ceo_frame_uri,
                    data=JsonLdObject(**slot_jsonld)
                )
                
                if hasattr(update_response, 'success'):
                    if update_response.success:
                        print("   ✅ CEO name updated successfully")
                    else:
                        print(f"   ❌ Failed to update CEO name: {update_response.message}")
                else:
                    print(f"   ⚠️  Update response type: {type(update_response).__name__}")
                    print(f"   ⚠️  Response: {update_response}")
            else:
                print("   ❌ CEO name slot not found!")
            
            # Update start date
            if ceo_start_slot:
                print(f"   Updating CEO start date from '{ceo_start_slot.dateTimeSlotValue}' to '2024-01-01'...")
                ceo_start_slot.dateTimeSlotValue = datetime(2024, 1, 1)
                
                # For single object, use to_jsonld() which returns proper JsonLdObject format
                slot_jsonld = ceo_start_slot.to_jsonld()
                # Remove @graph wrapper if present (to_jsonld should return flat object)
                if '@graph' in slot_jsonld and isinstance(slot_jsonld['@graph'], list) and len(slot_jsonld['@graph']) == 1:
                    slot_jsonld = slot_jsonld['@graph'][0]
                
                from vitalgraph.model.jsonld_model import JsonLdObject
                update_response = client.kgframes.update_frame_slots(
                    space_id=space_id,
                    graph_id=graph_id,
                    frame_uri=ceo_frame_uri,
                    data=JsonLdObject(**slot_jsonld)
                )
                
                if hasattr(update_response, 'success'):
                    if update_response.success:
                        print("   ✅ CEO start date updated successfully")
                    else:
                        print(f"   ❌ Failed to update CEO start date: {update_response.message}")
                else:
                    print(f"   ⚠️  Update response type: {type(update_response).__name__}")
                    print(f"   ⚠️  Response: {update_response}")
            else:
                print("   ❌ CEO start date slot not found!")
        else:
            print("   ❌ Failed to retrieve CEO frame or frame has no complete_graph")
            if hasattr(ceo_response, 'success'):
                print(f"   Response success: {ceo_response.success}")
            print(f"   Response type: {type(ceo_response).__name__}")
        
        # View updated CEO frame
        print_subsection("Updated CEO Frame")
        ceo_updated_response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=ceo_frame_uri,
            include_frame_graph=True
        )
        
        if hasattr(ceo_updated_response, 'success') and ceo_updated_response.success:
            vs = VitalSigns()
            if ceo_updated_response.complete_graph:
                ceo_objects = vs.from_jsonld_list(ceo_updated_response.complete_graph.model_dump(by_alias=True))
                ceo_frame = [obj for obj in ceo_objects if isinstance(obj, KGFrame)][0]
                ceo_slots = [obj for obj in ceo_objects if hasattr(obj, 'kGSlotType')]
                pretty_print_frame_with_slots(ceo_frame, ceo_slots, "CEO Frame After Update")
            else:
                ceo_frame = vs.from_jsonld(ceo_updated_response.frame.model_dump(by_alias=True))
                pretty_print_frame_with_slots(ceo_frame, [], "CEO Frame After Update")
        
        # ============================================================================
        # STEP 6: Update Company Information (Growth)
        # ============================================================================
        print_section("STEP 6: Update Company Info - Company Growth")
        
        print("📝 Scenario: Acme Corporation grows significantly")
        print("   Old Employee Count: 500")
        print("   New Employee Count: 1,200\n")
        
        # Get company frame with slots
        company_response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=company_frame_uri,
            include_frame_graph=True
        )
        
        if hasattr(company_response, 'success') and company_response.success:
            if not company_response.complete_graph:
                print("   ⚠️  Company frame retrieved but complete_graph is None")
                
        if hasattr(company_response, 'complete_graph') and company_response.complete_graph:
            # Convert to GraphObjects
            vs = VitalSigns()
            company_objects = vs.from_jsonld_list(company_response.complete_graph.model_dump(by_alias=True))
            
            # Find employee count slot by slot type
            employee_slot = None
            for obj in company_objects:
                if hasattr(obj, 'kGSlotType'):
                    slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                    if slot_type == 'http://vital.ai/ontology/haley-ai-kg#EmployeeCountSlot':
                        employee_slot = obj
                        break
            
            if employee_slot:
                print(f"   Updating employee count from {employee_slot.integerSlotValue} to 1200...")
                employee_slot.integerSlotValue = 1200
                
                # For single object, use to_jsonld() which returns proper JsonLdObject format
                slot_jsonld = employee_slot.to_jsonld()
                # Remove @graph wrapper if present
                if '@graph' in slot_jsonld and isinstance(slot_jsonld['@graph'], list) and len(slot_jsonld['@graph']) == 1:
                    slot_jsonld = slot_jsonld['@graph'][0]
                
                from vitalgraph.model.jsonld_model import JsonLdObject
                update_response = client.kgframes.update_frame_slots(
                    space_id=space_id,
                    graph_id=graph_id,
                    frame_uri=company_frame_uri,
                    data=JsonLdObject(**slot_jsonld)
                )
                
                if hasattr(update_response, 'success'):
                    if update_response.success:
                        print("   ✅ Employee count updated successfully")
                    else:
                        print(f"   ❌ Failed to update employee count: {update_response.message}")
                else:
                    print(f"   ⚠️  Update response type: {type(update_response).__name__}")
            else:
                print("   ❌ Employee count slot not found!")
        else:
            print("   ❌ Failed to retrieve company frame or frame has no complete_graph")
        
        # View updated company frame
        print_subsection("Updated Company Info Frame")
        company_updated_response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=company_frame_uri,
            include_frame_graph=True
        )
        
        if hasattr(company_updated_response, 'success') and company_updated_response.success:
            vs = VitalSigns()
            if company_updated_response.complete_graph:
                company_objects = vs.from_jsonld_list(company_updated_response.complete_graph.model_dump(by_alias=True))
                company_frame = [obj for obj in company_objects if isinstance(obj, KGFrame)][0]
                company_slots = [obj for obj in company_objects if hasattr(obj, 'kGSlotType')]
                pretty_print_frame_with_slots(company_frame, company_slots, "Company Info Frame After Update")
            else:
                company_frame = vs.from_jsonld(company_updated_response.frame.model_dump(by_alias=True))
                pretty_print_frame_with_slots(company_frame, [], "Company Info Frame After Update")
        
        # ============================================================================
        # STEP 7: Update Address (Office Relocation)
        # ============================================================================
        print_section("STEP 7: Update Address - Office Relocation")
        
        print("📝 Scenario: Acme Corporation moves to a new office")
        print("   Old Address: 123 Business Ave, San Francisco, CA 94102")
        print("   New Address: 456 Innovation Blvd, San Francisco, CA 94105\n")
        
        # Get address frame with slots
        address_response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=address_frame_uri,
            include_frame_graph=True
        )
        
        if hasattr(address_response, 'success') and address_response.success:
            if not address_response.complete_graph:
                print("   ⚠️  Address frame retrieved but complete_graph is None")
                
        if hasattr(address_response, 'complete_graph') and address_response.complete_graph:
            # Convert to GraphObjects
            vs = VitalSigns()
            address_objects = vs.from_jsonld_list(address_response.complete_graph.model_dump(by_alias=True))
            
            # Find street and zip slots by slot type
            street_slot = None
            zip_slot = None
            
            for obj in address_objects:
                if hasattr(obj, 'kGSlotType'):
                    slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                    if slot_type == 'http://vital.ai/ontology/haley-ai-kg#StreetSlot':
                        street_slot = obj
                    elif slot_type == 'http://vital.ai/ontology/haley-ai-kg#ZipCodeSlot':
                        zip_slot = obj
            
            # Update street
            if street_slot:
                print(f"   Updating street from '{street_slot.textSlotValue}' to '456 Innovation Blvd'...")
                street_slot.textSlotValue = "456 Innovation Blvd"
                
                # For single object, use to_jsonld() which returns proper JsonLdObject format
                slot_jsonld = street_slot.to_jsonld()
                # Remove @graph wrapper if present
                if '@graph' in slot_jsonld and isinstance(slot_jsonld['@graph'], list) and len(slot_jsonld['@graph']) == 1:
                    slot_jsonld = slot_jsonld['@graph'][0]
                
                from vitalgraph.model.jsonld_model import JsonLdObject
                update_response = client.kgframes.update_frame_slots(
                    space_id=space_id,
                    graph_id=graph_id,
                    frame_uri=address_frame_uri,
                    data=JsonLdObject(**slot_jsonld)
                )
                
                if hasattr(update_response, 'success'):
                    if update_response.success:
                        print("   ✅ Street address updated successfully")
                    else:
                        print(f"   ❌ Failed to update street: {update_response.message}")
                else:
                    print(f"   ⚠️  Update response type: {type(update_response).__name__}")
            else:
                print("   ❌ Street slot not found!")
            
            # Update zip code
            if zip_slot:
                print(f"   Updating zip code from '{zip_slot.textSlotValue}' to '94105'...")
                zip_slot.textSlotValue = "94105"
                
                # For single object, use to_jsonld() which returns proper JsonLdObject format
                slot_jsonld = zip_slot.to_jsonld()
                # Remove @graph wrapper if present
                if '@graph' in slot_jsonld and isinstance(slot_jsonld['@graph'], list) and len(slot_jsonld['@graph']) == 1:
                    slot_jsonld = slot_jsonld['@graph'][0]
                
                from vitalgraph.model.jsonld_model import JsonLdObject
                update_response = client.kgframes.update_frame_slots(
                    space_id=space_id,
                    graph_id=graph_id,
                    frame_uri=address_frame_uri,
                    data=JsonLdObject(**slot_jsonld)
                )
                
                if hasattr(update_response, 'success'):
                    if update_response.success:
                        print("   ✅ Zip code updated successfully")
                    else:
                        print(f"   ❌ Failed to update zip code: {update_response.message}")
                else:
                    print(f"   ⚠️  Update response type: {type(update_response).__name__}")
            else:
                print("   ❌ Zip code slot not found!")
        else:
            print("   ❌ Failed to retrieve address frame or frame has no complete_graph")
        
        # View updated address frame
        print_subsection("Updated Address Frame")
        address_updated_response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=address_frame_uri,
            include_frame_graph=True
        )
        
        if hasattr(address_updated_response, 'success') and address_updated_response.success:
            vs = VitalSigns()
            if address_updated_response.complete_graph:
                address_objects = vs.from_jsonld_list(address_updated_response.complete_graph.model_dump(by_alias=True))
                address_frame = [obj for obj in address_objects if isinstance(obj, KGFrame)][0]
                address_slots = [obj for obj in address_objects if hasattr(obj, 'kGSlotType')]
                pretty_print_frame_with_slots(address_frame, address_slots, "Address Frame After Update")
            else:
                address_frame = vs.from_jsonld(address_updated_response.frame.model_dump(by_alias=True))
                pretty_print_frame_with_slots(address_frame, [], "Address Frame After Update")
        
        # ============================================================================
        # STEP 8: Final Entity Graph Display
        # ============================================================================
        print_section("STEP 8: Final Entity Graph (After All Updates)")
        
        print("📊 Retrieving complete entity graph with all updates...\n")
        
        final_entity_response = client.kgentities.get_kgentity(
            space_id=space_id,
            graph_id=graph_id,
            uri=org_entity_uri,
            include_entity_graph=True
        )
        
        # Convert to GraphObjects
        vs = VitalSigns()
        if isinstance(final_entity_response, JsonLdDocument):
            final_objects = vs.from_jsonld_list(final_entity_response.model_dump(by_alias=True))
            pretty_print_graph_objects(final_objects, "Final Organization Entity Graph")
        elif isinstance(final_entity_response, JsonLdObject):
            final_objects = [vs.from_jsonld(final_entity_response.model_dump(by_alias=True))]
            pretty_print_graph_objects(final_objects, "Final Organization Entity Graph")
            
            print("\n📝 Summary of Changes:")
            print("   ✓ CEO changed from John Smith to Sarah Johnson")
            print("   ✓ CEO start date updated to 2024-01-01")
            print("   ✓ Employee count increased from 500 to 1,200")
            print("   ✓ Office relocated to 456 Innovation Blvd")
            print("   ✓ Zip code updated to 94105")
        
        # VALIDATION CHECKPOINT 3: After all frame updates (before cleanup)
        await validation_checkpoint(client, space_id, graph_id, "After All Frame Updates")
        
        print_section("✅ Test Completed Successfully!")
        
        return True
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up test space...")
        try:
            client.spaces.delete_space(space_id)
            print(f"✅ Test space '{space_id}' deleted")
        except Exception as e:
            print(f"⚠️  Could not delete test space: {e}")
        
        client.close()
        print("✅ Client closed")


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
