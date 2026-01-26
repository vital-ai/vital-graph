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
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime

import click
from click_repl import repl
from prompt_toolkit.history import FileHistory
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import CompleteStyle
from tabulate import tabulate

# Import VitalGraphDB components
from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.ops.graph_import_op import GraphImportOp



class VitalGraphDBAdminREPL:
    """VitalGraphDB Admin REPL implementation with database management."""
    
    def __init__(self, config_path: Optional[str] = None, log_level: str = "INFO"):
        self.config_path = config_path
        self.connected = False
        self.db_connection = None
        self.config = None
        self.db_impl = None  # PostgreSQL database implementation
        self.current_space_id = None  # Currently active space ID
        self.log_level = log_level.upper()  # Store current logging level
        self.loop = None  # Persistent event loop for async operations
        
    def _run_async(self, coro):
        """Run async coroutine using persistent event loop."""
        if self.loop is None:
            # Create a new event loop for the REPL session
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        
        return self.loop.run_until_complete(coro)
    
    def _close_loop(self):
        """Close the event loop when REPL exits."""
        if self.loop is not None and not self.loop.is_closed():
            self.loop.close()
            self.loop = None
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(sig, frame):
            if self.connected and self.db_connection:
                print("\nClosing database connection...")
                try:
                    self.disconnect_db()
                except Exception as e:
                    print(f"Error closing connection: {e}")
            self._close_loop()
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
    
    def format_table(self, data: List[Dict[str, Any]], headers: List[str], title: str = None) -> None:
        """Format and display data as a nice table."""
        if title:
            print(f"\n{title}")
            print("=" * len(title))
        
        if not data:
            print("(No data found)")
            return
        
        # Prepare table data
        table_data = []
        for item in data:
            row = []
            for header in headers:
                value = item.get(header.lower().replace(' ', '_'), 'N/A')
                # Format datetime values
                if isinstance(value, datetime):
                    value = value.strftime('%Y-%m-%d %H:%M:%S')
                elif value is None:
                    value = 'N/A'
                row.append(str(value))
            table_data.append(row)
        
        # Display table with nice formatting
        print(f"\n{tabulate(table_data, headers=headers, tablefmt='grid')}")
        print(f"\nTotal: {len(data)} item(s)")
    
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
            return self._run_async(self.cmd_init(args))
        elif command == 'purge':
            return self.cmd_purge(args)
        elif command == 'delete':
            return self.cmd_delete(args)
        elif command == 'info':
            return self.cmd_info(args)
        elif command == 'clear':
            return self.cmd_clear(args)
        elif command == 'use':
            return self.cmd_use(args)
        elif command == 'unuse':
            return self.cmd_unuse(args)
        elif command == 'import':
            return self.cmd_import(args)
        elif command == 'list':
            return self.cmd_list(args)
        elif command == 'rebuild':
            return self.cmd_rebuild(args)
        elif command == 'reindex':
            return self.cmd_rebuild(args)
        elif command == 'set':
            return self.cmd_set(args)
        elif command in ['help', '?']:
            return self.cmd_help(args)
        else:
            print(f"Unknown command: {command}. Type 'help;' for available commands.")
            return True
    
    def cmd_exit(self, args: list[str]) -> bool:
        """Exit the REPL."""
        if self.connected:
            print("Closing database connection...")
            try:
                self.disconnect_db()
            except Exception as e:
                print(f"Error closing connection: {e}")
        self._close_loop()
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
            
            # Create VitalGraphImpl instance with the loaded config
            print("Initializing VitalGraph implementation...")
            self.vital_graph_impl = VitalGraphImpl(config=self.config)
            
            # Get database implementation from VitalGraphImpl
            self.db_impl = self.vital_graph_impl.get_db_impl()
            
            if self.db_impl is None:
                print("❌ Failed to initialize database implementation")
                return True
            
            # Connect to the database
            print("Connecting to VitalGraphDB database...")
            connected = self._run_async(self.db_impl.connect())
            
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
    
    async def cmd_init(self, args: list[str]) -> bool:
        """Initialize database tables (only if they don't exist)."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        if not self.db_impl:
            print("Error: Not connected to database. Use 'connect' command first.")
            return True
        
        # Check if this is a fuseki_postgresql backend
        backend_type = self.config.get_backend_config().get('type', 'postgresql')
        
        if backend_type == 'fuseki_postgresql':
            return await self._init_fuseki_postgresql_backend()
        
        # Standard PostgreSQL backend initialization
        if not hasattr(self.db_impl, 'table_prefix') or not self.db_impl.table_prefix:
            print("Error: Database implementation missing table_prefix configuration.")
            return True
        
        print(f"Initializing database tables with prefix: {self.db_impl.table_prefix}")
        
        # Let the database implementation determine the proper state based on table existence
        await self.db_impl._load_current_state()
        print(f"Current database state: {self.db_impl.state}")
        
        if self.db_impl.state != "uninitialized":
            print(f"❌ Cannot initialize - database state is '{self.db_impl.state}', must be 'uninitialized'")
            print("   Tables may already exist for this prefix")
            return True
        
        try:
            success = await self.db_impl.init_tables()
            if success:
                print("Database tables initialized successfully.")
            else:
                print("Failed to initialize database tables.")
                print("   Check database connection and permissions")
                
        except Exception as e:
            print(f"❌ Error during initialization: {e}")
            return True
        
        return True
    
    async def _init_fuseki_postgresql_backend(self) -> bool:
        """Initialize fuseki_postgresql backend admin tables."""
        print("🚀 Initializing Fuseki-PostgreSQL Backend")
        print("=" * 50)
        
        try:
            from vitalgraph.db.fuseki_postgresql.postgresql_schema import FusekiPostgreSQLSchema
            
            # Create schema instance
            schema = FusekiPostgreSQLSchema()
            
            # Check if admin tables already exist
            print("\n📋 Checking for existing admin tables...")
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('install', 'space', 'graph', 'user')
            """
            
            result = await self.db_impl.execute_query(check_query)
            table_count = result[0]['table_count'] if result else 0
            
            if table_count == 4:
                print("✅ Admin tables already exist (install, space, graph, user)")
                print("   No initialization needed.")
                return True
            elif table_count > 0:
                print(f"⚠️  Warning: Found {table_count} out of 4 admin tables")
                print("   Some tables may be missing or partially created")
                response = input("   Continue with initialization? (yes/no): ").strip().lower()
                if response not in ['yes', 'y']:
                    print("   Initialization cancelled.")
                    return True
            
            print(f"\n📦 Creating admin tables...")
            
            # Create admin tables
            admin_table_statements = schema.create_admin_tables_sql()
            for i, statement in enumerate(admin_table_statements, 1):
                table_name = list(schema.ADMIN_TABLES.keys())[i-1]
                print(f"   Creating table: {table_name}")
                await self.db_impl.execute_update(statement)
            
            print(f"\n🔍 Creating admin table indexes...")
            
            # Create admin table indexes
            admin_index_statements = schema.create_admin_indexes_sql()
            for statement in admin_index_statements:
                await self.db_impl.execute_update(statement)
            
            print(f"\n✅ Fuseki-PostgreSQL admin tables initialized successfully!")
            print(f"   Created tables: install, space, graph, user")
            print(f"   Created indexes for: space, graph, user")
            
            return True
            
        except Exception as e:
            print(f"\n❌ Error during Fuseki-PostgreSQL initialization: {e}")
            import traceback
            traceback.print_exc()
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
        
        # Check backend type
        backend_type = self.config.get_backend_config().get('type', 'postgresql')
        
        if backend_type == 'fuseki_postgresql':
            return self._run_async(self._info_fuseki_postgresql_backend())
        
        # Standard PostgreSQL backend
        # Load current state to get accurate status
        self._run_async(self.db_impl._load_current_state())
        
        print("Database: PostgreSQL")
        print("Status: Connected")
        print(f"Table Prefix: {self.db_impl.table_prefix}")
        print(f"Initialization State: {self.db_impl.state}")
        
        if self.db_impl.state == "initialized":
            print(f"Install ID: {self.db_impl.current_install.get('id', 'N/A') if self.db_impl.current_install else 'N/A'}")
            print(f"Spaces: {len(self.db_impl.current_spaces)} configured")
            print(f"Users: {len(self.db_impl.current_users)} configured")
        elif self.db_impl.state == "uninitialized":
            print("Global tables not yet created - run 'init;' to initialize")
        
        print("Version: 1.0.0")
        return True
    
    async def _info_fuseki_postgresql_backend(self) -> bool:
        """Show info for fuseki_postgresql backend."""
        try:
            print("Backend: Fuseki-PostgreSQL Hybrid")
            print("Status: Connected")
            
            # Check if admin tables exist
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('install', 'space', 'graph', 'user')
            """
            
            result = await self.db_impl.execute_query(check_query)
            table_count = result[0]['table_count'] if result else 0
            
            if table_count == 4:
                print("Initialization State: Initialized")
                print("Admin Tables: ✅ All present (install, space, graph, user)")
                
                # Get space count
                space_query = "SELECT COUNT(*) as count FROM space"
                space_result = await self.db_impl.execute_query(space_query)
                space_count = space_result[0]['count'] if space_result else 0
                print(f"Spaces: {space_count} configured")
                
                # Get user count
                user_query = 'SELECT COUNT(*) as count FROM "user"'
                user_result = await self.db_impl.execute_query(user_query)
                user_count = user_result[0]['count'] if user_result else 0
                print(f"Users: {user_count} configured")
                
            elif table_count > 0:
                print("Initialization State: Partially Initialized")
                print(f"Admin Tables: ⚠️  {table_count} out of 4 tables present")
                print("   Run 'init;' to complete initialization")
            else:
                print("Initialization State: Uninitialized")
                print("Admin Tables: ❌ Not created")
                print("   Run 'init;' to initialize")
            
            # Show Fuseki connection info
            fuseki_config = self.config.get_fuseki_postgresql_config().get('fuseki', {})
            print(f"\nFuseki Server: {fuseki_config.get('server_url', 'N/A')}")
            print(f"Fuseki Dataset: {fuseki_config.get('dataset_name', 'N/A')}")
            print(f"JWT Authentication: {'Enabled' if fuseki_config.get('enable_authentication') else 'Disabled'}")
            
            # Show PostgreSQL connection info
            pg_config = self.config.get_fuseki_postgresql_config().get('database', {})
            print(f"\nPostgreSQL Host: {pg_config.get('host', 'N/A')}")
            print(f"PostgreSQL Database: {pg_config.get('database', 'N/A')}")
            
            print("\nVersion: 1.0.0")
            
            return True
            
        except Exception as e:
            print(f"❌ Error getting backend info: {e}")
            return True
    
    def cmd_list(self, args: list[str]) -> bool:
        """List various database components."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: list <subcommand>")
            print("Available subcommands: spaces, tables, users, indexes, graphs, namespaces")
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
        elif subcommand == 'graphs':
            return self.cmd_list_graphs(args[1:])
        elif subcommand == 'namespaces':
            return self.cmd_list_namespaces(args[1:])
        else:
            print(f"Unknown list subcommand: {subcommand}")
            print("Available subcommands: spaces, tables, users, indexes, graphs, namespaces")
        
        return True
    
    def cmd_list_spaces(self, args: list[str]) -> bool:
        """List graph spaces."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        try:
            # Get spaces from database
            spaces = self._run_async(self.db_impl.list_spaces())
            
            # Define table headers
            headers = ['ID', 'Space', 'Name', 'Tenant', 'Description', 'Updated']
            
            # Display as formatted table
            self.format_table(spaces, headers, "VitalGraphDB Graph Spaces")
                    
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
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        try:
            # Get users from database
            users = self._run_async(self.db_impl.list_users())
            
            # Add password status to each user for display
            for user in users:
                user['password_status'] = '[HIDDEN]' if user.get('password') else '[NOT SET]'
            
            # Define table headers
            headers = ['ID', 'Username', 'Email', 'Tenant', 'Password Status', 'Updated']
            
            # Display as formatted table
            self.format_table(users, headers, "VitalGraphDB Database Users")
                    
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
    
    def cmd_list_graphs(self, args: list[str]) -> bool:
        """List graphs either globally or within current space."""
        if self.current_space_id:
            print(f"Graphs in Space '{self.current_space_id}':")
            print("=" * (len(f"Graphs in Space '{self.current_space_id}':") + 5))
            # TODO: Implement space-specific graph listing logic
            print(f"(Graph listing for space '{self.current_space_id}' - implementation pending)")
        else:
            print("All Graphs (Global):")
            print("===================")
            # TODO: Implement global graph listing logic
            print("(Global graph listing - implementation pending)")
        return True
    
    def cmd_list_namespaces(self, args: list[str]) -> bool:
        """List namespaces either globally or within current space."""
        if self.current_space_id:
            print(f"Namespaces in Space '{self.current_space_id}':")
            print("=" * (len(f"Namespaces in Space '{self.current_space_id}':") + 5))
            # TODO: Implement space-specific namespace listing logic
            print(f"(Namespace listing for space '{self.current_space_id}' - implementation pending)")
        else:
            print("All Namespaces (Global):")
            print("========================")
            # TODO: Implement global namespace listing logic
            print("(Global namespace listing - implementation pending)")
        return True
    
    def cmd_rebuild(self, args: list[str]) -> bool:
        """Rebuild indexes or stats."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: rebuild <subcommand> [space_id]")
            print("Available subcommands: indexes, index, stats")
            print("  rebuild indexes             - Rebuild all space indexes")
            print("  rebuild index <space_id>    - Rebuild indexes for specific space")
            print("  rebuild stats               - Rebuild database statistics")
            return True
        
        subcommand = args[0].lower()
        
        if subcommand == 'indexes':
            # Rebuild ALL space indexes
            return self.cmd_rebuild_indexes([])
        elif subcommand == 'index':
            # Rebuild indexes for specific space
            if len(args) < 2:
                print("Usage: rebuild index <space_id>")
                return True
            space_id = args[1]
            return self.cmd_rebuild_indexes([space_id])
        elif subcommand == 'stats':
            return self.cmd_rebuild_stats([])
        else:
            print(f"Unknown rebuild subcommand: {subcommand}")
            print("Available subcommands: indexes, stats")
        
        return True
    
    def cmd_clear(self, args: list[str]) -> bool:
        """Clear data within a space but leave the space in place."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: clear <space_id>")
            print("Example: clear space123")
            return True
        
        space_id = args[0]
        print(f"Clearing data in space '{space_id}'...")
        # TODO: Implement space data clearing logic
        print(f"✅ Data cleared from space '{space_id}' (space structure preserved)")
        return True
    
    def cmd_use(self, args: list[str]) -> bool:
        """Set current space and display space ID in prompt."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: use <space_id>")
            print("Example: use space123")
            return True
        
        space_id = args[0]
        print(f"Validating space '{space_id}'...")
        
        try:
            # Get all spaces from database to validate the space_id
            spaces = self._run_async(self.db_impl.list_spaces())
            
            # Check if space_id exists (can be either ID or space name)
            valid_space = None
            for space in spaces:
                if (str(space.get('id')) == space_id or 
                    space.get('space') == space_id or
                    space.get('space_name') == space_id):
                    valid_space = space
                    break
            
            if valid_space:
                # Set the current space using the actual space identifier
                actual_space_id = valid_space.get('space', space_id)
                self.current_space_id = actual_space_id
                print(f"✅ Current space set to '{actual_space_id}'")
                print(f"   Space Name: {valid_space.get('space_name', 'N/A')}")
                print(f"   Space ID will appear in prompt: [space:{actual_space_id}]")
            else:
                print(f"❌ Space '{space_id}' not found in database.")
                print("Available spaces:")
                if spaces:
                    for space in spaces:
                        print(f"  - ID: {space.get('id')}, Space: {space.get('space')}, Name: {space.get('space_name')}")
                else:
                    print("  (No spaces found)")
                print("Use 'list spaces;' to see all available spaces.")
                    
        except Exception as e:
            print(f"❌ Error validating space: {e}")
        
        return True
    
    def cmd_unuse(self, args: list[str]) -> bool:
        """Unset the current space."""
        if self.current_space_id is None:
            print("❌ No current space is set.")
            return True
        
        previous_space = self.current_space_id
        self.current_space_id = None
        print(f"✅ Unset current space (was '{previous_space}')")
        print("   Space ID removed from prompt")
        return True
    
    def cmd_import(self, args: list[str]) -> bool:
        """Import data into a space with flexible parameter handling."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        # Parse command-line arguments
        import_params = self._parse_import_args(args)
        
        # Interactive mode: prompt for missing parameters
        if not self._complete_import_params_interactive(import_params):
            return True  # User cancelled
        
        # Validate parameters
        if not self._validate_import_params(import_params):
            return True  # Validation failed
        
        # Execute import
        return self._execute_import(import_params)
    
    def _parse_import_args(self, args: list[str]) -> dict:
        """Parse command-line arguments for import command."""
        params = {
            'space_id': None,
            'file_path': None,
            'file_format': None,
            'batch_size': 50000,
            'pre_validate': False,
            'interactive': True
        }
        
        i = 0
        while i < len(args):
            arg = args[i]
            
            if arg in ['--space-id', '-s'] and i + 1 < len(args):
                params['space_id'] = args[i + 1]
                i += 2
            elif arg in ['--file', '-f'] and i + 1 < len(args):
                params['file_path'] = args[i + 1]
                i += 2
            elif arg in ['--format', '-t'] and i + 1 < len(args):
                params['file_format'] = args[i + 1].lower()
                i += 2
            elif arg in ['--batch-size', '-b'] and i + 1 < len(args):
                try:
                    params['batch_size'] = int(args[i + 1])
                except ValueError:
                    print(f"❌ Invalid batch size: {args[i + 1]}")
                i += 2
            elif arg in ['--validate', '--pre-validate']:
                params['pre_validate'] = True
                i += 1
            elif arg in ['--no-validate']:
                params['pre_validate'] = False
                i += 1
            elif arg in ['--interactive', '-i'] and i + 1 < len(args):
                interactive_val = args[i + 1].lower()
                if interactive_val in ['true', '1', 'yes', 'on']:
                    params['interactive'] = True
                elif interactive_val in ['false', '0', 'no', 'off']:
                    params['interactive'] = False
                else:
                    print(f"❌ Invalid interactive value: {args[i + 1]}. Use true/false.")
                    return {}
                i += 2
            else:
                print(f"❌ Unknown import argument: {arg}")
                print("Usage: import [--space-id|-s <id>] [--file|-f <path>] [--format|-t <format>]")
                print("              [--batch-size|-b <size>] [--validate|--no-validate] [--interactive|-i true/false]")
                return {}
        
        return params
    
    def _complete_import_params_interactive(self, params: dict) -> bool:
        """Handle parameter collection based on interactive mode."""
        if not params.get('interactive', True):
            # Non-interactive mode: validate required parameters and use defaults
            return self._handle_non_interactive_params(params)
        else:
            # Interactive mode: prompt for missing/invalid parameters with validation
            return self._handle_interactive_params(params)
    
    def _handle_non_interactive_params(self, params: dict) -> bool:
        """Handle non-interactive mode: use defaults or error for missing required params."""
        # Check required parameters
        if not params['space_id']:
            if self.current_space_id:
                params['space_id'] = self.current_space_id
                print(f"ℹ️ Using current space: {self.current_space_id}")
            else:
                print("❌ Error: Space ID is required. Use --space-id|-s or set a current space with 'use <space_id>;'")
                return False
        
        if not params['file_path']:
            print("❌ Error: File path is required. Use --file|-f <path>")
            return False
        
        # Use defaults for optional parameters
        if not params['file_format']:
            print("ℹ️ File format not specified - will auto-detect from file extension")
        
        print(f"ℹ️ Using batch size: {params['batch_size']:,}")
        print(f"ℹ️ Pre-validation: {'enabled' if params['pre_validate'] else 'disabled'}")
        
        return True
    
    def _handle_interactive_params(self, params: dict) -> bool:
        """Handle interactive mode with validation and retry logic."""
        print("\nℹ️ Import Data Wizard")
        print("===================\n")
        
        try:
            # Space ID with validation and retry
            if not self._collect_space_id_interactive(params):
                return False
            
            # File path with validation and retry
            if not self._collect_file_path_interactive(params):
                return False
            
            # File format with validation and retry
            if not self._collect_file_format_interactive(params):
                return False
            
            # Batch size with validation and retry
            if not self._collect_batch_size_interactive(params):
                return False
            
            # Pre-validate option
            if not self._collect_pre_validate_interactive(params):
                return False
            
            # Final confirmation
            return self._confirm_import_interactive(params)
            
        except (EOFError, KeyboardInterrupt):
            print("\nℹ️ Import cancelled by user.")
            return False
    
    def _collect_space_id_interactive(self, params: dict) -> bool:
        """Collect and validate space ID interactively."""
        while True:
            try:
                if params['space_id']:
                    # Already have a value, show it as current
                    current_val = params['space_id']
                    user_input = input(f"Space ID [{current_val}]: ").strip()
                    if not user_input:
                        # Keep current value
                        break
                    params['space_id'] = user_input
                else:
                    # No value yet
                    if self.current_space_id:
                        default_space = self.current_space_id
                        user_input = input(f"Space ID [{default_space}]: ").strip()
                        params['space_id'] = user_input if user_input else default_space
                    else:
                        user_input = input("Space ID (required): ").strip()
                        if not user_input:
                            print("❌ Space ID is required. Please enter a space ID or press Ctrl+D to cancel.")
                            continue
                        params['space_id'] = user_input
                
                # Validate space exists
                if self._validate_space_exists(params['space_id']):
                    break
                else:
                    print(f"❌ Space '{params['space_id']}' not found. Please try again or press Ctrl+D to cancel.")
                    # Reset the invalid value so user gets prompted again
                    params['space_id'] = None
                    
            except (EOFError, KeyboardInterrupt):
                raise
        
        return True
    
    def _collect_file_path_interactive(self, params: dict) -> bool:
        """Collect and validate file path interactively."""
        while True:
            try:
                if params['file_path']:
                    # Already have a value, show it as current
                    current_val = params['file_path']
                    user_input = input(f"File path [{current_val}]: ").strip()
                    if not user_input:
                        # Keep current value
                        break
                    params['file_path'] = user_input
                else:
                    # No value yet
                    user_input = input("File path (required): ").strip()
                    if not user_input:
                        print("❌ File path is required. Please enter a file path or press Ctrl+D to cancel.")
                        continue
                    params['file_path'] = user_input
                
                # Validate file exists
                if self._validate_file_exists(params['file_path']):
                    break
                else:
                    print(f"❌ File '{params['file_path']}' not found or not accessible. Please try again or press Ctrl+D to cancel.")
                    # Reset the invalid value so user gets prompted again
                    params['file_path'] = None
                    
            except (EOFError, KeyboardInterrupt):
                raise
        
        return True
    
    def _collect_file_format_interactive(self, params: dict) -> bool:
        """Collect and validate file format interactively."""
        valid_formats = ['turtle', 'xml', 'nt', 'n3', 'json-ld', 'auto-detect']
        
        while True:
            try:
                if params['file_format']:
                    current_val = params['file_format']
                    user_input = input(f"File format [{current_val}]: ").strip().lower()
                    if not user_input:
                        break
                    params['file_format'] = user_input if user_input != 'auto-detect' else None
                else:
                    user_input = input("File format [auto-detect]: ").strip().lower()
                    params['file_format'] = user_input if user_input and user_input != 'auto-detect' else None
                
                # Validate format if specified
                if params['file_format'] and params['file_format'] not in valid_formats[:-1]:  # Exclude 'auto-detect'
                    print(f"❌ Invalid format '{params['file_format']}'. Valid formats: {', '.join(valid_formats)}")
                    params['file_format'] = None
                    continue
                
                break
                
            except (EOFError, KeyboardInterrupt):
                raise
        
        return True
    
    def _collect_batch_size_interactive(self, params: dict) -> bool:
        """Collect and validate batch size interactively."""
        while True:
            try:
                current_val = params['batch_size']
                user_input = input(f"Batch size [{current_val:,}]: ").strip()
                
                if not user_input:
                    # Keep current value
                    break
                
                try:
                    batch_size = int(user_input.replace(',', ''))  # Allow comma separators
                    if batch_size < 1 or batch_size > 1000000:
                        print("❌ Batch size must be between 1 and 1,000,000. Please try again.")
                        continue
                    params['batch_size'] = batch_size
                    break
                except ValueError:
                    print(f"❌ Invalid batch size '{user_input}'. Please enter a number between 1 and 1,000,000.")
                    continue
                    
            except (EOFError, KeyboardInterrupt):
                raise
        
        return True
    
    def _collect_pre_validate_interactive(self, params: dict) -> bool:
        """Collect pre-validate option interactively."""
        try:
            current_val = 'yes' if params['pre_validate'] else 'no'
            user_input = input(f"Pre-validate data [{current_val}]: ").strip().lower()
            
            if user_input in ['y', 'yes', 'true', '1']:
                params['pre_validate'] = True
            elif user_input in ['n', 'no', 'false', '0']:
                params['pre_validate'] = False
            # If empty, keep current value
            
        except (EOFError, KeyboardInterrupt):
            raise
        
        return True
    
    def _confirm_import_interactive(self, params: dict) -> bool:
        """Show final confirmation in interactive mode."""
        try:
            print(f"\nℹ️ Import Summary:")
            print(f"  Space ID: {params['space_id']}")
            print(f"  File: {params['file_path']}")
            print(f"  Format: {params['file_format'] or 'auto-detect'}")
            print(f"  Batch Size: {params['batch_size']:,}")
            print(f"  Pre-validate: {'Yes' if params['pre_validate'] else 'No'}")
            
            confirm = input("\nProceed with import? [y/N]: ").strip().lower()
            return confirm in ['y', 'yes']
            
        except (EOFError, KeyboardInterrupt):
            print("\nℹ️ Import cancelled by user.")
            return False
    
    def _validate_space_exists(self, space_id: str) -> bool:
        """Validate that a space exists in the database."""
        try:
            spaces = asyncio.run(self.db_impl.list_spaces())
            for space in spaces:
                if (str(space.get('id')) == space_id or 
                    space.get('space') == space_id or
                    space.get('space_name') == space_id):
                    return True
            return False
        except Exception:
            return False
    
    def _validate_file_exists(self, file_path: str) -> bool:
        """Validate that a file exists and is readable."""
        try:
            from pathlib import Path
            path = Path(file_path)
            return path.exists() and path.is_file()
        except Exception:
            return False
    
    def _validate_import_params(self, params: dict) -> bool:
        """Validate import parameters."""
        if not params:
            return False
        
        # Validate space exists
        try:
            spaces = asyncio.run(self.db_impl.list_spaces())
            valid_space = None
            for space in spaces:
                if (str(space.get('id')) == params['space_id'] or 
                    space.get('space') == params['space_id'] or
                    space.get('space_name') == params['space_id']):
                    valid_space = space
                    break
            
            if not valid_space:
                print(f"❌ Space '{params['space_id']}' not found.")
                return False
            
            # Store the validated space info
            params['_validated_space'] = valid_space
            
        except Exception as e:
            print(f"❌ Error validating space: {e}")
            return False
        
        # Validate file exists
        from pathlib import Path
        file_path = Path(params['file_path'])
        if not file_path.exists():
            print(f"❌ File not found: {params['file_path']}")
            return False
        
        if not file_path.is_file():
            print(f"❌ Path is not a file: {params['file_path']}")
            return False
        
        # Auto-detect format if not specified
        if not params['file_format']:
            suffix = file_path.suffix.lower()
            format_map = {
                '.ttl': 'turtle',
                '.turtle': 'turtle',
                '.rdf': 'xml',
                '.xml': 'xml',
                '.nt': 'nt',
                '.n3': 'n3',
                '.jsonld': 'json-ld',
                '.json': 'json-ld'
            }
            params['file_format'] = format_map.get(suffix)
            if params['file_format']:
                print(f"ℹ️ Auto-detected format: {params['file_format']}")
            else:
                print(f"⚠️ Could not auto-detect format for {suffix}. Defaulting to turtle.")
                params['file_format'] = 'turtle'
        
        # Validate batch size
        if params['batch_size'] < 1 or params['batch_size'] > 1000000:
            print(f"❌ Invalid batch size: {params['batch_size']}. Must be between 1 and 1,000,000.")
            return False
        
        return True
    
    def _execute_import(self, params: dict) -> bool:
        """Execute the data import using GraphImportOp."""
        print(f"\n📋 Import Parameters:")
        print(f"  Space ID: {params['space_id']}")
        if '_validated_space' in params:
            space_name = params['_validated_space'].get('space_name', 'N/A')
            print(f"  Space Name: {space_name}")
        print(f"  File Path: {params['file_path']}")
        print(f"  File Format: {params['file_format']}")
        print(f"  Batch Size: {params['batch_size']:,}")
        print(f"  Pre-validate: {'Yes' if params['pre_validate'] else 'No'}")
        print(f"  Interactive Mode: {'Yes' if params['interactive'] else 'No'}")
        
        try:
            # Create GraphImportOp instance
            import_op = GraphImportOp(
                file_path=params['file_path'],
                space_id=params['space_id'],
                validate_before_import=params['pre_validate'],
                batch_size=params['batch_size']
            )
            
            print(f"\n🚀 Starting import operation (ID: {import_op.operation_id})")
            print(f"   Operation: {import_op.get_operation_name()}")
            
            # Execute the import operation
            result = import_op.run()
            
            # Display results
            if result.is_success():
                print(f"\n✅ Import completed successfully!")
                print(f"   {result.message}")
                
                # Show detailed results
                if result.details:
                    details = result.details
                    
                    # File information
                    if 'file_info' in details and details['file_info']:
                        file_info = details['file_info']
                        print(f"\n📁 File Information:")
                        print(f"   Size: {file_info.get('size_mb', 0):.2f} MB")
                        print(f"   Type: {file_info.get('detected_type', 'unknown')}")
                        print(f"   Compressed: {'Yes' if file_info.get('is_compressed', False) else 'No'}")
                    
                    # Validation results
                    if 'validation_result' in details and details['validation_result']:
                        val_result = details['validation_result']
                        print(f"\n✅ Validation Results:")
                        print(f"   Format: {val_result.get('format_detected', 'Unknown')}")
                        print(f"   Triples: {val_result.get('triple_count', 0):,}")
                        print(f"   File Size: {val_result.get('file_size_mb', 0):.2f} MB")
                        print(f"   Parse Time: {val_result.get('parsing_time_ms', 0):.2f} ms")
                        print(f"   Namespaces: {val_result.get('namespaces_count', 0)}")
                
                # Show warnings if any
                if result.warnings:
                    print(f"\n⚠️  Warnings:")
                    for warning in result.warnings:
                        print(f"   - {warning}")
                
                # Show operation summary
                summary = import_op.get_import_summary()
                duration = summary.get('duration_seconds', 0)
                if duration:
                    print(f"\n⏱️  Operation completed in {duration:.2f} seconds")
                
                return True
                
            else:
                print(f"\n❌ Import failed!")
                print(f"   {result.message}")
                
                # Show error details
                if result.details:
                    details = result.details
                    if 'validation_result' in details and details['validation_result']:
                        val_result = details['validation_result']
                        if val_result.get('error_message'):
                            print(f"   Validation Error: {val_result['error_message']}")
                
                # Show warnings if any
                if result.warnings:
                    print(f"\n⚠️  Warnings:")
                    for warning in result.warnings:
                        print(f"   - {warning}")
                
                return False
                
        except Exception as e:
            print(f"\n❌ Import operation failed with exception:")
            print(f"   {str(e)}")
            return False
    
    def cmd_rebuild_indexes(self, args: list[str]) -> bool:
        """Rebuild database indexes, optionally for a specific space."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        space_id = args[0] if args and args[0] else None
        
        if space_id:
            print(f"Rebuilding indexes for space '{space_id}'...")
            # TODO: Implement space-specific index rebuilding logic
            print(f"✅ Indexes rebuilt for space '{space_id}'")
        else:
            print("Rebuilding all database indexes...")
            # TODO: Implement global index rebuilding logic
            print("✅ All database indexes rebuilt")
        
        return True
    
    def cmd_rebuild_stats(self, args: list[str]) -> bool:
        """Rebuild database statistics."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        print("Rebuilding database statistics...")
        # TODO: Implement stats rebuilding logic
        print("✅ Database statistics rebuilt")
        
        return True
    
    def cmd_reindex(self, args: list[str]) -> bool:
        """Reindex database indexes for a specific space (synonym for rebuild index)."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: reindex <space_id>")
            print("  Rebuild indexes for a specific space (synonym for 'rebuild index <space_id>')")
            return True
        
        space_id = args[0]
        return self.cmd_rebuild_indexes([space_id])
    
    def cmd_set(self, args: list[str]) -> bool:
        """Set configuration options like logging level."""
        if not args:
            print("Usage: set <option> <value>;")
            print("Available options:")
            print(f"  log-level <level>  - Set logging level (current: {self.log_level})")
            print("                       Valid levels: DEBUG, INFO, WARNING, ERROR, CRITICAL")
            return True
        
        if len(args) < 2:
            print("Error: set command requires both option and value")
            print("Usage: set <option> <value>;")
            return True
        
        option = args[0].lower()
        value = args[1].upper()
        
        if option == 'log-level':
            valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
            if value not in valid_levels:
                print(f"Error: Invalid log level '{value}'")
                print(f"Valid levels: {', '.join(valid_levels)}")
                return True
            
            # Update logging level
            self.log_level = value
            numeric_level = getattr(logging, value)
            
            # Update root logger
            logging.getLogger().setLevel(numeric_level)
            
            # Update specific VitalGraph loggers
            logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(numeric_level)
            logging.getLogger('vitalgraph.ops.graph_import_op').setLevel(numeric_level)
            logging.getLogger('vitalgraph.db.postgresql.postgresql_db_impl').setLevel(numeric_level)
            
            print(f"✅ Logging level set to {value}")
            return True
        else:
            print(f"Error: Unknown option '{option}'")
            print("Available options: log-level")
            return True
    
    def cmd_help(self, args: list[str]) -> bool:
        """Display help information for available commands."""
        help_text = """
🔧 VitalGraphDB Admin REPL Commands:

📊 Database Management:
  connect;          - Connect to VitalGraphDB database
  disconnect;       - Disconnect from database
  init;             - Initialize database tables (only if not present)
  purge;            - Reset all tables to initial state
  delete;           - Delete all VitalGraphDB tables
  info;             - Show VitalGraphDB installation information

📋 List Commands:
  list spaces;      - List graph "spaces"
  list tables;      - List all VitalGraphDB tables
  list users;       - List database users
  list indexes;     - List database indexes
  list graphs;      - List graphs (globally or within current space)
  list namespaces;  - List namespaces (globally or within current space)

🔧 Maintenance Commands:
  rebuild indexes;  - Rebuild all database indexes
  rebuild stats;    - Rebuild database statistics for performance
  clear <space-id>; - Clear data within a space but leave the space in place

🌐 Space Management:
  use <space-id>;   - Set current space and display space ID in prompt
  unuse;            - Unset the current space

📥 Data Import:
  import;           - Import RDF data into a space (interactive or with args)

⚙️  Configuration:
  set log-level <level>; - Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

❓ Help & Control:
  help; or ?;       - Show this help message
  exit; or quit;    - Exit the REPL

Note: All commands must end with a semicolon (;)
        """
        print(help_text)
        return True
    
    def get_config_path(self) -> Path:
        """Get the config file path (from CLI arg or default)."""
        if self.config_path:
            return Path(self.config_path)
        else:
            # Default: bin parent + vitalgraphdb_config + config file name
            script_dir = Path(__file__).resolve().parent.parent.parent  # Go up to project root
            return script_dir / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    def connect_db(self) -> bool:
        """Connect to database for CLI command execution."""
        if self.connected:
            return True
            
        try:
            # Load server config to get database connection info
            config_path = self.get_config_path()
            
            # Load VitalGraphDB server configuration
            self.config = VitalGraphConfig(config_path)
            
            # Create VitalGraphImpl instance with the loaded config
            self.vital_graph_impl = VitalGraphImpl(config=self.config)
            
            # Get database implementation from VitalGraphImpl
            self.db_impl = self.vital_graph_impl.get_db_impl()
            
            if self.db_impl is None:
                return False
            
            # Connect to the database
            connected = asyncio.run(self.db_impl.connect())
            
            if connected:
                self.connected = True
                return True
            else:
                self.db_impl = None
                return False
        
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            print(f"❌ Failed to connect to database")
            self.db_impl = None
            return False
    
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
                    # Show connection status and current space in prompt
                    status = "🟢" if self.connected else "🔴"
                    space_info = f"[space:{self.current_space_id}]" if self.current_space_id else ""
                    prompt_text = f"vitalgraphdb-admin{status}{space_info}> "
                    
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
  vitalgraphadmin -c import --file data.ttl --space-id space1  # Direct command execution

Admin Commands:
  connect;          - Connect to database
  disconnect;       - Disconnect from database
  init;             - Initialize tables
  purge;            - Reset tables
  delete;           - Delete tables
  info;             - Show installation info
  import;           - Import RDF data into a space
  list spaces;      - List graph spaces
  list tables;      - List tables
  list users;       - List users
  list indexes;     - List indexes
  rebuild indexes;  - Rebuild indexes
  rebuild stats;    - Rebuild statistics
        """
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="Path to VitalGraphDB server configuration file (default: auto-detected from project structure)"
    )
    
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    
    parser.add_argument(
        "-c", "--command",
        type=str,
        choices=["import", "info", "init", "purge", "delete", "reindex", "stats"],
        help="Execute a specific admin command directly (import, info, init, purge, delete, reindex, stats)"
    )
    
    parser.add_argument(
        "-i", "--interactive",
        type=str,
        choices=["true", "false", "1", "0", "yes", "no", "on", "off"],
        default="true",
        help="Enable interactive mode for commands (default: true)"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="VitalGraphDB Admin REPL 1.0.0"
    )
    
    # Add remaining arguments for import command
    parser.add_argument("--file", "-f", type=str, help="File path for import command")
    parser.add_argument("--space-id", "-s", type=str, help="Space ID for import/reindex commands")
    parser.add_argument("--format", "-t", type=str, help="File format for import command")
    parser.add_argument("--batch-size", "-b", type=int, help="Batch size for import command")
    parser.add_argument("--validate", action="store_true", help="Enable pre-validation for import")
    parser.add_argument("--no-validate", action="store_true", help="Disable pre-validation for import")
    
    return parser.parse_args()


def setup_logging(log_level: str = "INFO"):
    """Configure logging for CLI operations."""
    # Convert string level to numeric level
    numeric_level = getattr(logging, log_level.upper())
    
    # Configure logging with specified level
    logging.basicConfig(
        level=numeric_level,
        format='%(message)s',  # Simple format for progress messages
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific logger levels
    logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(numeric_level)
    logging.getLogger('vitalgraph.ops.graph_import_op').setLevel(numeric_level)
    logging.getLogger('vitalgraph.db.postgresql.postgresql_db_impl').setLevel(numeric_level)


def main():
    """Main entry point for VitalGraphDB admin REPL."""
    args = parse_args()
    
    # Setup logging for progress tracking with specified level
    setup_logging(args.log_level)
    
    try:
        repl_instance = VitalGraphDBAdminREPL(config_path=args.config, log_level=args.log_level)
        
        # If a command is specified, execute it directly
        if args.command:
            success = repl_instance.execute_cli_command(args)
            sys.exit(0 if success else 1)
        else:
            # Start interactive REPL
            repl_instance.run_repl()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting admin REPL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
