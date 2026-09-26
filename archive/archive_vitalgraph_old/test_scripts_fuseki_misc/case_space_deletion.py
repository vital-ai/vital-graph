"""
Space Deletion Test Case

Tests space deletion and cleanup in the FUSEKI_POSTGRESQL hybrid backend including:
- Dual-write space storage deletion
- Fuseki dataset deletion and verification
- PostgreSQL backup tables deletion and verification
- Admin dataset space unregistration
- Backend component cleanup
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class SpaceDeletionTester:
    """
    Test case for space deletion and cleanup functionality.
    
    Tests proper deletion of spaces and cleanup of all resources.
    """
    
    def __init__(self, components: Dict[str, Any], test_space_id: str):
        """
        Initialize space deletion tester.
        
        Args:
            components: Dictionary of initialized backend components
            test_space_id: ID of the test space to delete
        """
        self.components = components
        self.test_space_id = test_space_id
        
        # Extract components for easier access
        self.dual_coordinator = components.get('dual_coordinator')
        self.fuseki_manager = components.get('fuseki_manager')
        self.admin_dataset = components.get('admin_dataset')
        self.postgresql_impl = components.get('postgresql_impl')
        self.space_impl = components.get('space_impl')
    
    async def test_space_deletion(self) -> Dict[str, Any]:
        """
        Test deletion of space with complete cleanup.
        
        Returns:
            Dictionary with test results
        """
        logger.info(f"🧹 Testing space deletion: {self.test_space_id}")
        
        results = {
            'success': True,
            'total_tests': 5,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        try:
            # Test 1: Dual-Write Space Storage Deletion
            logger.info("🔍 Test 1: Dual-Write Space Storage Deletion")
            storage_deletion_success = await self._test_dual_write_storage_deletion()
            
            if storage_deletion_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Dual-Write Storage Deletion',
                    'status': 'PASSED',
                    'message': 'Space storage deleted from both systems'
                })
                logger.info("✅ Dual-Write Storage Deletion: PASSED")
            else:
                results['failed_tests'].append("Dual-Write Storage Deletion failed")
                results['test_details'].append({
                    'test': 'Dual-Write Storage Deletion',
                    'status': 'FAILED',
                    'message': 'Failed to delete space storage'
                })
                logger.error("❌ Dual-Write Storage Deletion: FAILED")
            
            # Test 2: Fuseki Dataset Deletion Verification
            logger.info("🔍 Test 2: Fuseki Dataset Deletion Verification")
            fuseki_verification_success = await self._test_fuseki_dataset_deletion_verification()
            
            if fuseki_verification_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Fuseki Dataset Deletion Verification',
                    'status': 'PASSED',
                    'message': 'Fuseki dataset successfully deleted'
                })
                logger.info("✅ Fuseki Dataset Deletion Verification: PASSED")
            else:
                results['failed_tests'].append("Fuseki Dataset Deletion Verification failed")
                results['test_details'].append({
                    'test': 'Fuseki Dataset Deletion Verification',
                    'status': 'FAILED',
                    'message': 'Fuseki dataset still exists after deletion'
                })
                logger.error("❌ Fuseki Dataset Deletion Verification: FAILED")
            
            # Test 3: PostgreSQL Tables Deletion Verification
            logger.info("🔍 Test 3: PostgreSQL Tables Deletion Verification")
            postgresql_verification_success = await self._test_postgresql_tables_deletion_verification()
            
            if postgresql_verification_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'PostgreSQL Tables Deletion Verification',
                    'status': 'PASSED',
                    'message': 'PostgreSQL backup tables successfully deleted'
                })
                logger.info("✅ PostgreSQL Tables Deletion Verification: PASSED")
            else:
                results['failed_tests'].append("PostgreSQL Tables Deletion Verification failed")
                results['test_details'].append({
                    'test': 'PostgreSQL Tables Deletion Verification',
                    'status': 'FAILED',
                    'message': 'PostgreSQL backup tables still exist after deletion'
                })
                logger.error("❌ PostgreSQL Tables Deletion Verification: FAILED")
            
            # Test 4: Admin Dataset Unregistration
            logger.info("🔍 Test 4: Admin Dataset Unregistration")
            admin_unregistration_success = await self._test_admin_dataset_unregistration()
            
            if admin_unregistration_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Admin Dataset Unregistration',
                    'status': 'PASSED',
                    'message': 'Space unregistered from admin dataset'
                })
                logger.info("✅ Admin Dataset Unregistration: PASSED")
            else:
                results['failed_tests'].append("Admin Dataset Unregistration failed")
                results['test_details'].append({
                    'test': 'Admin Dataset Unregistration',
                    'status': 'FAILED',
                    'message': 'Failed to unregister space from admin dataset'
                })
                logger.error("❌ Admin Dataset Unregistration: FAILED")
            
            # Test 5: Backend Component Cleanup
            logger.info("🔍 Test 5: Backend Component Cleanup")
            cleanup_success = await self._test_backend_cleanup()
            
            if cleanup_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Backend Component Cleanup',
                    'status': 'PASSED',
                    'message': 'All backend components cleaned up successfully'
                })
                logger.info("✅ Backend Component Cleanup: PASSED")
            else:
                results['failed_tests'].append("Backend Component Cleanup failed")
                results['test_details'].append({
                    'test': 'Backend Component Cleanup',
                    'status': 'FAILED',
                    'message': 'Failed to cleanup some backend components'
                })
                logger.error("❌ Backend Component Cleanup: FAILED")
            
            # Update overall success
            results['success'] = len(results['failed_tests']) == 0
            
        except Exception as e:
            logger.error(f"❌ Space deletion testing failed: {e}")
            results['success'] = False
            results['failed_tests'].append(f"Test execution error: {str(e)}")
        
        return results
    
    async def _test_dual_write_storage_deletion(self) -> bool:
        """Test dual-write space storage deletion."""
        try:
            if not self.dual_coordinator:
                logger.error("   Dual-write coordinator not available")
                return False
            
            # Delete space using dual-write coordinator
            success = await self.dual_coordinator.delete_space_storage(self.test_space_id)
            
            if success:
                logger.info(f"   Space storage deleted successfully: {self.test_space_id}")
                return True
            else:
                logger.error(f"   Space storage deletion failed: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"   Dual-write storage deletion failed: {e}")
            return False
    
    async def _test_fuseki_dataset_deletion_verification(self) -> bool:
        """Test Fuseki dataset deletion verification."""
        try:
            if not self.fuseki_manager:
                logger.error("   Fuseki manager not available")
                return False
            
            # Verify Fuseki dataset is deleted
            dataset_exists = await self.fuseki_manager.dataset_exists(self.test_space_id)
            
            if not dataset_exists:
                logger.info(f"   Fuseki dataset successfully deleted: {self.test_space_id}")
                return True
            else:
                logger.error(f"   Fuseki dataset still exists after deletion: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"   Fuseki dataset deletion verification failed: {e}")
            return False
    
    async def _test_postgresql_tables_deletion_verification(self) -> bool:
        """Test PostgreSQL backup tables deletion verification."""
        try:
            if not self.postgresql_impl:
                logger.error("   PostgreSQL implementation not available")
                return False
            
            # Verify PostgreSQL tables are deleted
            tables_exist = await self.postgresql_impl.space_data_tables_exist(self.test_space_id)
            
            if not tables_exist:
                logger.info(f"   PostgreSQL backup tables successfully deleted: {self.test_space_id}")
                return True
            else:
                logger.error(f"   PostgreSQL backup tables still exist after deletion: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"   PostgreSQL tables deletion verification failed: {e}")
            return False
    
    async def _test_admin_dataset_unregistration(self) -> bool:
        """Test admin dataset space unregistration."""
        try:
            if not self.admin_dataset:
                logger.error("   Admin dataset not available")
                return False
            
            # Unregister from admin dataset
            await self.admin_dataset.unregister_space(self.test_space_id)
            
            logger.info(f"   Space unregistered from admin dataset: {self.test_space_id}")
            return True
                
        except Exception as e:
            logger.error(f"   Admin dataset unregistration failed: {e}")
            return False
    
    async def _test_backend_cleanup(self) -> bool:
        """Test backend component cleanup."""
        try:
            logger.info("   Cleaning up backend connections...")
            
            cleanup_success = True
            
            # Clean up space implementation
            if self.space_impl:
                try:
                    await self.space_impl.disconnect()
                    logger.info("     Space implementation disconnected")
                except Exception as e:
                    logger.error(f"     Space implementation cleanup failed: {e}")
                    cleanup_success = False
            
            # Clean up Fuseki manager
            if self.fuseki_manager:
                try:
                    await self.fuseki_manager.disconnect()
                    logger.info("     Fuseki manager disconnected")
                except Exception as e:
                    logger.error(f"     Fuseki manager cleanup failed: {e}")
                    cleanup_success = False
            
            # Clean up admin dataset
            if self.admin_dataset:
                try:
                    await self.admin_dataset.disconnect()
                    logger.info("     Admin dataset disconnected")
                except Exception as e:
                    logger.error(f"     Admin dataset cleanup failed: {e}")
                    cleanup_success = False
            
            # Clean up PostgreSQL implementation
            if self.postgresql_impl:
                try:
                    await self.postgresql_impl.disconnect()
                    logger.info("     PostgreSQL implementation disconnected")
                except Exception as e:
                    logger.error(f"     PostgreSQL implementation cleanup failed: {e}")
                    cleanup_success = False
            
            if cleanup_success:
                logger.info("   Backend cleanup completed successfully")
                return True
            else:
                logger.error("   Some backend components failed to cleanup")
                return False
                
        except Exception as e:
            logger.error(f"   Backend cleanup test failed: {e}")
            return False
