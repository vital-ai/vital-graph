#!/usr/bin/env python3
"""
Test script for space ID length validation.

This script tests that the PostgreSQL identifier length validation
properly prevents space IDs that would cause index name truncation.
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils

def test_space_id_length_validation():
    """Test that space ID length validation works correctly."""
    
    print("🧪 TESTING SPACE ID LENGTH VALIDATION")
    print("=" * 50)
    
    # Test 1: Valid short space ID should pass
    print("\n1️⃣ Testing valid short space ID...")
    try:
        PostgreSQLSpaceUtils.validate_space_id("test_sm_123")
        print("✅ PASS: Short space ID accepted")
    except ValueError as e:
        print(f"❌ FAIL: Short space ID rejected: {e}")
        return False
    
    # Test 2: Space ID at the limit (10 chars) should pass
    print("\n2️⃣ Testing space ID at maximum length (10 chars)...")
    try:
        PostgreSQLSpaceUtils.validate_space_id("1234567890")  # Exactly 10 chars
        print("✅ PASS: 10-character space ID accepted")
    except ValueError as e:
        print(f"❌ FAIL: 10-character space ID rejected: {e}")
        return False
    
    # Test 3: Space ID over the limit should fail
    print("\n3️⃣ Testing space ID over maximum length (11+ chars)...")
    try:
        PostgreSQLSpaceUtils.validate_space_id("12345678901")  # 11 chars - should fail
        print("❌ FAIL: 11-character space ID was accepted (should have been rejected)")
        return False
    except ValueError as e:
        expected_msg = "is too long"
        if expected_msg in str(e):
            print(f"✅ PASS: 11-character space ID properly rejected: {e}")
        else:
            print(f"❌ FAIL: Wrong error message: {e}")
            return False
    
    # Test 4: Very long space ID should fail with clear message
    print("\n4️⃣ Testing very long space ID...")
    long_space_id = "test_space_manager_with_very_long_name_that_exceeds_limits"
    try:
        PostgreSQLSpaceUtils.validate_space_id(long_space_id)
        print("❌ FAIL: Very long space ID was accepted (should have been rejected)")
        return False
    except ValueError as e:
        expected_phrases = ["too long", "PostgreSQL", "identifier length", "10 characters"]
        error_msg = str(e)
        if all(phrase in error_msg for phrase in expected_phrases):
            print(f"✅ PASS: Very long space ID properly rejected with informative message")
            print(f"   Error: {e}")
        else:
            print(f"❌ FAIL: Error message missing expected information: {e}")
            return False
    
    # Test 5: Show what the problematic index name would look like
    print("\n5️⃣ Demonstrating why length limits are needed...")
    problematic_space_id = "test_space_manager_12345"
    global_prefix = "vitalgraph1"
    
    # Simulate the longest index name that would be generated
    table_prefix = f"{global_prefix}__{problematic_space_id}__"
    longest_index = f"idx_{table_prefix}_unlogged_term_text_gist_trgm"
    
    print(f"   Space ID: '{problematic_space_id}' ({len(problematic_space_id)} chars)")
    print(f"   Generated index name: '{longest_index}' ({len(longest_index)} chars)")
    print(f"   PostgreSQL limit: 63 characters")
    
    if len(longest_index) > 63:
        truncated = longest_index[:63]
        print(f"   Would be truncated to: '{truncated}' (collision risk!)")
        print("   ⚠️  This demonstrates why validation is necessary")
    else:
        print("   ✅ This would fit within PostgreSQL limits")
    
    return True

def main():
    """Run the space ID validation tests."""
    print("🚀 Starting Space ID Length Validation Tests")
    print("=" * 60)
    
    success = test_space_id_length_validation()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 ALL VALIDATION TESTS PASSED!")
        print("✅ Space ID length validation is working correctly")
        print("✅ Callers will get clear error messages for problematic space IDs")
        return 0
    else:
        print("❌ VALIDATION TESTS FAILED!")
        print("❌ Space ID length validation needs fixes")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
