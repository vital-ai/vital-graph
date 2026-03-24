#!/usr/bin/env python3
"""
Comprehensive test script for FUSEKI_POSTGRESQL hybrid backend.

Tests the complete lifecycle:
1. Backend instantiation and connectivity
2. Space creation (Fuseki dataset + PostgreSQL tables)
3. SPARQL INSERT operations (dual-write)
4. SPARQL UPDATE operations (dual-write)
5. SPARQL DELETE operations (dual-write)
6. SPARQL QUERY operations (read from Fuseki)
7. Space deletion (cleanup both systems)
8. Dual-write consistency validation

Usage:
    python test_scripts/fuseki_postgresql/test_fuseki_postgresql_backend_complete.py
"""

import sys
import os
import asyncio
import logging
import yaml
from pathlib import Path
from datetime import datetime
import uuid

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.db.fuseki_postgresql.fuseki_postgresql_space_impl import FusekiPostgreSQLSpaceImpl
from vitalgraph.db.fuseki_postgresql.dual_write_coordinator import DualWriteCoordinator
from vitalgraph.db.fuseki_postgresql.fuseki_dataset_manager import FusekiDatasetManager
from vitalgraph.db.fuseki_postgresql.fuseki_admin_dataset import FusekiAdminDataset
from vitalgraph.db.fuseki_postgresql.postgresql_db_impl import FusekiPostgreSQLDbImpl

# Import modular test cases
from test_script_kg_impl.backend.case_backend_initialization import BackendInitializationTester
from test_script_kg_impl.backend.case_space_creation import SpaceCreationTester
from test_script_kg_impl.backend.case_sparql_operations import SPARQLOperationsTester
from test_script_kg_impl.backend.case_dual_write_consistency import DualWriteConsistencyTester
from test_script_kg_impl.backend.case_space_deletion import SpaceDeletionTester

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load the FUSEKI_POSTGRESQL configuration."""
    config_file = project_root / "vitalgraphdb_config" / "vitalgraphdb-config-fuseki-postgresql.yaml"
    
    logger.info(f"Loading configuration from: {config_file}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    return config['fuseki_postgresql']


class FusekiPostgreSQLBackendTester:
    """Comprehensive tester for FUSEKI_POSTGRESQL hybrid backend."""
    
    def __init__(self, config: dict):
        """Initialize the tester with configuration."""
        self.config = config
        self.fuseki_config = config['fuseki']
        self.postgresql_config = config['database']
        
        # Test space configuration
        self.test_space_id = f"test_backend_{uuid.uuid4().hex[:8]}"
        self.test_graph_uri = f"http://vital.ai/test/graph/{self.test_space_id}"
        
        # Backend components
        self.space_impl = None
        self.dual_coordinator = None
        self.fuseki_manager = None
        self.admin_dataset = None
        self.postgresql_impl = None
        
        logger.info(f"Initialized tester for space: {self.test_space_id}")
    
    async def initialize_backend(self) -> bool:
        """Initialize all backend components using modular test case."""
        try:
            logger.info("🔧 Initializing FUSEKI_POSTGRESQL backend components...")
            
            # Use modular backend initialization tester
            config = {
                'fuseki': self.fuseki_config,
                'database': self.postgresql_config
            }
            init_tester = BackendInitializationTester(config)
            
            # Run the initialization tests
            init_results = await init_tester.test_backend_initialization()
            
            if init_results['success']:
                # Extract initialized components from the tester
                self.postgresql_impl = init_tester.postgresql_impl
                self.fuseki_manager = init_tester.fuseki_manager
                self.admin_dataset = init_tester.admin_dataset
                self.dual_coordinator = init_tester.dual_coordinator
                self.space_impl = init_tester.space_impl
                
                logger.info("✅ Backend components initialized successfully using modular test case")
                logger.info(f"   - {init_results['total_tests']} initialization tests passed")
                return True
            else:
                logger.error("❌ Backend initialization failed in modular test case")
                for test in init_results['tests']:
                    if not test['passed']:
                        logger.error(f"   - {test['name']}: {test.get('error', 'Failed')}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Backend initialization failed: {e}")
            return False
    
    async def test_space_creation(self) -> bool:
        """Test creating a new space with dual-write coordination using modular test case."""
        try:
            logger.info(f"🏗️  Testing space creation: {self.test_space_id}")
            
            # Use modular space creation tester
            components = {
                'dual_coordinator': self.dual_coordinator,
                'fuseki_manager': self.fuseki_manager,
                'postgresql_impl': self.postgresql_impl,
                'admin_dataset': self.admin_dataset
            }
            space_tester = SpaceCreationTester(components, self.test_space_id)
            
            # Run the space creation tests
            creation_results = await space_tester.test_space_creation()
            
            if creation_results['success']:
                logger.info("✅ Space creation successful using modular test case")
                logger.info(f"   - {creation_results['total_tests']} space creation tests passed")
                return True
            else:
                logger.error("❌ Space creation failed in modular test case")
                if 'failed_tests' in creation_results:
                    for failed_test in creation_results['failed_tests']:
                        logger.error(f"   - {failed_test}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Space creation test failed: {e}")
            return False
    
    async def test_sparql_operations(self) -> bool:
        """Test all SPARQL operations using modular test case."""
        try:
            logger.info("📝 Testing SPARQL operations using modular test case...")
            
            # Use modular SPARQL operations tester
            components = {
                'dual_coordinator': self.dual_coordinator,
                'fuseki_manager': self.fuseki_manager
            }
            sparql_tester = SPARQLOperationsTester(components, self.test_space_id, self.test_graph_uri)
            
            # Run all SPARQL operation tests
            sparql_results = await sparql_tester.test_sparql_operations()
            
            if sparql_results['success']:
                logger.info("✅ All SPARQL operations successful using modular test case")
                logger.info(f"   - {sparql_results['total_tests']} SPARQL operation tests passed")
                return True
            else:
                logger.error("❌ SPARQL operations failed in modular test case")
                if 'failed_tests' in sparql_results:
                    for failed_test in sparql_results['failed_tests']:
                        logger.error(f"   - {failed_test}")
                return False
            
        except Exception as e:
            logger.error(f"❌ SPARQL operations test failed: {e}")
            return False
    
    async def test_dual_write_consistency(self) -> bool:
        """Test dual-write consistency using modular test case."""
        try:
            logger.info("🔄 Testing dual-write consistency using modular test case...")
            
            # Use modular dual-write consistency tester
            components = {
                'space_impl': self.space_impl,
                'postgresql_impl': self.postgresql_impl
            }
            consistency_tester = DualWriteConsistencyTester(components, self.test_space_id, self.test_graph_uri)
            
            # Run the dual-write consistency tests
            consistency_results = await consistency_tester.test_dual_write_consistency()
            
            if consistency_results['success']:
                logger.info("✅ Dual-write consistency verified using modular test case")
                logger.info(f"   - {consistency_results['total_tests']} consistency tests passed")
                return True
            else:
                logger.error("❌ Dual-write consistency failed in modular test case")
                if 'failed_tests' in consistency_results:
                    for failed_test in consistency_results['failed_tests']:
                        logger.error(f"   - {failed_test}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Dual-write consistency test failed: {e}")
            return False
    
    async def _get_postgresql_triples(self) -> list:
        """Get all triples from PostgreSQL backup tables."""
        try:
            # Use the PostgreSQL connection pool properly
            async with self.postgresql_impl.connection_pool.acquire() as conn:
                # First, check what tables exist
                table_query = f"""
                SELECT table_name FROM information_schema.tables 
                WHERE table_name LIKE '{self.test_space_id}%'
                """
                tables = await conn.fetch(table_query)
                logger.info(f"🔍 PostgreSQL tables for space {self.test_space_id}: {[t['table_name'] for t in tables]}")
                
                # Check if the expected tables exist
                quad_table = f"{self.test_space_id}_rdf_quad"
                term_table = f"{self.test_space_id}_term"
                
                # Count total rows in each table
                try:
                    quad_count = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_table}")
                    term_count = await conn.fetchval(f"SELECT COUNT(*) FROM {term_table}")
                    logger.info(f"📊 Table counts - {quad_table}: {quad_count} rows, {term_table}: {term_count} rows")
                except Exception as table_error:
                    logger.error(f"❌ Error checking table counts: {table_error}")
                    return []
                
                # Check table schema to get correct column names
                schema_query = f"""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = '{term_table}' 
                ORDER BY ordinal_position
                """
                term_columns = await conn.fetch(schema_query)
                logger.info(f"🔍 Term table columns: {[c['column_name'] for c in term_columns]}")
                
                schema_query2 = f"""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = '{quad_table}' 
                ORDER BY ordinal_position
                """
                quad_columns = await conn.fetch(schema_query2)
                logger.info(f"🔍 Quad table columns: {[c['column_name'] for c in quad_columns]}")
                
                # Use correct column names based on actual schema
                all_query = f"""
                SELECT t_s.term_text as subject, t_p.term_text as predicate, t_o.term_text as object
                FROM {quad_table} q
                JOIN {term_table} t_s ON q.subject_uuid = t_s.term_uuid
                JOIN {term_table} t_p ON q.predicate_uuid = t_p.term_uuid  
                JOIN {term_table} t_o ON q.object_uuid = t_o.term_uuid
                """
                
                logger.info(f"🔍 Querying ALL PostgreSQL data (no graph filter)")
                rows = await conn.fetch(all_query)
                logger.info(f"📊 PostgreSQL query returned {len(rows)} rows")
                
                triples = []
                for row in rows:
                    triple = (row['subject'], row['predicate'], row['object'])
                    triples.append(triple)
                    logger.info(f"🔍 PostgreSQL triple: {triple}")
                
                return triples
            
        except Exception as e:
            logger.error(f"❌ Error querying PostgreSQL: {e}")
            return []
    
    async def test_space_deletion(self) -> bool:
        """Test space deletion using modular test case."""
        try:
            logger.info(f"🧹 Testing space deletion using modular test case...")
            
            # Use modular space deletion tester
            components = {
                'dual_coordinator': self.dual_coordinator,
                'fuseki_manager': self.fuseki_manager,
                'postgresql_impl': self.postgresql_impl,
                'admin_dataset': self.admin_dataset
            }
            deletion_tester = SpaceDeletionTester(components, self.test_space_id)
            
            # Run the space deletion tests
            deletion_results = await deletion_tester.test_space_deletion()
            
            if deletion_results['success']:
                logger.info("✅ Space deletion successful using modular test case")
                logger.info(f"   - {deletion_results['total_tests']} space deletion tests passed")
                return True
            else:
                logger.error("❌ Space deletion failed in modular test case")
                if 'failed_tests' in deletion_results:
                    for failed_test in deletion_results['failed_tests']:
                        logger.error(f"   - {failed_test}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Space deletion test failed: {e}")
            return False
    
    async def cleanup_backend(self) -> bool:
        """Clean up backend connections."""
        try:
            logger.info("🧹 Cleaning up backend connections...")
            
            if self.space_impl:
                await self.space_impl.disconnect()
            
            if self.fuseki_manager:
                await self.fuseki_manager.disconnect()
            
            if self.admin_dataset:
                await self.admin_dataset.disconnect()
            
            if self.postgresql_impl:
                await self.postgresql_impl.disconnect()
            
            logger.info("✅ Backend cleanup successful")
            return True
            
        except Exception as e:
            logger.error(f"❌ Backend cleanup failed: {e}")
            return False
    
    async def run_all_tests(self) -> bool:
        """Run the complete test suite."""
        logger.info("🧪 Starting FUSEKI_POSTGRESQL Backend Test Suite")
        logger.info("=" * 70)
        
        tests = [
            ("Backend Initialization", self.initialize_backend),
            ("Space Creation", self.test_space_creation),
            ("SPARQL Operations", self.test_sparql_operations),
            ("Dual-Write Consistency", self.test_dual_write_consistency),
            ("Space Deletion", self.test_space_deletion),
            ("Backend Cleanup", self.cleanup_backend)
        ]
        
        results = []
        for test_name, test_func in tests:
            logger.info(f"\n🔬 Running: {test_name}")
            try:
                result = await test_func()
                results.append((test_name, result))
                if result:
                    logger.info(f"✅ {test_name}: PASSED")
                else:
                    logger.error(f"❌ {test_name}: FAILED")
            except Exception as e:
                logger.error(f"❌ {test_name}: FAILED with exception: {e}")
                results.append((test_name, False))
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("📊 Test Results Summary:")
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            logger.info(f"  {test_name}: {status}")
        
        logger.info(f"\n🎯 Overall Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
        
        if passed == total:
            logger.info("🎉 All tests PASSED! FUSEKI_POSTGRESQL backend is fully functional.")
            return True
        else:
            logger.error(f"⚠️  {total-passed} tests FAILED. Please review the implementation.")
            return False


async def main():
    """Main test function."""
    try:
        # Load configuration
        config = load_config()
        
        # Create and run tester
        tester = FusekiPostgreSQLBackendTester(config)
        success = await tester.run_all_tests()
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Test suite failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
