#!/usr/bin/env python3
"""
Common utilities for KG endpoint testing.

This module provides shared functionality for testing KG endpoints including:
- VitalGraph app setup and teardown
- Space management operations
- Test data creation and cleanup
- Common test patterns and assertions
"""

import sys
import os
import json
import logging
import uuid
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# VitalGraph imports
from vitalgraph.config.config_loader import get_config
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BaseKGEndpointTester:
    """Base class for KG endpoint testing with common functionality."""
    
    def __init__(self, fuseki_url: str = "http://localhost:3030"):
        self.fuseki_url = fuseki_url
        self.vitalgraph_app = None
        self.space_manager = None
        self.kgentities_endpoint = None
        self.kgframes_endpoint = None
        self.test_results = []
        self.cached_spaces = []
        
        # Test data
        self.test_entity_graphs = []
        self.entity_test_space_id = None
        self.created_entity_uris = []
        
        # Prefixes for SPARQL queries
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
    
    async def setup_vitalgraph_app(self) -> bool:
        """Setup VitalGraph application with Fuseki backend."""
        try:
            logger.info("🔧 Setting up VitalGraph app with Fuseki backend")
            
            # Load configuration with proper config file path
            config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
            if config_path.exists():
                config = get_config(str(config_path))
            else:
                # Fallback to default config
                config = get_config()
            
            # Override Fuseki URL for testing
            config.fuseki_url = self.fuseki_url
            
            # Initialize VitalGraph implementation
            self.vitalgraph_app = VitalGraphImpl(config)
            
            # Get space manager
            self.space_manager = self.vitalgraph_app.get_space_manager()
            
            # Initialize space manager from database
            await self.space_manager.initialize_from_database()
            
            # Create mock auth dependency for testing
            def mock_auth_dependency():
                return {"username": "test_user", "user_id": "test_user_123"}
            
            # Initialize endpoints
            self.kgentities_endpoint = KGEntitiesEndpoint(
                space_manager=self.space_manager,
                auth_dependency=mock_auth_dependency
            )
            
            logger.info("✅ VitalGraph app setup completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup VitalGraph app: {e}")
            return False
    
    async def create_test_space(self, space_name_prefix: str = "test_space") -> Optional[str]:
        """Create a test space and return its ID."""
        try:
            test_space_id = f"{space_name_prefix}_{uuid.uuid4().hex[:8]}"
            
            space_created = await self.space_manager.create_space_with_tables(
                space_id=test_space_id,
                space_name=f"Test Space {test_space_id}",
                space_description=f"Test space for {space_name_prefix} operations"
            )
            
            if space_created:
                self.cached_spaces.append(test_space_id)
                logger.info(f"✅ Created test space: {test_space_id}")
                return test_space_id
            else:
                logger.error(f"❌ Failed to create test space: {test_space_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Exception creating test space: {e}")
            return None
    
    async def create_entity_graphs_in_space(self, space_id: str) -> bool:
        """Create test entity graphs in the specified space."""
        try:
            logger.info(f"🔍 Creating entity graphs in space: {space_id}")
            
            # Create test entity graphs using VitalSigns
            entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=False)
            
            if not entity_graphs:
                logger.error("❌ Failed to create entity graphs from test data")
                return False
            
            logger.info(f"📋 Created {len(entity_graphs)} entity graphs from test data")
            
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            self.created_entity_uris = []
            
            # Create each entity graph in the test space
            for i, entity_graph in enumerate(entity_graphs):
                logger.info(f"🔍 Creating entity graph {i+1}/{len(entity_graphs)} with {len(entity_graph)} objects")
                
                # Create entities in the test space - pass GraphObjects directly
                response = await self.kgentities_endpoint._create_or_update_entities(
                    space_id=space_id,
                    graph_id="main",
                    objects=entity_graph,
                    operation_mode=OperationMode.CREATE,
                    parent_uri=None,
                    current_user={"username": "test_user", "user_id": "test_user_123"}
                )
                
                if response and hasattr(response, 'created_uris') and response.created_uris:
                    # Store the entity URI (first URI should be the main entity)
                    entity_uri = response.created_uris[0]
                    self.created_entity_uris.append(entity_uri)
                    logger.info(f"✅ Created entity graph {i+1}: {entity_uri} ({len(response.created_uris)} objects)")
                else:
                    logger.error(f"❌ No entities created for graph {i+1}")
                    return False
            
            logger.info(f"✅ Created {len(entity_graphs)} entity graphs with {len(self.created_entity_uris)} entities")
            return True
            
        except Exception as e:
            logger.error(f"❌ Exception creating entity graphs: {e}")
            return False
    
    async def cleanup_entity_graphs(self, space_id: str) -> bool:
        """Clean up entity graphs from the specified space."""
        try:
            if not self.created_entity_uris:
                logger.info("ℹ️ No entity graphs to clean up")
                return True
            
            logger.info(f"🧹 Cleaning up {len(self.created_entity_uris)} entity graphs")
            
            for i, entity_uri in enumerate(self.created_entity_uris):
                try:
                    response = await self.kgentities_endpoint._delete_entity_by_uri(
                        space_id=space_id,
                        graph_id="main",
                        uri=entity_uri,
                        delete_entity_graph=True,
                        current_user={"username": "test_user", "user_id": "test_user_123"}
                    )
                    
                    if response and hasattr(response, 'deleted_count'):
                        logger.info(f"🧹 Deleted entity graph {i+1}: {response.deleted_count} objects")
                    else:
                        logger.warning(f"⚠️ Failed to delete entity graph {i+1}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Exception deleting entity graph {i+1}: {e}")
            
            self.created_entity_uris = []
            logger.info("✅ Entity graphs cleanup completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Exception during entity graphs cleanup: {e}")
            return False
    
    async def cleanup_resources(self):
        """Clean up all test resources."""
        try:
            logger.info("🧹 Starting resource cleanup")
            
            # Clean up cached spaces
            if self.cached_spaces:
                logger.info(f"🧹 Found {len(self.cached_spaces)} cached spaces to clean up")
                
                for space_id in self.cached_spaces:
                    try:
                        logger.info(f"🧹 Cleaning up space: {space_id}")
                        
                        # Close the space implementation
                        space_record = self.space_manager.get_space(space_id)
                        if space_record and space_record.space_impl:
                            await space_record.space_impl.close()
                            logger.info(f"🧹 Closed SpaceImpl for space: {space_id}")
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Error closing space {space_id}: {e}")
                
                # Delete entity test space if it exists
                if self.entity_test_space_id:
                    try:
                        logger.info(f"🧹 Cleaning up entity test space: {self.entity_test_space_id}")
                        await self.space_manager.delete_space_with_tables(self.entity_test_space_id)
                        logger.info(f"🧹 Deleted entity test space: {self.entity_test_space_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error deleting entity test space: {e}")
            
            # Close VitalGraph app (no close method needed for VitalGraphImpl)
            if self.vitalgraph_app:
                logger.info("🧹 VitalGraph app cleanup completed")
            
            logger.info("🧹 Resources cleaned up successfully")
            
        except Exception as e:
            logger.error(f"❌ Error during resource cleanup: {e}")
    
    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log test result in a consistent format."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}")
        if not success or data:
            logger.info(f"    {message}")
            if data:
                logger.info(f"    Data: {json.dumps(data, indent=2)}")
            
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data or {}
        })
    
    def print_test_summary(self):
        """Print a summary of all test results."""
        logger.info("=" * 60)
        logger.info("📊 Test Results Summary:")
        
        passed = 0
        failed = 0
        
        for result in self.test_results:
            status = "✅ PASSED" if result["success"] else "❌ FAILED"
            logger.info(f"  {result['test_name']}: {status}")
            if result["success"]:
                passed += 1
            else:
                failed += 1
        
        logger.info("-" * 60)
        
        if failed == 0:
            logger.info("🎉 All tests PASSED!")
            return True
        else:
            logger.error("💥 Some tests FAILED!")
            return False


async def run_test_suite(tester_class, test_methods: List[str]):
    """Run a test suite with the given tester class and methods."""
    tester = None
    success = False
    
    try:
        # Initialize tester
        tester = tester_class()
        
        # Setup VitalGraph app
        if not await tester.setup_vitalgraph_app():
            logger.error("❌ Failed to setup VitalGraph app")
            return False
        
        # Run test methods
        for method_name in test_methods:
            if hasattr(tester, method_name):
                method = getattr(tester, method_name)
                logger.info(f"🧪 Running test: {method_name}")
                await method()
            else:
                logger.error(f"❌ Test method not found: {method_name}")
        
        # Print test summary
        success = tester.print_test_summary()
        
    except Exception as e:
        logger.error(f"❌ Test suite failed with exception: {e}")
        success = False
    
    finally:
        # Clean up resources
        if tester:
            await tester.cleanup_resources()
    
    return success