#!/usr/bin/env python3
"""
Integration Test Runner for MockKGFramesEndpoint Integration Task.

This script runs both the existing KG endpoint enhancement tests and the new
MockKGFramesEndpoint integration tests to validate:
- VitalSigns integration patterns from MockKGEntitiesEndpoint
- Grouping URI enforcement for frame operations  
- isinstance() type checking and Property object handling
"""

import sys
import subprocess
from pathlib import Path

def run_test_file(test_file_path: str, description: str) -> bool:
    """Run a test file and return success status."""
    print(f"\n🚀 Running {description}")
    print("=" * 80)
    
    try:
        # Run the test file
        result = subprocess.run([
            sys.executable, test_file_path
        ], capture_output=True, text=True, cwd=Path(test_file_path).parent)
        
        # Print output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        # Return success status
        success = result.returncode == 0
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"\n{status} {description}")
        
        return success
        
    except Exception as e:
        print(f"❌ FAILED {description}: {e}")
        return False

def main():
    """Run all integration tests for MockKGFramesEndpoint integration task."""
    print("🧪 MockKGFramesEndpoint Integration Task - Test Suite")
    print("=" * 80)
    print("Testing VitalSigns patterns, Property handling, and grouping URI enforcement")
    
    # Test files to run
    test_files = [
        {
            "path": "/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_mock_client_test/test_kg_endpoint_enhancements.py",
            "description": "KG Endpoint Enhancements (with MockKGFrames integration tests)"
        },
        {
            "path": "/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_mock_client_test/test_mock_kgframes_integration.py", 
            "description": "MockKGFramesEndpoint Integration (VitalSigns patterns & Property handling)"
        }
    ]
    
    # Run all test files
    results = []
    for test_file in test_files:
        success = run_test_file(test_file["path"], test_file["description"])
        results.append({
            "description": test_file["description"],
            "success": success
        })
    
    # Print final summary
    print("\n" + "=" * 80)
    print("📊 FINAL TEST SUMMARY - MockKGFramesEndpoint Integration Task")
    print("=" * 80)
    
    passed_suites = 0
    for result in results:
        status = "✅ PASSED" if result["success"] else "❌ FAILED"
        print(f"{status} {result['description']}")
        if result["success"]:
            passed_suites += 1
    
    total_suites = len(results)
    print(f"\nTest Suites: {passed_suites}/{total_suites} passed")
    
    if passed_suites == total_suites:
        print("\n🎉 ALL INTEGRATION TESTS PASSED!")
        print("✅ MockKGFramesEndpoint integration task requirements validated:")
        print("   - VitalSigns integration patterns applied")
        print("   - Grouping URI enforcement working")
        print("   - isinstance() type checking implemented")
        print("   - Property object handling functional")
        return True
    else:
        print("\n⚠️  SOME INTEGRATION TESTS FAILED")
        print("❌ MockKGFramesEndpoint integration task needs attention")
        print("   Check the test output above for specific failures")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
