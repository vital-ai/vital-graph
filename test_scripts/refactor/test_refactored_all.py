#!/usr/bin/env python3
"""
Refactored SPARQL Implementation Comprehensive Test Suite
========================================================

Runs all refactored test scripts to verify functional parity between
original and refactored SPARQL implementations.

This script is designed to be run after significant changes to ensure
no regressions have been introduced.

Test Scripts Included:
- test_refactored_graph_queries.py - GRAPH pattern queries
- test_refactored_filter_queries.py - Filter function queries
- test_refactored_select_queries.py - Basic SELECT queries
- test_refactored_union_queries.py - UNION pattern queries
- test_refactored_values_queries.py - VALUES clause queries
- test_refactored_agg_queries.py - Aggregate function queries
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

# Test script configurations
TEST_SCRIPTS = [
    {
        "name": "Graph Queries",
        "script": "test_refactored_graph_queries.py",
        "description": "GRAPH pattern queries and context handling"
    },
    {
        "name": "Filter Queries", 
        "script": "test_refactored_filter_queries.py",
        "description": "Filter functions (REGEX, CONTAINS, isURI, etc.)"
    },
    {
        "name": "BIND Queries",
        "script": "test_refactored_bind_only.py",
        "description": "BIND expressions and function composition (standalone validation)"
    },
    {
        "name": "CONSTRUCT Queries",
        "script": "test_refactored_construct_only.py",
        "description": "CONSTRUCT queries and RDF triple generation (standalone validation)"
    },
    {
        "name": "ASK & DESCRIBE Queries (Standalone)",
        "script": "test_refactored_ask_describe_only.py",
        "description": "Tests ASK and DESCRIBE queries in refactored implementation independently"
    },
    {
        "name": "Property Path Queries",
        "script": "test_refactored_property_path_queries.py", 
        "description": "Property paths (+, *, /, |, ~, !) and transitive relationships"
    },
    {
        "name": "Optional Queries",
        "script": "test_refactored_optional_queries.py",
        "description": "OPTIONAL patterns, BOUND function, nested optionals"
    },
    {
        "name": "Minus Queries",
        "script": "test_refactored_minus_queries.py",
        "description": "MINUS patterns, exclusion logic, nested minus"
    },
    {
        "name": "Lang/DT Queries",
        "script": "test_refactored_lang_dt_queries.py",
        "description": "LANG() and DATATYPE() functions, language tags, datatypes"
    },
    {
        "name": "Builtin Critical Functions",
        "script": "test_refactored_builtin_critical.py",
        "description": "BOUND, COALESCE, URI, ENCODE_FOR_URI, IF functions"
    },
    {
        "name": "Builtin String Functions",
        "script": "test_refactored_builtin_string.py",
        "description": "CONCAT, STR, SUBSTR, STRLEN, UCASE, LCASE, REPLACE, etc."
    },
    {
        "name": "Builtin Numeric Functions",
        "script": "test_refactored_builtin_numeric.py",
        "description": "ABS, CEIL, FLOOR, ROUND, RAND, mathematical operations"
    },
    {
        "name": "Builtin Type Functions",
        "script": "test_refactored_builtin_types.py",
        "description": "ISURI, ISLITERAL, ISNUMERIC, ISBLANK type checking"
    },
    {
        "name": "Select Queries",
        "script": "test_refactored_select_queries.py", 
        "description": "Basic SELECT queries and patterns"
    },
    {
        "name": "Union Queries",
        "script": "test_refactored_union_queries.py",
        "description": "UNION pattern queries and combinations"
    },
    {
        "name": "Values Queries",
        "script": "test_refactored_values_queries.py",
        "description": "VALUES clause queries and data binding"
    },
    {
        "name": "Aggregate Queries",
        "script": "test_refactored_agg_queries.py",
        "description": "Aggregate functions (COUNT, SUM, AVG, etc.)"
    }
]

def run_test_script(script_path: Path) -> Tuple[bool, str, float]:
    """Run a single test script and return success status, output, and duration."""
    start_time = time.time()
    
    try:
        # Use the same Python interpreter that's running this script
        python_executable = sys.executable
        
        result = subprocess.run(
            [python_executable, str(script_path)],
            cwd=script_path.parent.parent,  # Run from vital-graph root
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout per test
        )
        
        duration = time.time() - start_time
        success = result.returncode == 0
        
        # Combine stdout and stderr for full output
        output = result.stdout
        if result.stderr:
            output += "\n--- STDERR ---\n" + result.stderr
            
        return success, output, duration
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return False, "Test timed out after 5 minutes", duration
    except Exception as e:
        duration = time.time() - start_time
        return False, f"Error running test: {e}", duration

def extract_test_summary(output: str) -> Dict[str, any]:
    """Extract test summary information from script output."""
    summary = {
        "total_tests": 0,
        "passed_tests": 0,
        "success_rate": 0.0,
        "cache_info": ""
    }
    
    lines = output.split('\n')
    
    for line in lines:
        line = line.strip()
        
        # Look for test summary patterns
        if "Total tests:" in line:
            try:
                summary["total_tests"] = int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
                
        elif "Passed:" in line:
            try:
                summary["passed_tests"] = int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
                
        elif "Success rate:" in line:
            try:
                rate_str = line.split(":")[1].strip().replace("%", "")
                summary["success_rate"] = float(rate_str)
            except (ValueError, IndexError):
                pass
                
        elif "Final cache sizes:" in line or "Cache:" in line:
            summary["cache_info"] = line
    
    return summary

def print_header():
    """Print the test suite header."""
    print("🧪 REFACTORED SPARQL IMPLEMENTATION COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    print("Testing functional parity between original and refactored implementations")
    print("=" * 70)
    print(f"📅 Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🐍 Python: {sys.executable}")
    print()

def print_test_header(test_config: Dict[str, str], index: int, total: int):
    """Print header for individual test."""
    print(f"\n{'='*50}")
    print(f"🔬 TEST {index}/{total}: {test_config['name']}")
    print(f"📝 {test_config['description']}")
    print(f"📄 Script: {test_config['script']}")
    print(f"{'='*50}")

def print_test_result(success: bool, duration: float, summary: Dict[str, any]):
    """Print test result summary."""
    status = "✅ PASSED" if success else "❌ FAILED"
    print(f"\n📊 RESULT: {status} (⏱️ {duration:.1f}s)")
    
    if summary["total_tests"] > 0:
        print(f"   Tests: {summary['passed_tests']}/{summary['total_tests']} passed")
        print(f"   Success Rate: {summary['success_rate']:.1f}%")
    
    if summary["cache_info"]:
        print(f"   {summary['cache_info']}")

def print_final_summary(results: List[Tuple[Dict, bool, float, Dict]]):
    """Print final comprehensive summary."""
    print("\n" + "=" * 70)
    print("📈 COMPREHENSIVE TEST SUITE SUMMARY")
    print("=" * 70)
    
    total_scripts = len(results)
    passed_scripts = sum(1 for _, success, _, _ in results if success)
    total_duration = sum(duration for _, _, duration, _ in results)
    
    print(f"\n🎯 OVERALL RESULTS:")
    print(f"   Scripts Run: {total_scripts}")
    print(f"   Scripts Passed: {passed_scripts}")
    print(f"   Scripts Failed: {total_scripts - passed_scripts}")
    print(f"   Overall Success Rate: {(passed_scripts/total_scripts)*100:.1f}%")
    print(f"   Total Duration: {total_duration:.1f}s")
    
    print(f"\n📋 DETAILED RESULTS:")
    for test_config, success, duration, summary in results:
        status = "✅" if success else "❌"
        rate = f"{summary['success_rate']:.1f}%" if summary['success_rate'] > 0 else "N/A"
        tests = f"{summary['passed_tests']}/{summary['total_tests']}" if summary['total_tests'] > 0 else "N/A"
        print(f"   {status} {test_config['name']:<20} | {duration:>6.1f}s | {tests:>8} | {rate:>6}")
    
    # Identify problem areas
    failed_tests = [test_config for test_config, success, _, _ in results if not success]
    if failed_tests:
        print(f"\n⚠️  FAILED TEST CATEGORIES:")
        for test_config in failed_tests:
            print(f"   ❌ {test_config['name']}: {test_config['description']}")
        print(f"\n🔧 RECOMMENDATION: Focus on fixing the {len(failed_tests)} failed test categories above.")
    else:
        print(f"\n🎉 ALL TEST CATEGORIES PASSED!")
        print(f"✅ Refactored implementation has achieved functional parity with original.")
    
    print(f"\n📅 Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

async def main():
    """Main test runner function."""
    print_header()
    
    # Get the directory containing this script
    script_dir = Path(__file__).parent
    
    # Results storage
    results = []
    
    # Run each test script
    for i, test_config in enumerate(TEST_SCRIPTS, 1):
        print_test_header(test_config, i, len(TEST_SCRIPTS))
        
        script_path = script_dir / test_config["script"]
        
        # Check if script exists
        if not script_path.exists():
            print(f"❌ Script not found: {script_path}")
            summary = {"total_tests": 0, "passed_tests": 0, "success_rate": 0.0, "cache_info": ""}
            results.append((test_config, False, 0.0, summary))
            continue
        
        # Run the test script
        print(f"🚀 Running {test_config['script']}...")
        success, output, duration = run_test_script(script_path)
        
        # Extract summary information
        summary = extract_test_summary(output)
        
        # Print result
        print_test_result(success, duration, summary)
        
        # Store results
        results.append((test_config, success, duration, summary))
        
        # Print abbreviated output for failed tests
        if not success:
            print(f"\n📄 ERROR OUTPUT (last 20 lines):")
            output_lines = output.split('\n')
            for line in output_lines[-20:]:
                if line.strip():
                    print(f"   {line}")
    
    # Print final summary
    print_final_summary(results)
    
    # Return overall success status
    overall_success = all(success for _, success, _, _ in results)
    return overall_success

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test suite interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)