#!/usr/bin/env python3
"""
Test VitalGraph REPL --config argument functionality
"""

import sys
import subprocess
from pathlib import Path

def test_config_argument():
    """Test the --config command-line argument."""
    print("Testing VitalGraph REPL --config argument...")
    
    python_path = "/opt/homebrew/anaconda3/envs/vital-graph/bin/python"
    project_root = Path(__file__).parent.parent
    
    # Test 1: Help shows --config option
    print("\n1. Testing --config in help output:")
    try:
        result = subprocess.run([
            python_path, "-m", "vitalgraph.client.cmd.vitalgraph_repl", "--help"
        ], capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0 and "--config CONFIG" in result.stdout:
            print("  ✅ --config argument appears in help")
        else:
            print("  ❌ --config argument missing from help")
            return False
    except Exception as e:
        print(f"  ❌ Help test error: {e}")
        return False
    
    # Test 2: Test with valid config file (default one)
    print("\n2. Testing with valid config file:")
    config_file = project_root / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    
    if not config_file.exists():
        print(f"  ❌ Default config file not found: {config_file}")
        return False
    
    try:
        # Test that we can specify the config file explicitly
        # We'll just test that the argument is accepted (not actually run the REPL)
        result = subprocess.run([
            python_path, "-m", "vitalgraph.client.cmd.vitalgraph_repl", 
            "--config", str(config_file), "--version"
        ], capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0:
            print(f"  ✅ --config argument accepted with valid file: {config_file}")
        else:
            print(f"  ❌ --config argument failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ❌ Config file test error: {e}")
        return False
    
    # Test 3: Test short form -c
    print("\n3. Testing short form -c:")
    try:
        result = subprocess.run([
            python_path, "-m", "vitalgraph.client.cmd.vitalgraph_repl", 
            "-c", str(config_file), "--version"
        ], capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0:
            print("  ✅ Short form -c works correctly")
        else:
            print(f"  ❌ Short form -c failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ❌ Short form test error: {e}")
        return False
    
    print("\n✅ All --config argument tests passed!")
    return True

def test_config_path_logic():
    """Test the config path logic in VitalGraphREPL class."""
    print("\nTesting VitalGraphREPL config path logic...")
    
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    from vitalgraph.client.cmd.vitalgraph_repl import VitalGraphREPL
    
    # Test 1: Default config path (None)
    print("\n1. Testing default config path:")
    repl_default = VitalGraphREPL(config_path=None)
    if repl_default.config_path is None:
        print("  ✅ Default config path is None")
    else:
        print(f"  ❌ Expected None, got: {repl_default.config_path}")
        return False
    
    # Test 2: Custom config path
    print("\n2. Testing custom config path:")
    custom_path = "/path/to/custom/config.yaml"
    repl_custom = VitalGraphREPL(config_path=custom_path)
    if repl_custom.config_path == custom_path:
        print(f"  ✅ Custom config path stored correctly: {custom_path}")
    else:
        print(f"  ❌ Expected {custom_path}, got: {repl_custom.config_path}")
        return False
    
    print("\n✅ All config path logic tests passed!")
    return True

def main():
    """Run all config argument tests."""
    print("VitalGraph REPL --config Argument Test Suite")
    print("=" * 50)
    
    try:
        # Test command-line argument functionality
        if not test_config_argument():
            sys.exit(1)
        
        # Test internal config path logic
        if not test_config_path_logic():
            sys.exit(1)
        
        print("\n" + "=" * 50)
        print("🎉 All --config argument tests passed!")
        print("\nThe --config argument is working correctly:")
        print("  - Use --config /path/to/config.yaml to specify custom config")
        print("  - Use -c /path/to/config.yaml as shorthand")
        print("  - Omit --config to use auto-detected default config")
        
    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
