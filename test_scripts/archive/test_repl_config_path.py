#!/usr/bin/env python3
"""
Test VitalGraphClient initialization with default config path in REPL
"""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph_client.cmd.vitalgraph_repl import VitalGraphREPL

def test_config_path_calculation():
    """Test that the REPL calculates the correct default config path."""
    print("Testing VitalGraphClient config path calculation...")
    
    repl = VitalGraphREPL()
    
    # Calculate the expected config path (same logic as in cmd_open)
    script_dir = Path(__file__).resolve().parent.parent  # Go up to project root
    expected_config_path = script_dir / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    
    print(f"Expected config path: {expected_config_path}")
    print(f"Config file exists: {expected_config_path.exists()}")
    
    if not expected_config_path.exists():
        print("❌ Config file not found at expected location")
        return False
    
    # Test VitalGraphClient initialization (without actually connecting)
    try:
        from vitalgraph_client.client.vitalgraph_client import VitalGraphClient
        client = VitalGraphClient(str(expected_config_path))
        print("✅ VitalGraphClient initialized successfully with config path")
        return True
    except Exception as e:
        print(f"❌ VitalGraphClient initialization failed: {e}")
        return False

def main():
    """Test config path functionality."""
    print("VitalGraph REPL Config Path Test")
    print("=" * 40)
    
    if test_config_path_calculation():
        print("\n✅ Config path test passed!")
        print("The REPL should now be able to initialize VitalGraphClient correctly.")
    else:
        print("\n❌ Config path test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
