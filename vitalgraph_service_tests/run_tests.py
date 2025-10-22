#!/usr/bin/env python3
"""
VitalGraphServiceImpl Test Runner

Comprehensive test runner for VitalGraphServiceImpl test suite.
Provides options for running unit tests, integration tests, or all tests.
"""

import sys
import logging
import argparse
import unittest
from pathlib import Path

# Add the parent directory to the path so we can import vitalgraph modules
sys.path.insert(0, str(Path(__file__).parent.parent))


def setup_logging(level=logging.INFO):
    """
    Set up logging configuration for the test runner.
    
    Args:
        level: Logging level (default: INFO)
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def run_unit_tests(verbosity=2):
    """
    Run unit tests only.
    
    Args:
        verbosity: Test verbosity level (default: 2)
    
    Returns:
        TestResult object
    """
    print("=" * 60)
    print("Running VitalGraphServiceImpl Unit Tests")
    print("=" * 60)
    
    # Import test modules from the real client test file
    from test_vitalgraph_service_real import (
        TestServiceBasics,
        TestServiceLifecycle,
        TestGraphManagement,
        TestCRUDOperations,
        TestQueryOperations,
        TestErrorHandling
    )
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add unit test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestServiceBasics))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestServiceLifecycle))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestGraphManagement))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestCRUDOperations))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestQueryOperations))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestErrorHandling))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    return result


def run_integration_tests(verbosity=2):
    """
    Run integration tests only.
    
    Args:
        verbosity: Test verbosity level (default: 2)
    
    Returns:
        TestResult object
    """
    print("=" * 60)
    print("Running VitalGraphServiceImpl Integration Tests")
    print("=" * 60)
    print("Note: Integration tests require a running VitalGraph backend")
    print("=" * 60)
    
    # Import integration test modules
    from test_integration import (
        TestVitalGraphServiceIntegration,
        TestVitalGraphServicePerformance
    )
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add integration test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestVitalGraphServiceIntegration))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestVitalGraphServicePerformance))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    return result


def run_all_tests(verbosity=2):
    """
    Run all tests (unit and integration).
    
    Args:
        verbosity: Test verbosity level (default: 2)
    
    Returns:
        Tuple of (unit_result, integration_result)
    """
    print("=" * 60)
    print("Running All VitalGraphServiceImpl Tests")
    print("=" * 60)
    
    # Run unit tests first
    unit_result = run_unit_tests(verbosity)
    
    print("\n" + "=" * 60)
    print("Unit Tests Complete - Starting Integration Tests")
    print("=" * 60)
    
    # Run integration tests
    integration_result = run_integration_tests(verbosity)
    
    return unit_result, integration_result


def print_test_summary(unit_result=None, integration_result=None):
    """
    Print a summary of test results.
    
    Args:
        unit_result: Unit test results
        integration_result: Integration test results
    """
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    if unit_result:
        print(f"Unit Tests:")
        print(f"  - Tests run: {unit_result.testsRun}")
        print(f"  - Failures: {len(unit_result.failures)}")
        print(f"  - Errors: {len(unit_result.errors)}")
        print(f"  - Skipped: {len(unit_result.skipped)}")
        print(f"  - Success rate: {((unit_result.testsRun - len(unit_result.failures) - len(unit_result.errors)) / unit_result.testsRun * 100):.1f}%" if unit_result.testsRun > 0 else "  - No tests run")
    
    if integration_result:
        print(f"\nIntegration Tests:")
        print(f"  - Tests run: {integration_result.testsRun}")
        print(f"  - Failures: {len(integration_result.failures)}")
        print(f"  - Errors: {len(integration_result.errors)}")
        print(f"  - Skipped: {len(integration_result.skipped)}")
        print(f"  - Success rate: {((integration_result.testsRun - len(integration_result.failures) - len(integration_result.errors)) / integration_result.testsRun * 100):.1f}%" if integration_result.testsRun > 0 else "  - No tests run")
    
    print("=" * 60)


def main():
    """
    Main test runner function.
    """
    parser = argparse.ArgumentParser(
        description="VitalGraphServiceImpl Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py                    # Run unit tests only
  python run_tests.py --unit             # Run unit tests only
  python run_tests.py --integration      # Run integration tests only
  python run_tests.py --all              # Run all tests
  python run_tests.py --verbose          # Run with verbose output
  python run_tests.py --debug            # Run with debug logging
        """
    )
    
    parser.add_argument(
        '--unit',
        action='store_true',
        help='Run unit tests only (default)'
    )
    
    parser.add_argument(
        '--integration',
        action='store_true',
        help='Run integration tests only'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='Run all tests (unit and integration)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Verbose test output'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Minimal test output'
    )
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(log_level)
    
    # Set verbosity
    if args.quiet:
        verbosity = 0
    elif args.verbose:
        verbosity = 2
    else:
        verbosity = 1
    
    # Determine which tests to run
    if args.integration:
        result = run_integration_tests(verbosity)
        print_test_summary(integration_result=result)
        return 0 if result.wasSuccessful() else 1
    elif args.all:
        unit_result, integration_result = run_all_tests(verbosity)
        print_test_summary(unit_result, integration_result)
        return 0 if (unit_result.wasSuccessful() and integration_result.wasSuccessful()) else 1
    else:
        # Default: run unit tests only
        result = run_unit_tests(verbosity)
        print_test_summary(unit_result=result)
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
