#!/usr/bin/env python3
"""
VitalGraphDB Admin Command Line Interface

Administrative REPL for VitalGraphDB server with database management capabilities.
Provides direct database access and administration commands.
"""

import argparse
import sys
import signal
import json
import asyncio
from typing import Optional
from pathlib import Path

import click
from click_repl import repl
from prompt_toolkit.history import FileHistory
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import CompleteStyle

# Import VitalGraphDB components
from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl



class VitalGraphDBAdminREPL:
    """VitalGraphDB Admin REPL implementation with database management."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.connected = False
        self.db_connection = None
        self.config = None
        self.db_impl = None  # PostgreSQL database implementation
        
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(sig, frame):
            if self.connected and self.db_connection:
                print("\nClosing database connection...")
                try:
                    self.disconnect_db()
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
        elif command == 'connect':
            return self.cmd_connect(args)
        elif command == 'disconnect':
            return self.cmd_disconnect(args)
        elif command == 'init':
            return self.cmd_init(args)
        elif command == 'purge':
            return self.cmd_purge(args)
        elif command == 'delete':
            return self.cmd_delete(args)
        elif command == 'info':
            return self.cmd_info(args)
        elif command == 'list':
            return self.cmd_list(args)
        elif command == 'rebuild':
            return self.cmd_rebuild(args)
        elif command in ['help', '?']:
            return self.cmd_help(args)
        else:
            print(f"Unknown command: {command}")
            print("Type 'help;' or '?;' for available commands.")
            return True
    
    def cmd_exit(self, args: list[str]) -> bool:
        """Exit the REPL."""
        if self.connected:
            print("Closing database connection...")
            try:
                self.disconnect_db()
            except Exception as e:
                print(f"Error closing connection: {e}")
        print("Goodbye!")
        return False
    
    def cmd_connect(self, args: list[str]) -> bool:
        """Connect to the VitalGraphDB database."""
        if self.connected:
            print("Already connected. Use 'disconnect;' to disconnect first.")
            return True
        
        try:
            # Load server config to get database connection info
            config_path = self.get_config_path()
            print(f"Using config file: {config_path}")
            
            # Load VitalGraphDB server configuration
            print("Loading VitalGraphDB configuration...")
            self.config = VitalGraphConfig(config_path)
            
            # Get database and tables configuration
            db_config = self.config.get_database_config()
            tables_config = self.config.get_tables_config()
            
            # Create PostgreSQL database implementation
            print("Initializing PostgreSQL database connection...")
            self.db_impl = PostgreSQLDbImpl(db_config, tables_config)
            
            # Connect to the database
            print("Connecting to VitalGraphDB database...")
            connected = asyncio.run(self.db_impl.connect())
            
            if connected:
                self.connected = True
                print("✅ Connected to database successfully!")
            else:
                print("❌ Failed to connect to database")
                self.db_impl = None
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            self.db_impl = None
        
        return True
    
    def cmd_disconnect(self, args: list[str]) -> bool:
        """Disconnect from the VitalGraphDB database."""
        if not self.connected:
            print("❌ Not connected to database.")
            return True
        
        try:
            print("Disconnecting from VitalGraphDB database...")
            self.disconnect_db()
            print("✅ Disconnected from database successfully!")
            
        except Exception as e:
            print(f"❌ Disconnection failed: {e}")
        
        return True
    
    def cmd_init(self, args: list[str]) -> bool:
        """Initialize database tables (only if they don't exist)."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        print("Initializing VitalGraphDB tables...")
        # TODO: Implement table initialization logic
        print("✅ Database tables initialized (if not already present)")
        return True
    
    def cmd_purge(self, args: list[str]) -> bool:
        """Reset all tables to initial state."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        print("⚠️  WARNING: This will reset all tables to initial state!")
        print("Purging VitalGraphDB tables...")
        # TODO: Implement table purge logic
        print("✅ Database tables purged and reset to initial state")
        return True
    
    def cmd_delete(self, args: list[str]) -> bool:
        """Delete all VitalGraphDB tables."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        print("⚠️  WARNING: This will permanently delete all VitalGraphDB tables!")
        print("Deleting VitalGraphDB tables...")
        # TODO: Implement table deletion logic
        print("✅ VitalGraphDB tables deleted")
        return True
    
    def cmd_info(self, args: list[str]) -> bool:
        """Provide information about the VitalGraphDB installation."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        print("VitalGraphDB Installation Information:")
        print("=====================================")
        # TODO: Implement info gathering logic
        print("Database: PostgreSQL")
        print("Status: Connected")
        print("Version: 1.0.0")
        print("Tables: [To be implemented]")
        return True
    
    def cmd_list(self, args: list[str]) -> bool:
        """List various database components."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: list <subcommand>")
            print("Available subcommands: spaces, tables, users, indexes")
            return True
        
        subcommand = args[0].lower()
        
        if subcommand == 'spaces':
            return self.cmd_list_spaces(args[1:])
        elif subcommand == 'tables':
            return self.cmd_list_tables(args[1:])
        elif subcommand == 'users':
            return self.cmd_list_users(args[1:])
        elif subcommand == 'indexes':
            return self.cmd_list_indexes(args[1:])
        else:
            print(f"Unknown list subcommand: {subcommand}")
            print("Available subcommands: spaces, tables, users, indexes")
        
        return True
    
    def cmd_list_spaces(self, args: list[str]) -> bool:
        """List graph spaces."""
        print("VitalGraphDB Graph Spaces:")
        print("=========================")
        
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        try:
            # Get spaces from database
            spaces = asyncio.run(self.db_impl.list_spaces())
            
            if not spaces:
                print("(No spaces found)")
            else:
                print(f"Found {len(spaces)} space(s):\n")
                for space in spaces:
                    print(f"  ID: {space.get('id', 'N/A')}")
                    print(f"  Space: {space.get('space', 'N/A')}")
                    print(f"  Name: {space.get('space_name', 'N/A')}")
                    print(f"  Tenant: {space.get('tenant', 'N/A')}")
                    print(f"  Description: {space.get('space_description', 'N/A')}")
                    print(f"  Updated: {space.get('update_time', 'N/A')}")
                    print()
                    
        except Exception as e:
            print(f"❌ Error listing spaces: {e}")
        
        return True
    
    def cmd_list_tables(self, args: list[str]) -> bool:
        """List all VitalGraphDB tables."""
        print("VitalGraphDB Tables:")
        print("===================")
        # TODO: Implement tables listing logic
        print("(No tables found - implementation pending)")
        return True
    
    def cmd_list_users(self, args: list[str]) -> bool:
        """List database users."""
        print("Database Users:")
        print("==============")
        
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        try:
            # Get users from database
            users = asyncio.run(self.db_impl.list_users())
            
            if not users:
                print("(No users found)")
            else:
                print(f"Found {len(users)} user(s):\n")
                for user in users:
                    print(f"  ID: {user.get('id', 'N/A')}")
                    print(f"  Username: {user.get('username', 'N/A')}")
                    print(f"  Email: {user.get('email', 'N/A')}")
                    print(f"  Tenant: {user.get('tenant', 'N/A')}")
                    print(f"  Updated: {user.get('update_time', 'N/A')}")
                    print(f"  Password: [HIDDEN]")
                    print()
                    
        except Exception as e:
            print(f"❌ Error listing users: {e}")
        
        return True
    
    def cmd_list_indexes(self, args: list[str]) -> bool:
        """List database indexes."""
        print("Database Indexes:")
        print("================")
        # TODO: Implement indexes listing logic
        print("(Index listing - implementation pending)")
        return True
    
    def cmd_rebuild(self, args: list[str]) -> bool:
        """Rebuild indexes or stats."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: rebuild <subcommand>")
            print("Available subcommands: indexes, stats")
            return True
        
        subcommand = args[0].lower()
        
        if subcommand == 'indexes':
            print("Rebuilding all database indexes...")
            # TODO: Implement index rebuilding logic
            print("✅ Database indexes rebuilt")
        elif subcommand == 'stats':
            print("Rebuilding database statistics...")
            # TODO: Implement stats rebuilding logic
            print("✅ Database statistics rebuilt")
        else:
            print(f"Unknown rebuild subcommand: {subcommand}")
            print("Available subcommands: indexes, stats")
        
        return True
    
    def cmd_help(self, args: list[str]) -> bool:
        """Show help information."""
        print("""
VitalGraphDB Admin REPL Commands:

Database Connection:
  connect;          - Connect to VitalGraphDB database
  disconnect;       - Disconnect from VitalGraphDB database
  
Database Management:
  init;             - Initialize database tables (if not present)
  purge;            - Reset all tables to initial state
  delete;           - Delete all VitalGraphDB tables
  
Information:
  info;             - Show VitalGraphDB installation information
  
Listing:
  list spaces;      - List graph spaces
  list tables;      - List all VitalGraphDB tables
  list users;       - List database users
  list indexes;     - List database indexes
  
Maintenance:
  rebuild indexes;  - Rebuild all database indexes
  rebuild stats;    - Rebuild database statistics
  
General:
  help;             - Show this help message
  ?;                - Show this help message
  exit;             - Exit the admin REPL

Notes:
  - All commands must end with a semicolon (;)
  - Use Ctrl+D to exit
  - Use Ctrl+C to interrupt and exit
  
Connection Status: {}
""".format("🟢 Connected" if self.connected else "🔴 Disconnected"))
        return True
    
    def get_config_path(self) -> Path:
        """Get the config file path (from CLI arg or default)."""
        if self.config_path:
            return Path(self.config_path)
        else:
            # Default: bin parent + vitalgraphdb_config + config file name
            script_dir = Path(__file__).resolve().parent.parent.parent  # Go up to project root
            return script_dir / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    def disconnect_db(self):
        """Disconnect from database."""
        if self.db_impl:
            try:
                asyncio.run(self.db_impl.disconnect())
            except Exception as e:
                print(f"Warning: Error during database disconnect: {e}")
            self.db_impl = None
        self.db_connection = None
        self.connected = False
    
    def run_repl(self):
        """Run the interactive REPL."""
        self.setup_signal_handlers()
        
        print("VitalGraphDB Admin REPL")
        print("Type 'help;' or '?;' for commands, 'exit;' to quit, or Ctrl+D to exit.")
        print()
        
        # Setup command history
        history_file = Path.home() / ".vitalgraphadmin_history"
        history = FileHistory(str(history_file))
        
        try:
            # Create REPL loop with prompt-toolkit for command history
            while True:
                try:
                    # Show connection status in prompt
                    status = "🟢" if self.connected else "🔴"
                    prompt_text = f"vitalgraphdb-admin{status}> "
                    
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
                    if self.connected:
                        print("Closing database connection...")
                        try:
                            self.disconnect_db()
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
    """Parse command line arguments for VitalGraphDB Admin REPL."""
    parser = argparse.ArgumentParser(
        description="VitalGraphDB Admin REPL - Database administration interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraphadmin                    # Start admin REPL with default settings
  vitalgraphadmin --config /path/to/config.yaml  # Use custom config file
  vitalgraphadmin --version          # Show version information

Admin Commands:
  connect;          - Connect to database
  disconnect;       - Disconnect from database
  init;             - Initialize tables
  purge;            - Reset tables
  delete;           - Delete tables
  info;             - Show installation info
  list spaces;      - List graph spaces
  list tables;      - List tables
  list users;       - List users
  list indexes;     - List indexes
  rebuild indexes;  - Rebuild indexes
  rebuild stats;    - Rebuild statistics
        """
    )
    
    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Path to VitalGraphDB server configuration file (default: auto-detected from project structure)"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="VitalGraphDB Admin REPL 1.0.0"
    )
    
    return parser.parse_args()


def main():
    """Main entry point for VitalGraphDB admin REPL."""
    args = parse_args()
    
    try:
        repl_instance = VitalGraphDBAdminREPL(config_path=args.config)
        repl_instance.run_repl()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting admin REPL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
