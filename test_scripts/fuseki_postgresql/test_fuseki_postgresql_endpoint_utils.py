#!/usr/bin/env python3
"""
Common utilities for Fuseki+PostgreSQL endpoint testing.

This module provides shared functionality for testing endpoints with the Fuseki+PostgreSQL
hybrid backend including:
- VitalGraph app setup with hybrid backend configuration
- Space management operations with dual-write validation
- Test data creation and cleanup
- SPARQL UPDATE validation and consistency checking
- Common test patterns and assertions for hybrid backend
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
from vitalgraph.db.backend_config import BackendType
from vitalgraph.db.fuseki_postgresql.fuseki_postgresql_space_impl import FusekiPostgreSQLSpaceImpl
from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
from vitalgraph.endpoint.kgtypes_endpoint import KGTypesEndpoint
from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FusekiPostgreSQLEndpointTester:
    """Base class for Fuseki+PostgreSQL endpoint testing with common functionality."""
    
    def __init__(self, fuseki_url: str = "http://localhost:3030", postgresql_config: Dict = None):
        self.fuseki_url = fuseki_url
        self.postgresql_config = postgresql_config or {
            "host": "localhost",
            "port": 5432,
            "database": "fuseki_sql_graph",
            "username": "postgres",
            "password": ""
        }
        
        # Backend and endpoints
        self.hybrid_backend = None
        self.space_manager = None
        self.kgentities_endpoint = None
        self.kgframes_endpoint = None
        self.kgtypes_endpoint = None
        
        # Test tracking
        self.test_results = []
        self.cached_spaces = []
        self.created_entity_uris = []
        
        # Test data
        self.test_entity_graphs = []
        self.entity_test_space_id = None
        
        # Prefixes for SPARQL queries
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
    
    async def setup_hybrid_backend(self) -> bool:
        """Setup Fuseki+PostgreSQL hybrid backend for testing."""
        try:
            logger.info("🔧 Setting up Fuseki+PostgreSQL hybrid backend")
            
            # Create hybrid backend configuration
            fuseki_config = {
                "server_url": self.fuseki_url,
                "admin_user": "admin",
                "admin_password": "admin",
                "dataset_prefix": "vitalgraph_space_"
            }
            
            # Initialize hybrid backend
            self.hybrid_backend = FusekiPostgreSQLSpaceImpl(
                fuseki_config=fuseki_config,
                postgresql_config=self.postgresql_config
            )
            
            # Test connectivity to both systems
            await self._validate_hybrid_connectivity()
            
            # Create real space manager with hybrid backend
            from vitalgraph.space.space_manager import SpaceManager
            self.space_manager = SpaceManager(space_backend=self.hybrid_backend)
            
            # Create mock auth dependency for testing
            def mock_auth_dependency():
                return {"username": "test_user", "user_id": "test_user_123"}
            
            # Initialize endpoints with hybrid backend
            self.kgentities_endpoint = KGEntitiesEndpoint(
                space_manager=self.space_manager,
                auth_dependency=mock_auth_dependency
            )
            
            self.kgframes_endpoint = KGFramesEndpoint(
                space_manager=self.space_manager,
                auth_dependency=mock_auth_dependency
            )
            
            # Set endpoint for backward compatibility with integration tests
            if hasattr(self, 'endpoint'):
                self.endpoint = self.kgframes_endpoint
            
            self.kgtypes_endpoint = KGTypesEndpoint(
                space_manager=self.space_manager,
                auth_dependency=mock_auth_dependency
            )
            
            logger.info("✅ Fuseki+PostgreSQL hybrid backend setup completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup hybrid backend: {e}")
            return False
    
    async def _validate_hybrid_connectivity(self):
        """Validate connectivity to both Fuseki and PostgreSQL."""
        try:
            # Connect to hybrid backend (this will connect both Fuseki and PostgreSQL)
            connected = await self.hybrid_backend.connect()
            if not connected:
                raise RuntimeError("Hybrid backend connection failed")
            
            # Verify both systems are connected
            if not await self.hybrid_backend.is_connected():
                raise RuntimeError("Hybrid backend connectivity validation failed")
            
            logger.info("✅ Hybrid backend connectivity validated")
            
        except Exception as e:
            logger.error(f"❌ Hybrid backend connectivity validation failed: {e}")
            raise
    
    async def create_test_space(self, space_name_prefix: str = "test_space") -> Optional[str]:
        """Create a test space using hybrid backend."""
        try:
            test_space_id = f"{space_name_prefix}_{uuid.uuid4().hex[:8]}"
            
            # Create space using hybrid backend (creates both Fuseki dataset and PostgreSQL tables)
            success = await self.hybrid_backend.create_space_storage(test_space_id)
            
            if success:
                self.cached_spaces.append(test_space_id)
                logger.info(f"✅ Created test space with hybrid backend: {test_space_id}")
                return test_space_id
            else:
                logger.error(f"❌ Failed to create test space: {test_space_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Exception creating test space: {e}")
            return None
    
    async def test_sparql_update_operation(self, space_id: str, sparql_update: str) -> Dict[str, Any]:
        """
        Test SPARQL UPDATE operation and validate dual-write consistency.
        
        Returns:
            Dictionary with test results including:
            - sparql_success: Whether SPARQL UPDATE succeeded
            - fuseki_count: Number of triples in Fuseki after operation
            - postgresql_count: Number of triples in PostgreSQL after operation
            - consistency_verified: Whether dual-write consistency is maintained
        """
        try:
            logger.info(f"🧪 Testing SPARQL UPDATE operation in space: {space_id}")
            
            # Execute SPARQL UPDATE via hybrid backend
            sparql_success = await self.hybrid_backend.execute_sparql_update(space_id, sparql_update)
            
            if not sparql_success:
                return {
                    "sparql_success": False,
                    "error": "SPARQL UPDATE execution failed"
                }
            
            # Validate dual-write consistency
            consistency_result = await self._validate_dual_write_consistency(space_id)
            
            return {
                "sparql_success": True,
                "fuseki_count": consistency_result.get("fuseki_count", 0),
                "postgresql_count": consistency_result.get("postgresql_count", 0),
                "consistency_verified": consistency_result.get("consistent", False),
                "consistency_details": consistency_result
            }
            
        except Exception as e:
            logger.error(f"❌ Exception testing SPARQL UPDATE: {e}")
            return {
                "sparql_success": False,
                "error": str(e)
            }
    
    async def _validate_dual_write_consistency(self, space_id: str) -> Dict[str, Any]:
        """Validate that Fuseki and PostgreSQL contain consistent data."""
        try:
            # Query Fuseki for triple count
            fuseki_query = """
            SELECT (COUNT(*) as ?count) WHERE {
                ?s ?p ?o
            }
            """
            fuseki_results = await self.hybrid_backend.fuseki_manager.query_dataset(
                f"vitalgraph_space_{space_id}", fuseki_query
            )
            fuseki_count = int(fuseki_results[0]['count']['value']) if fuseki_results else 0
            
            # Query PostgreSQL for triple count
            pg_count_query = f"SELECT COUNT(*) FROM {space_id}_rdf_quad"
            pg_results = await self.hybrid_backend.postgresql_impl.execute_query(pg_count_query)
            postgresql_count = pg_results[0]['count'] if pg_results else 0
            
            consistent = fuseki_count == postgresql_count
            
            logger.info(f"📊 Consistency check - Fuseki: {fuseki_count}, PostgreSQL: {postgresql_count}, Consistent: {consistent}")
            
            return {
                "fuseki_count": fuseki_count,
                "postgresql_count": postgresql_count,
                "consistent": consistent,
                "difference": abs(fuseki_count - postgresql_count)
            }
            
        except Exception as e:
            logger.error(f"❌ Exception validating dual-write consistency: {e}")
            return {
                "fuseki_count": 0,
                "postgresql_count": 0,
                "consistent": False,
                "error": str(e)
            }
    
    async def create_entity_graphs_via_sparql(self, space_id: str) -> bool:
        """Create test entity graphs using SPARQL UPDATE operations."""
        try:
            logger.info(f"🔍 Creating entity graphs via SPARQL UPDATE in space: {space_id}")
            
            # Create test entity graphs using VitalSigns
            entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=True)
            
            if not entity_graphs:
                logger.error("❌ Failed to create entity graphs from test data")
                return False
            
            logger.info(f"📋 Created {len(entity_graphs)} entity graphs from test data")
            
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            self.created_entity_uris = []
            
            # Create each entity graph using SPARQL INSERT
            for i, entity_graph in enumerate(entity_graphs):
                logger.info(f"🔍 Creating entity graph {i+1}/{len(entity_graphs)} with {len(entity_graph)} objects")
                
                # Convert VitalSigns objects to SPARQL INSERT
                sparql_insert = self._generate_insert_sparql_from_objects(entity_graph, space_id)
                
                # Execute SPARQL UPDATE
                test_result = await self.test_sparql_update_operation(space_id, sparql_insert)
                
                if test_result["sparql_success"] and test_result["consistency_verified"]:
                    # Extract entity URI from the first object
                    entity_uri = str(entity_graph[0].URI)
                    self.created_entity_uris.append(entity_uri)
                    logger.info(f"✅ Created entity graph {i+1} via SPARQL: {entity_uri}")
                    logger.info(f"📊 Dual-write consistency: Fuseki={test_result['fuseki_count']}, PostgreSQL={test_result['postgresql_count']}")
                else:
                    logger.error(f"❌ Failed to create entity graph {i+1} via SPARQL")
                    return False
            
            logger.info(f"✅ Created {len(entity_graphs)} entity graphs via SPARQL UPDATE")
            return True
            
        except Exception as e:
            logger.error(f"❌ Exception creating entity graphs via SPARQL: {e}")
            return False
    
    def _generate_insert_sparql_from_objects(self, objects: List, space_id: str) -> str:
        """Generate SPARQL INSERT DATA statement from VitalSigns objects."""
        graph_uri = f"http://vital.ai/graph/{space_id}/entities"
        
        sparql_insert = f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        INSERT DATA {{
            GRAPH <{graph_uri}> {{
        """
        
        # Convert each object to triples
        for obj in objects:
            triples = obj.to_triples()
            for triple in triples:
                subject, predicate, object_val = triple
                formatted_object = self._format_sparql_object(object_val)
                sparql_insert += f"        <{subject}> <{predicate}> {formatted_object} .\n"
        
        sparql_insert += """
            }
        }
        """
        
        return sparql_insert
    
    def _format_sparql_object(self, obj) -> str:
        """Format an object for SPARQL (URI or literal)."""
        if isinstance(obj, str):
            if obj.startswith("http://") or obj.startswith("https://") or obj.startswith("urn:"):
                return f"<{obj}>"
            else:
                return f'"{obj}"'
        else:
            return f'"{str(obj)}"'
    
    async def cleanup_resources(self):
        """Clean up all test resources."""
        try:
            logger.info("🧹 Starting hybrid backend resource cleanup")
            
            # Clean up cached spaces
            if self.cached_spaces:
                logger.info(f"🧹 Found {len(self.cached_spaces)} cached spaces to clean up")
                
                for space_id in self.cached_spaces:
                    try:
                        logger.info(f"🧹 Cleaning up hybrid space: {space_id}")
                        
                        # Delete space using hybrid backend (removes both Fuseki dataset and PostgreSQL tables)
                        await self.hybrid_backend.delete_space_storage(space_id)
                        logger.info(f"🧹 Deleted hybrid space: {space_id}")
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Error deleting hybrid space {space_id}: {e}")
            
            # Close hybrid backend connections
            if self.hybrid_backend:
                try:
                    # Disconnect the entire hybrid backend (this will close both Fuseki and PostgreSQL)
                    await self.hybrid_backend.disconnect()
                    logger.info("🧹 Disconnected hybrid backend")
                    
                    # Give a small delay to ensure all async cleanup operations complete
                    import asyncio
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.warning(f"⚠️ Error disconnecting hybrid backend: {e}")
            
            # Clean up all tracked resources globally with aggressive cleanup
            try:
                from vitalgraph.utils.resource_manager import cleanup_resources
                await cleanup_resources()
                logger.info("🧹 Global resource cleanup completed")
                
                # Additional delay to ensure all async operations complete
                import asyncio
                await asyncio.sleep(0.3)
                
                # Force garbage collection to help with cleanup
                import gc
                gc.collect()
                
            except Exception as e:
                logger.warning(f"⚠️ Error during global resource cleanup: {e}")
            
            logger.info("🧹 Hybrid backend resources cleaned up successfully")
            
        except Exception as e:
            logger.error(f"❌ Error during hybrid backend resource cleanup: {e}")
    
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
        logger.info("📊 Fuseki+PostgreSQL Test Results Summary:")
        
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
            logger.info("🎉 All Fuseki+PostgreSQL tests PASSED!")
            return True
        else:
            logger.error("💥 Some Fuseki+PostgreSQL tests FAILED!")
            return False


# Removed MockSpaceManagerWithHybridBackend and MockSpaceRecord - now using real SpaceManager


async def run_hybrid_test_suite(tester_class, test_methods: List[str]):
    """Run a test suite with the given tester class and methods for hybrid backend."""
    tester = None
    success = False
    
    try:
        # Initialize tester
        tester = tester_class()
        
        # Setup hybrid backend
        if not await tester.setup_hybrid_backend():
            logger.error("❌ Failed to setup Fuseki+PostgreSQL hybrid backend")
            return False
        
        # Run test methods
        for method_name in test_methods:
            if hasattr(tester, method_name):
                method = getattr(tester, method_name)
                logger.info(f"🧪 Running hybrid backend test: {method_name}")
                await method()
            else:
                logger.error(f"❌ Test method not found: {method_name}")
        
        # Print test summary
        success = tester.print_test_summary()
        
    except Exception as e:
        logger.error(f"❌ Hybrid backend test suite failed with exception: {e}")
        success = False
    
    finally:
        # Clean up resources
        if tester:
            await tester.cleanup_resources()
    
    return success
