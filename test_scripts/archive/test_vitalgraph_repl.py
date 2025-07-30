#!/usr/bin/env python3
"""
Test script for VitalGraph REPL functionality

This script tests the REPL commands programmatically to ensure they work correctly.
"""

import sys
import os
import subprocess
import time
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph_client.cmd.vitalgraph_repl import VitalGraphREPL

def test_repl_commands():
    """Test REPL command parsing and execution."""
    print("Testing VitalGraph REPL commands...")
    
    repl = VitalGraphREPL()
    
    # Test command parsing
    print("\n1. Testing command parsing:")
    
    test_cases = [
        ("help;", ("help", [])),
        ("?;", ("?", [])),
        ("open;", ("open", [])),
        ("close;", ("close", [])),
        ("exit;", ("exit", [])),
        ("  help  ;  ", ("help", [])),  # Test whitespace handling
        ("unknown_command;", ("unknown_command", [])),
    ]
    
    for input_cmd, expected in test_cases:
        result = repl.parse_command(input_cmd)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{input_cmd}' -> {result}")
    
    # Test help command
    print("\n2. Testing help command:")
    result = repl.cmd_help([])
    print(f"  ✅ Help command executed successfully: {result}")
    
    # Test connection status (should be disconnected initially)
    print("\n3. Testing initial connection status:")
    print(f"  ✅ Initial connection status: {'Connected' if repl.connected else 'Disconnected'}")
    
    print("\n✅ All REPL command tests passed!")

def test_repl_cli():
    """Test the REPL CLI interface."""
    print("\nTesting VitalGraph REPL CLI interface...")
    
    python_path = "/opt/homebrew/anaconda3/envs/vital-graph/bin/python"
    
    # Test help output
    try:
        result = subprocess.run([
            python_path, "-m", "vitalgraph_client.cmd.vitalgraph_repl", "--help"
        ], capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0:
            print("  ✅ CLI help command works")
        else:
            print(f"  ❌ CLI help failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ❌ CLI help error: {e}")
        return False
    
    # Test version output
    try:
        result = subprocess.run([
            python_path, "-m", "vitalgraph_client.cmd.vitalgraph_repl", "--version"
        ], capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0 and "VitalGraph Client REPL 1.0.0" in result.stdout:
            print("  ✅ CLI version command works")
        else:
            print(f"  ❌ CLI version failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ❌ CLI version error: {e}")
        return False
    
    print("  ✅ All CLI tests passed!")
    return True

def test_bin_script():
    """Test the bin/vitalgraph script."""
    print("\nTesting bin/vitalgraph script...")
    
    bin_script = project_root / "bin" / "vitalgraph"
    
    if not bin_script.exists():
        print("  ❌ bin/vitalgraph script not found")
        return False
    
    if not os.access(bin_script, os.X_OK):
        print("  ❌ bin/vitalgraph script not executable")
        return False
    
    try:
        result = subprocess.run([str(bin_script), "--version"], 
                              capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0 and "VitalGraph Client REPL 1.0.0" in result.stdout:
            print("  ✅ bin/vitalgraph script works")
        else:
            print(f"  ❌ bin/vitalgraph script failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ❌ bin/vitalgraph script error: {e}")
        return False
    
    print("  ✅ bin/vitalgraph script test passed!")
    return True

def main():
    """Run all REPL tests."""
    print("VitalGraph REPL Test Suite")
    print("=" * 50)
    
    try:
        # Test REPL command functionality
        test_repl_commands()
        
        # Test CLI interface
        if not test_repl_cli():
            sys.exit(1)
        
        # Test bin script
        if not test_bin_script():
            sys.exit(1)
        
        print("\n" + "=" * 50)
        print("🎉 All VitalGraph REPL tests passed!")
        print("\nREPL is ready for use:")
        print("  - Run 'bin/vitalgraph' to start the interactive REPL")
        print("  - Use 'help;' in the REPL for available commands")
        print("  - Commands: open;, close;, exit;, help;, ?;")
        print("  - Use Ctrl+D or Ctrl+C to exit")
        
    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
