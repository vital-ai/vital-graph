#!/usr/bin/env python3
"""
Test script to verify database connection leak fixes in VitalGraph.

This script performs stress testing of SPARQL endpoints and database operations
to ensure connections are properly released and the system remains stable.
"""

import asyncio
import logging
import time
import psutil
import os
import sys
from pathlib import Path
from typing import Dict, List, Any
import concurrent.futures
import json

# Add the parent directory to the path so we can import vitalgraph_client
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph_client.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConnectionLeakTester:
    """Test suite for detecting database connection leaks under load."""
    
    def __init__(self, config_path: str = None, space_id: str = "wordnet_space"):
        self.space_id = space_id
        self.config_path = config_path
        self.client = None
        
    def setup_test_environment(self):
        """Setup test environment and authenticate."""
        try:
            # Initialize VitalGraphClient
            if self.config_path:
                self.client = VitalGraphClient(self.config_path)
            else:
                self.client = VitalGraphClient()
            
            # Open connection
            self.client.open()
            
            if not self.client.is_connected():
                raise Exception("Failed to connect to VitalGraph server")
            
            logger.info("✅ Test environment setup successful")
            return True
            
        except Exception as e:
            logger.error(f"❌ Test environment setup failed: {e}")
            return False
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics including memory and open files."""
        try:
            process = psutil.Process()
            return {
                "memory_mb": process.memory_info().rss / 1024 / 1024,
                "open_files": len(process.open_files()),
                "connections": len(process.connections()),
                "cpu_percent": process.cpu_percent(),
                "timestamp": time.time()
            }
        except Exception as e:
            logger.warning(f"Could not get system metrics: {e}")
            return {"error": str(e), "timestamp": time.time()}
    
    def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        """Execute a single SPARQL query and measure response."""
        start_time = time.time()
        try:
            # Execute SPARQL query using VitalGraphClient
            result = self.client.execute_sparql_query(space_id, query)
            
            execution_time = time.time() - start_time
            
            # Calculate response size based on result
            response_size = len(str(result)) if result else 0
            
            return {
                "success": True,
                "status_code": 200,
                "execution_time": execution_time,
                "response_size": response_size,
                "error": None,
                "result_count": len(result) if isinstance(result, list) else 1
            }
            
        except VitalGraphClientError as e:
            execution_time = time.time() - start_time
            return {
                "success": False,
                "status_code": None,
                "execution_time": execution_time,
                "response_size": 0,
                "error": f"VitalGraph error: {str(e)}"
            }
        except Exception as e:
            execution_time = time.time() - start_time
            return {
                "success": False,
                "status_code": None,
                "execution_time": execution_time,
                "response_size": 0,
                "error": f"Unexpected error: {str(e)}"
            }
    
    def cleanup(self):
        """Clean up client connection."""
        if self.client:
            try:
                self.client.close()
                logger.info("✅ Client connection closed")
            except Exception as e:
                logger.warning(f"⚠️ Error closing client: {e}")
    
    def run_concurrent_queries(self, space_id: str, num_threads: int = 10, queries_per_thread: int = 5) -> List[Dict[str, Any]]:
        """Run concurrent SPARQL queries to test connection handling under load."""
        
        # EXTREMELY MALFORMED SPARQL QUERIES - PURE GARBAGE TO TRIGGER PARSING EXCEPTIONS
        test_queries = [
            # Repeated opening brackets
            "{{{{{{{{",
            
            # Repeated closing brackets
            "}}}}}}}}",
            
            # Mixed brackets chaos
            "{{{{}}}}{{{{}}}}{{{{{{{",
            
            # Repeated parentheses
            "((((((((",
            
            # Mixed parentheses chaos
            "(((())))(((())))((((",
            
            # Repeated angle brackets
            "<<<<<<<<",
            
            # Mixed angle brackets
            "<<<<>>>><<<<<>>>",
            
            # Repeated question marks
            "????????",
            
            # Repeated dots
            "........",
            
            # Repeated semicolons
            ";;;;;;;;;",
            
            # Random symbol spam
            "!@#$%^&*()_+-=[]{}|;':,.<>?",
            
            # Repeated SELECT keywords
            "SELECT SELECT SELECT SELECT",
            
            # Numbers only
            "12345678901234567890",
            
            # Repeated WHERE
            "WHERE WHERE WHERE WHERE",
            
            # Binary garbage
            "01010101010101010101",
            
            # Unicode chaos
            "αβγδεζηθικλμνξοπρστυφχψω",
            
            # Emoji spam
            "🔥🔥🔥🔥🔥🔥🔥🔥",
            
            # Long string of A's
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            
            # Backslash spam
            "\\\\\\\\\\\\\\\\",
            
            # Quote spam
            '""""""""""""""""',
            
            # Apostrophe spam
            "''''''''''''''''",
            
            # Newline spam
            "\n\n\n\n\n\n\n\n",
            
            # Tab spam
            "\t\t\t\t\t\t\t\t",
            
            # Space spam
            "                    ",
            
            # Mixed chaos
            "{{{{SELECT????WHERE}}}}<<<>>>!!!"
        ]
        
        results = []
        
        def worker_thread(thread_id: int):
            """Worker thread function."""
            thread_results = []
            for i in range(queries_per_thread):
                query = test_queries[i % len(test_queries)]
                logger.info(f"Thread {thread_id}, Query {i+1}: Executing SPARQL query")
                
                # Get metrics before query
                metrics_before = self.get_system_metrics()
                
                # Execute query
                result = self.execute_sparql_query(space_id, query)
                result["thread_id"] = thread_id
                result["query_index"] = i
                result["query"] = query[:50] + "..." if len(query) > 50 else query
                
                # Get metrics after query
                metrics_after = self.get_system_metrics()
                result["metrics_before"] = metrics_before
                result["metrics_after"] = metrics_after
                
                thread_results.append(result)
                
                # Small delay between queries in same thread
                time.sleep(0.1)
            
            return thread_results
        
        # Execute concurrent threads
        logger.info(f"🚀 Starting {num_threads} concurrent threads with {queries_per_thread} queries each")
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            future_to_thread = {executor.submit(worker_thread, i): i for i in range(num_threads)}
            
            for future in concurrent.futures.as_completed(future_to_thread):
                thread_id = future_to_thread[future]
                try:
                    thread_results = future.result()
                    results.extend(thread_results)
                    logger.info(f"✅ Thread {thread_id} completed successfully")
                except Exception as e:
                    logger.error(f"❌ Thread {thread_id} failed: {e}")
                    results.append({
                        "success": False,
                        "thread_id": thread_id,
                        "error": str(e),
                        "execution_time": 0
                    })
        
        total_time = time.time() - start_time
        logger.info(f"🏁 All threads completed in {total_time:.2f} seconds")
        
        return results
    
    def analyze_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze test results for connection leaks and performance issues."""
        
        successful_queries = [r for r in results if r.get("success", False)]
        failed_queries = [r for r in results if not r.get("success", False)]
        
        # Calculate metrics
        total_queries = len(results)
        success_rate = len(successful_queries) / total_queries if total_queries > 0 else 0
        
        execution_times = [r["execution_time"] for r in successful_queries]
        avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0
        
        # Analyze system metrics progression
        memory_progression = []
        connection_progression = []
        
        for result in results:
            if "metrics_before" in result and "metrics_after" in result:
                before = result["metrics_before"]
                after = result["metrics_after"]
                
                if "memory_mb" in before and "memory_mb" in after:
                    memory_progression.append({
                        "before": before["memory_mb"],
                        "after": after["memory_mb"],
                        "delta": after["memory_mb"] - before["memory_mb"]
                    })
                
                if "connections" in before and "connections" in after:
                    connection_progression.append({
                        "before": before["connections"],
                        "after": after["connections"],
                        "delta": after["connections"] - before["connections"]
                    })
        
        # Check for connection leaks
        connection_deltas = [c["delta"] for c in connection_progression]
        avg_connection_delta = sum(connection_deltas) / len(connection_deltas) if connection_deltas else 0
        max_connection_delta = max(connection_deltas) if connection_deltas else 0
        
        # Check for memory leaks
        memory_deltas = [m["delta"] for m in memory_progression]
        avg_memory_delta = sum(memory_deltas) / len(memory_deltas) if memory_deltas else 0
        max_memory_delta = max(memory_deltas) if memory_deltas else 0
        
        analysis = {
            "total_queries": total_queries,
            "successful_queries": len(successful_queries),
            "failed_queries": len(failed_queries),
            "success_rate": success_rate,
            "avg_execution_time": avg_execution_time,
            "avg_connection_delta": avg_connection_delta,
            "max_connection_delta": max_connection_delta,
            "avg_memory_delta": avg_memory_delta,
            "max_memory_delta": max_memory_delta,
            "connection_leak_detected": max_connection_delta > 5 or avg_connection_delta > 1,
            "memory_leak_detected": max_memory_delta > 50 or avg_memory_delta > 10,
            "performance_degradation": avg_execution_time > 5.0
        }
        
        return analysis
    
    def run_full_test_suite(self, space_id: str = "wordnet_space") -> Dict[str, Any]:
        """Run the complete connection leak test suite."""
        
        logger.info("🧪 Starting Connection Leak Test Suite")
        
        # Test 1: Light load (5 threads, 3 queries each)
        logger.info("📊 Test 1: Light Load Testing")
        light_results = self.run_concurrent_queries(space_id, num_threads=5, queries_per_thread=3)
        
        # Wait between tests
        time.sleep(2)
        
        # Test 2: Medium load (10 threads, 5 queries each)
        logger.info("📊 Test 2: Medium Load Testing")
        medium_results = self.run_concurrent_queries(space_id, num_threads=10, queries_per_thread=5)
        
        # Wait between tests
        time.sleep(2)
        
        # Test 3: Heavy load (15 threads, 7 queries each)
        logger.info("📊 Test 3: Heavy Load Testing")
        heavy_results = self.run_concurrent_queries(space_id, num_threads=15, queries_per_thread=7)
        
        # Analyze all results
        all_results = light_results + medium_results + heavy_results
        analysis = self.analyze_results(all_results)
        
        # Generate report
        report = {
            "test_summary": {
                "light_load": self.analyze_results(light_results),
                "medium_load": self.analyze_results(medium_results),
                "heavy_load": self.analyze_results(heavy_results),
                "overall": analysis
            },
            "raw_results": {
                "light_load": light_results,
                "medium_load": medium_results,
                "heavy_load": heavy_results
            }
        }
        
        return report
    
    def print_test_report(self, report: Dict[str, Any]):
        """Print a formatted test report."""
        
        print("\n" + "="*80)
        print("🧪 CONNECTION LEAK TEST REPORT")
        print("="*80)
        
        overall = report["test_summary"]["overall"]
        
        print(f"\n📊 OVERALL RESULTS:")
        print(f"   Total Queries: {overall['total_queries']}")
        print(f"   Success Rate: {overall['success_rate']:.1%}")
        print(f"   Average Execution Time: {overall['avg_execution_time']:.3f}s")
        
        print(f"\n🔍 CONNECTION ANALYSIS:")
        print(f"   Average Connection Delta: {overall['avg_connection_delta']:.2f}")
        print(f"   Max Connection Delta: {overall['max_connection_delta']}")
        print(f"   Connection Leak Detected: {'❌ YES' if overall['connection_leak_detected'] else '✅ NO'}")
        
        print(f"\n💾 MEMORY ANALYSIS:")
        print(f"   Average Memory Delta: {overall['avg_memory_delta']:.2f} MB")
        print(f"   Max Memory Delta: {overall['max_memory_delta']:.2f} MB")
        print(f"   Memory Leak Detected: {'❌ YES' if overall['memory_leak_detected'] else '✅ NO'}")
        
        print(f"\n⚡ PERFORMANCE ANALYSIS:")
        print(f"   Performance Degradation: {'❌ YES' if overall['performance_degradation'] else '✅ NO'}")
        
        # Test-specific results
        for test_name in ["light_load", "medium_load", "heavy_load"]:
            test_data = report["test_summary"][test_name]
            print(f"\n📈 {test_name.upper().replace('_', ' ')} RESULTS:")
            print(f"   Success Rate: {test_data['success_rate']:.1%}")
            print(f"   Avg Execution Time: {test_data['avg_execution_time']:.3f}s")
            print(f"   Connection Delta: {test_data['avg_connection_delta']:.2f}")
            print(f"   Memory Delta: {test_data['avg_memory_delta']:.2f} MB")
        
        # Overall assessment
        print(f"\n🎯 OVERALL ASSESSMENT:")
        issues = []
        if overall['connection_leak_detected']:
            issues.append("Connection leaks detected")
        if overall['memory_leak_detected']:
            issues.append("Memory leaks detected")
        if overall['performance_degradation']:
            issues.append("Performance degradation detected")
        if overall['success_rate'] < 0.95:
            issues.append("Low success rate")
        
        if not issues:
            print("   ✅ ALL TESTS PASSED - No connection leaks detected!")
        else:
            print("   ❌ ISSUES DETECTED:")
            for issue in issues:
                print(f"      - {issue}")
        
        print("\n" + "="*80)

def main():
    """Main test function."""
    
    # Look for config file in the vitalgraphclient_config directory
    config_dir = Path(__file__).parent.parent.parent / "vitalgraphclient_config"
    config_file = config_dir / "vitalgraphclient-config.yaml"
    
    config_path = None
    if config_file.exists():
        config_path = str(config_file)
        logger.info(f"Found config file: {config_path}")
    else:
        logger.info("No config file found, will use defaults")
    
    tester = ConnectionLeakTester(config_path=config_path)
    
    # Setup test environment
    if not tester.setup_test_environment():
        logger.error("Failed to setup test environment")
        return
    
    try:
        # Run full test suite
        report = tester.run_full_test_suite()
        
        # Print results
        tester.print_test_report(report)
        
        # Save detailed results to file
        with open("connection_leak_test_results.json", "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info("📄 Detailed results saved to connection_leak_test_results.json")
        
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        raise
    
    finally:
        # Cleanup
        tester.cleanup()

if __name__ == "__main__":
    main()
