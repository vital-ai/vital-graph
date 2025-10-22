#!/usr/bin/env python3
"""
SPARQL Query Endpoint Performance Test

Performance test script for VitalGraph SPARQL query endpoints.
Tests query performance by running the same query pattern multiple times
with different search terms and tracking timing statistics.

UPDATED: Now uses typed client methods with SPARQLQueryResponse models 
instead of direct response handling for full type safety.
"""

import sys
import time
import statistics
import random
from pathlib import Path
from typing import List, Dict, Any

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.sparql_model import SPARQLQueryResponse, SPARQLQueryRequest

# Test configuration
BASE_URL = "http://localhost:8001"
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"  # Use the WordNet graph
CONFIG_PATH = "/Users/hadfield/Local/vital-git/vital-graph/vitalgraphclient_config/vitalgraphclient-config.yaml"
N = 100  # Number of queries to run

# Sample search terms to use in queries
SEARCH_TERMS = [
    "happy", "sad", "excited", "calm", "angry", "peaceful", "joyful", "worried",
    "confident", "nervous", "relaxed", "stressed", "content", "frustrated", 
    "optimistic", "pessimistic", "energetic", "tired", "focused", "distracted",
    "grateful", "disappointed", "hopeful", "anxious", "proud", "embarrassed",
    "curious", "bored", "motivated", "lazy", "creative", "logical"
]

class SPARQLQueryPerformanceTester:
    """Performance tester for SPARQL query endpoints."""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client = None
        self.query_times = []
        
    def connect(self) -> bool:
        """Connect to VitalGraph server.
        
        Returns:
            bool: True if connection was successful, False otherwise
        """
        print("🔐 Connecting to VitalGraph server...")
        try:
            self.client = VitalGraphClient(CONFIG_PATH)
            self.client.open()
            print(f"   ✅ Connected to {self.base_url}")
            return True
        except Exception as e:
            print(f"   ❌ Connection failed: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from VitalGraph server."""
        if self.client:
            self.client.close()
            print("   🔌 Disconnected from server")
    
    def run_performance_test(self, num_queries: int = 100) -> Dict[str, Any]:
        """
        Run performance test with multiple queries.
        
        Args:
            num_queries: Number of queries to execute
            
        Returns:
            Dictionary with performance statistics
        """
        print(f"\n🚀 Starting performance test with {num_queries} queries...")
        print(f"   Target graph: {GRAPH_URI}")
        print(f"   Search terms pool: {len(SEARCH_TERMS)} terms")
        
        self.query_times = []
        successful_queries = 0
        failed_queries = 0
        
        for i in range(num_queries):
            # Select a random search term
            search_term = random.choice(SEARCH_TERMS)
            
            # Build the SPARQL query
            query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                SELECT ?entity ?name ?edge ?connected WHERE {{
                    GRAPH <{GRAPH_URI}> {{
                        ?entity rdf:type haley:KGEntity .
                        ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
                        ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?entity .
                        ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?connected .
                    }}
                    FILTER(CONTAINS(?name, "{search_term}"))
                }}
            """
            
            # Execute query and measure time
            start_time = time.time()
            try:
                query_request = SPARQLQueryRequest(query=query, format="json")
                result: SPARQLQueryResponse = self.client.execute_sparql_query(SPACE_ID, query_request)
                end_time = time.time()
                
                query_time = end_time - start_time
                self.query_times.append(query_time)
                successful_queries += 1
                
                # Count results using typed response
                result_count = 0
                if result and result.results and result.results.bindings:
                    result_count = len(result.results.bindings)
                
                # Log individual query details
                print(f"   Query {i + 1:3d}: '{search_term:12s}' -> {result_count:3d} results ({query_time:.3f}s)")
                
                # Progress indicator every 10 queries
                if (i + 1) % 10 == 0:
                    print(f"   📊 Completed {i + 1}/{num_queries} queries (avg: {statistics.mean(self.query_times):.3f}s)")
                    
            except Exception as e:
                end_time = time.time()
                failed_queries += 1
                print(f"   ⚠️  Query {i + 1} failed with term '{search_term}': {e}")
        
        # Calculate statistics
        if self.query_times:
            stats = {
                'total_queries': num_queries,
                'successful_queries': successful_queries,
                'failed_queries': failed_queries,
                'total_time': sum(self.query_times),
                'average_time': statistics.mean(self.query_times),
                'median_time': statistics.median(self.query_times),
                'min_time': min(self.query_times),
                'max_time': max(self.query_times),
                'std_deviation': statistics.stdev(self.query_times) if len(self.query_times) > 1 else 0,
                'queries_per_second': successful_queries / sum(self.query_times) if sum(self.query_times) > 0 else 0
            }
        else:
            stats = {
                'total_queries': num_queries,
                'successful_queries': 0,
                'failed_queries': failed_queries,
                'total_time': 0,
                'average_time': 0,
                'median_time': 0,
                'min_time': 0,
                'max_time': 0,
                'std_deviation': 0,
                'queries_per_second': 0
            }
        
        return stats
    
    def print_performance_report(self, stats: Dict[str, Any]) -> None:
        """Print a detailed performance report."""
        print("\n" + "=" * 60)
        print("📊 SPARQL QUERY PERFORMANCE REPORT")
        print("   Using typed SPARQLQueryResponse models for full type safety")
        print("=" * 60)
        
        print(f"\n🎯 Test Summary:")
        print(f"   Total queries executed: {stats['total_queries']}")
        print(f"   Successful queries: {stats['successful_queries']}")
        print(f"   Failed queries: {stats['failed_queries']}")
        print(f"   Success rate: {(stats['successful_queries'] / stats['total_queries'] * 100):.1f}%")
        
        if stats['successful_queries'] > 0:
            print(f"\n⏱️  Timing Statistics:")
            print(f"   Total execution time: {stats['total_time']:.3f}s")
            print(f"   Average query time: {stats['average_time']:.3f}s")
            print(f"   Median query time: {stats['median_time']:.3f}s")
            print(f"   Fastest query: {stats['min_time']:.3f}s")
            print(f"   Slowest query: {stats['max_time']:.3f}s")
            print(f"   Standard deviation: {stats['std_deviation']:.3f}s")
            
            print(f"\n🚀 Performance Metrics:")
            print(f"   Queries per second: {stats['queries_per_second']:.2f}")
            print(f"   Milliseconds per query: {stats['average_time'] * 1000:.1f}ms")
            
            # Performance assessment
            if stats['average_time'] < 0.1:
                performance = "🟢 EXCELLENT"
            elif stats['average_time'] < 0.5:
                performance = "🟡 GOOD"
            elif stats['average_time'] < 1.0:
                performance = "🟠 FAIR"
            else:
                performance = "🔴 SLOW"
            
            print(f"   Performance rating: {performance}")
            
            # Distribution analysis
            fast_queries = sum(1 for t in self.query_times if t < stats['average_time'])
            slow_queries = len(self.query_times) - fast_queries
            
            print(f"\n📈 Distribution Analysis:")
            print(f"   Queries faster than average: {fast_queries} ({fast_queries/len(self.query_times)*100:.1f}%)")
            print(f"   Queries slower than average: {slow_queries} ({slow_queries/len(self.query_times)*100:.1f}%)")
            
            # Percentile analysis
            if len(self.query_times) >= 10:
                sorted_times = sorted(self.query_times)
                p95 = sorted_times[int(0.95 * len(sorted_times))]
                p99 = sorted_times[int(0.99 * len(sorted_times))]
                
                print(f"\n📊 Percentile Analysis:")
                print(f"   95th percentile: {p95:.3f}s")
                print(f"   99th percentile: {p99:.3f}s")
        
        print("\n" + "=" * 60)

def main() -> int:
    """Main function to run the performance test.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    print("🧪 VitalGraph SPARQL Query Endpoint Performance Test")
    print("   Using typed SPARQLQueryResponse models for full type safety")
    print("=" * 60)
    
    # Use constant N for number of queries
    num_queries = N
    print(f"Running {num_queries} queries...")
    
    # Initialize tester
    tester = SPARQLQueryPerformanceTester()
    
    try:
        # Connect to server
        if not tester.connect():
            return 1
        
        # Run performance test
        stats = tester.run_performance_test(num_queries)
        
        # Print results
        tester.print_performance_report(stats)
        
        # Disconnect
        tester.disconnect()
        
        print("\n✅ Performance test completed successfully with typed client methods!")
        print("   Used SPARQLQueryResponse models for full type safety.")
        return 0
        
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        tester.disconnect()
        return 1
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        tester.disconnect()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
