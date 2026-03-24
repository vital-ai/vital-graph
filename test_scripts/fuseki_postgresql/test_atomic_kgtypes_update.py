#!/usr/bin/env python3
"""
Test module for atomic KGTypes UPDATE functionality using the new KGTypesUpdateProcessor.

This module validates the new KGTypes UPDATE operations that use the validated
update_quads function for true atomicity and consistency.

Location: /Users/hadfield/Local/vital-git/vital-graph/test_scripts/fuseki_postgresql/test_atomic_kgtypes_update.py
"""

import sys
import os
import logging
import asyncio
import traceback
from typing import List, Dict, Any
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType

# VitalGraph imports
from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
from vitalgraph.kg_impl.kgtypes_update_impl import KGTypesUpdateProcessor
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AtomicKGTypesUpdateTestSuite:
    """Test suite for atomic KGTypes UPDATE functionality."""
    
    def __init__(self):
        self.tester = None
        self.backend_adapter = None
        self.space_id = None
        self.graph_id = "http://vital.ai/graph/test_atomic_kgtypes_update"
        self.processor = KGTypesUpdateProcessor()

    async def setup_test_environment(self):
        """Set up test environment with hybrid backend."""
        try:
            logger.info("🔧 Setting up atomic KGTypes UPDATE test environment...")
            
            # Initialize tester and backend
            self.tester = FusekiPostgreSQLEndpointTester()
            await self.tester.setup_hybrid_backend()
            
            # Create test space
            self.space_id = await self.tester.create_test_space("atomic_kgtypes_update_test")
            
            # Create backend adapter
            self.backend_adapter = create_backend_adapter(self.tester.hybrid_backend)
            
            logger.info("✅ Atomic KGTypes UPDATE test environment setup complete")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup test environment: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_kgtype_update_basic(self) -> bool:
        """Test basic atomic KGType UPDATE operation."""
        try:
            logger.info("🧪 Testing basic atomic KGType UPDATE...")
            
            # Step 1: Create initial KGType
            initial_type = KGType()
            initial_type.URI = "http://vital.ai/test/kgtype_update_basic"
            initial_type.name = "Initial Type"
            
            # Store initial type
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, [initial_type]
            )
            
            if not store_result.success:
                raise Exception(f"Failed to store initial KGType: {store_result.message}")
            
            logger.info("✅ Initial KGType created successfully")
            
            # Step 2: Update KGType with new data using atomic UPDATE
            updated_type = KGType()
            updated_type.URI = initial_type.URI  # Same URI for update
            updated_type.name = "Updated Type"
            
            # Execute atomic UPDATE
            success = await self.processor.update_kgtype(
                self.backend_adapter, self.space_id, self.graph_id,
                str(initial_type.URI), [updated_type]
            )
            
            if not success:
                raise Exception("Atomic KGType UPDATE failed")
            
            logger.info("✅ Atomic KGType UPDATE completed successfully")
            
            # Step 3: Verify update results by checking graph state
            subjects_query = f"""
            SELECT DISTINCT ?s WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?s ?p ?o .
                }}
            }}
            """
            subjects_result = await self.backend_adapter.execute_sparql_query(self.space_id, subjects_query)
            
            # Extract subject URIs from results
            subject_uris = []
            if isinstance(subjects_result, list):
                for result in subjects_result:
                    if isinstance(result, dict) and 's' in result:
                        uri = result['s'].get('value', '') if isinstance(result['s'], dict) else str(result['s'])
                        if uri:
                            subject_uris.append(uri)
            
            # Check that the type still exists
            type_exists = str(updated_type.URI) in subject_uris
            
            # Verify the name was updated by querying the specific property
            name_query = f"""
            SELECT ?name WHERE {{
                GRAPH <{self.graph_id}> {{
                    <{updated_type.URI}> <http://vital.ai/ontology/vital-core#hasName> ?name .
                }}
            }}
            """
            name_result = await self.backend_adapter.execute_sparql_query(self.space_id, name_query)
            
            updated_name = None
            if isinstance(name_result, list) and len(name_result) > 0:
                name_binding = name_result[0]
                if isinstance(name_binding, dict) and 'name' in name_binding:
                    updated_name = name_binding['name'].get('value', '') if isinstance(name_binding['name'], dict) else str(name_binding['name'])
            
            logger.info(f"🔍 Atomic UPDATE validation:")
            logger.info(f"  - Type exists: {type_exists}")
            logger.info(f"  - Updated name: {updated_name}")
            
            if not type_exists:
                raise Exception("KGType not found after UPDATE")
            
            if updated_name != "Updated Type":
                raise Exception(f"Name not updated correctly. Expected 'Updated Type', got '{updated_name}'")
            
            logger.info("✅ Basic atomic KGType UPDATE test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Basic atomic KGType UPDATE test failed: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_kgtype_update_with_validation(self) -> bool:
        """Test atomic KGType UPDATE with existence validation."""
        try:
            logger.info("🧪 Testing atomic KGType UPDATE with validation...")
            
            # Step 1: Create initial KGType
            kgtype = KGType()
            kgtype.URI = "http://vital.ai/test/kgtype_validation"
            kgtype.name = "Type for Validation"
            
            # Store initial type
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, [kgtype]
            )
            
            if not store_result.success:
                raise Exception("Failed to store initial KGType")
            
            # Step 2: Verify type exists before update
            exists = await self.processor.kgtype_exists(
                self.backend_adapter, self.space_id, self.graph_id, str(kgtype.URI)
            )
            
            if not exists:
                raise Exception("KGType existence validation failed")
            
            # Step 3: Update type
            updated_kgtype = KGType()
            updated_kgtype.URI = kgtype.URI
            updated_kgtype.name = "Updated Type with Validation"
            
            success = await self.processor.update_kgtype(
                self.backend_adapter, self.space_id, self.graph_id,
                str(kgtype.URI), [updated_kgtype]
            )
            
            if not success:
                raise Exception("KGType update failed")
            
            logger.info("✅ Atomic KGType UPDATE with validation test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic KGType UPDATE with validation test failed: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_kgtype_update_nonexistent(self) -> bool:
        """Test atomic KGType UPDATE on non-existent type."""
        try:
            logger.info("🧪 Testing atomic KGType UPDATE on non-existent type...")
            
            # Try to update non-existent type
            nonexistent_type = KGType()
            nonexistent_type.URI = "http://vital.ai/test/kgtype_nonexistent"
            nonexistent_type.name = "Non-existent Type"
            
            success = await self.processor.update_kgtype(
                self.backend_adapter, self.space_id, self.graph_id,
                str(nonexistent_type.URI), [nonexistent_type]
            )
            
            # Should still succeed (atomic update will just insert if nothing to delete)
            if not success:
                raise Exception("Update of non-existent KGType should succeed")
            
            logger.info("✅ Atomic KGType UPDATE non-existent test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic KGType UPDATE non-existent test failed: {e}")
            traceback.print_exc()
            return False

    async def test_atomic_kgtype_batch_update(self) -> bool:
        """Test atomic batch KGType UPDATE operation."""
        try:
            logger.info("🧪 Testing atomic batch KGType UPDATE...")
            
            # Step 1: Create initial KGTypes
            type1 = KGType()
            type1.URI = "http://vital.ai/test/kgtype_batch_1"
            type1.name = "Initial Type 1"
            
            type2 = KGType()
            type2.URI = "http://vital.ai/test/kgtype_batch_2"
            type2.name = "Initial Type 2"
            
            # Store initial types
            store_result = await self.backend_adapter.store_objects(
                self.space_id, self.graph_id, [type1, type2]
            )
            
            if not store_result.success:
                raise Exception("Failed to store initial KGTypes")
            
            logger.info("✅ Initial KGTypes created successfully")
            
            # Step 2: Prepare batch updates
            updated_type1 = KGType()
            updated_type1.URI = type1.URI
            updated_type1.name = "Updated Type 1"
            
            updated_type2 = KGType()
            updated_type2.URI = type2.URI
            updated_type2.name = "Updated Type 2"
            
            batch_updates = {
                str(type1.URI): [updated_type1],
                str(type2.URI): [updated_type2]
            }
            
            # Step 3: Execute batch UPDATE
            updated_uris = await self.processor.update_kgtypes_batch(
                self.backend_adapter, self.space_id, self.graph_id, batch_updates
            )
            
            if len(updated_uris) != 2:
                raise Exception(f"Expected 2 updated types, got {len(updated_uris)}")
            
            logger.info("✅ Atomic batch KGType UPDATE test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic batch KGType UPDATE test failed: {e}")
            traceback.print_exc()
            return False

    async def cleanup_test_environment(self):
        """Clean up test environment."""
        try:
            if self.tester:
                await self.tester.cleanup_resources()
            logger.info("✅ Test environment cleanup completed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")


async def run_atomic_kgtypes_update_tests():
    """Run all atomic KGTypes UPDATE tests."""
    logger.info("🎯 ATOMIC KGTYPES UPDATE TEST SUITE")
    logger.info("=" * 60)
    
    test_suite = AtomicKGTypesUpdateTestSuite()
    
    try:
        # Setup test environment
        if not await test_suite.setup_test_environment():
            logger.error("💥 FAILED TO SETUP TEST ENVIRONMENT!")
            return False
        
        # Run tests
        tests = [
            ("Basic Atomic KGType UPDATE", test_suite.test_atomic_kgtype_update_basic),
            ("Atomic KGType UPDATE with Validation", test_suite.test_atomic_kgtype_update_with_validation),
            ("Atomic KGType UPDATE Non-existent", test_suite.test_atomic_kgtype_update_nonexistent),
            ("Atomic Batch KGType UPDATE", test_suite.test_atomic_kgtype_batch_update),
        ]
        
        passed = 0
        failed = 0
        
        for test_name, test_func in tests:
            logger.info("=" * 60)
            logger.info(f"🧪 Running test: {test_name}")
            logger.info("=" * 60)
            
            if await test_func():
                logger.info(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                logger.error(f"❌ {test_name}: FAILED")
                failed += 1
        
        # Summary
        logger.info("=" * 60)
        logger.info("🎯 ATOMIC KGTYPES UPDATE TEST SUITE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"✅ Passed: {passed}/{passed + failed}")
        logger.info(f"❌ Failed: {failed}/{passed + failed}")
        logger.info(f"📊 Success Rate: {(passed / (passed + failed) * 100):.1f}%")
        
        if failed == 0:
            logger.info("🎉 ALL ATOMIC KGTYPES UPDATE TESTS PASSED!")
            return True
        else:
            logger.error("💥 SOME ATOMIC KGTYPES UPDATE TESTS FAILED!")
            return False
            
    finally:
        await test_suite.cleanup_test_environment()


if __name__ == "__main__":
    asyncio.run(run_atomic_kgtypes_update_tests())
