#!/usr/bin/env python3
"""
VitalGraph SPARQL Test Application

This application orchestrates and runs multiple SPARQL test suites, providing
comprehensive aggregation and reporting of test results across all test modules.

Features:
- Runs multiple test suites in sequence
- Aggregates results across all test suites
- Provides detailed success/failure reporting
- Tracks performance metrics
- Generates comprehensive summary reports

Usage:
    python test_scripts/sparql/test_app.py

Requirements:
    - VitalGraph database must be running
    - Test data must be loaded (run reload_test_data.py first)
    - Configuration file must be present in vitalgraphdb_config/
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import test utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tool_utils"))
from tool_utils import TestToolUtils

# Import test suite functions
from test_union_queries import test_union_queries
from test_select_queries import test_subquery_patterns
from test_graph_queries import test_graph_queries
from test_builtin_critical import test_critical_builtins
from test_builtin_numeric import test_numeric_builtins
from test_builtin_string import test_string_builtins
from test_builtin_types import test_type_builtins

class VitalGraphTestApp:
    """
    Main test application that orchestrates multiple SPARQL test suites.
    """
    
    def __init__(self):
        self.suite_results = []
        self.start_time = None
        self.end_time = None
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """
        Run all available SPARQL test suites and aggregate results.
        
        Returns:
            Dict with comprehensive test results and statistics
        """
        print("🎯 VitalGraph SPARQL Test Application")
        print("=" * 60)
        print("🚀 Running comprehensive SPARQL test suite...")
        print("📊 This will test UNION, sub-SELECT, and other SPARQL patterns")
        print("=" * 60)
        
        self.start_time = time.time()
        
        # Define test suites to run
        test_suites = [
            {
                'name': 'UNION Query Tests',
                'function': test_union_queries,
                'description': 'Tests UNION pattern functionality with various scenarios'
            },
            {
                'name': 'Sub-SELECT Query Tests', 
                'function': test_subquery_patterns,
                'description': 'Tests sub-SELECT (subquery) functionality including EXISTS/NOT EXISTS'
            },
            {
                'name': 'GRAPH Query Tests',
                'function': test_graph_queries,
                'description': 'Tests GRAPH pattern functionality with WordNet and named graph data'
            },
            {
                'name': 'Critical Built-in Tests',
                'function': test_critical_builtins,
                'description': 'Tests critical SPARQL built-in functions (BOUND, COALESCE, URI, etc.)'
            },
            {
                'name': 'Numeric Built-in Tests',
                'function': test_numeric_builtins,
                'description': 'Tests numeric SPARQL built-in functions (ABS, CEIL, FLOOR, RAND, etc.)'
            },
            {
                'name': 'String Built-in Tests',
                'function': test_string_builtins,
                'description': 'Tests string SPARQL built-in functions (CONCAT, SUBSTR, REPLACE, etc.)'
            },
            {
                'name': 'Type Built-in Tests',
                'function': test_type_builtins,
                'description': 'Tests type checking SPARQL built-in functions (ISURI, ISLITERAL, DATATYPE, etc.)'
            }
        ]
        
        # Run each test suite
        for suite_config in test_suites:
            try:
                suite_result = await TestToolUtils.run_test_suite(
                    suite_name=suite_config['name'],
                    test_function=suite_config['function']
                )
                suite_result['description'] = suite_config['description']
                self.suite_results.append(suite_result)
                
            except Exception as e:
                print(f"❌ Failed to run test suite '{suite_config['name']}': {e}")
                # Add failed suite to results
                self.suite_results.append({
                    'suite_name': suite_config['name'],
                    'test_results': [],
                    'total_time': 0,
                    'error_msg': str(e),
                    'success': False,
                    'description': suite_config['description']
                })
        
        self.end_time = time.time()
        
        # Generate comprehensive report
        return self.generate_comprehensive_report()
    
    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive test report with aggregated statistics.
        
        Returns:
            Dict with complete test results and analysis
        """
        # Aggregate all test results
        aggregated = TestToolUtils.aggregate_test_suites(self.suite_results)
        
        # Add application-level metadata
        total_app_time = self.end_time - self.start_time if self.end_time and self.start_time else 0
        
        aggregated.update({
            'application_start_time': self.start_time,
            'application_end_time': self.end_time,
            'total_application_time': total_app_time,
            'test_suites_run': len(self.suite_results),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # Print comprehensive summary
        TestToolUtils.print_aggregated_summary(aggregated)
        
        # Print additional application-level details
        self.print_application_summary(aggregated)
        
        return aggregated
    
    def print_application_summary(self, aggregated: Dict[str, Any]):
        """
        Print application-level summary and recommendations.
        
        Args:
            aggregated: Aggregated test results
        """
        print("\n🎯 APPLICATION SUMMARY")
        print("=" * 30)
        
        # Performance analysis
        avg_suite_time = aggregated['total_execution_time'] / aggregated['total_suites'] if aggregated['total_suites'] > 0 else 0
        print(f"⏱️  Performance:")
        print(f"  Total Application Time: {aggregated['total_application_time']:.3f}s")
        print(f"  Average Suite Time: {avg_suite_time:.3f}s")
        
        # Success rate analysis
        success_rate = aggregated['overall_success_rate']
        if success_rate >= 90:
            status = "🎉 EXCELLENT"
        elif success_rate >= 70:
            status = "✅ GOOD"
        elif success_rate >= 50:
            status = "⚠️  NEEDS IMPROVEMENT"
        else:
            status = "❌ CRITICAL ISSUES"
        
        print(f"\n📈 Overall Status: {status}")
        print(f"  Success Rate: {success_rate:.1f}%")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        if aggregated['total_failed'] == 0:
            print("  🎉 All tests passed! The SPARQL implementation is working well.")
        else:
            print(f"  📝 {aggregated['total_failed']} tests failed - review error details above")
            print("  🔧 Focus on fixing RDFLib parser limitations and missing SPARQL features")
            
        # Test coverage analysis
        print(f"\n📊 Test Coverage:")
        for suite_stat in aggregated['suite_stats']:
            coverage_icon = "🟢" if suite_stat['success_rate'] >= 80 else "🟡" if suite_stat['success_rate'] >= 50 else "🔴"
            print(f"  {coverage_icon} {suite_stat['name']}: {suite_stat['success_rate']:.1f}% coverage")
        
        print("\n" + "=" * 60)
        print("🏁 Test Application Complete!")
        print("📋 Review the detailed results above for specific issues and improvements.")
        print("=" * 60)

async def main():
    """
    Main entry point for the test application.
    """
    app = VitalGraphTestApp()
    
    try:
        results = await app.run_all_tests()
        
        # Exit with appropriate code based on results
        if results['total_failed'] == 0:
            print("\n✅ All tests passed successfully!")
            sys.exit(0)
        else:
            print(f"\n⚠️  {results['total_failed']} tests failed. See details above.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Test execution interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Test application failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
