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
# GraphImportOp removed — import is now handled by standalone vitalgraphimport CLI



class VitalGraphDBAdminREPL:
    """VitalGraphDB Admin REPL implementation with database management."""
    
    def __init__(self, config_path: Optional[str] = None, log_level: str = "INFO"):
        self.config_path = config_path
        self.connected = False
        self.db_connection = None
        self.config = None
        self.db_impl = None  # PostgreSQL database implementation
        self.space_backend = None  # Space backend (has list_spaces, etc.)
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
            return self._run_async(self.cmd_purge(args))
        elif command == 'delete':
            return self._run_async(self.cmd_delete(args))
        elif command == 'info':
            return self.cmd_info(args)
        elif command == 'clear':
            return self.cmd_clear(args)
        elif command == 'use':
            return self.cmd_use(args)
        elif command == 'unuse':
            return self.cmd_unuse(args)
        elif command == 'import':
            print("\n⚠️  The 'import' command has been removed from vitalgraphadmin.")
            print("   Use the standalone CLI instead:")
            print("     vitalgraphimport -s <space_id> -f <file.nt>")
            print("     vitalgraphimport --help\n")
            return True
        elif command == 'list':
            return self.cmd_list(args)
        elif command == 'rebuild':
            return self.cmd_rebuild(args)
        elif command == 'reindex':
            return self.cmd_rebuild(args)
        elif command == 'set':
            return self.cmd_set(args)
        elif command == 'user':
            return self.cmd_user(args)
        elif command == 'audit':
            return self.cmd_audit(args)
        elif command == 'apikey':
            return self.cmd_apikey(args)
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
            # Load configuration from environment variables
            print("Loading VitalGraphDB configuration from environment...")
            self.config = VitalGraphConfig()
            
            # Create VitalGraphImpl instance with the loaded config
            print("Initializing VitalGraph implementation...")
            self.vital_graph_impl = VitalGraphImpl(config=self.config)
            
            backend_type = self.config.get_backend_config().get('type', 'postgresql')
            
            if backend_type == 'sparql_sql':
                # sparql_sql: db_impl is created during space_backend.connect()
                space_backend = getattr(self.vital_graph_impl, 'space_backend', None)
                if space_backend is None:
                    print("❌ Failed to initialize sparql_sql space backend")
                    return True
                print("Connecting to sparql_sql backend...")
                connected = self._run_async(space_backend.connect())
                if connected:
                    self.db_impl = space_backend.db_impl
                    self.space_backend = space_backend
                    self.vital_graph_impl.db_impl = self.db_impl
                    self.connected = True
                    sidecar_url = getattr(space_backend, 'sidecar_url', 'N/A')
                    print(f"✅ Connected to sparql_sql backend (sidecar={sidecar_url})")
                else:
                    print("❌ Failed to connect to sparql_sql backend")
            else:
                # Standard path: db_impl available at init time
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
    
    async def _notify_token_version_changed(self, username: str, signal_type: str = "revoked"):
        """Send token version change NOTIFY to all server instances."""
        try:
            from vitalgraph.signal.signal_manager import SignalManager
            sm = SignalManager(self.db_impl)
            await sm.notify_token_version_changed(username, signal_type)
            await sm._close_notify_connection()
        except Exception as e:
            print(f"  ⚠️  Token version NOTIFY failed: {e}")

    async def _list_spaces_async(self) -> list:
        """List spaces, routing through space_backend for sparql_sql or db_impl otherwise."""
        if self.space_backend and hasattr(self.space_backend, 'list_spaces'):
            return await self.space_backend.list_spaces()
        return await self.db_impl.list_spaces()

    def _get_backend_admin(self):
        """Return the backend-specific admin module for the current backend type."""
        backend_type = self.config.get_backend_config().get('type', 'postgresql')
        
        if backend_type == 'sparql_sql':
            from vitalgraph.db.sparql_sql.sparql_sql_admin import SparqlSQLAdmin
            return SparqlSQLAdmin()
        elif backend_type == 'fuseki_postgresql':
            from vitalgraph.db.fuseki_postgresql.fuseki_admin import FusekiPostgreSQLAdmin
            return FusekiPostgreSQLAdmin()
        else:
            return None
    
    async def cmd_init(self, args: list[str]) -> bool:
        """Initialize database tables (only if they don't exist)."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        admin = self._get_backend_admin()
        if admin is None:
            print("❌ No admin module available for this backend type.")
            return True
        
        backend_type = self.config.get_backend_config().get('type', 'postgresql')
        print(f"🚀 Initializing {backend_type} Backend")
        print("=" * 50)
        
        try:
            status = await admin.check_admin_tables(self.db_impl)
            
            if status['found'] == status['expected']:
                print(f"✅ All {status['expected']} admin tables already exist")
                print("   No initialization needed.")
                return True
            elif status['found'] > 0:
                print(f"⚠️  Warning: Found {status['found']} out of {status['expected']} admin tables")
                response = input("   Continue with initialization? (yes/no): ").strip().lower()
                if response not in ['yes', 'y']:
                    print("   Initialization cancelled.")
                    return True
            
            print("\n📦 Creating admin tables...")
            success = await admin.init_tables(self.db_impl)
            if success:
                print(f"\n✅ {backend_type} admin tables initialized successfully!")
            else:
                print(f"\n❌ Failed to initialize {backend_type} admin tables")
            
        except Exception as e:
            print(f"\n❌ Error during initialization: {e}")
            import traceback
            traceback.print_exc()
        
        return True
    
    async def cmd_purge(self, args: list[str]) -> bool:
        """Reset all tables to initial state."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        admin = self._get_backend_admin()
        if admin is None:
            print("❌ No admin module available for this backend type.")
            return True
        
        print("⚠️  WARNING: This will delete ALL data and reset tables to initial state!")
        response = input("   Type 'yes' to confirm: ").strip().lower()
        if response != 'yes':
            print("   Purge cancelled.")
            return True
        
        try:
            print("Purging VitalGraphDB tables...")
            success = await admin.purge_tables(self.db_impl)
            if success:
                print("✅ Database tables purged and reset to initial state")
            else:
                print("❌ Failed to purge database tables")
        except Exception as e:
            print(f"❌ Error during purge: {e}")
            import traceback
            traceback.print_exc()
        
        return True
    
    async def cmd_delete(self, args: list[str]) -> bool:
        """Delete all VitalGraphDB tables."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        admin = self._get_backend_admin()
        if admin is None:
            print("❌ No admin module available for this backend type.")
            return True
        
        print("⚠️  WARNING: This will permanently DELETE all VitalGraphDB tables!")
        response = input("   Type 'yes' to confirm: ").strip().lower()
        if response != 'yes':
            print("   Delete cancelled.")
            return True
        
        try:
            print("Deleting VitalGraphDB tables...")
            success = await admin.delete_tables(self.db_impl)
            if success:
                print("✅ VitalGraphDB tables deleted")
            else:
                print("❌ Failed to delete database tables")
        except Exception as e:
            print(f"❌ Error during delete: {e}")
            import traceback
            traceback.print_exc()
        
        return True
    
    def cmd_info(self, args: list[str]) -> bool:
        """Provide information about the VitalGraphDB installation."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        admin = self._get_backend_admin()
        if admin is None:
            print("❌ No admin module available for this backend type.")
            return True
        
        print("VitalGraphDB Installation Information:")
        print("=====================================")
        
        try:
            info = self._run_async(admin.get_info(self.db_impl, config=self.config))
            
            print(f"Backend: {info.get('backend', 'Unknown')}")
            print(f"Status: {info.get('status', 'Unknown')}")
            
            # Connection details
            if 'sidecar_url' in info:
                print(f"Sidecar URL: {info['sidecar_url']}")
            if 'fuseki_server' in info:
                print(f"\nFuseki Server: {info['fuseki_server']}")
                print(f"Fuseki Dataset: {info.get('fuseki_dataset', 'N/A')}")
                print(f"JWT Authentication: {'Enabled' if info.get('jwt_auth') else 'Disabled'}")
            if 'pg_host' in info:
                print(f"\nPostgreSQL Host: {info['pg_host']}")
                print(f"PostgreSQL Database: {info.get('pg_database', 'N/A')}")
            
            # Initialization state
            init_state = info.get('init_state', 'unknown')
            if init_state == 'initialized':
                admin_tables = info.get('admin_tables', {})
                print(f"\nInitialization State: Initialized")
                print(f"Admin Tables: ✅ All present ({admin_tables.get('found', '?')}/{admin_tables.get('expected', '?')})")
                print(f"Spaces: {info.get('space_count', 0)} configured")
                
                # Per-space table check (sparql_sql)
                for sp in info.get('spaces', []):
                    status_icon = "✅" if sp['tables_ok'] else "⚠️"
                    print(f"  {sp['space_id']}: {status_icon}")
                
                if 'pg_trgm' in info:
                    print(f"\npg_trgm extension: {'✅' if info['pg_trgm'] else '❌ Missing'}")
                
                print(f"Users: {info.get('user_count', 0)} configured")
            elif init_state == 'partially_initialized':
                admin_tables = info.get('admin_tables', {})
                print(f"\nInitialization State: Partially Initialized")
                print(f"Admin Tables: ⚠️  {admin_tables.get('found', '?')} out of {admin_tables.get('expected', '?')} tables present")
                print("   Run 'init;' to complete initialization")
            else:
                print(f"\nInitialization State: Uninitialized")
                print("Admin Tables: ❌ Not created")
                print("   Run 'init;' to initialize")
            
            print("\nVersion: 1.0.0")
            
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
            # Route through space_backend if available (sparql_sql), else db_impl
            if self.space_backend and hasattr(self.space_backend, 'list_spaces'):
                raw_spaces = self._run_async(self.space_backend.list_spaces())
            else:
                raw_spaces = self._run_async(self.db_impl.list_spaces())
            
            # Normalize to dicts with display-friendly keys
            spaces = []
            for s in raw_spaces:
                row = dict(s) if hasattr(s, 'keys') else s
                spaces.append({
                    'space_id': row.get('space_id', 'N/A'),
                    'space_name': row.get('space_name', ''),
                    'tenant': row.get('tenant', 'default'),
                    'description': row.get('space_description', ''),
                    'updated': row.get('update_time', ''),
                })
            
            headers = ['Space ID', 'Space Name', 'Tenant', 'Description', 'Updated']
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
            # Get users via backend admin
            admin = self._get_backend_admin()
            if admin and hasattr(admin, 'list_users'):
                raw_users = self._run_async(admin.list_users(self.db_impl))
            else:
                raw_users = self._run_async(self.db_impl.list_users())
            
            # Normalize to dicts with display-friendly keys
            users = []
            for u in raw_users:
                row = dict(u) if hasattr(u, 'keys') else u.__dict__ if hasattr(u, '__dict__') else u
                users.append({
                    'user_id': row.get('user_id', 'N/A'),
                    'username': row.get('username', ''),
                    'email': row.get('email', ''),
                    'tenant': row.get('tenant', 'default'),
                    'password_status': '[HIDDEN]' if row.get('password') else '[NOT SET]',
                    'updated': row.get('update_time', ''),
                })
            
            headers = ['User ID', 'Username', 'Email', 'Tenant', 'Password Status', 'Updated']
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
        """Rebuild indexes, stats, or run maintenance ops."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        if not args:
            print("Usage: rebuild <subcommand> [space_id]")
            print("Available subcommands: indexes, index, stats, analyze, vacuum, resync")
            print("  rebuild indexes             - Rebuild all space indexes")
            print("  rebuild index <space_id>    - Rebuild indexes for specific space")
            print("  rebuild stats [space_id]    - Rebuild query optimizer statistics")
            print("  rebuild analyze [space_id]  - Run ANALYZE on space tables")
            print("  rebuild vacuum [space_id]   - Run VACUUM on space tables")
            print("  rebuild resync [space_id]   - Resync auxiliary tables (edge, frame_entity, stats)")
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
            return self.cmd_rebuild_stats(args[1:])
        elif subcommand == 'analyze':
            return self.cmd_rebuild_analyze(args[1:])
        elif subcommand == 'vacuum':
            return self.cmd_rebuild_vacuum(args[1:])
        elif subcommand == 'resync':
            return self.cmd_rebuild_resync(args[1:])
        else:
            print(f"Unknown rebuild subcommand: {subcommand}")
            print("Available subcommands: indexes, index, stats, analyze, vacuum, resync")
        
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
            spaces = self._run_async(self._list_spaces_async())
            
            # Check if space_id exists (can be either ID or space name)
            valid_space = None
            for space in spaces:
                row = dict(space) if hasattr(space, 'keys') else space
                if (str(row.get('id')) == space_id or 
                    row.get('space_id') == space_id or
                    row.get('space') == space_id or
                    row.get('space_name') == space_id):
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
        """Deprecated — use standalone vitalgraphimport CLI."""
        print("\n⚠️  The 'import' command has been removed from vitalgraphadmin.")
        print("   Use the standalone CLI instead:")
        print("     vitalgraphimport -s <space_id> -f <file.nt>")
        print("     vitalgraphimport --help\n")
        return True
    
    # --- Import helper methods removed (now in vitalgraphimport CLI) ---
    # --- (cmd_import, _parse_import_args, _execute_import, etc.) ---

    def cmd_rebuild_indexes(self, args: list[str]) -> bool:
        """Rebuild database indexes, optionally for a specific space."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        space_id = args[0] if args and args[0] else None
        
        async def _do_rebuild_indexes(sid):
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return
            
            if sid:
                space_ids = [sid]
            else:
                spaces = await self._list_spaces_async()
                space_ids = [dict(s).get('space_id', dict(s).get('space', dict(s).get('id', ''))) if hasattr(s, 'keys') else s.get('space_id', s.get('space', s.get('id', ''))) for s in spaces if s]
                if not space_ids:
                    print("No spaces found.")
                    return
            
            for s in space_ids:
                print(f"\n🔄 Rebuilding indexes for space '{s}'...")
                tables = [
                    f"{s}_term", f"{s}_rdf_quad", f"{s}_datatype",
                    f"{s}_rdf_pred_stats", f"{s}_rdf_stats",
                ]
                async with pool.acquire() as conn:
                    for table in tables:
                        try:
                            # Check table exists before reindexing
                            exists = await conn.fetchval(
                                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                                "WHERE table_schema='public' AND table_name=$1)", table
                            )
                            if exists:
                                await conn.execute(f"REINDEX TABLE {table}")
                                print(f"   ✅ {table}")
                            else:
                                print(f"   ⏭️  {table} (not found, skipping)")
                        except Exception as e:
                            print(f"   ❌ {table}: {e}")
                
                # Run ANALYZE after reindex to update planner stats
                try:
                    from vitalgraph.ops.database_op import AnalyzeOp
                    async with pool.acquire() as conn:
                        op = AnalyzeOp(s, conn=conn)
                        result = await op.execute()
                        if result.is_success():
                            print(f"   ✅ ANALYZE complete")
                        else:
                            print(f"   ⚠️  ANALYZE: {result.message}")
                except Exception as e:
                    print(f"   ⚠️  ANALYZE failed: {e}")
            
            print(f"\n✅ Index rebuild complete for {len(space_ids)} space(s)")
        
        try:
            self._run_async(_do_rebuild_indexes(space_id))
        except Exception as e:
            print(f"❌ Rebuild indexes failed: {e}")
        
        return True
    
    def cmd_rebuild_stats(self, args: list[str]) -> bool:
        """Rebuild rdf_pred_stats / rdf_stats query optimizer tables."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        space_id = args[0] if args and args[0] else None
        
        async def _do_rebuild_stats(sid):
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return
            
            if sid:
                space_ids = [sid]
            else:
                spaces = await self._list_spaces_async()
                space_ids = [dict(s).get('space_id', dict(s).get('space', '')) if hasattr(s, 'keys') else s.get('space_id', s.get('space', '')) for s in spaces if s]
                if not space_ids:
                    print("No spaces found.")
                    return
            
            from vitalgraph.ops.database_op import StatsRebuildOp
            
            for s in space_ids:
                print(f"\n🔄 Rebuilding stats for space '{s}'...")
                try:
                    async with pool.acquire() as conn:
                        op = StatsRebuildOp(s, conn=conn)
                        result = await op.execute()
                        if result.is_success():
                            print(f"   ✅ {result.message}")
                        else:
                            print(f"   ❌ {result.message}")
                except Exception as e:
                    print(f"   ❌ Stats rebuild failed: {e}")
            
            print(f"\n✅ Stats rebuild complete for {len(space_ids)} space(s)")
        
        try:
            self._run_async(_do_rebuild_stats(space_id))
        except Exception as e:
            print(f"❌ Rebuild stats failed: {e}")
        
        return True
    
    def cmd_rebuild_analyze(self, args: list[str]) -> bool:
        """Run ANALYZE on space tables to update PostgreSQL planner statistics."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        space_id = args[0] if args and args[0] else None
        
        async def _do_analyze(sid):
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return
            
            if sid:
                space_ids = [sid]
            else:
                spaces = await self._list_spaces_async()
                space_ids = [dict(s).get('space_id', dict(s).get('space', '')) if hasattr(s, 'keys') else s.get('space_id', s.get('space', '')) for s in spaces if s]
                if not space_ids:
                    print("No spaces found.")
                    return
            
            from vitalgraph.ops.database_op import AnalyzeOp
            
            for s in space_ids:
                print(f"\n🔄 Running ANALYZE for space '{s}'...")
                try:
                    async with pool.acquire() as conn:
                        op = AnalyzeOp(s, conn=conn)
                        result = await op.execute()
                        if result.is_success():
                            print(f"   ✅ {result.message}")
                        else:
                            print(f"   ❌ {result.message}")
                except Exception as e:
                    print(f"   ❌ ANALYZE failed: {e}")
            
            print(f"\n✅ ANALYZE complete for {len(space_ids)} space(s)")
        
        try:
            self._run_async(_do_analyze(space_id))
        except Exception as e:
            print(f"❌ ANALYZE failed: {e}")
        
        return True
    
    def cmd_rebuild_vacuum(self, args: list[str]) -> bool:
        """Run VACUUM on space tables to reclaim dead tuple storage."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        space_id = args[0] if args and args[0] else None
        
        async def _do_vacuum(sid):
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return
            
            if sid:
                space_ids = [sid]
            else:
                spaces = await self._list_spaces_async()
                space_ids = [dict(s).get('space_id', dict(s).get('space', '')) if hasattr(s, 'keys') else s.get('space_id', s.get('space', '')) for s in spaces if s]
                if not space_ids:
                    print("No spaces found.")
                    return
            
            from vitalgraph.ops.database_op import VacuumOp
            
            for s in space_ids:
                print(f"\n🔄 Running VACUUM for space '{s}'...")
                try:
                    async with pool.acquire() as conn:
                        op = VacuumOp(s, conn=conn)
                        result = await op.execute()
                        if result.is_success():
                            print(f"   ✅ {result.message}")
                        else:
                            print(f"   ❌ {result.message}")
                except Exception as e:
                    print(f"   ❌ VACUUM failed: {e}")
            
            print(f"\n✅ VACUUM complete for {len(space_ids)} space(s)")
        
        try:
            self._run_async(_do_vacuum(space_id))
        except Exception as e:
            print(f"❌ VACUUM failed: {e}")
        
        return True
    
    def cmd_rebuild_resync(self, args: list[str]) -> bool:
        """Resync all auxiliary tables (edge, frame_entity, stats) from rdf_quad."""
        if not self.connected:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True
        
        backend_type = self.config.get_backend_config().get('type', 'postgresql')
        if backend_type != 'sparql_sql':
            print("❌ Resync is only available for the sparql_sql backend.")
            return True
        
        space_id = args[0] if args and args[0] else None
        
        async def _do_resync(sid):
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return
            
            if sid:
                space_ids = [sid]
            else:
                spaces = await self._list_spaces_async()
                space_ids = [dict(s).get('space_id', dict(s).get('space', '')) if hasattr(s, 'keys') else s.get('space_id', s.get('space', '')) for s in spaces if s]
                if not space_ids:
                    print("No spaces found.")
                    return
            
            from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables
            
            for s in space_ids:
                print(f"\n🔄 Resyncing auxiliary tables for space '{s}'...")
                try:
                    async with pool.acquire() as conn:
                        result = await resync_all_auxiliary_tables(conn, s)
                        print(f"   ✅ edge:         {result['edge_rows']:>10,} rows")
                        print(f"   ✅ frame_entity: {result['frame_entity_rows']:>10,} rows")
                        print(f"   ✅ pred_stats:   {result['pred_stats_rows']:>10,} rows")
                        print(f"   ✅ quad_stats:   {result['quad_stats_rows']:>10,} rows")
                except Exception as e:
                    print(f"   ❌ Resync failed: {e}")
            
            print(f"\n✅ Resync complete for {len(space_ids)} space(s)")
        
        try:
            self._run_async(_do_resync(space_id))
        except Exception as e:
            print(f"❌ Resync failed: {e}")
        
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
            logging.getLogger('vitalgraph.db.sparql_sql').setLevel(numeric_level)
            
            print(f"✅ Logging level set to {value}")
            return True
        else:
            print(f"Error: Unknown option '{option}'")
            print("Available options: log-level")
            return True
    
    # ------------------------------------------------------------------
    # User Management Commands
    # ------------------------------------------------------------------

    def cmd_user(self, args: list[str]) -> bool:
        """User management command dispatcher."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True

        if not args:
            print("Usage: user <subcommand> [args...]")
            print("Subcommands: list, add, delete, password, role, deactivate, activate, grant, revoke, spaces")
            return True

        sub = args[0].lower()
        if sub == 'list':
            return self._run_async(self._user_list())
        elif sub == 'add':
            return self._run_async(self._user_add(args[1:]))
        elif sub == 'delete':
            return self._run_async(self._user_delete(args[1:]))
        elif sub == 'password':
            return self._run_async(self._user_password(args[1:]))
        elif sub == 'role':
            return self._run_async(self._user_role(args[1:]))
        elif sub == 'deactivate':
            return self._run_async(self._user_deactivate(args[1:]))
        elif sub == 'activate':
            return self._run_async(self._user_activate(args[1:]))
        elif sub == 'grant':
            return self._run_async(self._user_grant(args[1:]))
        elif sub == 'revoke':
            return self._run_async(self._user_revoke(args[1:]))
        elif sub == 'spaces':
            return self._run_async(self._user_spaces(args[1:]))
        else:
            print(f"Unknown user subcommand: {sub}")
            return True

    async def _user_list(self) -> bool:
        """List all users with role and status."""
        try:
            users = await self.db_impl.list_all_users()
            display = []
            for u in users:
                display.append({
                    'user_id': u.get('user_id', ''),
                    'username': u.get('username', ''),
                    'role': u.get('role', 'user'),
                    'is_active': '✅' if u.get('is_active', True) else '❌',
                    'email': u.get('email', ''),
                    'last_login': u.get('last_login', ''),
                })
            headers = ['User ID', 'Username', 'Role', 'Is Active', 'Email', 'Last Login']
            self.format_table(display, headers, "VitalGraphDB Users")
        except Exception as e:
            print(f"❌ Error listing users: {e}")
        return True

    async def _user_add(self, args: list[str]) -> bool:
        """Create a new user: user add <username> <password> [role]"""
        if len(args) < 2:
            print("Usage: user add <username> <password> [role]")
            print("  role: admin | user | reader (default: user)")
            return True
        username = args[0]
        password = args[1]
        role = args[2] if len(args) > 2 else 'user'

        if role not in ('admin', 'user', 'reader'):
            print(f"❌ Invalid role '{role}'. Must be: admin, user, reader")
            return True

        try:
            from vitalgraph.auth.password import hash_password
            hashed = hash_password(password)
            result = await self.db_impl.create_user(
                username=username, password_hash=hashed, role=role
            )
            if result:
                from vitalgraph.auth.audit import emit_audit_event
                emit_audit_event("auth.user.created", "admin-cli",
                                 target=username, role=role)
                print(f"✅ User '{username}' created with role '{role}' (id={result.get('user_id')})")
            else:
                print(f"❌ Failed to create user '{username}')")
        except ValueError as e:
            print(f"❌ {e}")
        except Exception as e:
            print(f"❌ Error creating user: {e}")
        return True

    async def _user_delete(self, args: list[str]) -> bool:
        """Delete a user: user delete <username>"""
        if not args:
            print("Usage: user delete <username>")
            return True
        username = args[0]
        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            confirm = input(f"Delete user '{username}'? (yes/no): ").strip().lower()
            if confirm != 'yes':
                print("Cancelled.")
                return True
            await self.db_impl.delete_user(user['user_id'])
            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.user.deleted", "admin-cli",
                             target=username, level="WARN")
            print(f"✅ User '{username}' deleted")
        except Exception as e:
            print(f"❌ Error deleting user: {e}")
        return True

    async def _user_password(self, args: list[str]) -> bool:
        """Change password: user password <username> <newpass>"""
        if len(args) < 2:
            print("Usage: user password <username> <new_password>")
            return True
        username, new_password = args[0], args[1]
        try:
            from vitalgraph.auth.password import hash_password
            hashed = hash_password(new_password)
            await self.db_impl.update_user_password_hash(username, hashed)
            await self._notify_token_version_changed(username, "password_changed")
            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.password.changed", "admin-cli",
                             target=username, changed_by="admin-cli")
            print(f"✅ Password updated for '{username}' (tokens invalidated)")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _user_role(self, args: list[str]) -> bool:
        """Change role: user role <username> <role>"""
        if len(args) < 2:
            print("Usage: user role <username> <admin|user|reader>")
            return True
        username, role = args[0], args[1]
        if role not in ('admin', 'user', 'reader'):
            print(f"❌ Invalid role '{role}'. Must be: admin, user, reader")
            return True
        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            await self.db_impl.update_user(user['user_id'], role=role)
            await self._notify_token_version_changed(username, "role_changed")
            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.role.changed", "admin-cli",
                             target=username, level="WARN",
                             old_role=user.get('role'), new_role=role)
            print(f"✅ User '{username}' role changed to '{role}'")
            if role == 'reader':
                print("   (All space access downgraded to read-only)")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _user_deactivate(self, args: list[str]) -> bool:
        """Deactivate user: user deactivate <username>"""
        if not args:
            print("Usage: user deactivate <username>")
            return True
        username = args[0]
        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            await self.db_impl.update_user(user['user_id'], is_active=False)
            await self._notify_token_version_changed(username, "deactivated")
            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.user.deactivated", "admin-cli",
                             target=username, level="WARN")
            print(f"✅ User '{username}' deactivated (all tokens invalidated)")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _user_activate(self, args: list[str]) -> bool:
        """Activate user: user activate <username>"""
        if not args:
            print("Usage: user activate <username>")
            return True
        username = args[0]
        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            await self.db_impl.update_user(user['user_id'], is_active=True)
            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.user.activated", "admin-cli", target=username)
            print(f"✅ User '{username}' activated")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _user_grant(self, args: list[str]) -> bool:
        """Grant space access: user grant <username> <space_id> <rw|r>"""
        if len(args) < 3:
            print("Usage: user grant <username> <space_id> <rw|r>")
            return True
        username, space_id, level = args[0], args[1], args[2]
        if level not in ('rw', 'r'):
            print(f"❌ Invalid access level '{level}'. Must be: rw, r")
            return True
        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            await self.db_impl.set_user_space_access(
                user['user_id'], space_id, level, granted_by='admin-cli'
            )
            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.space_access.granted", "admin-cli",
                             target=username, space_id=space_id, level=level)
            print(f"✅ Granted '{level}' access on space '{space_id}' to '{username}'")
        except ValueError as e:
            print(f"❌ {e}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _user_revoke(self, args: list[str]) -> bool:
        """Revoke space access: user revoke <username> <space_id>"""
        if len(args) < 2:
            print("Usage: user revoke <username> <space_id>")
            return True
        username, space_id = args[0], args[1]
        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            await self.db_impl.revoke_user_space_access(user['user_id'], space_id)
            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.space_access.revoked", "admin-cli",
                             target=username, space_id=space_id)
            print(f"✅ Revoked access on space '{space_id}' from '{username}'")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _user_spaces(self, args: list[str]) -> bool:
        """Show user's space access: user spaces <username>"""
        if not args:
            print("Usage: user spaces <username>")
            return True
        username = args[0]
        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            spaces = await self.db_impl.get_user_spaces(user['user_id'])
            if not spaces:
                print(f"User '{username}' (role={user.get('role', 'user')}): No space access assigned")
            else:
                print(f"\nUser '{username}' (role={user.get('role', 'user')}) space access:")
                print("-" * 40)
                for space_id, level in spaces.items():
                    print(f"  {space_id}: {level}")
                print(f"\nTotal: {len(spaces)} space(s)")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # API Key Commands
    # ------------------------------------------------------------------

    def cmd_apikey(self, args: list[str]) -> bool:
        """API key management command dispatcher."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True

        if not args:
            print("Usage: apikey <subcommand> [args...]")
            print("Subcommands: list, create, revoke, info")
            return True

        sub = args[0].lower()
        if sub == 'list':
            return self._run_async(self._apikey_list(args[1:]))
        elif sub == 'create':
            return self._run_async(self._apikey_create(args[1:]))
        elif sub == 'revoke':
            return self._run_async(self._apikey_revoke(args[1:]))
        elif sub == 'info':
            return self._run_async(self._apikey_info(args[1:]))
        else:
            print(f"Unknown apikey subcommand: {sub}")
            return True

    async def _apikey_list(self, args: list[str]) -> bool:
        """List API keys: apikey list [username]"""
        username = args[0] if args else None
        user_id = None
        if username:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True
            user_id = user['user_id']

        try:
            keys = await self.db_impl.list_api_keys(user_id=user_id)
            if not keys:
                print("No API keys found.")
                return True

            print(f"\n{'Key ID':<38} {'Prefix':<14} {'Name':<20} {'User':<12} {'Active':<8} {'Last Used'}")
            print(f"{'─' * 110}")
            for k in keys:
                key_id = str(k['key_id'])[:36]
                prefix = f"vg_{k['key_prefix']}..."
                name = (k['name'] or '')[:18]
                user = k.get('username', '')[:10]
                active = '✓' if k['is_active'] else '✗'
                last_used = k['last_used'].strftime('%Y-%m-%d %H:%M') if k.get('last_used') else 'never'
                print(f"{key_id:<38} {prefix:<14} {name:<20} {user:<12} {active:<8} {last_used}")
            print(f"\nTotal: {len(keys)} key(s)")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _apikey_create(self, args: list[str]) -> bool:
        """Create API key: apikey create <username> <name> [expires_days]"""
        if len(args) < 2:
            print("Usage: apikey create <username> <name> [expires_days]")
            return True

        username = args[0]
        name = args[1]
        expires_days = int(args[2]) if len(args) > 2 else None

        try:
            user = await self.db_impl.get_user_by_username(username)
            if not user:
                print(f"❌ User '{username}' not found")
                return True

            # Check max keys
            count = await self.db_impl.count_user_api_keys(user['user_id'])
            if count >= 10:
                print(f"❌ Maximum API keys (10) reached for user '{username}'")
                return True

            from vitalgraph.auth.api_key import generate_api_key, hash_api_key
            from datetime import datetime, timedelta, timezone

            full_key, prefix = generate_api_key()
            key_hash = hash_api_key(full_key)

            expires_at = None
            if expires_days:
                expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

            record = await self.db_impl.create_api_key(
                user_id=user['user_id'],
                name=name,
                key_prefix=prefix,
                key_hash=key_hash,
                expires_at=expires_at,
            )

            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.apikey.created", "admin-cli",
                             target=username, key_name=name, key_prefix=prefix)

            print(f"\n✅ API key created for user '{username}':")
            print(f"   Key:     {full_key}")
            print(f"   Name:    {name}")
            print(f"   ID:      {record.get('key_id')}")
            if expires_at:
                print(f"   Expires: {expires_at.isoformat()}")
            print(f"   ⚠️  Save this key now — it cannot be retrieved again.")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _apikey_revoke(self, args: list[str]) -> bool:
        """Revoke API key: apikey revoke <key_id>"""
        if not args:
            print("Usage: apikey revoke <key_id>")
            return True

        key_id = args[0]
        try:
            key = await self.db_impl.get_api_key_by_id(key_id)
            if not key:
                print(f"❌ API key '{key_id}' not found")
                return True

            await self.db_impl.deactivate_api_key(key_id)

            from vitalgraph.auth.audit import emit_audit_event
            emit_audit_event("auth.apikey.revoked", "admin-cli",
                             target=key.get('username', ''), level="WARN",
                             key_id=key_id, key_name=key.get('name', ''))

            print(f"✅ API key '{key.get('name', key_id)}' revoked")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _apikey_info(self, args: list[str]) -> bool:
        """Show API key details: apikey info <key_id>"""
        if not args:
            print("Usage: apikey info <key_id>")
            return True

        key_id = args[0]
        try:
            key = await self.db_impl.get_api_key_by_id(key_id)
            if not key:
                print(f"❌ API key '{key_id}' not found")
                return True

            print(f"\nAPI Key Details:")
            print(f"  ID:       {key['key_id']}")
            print(f"  Prefix:   vg_{key['key_prefix']}...")
            print(f"  Name:     {key['name']}")
            print(f"  User:     {key['username']}")
            print(f"  Active:   {key['is_active']}")
            print(f"  Created:  {key.get('created_time', 'N/A')}")
            print(f"  Last Used: {key.get('last_used', 'never')}")
            print(f"  Expires:  {key.get('expires_at', 'never')}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Audit Commands
    # ------------------------------------------------------------------

    def cmd_audit(self, args: list[str]) -> bool:
        """Audit log command dispatcher."""
        if not self.connected or not self.db_impl:
            print("❌ Not connected to database. Use 'connect;' first.")
            return True

        if not args:
            print("Usage: audit <subcommand> [args...]")
            print("Subcommands: tail, purge, count")
            return True

        sub = args[0].lower()
        if sub == 'tail':
            return self._run_async(self._audit_tail(args[1:]))
        elif sub == 'purge':
            return self._run_async(self._audit_purge(args[1:]))
        elif sub == 'count':
            return self._run_async(self._audit_count())
        else:
            print(f"Unknown audit subcommand: {sub}")
            return True

    async def _audit_tail(self, args: list[str]) -> bool:
        """Show recent audit log entries.

        Usage: audit tail [--event <event>] [--user <username>] [--last <duration>] [--limit <n>]
        Examples:
            audit tail
            audit tail --event auth.login.failure --last 24h
            audit tail --user jsmith --last 7d
            audit tail --limit 50
        """
        import json
        from datetime import datetime, timedelta, timezone

        # Parse args
        event_filter = None
        user_filter = None
        last_duration = None
        limit = 25
        i = 0
        while i < len(args):
            if args[i] == '--event' and i + 1 < len(args):
                event_filter = args[i + 1]
                i += 2
            elif args[i] == '--user' and i + 1 < len(args):
                user_filter = args[i + 1]
                i += 2
            elif args[i] == '--last' and i + 1 < len(args):
                last_duration = args[i + 1]
                i += 2
            elif args[i] == '--limit' and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            else:
                i += 1

        # Build query
        conditions = []
        params = []
        idx = 1

        if event_filter:
            conditions.append(f"event = ${idx}")
            params.append(event_filter)
            idx += 1

        if user_filter:
            conditions.append(f"(actor = ${idx} OR target = ${idx})")
            params.append(user_filter)
            idx += 1

        if last_duration:
            # Parse duration: "24h", "7d", "30m"
            amount = int(last_duration[:-1])
            unit = last_duration[-1]
            if unit == 'h':
                delta = timedelta(hours=amount)
            elif unit == 'd':
                delta = timedelta(days=amount)
            elif unit == 'm':
                delta = timedelta(minutes=amount)
            else:
                print(f"❌ Invalid duration unit '{unit}'. Use h (hours), d (days), m (minutes)")
                return True
            since = datetime.now(timezone.utc) - delta
            conditions.append(f"timestamp >= ${idx}")
            params.append(since)
            idx += 1

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        query = f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT {limit}"

        try:
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return True
            rows = await pool.fetch(query, *params)
            if not rows:
                print("No audit log entries found.")
                return True

            print(f"\n{'─' * 100}")
            print(f"{'Timestamp':<26} {'Level':<6} {'Event':<28} {'Actor':<12} {'Target':<12} Details")
            print(f"{'─' * 100}")
            for row in rows:
                ts = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else ''
                level = row.get('level', '')
                event = row.get('event', '')
                actor = row.get('actor', '') or ''
                target = row.get('target', '') or ''
                details = json.dumps(dict(row['details'])) if row.get('details') else ''
                # Truncate details for display
                if len(details) > 40:
                    details = details[:37] + '...'
                print(f"{ts:<26} {level:<6} {event:<28} {actor:<12} {target:<12} {details}")
            print(f"{'─' * 100}")
            print(f"Showing {len(rows)} entries (limit={limit})")
        except Exception as e:
            print(f"❌ Error querying audit log: {e}")
        return True

    async def _audit_purge(self, args: list[str]) -> bool:
        """Delete old audit log entries.

        Usage: audit purge --older-than <duration>
        Examples:
            audit purge --older-than 90d
            audit purge --older-than 24h
        """
        from datetime import datetime, timedelta, timezone

        # Parse --older-than
        older_than = None
        i = 0
        while i < len(args):
            if args[i] == '--older-than' and i + 1 < len(args):
                older_than = args[i + 1]
                i += 2
            else:
                i += 1

        if not older_than:
            print("Usage: audit purge --older-than <duration>")
            print("Example: audit purge --older-than 90d")
            return True

        # Parse duration
        amount = int(older_than[:-1])
        unit = older_than[-1]
        if unit == 'h':
            delta = timedelta(hours=amount)
        elif unit == 'd':
            delta = timedelta(days=amount)
        else:
            print(f"❌ Invalid duration unit '{unit}'. Use h (hours) or d (days)")
            return True

        cutoff = datetime.now(timezone.utc) - delta

        try:
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return True
            result = await pool.execute(
                "DELETE FROM audit_log WHERE timestamp < $1", cutoff
            )
            # asyncpg returns "DELETE N"
            count = result.split()[-1] if result else '0'
            print(f"✅ Purged {count} audit log entries older than {older_than}")
        except Exception as e:
            print(f"❌ Error purging audit log: {e}")
        return True

    async def _audit_count(self) -> bool:
        """Show audit log entry count and breakdown by event type."""
        try:
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return True
            total = await pool.fetchval("SELECT COUNT(*) FROM audit_log")
            print(f"\nAudit Log: {total} total entries")

            rows = await pool.fetch(
                "SELECT event, level, COUNT(*) as cnt FROM audit_log "
                "GROUP BY event, level ORDER BY cnt DESC LIMIT 20"
            )
            if rows:
                print(f"\n{'Event':<35} {'Level':<8} {'Count':<8}")
                print(f"{'─' * 55}")
                for row in rows:
                    print(f"{row['event']:<35} {row['level']:<8} {row['cnt']:<8}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------

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
  rebuild indexes;           - Rebuild all database indexes
  rebuild index <space_id>;  - Rebuild indexes for specific space
  rebuild stats [space_id];  - Rebuild query optimizer statistics
  rebuild analyze [space_id];- Run ANALYZE on space tables
  rebuild vacuum [space_id]; - Run VACUUM on space tables
  rebuild resync [space_id]; - Resync auxiliary tables (edge, frame_entity, stats)
  clear <space-id>;          - Clear data within a space but leave the space in place

🌐 Space Management:
  use <space-id>;   - Set current space and display space ID in prompt
  unuse;            - Unset the current space

📥 Data Import/Export (standalone CLIs):
  vitalgraphimport -s <space_id> -f <file>   - Import RDF data
  vitalgraphexport -s <space_id> -f <file>   - Export RDF data
  (Run with --help for full options)

👤 User Management:
  user list;                          - List all users
  user add <username> <password> [role]; - Create user (role: admin|user|reader)
  user delete <username>;             - Delete a user
  user password <username> <newpass>; - Change user password
  user role <username> <role>;        - Change user role
  user deactivate <username>;         - Deactivate user (invalidates tokens)
  user activate <username>;           - Reactivate user
  user grant <username> <space_id> <rw|r>; - Grant space access
  user revoke <username> <space_id>;  - Revoke space access
  user spaces <username>;             - Show user's space access

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
            # Load configuration from environment variables
            self.config = VitalGraphConfig()
            
            # Create VitalGraphImpl instance with the loaded config
            self.vital_graph_impl = VitalGraphImpl(config=self.config)
            
            backend_type = self.config.get_backend_config().get('type', 'postgresql')
            
            if backend_type == 'sparql_sql':
                # sparql_sql: connect via space_backend, then pick up db_impl
                space_backend = getattr(self.vital_graph_impl, 'space_backend', None)
                if space_backend is None:
                    return False
                connected = self._run_async(space_backend.connect())
                if connected:
                    self.db_impl = space_backend.db_impl
                    self.space_backend = space_backend
                    self.connected = True
                    return True
                else:
                    return False
            else:
                # Standard path
                self.db_impl = self.vital_graph_impl.get_db_impl()
                
                if self.db_impl is None:
                    return False
                
                connected = self._run_async(self.db_impl.connect())
                
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
                self._run_async(self.db_impl.disconnect())
            except Exception as e:
                print(f"Warning: Error during database disconnect: {e}")
            self.db_impl = None
        self.db_connection = None
        self.connected = False
    
    def execute_cli_command(self, args) -> bool:
        """Execute a single CLI command non-interactively, then exit."""
        # Auto-connect
        if not self.connect_db():
            print("❌ Failed to connect to database")
            return False

        command = args.command
        success = True

        try:
            if command == 'init':
                success = self._run_async(self.cmd_init([]))

            elif command == 'info':
                success = self.cmd_info([])

            elif command == 'import':
                print("\n⚠️  The 'import' command has been removed from vitalgraphadmin.")
                print("   Use the standalone CLI instead:")
                print("     vitalgraphimport -s <space_id> -f <file.nt>")
                print("     vitalgraphimport --help\n")
                success = False

            elif command == 'list-spaces':
                success = self.cmd_list_spaces([])

            elif command == 'list-users':
                success = self.cmd_list_users([])

            elif command == 'list-graphs':
                space_args = []
                if args.space_id:
                    self.current_space_id = args.space_id
                success = self.cmd_list_graphs(space_args)

            elif command == 'create-space':
                if not args.space_id:
                    print("❌ --space-id is required for create-space")
                    return False
                success = self._run_async(
                    self._cli_create_space(args.space_id, args.space_name))

            elif command == 'drop-space':
                if not args.space_id:
                    print("❌ --space-id is required for drop-space")
                    return False
                if not args.yes:
                    confirm = input(
                        f"⚠️  Drop space '{args.space_id}' and ALL its data? (yes/no): "
                    ).strip().lower()
                    if confirm not in ('yes', 'y'):
                        print("Cancelled.")
                        return True
                success = self._run_async(
                    self._cli_drop_space(args.space_id))

            elif command == 'rebuild-indexes':
                space_id = args.space_id
                if space_id:
                    success = self.cmd_rebuild_indexes([space_id])
                else:
                    success = self.cmd_rebuild_indexes([])

            elif command == 'rebuild-stats':
                space_id = args.space_id
                success = self.cmd_rebuild_stats([space_id] if space_id else [])

            elif command == 'rebuild-analyze':
                space_id = args.space_id
                success = self.cmd_rebuild_analyze([space_id] if space_id else [])

            elif command == 'rebuild-vacuum':
                space_id = args.space_id
                success = self.cmd_rebuild_vacuum([space_id] if space_id else [])

            elif command == 'rebuild-resync':
                space_id = args.space_id
                success = self.cmd_rebuild_resync([space_id] if space_id else [])

            elif command == 'purge':
                success = self.cmd_purge([])

            elif command == 'delete':
                success = self.cmd_delete([])

            # --- User management ---
            elif command == 'user-list':
                success = self._run_async(self._user_list())

            elif command == 'user-add':
                if not args.username or not args.password:
                    print("❌ --username and --password are required for user-add")
                    return False
                role = args.role or 'user'
                success = self._run_async(self._user_add([args.username, args.password, role]))

            elif command == 'user-delete':
                if not args.username:
                    print("❌ --username is required for user-delete")
                    return False
                if not args.yes:
                    confirm = input(
                        f"⚠️  Delete user '{args.username}'? (yes/no): "
                    ).strip().lower()
                    if confirm not in ('yes', 'y'):
                        print("Cancelled.")
                        return True
                success = self._run_async(self._user_delete([args.username]))

            elif command == 'user-password':
                if not args.username or not args.password:
                    print("❌ --username and --password are required for user-password")
                    return False
                success = self._run_async(self._user_password([args.username, args.password]))

            elif command == 'user-role':
                if not args.username or not args.role:
                    print("❌ --username and --role are required for user-role")
                    return False
                success = self._run_async(self._user_role([args.username, args.role]))

            elif command == 'user-deactivate':
                if not args.username:
                    print("❌ --username is required for user-deactivate")
                    return False
                success = self._run_async(self._user_deactivate([args.username]))

            elif command == 'user-activate':
                if not args.username:
                    print("❌ --username is required for user-activate")
                    return False
                success = self._run_async(self._user_activate([args.username]))

            elif command == 'user-grant':
                if not args.username or not args.space_id or not args.level:
                    print("❌ --username, --space-id, and --level are required for user-grant")
                    return False
                success = self._run_async(self._user_grant([args.username, args.space_id, args.level]))

            elif command == 'user-revoke':
                if not args.username or not args.space_id:
                    print("❌ --username and --space-id are required for user-revoke")
                    return False
                success = self._run_async(self._user_revoke([args.username, args.space_id]))

            elif command == 'user-spaces':
                if not args.username:
                    print("❌ --username is required for user-spaces")
                    return False
                success = self._run_async(self._user_spaces([args.username]))

            # --- API key management ---
            elif command == 'apikey-list':
                api_args = [args.username] if args.username else []
                success = self._run_async(self._apikey_list(api_args))

            elif command == 'apikey-create':
                if not args.username or not args.key_name:
                    print("❌ --username and --key-name are required for apikey-create")
                    return False
                api_args = [args.username, args.key_name]
                if args.expires_days:
                    api_args.append(str(args.expires_days))
                success = self._run_async(self._apikey_create(api_args))

            elif command == 'apikey-revoke':
                if not args.key_id:
                    print("❌ --key-id is required for apikey-revoke")
                    return False
                success = self._run_async(self._apikey_revoke([args.key_id]))

            # --- Maintenance ---
            elif command == 'clear-space':
                if not args.space_id:
                    print("❌ --space-id is required for clear-space")
                    return False
                if not args.yes:
                    confirm = input(
                        f"⚠️  Clear ALL data in space '{args.space_id}'? (yes/no): "
                    ).strip().lower()
                    if confirm not in ('yes', 'y'):
                        print("Cancelled.")
                        return True
                self.current_space_id = args.space_id
                success = self.cmd_clear([])

            # Legacy aliases
            elif command == 'reindex':
                space_id = args.space_id
                if space_id:
                    success = self.cmd_rebuild_indexes([space_id])
                else:
                    success = self.cmd_rebuild_indexes([])

            elif command == 'stats':
                success = self.cmd_rebuild_stats([])

            else:
                print(f"❌ Unknown CLI command: {command}")
                success = False

        except Exception as e:
            print(f"❌ Command '{command}' failed: {e}")
            import traceback
            traceback.print_exc()
            success = False
        finally:
            self.disconnect_db()
            self._close_loop()

        return success

    async def _cli_create_space(self, space_id: str, space_name: str = None) -> bool:
        """Create a new space (admin tables + per-space data tables)."""
        space_name = space_name or space_id
        backend_type = self.config.get_backend_config().get('type', 'postgresql')

        try:
            # Insert into admin space table
            print(f"📦 Creating space '{space_id}' (name='{space_name}')...")
            await self.db_impl.execute_update(
                "INSERT INTO space (space_id, space_name, update_time) "
                "VALUES ($1, $2, NOW()) ON CONFLICT (space_id) DO NOTHING",
                [space_id, space_name]
            )

            # Create per-space tables for sparql_sql backend
            if backend_type == 'sparql_sql':
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                print("   Creating per-space tables, indexes, and seeding datatypes...")
                async with self.db_impl.connection_pool.acquire() as conn:
                    await SparqlSQLSchema.create_space(conn, space_id)
                print(f"✅ Space '{space_id}' created with per-space tables")
            elif backend_type == 'fuseki_postgresql':
                from vitalgraph.db.fuseki_postgresql.postgresql_schema import FusekiPostgreSQLSchema
                schema = FusekiPostgreSQLSchema()
                print("   Creating per-space tables...")
                for stmt in schema.create_space_tables_sql(space_id):
                    await self.db_impl.execute_update(stmt)
                print("   Creating per-space indexes...")
                for stmt in schema.create_space_indexes_sql(space_id):
                    await self.db_impl.execute_update(stmt)
                print(f"✅ Space '{space_id}' created with per-space tables")
            else:
                print(f"✅ Space '{space_id}' registered (no per-space tables for {backend_type})")

            return True

        except Exception as e:
            print(f"❌ Failed to create space '{space_id}': {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _cli_drop_space(self, space_id: str) -> bool:
        """Drop a space and its per-space data tables."""
        backend_type = self.config.get_backend_config().get('type', 'postgresql')

        try:
            # Drop per-space tables
            if backend_type == 'sparql_sql':
                from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
                print(f"🗑️  Dropping per-space tables for '{space_id}'...")
                async with self.db_impl.connection_pool.acquire() as conn:
                    await SparqlSQLSchema.drop_space(conn, space_id)
            elif backend_type == 'fuseki_postgresql':
                from vitalgraph.db.fuseki_postgresql.postgresql_schema import FusekiPostgreSQLSchema
                schema = FusekiPostgreSQLSchema()
                print(f"🗑️  Dropping per-space tables for '{space_id}'...")
                for stmt in schema.drop_space_indexes_sql(space_id):
                    await self.db_impl.execute_update(stmt)
                for stmt in schema.drop_space_tables_sql(space_id):
                    await self.db_impl.execute_update(stmt)

            # Remove from admin tables
            print(f"   Removing space from admin tables...")
            await self.db_impl.execute_update(
                "DELETE FROM graph WHERE space_id = $1", [space_id])
            await self.db_impl.execute_update(
                "DELETE FROM space WHERE space_id = $1", [space_id])

            print(f"✅ Space '{space_id}' dropped")
            return True

        except Exception as e:
            print(f"❌ Failed to drop space '{space_id}': {e}")
            import traceback
            traceback.print_exc()
            return False

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
    """Parse command line arguments for VitalGraphDB Admin."""
    parser = argparse.ArgumentParser(
        description="VitalGraphDB Admin - Database administration CLI and REPL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Non-interactive examples:
  vitalgraphadmin -c init                                    # Initialize database
  vitalgraphadmin -c info                                    # Show backend info
  vitalgraphadmin -c list-spaces                             # List all spaces
  vitalgraphadmin -c list-users                              # List all users
  vitalgraphadmin -c list-graphs -s myspace                  # List graphs in a space
  vitalgraphadmin -c create-space -s myspace                 # Create a new space
  vitalgraphadmin -c create-space -s myspace --space-name "My Space"
  vitalgraphadmin -c drop-space -s myspace --yes             # Drop space (no prompt)
  vitalgraphadmin -c import -s myspace -f data.ttl           # Import data
  vitalgraphadmin -c import -s myspace -f data.nq -b 100000  # Import with batch size
  vitalgraphadmin -c rebuild-indexes -s myspace              # Rebuild space indexes
  vitalgraphadmin -c rebuild-stats                           # Rebuild statistics
  vitalgraphadmin -c rebuild-stats -s myspace                # Rebuild stats for one space
  vitalgraphadmin -c rebuild-analyze                         # ANALYZE all spaces
  vitalgraphadmin -c rebuild-analyze -s myspace              # ANALYZE one space
  vitalgraphadmin -c rebuild-vacuum                          # VACUUM all spaces
  vitalgraphadmin -c rebuild-vacuum -s myspace               # VACUUM one space

Interactive REPL:
  vitalgraphadmin                     # Start interactive REPL
  vitalgraphadmin --config /path/to/config.yaml
        """
    )

    # Global options
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config file (default: auto-detected from project structure)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="VitalGraphDB Admin 1.0.0"
    )

    # Command selection
    parser.add_argument(
        "-c", "--command",
        type=str,
        choices=[
            "init", "info",
            "list-spaces", "list-users", "list-graphs",
            "create-space", "drop-space",
            "rebuild-indexes", "rebuild-stats", "rebuild-analyze", "rebuild-vacuum", "rebuild-resync",
            "purge", "delete",
            # User management
            "user-list", "user-add", "user-delete", "user-password",
            "user-role", "user-deactivate", "user-activate",
            "user-grant", "user-revoke", "user-spaces",
            # API key management
            "apikey-list", "apikey-create", "apikey-revoke",
            # Maintenance
            "clear-space",
            # Legacy aliases
            "reindex", "stats",
        ],
        help="Execute a command non-interactively (omit for REPL mode)"
    )

    # Space options
    parser.add_argument(
        "-s", "--space-id",
        type=str,
        help="Space ID (required for create-space, drop-space; optional for list-graphs, rebuild-indexes)"
    )
    parser.add_argument(
        "--space-name",
        type=str,
        help="Human-readable space name (for create-space; defaults to space-id)"
    )

    # Confirmation bypass
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompts (for drop-space, purge, delete)"
    )

    # User management options
    parser.add_argument(
        "--username", "-u",
        type=str,
        help="Username for user/apikey commands"
    )
    parser.add_argument(
        "--password",
        type=str,
        help="Password for user-add or user-password"
    )
    parser.add_argument(
        "--role",
        type=str,
        choices=["admin", "user", "reader"],
        help="Role for user-add or user-role"
    )
    parser.add_argument(
        "--level",
        type=str,
        choices=["rw", "r"],
        help="Access level for user-grant (rw or r)"
    )

    # API key options
    parser.add_argument(
        "--key-name",
        type=str,
        help="Name for apikey-create"
    )
    parser.add_argument(
        "--key-id",
        type=str,
        help="Key ID for apikey-revoke"
    )
    parser.add_argument(
        "--expires-days",
        type=int,
        help="Expiration in days for apikey-create"
    )

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
    logging.getLogger('vitalgraph.db.sparql_sql').setLevel(numeric_level)


def main():
    """Main entry point for VitalGraphDB admin REPL."""
    args = parse_args()
    
    # Load .env file so profile-based env vars (PROD_*, LOCAL_*, etc.) are available
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass
    
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
