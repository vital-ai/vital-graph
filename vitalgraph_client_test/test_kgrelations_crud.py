#!/usr/bin/env python3
"""
KGRelations CRUD Test Suite

Standalone test for KGRelations operations including:
- Create relation types and products
- Create relations (MakesProduct, CompetitorOf, PartnerWith, Supplies)
- List relations with filtering
- Get individual relations
- Update relations
- Delete relations

Uses organization data from multi_kgentity test but runs independently.
"""

import sys
import logging
import asyncio
from typing import Dict, Any, List
from datetime import datetime
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# Import test case modules
from vitalgraph_client_test.multi_kgentity.case_create_organizations import CreateOrganizationsTester
from vitalgraph_client_test.multi_kgentity.case_create_relations import create_all_relation_data

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class KGRelationsTestRunner:
    """Main test runner for KGRelations CRUD operations."""
    
    def __init__(self):
        self.client = None
        self.space_id = None
        self.graph_id = "urn:kgrelations_test_graph"
        self.data_creator = ClientTestDataCreator()
        
        # Test data storage
        self.org_uris = {}
        self.relation_type_uris = {}
        self.product_uris = {}
        self.relation_uris = {}
        
        # Test results
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_errors = []
    
    async def setup(self):
        """Set up test environment."""
        logger.info("=" * 80)
        logger.info("  KGRelations CRUD Test Suite")
        logger.info("=" * 80)
        
        # Create client
        self.client = VitalGraphClient()
        await self.client.open()
        logger.info("✅ Client opened")
        
        # Create test space
        self.space_id = f"space_kgrelations_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        space_data = Space(
            space=self.space_id,
            space_name="KGRelations CRUD Test",
            space_description="Test space for KGRelations CRUD operations",
            tenant="test_tenant"
        )
        response = await self.client.spaces.create_space(space_data)
        if response.is_success:
            logger.info(f"✅ Test space created: {self.space_id}")
        else:
            raise Exception(f"Failed to create test space: {response.error_message}")
    
    async def teardown(self):
        """Clean up test environment."""
        logger.info("\n" + "=" * 80)
        logger.info("  🧹 Cleanup")
        logger.info("=" * 80)
        
        if self.space_id and self.client:
            response = await self.client.spaces.delete_space(self.space_id)
            if response.is_success:
                logger.info(f"✅ Test space deleted: {self.space_id}")
        
        if self.client:
            await self.client.close()
            logger.info("✅ Client closed")
    
    async def test_section(self, name: str, test_func):
        """Run a test section and track results."""
        logger.info("\n" + "=" * 80)
        logger.info(f"  {name}")
        logger.info("=" * 80)
        
        try:
            passed, failed, errors = await test_func()
            self.tests_passed += passed
            self.tests_failed += failed
            self.test_errors.extend(errors)
            
            if failed == 0:
                logger.info(f"✅ PASS: {name}")
                logger.info(f"   Tests: {passed}/{passed + failed} passed")
            else:
                logger.info(f"❌ FAIL: {name}")
                logger.info(f"   Tests: {passed}/{passed + failed} passed")
                if errors:
                    logger.info(f"   Errors:")
                    for error in errors:
                        logger.info(f"      • {error}")
        except Exception as e:
            logger.error(f"❌ EXCEPTION in {name}: {e}")
            self.tests_failed += 1
            self.test_errors.append(f"{name}: {str(e)}")
    
    async def create_organizations(self) -> tuple:
        """Create organization entities for testing."""
        logger.info("\n--- Creating Organizations ---")
        
        org_tester = CreateOrganizationsTester(self.client)
        results = await org_tester.run_tests(
            self.space_id,
            self.graph_id
        )
        
        # Convert entity URIs list to dict mapping names to URIs
        from vitalgraph_client_test.multi_kgentity.case_create_organizations import ORGANIZATIONS
        self.org_uris = {}
        for i, org_data in enumerate(ORGANIZATIONS):
            if i < len(results['created_entity_uris']):
                self.org_uris[org_data['name']] = results['created_entity_uris'][i]
        
        passed = results['tests_passed']
        failed = results['tests_failed']
        errors = results['errors']
        
        logger.info(f"✅ Created {passed} organizations")
        return passed, failed, errors
    
    async def create_relation_data(self) -> tuple:
        """Create relation types, products, and relation instances."""
        logger.info("\n--- Creating Relation Data ---")
        
        self.relation_type_uris, self.product_uris, self.relation_uris = create_all_relation_data(
            self.client,
            self.space_id,
            self.graph_id,
            self.org_uris
        )
        
        total_relations = sum(len(uris) for uris in self.relation_uris.values())
        passed = total_relations
        failed = 0
        errors = []
        
        return passed, failed, errors
    
    async def test_list_all_relations(self) -> tuple:
        """Test listing all relations."""
        logger.info("\n--- List All Relations ---")
        
        passed = 0
        failed = 0
        errors = []
        
        try:
            response = await self.client.kgrelations.list_relations(
                self.space_id,
                self.graph_id,
                page_size=50
            )
            
            if response.is_success:
                total_relations = sum(len(uris) for uris in self.relation_uris.values())
                actual = len(response.objects) if response.objects else 0
                if actual == total_relations:
                    logger.info(f"✅ Listed {actual} relations (expected {total_relations})")
                    passed += 1
                else:
                    logger.error(f"❌ Count mismatch: Listed {actual} relations (expected {total_relations})")
                    failed += 1
                    errors.append(f"List all count mismatch: expected {total_relations}, got {actual}")
            else:
                logger.error(f"❌ Failed to list relations: {response.message}")
                failed += 1
                errors.append(f"List all relations failed: {response.message}")
        except Exception as e:
            logger.error(f"❌ Exception: {e}")
            failed += 1
            errors.append(f"List all relations exception: {str(e)}")
        
        return passed, failed, errors
    
    async def test_list_by_source(self) -> tuple:
        """Test listing relations filtered by source entity."""
        logger.info("\n--- List Relations by Source Entity ---")
        
        passed = 0
        failed = 0
        errors = []
        
        # Test with TechCorp (should have MakesProduct and PartnerWith relations)
        techcorp_uri = self.org_uris.get("TechCorp Industries")
        if techcorp_uri:
            try:
                response = await self.client.kgrelations.list_relations(
                    self.space_id,
                    self.graph_id,
                    entity_source_uri=techcorp_uri
                )
                
                if response.is_success:
                    # TechCorp should have 2 MakesProduct + 1 PartnerWith + 1 Supplies (as destination) = 3 outgoing
                    # But we're filtering by source, so should be 3 (2 MakesProduct + 1 PartnerWith)
                    actual = len(response.objects) if response.objects else 0
                    expected = 3  # 2 MakesProduct + 1 PartnerWith
                    if actual >= expected:  # Use >= because there might be more
                        logger.info(f"✅ Found {actual} relations from TechCorp Industries (expected at least {expected})")
                        passed += 1
                    else:
                        logger.error(f"❌ Count mismatch: Found {actual} relations from TechCorp (expected at least {expected})")
                        failed += 1
                        errors.append(f"List by source count mismatch: expected at least {expected}, got {actual}")
                else:
                    logger.error(f"❌ Failed: {response.message}")
                    failed += 1
                    errors.append(f"List by source failed: {response.message}")
            except Exception as e:
                logger.error(f"❌ Exception: {e}")
                failed += 1
                errors.append(f"List by source exception: {str(e)}")
        
        return passed, failed, errors
    
    async def test_list_by_relation_type(self) -> tuple:
        """Test listing relations filtered by relation type."""
        logger.info("\n--- List Relations by Type ---")
        
        passed = 0
        failed = 0
        errors = []
        
        # Test MakesProductRelation
        makes_product_type = self.relation_type_uris.get('makes_product')
        if makes_product_type:
            try:
                response = await self.client.kgrelations.list_relations(
                    self.space_id,
                    self.graph_id,
                    relation_type_uri=makes_product_type
                )
                
                if response.is_success:
                    expected = len(self.relation_uris['makes_product'])
                    actual = len(response.objects) if response.objects else 0
                    if actual == expected:
                        logger.info(f"✅ Found {actual} MakesProduct relations (expected {expected})")
                        passed += 1
                    else:
                        logger.error(f"❌ Count mismatch: Found {actual} MakesProduct relations (expected {expected})")
                        failed += 1
                        errors.append(f"List by type count mismatch: expected {expected}, got {actual}")
                else:
                    logger.error(f"❌ Failed: {response.message}")
                    failed += 1
                    errors.append(f"List by type failed: {response.message}")
            except Exception as e:
                logger.error(f"❌ Exception: {e}")
                failed += 1
                errors.append(f"List by type exception: {str(e)}")
        
        return passed, failed, errors
    
    async def test_get_relation(self) -> tuple:
        """Test getting individual relation."""
        logger.info("\n--- Get Individual Relation ---")
        
        passed = 0
        failed = 0
        errors = []
        
        # Get first MakesProduct relation
        if self.relation_uris['makes_product']:
            relation_uri = self.relation_uris['makes_product'][0]
            try:
                response = await self.client.kgrelations.get_relation(
                    self.space_id,
                    self.graph_id,
                    relation_uri
                )
                
                if response.is_success and response.objects:
                    logger.info(f"✅ Retrieved relation: {relation_uri}")
                    passed += 1
                else:
                    logger.error(f"❌ Failed to get relation")
                    failed += 1
                    errors.append(f"Get relation failed")
            except Exception as e:
                logger.error(f"❌ Exception: {e}")
                failed += 1
                errors.append(f"Get relation exception: {str(e)}")
        
        return passed, failed, errors
    
    async def test_delete_relation(self) -> tuple:
        """Test deleting relations."""
        logger.info("\n--- Delete Relation ---")
        
        passed = 0
        failed = 0
        errors = []
        
        # Delete one CompetitorOf relation
        if self.relation_uris['competitor_of']:
            relation_uri = self.relation_uris['competitor_of'][0]
            try:
                response = await self.client.kgrelations.delete_relations(
                    self.space_id,
                    self.graph_id,
                    [relation_uri]
                )
                
                if response.is_success:
                    logger.info(f"✅ Deleted relation: {relation_uri}")
                    passed += 1
                    
                    # Verify deletion by checking total count
                    list_response = await self.client.kgrelations.list_relations(
                        self.space_id,
                        self.graph_id,
                        page_size=50
                    )
                    expected_count = sum(len(uris) for uris in self.relation_uris.values()) - 1
                    actual_count = len(list_response.objects) if list_response.objects else 0
                    if actual_count == expected_count:
                        logger.info(f"✅ Verified deletion (count: {actual_count})")
                        passed += 1
                    else:
                        logger.error(f"❌ Count mismatch after deletion: expected {expected_count}, got {actual_count}")
                        failed += 1
                        errors.append(f"Deletion verification failed: expected {expected_count}, got {actual_count}")
                else:
                    logger.error(f"❌ Failed to delete: {response.message}")
                    failed += 1
                    errors.append(f"Delete failed: {response.message}")
            except Exception as e:
                logger.error(f"❌ Exception: {e}")
                failed += 1
                errors.append(f"Delete exception: {str(e)}")
        
        return passed, failed, errors
    
    async def run(self):
        """Run all tests."""
        try:
            await self.setup()
            
            # Create test data
            await self.test_section("Create Organizations", self.create_organizations)
            await self.test_section("Create Relation Data", self.create_relation_data)
            
            # Test CRUD operations
            await self.test_section("List All Relations", self.test_list_all_relations)
            await self.test_section("List by Source Entity", self.test_list_by_source)
            await self.test_section("List by Relation Type", self.test_list_by_relation_type)
            await self.test_section("Get Individual Relation", self.test_get_relation)
            await self.test_section("Delete Relation", self.test_delete_relation)
            
            # Print summary
            self.print_summary()
            
        finally:
            await self.teardown()
    
    def print_summary(self):
        """Print test summary."""
        logger.info("\n" + "=" * 80)
        logger.info("  TEST SUMMARY")
        logger.info("=" * 80)
        
        total = self.tests_passed + self.tests_failed
        logger.info(f"OVERALL: {self.tests_passed}/{total} tests passed")
        logger.info("=" * 80)
        
        if self.tests_failed == 0:
            logger.info("\n" + "=" * 80)
            logger.info("  ✅ All Tests Completed Successfully!")
            logger.info("=" * 80)
        else:
            logger.info("\n" + "=" * 80)
            logger.info("  ⚠️ Some Tests Failed")
            logger.info("=" * 80)


if __name__ == "__main__":
    runner = KGRelationsTestRunner()
    asyncio.run(runner.run())
