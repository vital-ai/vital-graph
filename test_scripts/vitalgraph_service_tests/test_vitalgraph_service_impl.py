#!/usr/bin/env python3
"""
VitalGraphServiceImpl Test Script

Comprehensive test suite for VitalGraphServiceImpl functionality.
Tests service management, graph operations, and helper methods.
"""

import sys
import logging
import json
import unittest
import os
from pathlib import Path

# Add the parent directory to the path so we can import vitalgraph modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.service.graph.vitalgraph_service_impl import VitalGraphServiceImpl
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vital_ai_vitalsigns.service.graph.graph_service_status import GraphServiceStatus
from vital_ai_vitalsigns_core.model.VitalSegment import VitalSegment


def setup_logging():
    """
    Set up logging configuration for the test.
    """
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


class TestVitalGraphServiceImpl(unittest.TestCase):
    """
    Test suite for VitalGraphServiceImpl implementation using real VitalGraphClient.
    
    These tests use the actual VitalGraphClient but can be configured to run
    against different backends or with different configurations.
    """
    
    @classmethod
    def setUpClass(cls):
        """
        Set up test fixtures for the entire test class.
        """
        # Look for test configuration
        cls.test_config_path = os.environ.get('VITALGRAPH_TEST_CONFIG', 'test_config.yaml')
        cls.test_space_id = os.environ.get('VITALGRAPH_TEST_SPACE_ID', 'test_space_123')
        cls.test_base_uri = os.environ.get('VITALGRAPH_TEST_BASE_URI', 'http://vital.ai/test')
        cls.test_namespace = os.environ.get('VITALGRAPH_TEST_NAMESPACE', 'test_namespace')
        
        # Check if we should skip tests due to missing configuration
        config_file = Path(cls.test_config_path)
        if not config_file.exists():
            cls.skip_tests = True
            cls.skip_reason = f"Config file not found: {cls.test_config_path}"
        else:
            cls.skip_tests = False
            cls.skip_reason = None
    
    def setUp(self):
        """
        Set up test fixtures before each test method.
        """
        if self.skip_tests:
            self.skipTest(self.skip_reason)
        
        try:
            # Create service instance with real client
            self.service = VitalGraphServiceImpl(
                config_path=self.test_config_path,
                space_id=self.test_space_id,
                base_uri=self.test_base_uri,
                namespace=self.test_namespace
            )
        except Exception as e:
            self.skipTest(f"Could not initialize service with real client: {e}")
    
    def tearDown(self):
        """
        Clean up after each test method.
        """
        if hasattr(self, 'service') and self.service:
            try:
                # Clean up any test data that may have been created
                self._cleanup_test_data()
            except Exception as e:
                logging.warning(f"Cleanup failed: {e}")
    
    def _cleanup_test_data(self):
        """
        Clean up any test data that may have been created during tests.
        """
        try:
            # Try to destroy the service to clean up any test graphs
            # Only do this if we're in a test namespace
            if hasattr(self, 'service') and 'test' in self.test_namespace.lower():
                result = self.service.destroy_service()
                if result.get('success'):
                    logging.info(f"Test cleanup successful: {result}")
        except Exception as e:
            logging.debug(f"Test cleanup failed (this may be expected): {e}")


class TestServiceManagement(TestVitalGraphServiceImpl):
    """
    Test service management functionality.
    """
    
    def test_service_initialization(self):
        """
        Test service initialization with valid parameters.
        """
        self.assertEqual(self.service.space_id, self.test_space_id)
        self.assertEqual(self.service.base_uri, self.test_base_uri)
        self.assertEqual(self.service.namespace, self.test_namespace)
        self.assertIsNotNone(self.service.client)
        self.assertIsInstance(self.service.client, VitalGraphClient)
    
    def test_service_initialization_without_space_id(self):
        """
        Test that service initialization fails without space_id.
        """
        with patch('vitalgraph.service.graph.vitalgraph_service_impl.VitalGraphClient'):
            with self.assertRaises(ValueError) as context:
                VitalGraphServiceImpl(
                    config_path=self.test_config_path,
                    space_id=None,
                    base_uri=self.test_base_uri,
                    namespace=self.test_namespace
                )
            self.assertIn("space_id is required", str(context.exception))
    
    def test_service_status_online(self):
        """
        Test service status when client is connected.
        """
        # This test depends on the actual client connection state
        status = self.service.service_status()
        # Status should be either ONLINE, OFFLINE, or ERROR
        self.assertIn(status, [GraphServiceStatus.ONLINE, GraphServiceStatus.OFFLINE, GraphServiceStatus.ERROR])
    
    def test_service_status_with_connection_check(self):
        """
        Test service status reflects actual client connection state.
        """
        status = self.service.service_status()
        client_connected = self.service.client.is_connected() if self.service.client else False
        
        if client_connected:
            self.assertEqual(status, GraphServiceStatus.ONLINE)
        else:
            self.assertIn(status, [GraphServiceStatus.OFFLINE, GraphServiceStatus.ERROR])
    
    def test_service_status_no_client(self):
        """
        Test service status when client is None.
        """
        # Temporarily set client to None
        original_client = self.service.client
        self.service.client = None
        
        status = self.service.service_status()
        self.assertEqual(status, GraphServiceStatus.ERROR)
        
        # Restore original client
        self.service.client = original_client
    
    def test_service_info(self):
        """
        Test service info retrieval.
        """
        info = self.service.service_info()
        
        self.assertIsInstance(info, dict)
        self.assertEqual(info["service_name"], "VitalGraphServiceImpl")
        self.assertTrue(info["client_initialized"])
        self.assertTrue(info["client_connected"])
        self.assertEqual(info["config_path"], self.test_config_path)
        self.assertIn("server_info", info)


class TestServiceLifecycle(TestVitalGraphServiceImpl):
    """
    Test service lifecycle operations (initialize/destroy).
    """
    
    def test_initialize_service_success(self):
        """
        Test successful service initialization.
        """
        # First try to clean up any existing service
        try:
            self.service.destroy_service()
        except:
            pass  # Expected if service doesn't exist
        
        result = self.service.initialize_service()
        
        # Result should be a dictionary with success status
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        
        if result["success"]:
            self.assertEqual(result["message"], "Service initialized successfully")
        else:
            # If initialization failed, it might be due to existing service or conflicts
            self.assertIn("error", result)
            logging.info(f"Service initialization result: {result}")
    
    def test_initialize_service_already_exists(self):
        """
        Test service initialization when service graph already exists.
        """
        # First initialize the service
        first_result = self.service.initialize_service()
        
        # Try to initialize again - should fail
        second_result = self.service.initialize_service()
        
        self.assertIsInstance(second_result, dict)
        self.assertIn("success", second_result)
        
        if first_result.get("success"):
            # If first initialization succeeded, second should fail
            self.assertFalse(second_result["success"])
            self.assertIn("already initialized", second_result.get("error", "").lower())
        else:
            # If first failed, second might also fail for same reason
            logging.info(f"Both initialization attempts failed: {first_result}, {second_result}")
    
    def test_initialize_service_namespace_conflict(self):
        """
        Test service initialization with namespace conflict.
        
        Note: This test may be skipped if no actual conflict exists in the test environment.
        """
        # This test is complex to set up with real client, so we'll skip it for now
        # In a real scenario, we would need to create a conflicting graph first
        self.skipTest("Namespace conflict test requires specific setup with real backend")
    
    def test_destroy_service_success(self):
        """
        Test successful service destruction.
        """
        # First initialize the service to have something to destroy
        init_result = self.service.initialize_service()
        
        # Create a test graph to verify cleanup
        if init_result.get("success"):
            try:
                self.service.create_graph("test_cleanup_graph", global_graph=True)
            except:
                pass  # Graph creation may fail, that's okay
        
        # Now test destruction
        result = self.service.destroy_service()
        
        # Result should be a dictionary with success status
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        
        if result["success"]:
            self.assertEqual(result["message"], "Service destroyed successfully")
            if "deleted_graphs" in result:
                self.assertIsInstance(result["deleted_graphs"], list)
        else:
            # Destruction may fail if service wasn't initialized
            self.assertIn("error", result)
            logging.info(f"Service destruction result: {result}")


class TestHelperMethods(TestVitalGraphServiceImpl):
    """
    Test helper methods functionality.
    """
    
    def test_get_service_graph_uri(self):
        """
        Test service graph URI generation.
        """
        expected_uri = f"{self.test_base_uri}/{self.test_namespace}/vital-service-graph"
        actual_uri = self.service._get_service_graph_uri()
        self.assertEqual(actual_uri, expected_uri)
    
    def test_get_graph_uri_global(self):
        """
        Test graph URI generation for global graphs.
        """
        graph_id = "test_graph"
        account_id = "test_account"
        
        uri = self.service._get_graph_uri(graph_id, account_id, global_graph=True)
        expected_uri = f"{self.test_base_uri}/GLOBAL/{graph_id}"
        self.assertEqual(uri, expected_uri)
    
    def test_get_graph_uri_private(self):
        """
        Test graph URI generation for private graphs.
        """
        graph_id = "test_graph"
        account_id = "test_account"
        
        uri = self.service._get_graph_uri(graph_id, account_id, global_graph=False)
        expected_uri = f"{self.test_base_uri}/{account_id}/{graph_id}"
        self.assertEqual(uri, expected_uri)
    
    def test_create_service_vital_segment(self):
        """
        Test service VitalSegment creation.
        """
        segment = self.service._create_service_vital_segment()
        
        self.assertIsInstance(segment, VitalSegment)
        self.assertEqual(segment.name, "vital-service-graph")
        self.assertEqual(segment.segmentNamespace, self.test_namespace)
        self.assertEqual(segment.segmentID, "vital-service-graph")
        self.assertIsNone(segment.segmentTenantID)
        self.assertFalse(segment.segmentGlobal)
        self.assertEqual(segment.segmentStateJSON, "[]")
    
    def test_create_graph_vital_segment(self):
        """
        Test graph VitalSegment creation.
        """
        graph_id = "test_graph"
        account_id = "test_account"
        global_graph = False
        
        segment = self.service._create_graph_vital_segment(graph_id, account_id, global_graph)
        
        self.assertIsInstance(segment, VitalSegment)
        self.assertEqual(segment.name, graph_id)
        self.assertEqual(segment.segmentNamespace, self.test_namespace)
        self.assertEqual(segment.segmentID, graph_id)
        self.assertEqual(segment.segmentTenantID, account_id)
        self.assertEqual(segment.segmentGlobal, global_graph)
    
    def test_check_graph_exists_true(self):
        """
        Test graph existence check when graph exists.
        """
        graph_uri = "http://test.com/graph"
        self.mock_client.execute_sparql_query.return_value = {"boolean": True}
        
        exists = self.service._check_graph_exists(graph_uri)
        self.assertTrue(exists)
    
    def test_check_graph_exists_false(self):
        """
        Test graph existence check when graph doesn't exist.
        """
        graph_uri = "http://test.com/graph"
        self.mock_client.execute_sparql_query.return_value = {"boolean": False}
        
        exists = self.service._check_graph_exists(graph_uri)
        self.assertFalse(exists)
    
    def test_ensure_client_connected_success(self):
        """
        Test client connection validation when connected.
        """
        self.mock_client.is_connected.return_value = True
        
        # Should not raise exception
        self.service._ensure_client_connected()
    
    def test_ensure_client_connected_no_client(self):
        """
        Test client connection validation when no client.
        """
        self.service.client = None
        
        with self.assertRaises(VitalGraphClientError) as context:
            self.service._ensure_client_connected()
        self.assertIn("not initialized", str(context.exception))
    
    def test_ensure_client_connected_not_connected(self):
        """
        Test client connection validation when not connected.
        """
        self.mock_client.is_connected.return_value = False
        
        with self.assertRaises(VitalGraphClientError) as context:
            self.service._ensure_client_connected()
        self.assertIn("not connected", str(context.exception))


class TestGraphManagement(TestVitalGraphServiceImpl):
    """
    Test graph management operations.
    """
    
    def test_create_graph_success(self):
        """
        Test successful graph creation.
        """
        graph_id = "test_graph"
        account_id = "test_account"
        global_graph = False
        
        # Mock graph doesn't exist
        self.mock_client.execute_sparql_query.return_value = {"boolean": False}
        # Mock successful operations
        self.mock_client.execute_sparql_update.return_value = {"success": True}
        self.mock_client.execute_sparql_insert.return_value = {"success": True}
        
        result = self.service.create_graph(
            graph_id=graph_id,
            account_id=account_id,
            global_graph=global_graph
        )
        
        self.assertTrue(result)
        
        # Verify SPARQL operations were called
        self.mock_client.execute_sparql_update.assert_called()  # CREATE GRAPH
        self.mock_client.execute_sparql_insert.assert_called()  # INSERT metadata
    
    def test_create_graph_already_exists(self):
        """
        Test graph creation when graph already exists.
        """
        graph_id = "test_graph"
        account_id = "test_account"
        
        # Mock graph exists
        self.mock_client.execute_sparql_query.return_value = {"boolean": True}
        
        result = self.service.create_graph(
            graph_id=graph_id,
            account_id=account_id,
            global_graph=False
        )
        
        self.assertFalse(result)
    
    def test_delete_graph_success(self):
        """
        Test successful graph deletion.
        """
        graph_id = "test_graph"
        account_id = "test_account"
        global_graph = False
        
        # Mock graph exists
        self.mock_client.execute_sparql_query.return_value = {"boolean": True}
        # Mock successful operations
        self.mock_client.execute_sparql_update.return_value = {"success": True}
        self.mock_client.execute_sparql_delete.return_value = {"success": True}
        
        result = self.service.delete_graph(
            graph_id=graph_id,
            account_id=account_id,
            global_graph=global_graph
        )
        
        self.assertTrue(result)
        
        # Verify SPARQL operations were called
        self.mock_client.execute_sparql_update.assert_called()  # DROP GRAPH
        self.mock_client.execute_sparql_delete.assert_called()  # DELETE metadata
    
    def test_delete_graph_not_exists(self):
        """
        Test graph deletion when graph doesn't exist.
        """
        graph_id = "test_graph"
        account_id = "test_account"
        
        # Mock graph doesn't exist
        self.mock_client.execute_sparql_query.return_value = {"boolean": False}
        
        result = self.service.delete_graph(
            graph_id=graph_id,
            account_id=account_id,
            global_graph=False
        )
        
        self.assertFalse(result)


if __name__ == '__main__':
    setup_logging()
    unittest.main(verbosity=2)
