#!/usr/bin/env python3
"""
VitalGraph KGFrames Endpoint Test (JWT Client)

Comprehensive test script for KGFrames endpoint operations using VitalGraph client.
Tests KGFrame creation, listing, retrieval, updating, deletion, and slot operations.

Architecture: Uses TWO-ENDPOINT testing pattern:
- KGEntities endpoint: Creates entity graphs with frames/slots
- KGFrames endpoint: Tests frame operations on existing entity graphs

Follows the correct pattern from fuseki_postgresql test implementation.
"""

import sys
import os
import logging
import inspect
from pathlib import Path
from typing import Dict, Any, List

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse

# Import test data creator
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# Import the comprehensive test case modules
from vitalgraph_client_test.kgframes.case_frame_create import run_frame_creation_tests
from vitalgraph_client_test.kgframes.case_frame_get import run_frame_get_tests
from vitalgraph_client_test.kgframes.case_frame_update import run_frame_update_tests
from vitalgraph_client_test.kgframes.case_frame_delete import run_frame_delete_tests
from vitalgraph_client_test.kgframes.case_slot_create import run_slot_create_tests
from vitalgraph_client_test.kgframes.case_slot_update import run_slot_update_tests
from vitalgraph_client_test.kgframes.case_slot_delete import run_slot_delete_tests
from vitalgraph_client_test.kgframes.case_frames_with_slots import run_frames_with_slots_tests
from vitalgraph_client_test.kgframes.case_child_frames import run_child_frames_tests
from vitalgraph_client_test.kgframes.case_query_frames import run_query_frames_tests
from vitalgraph_client_test.kgframes.case_frame_graphs import run_frame_graphs_tests
from vitalgraph_client_test.kgframes.case_integration_tests import run_integration_tests


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)


async def test_kgframes_endpoint() -> bool:
    """
    Test the KGFrames endpoint operations using VitalGraph client.
    
    Args:
        config_path: Path to client configuration file
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph KGFrames Endpoint Testing")
    print("   Using direct client testing with basic operations")
    print("=" * 80)
    
    try:
        # Initialize and connect client with JWT
        print("\n1. Initializing and connecting JWT client...")
        # Configuration loaded from environment variables
        client = VitalGraphClient()
        
        await client.open()
        print(f"   ✓ JWT client connected: {client.is_connected()}")
        
        # Display JWT authentication status
        server_info = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Active:")
        print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
        print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
        
        # Create or use test space
        print("\n2. Setting up test space...")
        test_space_id = "space_client_kgframes_test"  # Dedicated space for KGFrames client tests
        test_graph_id = "urn:test_kgframes"
        
        # Check if space already exists
        spaces_response = await client.spaces.list_spaces()
        existing_spaces = spaces_response.spaces
        existing_space = next((s for s in existing_spaces if s.space == test_space_id), None)
        
        if existing_space:
            print(f"   ⚠️  Found existing test space '{test_space_id}', deleting it first...")
            try:
                delete_response = await client.spaces.delete_space(test_space_id)
                if delete_response and (
                    (hasattr(delete_response, 'success') and delete_response.success) or
                    (hasattr(delete_response, 'message') and "deleted successfully" in str(delete_response.message))
                ):
                    print(f"   ✓ Existing space deleted successfully")
                else:
                    error_msg = delete_response.message if delete_response and hasattr(delete_response, 'message') else 'Unknown error'
                    print(f"   ❌ Failed to delete existing space: {error_msg}")
                    return False
            except Exception as e:
                print(f"   ❌ Exception deleting existing space: {e}")
                return False
        
        # Create fresh test space
        print(f"   📝 Creating fresh test space: {test_space_id}")
        try:
            space_data = Space(
                space=test_space_id,
                space_name="KGFrames Client Test Space",
                space_description="Dedicated space for VitalGraph client KGFrames endpoint testing",
                tenant="test_tenant"
            )
            
            create_response = await client.spaces.add_space(space_data)
            if create_response and (
                (hasattr(create_response, 'success') and create_response.success) or
                (hasattr(create_response, 'created_count') and create_response.created_count == 1) or
                (hasattr(create_response, 'message') and "created successfully" in str(create_response.message))
            ):
                print(f"   ✓ Test space created successfully: {test_space_id}")
            else:
                error_msg = create_response.message if create_response and hasattr(create_response, 'message') else 'Unknown error'
                print(f"   ❌ Failed to create test space: {error_msg}")
                return False
        except Exception as e:
            print(f"   ❌ Exception creating test space: {e}")
            return False
        
        # Initialize test results tracking
        all_results = []
        total_tests = 0
        total_passed = 0
        total_failed = 0
        
        # Initialize test data creator
        test_data_creator = ClientTestDataCreator()
        
        # Create entity graphs via KGEntities endpoint FIRST (correct pattern)
        print("\n3. Creating entity graphs via KGEntities endpoint...")
        
        # Create comprehensive entity data with frames and slots
        person_objects = test_data_creator.create_person_with_contact("Test Person")
        org_objects = test_data_creator.create_organization_with_address("Test Organization")
        project_objects = test_data_creator.create_project_with_timeline("Test Project")
        
        # Extract entities for creation via KGEntities endpoint
        person_entity = [obj for obj in person_objects if obj.__class__.__name__ == 'KGEntity'][0]
        org_entity = [obj for obj in org_objects if obj.__class__.__name__ == 'KGEntity'][0]
        project_entity = [obj for obj in project_objects if obj.__class__.__name__ == 'KGEntity'][0]
        
        # Convert to quads and create via KGEntities endpoint
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        
        # Create entities with their complete graphs
        entities_created = []
        for entity_name, entity_objects in [
            ("Person", person_objects),
            ("Organization", org_objects), 
            ("Project", project_objects)
        ]:
            try:
                entity_response = await client.kgentities.create_kgentities(
                    space_id=test_space_id,
                    graph_id=test_graph_id,
                    objects=entity_objects
                )
                
                # Check for successful entity creation
                success = False
                entities_count = 0
                
                if hasattr(entity_response, 'is_success') and entity_response.is_success:
                    success = True
                    entities_count = getattr(entity_response, 'created_count', 0)
                elif hasattr(entity_response, 'created_count') and entity_response.created_count > 0:
                    success = True
                    entities_count = entity_response.created_count
                elif hasattr(entity_response, 'message') and "created" in str(entity_response.message).lower():
                    success = True
                    import re
                    match = re.search(r'created (\d+)', str(entity_response.message))
                    entities_count = int(match.group(1)) if match else 1
                
                if success:
                    print(f"   ✓ Created {entity_name} entity graph with {entities_count} entities")
                    entities_created.extend(entity_objects)
                else:
                    error_msg = getattr(entity_response, 'message', 'Unknown error')
                    print(f"   ❌ Failed to create {entity_name} entity: {error_msg}")
                    return False
                    
            except Exception as e:
                print(f"   ❌ Exception creating {entity_name} entity: {e}")
                return False
        
        # Extract test URIs from created entities
        test_entity_uri = str(person_entity.URI)
        
        # Extract frame URIs from created entity graphs
        person_frames = [obj for obj in person_objects if obj.__class__.__name__ == 'KGFrame']
        org_frames = [obj for obj in org_objects if obj.__class__.__name__ == 'KGFrame']
        
        test_frame_uri = str(person_frames[0].URI) if person_frames else None
        test_frame_uris = [str(frame.URI) for frame in person_frames[:3]]
        test_parent_uri = str(org_frames[0].URI) if org_frames else str(org_entity.URI)
        
        # Run comprehensive test suites
        print("\n3. Running Frame Creation Tests...")
        try:
            success = await run_frame_creation_tests(
                client, test_space_id, test_graph_id, 
                entity_uri=test_entity_uri, parent_uri=test_parent_uri, logger=logger
            )
            all_results.append(("Frame Creation Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Frame Creation Tests failed: {e}")
            all_results.append(("Frame Creation Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n4. Running Frame Retrieval Tests...")
        try:
            success = await run_frame_get_tests(
                client, test_space_id, test_graph_id,
                frame_uri=test_frame_uri, entity_uri=test_entity_uri, 
                parent_uri=test_parent_uri, logger=logger
            )
            all_results.append(("Frame Retrieval Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Frame Retrieval Tests failed: {e}")
            all_results.append(("Frame Retrieval Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n5. Running Frame Update Tests...")
        try:
            success = await run_frame_update_tests(
                client, test_space_id, test_graph_id,
                frame_uri=test_frame_uri, entity_uri=test_entity_uri,
                parent_uri=test_parent_uri, logger=logger
            )
            all_results.append(("Frame Update Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Frame Update Tests failed: {e}")
            all_results.append(("Frame Update Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n6. Running Slot Creation Tests...")
        try:
            success = await run_slot_create_tests(
                client, test_space_id, test_graph_id, test_frame_uri,
                entity_uri=test_entity_uri, parent_uri=test_parent_uri, logger=logger
            )
            all_results.append(("Slot Creation Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Slot Creation Tests failed: {e}")
            all_results.append(("Slot Creation Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n7. Running Slot Update Tests...")
        try:
            success = await run_slot_update_tests(
                client, test_space_id, test_graph_id, test_frame_uri,
                entity_uri=test_entity_uri, parent_uri=test_parent_uri, logger=logger
            )
            all_results.append(("Slot Update Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Slot Update Tests failed: {e}")
            all_results.append(("Slot Update Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n8. Running Frames with Slots Integration Tests...")
        try:
            success = await run_frames_with_slots_tests(
                client, test_space_id, test_graph_id,
                frame_uri=test_frame_uri, frame_uris=test_frame_uris,
                entity_uri=test_entity_uri, logger=logger
            )
            all_results.append(("Frames with Slots Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Frames with Slots Tests failed: {e}")
            all_results.append(("Frames with Slots Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n9. Running Child Frames Tests...")
        try:
            success = await run_child_frames_tests(
                client, test_space_id, test_graph_id,
                parent_frame_uri=test_frame_uri, logger=logger
            )
            all_results.append(("Child Frames Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Child Frames Tests failed: {e}")
            all_results.append(("Child Frames Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n10. Running Query Frames Tests...")
        try:
            success = await run_query_frames_tests(
                client, test_space_id, test_graph_id, logger=logger
            )
            all_results.append(("Query Frames Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Query Frames Tests failed: {e}")
            all_results.append(("Query Frames Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n11. Running Frame Graphs Tests...")
        try:
            success = await run_frame_graphs_tests(
                client, test_space_id, test_graph_id,
                frame_uri=test_frame_uri, frame_uris=test_frame_uris,
                entity_uri=test_entity_uri, logger=logger
            )
            all_results.append(("Frame Graphs Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Frame Graphs Tests failed: {e}")
            all_results.append(("Frame Graphs Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n12. Running Integration Tests...")
        try:
            success = await run_integration_tests(
                client, test_space_id, test_graph_id,
                entity_uri=test_entity_uri, logger=logger
            )
            all_results.append(("Integration Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Integration Tests failed: {e}")
            all_results.append(("Integration Tests", False))
            total_tests += 1
            total_failed += 1
        
        # Run destructive tests LAST so they don't break other suites
        print("\n13. Running Slot Delete Tests...")
        try:
            success = await run_slot_delete_tests(
                client, test_space_id, test_graph_id, test_frame_uri, logger=logger
            )
            all_results.append(("Slot Delete Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Slot Delete Tests failed: {e}")
            all_results.append(("Slot Delete Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n14. Running Frame Delete Tests...")
        try:
            success = await run_frame_delete_tests(
                client, test_space_id, test_graph_id,
                frame_uri=test_frame_uri, frame_uris=test_frame_uris,
                parent_frame_uri=test_parent_uri,
                entity_uri=test_entity_uri, logger=logger
            )
            all_results.append(("Frame Delete Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ Frame Delete Tests failed: {e}")
            all_results.append(("Frame Delete Tests", False))
            total_tests += 1
            total_failed += 1
        
        # Cleanup test space
        print(f"\n15. Cleaning up test space...")
        try:
            delete_response = await client.spaces.delete_space(test_space_id)
            if delete_response and hasattr(delete_response, 'is_success') and delete_response.is_success:
                print(f"   ✓ Test space deleted successfully: {test_space_id}")
            elif delete_response and hasattr(delete_response, 'message') and "deleted successfully" in str(delete_response.message):
                print(f"   ✓ Test space deleted successfully: {test_space_id}")
            else:
                error_msg = delete_response.message if delete_response and hasattr(delete_response, 'message') else 'Unknown error'
                print(f"   ⚠️  Failed to delete test space: {error_msg}")
        except Exception as e:
            print(f"   ⚠️  Exception deleting test space: {e}")
        
        # Close client
        print(f"\n16. Client closed successfully")
        await client.close()
        
        # Print comprehensive test summary
        print(f"\n✅ KGFrames endpoint testing completed!")
        
        print(f"\n📊 Comprehensive Test Summary:")
        print(f"   • Space tested: {test_space_id}")
        print(f"   • Graph tested: {test_graph_id}")
        print(f"   • Total test suites run: {total_tests}")
        print(f"   • Test suites passed: {total_passed}")
        print(f"   • Test suites failed: {total_failed}")
        print(f"   • Success rate: {(total_passed/total_tests*100):.1f}%" if total_tests > 0 else "   • Success rate: N/A")
        
        print(f"\n📋 Test Suite Results:")
        for test_name, success in all_results:
            status = "✅" if success else "❌"
            print(f"   {status} {test_name}")
        
        print(f"\n🎉 KGFrames comprehensive client testing completed!")
        if total_failed == 0:
            print(f"✅ All comprehensive test suites passed!")
            print(f"   • Frame CRUD operations ✓")
            print(f"   • Slot CRUD operations ✓") 
            print(f"   • Frames with slots integration ✓")
            print(f"   • End-to-end integration testing ✓")
        else:
            print(f"⚠️ {total_failed} test suite(s) failed - check detailed logs above")
        
        return total_failed == 0
        
    except VitalGraphClientError as e:
        logger.error(f"VitalGraph client error: {e}")
        print(f"\n❌ VitalGraph client error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\n❌ Unexpected error: {e}")
        return False


def main():
    """Main function."""
    print("Starting VitalGraph KGFrames Endpoint Testing...")
    print("📋 Note: Using direct client testing with basic operations")
    
    # Configuration loaded from environment variables
    
    # Run tests
    import asyncio
    success = asyncio.run(test_kgframes_endpoint())
    
    if success:
        print("✅ All tests completed successfully!")
        return True
    else:
        print("❌ Some tests failed!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
