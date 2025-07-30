#!/usr/bin/env python3
"""
Simple diagnostic test to check if logging is working at all
"""

import sys
import os
import logging
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Configure logging with maximum verbosity
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Test basic logging
print("=== LOGGING DIAGNOSTIC TEST ===")
print("Testing basic logging functionality...")

# Test root logger
logging.info("✅ Root logger test message")

# Test vitalgraph loggers specifically
vitalgraph_logger = logging.getLogger('vitalgraph.store.store')
vitalgraph_logger.setLevel(logging.DEBUG)
vitalgraph_logger.info("✅ VitalGraph SQL Store logger test message")

base_logger = logging.getLogger('vitalgraph.store.base')
base_logger.setLevel(logging.DEBUG)
base_logger.info("✅ VitalGraph SQL Base logger test message")

print("If you see the ✅ messages above, logging is working.")
print("If not, there's a logging configuration issue.")

# Now try to import VitalGraph and see if any logs appear
print("\n=== IMPORTING VITALGRAPH ===")
try:
    from vitalgraph.store.store import VitalGraphSQLStore
    print("✅ VitalGraphSQLStore imported successfully")
    
    # Try to create a store instance (without connecting)
    print("\n=== CREATING STORE INSTANCE ===")
    store = VitalGraphSQLStore(identifier="test")
    print("✅ VitalGraphSQLStore instance created")
    
    # Test if our logging additions work by calling a simple method
    print("\n=== TESTING METHOD CALLS ===")
    print("Calling store methods to see if logging appears...")
    
    # This should trigger some logging if our additions work
    try:
        # Just test the logger directly in the store
        store_logger = logging.getLogger('vitalgraph.store.store')
        store_logger.info("🔍 Direct logger test from store module")
        
        print("✅ Direct logger test completed")
    except Exception as e:
        print(f"❌ Error testing store methods: {e}")
        
except Exception as e:
    print(f"❌ Error importing VitalGraph: {e}")
    import traceback
    traceback.print_exc()

print("\n=== DIAGNOSTIC COMPLETE ===")
print("Check the output above to see which logging messages appeared.")
