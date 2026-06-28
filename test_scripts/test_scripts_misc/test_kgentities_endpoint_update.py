#!/usr/bin/env python3
"""
Test script to verify the updated KGEntitiesEndpoint works correctly.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_import():
    """Test that the updated endpoint can be imported without errors."""
    try:
        from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
        print("✅ KGEntitiesEndpoint import successful")
        return True
    except Exception as e:
        print(f"❌ KGEntitiesEndpoint import failed: {e}")
        return False

def test_initialization():
    """Test that the endpoint can be initialized."""
    try:
        from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
        
        # Mock space manager and auth dependency
        class MockSpaceManager:
            def get_space(self, space_id):
                return None
        
        def mock_auth_dependency():
            return {"username": "test"}
        
        # Try to initialize
        endpoint = KGEntitiesEndpoint(MockSpaceManager(), mock_auth_dependency)
        print("✅ KGEntitiesEndpoint initialization successful")
        print(f"   - Router created: {endpoint.router is not None}")
        print(f"   - Grouping URI builder: {endpoint.grouping_uri_builder is not None}")
        print(f"   - Entity validator: {endpoint.entity_validator is not None}")
        print(f"   - Relations placeholder: {endpoint.relations is None}")
        return True
    except Exception as e:
        print(f"❌ KGEntitiesEndpoint initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("🧪 Testing Updated KGEntitiesEndpoint")
    print("=" * 50)
    
    tests = [
        ("Import Test", test_import),
        ("Initialization Test", test_initialization),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 {test_name}:")
        if test_func():
            passed += 1
        
    print("\n" + "=" * 50)
    print(f"🏁 Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed! KGEntitiesEndpoint update successful.")
        return True
    else:
        print("❌ Some tests failed. Check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
