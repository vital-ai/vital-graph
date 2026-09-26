"""
Space Creation Test Case

Tests creation of spaces in the FUSEKI_POSTGRESQL hybrid backend including:
- Dual-write space storage creation
- Fuseki dataset creation and verification
- PostgreSQL backup tables creation and verification
- Admin dataset space registration
"""

import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class SpaceCreationTester:
    """
    Test case for space creation functionality.
    
    Tests proper creation of spaces with dual-write coordination.
    """
    
    def __init__(self, components: Dict[str, Any], test_space_id: str):
        """
        Initialize space creation tester.
        
        Args:
            components: Dictionary of initialized backend components
            test_space_id: ID of the test space to create
        """
        self.components = components
        self.test_space_id = test_space_id
        
        # Extract components for easier access
        self.dual_coordinator = components.get('dual_coordinator')
        self.fuseki_manager = components.get('fuseki_manager')
        self.admin_dataset = components.get('admin_dataset')
        self.postgresql_impl = components.get('postgresql_impl')
    
    async def test_space_creation(self) -> Dict[str, Any]:
        """
        Test creation of a new space with dual-write coordination.
        
        Returns:
            Dictionary with test results
        """
        logger.info(f"🏗️ Testing space creation: {self.test_space_id}")
        
        results = {
            'success': True,
            'total_tests': 4,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': [],
            'space_created': False
        }
        
        try:
            # Test 1: Dual-Write Space Storage Creation
            logger.info("🔍 Test 1: Dual-Write Space Storage Creation")
            storage_success = await self._test_dual_write_storage_creation()
            
            if storage_success:
                results['passed_tests'] += 1
                results['space_created'] = True
                results['test_details'].append({
                    'test': 'Dual-Write Storage Creation',
                    'status': 'PASSED',
                    'message': 'Space storage created in both systems'
                })
                logger.info("✅ Dual-Write Storage Creation: PASSED")
            else:
                results['failed_tests'].append("Dual-Write Storage Creation failed")
                results['test_details'].append({
                    'test': 'Dual-Write Storage Creation',
                    'status': 'FAILED',
                    'message': 'Failed to create space storage'
                })
                logger.error("❌ Dual-Write Storage Creation: FAILED")
            
            # Test 2: Fuseki Dataset Verification
            logger.info("🔍 Test 2: Fuseki Dataset Verification")
            fuseki_verification_success = await self._test_fuseki_dataset_verification()
            
            if fuseki_verification_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Fuseki Dataset Verification',
                    'status': 'PASSED',
                    'message': 'Fuseki dataset exists and accessible'
                })
                logger.info("✅ Fuseki Dataset Verification: PASSED")
            else:
                results['failed_tests'].append("Fuseki Dataset Verification failed")
                results['test_details'].append({
                    'test': 'Fuseki Dataset Verification',
                    'status': 'FAILED',
                    'message': 'Fuseki dataset not found or not accessible'
                })
                logger.error("❌ Fuseki Dataset Verification: FAILED")
            
            # Test 3: PostgreSQL Tables Verification
            logger.info("🔍 Test 3: PostgreSQL Tables Verification")
            postgresql_verification_success = await self._test_postgresql_tables_verification()
            
            if postgresql_verification_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'PostgreSQL Tables Verification',
                    'status': 'PASSED',
                    'message': 'PostgreSQL backup tables exist'
                })
                logger.info("✅ PostgreSQL Tables Verification: PASSED")
            else:
                results['failed_tests'].append("PostgreSQL Tables Verification failed")
                results['test_details'].append({
                    'test': 'PostgreSQL Tables Verification',
                    'status': 'FAILED',
                    'message': 'PostgreSQL backup tables not found'
                })
                logger.error("❌ PostgreSQL Tables Verification: FAILED")
            
            # Test 4: Admin Dataset Registration
            logger.info("🔍 Test 4: Admin Dataset Registration")
            admin_registration_success = await self._test_admin_dataset_registration()
            
            if admin_registration_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Admin Dataset Registration',
                    'status': 'PASSED',
                    'message': 'Space registered in admin dataset'
                })
                logger.info("✅ Admin Dataset Registration: PASSED")
            else:
                results['failed_tests'].append("Admin Dataset Registration failed")
                results['test_details'].append({
                    'test': 'Admin Dataset Registration',
                    'status': 'FAILED',
                    'message': 'Failed to register space in admin dataset'
                })
                logger.error("❌ Admin Dataset Registration: FAILED")
            
            # Update overall success
            results['success'] = len(results['failed_tests']) == 0
            
        except Exception as e:
            logger.error(f"❌ Space creation testing failed: {e}")
            results['success'] = False
            results['failed_tests'].append(f"Test execution error: {str(e)}")
        
        return results
    
    async def _test_dual_write_storage_creation(self) -> bool:
        """Test dual-write space storage creation."""
        try:
            if not self.dual_coordinator:
                logger.error("   Dual-write coordinator not available")
                return False
            
            # Create space using dual-write coordinator
            success = await self.dual_coordinator.create_space_storage(self.test_space_id)
            
            if success:
                logger.info(f"   Space storage created successfully: {self.test_space_id}")
                return True
            else:
                logger.error(f"   Space storage creation failed: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"   Dual-write storage creation failed: {e}")
            return False
    
    async def _test_fuseki_dataset_verification(self) -> bool:
        """Test Fuseki dataset verification."""
        try:
            if not self.fuseki_manager:
                logger.error("   Fuseki manager not available")
                return False
            
            # Verify Fuseki dataset exists
            dataset_exists = await self.fuseki_manager.dataset_exists(self.test_space_id)
            
            if dataset_exists:
                logger.info(f"   Fuseki dataset verified: {self.test_space_id}")
                return True
            else:
                logger.error(f"   Fuseki dataset not found: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"   Fuseki dataset verification failed: {e}")
            return False
    
    async def _test_postgresql_tables_verification(self) -> bool:
        """Test PostgreSQL backup tables verification."""
        try:
            if not self.postgresql_impl:
                logger.error("   PostgreSQL implementation not available")
                return False
            
            # Verify PostgreSQL tables exist
            tables_exist = await self.postgresql_impl.space_data_tables_exist(self.test_space_id)
            
            if tables_exist:
                logger.info(f"   PostgreSQL backup tables verified: {self.test_space_id}")
                return True
            else:
                logger.error(f"   PostgreSQL backup tables not found: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"   PostgreSQL tables verification failed: {e}")
            return False
    
    async def _test_admin_dataset_registration(self) -> bool:
        """Test admin dataset space registration."""
        try:
            if not self.admin_dataset:
                logger.error("   Admin dataset not available")
                return False
            
            # Register space in admin dataset
            await self.admin_dataset.register_space(
                space_id=self.test_space_id,
                space_name=f"Test Space {self.test_space_id}",
                space_description="Comprehensive backend test space",
                tenant="test"
            )
            
            logger.info(f"   Space registered in admin dataset: {self.test_space_id}")
            return True
                
        except Exception as e:
            logger.error(f"   Admin dataset registration failed: {e}")
            return False
