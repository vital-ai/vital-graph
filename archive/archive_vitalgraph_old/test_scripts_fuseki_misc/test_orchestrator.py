#!/usr/bin/env python3
"""
Generic Test Orchestrator Base Classes

Provides base orchestration functionality for modular test implementations.
Used by specific endpoint test scripts to coordinate test execution with
proper space management and resource cleanup.

This is a generic orchestrator - specific endpoint tests should inherit
from these base classes and implement their own test logic.
"""

import logging
import uuid
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod

# Import test framework
import sys
sys.path.append('/Users/hadfield/Local/vital-git/vital-graph/test_scripts/fuseki_postgresql')
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Import models
from vitalgraph.model.spaces_model import Space

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BaseTestOrchestrator(FusekiPostgreSQLEndpointTester, ABC):
    """
    Base test orchestrator for endpoint testing with Fuseki+PostgreSQL backend.
    
    Provides common functionality:
    - Backend setup and teardown
    - Test space creation and cleanup
    - Resource tracking
    - Error handling patterns
    
    Subclasses should implement endpoint-specific test logic.
    """
    
    def __init__(self, test_name: str = "generic"):
        super().__init__()
        self.test_name = test_name
        self.test_space_id = None
        self.test_graph_id = None
        self.created_resource_uris = []
        
    async def create_test_space(self, space_prefix: str = None) -> bool:
        """
        Create test space for endpoint testing.
        
        Args:
            space_prefix: Optional prefix for space naming (defaults to test_name)
            
        Returns:
            bool: True if space creation successful, False otherwise
        """
        try:
            # Use provided prefix or default to test name
            prefix = space_prefix or self.test_name
            
            # Generate unique space and graph IDs
            self.test_space_id = f"test_{prefix}_space_{uuid.uuid4().hex[:8]}"
            self.test_graph_id = f"test_{prefix}_graph_{uuid.uuid4().hex[:8]}"
            
            logger.info(f"🔧 Creating test space: {self.test_space_id}")
            logger.info(f"🔧 Using test graph: {self.test_graph_id}")
            
            # Create space using space manager
            space = Space(
                space=self.test_space_id,
                space_name=f"{prefix.title()} Test Space {self.test_space_id}",
                space_description=f"Test space for {prefix} endpoint testing",
                tenant="test_user_123"
            )
            
            success = await self.space_manager.create_space(space)
            if success:
                logger.info(f"✅ Test space created successfully: {self.test_space_id}")
                return True
            else:
                logger.error(f"❌ Failed to create test space: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error creating test space: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def cleanup_test_space(self) -> bool:
        """Clean up test space and all created resources."""
        try:
            logger.info(f"� Cleaning up test space: {self.test_space_id}")
            
            if self.test_space_id and self.space_manager:
                success = await self.space_manager.delete_space(self.test_space_id)
                if success:
                    logger.info(f"✅ Test space deleted successfully: {self.test_space_id}")
                    return True
                else:
                    logger.error(f"❌ Failed to delete test space: {self.test_space_id}")
                    return False
            else:
                logger.warning("⚠️ No test space to clean up")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def track_created_resource(self, resource_uri: str):
        """Track a created resource URI for cleanup purposes."""
        if resource_uri not in self.created_resource_uris:
            self.created_resource_uris.append(resource_uri)
            logger.debug(f"📝 Tracked resource: {resource_uri}")
    
    def get_created_resources(self) -> List[str]:
        """Get list of created resource URIs."""
        return self.created_resource_uris.copy()
    
    def clear_created_resources(self):
        """Clear the list of created resource URIs."""
        self.created_resource_uris.clear()
    
    @abstractmethod
    async def setup_endpoint(self) -> bool:
        """
        Setup the specific endpoint for testing.
        
        Subclasses must implement this to initialize their specific endpoint.
        
        Returns:
            bool: True if endpoint setup successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def run_test_operations(self) -> bool:
        """
        Run the specific test operations for this endpoint.
        
        Subclasses must implement this to define their test logic.
        
        Returns:
            bool: True if all tests successful, False otherwise
        """
        pass
    
    async def run_orchestrated_tests(self) -> bool:
        """
        Run the full orchestrated test cycle.
        
        Standard pattern: setup → create space → run tests → cleanup
        
        Returns:
            bool: True if all tests successful, False otherwise
        """
        logger.info(f"🚀 Starting {self.test_name} orchestrated test cycle")
        
        try:
            # Setup endpoint
            logger.info("\n" + "="*60)
            logger.info(f"Setting up {self.test_name} endpoint")
            logger.info("="*60)
            
            if not await self.setup_endpoint():
                logger.error("❌ Endpoint setup failed")
                return False
            
            # Create test space
            logger.info("\n" + "="*60)
            logger.info("Creating test space")
            logger.info("="*60)
            
            if not await self.create_test_space():
                logger.error("❌ Test space creation failed")
                return False
            
            # Run test operations
            logger.info("\n" + "="*60)
            logger.info(f"Running {self.test_name} test operations")
            logger.info("="*60)
            
            test_success = await self.run_test_operations()
            
            # Cleanup (always attempt cleanup)
            logger.info("\n" + "="*60)
            logger.info("Cleaning up test space")
            logger.info("="*60)
            
            cleanup_success = await self.cleanup_test_space()
            if not cleanup_success:
                logger.warning("⚠️ Cleanup had issues, but tests completed")
            
            # Report results
            logger.info("\n" + "="*60)
            if test_success:
                logger.info(f"✅ {self.test_name} orchestrated tests completed successfully!")
            else:
                logger.error(f"❌ {self.test_name} orchestrated tests failed!")
            logger.info("📊 Test Results:")
            logger.info(f"   - Endpoint setup: ✅ Success")
            logger.info(f"   - Space creation: ✅ Success")
            logger.info(f"   - Test operations: {'✅ Success' if test_success else '❌ Failed'}")
            logger.info(f"   - Space cleanup: {'✅ Success' if cleanup_success else '⚠️ Issues'}")
            logger.info("="*60)
            
            return test_success
            
        except Exception as e:
            logger.error(f"❌ Orchestrated tests failed with exception: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Always attempt cleanup on failure
            try:
                await self.cleanup_test_space()
            except:
                pass
            
            return False
