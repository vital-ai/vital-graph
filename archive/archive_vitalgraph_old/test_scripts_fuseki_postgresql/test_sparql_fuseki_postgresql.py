#!/usr/bin/env python3
"""
Comprehensive SPARQL Testing for Fuseki-PostgreSQL Hybrid Backend

This script consolidates all SPARQL-related testing including:
- SPARQL parsing and operation type detection
- SPARQL UPDATE operations (INSERT, DELETE, MODIFY)
- SPARQL query execution and validation
- Dual-write coordination testing
- RDFLib integration validation

Uses modular test cases from test_script_kg_impl/sparql_query/ directory.
"""

import sys
import os
import logging
import asyncio

# Add the project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester
from test_script_kg_impl.sparql_query.case_sparql_parser import SPARQLParserTester, SPARQLExecutionTester

logger = logging.getLogger(__name__)


class FusekiPostgreSQLSPARQLTester(FusekiPostgreSQLEndpointTester):
    """
    Comprehensive SPARQL testing for Fuseki-PostgreSQL hybrid backend.
    
    Tests all aspects of SPARQL functionality including parsing, execution,
    and dual-write coordination.
    """
    
    def __init__(self):
        """Initialize the SPARQL tester."""
        super().__init__()
        self.test_space_id = None
        self.test_graph_id = None
        
    async def create_test_space(self) -> bool:
        """Create test space for SPARQL testing."""
        try:
            import uuid
            # Generate unique space and graph IDs
            self.test_space_id = f"test_sparql_space_{uuid.uuid4().hex[:8]}"
            self.test_graph_id = f"http://vital.ai/graph/sparql_test_{uuid.uuid4().hex[:8]}"
            
            logger.info(f"🔧 Creating test space: {self.test_space_id}")
            logger.info(f"🔧 Using test graph: {self.test_graph_id}")
            
            # Create space using space manager
            from vitalgraph.model.spaces_model import Space
            space = Space(
                space=self.test_space_id,
                space_name=f"SPARQL Test Space {self.test_space_id}",
                space_description="Test space for SPARQL operations testing",
                tenant="test_user_123"
            )
            
            # Use create_space_with_tables to ensure proper setup
            success = await self.space_manager.create_space_with_tables(
                space_id=self.test_space_id,
                space_name=space.space_name,
                space_description=space.space_description
            )
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
    
    async def run_sparql_tests(self) -> bool:
        """Run the SPARQL test operations."""
        logger.info("🔍 Running SPARQL test operations...")
        
        test_results = {
            'parser_tests': False,
            'execution_tests': False
        }
        
        try:
            # Run SPARQL parser tests
            test_results['parser_tests'] = await self._run_sparql_parser_tests()
            
            # Run SPARQL execution tests
            test_results['execution_tests'] = await self._run_sparql_execution_tests()
            
            # Summary
            all_passed = all(test_results.values())
            
            logger.info("📊 SPARQL Test Results Summary:")
            logger.info(f"   - Parser tests: {'✅ PASSED' if test_results['parser_tests'] else '❌ FAILED'}")
            logger.info(f"   - Execution tests: {'✅ PASSED' if test_results['execution_tests'] else '❌ FAILED'}")
            
            return all_passed
            
        except Exception as e:
            logger.error(f"❌ SPARQL test operations failed: {e}")
            return False
    
    async def _run_sparql_parser_tests(self):
        """Run comprehensive SPARQL parser tests."""
        logger.info("  Running SPARQL parser tests...")
        
        try:
            # Initialize SPARQL parser tester
            parser_tester = SPARQLParserTester(
                self.hybrid_backend.sparql_parser
            )
            
            # Run parser tests
            parser_results = await parser_tester.test_sparql_parsing()
            
            if parser_results['success']:
                logger.info("  ✅ SPARQL parser tests passed")
                return True
            else:
                logger.error(f"  ❌ SPARQL parser tests failed")
                return False
                
        except Exception as e:
            logger.error(f"  ❌ SPARQL parser tests failed with exception: {e}")
            return False
    
    async def _run_sparql_execution_tests(self):
        """Run SPARQL execution tests against the hybrid backend."""
        logger.info("  Running SPARQL execution tests...")
        
        try:
            # Use modular execution tester
            execution_tester = SPARQLExecutionTester(self.hybrid_backend)
            execution_results = await execution_tester.test_sparql_execution(
                self.test_space_id, self.test_graph_id
            )
            
            if execution_results['success']:
                logger.info("  ✅ SPARQL execution tests passed")
                return True
            else:
                logger.error("  ❌ SPARQL execution tests failed")
                for test in execution_results['tests']:
                    if not test['passed']:
                        logger.error(f"     - {test['name']}: {test.get('error', 'Failed')}")
                return False
                
        except Exception as e:
            logger.error(f"  ❌ SPARQL execution tests failed: {e}")
            return False
    


async def main():
    """Main test execution function."""
    logger.info("🔬 Fuseki-PostgreSQL SPARQL Testing Suite")
    logger.info("=" * 60)
    
    tester = FusekiPostgreSQLSPARQLTester()
    
    try:
        # Setup hybrid backend
        logger.info("🔧 Setting up Fuseki+PostgreSQL hybrid backend...")
        if not await tester.setup_hybrid_backend():
            logger.error("❌ Failed to setup hybrid backend")
            return 1
        
        # Create test space
        logger.info("🏗️ Creating test space...")
        if not await tester.create_test_space():
            logger.error("❌ Failed to create test space")
            return 1
        
        # Run SPARQL tests
        logger.info("🧪 Running SPARQL tests...")
        success = await tester.run_sparql_tests()
        
        # Cleanup
        logger.info("🧹 Cleaning up test space...")
        try:
            await tester.space_manager.delete_space_with_tables(tester.test_space_id)
            logger.info(f"✅ Test space deleted: {tester.test_space_id}")
        except Exception as e:
            logger.warning(f"⚠️ Cleanup warning: {e}")
        
        # Final cleanup
        try:
            await tester.cleanup()
        except Exception as e:
            logger.warning(f"⚠️ Backend cleanup warning: {e}")
        
        if success:
            logger.info("🎉 All SPARQL tests completed successfully!")
            return 0
        else:
            logger.error("💥 Some SPARQL tests failed!")
            return 1
            
    except Exception as e:
        logger.error(f"💥 SPARQL testing failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
