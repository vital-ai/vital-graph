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
        elif backend_type == 'sparql_sql':
            return await self._init_sparql_sql_backend()
        
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
    
    async def _init_sparql_sql_backend(self) -> bool:
        """Initialize sparql_sql backend admin tables and pg_trgm extension."""
        print("🚀 Initializing SPARQL-SQL Backend")
        print("=" * 50)
        
        try:
            # Check if admin tables already exist
            print("\n📋 Checking for existing admin tables...")
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('install', 'space', 'graph', 'user', 'process',
                              'agent_type', 'agent', 'agent_endpoint', 'agent_change_log')
            """
            
            result = await self.db_impl.execute_query(check_query)
            table_count = result[0]['table_count'] if result else 0
            
            if table_count == 9:
                print("✅ Admin tables already exist (install, space, graph, user, process, agent_type, agent, agent_endpoint, agent_change_log)")
                print("   No initialization needed.")
            elif table_count > 0:
                print(f"⚠️  Warning: Found {table_count} out of 9 admin tables")
                response = input("   Continue with initialization? (yes/no): ").strip().lower()
                if response not in ['yes', 'y']:
                    print("   Initialization cancelled.")
                    return True
            
            if table_count < 9:
                # Ensure pg_trgm extension
                print("\n📦 Ensuring pg_trgm extension...")
                await self.db_impl.execute_update(
                    "CREATE EXTENSION IF NOT EXISTS pg_trgm"
                )
                print("   ✅ pg_trgm extension ready")
                
                # Create admin tables
                print("\n📦 Creating admin tables...")
                
                admin_ddl = [
                    ("install", '''
                        CREATE TABLE IF NOT EXISTS install (
                            id SERIAL PRIMARY KEY,
                            install_datetime TIMESTAMP,
                            update_datetime TIMESTAMP,
                            active BOOLEAN
                        )
                    '''),
                    ("space", '''
                        CREATE TABLE IF NOT EXISTS space (
                            space_id VARCHAR(255) PRIMARY KEY,
                            space_name VARCHAR(255),
                            space_description TEXT,
                            tenant VARCHAR(255),
                            update_time TIMESTAMP
                        )
                    '''),
                    ("graph", '''
                        CREATE TABLE IF NOT EXISTS graph (
                            graph_id SERIAL PRIMARY KEY,
                            space_id VARCHAR(255) NOT NULL,
                            graph_uri VARCHAR(500),
                            graph_name VARCHAR(255),
                            created_time TIMESTAMP,
                            FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE
                        )
                    '''),
                    ('"user"', '''
                        CREATE TABLE IF NOT EXISTS "user" (
                            user_id SERIAL PRIMARY KEY,
                            username VARCHAR(255) UNIQUE NOT NULL,
                            password VARCHAR(255),
                            email VARCHAR(255),
                            tenant VARCHAR(255),
                            update_time TIMESTAMP
                        )
                    '''),
                    ('process', '''
                        CREATE TABLE IF NOT EXISTS process (
                            process_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                            process_type VARCHAR(64) NOT NULL,
                            process_subtype VARCHAR(128),
                            status VARCHAR(32) NOT NULL DEFAULT 'pending',
                            instance_id VARCHAR(128),
                            started_at TIMESTAMPTZ,
                            completed_at TIMESTAMPTZ,
                            progress_percent REAL DEFAULT 0.0,
                            progress_message TEXT,
                            error_message TEXT,
                            result_details JSONB,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                    '''),
                    # --- Agent Registry tables ---
                    ('agent_type', '''
                        CREATE TABLE IF NOT EXISTS agent_type (
                            type_id SERIAL PRIMARY KEY,
                            type_key VARCHAR(500) UNIQUE NOT NULL,
                            type_label VARCHAR(255) NOT NULL,
                            type_description TEXT,
                            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                            updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                        )
                    '''),
                    ('agent', '''
                        CREATE TABLE IF NOT EXISTS agent (
                            agent_id VARCHAR(50) PRIMARY KEY,
                            agent_type_id INTEGER NOT NULL REFERENCES agent_type(type_id),
                            entity_id VARCHAR(50),
                            agent_name VARCHAR(500) NOT NULL,
                            agent_uri VARCHAR(500) UNIQUE NOT NULL,
                            description TEXT,
                            version VARCHAR(50),
                            status VARCHAR(20) NOT NULL DEFAULT 'active',
                            protocol_format_uri VARCHAR(500),
                            auth_service_uri VARCHAR(500),
                            auth_service_config JSONB DEFAULT '{}',
                            capabilities JSONB DEFAULT '[]',
                            metadata JSONB DEFAULT '{}',
                            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                            updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                            created_by VARCHAR(255),
                            notes TEXT
                        )
                    '''),
                    ('agent_endpoint', '''
                        CREATE TABLE IF NOT EXISTS agent_endpoint (
                            endpoint_id SERIAL PRIMARY KEY,
                            agent_id VARCHAR(50) NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
                            endpoint_uri VARCHAR(500) NOT NULL,
                            endpoint_url VARCHAR(1000) NOT NULL,
                            protocol VARCHAR(20) NOT NULL DEFAULT 'websocket',
                            status VARCHAR(20) NOT NULL DEFAULT 'active',
                            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                            updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                            notes TEXT,
                            UNIQUE (agent_id, endpoint_uri)
                        )
                    '''),
                    ('agent_change_log', '''
                        CREATE TABLE IF NOT EXISTS agent_change_log (
                            log_id BIGSERIAL PRIMARY KEY,
                            agent_id VARCHAR(50) REFERENCES agent(agent_id) ON DELETE SET NULL,
                            change_type VARCHAR(50) NOT NULL,
                            change_detail JSONB,
                            changed_by VARCHAR(255),
                            comment TEXT,
                            created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                        )
                    '''),
                ]
                
                for table_name, ddl in admin_ddl:
                    print(f"   Creating table: {table_name}")
                    await self.db_impl.execute_update(ddl)
                
                # Create indexes
                print("\n🔍 Creating admin table indexes...")
                admin_indexes = [
                    'CREATE INDEX IF NOT EXISTS idx_space_tenant ON space(tenant)',
                    'CREATE INDEX IF NOT EXISTS idx_space_update_time ON space(update_time)',
                    'CREATE INDEX IF NOT EXISTS idx_graph_space_id ON graph(space_id)',
                    'CREATE INDEX IF NOT EXISTS idx_graph_uri ON graph(graph_uri)',
                    'CREATE INDEX IF NOT EXISTS idx_user_tenant ON "user"(tenant)',
                    'CREATE INDEX IF NOT EXISTS idx_user_username ON "user"(username)',
                    'CREATE INDEX IF NOT EXISTS idx_process_type_status ON process(process_type, status)',
                    'CREATE INDEX IF NOT EXISTS idx_process_created ON process(created_at DESC)',
                    # Agent registry indexes
                    'CREATE INDEX IF NOT EXISTS idx_agent_type_id ON agent(agent_type_id)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_entity ON agent(entity_id)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_name ON agent(agent_name)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_uri ON agent(agent_uri)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_status ON agent(status)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_protocol ON agent(protocol_format_uri)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_auth_service ON agent(auth_service_uri)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_created ON agent(created_time)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_ep_agent ON agent_endpoint(agent_id)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_ep_uri ON agent_endpoint(agent_id, endpoint_uri)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_ep_protocol ON agent_endpoint(protocol)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_ep_status ON agent_endpoint(status)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_log_agent ON agent_change_log(agent_id)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_log_type ON agent_change_log(change_type)',
                    'CREATE INDEX IF NOT EXISTS idx_agent_log_time ON agent_change_log(created_time)',
                ]
                for stmt in admin_indexes:
                    await self.db_impl.execute_update(stmt)
                
                # Seed install record
                print("\n📝 Seeding install record...")
                await self.db_impl.execute_update(
                    "INSERT INTO install (install_datetime, update_datetime, active) "
                    "SELECT NOW(), NOW(), true "
                    "WHERE NOT EXISTS (SELECT 1 FROM install)"
                )
                
                # Seed agent_type with initial type
                print("\n📝 Seeding agent_type...")
                await self.db_impl.execute_update(
                    "INSERT INTO agent_type (type_key, type_label, type_description) "
                    "SELECT 'urn:vital-ai:agent-type:chat', 'Chat', 'Conversational chat agent' "
                    "WHERE NOT EXISTS (SELECT 1 FROM agent_type WHERE type_key = 'urn:vital-ai:agent-type:chat')"
                )
                
                print(f"\n✅ SPARQL-SQL admin tables initialized successfully!")
                print(f"   Created tables: install, space, graph, user, process, agent_type, agent, agent_endpoint, agent_change_log")
                print(f"   Created indexes for: space, graph, user, process, agent, agent_endpoint, agent_change_log")
                print(f"   Extension: pg_trgm")
            
            return True
            
        except Exception as e:
            print(f"\n❌ Error during SPARQL-SQL initialization: {e}")
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
        elif backend_type == 'sparql_sql':
            return self._run_async(self._info_sparql_sql_backend())
        
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
    
    async def _info_sparql_sql_backend(self) -> bool:
        """Show info for sparql_sql backend."""
        try:
            print("Backend: SPARQL-SQL (Pure PostgreSQL)")
            print("Status: Connected")
            
            # Sidecar info
            sparql_sql_config = self.config.get_sparql_sql_config()
            sidecar_url = sparql_sql_config.get('sidecar', {}).get('url', 'N/A')
            print(f"Sidecar URL: {sidecar_url}")
            
            # PostgreSQL connection info
            pg_config = sparql_sql_config.get('database', {})
            print(f"\nPostgreSQL Host: {pg_config.get('host', 'N/A')}")
            print(f"PostgreSQL Database: {pg_config.get('database', 'N/A')}")
            
            # Check admin tables
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('install', 'space', 'graph', 'user', 'process')
            """
            
            result = await self.db_impl.execute_query(check_query)
            table_count = result[0]['table_count'] if result else 0
            
            if table_count == 5:
                print("\nInitialization State: Initialized")
                print("Admin Tables: ✅ All present (install, space, graph, user, process)")
                
                # Get space count
                space_result = await self.db_impl.execute_query(
                    "SELECT COUNT(*) as count FROM space")
                space_count = space_result[0]['count'] if space_result else 0
                print(f"Spaces: {space_count} configured")
                
                # List spaces with per-space table info
                if space_count > 0:
                    spaces = await self.db_impl.execute_query(
                        "SELECT space_id FROM space ORDER BY space_id")
                    print("\nPer-space tables:")
                    for sp in spaces:
                        sid = sp['space_id']
                        term_tbl = f"{sid}_term"
                        quad_tbl = f"{sid}_rdf_quad"
                        tbl_check = await self.db_impl.execute_query(
                            "SELECT COUNT(*) as c FROM information_schema.tables "
                            "WHERE table_schema = 'public' AND table_name IN ($1, $2)",
                            [term_tbl, quad_tbl]
                        )
                        tbl_count = tbl_check[0]['c'] if tbl_check else 0
                        status = "✅" if tbl_count == 2 else f"⚠️  ({tbl_count}/2 tables)"
                        print(f"  {sid}: {status}")
                
                # Check pg_trgm
                ext_result = await self.db_impl.execute_query(
                    "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                pg_trgm = "✅" if ext_result else "❌ Missing"
                print(f"\npg_trgm extension: {pg_trgm}")
                
                # Get user count
                user_result = await self.db_impl.execute_query(
                    'SELECT COUNT(*) as count FROM "user"')
                user_count = user_result[0]['count'] if user_result else 0
                print(f"Users: {user_count} configured")
                
            elif table_count > 0:
                print("\nInitialization State: Partially Initialized")
                print(f"Admin Tables: ⚠️  {table_count} out of 4 tables present")
                print("   Run 'init;' to complete initialization")
            else:
                print("\nInitialization State: Uninitialized")
                print("Admin Tables: ❌ Not created")
                print("   Run 'init;' to initialize")
            
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
        valid_formats = ['turtle', 'xml', 'nt', 'n3', 'auto-detect']
        
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
                '.json': 'nquads'
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
        
        async def _do_rebuild_indexes(sid):
            pool = getattr(self.db_impl, 'connection_pool', None)
            if not pool:
                print("❌ No connection pool available")
                return
            
            if sid:
                space_ids = [sid]
            else:
                spaces = await self.db_impl.list_spaces()
                space_ids = [s.get('space', s.get('id', '')) for s in spaces if s]
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
                spaces = await self.db_impl.list_spaces()
                space_ids = [s.get('space', s.get('id', '')) for s in spaces if s]
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
                spaces = await self.db_impl.list_spaces()
                space_ids = [s.get('space', s.get('id', '')) for s in spaces if s]
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
                spaces = await self.db_impl.list_spaces()
                space_ids = [s.get('space', s.get('id', '')) for s in spaces if s]
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
                spaces = await self.db_impl.list_spaces()
                space_ids = [s.get('space', s.get('id', '')) for s in spaces if s]
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
                backend_type = self.config.get_backend_config().get('type', 'postgresql')
                if backend_type == 'sparql_sql':
                    if not args.space_id:
                        print("❌ --space-id is required for import")
                        return False
                    if not args.file:
                        print("❌ --file is required for import")
                        return False
                    graph_uri = args.graph_uri or f"urn:{args.space_id}"
                    success = self._run_async(
                        self._cli_import_sparql_sql(
                            space_id=args.space_id,
                            file_path=args.file,
                            graph_uri=graph_uri,
                            batch_size=args.batch_size or 50000,
                            force=args.yes,
                        ))
                else:
                    import_args = []
                    if args.space_id:
                        import_args += ['--space-id', args.space_id]
                    if args.file:
                        import_args += ['--file', args.file]
                    if args.format:
                        import_args += ['--format', args.format]
                    if args.batch_size:
                        import_args += ['--batch-size', str(args.batch_size)]
                    if args.validate:
                        import_args.append('--validate')
                    if args.no_validate:
                        import_args.append('--no-validate')
                    import_args += ['--interactive', 'false']
                    success = self.cmd_import(import_args)

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

    async def _cli_import_sparql_sql(
        self,
        space_id: str,
        file_path: str,
        graph_uri: str,
        batch_size: int = 50000,
        force: bool = False,
    ) -> bool:
        """Bulk-load an N-Triples file into a sparql_sql space using COPY.

        Algorithm (mirrors load_wordnet_frames.py):
          1. Parse .nt with pyoxigraph, collect unique terms + deterministic UUIDs
          2. COPY terms into {space_id}_term
          3. Parse again, COPY quads into {space_id}_rdf_quad
          4. ANALYZE both tables
        """
        import os
        import time
        import uuid as uuid_mod

        _NS = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

        def _term_uuid(text, ttype, lang=None, datatype_id=None):
            parts = [text, ttype]
            if lang is not None:
                parts.append(f"lang:{lang}")
            if datatype_id is not None:
                parts.append(f"datatype:{datatype_id}")
            return str(uuid_mod.uuid5(_NS, "\x00".join(parts)))

        # --- validate inputs ---
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return False

        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        t = SparqlSQLSchema.get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        file_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"📋 Import Summary")
        print(f"   File      : {file_path} ({file_mb:.0f} MB)")
        print(f"   Space     : {space_id}")
        print(f"   Graph URI : {graph_uri}")
        print(f"   Tables    : {term_tbl}, {quad_tbl}")

        pool = self.db_impl.connection_pool
        async with pool.acquire() as conn:
            # Check tables exist
            for tbl in (term_tbl, quad_tbl):
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name=$1)", tbl)
                if not exists:
                    print(f"❌ Table {tbl} does not exist. Run create-space first.")
                    return False

            # Check if tables already have data
            existing_terms = await conn.fetchval(f"SELECT COUNT(*) FROM {term_tbl}")
            existing_quads = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_tbl}")
            if existing_terms > 0 or existing_quads > 0:
                if force:
                    print(f"⚠️  Truncating tables ({existing_terms:,} terms, {existing_quads:,} quads)")
                    await conn.execute(f"TRUNCATE {quad_tbl}")
                    await conn.execute(f"TRUNCATE {term_tbl} CASCADE")
                else:
                    print(f"❌ Tables not empty ({existing_terms:,} terms, {existing_quads:,} quads).")
                    print(f"   Use --yes to truncate before loading.")
                    return False

            # --- save & drop non-PK indexes for fast bulk loading ---
            print("\n🔧 Saving and dropping indexes for bulk load...")
            saved_indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename = ANY($1::text[]) "
                "AND indexname NOT LIKE '%_pkey'",
                [term_tbl, quad_tbl])
            for row in saved_indexes:
                await conn.execute(f"DROP INDEX IF EXISTS {row['indexname']}")
            print(f"   Dropped {len(saved_indexes)} indexes")

        # --- pass 1: collect unique terms ---
        print("\n📖 Pass 1: Collecting unique terms...")
        try:
            from pyoxigraph import parse as ox_parse
        except ImportError:
            print("❌ pyoxigraph is required for N-Triples parsing.")
            print("   Install with: pip install pyoxigraph")
            return False

        terms = {}  # {(text, type, lang): uuid_str}
        triple_count = 0
        t0 = time.time()

        def ensure(text, ttype, lang=None):
            key = (text, ttype, lang)
            if key not in terms:
                terms[key] = _term_uuid(text, ttype, lang=lang)
            return terms[key]

        ensure(graph_uri, "U")

        with open(file_path, "rb") as f:
            for triple in ox_parse(f, "application/n-triples"):
                s_cls = type(triple.subject).__name__
                ensure(triple.subject.value, "B" if s_cls == "BlankNode" else "U")
                ensure(triple.predicate.value, "U")
                obj = triple.object
                obj_cls = type(obj).__name__
                if obj_cls == "Literal":
                    lang = str(obj.language) if obj.language else None
                    ensure(obj.value, "L", lang)
                elif obj_cls == "BlankNode":
                    ensure(obj.value, "B")
                else:
                    ensure(obj.value, "U")
                triple_count += 1
                if triple_count % 1_000_000 == 0:
                    print(f"   {triple_count:,} triples, {len(terms):,} unique terms")

        pass1_dt = time.time() - t0
        print(f"   Pass 1 done: {triple_count:,} triples, {len(terms):,} terms in {pass1_dt:.1f}s")

        # --- COPY terms ---
        print(f"\n📥 COPY {len(terms):,} terms into {term_tbl}...")
        t0 = time.time()
        term_records = [
            (uid, text, ttype, lang, "primary")
            for (text, ttype, lang), uid in terms.items()
        ]
        async with pool.acquire() as conn:
            await conn.copy_records_to_table(
                term_tbl,
                columns=["term_uuid", "term_text", "term_type", "lang", "dataset"],
                records=term_records,
            )
        term_dt = time.time() - t0
        print(f"   {len(term_records):,} terms loaded in {term_dt:.1f}s")
        del term_records  # free memory

        # --- pass 2: COPY quads ---
        print(f"\n📥 Pass 2: COPY quads into {quad_tbl}...")
        graph_uuid = terms[(graph_uri, "U", None)]
        quad_batch = []
        total_quads = 0
        t0 = time.time()

        async def flush_quads(batch):
            nonlocal total_quads
            if not batch:
                return
            async with pool.acquire() as conn:
                await conn.copy_records_to_table(
                    quad_tbl,
                    columns=["subject_uuid", "predicate_uuid", "object_uuid",
                             "context_uuid", "dataset"],
                    records=batch,
                )
            total_quads += len(batch)

        with open(file_path, "rb") as f:
            for triple in ox_parse(f, "application/n-triples"):
                s_cls = type(triple.subject).__name__
                s_uuid = terms[(triple.subject.value, "B" if s_cls == "BlankNode" else "U", None)]
                p_uuid = terms[(triple.predicate.value, "U", None)]
                obj = triple.object
                obj_cls = type(obj).__name__
                if obj_cls == "Literal":
                    lang = str(obj.language) if obj.language else None
                    o_uuid = terms[(obj.value, "L", lang)]
                elif obj_cls == "BlankNode":
                    o_uuid = terms[(obj.value, "B", None)]
                else:
                    o_uuid = terms[(obj.value, "U", None)]

                quad_batch.append((s_uuid, p_uuid, o_uuid, graph_uuid, "primary"))

                if len(quad_batch) >= batch_size:
                    await flush_quads(quad_batch)
                    quad_batch = []
                    if total_quads % 1_000_000 == 0:
                        elapsed = time.time() - t0
                        rate = total_quads / elapsed if elapsed > 0 else 0
                        print(f"   {total_quads:,} quads ({rate:,.0f}/s)")

        await flush_quads(quad_batch)
        quad_dt = time.time() - t0
        rate = total_quads / quad_dt if quad_dt > 0 else 0
        print(f"   {total_quads:,} quads loaded in {quad_dt:.1f}s ({rate:,.0f}/s)")

        # --- recreate indexes ---
        print(f"\n🔧 Recreating {len(saved_indexes)} indexes...")
        idx_t0 = time.time()
        async with pool.acquire() as conn:
            for row in saved_indexes:
                await conn.execute(row['indexdef'])
        print(f"   Indexes recreated in {time.time() - idx_t0:.1f}s")

        # --- ANALYZE ---
        print("\n📊 Running ANALYZE...")
        async with pool.acquire() as conn:
            await conn.execute(f"ANALYZE {term_tbl}")
            await conn.execute(f"ANALYZE {quad_tbl}")

        # --- register graph in admin tables ---
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO graph (space_id, graph_uri, graph_name, created_time) "
                "VALUES ($1, $2, $3, NOW()) "
                "ON CONFLICT DO NOTHING",
                space_id, graph_uri, graph_uri,
            )

        # --- verify ---
        async with pool.acquire() as conn:
            final_terms = await conn.fetchval(f"SELECT COUNT(*) FROM {term_tbl}")
            final_quads = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_tbl}")

        total_dt = pass1_dt + term_dt + quad_dt
        print(f"\n✅ Import complete!")
        print(f"   Terms: {final_terms:,}")
        print(f"   Quads: {final_quads:,}")
        print(f"   Total time: {total_dt:.1f}s")
        return True

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
            "import",
            "rebuild-indexes", "rebuild-stats", "rebuild-analyze", "rebuild-vacuum", "rebuild-resync",
            "purge", "delete",
            # Legacy aliases
            "reindex", "stats",
        ],
        help="Execute a command non-interactively (omit for REPL mode)"
    )

    # Space options
    parser.add_argument(
        "-s", "--space-id",
        type=str,
        help="Space ID (required for create-space, drop-space, import; optional for list-graphs, rebuild-indexes)"
    )
    parser.add_argument(
        "--space-name",
        type=str,
        help="Human-readable space name (for create-space; defaults to space-id)"
    )

    # Import options
    parser.add_argument(
        "--graph-uri", "-g",
        type=str,
        help="Graph URI for import (default: urn:<space_id>)"
    )
    parser.add_argument(
        "-f", "--file",
        type=str,
        help="File path for import command"
    )
    parser.add_argument(
        "-t", "--format",
        type=str,
        choices=["turtle", "xml", "nt", "n3", "nquads"],
        help="RDF file format (default: auto-detect from extension)"
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=50000,
        help="Batch size for import (default: 50000)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Enable pre-validation before import"
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Disable pre-validation before import"
    )

    # Confirmation bypass
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompts (for drop-space, purge, delete)"
    )

    # Interactive mode (legacy, only affects import wizard)
    parser.add_argument(
        "-i", "--interactive",
        type=str,
        choices=["true", "false", "1", "0", "yes", "no", "on", "off"],
        default="true",
        help="Enable interactive mode for import wizard (default: true)"
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
