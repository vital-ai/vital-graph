#!/usr/bin/env python3
"""
VitalGraph Client REPL

Interactive command-line interface for VitalGraph using the client library.
Provides a REPL environment for interacting with VitalGraph servers.
"""

import argparse
import sys
import signal
from typing import Optional
from pathlib import Path

import click
from click_repl import repl
from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import CompleteStyle

from vitalgraph_client.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError


class VitalGraphREPL:
    """VitalGraph REPL implementation with client management."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.client: Optional[VitalGraphClient] = None
        self.connected = False
        self.config_path = config_path
        
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(sig, frame):
            if self.client and self.connected:
                print("\nClosing connection...")
                try:
                    self.client.close()
                except Exception as e:
                    print(f"Error closing connection: {e}")
            print("Goodbye!")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
    
    def parse_command(self, command_line: str) -> tuple[str, list[str]]:
        """Parse a command line into command and arguments."""
        # Remove trailing semicolon if present
        if command_line.strip().endswith(';'):
            command_line = command_line.strip()[:-1]
        
        parts = command_line.strip().split()
        if not parts:
            return "", []
        
        return parts[0].lower(), parts[1:]
    
    def execute_command(self, command_line: str) -> bool:
        """Execute a REPL command. Returns False if should exit."""
        if not command_line.strip():
            return True
            
        command, args = self.parse_command(command_line)
        
        if command in ['exit', 'quit']:
            return self.cmd_exit(args)
        elif command == 'open':
            return self.cmd_open(args)
        elif command == 'close':
            return self.cmd_close(args)
        elif command in ['help', '?']:
            return self.cmd_help(args)
        else:
            print(f"Unknown command: {command}")
            print("Type 'help;' or '?;' for available commands.")
            return True
    
    def cmd_exit(self, args: list[str]) -> bool:
        """Exit the REPL."""
        if self.client and self.connected:
            print("Closing connection...")
            try:
                self.client.close()
                self.connected = False
            except Exception as e:
                print(f"Error closing connection: {e}")
        print("Goodbye!")
        return False
    
    def cmd_open(self, args: list[str]) -> bool:
        """Open connection to VitalGraph server."""
        if self.connected:
            print("Already connected. Use 'close;' first to disconnect.")
            return True
        
        try:
            if not self.client:
                # Use config path from command line or calculate default
                if self.config_path:
                    config_path = Path(self.config_path)
                    print(f"Using config file (from --config): {config_path}")
                else:
                    # Calculate default config path: bin directory + ../vitalgraphclient_config/vitalgraphclient-config.yaml
                    script_dir = Path(__file__).resolve().parent.parent.parent  # Go up to project root
                    config_path = script_dir / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
                    print(f"Using config file (default): {config_path}")
                
                # Verify config file exists
                if not config_path.exists():
                    raise VitalGraphClientError(f"Config file not found: {config_path}")
                
                self.client = VitalGraphClient(str(config_path))
            
            print("Connecting to VitalGraph server...")
            self.client.open()
            self.connected = True
            print("✅ Connected successfully!")
            
        except VitalGraphClientError as e:
            print(f"❌ Connection failed: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
        
        return True
    
    def cmd_close(self, args: list[str]) -> bool:
        """Close connection to VitalGraph server."""
        if not self.connected:
            print("Not connected.")
            return True
        
        try:
            if self.client:
                self.client.close()
                self.connected = False
                print("✅ Disconnected successfully!")
        except Exception as e:
            print(f"❌ Error closing connection: {e}")
        
        return True
    
    def cmd_help(self, args: list[str]) -> bool:
        """Show help information."""
        print("""
VitalGraph Client REPL Commands:

  open;     - Connect to VitalGraph server
  close;    - Disconnect from VitalGraph server  
  exit;     - Exit the REPL (also quit;)
  help;     - Show this help message
  ?;        - Show this help message

Notes:
  - All commands must end with a semicolon (;)
  - Use Ctrl+D to exit
  - Use Ctrl+C to interrupt and exit
  
Connection Status: {}
""".format("🟢 Connected" if self.connected else "🔴 Disconnected"))
        return True
    
    def run_repl(self):
        """Run the interactive REPL."""
        self.setup_signal_handlers()
        
        print("VitalGraph Client REPL")
        print("Type 'help;' or '?;' for commands, 'exit;' to quit, or Ctrl+D to exit.")
        print()
        
        # Setup command history
        history_file = Path.home() / ".vitalgraph_history"
        history = FileHistory(str(history_file))
        
        try:
            # Create REPL loop with prompt-toolkit for command history
            while True:
                try:
                    # Show connection status in prompt
                    status = "🟢" if self.connected else "🔴"
                    prompt_text = f"vitalgraph{status}> "
                    
                    # Use prompt-toolkit for better REPL experience
                    command_line = prompt(
                        prompt_text,
                        history=history,
                        complete_style=CompleteStyle.READLINE_LIKE
                    )
                    
                    if not self.execute_command(command_line):
                        break
                        
                except EOFError:
                    # Ctrl+D pressed
                    print()  # New line for clean output
                    if self.client and self.connected:
                        print("Closing connection...")
                        try:
                            self.client.close()
                        except Exception as e:
                            print(f"Error closing connection: {e}")
                    print("Goodbye!")
                    break
                except KeyboardInterrupt:
                    # Ctrl+C pressed - handled by signal handler
                    continue
                    
        except Exception as e:
            print(f"REPL error: {e}")
            sys.exit(1)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for VitalGraph REPL."""
    parser = argparse.ArgumentParser(
        description="VitalGraph Client REPL - Interactive command-line interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraph                    # Start REPL with default settings
  vitalgraph --config /path/to/config.yaml  # Use custom config file
  vitalgraph --version          # Show version information

REPL Commands:
  open;     - Connect to VitalGraph server
  close;    - Disconnect from server
  exit;     - Exit the REPL
  help;     - Show help
        """
    )
    
    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Path to VitalGraph client configuration file (default: auto-detected from project structure)"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="VitalGraph Client REPL 1.0.0"
    )
    
    return parser.parse_args()


def main():
    """Main entry point for VitalGraph client REPL."""
    args = parse_args()
    
    try:
        repl_instance = VitalGraphREPL(config_path=args.config)
        repl_instance.run_repl()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting REPL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
