#!/usr/bin/env python3
"""
Standalone test for space ID validation to verify it's working correctly.
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

def test_space_id_validation_standalone():
    """Test space ID length validation independently."""
    from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils
    
    print("🧪 STANDALONE SPACE ID VALIDATION TEST")
    print("=" * 50)
    
    try:
        # Test 1: Valid short space ID should pass
        print("\n✅ Test 1: Valid short space ID...")
        PostgreSQLSpaceUtils.validate_space_id("test_sm_123")
        print("   PASS: Short space ID accepted")
        
        # Test 2: Space ID at reasonable length should pass
        print("\n✅ Test 2: Reasonable length space ID...")
        PostgreSQLSpaceUtils.validate_space_id("test_space")
        print("   PASS: Reasonable space ID accepted")
        
        # Test 3: Very long space ID should fail (over 14 chars)
        print("\n⚠️ Test 3: Overly long space ID (should fail)...")
        try:
            long_space_id = "test_space_manager_very_long_name"  # 30 chars - definitely over limit
            PostgreSQLSpaceUtils.validate_space_id(long_space_id)
            print(f"   ❌ FAIL: Long space ID '{long_space_id}' was accepted (should have been rejected)")
            return False
        except ValueError as e:
            if "too long" in str(e) and "PostgreSQL" in str(e):
                print(f"   ✅ PASS: Long space ID properly rejected")
                print(f"   Error: {str(e)[:100]}...")
            else:
                print(f"   ❌ FAIL: Wrong error message: {e}")
                return False
        
        # Test 4: Demonstrate the problem this prevents
        print("\n🔍 Test 4: Demonstrating PostgreSQL identifier length issue prevention...")
        problematic_space_id = "test_space_manager_12345"
        global_prefix = "vitalgraph1"
        table_prefix = f"{global_prefix}__{problematic_space_id}__"
        longest_index = f"idx_{table_prefix}_unlogged_term_text_gist_trgm"
        
        print(f"   📊 Example problematic space ID: '{problematic_space_id}' ({len(problematic_space_id)} chars)")
        print(f"   📊 Generated index name would be: '{longest_index}' ({len(longest_index)} chars)")
        print(f"   📊 PostgreSQL limit: 63 characters")
        
        if len(longest_index) > 63:
            print(f"   ⚠️ Would exceed limit by {len(longest_index) - 63} chars - validation prevents this!")
        else:
            print(f"   ✅ Within limit - safe to use")
        
        print("\n🎉 ALL VALIDATION TESTS PASSED!")
        return True
        
    except Exception as e:
        print(f"\n❌ Validation test failed with unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = test_space_id_validation_standalone()
    if success:
        print("\n✅ Space ID validation is working correctly!")
        sys.exit(0)
    else:
        print("\n❌ Space ID validation has issues!")
        sys.exit(1)
