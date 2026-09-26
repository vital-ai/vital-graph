"""
Backend Initialization Test Case

Tests initialization of all FUSEKI_POSTGRESQL hybrid backend components including:
- PostgreSQL database connection and setup
- Fuseki server connection and dataset management
- Dual-write coordinator initialization
- Space implementation setup
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class BackendInitializationTester:
    """
    Test case for backend initialization functionality.
    
    Tests proper setup and connectivity of all hybrid backend components.
    """
    
    def __init__(self, config: dict):
        """
        Initialize backend initialization tester.
        
        Args:
            config: Configuration dictionary for FUSEKI_POSTGRESQL backend
        """
        self.config = config
        self.fuseki_config = config['fuseki']
        self.postgresql_config = config['database']
        
        # Backend components (will be initialized during test)
        self.space_impl = None
        self.dual_coordinator = None
        self.fuseki_manager = None
        self.admin_dataset = None
        self.postgresql_impl = None
    
    async def test_backend_initialization(self) -> Dict[str, Any]:
        """
        Test initialization of all backend components.
        
        Returns:
            Dictionary with test results
        """
        logger.info("🔧 Testing backend initialization...")
        
        results = {
            'success': True,
            'total_tests': 5,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': [],
            'components': {}
        }
        
        try:
            # Test 1: PostgreSQL Implementation Initialization
            logger.info("🔍 Test 1: PostgreSQL Implementation")
            postgresql_success = await self._test_postgresql_init()
            results['components']['postgresql'] = postgresql_success
            
            if postgresql_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'PostgreSQL Initialization',
                    'status': 'PASSED',
                    'message': 'PostgreSQL connection and setup successful'
                })
                logger.info("✅ PostgreSQL Initialization: PASSED")
            else:
                results['failed_tests'].append("PostgreSQL Initialization failed")
                results['test_details'].append({
                    'test': 'PostgreSQL Initialization',
                    'status': 'FAILED',
                    'message': 'Failed to connect or setup PostgreSQL'
                })
                logger.error("❌ PostgreSQL Initialization: FAILED")
            
            # Test 2: Fuseki Manager Initialization
            logger.info("🔍 Test 2: Fuseki Manager")
            fuseki_manager_success = await self._test_fuseki_manager_init()
            results['components']['fuseki_manager'] = fuseki_manager_success
            
            if fuseki_manager_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Fuseki Manager Initialization',
                    'status': 'PASSED',
                    'message': 'Fuseki manager connection successful'
                })
                logger.info("✅ Fuseki Manager Initialization: PASSED")
            else:
                results['failed_tests'].append("Fuseki Manager Initialization failed")
                results['test_details'].append({
                    'test': 'Fuseki Manager Initialization',
                    'status': 'FAILED',
                    'message': 'Failed to connect to Fuseki server'
                })
                logger.error("❌ Fuseki Manager Initialization: FAILED")
            
            # Test 3: Admin Dataset Initialization
            logger.info("🔍 Test 3: Admin Dataset")
            admin_dataset_success = await self._test_admin_dataset_init()
            results['components']['admin_dataset'] = admin_dataset_success
            
            if admin_dataset_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Admin Dataset Initialization',
                    'status': 'PASSED',
                    'message': 'Admin dataset connection successful'
                })
                logger.info("✅ Admin Dataset Initialization: PASSED")
            else:
                results['failed_tests'].append("Admin Dataset Initialization failed")
                results['test_details'].append({
                    'test': 'Admin Dataset Initialization',
                    'status': 'FAILED',
                    'message': 'Failed to connect to admin dataset'
                })
                logger.error("❌ Admin Dataset Initialization: FAILED")
            
            # Test 4: Dual-Write Coordinator Initialization
            logger.info("🔍 Test 4: Dual-Write Coordinator")
            dual_coordinator_success = await self._test_dual_coordinator_init()
            results['components']['dual_coordinator'] = dual_coordinator_success
            
            if dual_coordinator_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Dual-Write Coordinator Initialization',
                    'status': 'PASSED',
                    'message': 'Dual-write coordinator setup successful'
                })
                logger.info("✅ Dual-Write Coordinator Initialization: PASSED")
            else:
                results['failed_tests'].append("Dual-Write Coordinator Initialization failed")
                results['test_details'].append({
                    'test': 'Dual-Write Coordinator Initialization',
                    'status': 'FAILED',
                    'message': 'Failed to setup dual-write coordinator'
                })
                logger.error("❌ Dual-Write Coordinator Initialization: FAILED")
            
            # Test 5: Space Implementation Initialization
            logger.info("🔍 Test 5: Space Implementation")
            space_impl_success = await self._test_space_impl_init()
            results['components']['space_impl'] = space_impl_success
            
            if space_impl_success:
                results['passed_tests'] += 1
                results['test_details'].append({
                    'test': 'Space Implementation Initialization',
                    'status': 'PASSED',
                    'message': 'Space implementation setup successful'
                })
                logger.info("✅ Space Implementation Initialization: PASSED")
            else:
                results['failed_tests'].append("Space Implementation Initialization failed")
                results['test_details'].append({
                    'test': 'Space Implementation Initialization',
                    'status': 'FAILED',
                    'message': 'Failed to setup space implementation'
                })
                logger.error("❌ Space Implementation Initialization: FAILED")
            
            # Update overall success
            results['success'] = len(results['failed_tests']) == 0
            
        except Exception as e:
            logger.error(f"❌ Backend initialization testing failed: {e}")
            results['success'] = False
            results['failed_tests'].append(f"Test execution error: {str(e)}")
        
        return results
    
    async def _test_postgresql_init(self) -> bool:
        """Test PostgreSQL implementation initialization."""
        try:
            from vitalgraph.db.fuseki_postgresql.postgresql_db_impl import FusekiPostgreSQLDbImpl
            
            self.postgresql_impl = FusekiPostgreSQLDbImpl(self.postgresql_config)
            await self.postgresql_impl.connect()
            
            # Test basic connectivity
            if hasattr(self.postgresql_impl, 'connection_pool') and self.postgresql_impl.connection_pool:
                logger.info("   PostgreSQL connection pool established")
                return True
            else:
                logger.error("   PostgreSQL connection pool not established")
                return False
                
        except Exception as e:
            logger.error(f"   PostgreSQL initialization failed: {e}")
            return False
    
    async def _test_fuseki_manager_init(self) -> bool:
        """Test Fuseki manager initialization."""
        try:
            from vitalgraph.db.fuseki_postgresql.fuseki_dataset_manager import FusekiDatasetManager
            
            self.fuseki_manager = FusekiDatasetManager(self.fuseki_config)
            await self.fuseki_manager.connect()
            
            # Test basic connectivity by checking server status
            if hasattr(self.fuseki_manager, 'session') and self.fuseki_manager.session:
                logger.info("   Fuseki manager session established")
                return True
            else:
                logger.error("   Fuseki manager session not established")
                return False
                
        except Exception as e:
            logger.error(f"   Fuseki manager initialization failed: {e}")
            return False
    
    async def _test_admin_dataset_init(self) -> bool:
        """Test admin dataset initialization."""
        try:
            from vitalgraph.db.fuseki_postgresql.fuseki_admin_dataset import FusekiAdminDataset
            
            self.admin_dataset = FusekiAdminDataset(self.fuseki_config)
            await self.admin_dataset.connect()
            
            # Test basic connectivity
            if hasattr(self.admin_dataset, 'session') and self.admin_dataset.session:
                logger.info("   Admin dataset session established")
                return True
            else:
                logger.error("   Admin dataset session not established")
                return False
                
        except Exception as e:
            logger.error(f"   Admin dataset initialization failed: {e}")
            return False
    
    async def _test_dual_coordinator_init(self) -> bool:
        """Test dual-write coordinator initialization."""
        try:
            from vitalgraph.db.fuseki_postgresql.dual_write_coordinator import DualWriteCoordinator
            
            # Requires both PostgreSQL and Fuseki components
            if not self.postgresql_impl or not self.fuseki_manager:
                logger.error("   Prerequisites not met for dual-write coordinator")
                return False
            
            self.dual_coordinator = DualWriteCoordinator(
                fuseki_manager=self.fuseki_manager,
                postgresql_impl=self.postgresql_impl
            )
            
            # Test that coordinator has required components
            if (hasattr(self.dual_coordinator, 'fuseki_manager') and 
                hasattr(self.dual_coordinator, 'postgresql_impl')):
                logger.info("   Dual-write coordinator components linked")
                return True
            else:
                logger.error("   Dual-write coordinator components not properly linked")
                return False
                
        except Exception as e:
            logger.error(f"   Dual-write coordinator initialization failed: {e}")
            return False
    
    async def _test_space_impl_init(self) -> bool:
        """Test space implementation initialization."""
        try:
            from vitalgraph.db.fuseki_postgresql.fuseki_postgresql_space_impl import FusekiPostgreSQLSpaceImpl
            
            self.space_impl = FusekiPostgreSQLSpaceImpl(
                fuseki_config=self.fuseki_config,
                postgresql_config=self.postgresql_config
            )
            await self.space_impl.connect()
            
            # Test that space implementation is properly connected
            if hasattr(self.space_impl, 'fuseki_manager') and hasattr(self.space_impl, 'postgresql_impl'):
                logger.info("   Space implementation components connected")
                return True
            else:
                logger.error("   Space implementation components not connected")
                return False
                
        except Exception as e:
            logger.error(f"   Space implementation initialization failed: {e}")
            return False
    
    async def cleanup_components(self):
        """Clean up initialized components."""
        try:
            logger.info("🧹 Cleaning up backend components...")
            
            if self.space_impl:
                await self.space_impl.disconnect()
                logger.info("   Space implementation disconnected")
            
            if self.fuseki_manager:
                await self.fuseki_manager.disconnect()
                logger.info("   Fuseki manager disconnected")
            
            if self.admin_dataset:
                await self.admin_dataset.disconnect()
                logger.info("   Admin dataset disconnected")
            
            if self.postgresql_impl:
                await self.postgresql_impl.disconnect()
                logger.info("   PostgreSQL implementation disconnected")
            
            logger.info("✅ Component cleanup completed")
            
        except Exception as e:
            logger.error(f"❌ Component cleanup failed: {e}")
    
    def get_initialized_components(self) -> Dict[str, Any]:
        """Get references to initialized components for use by other tests."""
        return {
            'space_impl': self.space_impl,
            'dual_coordinator': self.dual_coordinator,
            'fuseki_manager': self.fuseki_manager,
            'admin_dataset': self.admin_dataset,
            'postgresql_impl': self.postgresql_impl
        }
