#!/usr/bin/env python3
"""
Comprehensive KG Testing for Fuseki-PostgreSQL Hybrid Backend

This script consolidates all KG-related testing including:
- DAG analysis and graph structure validation
- KGEntity graph operations and relationships
- Graph utilities functionality testing
- KG data structure integrity validation

Uses modular test cases from test_script_kg_impl/kg/ directory.
"""

import sys
import os
import logging
import asyncio

# Add the project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester
from test_script_kg_impl.kg.case_dag_analysis import DAGAnalysisTester

logger = logging.getLogger(__name__)


class FusekiPostgreSQLKGTester(FusekiPostgreSQLEndpointTester):
    """
    Comprehensive KG testing for Fuseki-PostgreSQL hybrid backend.
    
    Tests all aspects of KG functionality including DAG analysis, graph structures,
    and KGEntity operations.
    """
    
    def __init__(self):
        """Initialize the KG tester."""
        super().__init__()
        self.test_space_id = None
        self.test_graph_id = None
        
    async def create_test_space(self) -> bool:
        """Create test space for KG testing."""
        try:
            import uuid
            # Generate unique space and graph IDs
            self.test_space_id = f"test_kg_space_{uuid.uuid4().hex[:8]}"
            self.test_graph_id = f"http://vital.ai/graph/kg_test_{uuid.uuid4().hex[:8]}"
            
            logger.info(f"🔧 Creating test space: {self.test_space_id}")
            logger.info(f"🔧 Using test graph: {self.test_graph_id}")
            
            # Create space using space manager
            from vitalgraph.model.spaces_model import Space
            space = Space(
                space=self.test_space_id,
                space_name=f"KG Test Space {self.test_space_id}",
                space_description="Test space for KG operations testing",
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
            return False
    
    async def run_kg_tests(self) -> bool:
        """
        Run comprehensive KG tests.
        
        Returns:
            bool: True if all tests pass, False otherwise
        """
        logger.info("🚀 Starting KG tests...")
        
        all_tests_passed = True
        test_results = []
        
        try:
            # Test 1: DAG Analysis
            logger.info("\n" + "="*60)
            logger.info("🔍 Running DAG Analysis Tests")
            logger.info("="*60)
            
            dag_result = await self._test_dag_analysis()
            test_results.append(("DAG Analysis", dag_result))
            if not dag_result:
                all_tests_passed = False
            
            # Future KG tests can be added here
            # Test 2: KGEntity Operations
            # Test 3: Graph Structure Validation
            # etc.
            
        except Exception as e:
            logger.error(f"❌ KG testing failed with exception: {e}")
            all_tests_passed = False
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("📊 KG Test Results Summary")
        logger.info("="*60)
        
        for test_name, result in test_results:
            status = "✅ PASSED" if result else "❌ FAILED"
            logger.info(f"{test_name}: {status}")
        
        overall_status = "✅ PASSED" if all_tests_passed else "❌ FAILED"
        logger.info(f"\nOverall KG Tests: {overall_status}")
        
        return all_tests_passed
    
    async def _test_dag_analysis(self) -> bool:
        """Test DAG analysis functionality."""
        try:
            # Import required modules
            from kgentity_test_data import KGEntityTestDataCreator
            from vitalgraph.utils import graph_utils
            
            # Create test data creator
            test_data_creator = KGEntityTestDataCreator()
            
            # Create DAG analysis tester
            dag_tester = DAGAnalysisTester(test_data_creator, graph_utils)
            
            # Run DAG analysis tests
            dag_results = await dag_tester.test_dag_analysis()
            
            # Log detailed results
            logger.info(f"DAG Analysis Results:")
            logger.info(f"  Total Tests: {dag_results['total_tests']}")
            logger.info(f"  Passed Tests: {dag_results['passed_tests']}")
            logger.info(f"  Failed Tests: {len(dag_results['failed_tests'])}")
            
            if dag_results['failed_tests']:
                logger.error(f"  Failures: {dag_results['failed_tests']}")
            
            for detail in dag_results['test_details']:
                status_emoji = "✅" if detail['status'] == 'PASSED' else "❌"
                logger.info(f"  {status_emoji} {detail['test']}: {detail['message']}")
            
            return dag_results['success']
            
        except Exception as e:
            logger.error(f"❌ DAG analysis test failed: {e}")
            return False
    
    async def cleanup(self):
        """Cleanup resources."""
        try:
            if hasattr(self, 'hybrid_backend') and self.hybrid_backend:
                await self.hybrid_backend.cleanup()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


def main():
    """Main function to run KG tests."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info("🚀 Starting Fuseki-PostgreSQL KG Testing...")
    
    async def run_tests():
        """Run the tests asynchronously."""
        tester = None
        try:
            # Initialize tester
            tester = FusekiPostgreSQLKGTester()
            
            # Setup hybrid backend
            logger.info("🔧 Setting up hybrid backend...")
            await tester.setup_hybrid_backend()
            
            # Create test space
            logger.info("🔧 Creating test space...")
            space_created = await tester.create_test_space()
            if not space_created:
                logger.error("❌ Failed to create test space")
                return False
            
            # Run KG tests
            logger.info("🔧 Running KG tests...")
            tests_passed = await tester.run_kg_tests()
            
            return tests_passed
            
        except Exception as e:
            logger.error(f"❌ Test execution failed: {e}")
            return False
        finally:
            # Cleanup
            if tester and tester.test_space_id:
                try:
                    logger.info("🧹 Cleaning up test space...")
                    await tester.space_manager.delete_space_with_tables(tester.test_space_id)
                    logger.info("✅ Test space cleaned up")
                except Exception as e:
                    logger.error(f"❌ Cleanup failed: {e}")
            
            if tester:
                try:
                    await tester.cleanup()
                    logger.info("✅ Backend cleanup completed")
                except Exception as e:
                    logger.error(f"❌ Backend cleanup failed: {e}")
    
    # Run tests
    success = asyncio.run(run_tests())
    
    if success:
        logger.info("🎉 All KG tests completed successfully!")
        sys.exit(0)
    else:
        logger.error("💥 Some KG tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
