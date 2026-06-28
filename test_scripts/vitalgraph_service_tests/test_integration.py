#!/usr/bin/env python3
"""
VitalGraphServiceImpl Integration Tests

Integration tests that use actual VitalGraphClient (when available).
These tests are designed to run against a real backend when ready.
"""

import sys
import logging
import unittest
from pathlib import Path

# Add the parent directory to the path so we can import vitalgraph modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.service.graph.vitalgraph_service_impl import VitalGraphServiceImpl
from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError


class TestVitalGraphServiceIntegration(unittest.TestCase):
    """
    Integration test suite for VitalGraphServiceImpl with real client.
    
    Note: These tests require a running VitalGraph backend and valid configuration.
    They are designed to be run when the service and client are fully operational.
    """
    
    @classmethod
    def setUpClass(cls):
        """
        Set up test fixtures for the entire test class.
        """
        cls.test_config_path = "test_config.yaml"  # Update with actual config path
        cls.test_space_id = "integration_test_space"
        cls.test_base_uri = "http://vital.ai/integration_test"
        cls.test_namespace = "integration_test_ns"
        
        # Skip tests if no config available
        config_file = Path(cls.test_config_path)
        if not config_file.exists():
            cls.skipTest(cls, f"Config file not found: {cls.test_config_path}")
    
    def setUp(self):
        """
        Set up test fixtures before each test method.
        """
        try:
            self.service = VitalGraphServiceImpl(
                config_path=self.test_config_path,
                space_id=self.test_space_id,
                base_uri=self.test_base_uri,
                namespace=self.test_namespace
            )
        except Exception as e:
            self.skipTest(f"Could not initialize service: {e}")
    
    def tearDown(self):
        """
        Clean up after each test method.
        """
        if hasattr(self, 'service') and self.service:
            try:
                # Clean up any test graphs created
                self._cleanup_test_graphs()
            except Exception as e:
                logging.warning(f"Cleanup failed: {e}")
    
    def _cleanup_test_graphs(self):
        """
        Clean up any test graphs that may have been created.
        """
        try:
            # Try to destroy the service (which cleans up all managed graphs)
            result = self.service.destroy_service()
            logging.info(f"Cleanup result: {result}")
        except Exception as e:
            logging.warning(f"Service destruction failed during cleanup: {e}")
    
    @unittest.skip("Integration test - requires running backend")
    def test_full_service_lifecycle(self):
        """
        Test complete service lifecycle: initialize -> create graphs -> destroy.
        """
        # Test service initialization
        init_result = self.service.initialize_service()
        self.assertTrue(init_result["success"], f"Service initialization failed: {init_result}")
        
        # Test graph creation
        graph_created = self.service.create_graph(
            graph_id="integration_test_graph",
            account_id="test_account",
            global_graph=False
        )
        self.assertTrue(graph_created, "Graph creation failed")
        
        # Test global graph creation
        global_graph_created = self.service.create_graph(
            graph_id="integration_test_global_graph",
            account_id="test_account",
            global_graph=True
        )
        self.assertTrue(global_graph_created, "Global graph creation failed")
        
        # Test service destruction (cleans up all graphs)
        destroy_result = self.service.destroy_service()
        self.assertTrue(destroy_result["success"], f"Service destruction failed: {destroy_result}")
        
        # Verify graphs were cleaned up
        self.assertGreater(len(destroy_result["deleted_graphs"]), 0, "No graphs were deleted during cleanup")
    
    @unittest.skip("Integration test - requires running backend")
    def test_service_status_and_info(self):
        """
        Test service status and info retrieval with real client.
        """
        # Test service status
        status = self.service.service_status()
        self.assertIsNotNone(status)
        
        # Test service info
        info = self.service.service_info()
        self.assertIsInstance(info, dict)
        self.assertIn("service_name", info)
        self.assertIn("client_initialized", info)
        self.assertIn("client_connected", info)
    
    @unittest.skip("Integration test - requires running backend")
    def test_graph_management_operations(self):
        """
        Test graph creation, existence checking, and deletion.
        """
        # Initialize service first
        init_result = self.service.initialize_service()
        if not init_result["success"]:
            self.skipTest(f"Could not initialize service: {init_result}")
        
        graph_id = "test_graph_operations"
        account_id = "test_account"
        
        try:
            # Test graph creation
            created = self.service.create_graph(
                graph_id=graph_id,
                account_id=account_id,
                global_graph=False
            )
            self.assertTrue(created, "Graph creation failed")
            
            # Test graph existence (indirectly through creation failure)
            duplicate_created = self.service.create_graph(
                graph_id=graph_id,
                account_id=account_id,
                global_graph=False
            )
            self.assertFalse(duplicate_created, "Duplicate graph creation should fail")
            
            # Test graph deletion
            deleted = self.service.delete_graph(
                graph_id=graph_id,
                account_id=account_id,
                global_graph=False
            )
            self.assertTrue(deleted, "Graph deletion failed")
            
            # Test deletion of non-existent graph
            deleted_again = self.service.delete_graph(
                graph_id=graph_id,
                account_id=account_id,
                global_graph=False
            )
            self.assertFalse(deleted_again, "Deletion of non-existent graph should fail")
            
        finally:
            # Cleanup
            self.service.destroy_service()
    
    @unittest.skip("Integration test - requires running backend")
    def test_error_handling_with_real_client(self):
        """
        Test error handling scenarios with real client.
        """
        # Test operations without service initialization
        graph_created = self.service.create_graph(
            graph_id="test_graph_no_init",
            account_id="test_account",
            global_graph=False
        )
        # This should fail gracefully
        self.assertFalse(graph_created, "Graph creation should fail without service initialization")
        
        # Test duplicate service initialization
        init_result1 = self.service.initialize_service()
        if init_result1["success"]:
            init_result2 = self.service.initialize_service()
            self.assertFalse(init_result2["success"], "Duplicate initialization should fail")
            
            # Cleanup
            self.service.destroy_service()


class TestVitalGraphServicePerformance(unittest.TestCase):
    """
    Performance tests for VitalGraphServiceImpl.
    
    These tests measure performance characteristics of various operations.
    """
    
    @unittest.skip("Performance test - requires running backend and performance baseline")
    def test_bulk_graph_operations_performance(self):
        """
        Test performance of bulk graph operations.
        """
        # This test would create many graphs and measure timing
        pass
    
    @unittest.skip("Performance test - requires running backend and performance baseline")
    def test_service_initialization_performance(self):
        """
        Test performance of service initialization.
        """
        # This test would measure initialization time
        pass


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    unittest.main(verbosity=2)
