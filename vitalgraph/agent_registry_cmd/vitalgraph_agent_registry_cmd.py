#!/usr/bin/env python3
"""
VitalGraph Agent Registry CLI.

Interactive REPL and non-interactive CLI for managing AI agents,
their endpoints, functions, and agent types.

Usage:
    vitalgraphagentregistry                        # Start REPL
    vitalgraphagentregistry -c list-agents          # Non-interactive
    vitalgraphagentregistry -c migrate --dry-run    # Schema migration
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import CompleteStyle

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logging.getLogger('asyncpg').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

LINE = '─' * 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _print_table(rows: List[Dict[str, Any]], columns: Optional[List[str]] = None, fmt: str = "table"):
    """Print rows as table, json, or csv."""
    if not rows:
        print("(no results)")
        return

    if fmt == "json":
        print(json.dumps(rows, indent=2, default=str))
        return

    if fmt == "csv":
        import csv as csv_mod
        import io
        cols = columns or list(rows[0].keys())
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=cols, extrasaction='ignore')
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, '') for k in cols})
        print(buf.getvalue(), end='')
        return

    # table
    cols = columns or list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(r.get(c, ''))))
    # cap column widths at 60
    for c in cols:
        widths[c] = min(widths[c], 60)

    header = '  '.join(c.ljust(widths[c]) for c in cols)
    sep = '  '.join('─' * widths[c] for c in cols)
    print(header)
    print(sep)
    for r in rows:
        vals = []
        for c in cols:
            v = str(r.get(c, ''))
            if len(v) > widths[c]:
                v = v[:widths[c] - 2] + '..'
            vals.append(v.ljust(widths[c]))
        print('  '.join(vals))
    print(f"\n{len(rows)} row(s)")


# ---------------------------------------------------------------------------
# Agent Registry CLI
# ---------------------------------------------------------------------------

class AgentRegistryCLI:
    """Agent Registry REPL and CLI."""

    def __init__(self):
        self.pool = None
        self.registry = None
        self.connected = False
        self.output_format = "table"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def _connect(self):
        """Connect to PostgreSQL and initialize registry impl."""
        import asyncpg
        from vitalgraph.config.config_loader import VitalGraphConfig
        from vitalgraph.agent_registry.agent_registry_impl import AgentRegistryImpl

        config = VitalGraphConfig()
        db_config = config.get_database_config()

        self.pool = await asyncpg.create_pool(
            host=db_config.get('host', 'localhost'),
            port=int(db_config.get('port', 5432)),
            database=db_config.get('database', 'vitalgraph'),
            user=db_config.get('username', 'postgres'),
            password=db_config.get('password', ''),
            min_size=1,
            max_size=5,
        )
        self.registry = AgentRegistryImpl(self.pool)
        self.connected = True

    async def _disconnect(self):
        if self.pool:
            await self.pool.close()
        self.connected = False

    def connect(self):
        _run_async(self._connect())
        print("✅ Connected to database")

    def disconnect(self):
        _run_async(self._disconnect())

    def _require_connected(self) -> bool:
        if not self.connected:
            print("❌ Not connected. Connecting...")
            try:
                self.connect()
            except Exception as e:
                print(f"❌ Connection failed: {e}")
                return False
        return True

    # ------------------------------------------------------------------
    # Agent Type commands
    # ------------------------------------------------------------------

    def cmd_list_types(self, args: list[str]) -> bool:
        """List agent types."""
        if not self._require_connected():
            return True
        types = _run_async(self.registry.list_agent_types())
        rows = []
        for t in types:
            rows.append({
                'type_id': t['type_id'],
                'type_key': t['type_key'],
                'type_label': t['type_label'],
                'description': (t.get('type_description') or '')[:50],
            })
        _print_table(rows, ['type_id', 'type_key', 'type_label', 'description'], self.output_format)
        return True

    def cmd_create_type(self, args: list[str]) -> bool:
        """Create agent type: create-type <type_key> <type_label> [description]"""
        if not self._require_connected():
            return True
        if len(args) < 2:
            print("Usage: create-type <type_key> <type_label> [description]")
            return True
        type_key, type_label = args[0], args[1]
        desc = ' '.join(args[2:]) if len(args) > 2 else None
        try:
            result = _run_async(self.registry.create_agent_type(type_key, type_label, desc))
            print(f"✅ Created agent type: {result['type_key']} (id={result['type_id']})")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Agent CRUD commands
    # ------------------------------------------------------------------

    def cmd_list_agents(self, args: list[str]) -> bool:
        """List agents with optional filters."""
        if not self._require_connected():
            return True
        # Parse optional flags
        type_key = self._extract_flag(args, '--type')
        status = self._extract_flag(args, '--status') or 'active'
        query = self._extract_flag(args, '--search')
        page_size = int(self._extract_flag(args, '--limit') or '20')
        page = int(self._extract_flag(args, '--page') or '1')

        agents, total = _run_async(self.registry.search_agents(
            query=query, type_key=type_key, status=status,
            page=page, page_size=page_size,
        ))
        rows = []
        for a in agents:
            rows.append({
                'agent_id': a['agent_id'],
                'agent_name': a['agent_name'],
                'type': a.get('agent_type_key', ''),
                'status': a['status'],
                'version': a.get('version', '') or '',
            })
        _print_table(rows, ['agent_id', 'agent_name', 'type', 'status', 'version'], self.output_format)
        print(f"Total: {total}")
        return True

    def cmd_get_agent(self, args: list[str]) -> bool:
        """Get agent details: get-agent <agent_id|agent_uri>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: get-agent <agent_id_or_uri>")
            return True
        identifier = args[0]
        # Try by ID first, then by URI
        agent = _run_async(self.registry.get_agent(identifier))
        if not agent:
            agent = _run_async(self.registry.get_agent_by_uri(identifier))
        if not agent:
            print(f"❌ Agent not found: {identifier}")
            return True
        print(json.dumps(agent, indent=2, default=str))
        return True

    def cmd_create_agent(self, args: list[str]) -> bool:
        """Create agent: create-agent --type <key> --name <name> --uri <uri> [options]"""
        if not self._require_connected():
            return True
        type_key = self._extract_flag(args, '--type')
        name = self._extract_flag(args, '--name')
        uri = self._extract_flag(args, '--uri')
        if not type_key or not name or not uri:
            print("Usage: create-agent --type <type_key> --name <name> --uri <uri> [--version V] [--description D] [--protocol P]")
            return True
        version = self._extract_flag(args, '--version')
        description = self._extract_flag(args, '--description')
        protocol = self._extract_flag(args, '--protocol')
        try:
            agent = _run_async(self.registry.create_agent(
                agent_type_key=type_key,
                agent_name=name,
                agent_uri=uri,
                version=version,
                description=description,
                protocol_format_uri=protocol,
            ))
            print(f"✅ Created agent: {agent['agent_id']} ({name})")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_update_agent(self, args: list[str]) -> bool:
        """Update agent: update-agent <agent_id> [--name N] [--status S] [--version V] [--description D]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: update-agent <agent_id> [--name N] [--status S] [--version V] [--description D]")
            return True
        agent_id = args.pop(0)
        name = self._extract_flag(args, '--name')
        status = self._extract_flag(args, '--status')
        version = self._extract_flag(args, '--version')
        description = self._extract_flag(args, '--description')
        try:
            result = _run_async(self.registry.update_agent(
                agent_id=agent_id,
                agent_name=name,
                status=status,
                version=version,
                description=description,
            ))
            if result:
                print(f"✅ Updated agent: {agent_id}")
            else:
                print(f"❌ Agent not found: {agent_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_delete_agent(self, args: list[str], yes: bool = False) -> bool:
        """Delete (soft) agent: delete-agent <agent_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: delete-agent <agent_id>")
            return True
        agent_id = args[0]
        if not yes:
            confirm = input(f"⚠️  Soft-delete agent '{agent_id}'? (yes/no): ").strip().lower()
            if confirm not in ('yes', 'y'):
                print("Cancelled.")
                return True
        success = _run_async(self.registry.delete_agent(agent_id))
        if success:
            print(f"✅ Agent soft-deleted: {agent_id}")
        else:
            print(f"❌ Agent not found or already deleted: {agent_id}")
        return True

    def cmd_set_status(self, args: list[str]) -> bool:
        """Set agent status: set-status <agent_id> <active|inactive|deprecated>"""
        if not self._require_connected():
            return True
        if len(args) < 2:
            print("Usage: set-status <agent_id> <active|inactive|deprecated>")
            return True
        agent_id, status = args[0], args[1]
        try:
            result = _run_async(self.registry.update_agent(agent_id=agent_id, status=status))
            if result:
                print(f"✅ Agent {agent_id} → {status}")
            else:
                print(f"❌ Agent not found: {agent_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Endpoint commands
    # ------------------------------------------------------------------

    def cmd_list_endpoints(self, args: list[str]) -> bool:
        """List endpoints for agent: list-endpoints <agent_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: list-endpoints <agent_id>")
            return True
        agent_id = args[0]
        endpoints = _run_async(self.registry.list_endpoints(agent_id))
        rows = []
        for ep in endpoints:
            rows.append({
                'endpoint_id': ep['endpoint_id'],
                'endpoint_uri': ep['endpoint_uri'],
                'endpoint_url': ep['endpoint_url'],
                'protocol': ep['protocol'],
                'status': ep['status'],
            })
        _print_table(rows, ['endpoint_id', 'endpoint_uri', 'endpoint_url', 'protocol', 'status'], self.output_format)
        return True

    def cmd_create_endpoint(self, args: list[str]) -> bool:
        """Create endpoint: create-endpoint <agent_id> --uri <uri> --url <url> [--protocol P]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: create-endpoint <agent_id> --uri <uri> --url <url> [--protocol P]")
            return True
        agent_id = args.pop(0)
        uri = self._extract_flag(args, '--uri')
        url = self._extract_flag(args, '--url')
        protocol = self._extract_flag(args, '--protocol') or 'websocket'
        if not uri or not url:
            print("❌ --uri and --url are required")
            return True
        try:
            ep = _run_async(self.registry.create_endpoint(
                agent_id=agent_id, endpoint_uri=uri,
                endpoint_url=url, protocol=protocol,
            ))
            print(f"✅ Created endpoint {ep['endpoint_id']} for agent {agent_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_update_endpoint(self, args: list[str]) -> bool:
        """Update endpoint: update-endpoint <endpoint_id> [--url U] [--protocol P] [--status S]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: update-endpoint <endpoint_id> [--url U] [--protocol P] [--status S]")
            return True
        endpoint_id = int(args.pop(0))
        url = self._extract_flag(args, '--url')
        protocol = self._extract_flag(args, '--protocol')
        status = self._extract_flag(args, '--status')
        try:
            result = _run_async(self.registry.update_endpoint(
                endpoint_id=endpoint_id, endpoint_url=url,
                protocol=protocol, status=status,
            ))
            if result:
                print(f"✅ Updated endpoint {endpoint_id}")
            else:
                print(f"❌ Endpoint not found: {endpoint_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_delete_endpoint(self, args: list[str]) -> bool:
        """Delete endpoint: delete-endpoint <endpoint_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: delete-endpoint <endpoint_id>")
            return True
        endpoint_id = int(args[0])
        success = _run_async(self.registry.delete_endpoint(endpoint_id))
        if success:
            print(f"✅ Endpoint {endpoint_id} soft-deleted")
        else:
            print(f"❌ Endpoint not found or already deleted: {endpoint_id}")
        return True

    # ------------------------------------------------------------------
    # Function commands
    # ------------------------------------------------------------------

    def cmd_list_functions(self, args: list[str]) -> bool:
        """List functions for agent: list-functions <agent_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: list-functions <agent_id>")
            return True
        agent_id = args[0]
        functions = _run_async(self.registry.list_functions(agent_id))
        rows = []
        for fn in functions:
            rows.append({
                'function_id': fn['function_id'],
                'function_uri': fn['function_uri'],
                'function_name': fn['function_name'],
                'status': fn['status'],
            })
        _print_table(rows, ['function_id', 'function_uri', 'function_name', 'status'], self.output_format)
        return True

    def cmd_create_function(self, args: list[str]) -> bool:
        """Create function: create-function <agent_id> --uri <uri> --name <name> [--description D]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: create-function <agent_id> --uri <uri> --name <name> [--description D]")
            return True
        agent_id = args.pop(0)
        uri = self._extract_flag(args, '--uri')
        name = self._extract_flag(args, '--name')
        description = self._extract_flag(args, '--description')
        if not uri or not name:
            print("❌ --uri and --name are required")
            return True
        try:
            fn = _run_async(self.registry.create_function(
                agent_id=agent_id, function_uri=uri,
                function_name=name, description=description,
            ))
            print(f"✅ Created function {fn['function_id']} for agent {agent_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_update_function(self, args: list[str]) -> bool:
        """Update function: update-function <function_id> [--name N] [--description D] [--status S]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: update-function <function_id> [--name N] [--description D] [--status S]")
            return True
        function_id = int(args.pop(0))
        name = self._extract_flag(args, '--name')
        description = self._extract_flag(args, '--description')
        status = self._extract_flag(args, '--status')
        try:
            result = _run_async(self.registry.update_function(
                function_id=function_id, function_name=name,
                description=description, status=status,
            ))
            if result:
                print(f"✅ Updated function {function_id}")
            else:
                print(f"❌ Function not found: {function_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_delete_function(self, args: list[str]) -> bool:
        """Delete function: delete-function <function_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: delete-function <function_id>")
            return True
        function_id = int(args[0])
        success = _run_async(self.registry.delete_function(function_id))
        if success:
            print(f"✅ Function {function_id} soft-deleted")
        else:
            print(f"❌ Function not found or already deleted: {function_id}")
        return True

    def cmd_discover(self, args: list[str]) -> bool:
        """Discover agents by function URI: discover <function_uri>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: discover <function_uri>")
            return True
        function_uri = args[0]
        results = _run_async(self.registry.discover_by_function(function_uri))
        rows = []
        for r in results:
            rows.append({
                'agent_id': r['agent_id'],
                'agent_name': r['agent_name'],
                'agent_uri': r.get('agent_uri', ''),
                'function_name': r['function_name'],
            })
        _print_table(rows, ['agent_id', 'agent_name', 'agent_uri', 'function_name'], self.output_format)
        return True

    # ------------------------------------------------------------------
    # Change log
    # ------------------------------------------------------------------

    def cmd_changelog(self, args: list[str]) -> bool:
        """Show change log: changelog <agent_id> [--limit N]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: changelog <agent_id> [--limit N]")
            return True
        agent_id = args.pop(0) if args else None
        limit = int(self._extract_flag(args, '--limit') or '50')
        entries = _run_async(self.registry.get_change_log(agent_id, limit=limit))
        rows = []
        for e in entries:
            rows.append({
                'log_id': e['log_id'],
                'change_type': e['change_type'],
                'changed_by': e.get('changed_by', '') or '',
                'created_time': str(e.get('created_time', ''))[:19],
                'comment': (e.get('comment') or '')[:40],
            })
        _print_table(rows, ['log_id', 'change_type', 'changed_by', 'created_time', 'comment'], self.output_format)
        return True

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def cmd_stats(self, args: list[str]) -> bool:
        """Show registry statistics."""
        if not self._require_connected():
            return True

        async def _stats():
            async with self.pool.acquire() as conn:
                agent_count = await conn.fetchval("SELECT COUNT(*) FROM agent WHERE status != 'deleted'")
                type_count = await conn.fetchval("SELECT COUNT(*) FROM agent_type")
                ep_count = await conn.fetchval("SELECT COUNT(*) FROM agent_endpoint WHERE status != 'deleted'")
                fn_count = await conn.fetchval("SELECT COUNT(*) FROM agent_function WHERE status != 'deleted'")
                log_count = await conn.fetchval("SELECT COUNT(*) FROM agent_change_log")

                print(f"\n📊 Agent Registry Statistics")
                print(LINE)
                print(f"  Agent types:  {type_count:,}")
                print(f"  Agents:       {agent_count:,}")
                print(f"  Endpoints:    {ep_count:,}")
                print(f"  Functions:    {fn_count:,}")
                print(f"  Change log:   {log_count:,}")

                # Status breakdown
                rows = await conn.fetch(
                    "SELECT status, COUNT(*) AS cnt FROM agent GROUP BY status ORDER BY cnt DESC"
                )
                if rows:
                    print(f"\n  Agent Status Breakdown:")
                    for r in rows:
                        print(f"    {r['status']:15} {r['cnt']:,}")

        _run_async(_stats())
        return True

    # ------------------------------------------------------------------
    # Schema migration
    # ------------------------------------------------------------------

    def cmd_migrate(self, args: list[str], dry_run: bool = False) -> bool:
        """Run schema migration (create tables, indexes, seeds)."""
        from agent_registry.migrate_agents import run_create, check_status

        async def _do_migrate():
            await run_create(self.pool, dry_run=dry_run)
            if not dry_run:
                print()
                await check_status(self.pool)

        if not self._require_connected():
            return True
        _run_async(_do_migrate())
        return True

    def cmd_schema_status(self, args: list[str]) -> bool:
        """Show schema status."""
        from agent_registry.migrate_agents import check_status

        if not self._require_connected():
            return True
        _run_async(check_status(self.pool))
        return True

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _extract_flag(self, args: list[str], flag: str) -> Optional[str]:
        """Extract --flag value from args list. Modifies args in-place."""
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                val = args.pop(i + 1)
                args.pop(i)
                return val
        return None

    # ------------------------------------------------------------------
    # REPL dispatch
    # ------------------------------------------------------------------

    def execute_command(self, command_line: str) -> bool:
        """Execute a REPL command. Returns False if should exit."""
        line = command_line.strip()
        if line.endswith(';'):
            line = line[:-1].strip()
        if not line:
            return True

        parts = line.split()
        command = parts[0].lower()
        args = parts[1:]

        dispatch = {
            # Agent types
            'list-types':        self.cmd_list_types,
            'create-type':       self.cmd_create_type,
            # Agents
            'list-agents':       self.cmd_list_agents,
            'get-agent':         self.cmd_get_agent,
            'create-agent':      self.cmd_create_agent,
            'update-agent':      self.cmd_update_agent,
            'delete-agent':      self.cmd_delete_agent,
            'set-status':        self.cmd_set_status,
            # Endpoints
            'list-endpoints':    self.cmd_list_endpoints,
            'create-endpoint':   self.cmd_create_endpoint,
            'update-endpoint':   self.cmd_update_endpoint,
            'delete-endpoint':   self.cmd_delete_endpoint,
            # Functions
            'list-functions':    self.cmd_list_functions,
            'create-function':   self.cmd_create_function,
            'update-function':   self.cmd_update_function,
            'delete-function':   self.cmd_delete_function,
            'discover':          self.cmd_discover,
            # Info
            'changelog':         self.cmd_changelog,
            'stats':             self.cmd_stats,
            # Schema
            'migrate':           lambda a: self.cmd_migrate(a, dry_run=('--dry-run' in a)),
            'schema-status':     self.cmd_schema_status,
            # Output format
            'format':            self.cmd_format,
            # Help / exit
            'help':              self.cmd_help,
            '?':                 self.cmd_help,
            'exit':              lambda a: False,
            'quit':              lambda a: False,
        }

        handler = dispatch.get(command)
        if handler:
            return handler(args)
        print(f"Unknown command: {command}")
        print("Type 'help' for available commands.")
        return True

    def cmd_format(self, args: list[str]) -> bool:
        """Set output format: format table|json|csv"""
        if args and args[0] in ('table', 'json', 'csv'):
            self.output_format = args[0]
            print(f"Output format: {self.output_format}")
        else:
            print(f"Current format: {self.output_format}. Usage: format table|json|csv")
        return True

    def cmd_help(self, args: list[str]) -> bool:
        """Show help."""
        print(f"""
Agent Registry CLI  [{'🟢 Connected' if self.connected else '🔴 Disconnected'}]

Agent Types:
  list-types                           List all agent types
  create-type <key> <label> [desc]     Create agent type

Agents:
  list-agents [--type T] [--status S] [--search Q] [--limit N]
  get-agent <id_or_uri>                Agent details (JSON)
  create-agent --type <key> --name <name> --uri <uri> [--version V] [--description D] [--protocol P]
  update-agent <id> [--name N] [--status S] [--version V] [--description D]
  delete-agent <id>                    Soft-delete agent
  set-status <id> <active|inactive|deprecated>

Endpoints:
  list-endpoints <agent_id>            List agent endpoints
  create-endpoint <agent_id> --uri <uri> --url <url> [--protocol P]
  update-endpoint <id> [--url U] [--protocol P] [--status S]
  delete-endpoint <id>                 Soft-delete endpoint

Functions:
  list-functions <agent_id>            List agent functions
  create-function <agent_id> --uri <uri> --name <name> [--description D]
  update-function <id> [--name N] [--description D] [--status S]
  delete-function <id>                 Soft-delete function
  discover <function_uri>              Find agents providing a function

Info:
  changelog <agent_id> [--limit N]     Change history
  stats                                Registry statistics

Schema:
  migrate [--dry-run]                  Create/update tables
  schema-status                        Show table status

  format table|json|csv                Output format
  help / ?                             This message
  exit / quit                          Exit
""")
        return True

    # ------------------------------------------------------------------
    # REPL loop
    # ------------------------------------------------------------------

    def run_repl(self):
        """Run interactive REPL."""
        signal.signal(signal.SIGINT, lambda s, f: (self.disconnect(), print("Goodbye!"), sys.exit(0)))

        print("VitalGraph Agent Registry CLI")
        print("Type 'help' for commands, 'exit' to quit.")
        print()

        # Auto-connect
        try:
            self.connect()
        except Exception as e:
            print(f"⚠️  Could not auto-connect: {e}")

        history_file = Path.home() / ".vitalgraph_agent_registry_history"
        history = FileHistory(str(history_file))

        try:
            while True:
                try:
                    indicator = "🟢" if self.connected else "🔴"
                    prompt_text = f"agent-registry{indicator}> "
                    command_line = prompt(
                        prompt_text,
                        history=history,
                        complete_style=CompleteStyle.READLINE_LIKE,
                    )
                    if not self.execute_command(command_line):
                        break
                except EOFError:
                    print()
                    break
                except KeyboardInterrupt:
                    continue
        finally:
            self.disconnect()
            print("Goodbye!")

    # ------------------------------------------------------------------
    # Non-interactive execution
    # ------------------------------------------------------------------

    def execute_cli_command(self, args) -> bool:
        """Execute non-interactive command from argparse args."""
        command = args.command

        try:
            self.connect()
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

        success = True
        try:
            if command == 'list-types':
                self.cmd_list_types([])

            elif command == 'create-type':
                cmd_args = [args.type_key, args.type_label]
                if args.description:
                    cmd_args.append(args.description)
                self.cmd_create_type(cmd_args)

            elif command == 'list-agents':
                cmd_args = []
                if args.type:
                    cmd_args.extend(['--type', args.type])
                if args.status:
                    cmd_args.extend(['--status', args.status])
                if args.search:
                    cmd_args.extend(['--search', args.search])
                if args.limit:
                    cmd_args.extend(['--limit', str(args.limit)])
                self.cmd_list_agents(cmd_args)

            elif command == 'get-agent':
                self.cmd_get_agent([args.agent_id])

            elif command == 'create-agent':
                cmd_args = ['--type', args.type, '--name', args.name, '--uri', args.uri]
                if args.version:
                    cmd_args.extend(['--version', args.version])
                if args.description:
                    cmd_args.extend(['--description', args.description])
                if args.protocol:
                    cmd_args.extend(['--protocol', args.protocol])
                self.cmd_create_agent(cmd_args)

            elif command == 'update-agent':
                cmd_args = [args.agent_id]
                if args.name:
                    cmd_args.extend(['--name', args.name])
                if args.status:
                    cmd_args.extend(['--status', args.status])
                if args.version:
                    cmd_args.extend(['--version', args.version])
                if args.description:
                    cmd_args.extend(['--description', args.description])
                self.cmd_update_agent(cmd_args)

            elif command == 'delete-agent':
                self.cmd_delete_agent([args.agent_id], yes=args.yes)

            elif command == 'set-status':
                self.cmd_set_status([args.agent_id, args.status])

            elif command == 'list-endpoints':
                self.cmd_list_endpoints([args.agent_id])

            elif command == 'create-endpoint':
                cmd_args = [args.agent_id, '--uri', args.uri, '--url', args.url]
                if args.protocol:
                    cmd_args.extend(['--protocol', args.protocol])
                self.cmd_create_endpoint(cmd_args)

            elif command == 'update-endpoint':
                cmd_args = [str(args.endpoint_id)]
                if args.url:
                    cmd_args.extend(['--url', args.url])
                if args.protocol:
                    cmd_args.extend(['--protocol', args.protocol])
                if args.status:
                    cmd_args.extend(['--status', args.status])
                self.cmd_update_endpoint(cmd_args)

            elif command == 'delete-endpoint':
                self.cmd_delete_endpoint([str(args.endpoint_id)])

            elif command == 'list-functions':
                self.cmd_list_functions([args.agent_id])

            elif command == 'create-function':
                cmd_args = [args.agent_id, '--uri', args.uri, '--name', args.name]
                if args.description:
                    cmd_args.extend(['--description', args.description])
                self.cmd_create_function(cmd_args)

            elif command == 'update-function':
                cmd_args = [str(args.function_id)]
                if args.name:
                    cmd_args.extend(['--name', args.name])
                if args.description:
                    cmd_args.extend(['--description', args.description])
                if args.status:
                    cmd_args.extend(['--status', args.status])
                self.cmd_update_function(cmd_args)

            elif command == 'delete-function':
                self.cmd_delete_function([str(args.function_id)])

            elif command == 'discover':
                self.cmd_discover([args.function_uri])

            elif command == 'changelog':
                cmd_args = [args.agent_id]
                if args.limit:
                    cmd_args.extend(['--limit', str(args.limit)])
                self.cmd_changelog(cmd_args)

            elif command == 'stats':
                self.cmd_stats([])

            elif command == 'migrate':
                self.cmd_migrate([], dry_run=args.dry_run)

            elif command == 'schema-status':
                self.cmd_schema_status([])

            else:
                print(f"❌ Unknown command: {command}")
                success = False

        except Exception as e:
            print(f"❌ Error: {e}")
            success = False
        finally:
            self.disconnect()

        return success


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VitalGraph Agent Registry CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraphagentregistry                                  # Start REPL
  vitalgraphagentregistry -c list-types                    # List agent types
  vitalgraphagentregistry -c list-agents --status active   # List active agents
  vitalgraphagentregistry -c create-agent --type urn:vital-ai:agent-type:chat --name "My Agent" --uri urn:my:agent
  vitalgraphagentregistry -c migrate --dry-run             # Preview schema migration
        """,
    )

    parser.add_argument(
        "-c", "--command",
        type=str,
        choices=[
            # Agent types
            "list-types", "create-type",
            # Agents
            "list-agents", "get-agent", "create-agent", "update-agent",
            "delete-agent", "set-status",
            # Endpoints
            "list-endpoints", "create-endpoint", "update-endpoint", "delete-endpoint",
            # Functions
            "list-functions", "create-function", "update-function", "delete-function",
            "discover",
            # Info
            "changelog", "stats",
            # Schema
            "migrate", "schema-status",
        ],
        help="Execute command non-interactively (omit for REPL mode)",
    )

    # Agent type args
    parser.add_argument("--type-key", type=str, help="Agent type key for create-type")
    parser.add_argument("--type-label", type=str, help="Agent type label for create-type")

    # Agent identification
    parser.add_argument("--agent-id", type=str, help="Agent ID")
    parser.add_argument("--type", type=str, help="Agent type key filter")
    parser.add_argument("--name", type=str, help="Agent/function name")
    parser.add_argument("--uri", type=str, help="Agent/endpoint/function URI")
    parser.add_argument("--url", type=str, help="Endpoint URL")
    parser.add_argument("--version", type=str, help="Agent version")
    parser.add_argument("--description", type=str, help="Description")
    parser.add_argument("--protocol", type=str, help="Endpoint protocol")
    parser.add_argument("--status", type=str, help="Status filter or new status")
    parser.add_argument("--search", type=str, help="Search query")
    parser.add_argument("--limit", type=int, help="Result limit")

    # Endpoint/function IDs
    parser.add_argument("--endpoint-id", type=int, help="Endpoint ID")
    parser.add_argument("--function-id", type=int, help="Function ID")
    parser.add_argument("--function-uri", type=str, help="Function URI for discover")

    # Flags
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--dry-run", action="store_true", help="Dry run for migrate")

    parser.add_argument("--version-info", action="version", version="VitalGraph Agent Registry CLI 1.0.0")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    cli = AgentRegistryCLI()

    try:
        if args.command:
            success = cli.execute_cli_command(args)
            sys.exit(0 if success else 1)
        else:
            cli.run_repl()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
