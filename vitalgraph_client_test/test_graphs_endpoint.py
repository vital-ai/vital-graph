#!/usr/bin/env python3
"""
Graphs Endpoint Client Test Script

Tests graph management operations using the VitalGraph JWT client.
This script validates graph CRUD operations through the client's graphs endpoint.

Test Coverage:
- Graph creation and validation
- Graph listing with response validation
- Graph information retrieval
- Graph clearing operations
- Graph deletion and cleanup
- Error handling and edge cases

Uses the actual VitalGraph client graphs endpoint methods:
- client.create_graph()
- client.list_graphs()
- client.get_graph_info()
- client.clear_graph()
- client.drop_graph()
"""

import sys
import json
import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import SpacesListResponse, SpaceCreateResponse, Space

# Import modular test cases
from graphs.case_graph_create import GraphCreateTester
from graphs.case_graph_list import GraphListTester
from graphs.case_graph_get import GraphGetTester
from graphs.case_graph_delete import GraphDeleteTester
from graphs.case_graph_clear import GraphClearTester


def setup_logging():
    """Set up logging configuration for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def test_graphs_endpoint(config_path: str) -> bool:
    """
    Test the graphs endpoint operations using VitalGraph client.
    
    Args:
        config_path: Path to configuration file (required)
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph Graphs Endpoint Test (JWT Client)")
    print("=" * 80)
    
    test_results = {
        'total_tests': 0,
        'passed_tests': 0,
        'failed_tests': [],
        'test_details': []
    }
    
    test_space_id = None
    created_graphs = []
    
    try:
        # Initialize and connect client with JWT
        print("\n1. Initializing and connecting JWT client...")
        # Configuration loaded from environment variables
        client = VitalGraphClient()
        
        client.open()
        print(f"   ✓ JWT client connected: {client.is_connected()}")
        
        # Display JWT authentication status
        server_info: Dict[str, Any] = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Active:")
        print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
        print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
        
        # Create or use test space
        print("\n2. Setting up test space...")
        test_space_id = "space_client_test"  # Dedicated space for client tests
        
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
                        print(f"   ❌ Failed to delete existing space: {delete_response.error_message}")
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
                space_name="Client Test Space",
                space_description="Dedicated space for VitalGraph client endpoint testing",
                tenant="test_tenant"
            )
            
            create_response = client.spaces.create_space(space_data)
            if create_response.is_success:
                print(f"   ✓ Test space created successfully: {create_response.space.space if create_response.space else test_space_id}")
            else:
                print(f"   ❌ Failed to create test space: {create_response.error_message}")
                return False
        except Exception as e:
            print(f"   ❌ Exception creating test space: {e}")
            return False
        
        # Test 1: Graph Creation
        print("\n3. Testing graph creation using client graphs endpoint...")
        create_tester = GraphCreateTester(client)
        create_results = create_tester.test_graph_creation(test_space_id)
        
        # Track created graphs for cleanup
        if 'created_graphs' in create_results:
            created_graphs.extend(create_results['created_graphs'])
        
        # Update test results
        test_results['total_tests'] += create_results['total_tests']
        test_results['passed_tests'] += create_results['passed_tests']
        test_results['failed_tests'].extend(create_results['failed_tests'])
        test_results['test_details'].extend(create_results['test_details'])
        
        if create_results['success']:
            print(f"   ✓ Graph creation tests PASSED: {create_results['passed_tests']}/{create_results['total_tests']}")
        else:
            print(f"   ❌ Graph creation tests FAILED: {len(create_results['failed_tests'])} failures")
        
        # Test 2: Graph Listing
        print("\n4. Testing graph listing using client graphs endpoint...")
        list_tester = GraphListTester(client)
        list_results = list_tester.test_graph_listing(test_space_id, created_graphs)
        
        # Update test results
        test_results['total_tests'] += list_results['total_tests']
        test_results['passed_tests'] += list_results['passed_tests']
        test_results['failed_tests'].extend(list_results['failed_tests'])
        test_results['test_details'].extend(list_results['test_details'])
        
        if list_results['success']:
            print(f"   ✓ Graph listing tests PASSED: {list_results['passed_tests']}/{list_results['total_tests']}")
        else:
            print(f"   ❌ Graph listing tests FAILED: {len(list_results['failed_tests'])} failures")
        
        # Test 3: Graph Information Retrieval
        print("\n5. Testing graph info retrieval using client graphs endpoint...")
        get_tester = GraphGetTester(client)
        get_results = get_tester.test_graph_retrieval(test_space_id, created_graphs)
        
        # Update test results
        test_results['total_tests'] += get_results['total_tests']
        test_results['passed_tests'] += get_results['passed_tests']
        test_results['failed_tests'].extend(get_results['failed_tests'])
        test_results['test_details'].extend(get_results['test_details'])
        
        if get_results['success']:
            print(f"   ✓ Graph info retrieval tests PASSED: {get_results['passed_tests']}/{get_results['total_tests']}")
        else:
            print(f"   ❌ Graph info retrieval tests FAILED: {len(get_results['failed_tests'])} failures")
        
        # Test 4: Graph Clearing
        print("\n6. Testing graph clearing using client graphs endpoint...")
        clear_tester = GraphClearTester(client)
        clear_results = clear_tester.test_graph_clearing(test_space_id, created_graphs)
        
        # Update test results
        test_results['total_tests'] += clear_results['total_tests']
        test_results['passed_tests'] += clear_results['passed_tests']
        test_results['failed_tests'].extend(clear_results['failed_tests'])
        test_results['test_details'].extend(clear_results['test_details'])
        
        if clear_results['success']:
            print(f"   ✓ Graph clearing tests PASSED: {clear_results['passed_tests']}/{clear_results['total_tests']}")
        else:
            print(f"   ❌ Graph clearing tests FAILED: {len(clear_results['failed_tests'])} failures")
        
        # Test 5: Graph Deletion
        print("\n7. Testing graph deletion using client graphs endpoint...")
        delete_tester = GraphDeleteTester(client)
        delete_results = delete_tester.test_graph_deletion(test_space_id, created_graphs)
        
        # Update test results
        test_results['total_tests'] += delete_results['total_tests']
        test_results['passed_tests'] += delete_results['passed_tests']
        test_results['failed_tests'].extend(delete_results['failed_tests'])
        test_results['test_details'].extend(delete_results['test_details'])
        
        if delete_results['success']:
            print(f"   ✓ Graph deletion tests PASSED: {delete_results['passed_tests']}/{delete_results['total_tests']}")
        else:
            print(f"   ❌ Graph deletion tests FAILED: {len(delete_results['failed_tests'])} failures")
        
        # Cleanup any remaining graphs
        print("\n8. Cleaning up remaining test graphs...")
        cleanup_count = 0
        for graph_uri in created_graphs[:]:  # Use slice copy to avoid modification during iteration
            try:
                client.drop_graph(test_space_id, graph_uri)
                print(f"   🗑️ Cleaned up graph: {graph_uri}")
                created_graphs.remove(graph_uri)
                cleanup_count += 1
            except Exception as e:
                print(f"   ⚠️  Failed to cleanup graph {graph_uri}: {e}")
        
        if cleanup_count > 0:
            print(f"   ✓ Cleaned up {cleanup_count} remaining graphs")
        else:
            print(f"   ✓ No remaining graphs to clean up")
        
        # Cleanup test space
        print(f"\n9. Cleaning up test space...")
        try:
            delete_response = client.spaces.delete_space(test_space_id)
            if delete_response.is_success:
                print(f"   ✓ Test space deleted successfully: {delete_response.space_id}")
            else:
                print(f"   ⚠️  Failed to delete test space: {delete_response.error_message}")
        except Exception as e:
            print(f"   ⚠️  Exception deleting test space: {e}")
        
        # Close client
        client.close()
        print(f"\n10. Client closed successfully")
        
        # Print comprehensive test summary
        print(f"\n✅ Graphs endpoint testing completed!")
        print(f"\n📊 Test Summary:")
        print(f"   • Total tests: {test_results['total_tests']}")
        print(f"   • Passed tests: {test_results['passed_tests']}")
        print(f"   • Failed tests: {len(test_results['failed_tests'])}")
        if test_results['failed_tests']:
            print(f"   • Failed test names: {', '.join(test_results['failed_tests'])}")
        
        print(f"\n📋 Detailed Test Results:")
        for detail in test_results['test_details']:
            status_icon = "✓" if detail['passed'] else "❌"
            test_name = detail['name']
            print(f"   {status_icon} {test_name}")
            if not detail['passed'] and 'error' in detail:
                print(f"     Error: {detail['error']}")
        
        # Determine overall success
        success = len(test_results['failed_tests']) == 0
        
        if success:
            print(f"\n🎉 All graphs endpoint tests PASSED!")
            print(f"   Graph operations validated using VitalGraph client graphs endpoint methods:")
            print(f"   - client.create_graph()")
            print(f"   - client.list_graphs()")
            print(f"   - client.get_graph_info()")
            print(f"   - client.clear_graph()")
            print(f"   - client.drop_graph()")
        else:
            print(f"\n❌ Some graphs endpoint tests FAILED!")
            print(f"   {len(test_results['failed_tests'])} out of {test_results['total_tests']} tests failed")
        
        return success
        
    except VitalGraphClientError as e:
        print(f"   ❌ VitalGraph client error: {e}")
        logger.error(f"Client error: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main() -> int:
    """Main function to test graphs endpoint.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("Starting VitalGraph Graphs Endpoint Test...")
    
    # Determine config file path (required for JWT client)
    config_dir = Path(__file__).parent.parent / "vitalgraphclient_config"
    config_file = config_dir / "vitalgraphclient-config.yaml"
    
    if config_file.exists():
        config_path = str(config_file)
        print(f"✓ Found config file: {config_path}")
    else:
        print(f"❌ Config file not found: {config_file}")
        print("   JWT client requires a configuration file.")
        print("   Please ensure vitalgraphclient-config.yaml exists in the vitalgraphclient_config directory.")
        return 1
    
    # Run graphs endpoint tests
    success = test_graphs_endpoint(config_path)
    
    if success:
        print("\n🎉 Graphs endpoint testing completed successfully!")
        print("\n✅ Graph operations validated with VitalGraph client graphs endpoint!")
        print("   All graph CRUD operations are working correctly through the client interface.")
        print("   Used modular test cases with proper client method calls.")
        return 0
    else:
        print("\n❌ Graphs endpoint testing failed.")
        print("   Check the error messages above for details.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)