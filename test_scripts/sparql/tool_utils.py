"""
Test Tool Utilities for VitalGraph SPARQL Testing

This module provides common utilities for SPARQL test scripts including:
- Safe algebra analysis and logging
- Query execution with error handling
- Result formatting and display
- Performance measurement
- Common test patterns
"""

import time
import asyncio
from typing import Any, Dict, List, Optional, Union, Tuple
from contextlib import asynccontextmanager

# RDFLib imports for SPARQL processing
try:
    from rdflib.plugins.sparql import prepareQuery
    from rdflib.plugins.sparql.algebra import translateAlgebra
except ImportError:
    prepareQuery = None
    translateAlgebra = None


class TestToolUtils:
    """
    Utility class for SPARQL test scripts.
    
    Provides common functionality for:
    - Safe algebra analysis
    - Query execution with timing
    - Result formatting
    - Error handling
    """
    
    @staticmethod
    def analyze_query_algebra(query: str, enable_logging: bool = True) -> Tuple[bool, Any, str]:
        """
        Safely analyze SPARQL query algebra with robust error handling.
        
        Args:
            query: SPARQL query string
            enable_logging: Whether to enable detailed algebra logging
            
        Returns:
            Tuple of (success, algebra_object, error_message)
        """
        if not prepareQuery or not translateAlgebra:
            return False, None, "RDFLib SPARQL modules not available"
            
        try:
            prepared_query = prepareQuery(query)
            algebra = translateAlgebra(prepared_query)
            
            if enable_logging:
                print(f"    📋 Analyzing query algebra...")
                
                # Safe algebra type detection
                algebra_name = TestToolUtils._get_safe_algebra_name(algebra)
                print(f"    🔍 Query type: {algebra_name}")
                print(f"    🔍 Algebra structure:")
                
                # Log structure safely
                TestToolUtils._log_algebra_node_safe(algebra)
                print(f"    " + "─" * 40)
            
            return True, algebra, ""
            
        except Exception as e:
            error_msg = str(e)
            if enable_logging:
                print(f"    📋 Analyzing query algebra...")
                print(f"    ⚠️  Algebra analysis failed: {error_msg}")
            return False, None, error_msg
    
    @staticmethod
    def _get_safe_algebra_name(node) -> str:
        """
        Safely get the name of an algebra node, handling string cases.
        
        Args:
            node: Algebra node (may be string)
            
        Returns:
            str: Safe name representation
        """
        if isinstance(node, str):
            return "String"
        return getattr(node, 'name', str(type(node).__name__))
    
    @staticmethod
    def _log_algebra_node_safe(node, indent: int = 6, max_depth: int = 2):
        """
        Safely log algebra node structure with depth limiting.
        
        Args:
            node: Algebra node to log
            indent: Current indentation level
            max_depth: Maximum recursion depth
        """
        if indent > 6 + (max_depth * 4):  # Limit depth
            print("  " * (indent // 2) + "... (max depth reached)")
            return
            
        spaces = " " * indent
        
        try:
            if isinstance(node, str):
                truncated = node[:50] + "..." if len(node) > 50 else node
                print(f"{spaces}📌 String: {truncated}")
                return
            
            if hasattr(node, 'name') and not isinstance(node, str):
                node_name = getattr(node, 'name', 'Unknown')
                print(f"{spaces}📌 {node_name}")
                
                # Only log key structure for common patterns
                if node_name == 'Union' and max_depth > 0:
                    if hasattr(node, 'p1') and node.p1:
                        print(f"{spaces}  ├─ LEFT:")
                        TestToolUtils._log_algebra_node_safe(node.p1, indent + 4, max_depth - 1)
                    if hasattr(node, 'p2') and node.p2:
                        print(f"{spaces}  └─ RIGHT:")
                        TestToolUtils._log_algebra_node_safe(node.p2, indent + 4, max_depth - 1)
                elif hasattr(node, 'triples') and node.triples:
                    print(f"{spaces}  └─ triples: {len(node.triples)} patterns")
                    
            elif isinstance(node, (list, tuple)):
                print(f"{spaces}📌 {type(node).__name__} ({len(node)} items)")
                if len(node) > 0 and max_depth > 0:
                    print(f"{spaces}  └─ [showing first item]")
                    TestToolUtils._log_algebra_node_safe(node[0], indent + 4, max_depth - 1)
            else:
                print(f"{spaces}📌 {type(node).__name__}")
                
        except Exception as e:
            print(f"{spaces}⚠️  Node logging error: {e}")
    
    @staticmethod
    async def execute_query_with_timing(sparql_impl, space_id: str, query: str, 
                                       query_name: str = "Query") -> Tuple[float, Any, Optional[str]]:
        """
        Execute SPARQL query with timing and error handling.
        
        Args:
            sparql_impl: SPARQL implementation instance
            space_id: Space identifier
            query: SPARQL query string
            query_name: Name for logging purposes
            
        Returns:
            Tuple of (execution_time, results, error_message)
        """
        try:
            start_time = time.time()
            results = await sparql_impl.execute_sparql_query(space_id, query)
            elapsed = time.time() - start_time
            return elapsed, results, None
            
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e)
            return elapsed, None, error_msg
    
    @staticmethod
    def format_query_results(results: Any, elapsed_time: float, 
                           error_msg: Optional[str] = None, max_results: int = 10) -> str:
        """
        Format query results for display.
        
        Args:
            results: Query results (list for SELECT, int for others)
            elapsed_time: Execution time in seconds
            error_msg: Optional error message
            max_results: Maximum number of results to show
            
        Returns:
            str: Formatted result string
        """
        if error_msg:
            return f"    ❌ {elapsed_time:.3f}s | Error: {error_msg}"
        
        if isinstance(results, list):
            # SELECT query results
            result_count = len(results)
            time_str = f"{elapsed_time:.3f}s"
            output = f"    ⏱️  {time_str} | {result_count} results\n"
            
            # Show sample results
            for i, result in enumerate(results[:max_results]):
                if isinstance(result, dict):
                    # Format as key=value pairs
                    pairs = [f"{k}={v}" for k, v in result.items()]
                    result_str = " | ".join(pairs)
                else:
                    result_str = str(result)
                    
                output += f"    [{i+1}] {result_str}\n"
            
            if result_count > max_results:
                output += f"    ... and {result_count - max_results} more results\n"
                
            return output.rstrip()
        
        elif isinstance(results, int):
            # UPDATE/INSERT/DELETE results
            return f"    ⏱️  {elapsed_time:.3f}s | {results} operations"
        
        else:
            # Other result types
            return f"    ⏱️  {elapsed_time:.3f}s | Result: {type(results).__name__}"
    
    @staticmethod
    def truncate_query_for_display(query: str, max_length: int = 200) -> str:
        """
        Truncate query text for display purposes.
        
        Args:
            query: SPARQL query string
            max_length: Maximum length before truncation
            
        Returns:
            str: Truncated query string
        """
        if len(query) <= max_length:
            return query
        return query[:max_length] + "..."
    
    @staticmethod
    def print_query_header(query_name: str, query: str):
        """
        Print a formatted header for a query test.
        
        Args:
            query_name: Name of the query
            query: SPARQL query string
        """
        print(f"  {query_name}:")
        truncated_query = TestToolUtils.truncate_query_for_display(query)
        print(f"    📝 Query text (first 200 chars): {truncated_query}")
    
    @staticmethod
    async def run_test_query(sparql_impl, space_id: str, query_name: str, query: str,
                           enable_algebra_logging: bool = True, max_results: int = 10) -> Dict[str, Any]:
        """
        Run a complete test query with algebra analysis, execution, and result formatting.
        
        Args:
            sparql_impl: SPARQL implementation instance
            space_id: Space identifier
            query_name: Name of the query for display
            query: SPARQL query string
            enable_algebra_logging: Whether to log algebra analysis
            max_results: Maximum results to display
            
        Returns:
            Dict with test results and metrics
        """
        # Print header
        TestToolUtils.print_query_header(query_name, query)
        
        # Analyze algebra
        algebra_success, algebra, algebra_error = TestToolUtils.analyze_query_algebra(
            query, enable_algebra_logging
        )
        
        # Execute query
        elapsed_time, results, error_msg = await TestToolUtils.execute_query_with_timing(
            sparql_impl, space_id, query, query_name
        )
        
        # Format and print results
        result_output = TestToolUtils.format_query_results(results, elapsed_time, error_msg, max_results)
        print(result_output)
        
        return {
            'query_name': query_name,
            'algebra_success': algebra_success,
            'algebra_error': algebra_error,
            'execution_time': elapsed_time,
            'results': results,
            'error_msg': error_msg,
            'success': error_msg is None
        }
    
    @staticmethod
    def print_test_section_header(section_name: str, description: str = ""):
        """
        Print a formatted section header for test organization.
        
        Args:
            section_name: Name of the test section
            description: Optional description
        """
        print(f"\n{section_name}:")
        if description:
            print(f"  {description}")
    
    @staticmethod
    def print_test_summary(test_results: List[Dict[str, Any]]):
        """
        Print a summary of test results.
        
        Args:
            test_results: List of test result dictionaries
        """
        total_tests = len(test_results)
        successful_tests = sum(1 for result in test_results if result.get('success', False))
        failed_tests = total_tests - successful_tests
        
        print(f"\n📊 Test Summary:")
        print(f"  Total tests: {total_tests}")
        print(f"  Successful: {successful_tests}")
        print(f"  Failed: {failed_tests}")
        
        if failed_tests > 0:
            print(f"\n❌ Failed tests:")
            for result in test_results:
                if not result.get('success', False):
                    error = result.get('error_msg', 'Unknown error')
                    print(f"  - {result['query_name']}: {error}")
    
    @staticmethod
    def aggregate_test_suites(suite_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregate results from multiple test suites.
        
        Args:
            suite_results: List of test suite result dictionaries
            
        Returns:
            Dict with aggregated statistics and details
        """
        total_suites = len(suite_results)
        total_tests = sum(len(suite.get('test_results', [])) for suite in suite_results)
        total_successful = sum(
            sum(1 for test in suite.get('test_results', []) if test.get('success', False))
            for suite in suite_results
        )
        total_failed = total_tests - total_successful
        total_time = sum(suite.get('total_time', 0) for suite in suite_results)
        
        # Calculate suite-level success rates
        suite_stats = []
        for suite in suite_results:
            suite_tests = suite.get('test_results', [])
            suite_successful = sum(1 for test in suite_tests if test.get('success', False))
            suite_total = len(suite_tests)
            success_rate = (suite_successful / suite_total * 100) if suite_total > 0 else 0
            
            suite_stats.append({
                'name': suite.get('suite_name', 'Unknown'),
                'total_tests': suite_total,
                'successful': suite_successful,
                'failed': suite_total - suite_successful,
                'success_rate': success_rate,
                'execution_time': suite.get('total_time', 0)
            })
        
        return {
            'total_suites': total_suites,
            'total_tests': total_tests,
            'total_successful': total_successful,
            'total_failed': total_failed,
            'overall_success_rate': (total_successful / total_tests * 100) if total_tests > 0 else 0,
            'total_execution_time': total_time,
            'suite_stats': suite_stats,
            'suite_results': suite_results
        }
    
    @staticmethod
    def print_aggregated_summary(aggregated_results: Dict[str, Any]):
        """
        Print a comprehensive summary of aggregated test results.
        
        Args:
            aggregated_results: Results from aggregate_test_suites()
        """
        print("\n" + "=" * 60)
        print("🎯 COMPREHENSIVE TEST SUITE SUMMARY")
        print("=" * 60)
        
        # Overall statistics
        print(f"\n📊 Overall Statistics:")
        print(f"  Test Suites: {aggregated_results['total_suites']}")
        print(f"  Total Tests: {aggregated_results['total_tests']}")
        print(f"  Successful: {aggregated_results['total_successful']} ({aggregated_results['overall_success_rate']:.1f}%)")
        print(f"  Failed: {aggregated_results['total_failed']}")
        print(f"  Total Time: {aggregated_results['total_execution_time']:.3f}s")
        
        # Suite-by-suite breakdown
        print(f"\n📋 Suite Breakdown:")
        for suite_stat in aggregated_results['suite_stats']:
            status_icon = "✅" if suite_stat['failed'] == 0 else "⚠️" if suite_stat['success_rate'] >= 50 else "❌"
            print(f"  {status_icon} {suite_stat['name']}:")
            print(f"    Tests: {suite_stat['successful']}/{suite_stat['total_tests']} ({suite_stat['success_rate']:.1f}%)")
            print(f"    Time: {suite_stat['execution_time']:.3f}s")
        
        # Failed tests summary
        failed_tests = []
        for suite in aggregated_results['suite_results']:
            for test in suite.get('test_results', []):
                if not test.get('success', False):
                    failed_tests.append({
                        'suite': suite.get('suite_name', 'Unknown'),
                        'test': test.get('query_name', 'Unknown'),
                        'error': test.get('error_msg', 'Unknown error')
                    })
        
        if failed_tests:
            print(f"\n❌ Failed Tests Details:")
            for failed in failed_tests:
                print(f"  [{failed['suite']}] {failed['test']}:")
                print(f"    {failed['error']}")
        else:
            print(f"\n🎉 All tests passed successfully!")
        
        print("\n" + "=" * 60)
    
    @staticmethod
    async def run_test_suite(suite_name: str, test_function, *args, **kwargs) -> Dict[str, Any]:
        """
        Run a complete test suite and collect results.
        
        Args:
            suite_name: Name of the test suite
            test_function: Async function that runs the test suite
            *args, **kwargs: Arguments to pass to the test function
            
        Returns:
            Dict with suite results and metadata
        """
        print(f"\n🚀 Starting Test Suite: {suite_name}")
        print("=" * 50)
        
        start_time = time.time()
        test_results = []
        error_msg = None
        
        try:
            # Run the test suite and collect results
            # The test function should return a list of test results
            results = await test_function(*args, **kwargs)
            if isinstance(results, list):
                test_results = results
            else:
                # If the function doesn't return results, we'll track what we can
                test_results = []
                
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Test suite failed: {error_msg}")
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Print suite summary
        successful_tests = sum(1 for test in test_results if test.get('success', False))
        total_tests = len(test_results)
        
        print(f"\n📊 {suite_name} Summary:")
        print(f"  Tests: {successful_tests}/{total_tests}")
        print(f"  Time: {total_time:.3f}s")
        if error_msg:
            print(f"  Error: {error_msg}")
        
        return {
            'suite_name': suite_name,
            'test_results': test_results,
            'total_time': total_time,
            'error_msg': error_msg,
            'success': error_msg is None
        }
