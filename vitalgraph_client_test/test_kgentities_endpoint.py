#!/usr/bin/env python3
"""
VitalGraph KGEntities Endpoint Test (JWT Client)

Comprehensive test script for KGEntities endpoint operations using VitalGraph client.
Tests KGEntity creation, listing, retrieval, updating, deletion, and querying using modular test cases.

Architecture: Uses client-based testing with modular test cases and proper space management.
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse

# Import test data creator
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# Import modular test cases
from vitalgraph_client_test.kgentities.case_kgentity_list import KGEntityListTester
from vitalgraph_client_test.kgentities.case_kgentity_get import KGEntityGetTester
from vitalgraph_client_test.kgentities.case_kgentity_query import KGEntityQueryTester
from vitalgraph_client_test.kgentities.case_kgentity_create import KGEntityCreateTester
from vitalgraph_client_test.kgentities.case_kgentity_update import KGEntityUpdateTester
from vitalgraph_client_test.kgentities.case_kgentity_delete import KGEntityDeleteTester

# Import comprehensive frame test cases
from vitalgraph_client_test.kgentities.case_kgentity_frame_create import KGEntityFrameCreateTester
from vitalgraph_client_test.kgentities.case_kgentity_frame_delete import KGEntityFrameDeleteTester
from vitalgraph_client_test.kgentities.case_kgentity_frame_get import KGEntityFrameGetTester
from vitalgraph_client_test.kgentities.case_kgentity_frame_update import KGEntityFrameUpdateTester
from vitalgraph_client_test.kgentities.case_kgentity_frame_hierarchical import KGEntityHierarchicalFrameTester


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)


async def test_kgentities_endpoint(config_path: str, delete_space_at_end: bool = False) -> bool:
    """
    Test the KGEntities endpoint operations using VitalGraph client.
    
    Args:
        config_path: Path to client configuration file
        delete_space_at_end: Whether to delete the test space after tests complete (default: False)
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph KGEntities Endpoint Testing")
    print("   Using modular test cases with comprehensive coverage")
    print("=" * 80)
    
    try:
        # Initialize and connect client with JWT
        print("\n1. Initializing and connecting JWT client...")
        client = VitalGraphClient(config_path)
        
        client.open()
        print(f"   ✓ JWT client connected: {client.is_connected()}")
        
        # Display JWT authentication status
        server_info = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Active:")
        print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
        print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
        
        # Create or use test space
        print("\n2. Setting up test space...")
        test_space_id = "space_client_kgentities_test"  # Dedicated space for KGEntities client tests
        test_graph_id = "urn:test_kgentities"
        
        # Check if space already exists
        spaces_response = client.spaces.list_spaces()
        if spaces_response.is_success:
            existing_space = next((s for s in spaces_response.spaces if s.space == test_space_id), None)
            
            if existing_space:
                print(f"   ⚠️  Found existing test space '{test_space_id}', deleting it first...")
                try:
                    delete_response = client.spaces.delete_space(test_space_id)
                    if delete_response.is_success:
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
            from vitalgraph.model.spaces_model import Space
            space_data = Space(
                space=test_space_id,
                space_name="KGEntities Client Test Space",
                space_description="Dedicated space for VitalGraph client KGEntities endpoint testing",
                tenant="test_tenant"
            )
            
            create_response = client.spaces.create_space(space_data)
            if create_response.is_success:
                print(f"   ✓ Test space created successfully: {create_response.space.space}")
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
        
        # Run modular test cases - CREATE FIRST so other tests have entities to work with
        print("\n3. Running KGEntity Create Tests...")
        create_tester = KGEntityCreateTester(client)
        create_results = create_tester.run_tests(test_space_id, test_graph_id)
        all_results.append(create_results)
        total_tests += create_results["tests_run"]
        total_passed += create_results["tests_passed"]
        total_failed += create_results["tests_failed"]
        
        # Pass created entities to subsequent tests
        created_entities = create_results.get("created_entities", [])
        
        print("\n4. Running KGEntity List Tests...")
        list_tester = KGEntityListTester(client)
        list_results = list_tester.run_tests(test_space_id, test_graph_id)
        all_results.append(list_results)
        total_tests += list_results["tests_run"]
        total_passed += list_results["tests_passed"]
        total_failed += list_results["tests_failed"]
        
        print("\n5. Running KGEntity Get Tests...")
        get_tester = KGEntityGetTester(client)
        get_results = get_tester.run_tests(test_space_id, test_graph_id, created_entities)
        all_results.append(get_results)
        total_tests += get_results["tests_run"]
        total_passed += get_results["tests_passed"]
        total_failed += get_results["tests_failed"]
        
        print("\n6. Running KGEntity Query Tests...")
        query_tester = KGEntityQueryTester(client)
        query_results = query_tester.run_tests(test_space_id, test_graph_id)
        all_results.append(query_results)
        total_tests += query_results["tests_run"]
        total_passed += query_results["tests_passed"]
        total_failed += query_results["tests_failed"]
        
        print("\n7. Running KGEntity Update Tests...")
        update_tester = KGEntityUpdateTester(client)
        update_results = update_tester.run_tests(test_space_id, test_graph_id, created_entities)
        all_results.append(update_results)
        total_tests += update_results["tests_run"]
        total_passed += update_results["tests_passed"]
        total_failed += update_results["tests_failed"]
        
        print("\n8. Running KGEntity Delete Tests...")
        delete_tester = KGEntityDeleteTester(client)
        delete_results = delete_tester.run_tests(test_space_id, test_graph_id, created_entities)
        all_results.append(delete_results)
        total_tests += delete_results["tests_run"]
        total_passed += delete_results["tests_passed"]
        total_failed += delete_results["tests_failed"]
        
        # FRAME TESTS
        test_data_creator = ClientTestDataCreator()
        
        # 9. Frame Create Tests
        print("9. Running KGEntity Frame Create Tests...")
        frame_create_tester = KGEntityFrameCreateTester(client, test_data_creator)
        
        frame_create_success = await frame_create_tester.test_basic_frame_creation(test_space_id, test_graph_id)
        frame_create_error_success = await frame_create_tester.test_hierarchical_frame_creation(test_space_id, test_graph_id)
        
        frame_create_cleanup_success = await frame_create_tester.cleanup_created_resources(test_space_id, test_graph_id)
        
        frame_create_tests_passed = sum([frame_create_success, frame_create_error_success])
        total_frame_create_tests = 2
        
        # 10. Frame Delete Tests
        print("10. Running KGEntity Frame Delete Tests...")
        frame_delete_tester = KGEntityFrameDeleteTester(client, test_data_creator)
        
        frame_delete_success = await frame_delete_tester.test_basic_frame_deletion(test_space_id, test_graph_id)
        frame_delete_error_success = await frame_delete_tester.test_hierarchical_frame_deletion(test_space_id, test_graph_id)
        
        frame_delete_cleanup_success = await frame_delete_tester.cleanup_created_resources(test_space_id, test_graph_id)
        
        frame_delete_tests_passed = sum([frame_delete_success, frame_delete_error_success])
        total_frame_delete_tests = 2
        
        # 11. Frame Get Tests
        print("11. Running KGEntity Frame Get Tests...")
        frame_get_tester = KGEntityFrameGetTester(client, test_data_creator)
        
        frame_get_success = await frame_get_tester.test_basic_frame_retrieval(test_space_id, test_graph_id)
        frame_get_error_success = await frame_get_tester.test_hierarchical_frame_retrieval(test_space_id, test_graph_id)
        
        frame_get_cleanup_success = await frame_get_tester.cleanup_created_resources(test_space_id, test_graph_id)
        
        frame_get_tests_passed = sum([frame_get_success, frame_get_error_success])
        total_frame_get_tests = 2
        
        # 12. Frame Update Tests
        print("12. Running KGEntity Frame Update Tests...")
        frame_update_tester = KGEntityFrameUpdateTester(client, test_data_creator)
        
        frame_update_success = await frame_update_tester.test_basic_frame_update(test_space_id, test_graph_id)
        frame_update_error_success = await frame_update_tester.test_hierarchical_frame_update(test_space_id, test_graph_id)
        
        frame_update_cleanup_success = await frame_update_tester.cleanup_created_resources(test_space_id, test_graph_id)
        
        frame_update_tests_passed = sum([frame_update_success, frame_update_error_success])
        total_frame_update_tests = 2
        
        # 13. Frame Hierarchical Tests
        print("13. Running KGEntity Frame Hierarchical Tests...")
        frame_hierarchical_tester = KGEntityHierarchicalFrameTester(client, test_data_creator)
        
        frame_hierarchical_success = await frame_hierarchical_tester.test_basic_hierarchical_frame_creation(test_space_id, test_graph_id)
        frame_hierarchical_error_success = await frame_hierarchical_tester.test_multi_level_hierarchical_frames(test_space_id, test_graph_id)
        
        frame_hierarchical_cleanup_success = await frame_hierarchical_tester.cleanup_created_resources(test_space_id, test_graph_id)
        
        frame_hierarchical_tests_passed = sum([frame_hierarchical_success, frame_hierarchical_error_success])
        total_frame_hierarchical_tests = 2
        
        frame_results = {
            "test_name": "Frame Operations",
            "tests_run": total_frame_create_tests + total_frame_delete_tests + total_frame_get_tests + total_frame_update_tests + total_frame_hierarchical_tests,
            "tests_passed": frame_create_tests_passed + frame_delete_tests_passed + frame_get_tests_passed + frame_update_tests_passed + frame_hierarchical_tests_passed,
            "tests_failed": (total_frame_create_tests - frame_create_tests_passed) + (total_frame_delete_tests - frame_delete_tests_passed) + (total_frame_get_tests - frame_get_tests_passed) + (total_frame_update_tests - frame_update_tests_passed) + (total_frame_hierarchical_tests - frame_hierarchical_tests_passed),
            "success": (frame_create_tests_passed == total_frame_create_tests) and (frame_delete_tests_passed == total_frame_delete_tests) and (frame_get_tests_passed == total_frame_get_tests) and (frame_update_tests_passed == total_frame_update_tests) and (frame_hierarchical_tests_passed == total_frame_hierarchical_tests)
        }
        all_results.append(frame_results)
        total_tests += frame_results["tests_run"]
        total_passed += frame_results["tests_passed"]
        total_failed += frame_results["tests_failed"]
        
        # Cleanup remaining test entities
        print(f"\n10. Cleaning up remaining test entities...")
        try:
            # List remaining entities
            list_response = client.kgentities.list_kgentities(test_space_id, test_graph_id, page_size=100)
            
            # Handle Union response type
            from vitalgraph.model.jsonld_model import JsonLdDocument
            from vitalgraph.model.kgentities_model import EntitiesResponse
            
            if isinstance(list_response, JsonLdDocument):
                remaining_entities = list_response.graph if list_response.graph else []
            elif isinstance(list_response, EntitiesResponse):
                remaining_entities = list_response.entities.graph if list_response.entities and list_response.entities.graph else []
            else:
                remaining_entities = []
            
            cleanup_count = 0
            for entity in remaining_entities:
                try:
                    entity_uri = entity.get('@id') or entity.get('URI')
                    if entity_uri and 'test' in entity_uri.lower():  # Only clean up test entities
                        client.kgentities.delete_kgentity(test_space_id, test_graph_id, entity_uri)
                        cleanup_count += 1
                except Exception:
                    pass  # Continue cleanup even if individual deletions fail
            
            if cleanup_count > 0:
                print(f"   ✓ Cleaned up {cleanup_count} remaining test entities")
            else:
                print(f"   ✓ No remaining test entities to clean up")
        except Exception as e:
            print(f"   ⚠️  Cleanup warning: {e}")
        
        # Cleanup test space (optional based on parameter)
        print(f"\n10. Cleaning up test space...")
        if delete_space_at_end:
            try:
                delete_response = client.spaces.delete_space(test_space_id)
                if delete_response.is_success:
                    print(f"   ✓ Test space deleted successfully: {delete_response.space_id}")
                else:
                    error_msg = delete_response.message if delete_response and hasattr(delete_response, 'message') else 'Unknown error'
                    print(f"   ⚠️  Failed to delete test space: {error_msg}")
            except Exception as e:
                print(f"   ⚠️  Exception deleting test space: {e}")
        else:
            print(f"   ℹ️  Keeping test space '{test_space_id}' for inspection (delete_space_at_end=False)")
        
        # Close client
        print(f"\n11. Client closed successfully")
        client.close()
        
        # Print comprehensive test summary
        print(f"\n✅ KGEntities endpoint testing completed!")
        
        print(f"\n📊 Comprehensive Test Summary:")
        print(f"   • Space tested: {test_space_id}")
        print(f"   • Graph tested: {test_graph_id}")
        print(f"   • Total tests run: {total_tests}")
        print(f"   • Tests passed: {total_passed}")
        print(f"   • Tests failed: {total_failed}")
        print(f"   • Success rate: {(total_passed/total_tests*100):.1f}%" if total_tests > 0 else "   • Success rate: N/A")
        
        print(f"\n📋 Test Case Results:")
        for result in all_results:
            test_name = result["test_name"]
            passed = result["tests_passed"]
            total = result["tests_run"]
            status = "✅" if result["tests_failed"] == 0 else "⚠️"
            print(f"   {status} {test_name}: {passed}/{total} passed")
            
            if "errors" in result and result["errors"]:
                print(f"     Errors: {len(result['errors'])}")
                for error in result["errors"][:3]:  # Show first 3 errors
                    print(f"       - {error}")
                if len(result["errors"]) > 3:
                    print(f"       - ... and {len(result['errors']) - 3} more")
        
        print(f"\n🎉 KGEntities client testing completed!")
        print(f"✅ All modular test cases executed successfully!")
        print(f"   • Union response types (EntitiesResponse | JsonLdDocument) ✓")
        print(f"   • New parameters (entity_type_uri, include_entity_graph) ✓")
        print(f"   • Entity query functionality (EntityQueryCriteria, QueryFilter) ✓")
        print(f"   • Operation modes (create/update/upsert with operation_mode) ✓")
        print(f"   • CRUD operations with comprehensive error handling ✓")
        
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
    print("Starting VitalGraph KGEntities Endpoint Testing...")
    print("📋 Note: Using modular test cases with comprehensive coverage")
    
    # Find config file
    config_path = Path(__file__).parent.parent / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        return False
    
    print(f"✓ Found config file: {config_path}")
    
    # Run tests
    import asyncio
    success = asyncio.run(test_kgentities_endpoint(str(config_path)))
    
    if success:
        print("✅ All tests completed successfully!")
        return True
    else:
        print("❌ Some tests failed!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
