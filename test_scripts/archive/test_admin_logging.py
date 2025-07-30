#!/usr/bin/env python3
"""
Test script for VitalGraphDB Admin logging level functionality.
Tests both command-line argument and REPL set command.
"""

import sys
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.admin_cmd.vitalgraphdb_admin_cmd import VitalGraphDBAdminREPL, setup_logging


def test_command_line_logging():
    """Test command-line logging level configuration."""
    print("🧪 Testing command-line logging level configuration...")
    
    # Test different logging levels
    test_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    
    for level in test_levels:
        print(f"\n📊 Testing logging level: {level}")
        
        # Setup logging with the specified level
        setup_logging(level)
        
        # Get the root logger level
        root_logger = logging.getLogger()
        current_level = logging.getLevelName(root_logger.level)
        
        print(f"✅ Root logger level set to: {current_level}")
        
        # Test specific VitalGraph loggers
        vitalgraph_loggers = [
            'vitalgraph.rdf.rdf_utils',
            'vitalgraph.ops.graph_import_op',
            'vitalgraph.db.postgresql.postgresql_db_impl'
        ]
        
        for logger_name in vitalgraph_loggers:
            logger = logging.getLogger(logger_name)
            logger_level = logging.getLevelName(logger.level)
            print(f"  - {logger_name}: {logger_level}")
        
        # Test actual logging at different levels
        print(f"  Testing actual log output at {level} level:")
        test_logger = logging.getLogger('test_logger')
        test_logger.debug("  🐛 DEBUG message")
        test_logger.info("  ℹ️  INFO message")
        test_logger.warning("  ⚠️  WARNING message")
        test_logger.error("  ❌ ERROR message")
        test_logger.critical("  🚨 CRITICAL message")


def test_repl_set_command():
    """Test REPL set command for logging level."""
    print("\n🧪 Testing REPL set command for logging level...")
    
    # Create REPL instance with default logging level
    repl = VitalGraphDBAdminREPL(log_level="INFO")
    print(f"📊 Initial logging level: {repl.log_level}")
    
    # Test set command with valid levels
    test_cases = [
        (["log-level", "DEBUG"], True, "DEBUG"),
        (["log-level", "WARNING"], True, "WARNING"),
        (["log-level", "ERROR"], True, "ERROR"),
        (["log-level", "CRITICAL"], True, "CRITICAL"),
        (["log-level", "INFO"], True, "INFO"),
    ]
    
    for args, should_succeed, expected_level in test_cases:
        print(f"\n📝 Testing: set {' '.join(args)};")
        result = repl.cmd_set(args)
        
        if should_succeed:
            if result and repl.log_level == expected_level:
                print(f"✅ Success: Logging level set to {expected_level}")
                
                # Verify actual logger levels
                root_logger = logging.getLogger()
                current_level = logging.getLevelName(root_logger.level)
                print(f"  Root logger level: {current_level}")
            else:
                print(f"❌ Failed: Expected level {expected_level}, got {repl.log_level}")
        else:
            print(f"⚠️  Expected failure: {result}")
    
    # Test invalid cases
    print("\n📝 Testing invalid cases:")
    invalid_cases = [
        ([], "No arguments"),
        (["log-level"], "Missing value"),
        (["log-level", "INVALID"], "Invalid level"),
        (["unknown-option", "value"], "Unknown option"),
    ]
    
    for args, description in invalid_cases:
        print(f"  Testing {description}: set {' '.join(args)};")
        result = repl.cmd_set(args)
        print(f"    Result: {'✅ Handled correctly' if result else '❌ Unexpected failure'}")


def test_help_command():
    """Test that help command shows the set command."""
    print("\n🧪 Testing help command includes set command...")
    
    repl = VitalGraphDBAdminREPL()
    
    # Capture help output
    import io
    from contextlib import redirect_stdout
    
    help_output = io.StringIO()
    with redirect_stdout(help_output):
        repl.cmd_help([])
    
    help_text = help_output.getvalue()
    
    # Check for set command documentation
    if "set log-level" in help_text and "Configuration:" in help_text:
        print("✅ Help command includes set command documentation")
    else:
        print("❌ Help command missing set command documentation")
        print("Help text preview:")
        print(help_text[:500] + "..." if len(help_text) > 500 else help_text)


def main():
    """Run all logging tests."""
    print("🚀 VitalGraphDB Admin Logging Level Tests")
    print("=" * 50)
    
    try:
        test_command_line_logging()
        test_repl_set_command()
        test_help_command()
        
        print("\n" + "=" * 50)
        print("✅ All logging level tests completed!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
