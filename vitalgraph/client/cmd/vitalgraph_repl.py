#!/usr/bin/env python3
"""
VitalGraph Client REPL

Interactive command-line interface for VitalGraph using the client library.
Supports both REPL (interactive) and non-interactive (-c <command>) modes.

Usage:
    vitalgraph                                 # Start REPL
    vitalgraph -c "list spaces"                # Non-interactive
    vitalgraph --api-key vg_... -c "list spaces"
"""

import argparse
import asyncio
import json
import shlex
import signal
import sys
from typing import Any, Dict, List, Optional
from pathlib import Path

from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.completion import WordCompleter

from ..vitalgraph_client import VitalGraphClient, VitalGraphClientError
from ...model.sparql_model import SPARQLQueryRequest


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
    """Print a list of dicts as table, json, or csv."""
    if not rows:
        print("(no results)")
        return

    if fmt == "json":
        print(json.dumps(rows, indent=2, default=str))
        return

    if fmt == "csv":
        import csv
        import io
        cols = columns or list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction='ignore')
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, '') for k in cols})
        print(buf.getvalue(), end='')
        return

    # table format
    cols = columns or list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(r.get(c, ''))))

    header = '  '.join(c.ljust(widths[c]) for c in cols)
    sep = '  '.join('─' * widths[c] for c in cols)
    print(header)
    print(sep)
    for r in rows:
        print('  '.join(str(r.get(c, '')).ljust(widths[c]) for c in cols))
    print(f"\n{len(rows)} row(s)")


# ---------------------------------------------------------------------------
# REPL class
# ---------------------------------------------------------------------------

class VitalGraphREPL:
    """VitalGraph REPL implementation with client management."""

    def __init__(self, api_key: Optional[str] = None):
        self.client: Optional[VitalGraphClient] = None
        self.connected = False
        self._api_key = api_key
        # Space context
        self.current_space: Optional[str] = None
        self.current_graph: Optional[str] = None
        self.output_format: str = "table"  # table | json | csv

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(sig, frame):
            self._safe_close()
            print("Goodbye!")
            sys.exit(0)
        signal.signal(signal.SIGINT, signal_handler)

    def _safe_close(self):
        if self.client and self.connected:
            try:
                _run_async(self.client.close())
            except Exception:
                pass
            self.connected = False

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_command(self, command_line: str) -> tuple[str, list[str]]:
        """Parse a command line into command and arguments."""
        line = command_line.strip()
        if line.endswith(';'):
            line = line[:-1].strip()
        if not line:
            return "", []
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        if not parts:
            return "", []
        # Support two-word commands: "list spaces", "get entity", etc.
        if len(parts) >= 2 and parts[0].lower() in (
            'list', 'get', 'space', 'server', 'user', 'process',
            'import', 'export', 'file',
        ):
            return f"{parts[0].lower()} {parts[1].lower()}", parts[2:]
        if len(parts) >= 2 and parts[0].lower() == 'sparql' and parts[1].lower() == 'multiline':
            return 'sparql multiline', parts[2:]
        return parts[0].lower(), parts[1:]

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def execute_command(self, command_line: str) -> bool:
        """Execute a REPL command. Returns False if should exit."""
        if not command_line.strip():
            return True
        command, args = self.parse_command(command_line)

        dispatch = {
            # Connection & auth
            'open':           self.cmd_open,
            'close':          self.cmd_close,
            'status':         self.cmd_status,
            'whoami':         self.cmd_whoami,
            'use':            self.cmd_use,
            'unuse':          self.cmd_unuse,
            'format':         self.cmd_format,
            # Space & graph exploration
            'list spaces':    self.cmd_list_spaces,
            'list graphs':    self.cmd_list_graphs,
            'space info':     self.cmd_space_info,
            # KG data exploration
            'list entities':  self.cmd_list_entities,
            'get entity':     self.cmd_get_entity,
            'list frames':    self.cmd_list_frames,
            'list types':     self.cmd_list_types,
            'list relations': self.cmd_list_relations,
            # Query
            'sparql':         self.cmd_sparql,
            'sparql multiline': self.cmd_sparql_multiline,
            # Import/Export job monitoring
            'import list':    self.cmd_import_list,
            'import status':  self.cmd_import_status,
            'export list':    self.cmd_export_list,
            'export status':  self.cmd_export_status,
            'export download': self.cmd_export_download,
            # Files
            'file list':      self.cmd_file_list,
            'file upload':    self.cmd_file_upload,
            'file download':  self.cmd_file_download,
            # Admin
            'user list':      self.cmd_user_list,
            'process list':   self.cmd_process_list,
            'server info':    self.cmd_server_info,
            # Meta
            'help':           self.cmd_help,
            '?':              self.cmd_help,
            'exit':           self.cmd_exit,
            'quit':           self.cmd_exit,
        }

        handler = dispatch.get(command)
        if handler:
            return handler(args)
        print(f"Unknown command: {command}")
        print("Type 'help' for available commands.")
        return True

    # ------------------------------------------------------------------
    # Require-connection guard
    # ------------------------------------------------------------------

    def _require_connected(self) -> bool:
        if not self.connected or not self.client:
            print("❌ Not connected. Use 'open' first.")
            return False
        return True

    def _require_space(self) -> Optional[str]:
        if self.current_space:
            return self.current_space
        print("❌ No space selected. Use 'use <space-id>' first.")
        return None

    def _require_graph(self) -> Optional[str]:
        if self.current_graph:
            return self.current_graph
        # Default graph from space
        if self.current_space:
            return f"urn:{self.current_space}"
        print("❌ No space/graph selected. Use 'use <space-id> [graph-uri]' first.")
        return None

    def _parse_flag(self, args: list[str], flag: str, has_value: bool = True) -> Optional[str]:
        """Extract --flag value from args list. Modifies args in-place."""
        for i, a in enumerate(args):
            if a == flag:
                if has_value and i + 1 < len(args):
                    val = args.pop(i + 1)
                    args.pop(i)
                    return val
                elif not has_value:
                    args.pop(i)
                    return "true"
        return None

    # ==================================================================
    # Connection & Auth (6a)
    # ==================================================================

    def cmd_open(self, args: list[str]) -> bool:
        """Open connection to VitalGraph server."""
        if self.connected:
            print("Already connected. Use 'close' first.")
            return True
        # Check for --api-key in args
        api_key = self._parse_flag(args, '--api-key') or self._api_key
        try:
            kwargs = {}
            if api_key:
                kwargs['api_key'] = api_key
            self.client = VitalGraphClient(**kwargs)
            _run_async(self.client.open())
            self.connected = True
            url = self.client.config.get_server_url() if self.client.config else '?'
            auth = "API key" if api_key else "JWT"
            print(f"✅ Connected to {url} ({auth})")
        except Exception as e:
            print(f"❌ Connection failed: {e}")
        return True

    def cmd_close(self, args: list[str]) -> bool:
        """Close connection."""
        if not self.connected:
            print("Not connected.")
            return True
        self._safe_close()
        print("✅ Disconnected.")
        return True

    def cmd_status(self, args: list[str]) -> bool:
        """Show connection and authentication status."""
        print(f"Connected:  {'✅ Yes' if self.connected else '❌ No'}")
        if self.client and self.client.config:
            print(f"Server:     {self.client.config.get_server_url()}")
        if self.client and self.client._api_key:
            print(f"Auth:       API key ({self.client._api_key[:8]}...)")
        elif self.client and self.client.access_token:
            exp = self.client.token_expiry
            print(f"Auth:       JWT (expires {exp})")
        print(f"Space:      {self.current_space or '(none)'}")
        print(f"Graph:      {self.current_graph or '(auto)'}")
        print(f"Format:     {self.output_format}")
        return True

    def cmd_whoami(self, args: list[str]) -> bool:
        """Show current identity."""
        if not self._require_connected():
            return True
        assert self.client is not None
        if getattr(self.client, '_api_key', None):
            print(f"Authenticated via API key: {self.client._api_key[:12]}...")
        elif getattr(self.client, 'auth_data', None):
            d = self.client.auth_data
            print(f"Username: {d.get('username', '?')}")
            print(f"Role:     {d.get('role', '?')}")
            print(f"Expires:  {self.client.token_expiry}")
        else:
            print("Not authenticated.")
        return True

    def cmd_use(self, args: list[str]) -> bool:
        """Set current space (and optionally graph) context."""
        if not args:
            print("Usage: use <space-id> [graph-uri]")
            return True
        self.current_space = args[0]
        self.current_graph = args[1] if len(args) > 1 else None
        graph_display = self.current_graph or f"urn:{self.current_space} (default)"
        print(f"Using space={self.current_space}  graph={graph_display}")
        return True

    def cmd_unuse(self, args: list[str]) -> bool:
        """Clear space/graph context."""
        self.current_space = None
        self.current_graph = None
        print("Space/graph context cleared.")
        return True

    def cmd_format(self, args: list[str]) -> bool:
        """Set output format: format table|json|csv"""
        if args and args[0] in ('table', 'json', 'csv'):
            self.output_format = args[0]
            print(f"Output format: {self.output_format}")
        else:
            print(f"Current format: {self.output_format}. Usage: format table|json|csv")
        return True

    # ==================================================================
    # Space & Graph Exploration (6b)
    # ==================================================================

    def cmd_list_spaces(self, args: list[str]) -> bool:
        """List all spaces."""
        if not self._require_connected():
            return True
        resp = _run_async(self.client.spaces.list_spaces())
        if resp.error_code:
            print(f"❌ {resp.error_message}")
            return True
        rows = []
        for s in resp.spaces:
            rows.append({
                'space_id': s.space,
                'space_name': getattr(s, 'space_name', '') or '',
            })
        _print_table(rows, ['space_id', 'space_name'], self.output_format)
        return True

    def cmd_list_graphs(self, args: list[str]) -> bool:
        """List graphs in a space."""
        if not self._require_connected():
            return True
        space_id = self._parse_flag(args, '--space') or (args[0] if args else None) or self.current_space
        if not space_id:
            print("Usage: list graphs [--space S]  (or 'use <space>' first)")
            return True
        resp = _run_async(self.client.graphs.list_graphs(space_id))
        if resp.error_code:
            print(f"❌ {resp.error_message}")
            return True
        rows = []
        for g in resp.graphs:
            rows.append({
                'graph_uri': g.graph_uri,
                'quad_count': getattr(g, 'quad_count', ''),
            })
        _print_table(rows, ['graph_uri', 'quad_count'], self.output_format)
        return True

    def cmd_space_info(self, args: list[str]) -> bool:
        """Show space info and statistics."""
        if not self._require_connected():
            return True
        space_id = self._parse_flag(args, '--space') or (args[0] if args else None) or self.current_space
        if not space_id:
            print("Usage: space info [--space S]")
            return True
        resp = _run_async(self.client.spaces.get_space_info(space_id))
        if resp.error_code:
            print(f"❌ {resp.error_message}")
            return True
        if resp.space:
            print(f"Space ID:   {resp.space.space}")
            print(f"Space Name: {getattr(resp.space, 'space_name', '')}")
        if resp.statistics:
            print("Statistics:")
            if isinstance(resp.statistics, dict):
                for k, v in resp.statistics.items():
                    print(f"  {k}: {v}")
            else:
                print(f"  {resp.statistics}")
        return True

    # ==================================================================
    # KG Data Exploration (6c)
    # ==================================================================

    def cmd_list_entities(self, args: list[str]) -> bool:
        """List KG entities."""
        if not self._require_connected():
            return True
        space_id = self._require_space()
        if not space_id:
            return True
        graph_id = self._require_graph()
        if not graph_id:
            return True
        type_uri = self._parse_flag(args, '--type')
        search = self._parse_flag(args, '--search')
        limit = int(self._parse_flag(args, '--limit') or '20')
        offset = int(self._parse_flag(args, '--offset') or '0')
        resp = _run_async(self.client.kgentities.list_kgentities(
            space_id=space_id,
            graph_id=graph_id,
            page_size=limit,
            offset=offset,
            entity_type_uri=type_uri,
            search=search,
        ))
        if hasattr(resp, 'error_code') and resp.error_code:
            print(f"❌ {getattr(resp, 'error_message', 'Error')}")
            return True
        objects = getattr(resp, 'objects', []) or []
        rows = []
        for obj in objects:
            uri = getattr(obj, 'URI', '') or getattr(obj, 'uri', '') or str(obj)
            name = getattr(obj, 'name', '') or ''
            rows.append({'uri': uri, 'name': name})
        _print_table(rows, ['uri', 'name'], self.output_format)
        return True

    def cmd_get_entity(self, args: list[str]) -> bool:
        """Get entity details: get entity --uri U"""
        if not self._require_connected():
            return True
        space_id = self._require_space()
        if not space_id:
            return True
        graph_id = self._require_graph()
        if not graph_id:
            return True
        uri = self._parse_flag(args, '--uri') or (args[0] if args else None)
        if not uri:
            print("Usage: get entity --uri <entity-uri>")
            return True
        resp = _run_async(self.client.kgentities.get_kgentity(space_id, graph_id, uri))
        if hasattr(resp, 'error_code') and resp.error_code:
            print(f"❌ {getattr(resp, 'error_message', 'Error')}")
            return True
        # Print as JSON for detailed view
        entity = getattr(resp, 'entity', None) or getattr(resp, 'object', None)
        if entity:
            if hasattr(entity, 'model_dump'):
                print(json.dumps(entity.model_dump(), indent=2, default=str))
            elif hasattr(entity, 'to_json'):
                print(entity.to_json())
            else:
                print(entity)
        else:
            print("Entity not found.")
        return True

    def cmd_list_frames(self, args: list[str]) -> bool:
        """List KG frames."""
        if not self._require_connected():
            return True
        space_id = self._require_space()
        if not space_id:
            return True
        graph_id = self._require_graph()
        if not graph_id:
            return True
        parent_uri = self._parse_flag(args, '--entity-uri')
        search = self._parse_flag(args, '--search')
        limit = int(self._parse_flag(args, '--limit') or '20')
        offset = int(self._parse_flag(args, '--offset') or '0')
        resp = _run_async(self.client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=limit,
            offset=offset,
            parent_uri=parent_uri,
            search=search,
        ))
        if hasattr(resp, 'error_code') and resp.error_code:
            print(f"❌ {getattr(resp, 'error_message', 'Error')}")
            return True
        objects = getattr(resp, 'objects', []) or []
        rows = []
        for obj in objects:
            uri = getattr(obj, 'URI', '') or getattr(obj, 'uri', '') or str(obj)
            name = getattr(obj, 'name', '') or ''
            rows.append({'uri': uri, 'name': name})
        _print_table(rows, ['uri', 'name'], self.output_format)
        return True

    def cmd_list_types(self, args: list[str]) -> bool:
        """List KG types."""
        if not self._require_connected():
            return True
        space_id = self._require_space()
        if not space_id:
            return True
        graph_id = self._require_graph()
        if not graph_id:
            return True
        limit = int(self._parse_flag(args, '--limit') or '50')
        resp = _run_async(self.client.kgtypes.list_kgtypes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=limit,
        ))
        if hasattr(resp, 'error_code') and resp.error_code:
            print(f"❌ {getattr(resp, 'error_message', 'Error')}")
            return True
        types = getattr(resp, 'types', []) or getattr(resp, 'objects', []) or []
        rows = []
        for t in types:
            uri = getattr(t, 'URI', '') or getattr(t, 'uri', '') or str(t)
            name = getattr(t, 'name', '') or ''
            rows.append({'uri': uri, 'name': name})
        _print_table(rows, ['uri', 'name'], self.output_format)
        return True

    def cmd_list_relations(self, args: list[str]) -> bool:
        """List relations."""
        if not self._require_connected():
            return True
        space_id = self._require_space()
        if not space_id:
            return True
        graph_id = self._require_graph()
        if not graph_id:
            return True
        entity_uri = self._parse_flag(args, '--entity-uri')
        limit = int(self._parse_flag(args, '--limit') or '20')
        resp = _run_async(self.client.kgrelations.list_relations(
            space_id=space_id,
            graph_id=graph_id,
            page_size=limit,
            entity_source_uri=entity_uri,
        ))
        if hasattr(resp, 'error_code') and resp.error_code:
            print(f"❌ {getattr(resp, 'error_message', 'Error')}")
            return True
        objects = getattr(resp, 'objects', []) or []
        rows = []
        for obj in objects:
            uri = getattr(obj, 'URI', '') or getattr(obj, 'uri', '') or str(obj)
            rows.append({'uri': uri})
        _print_table(rows, ['uri'], self.output_format)
        return True

    # ==================================================================
    # Query (6d)
    # ==================================================================

    def cmd_sparql(self, args: list[str]) -> bool:
        """Execute SPARQL query: sparql <query>"""
        if not self._require_connected():
            return True
        space_id = self._require_space()
        if not space_id:
            return True
        if not args:
            print("Usage: sparql <SPARQL query>")
            return True
        query = ' '.join(args)
        req = SPARQLQueryRequest(
            query=query,
            default_graph_uri=None,
            named_graph_uri=None,
            format="application/sparql-results+json",
        )
        try:
            resp = _run_async(self.client.sparql.execute_sparql_query(space_id, req))
            if hasattr(resp, 'error') and resp.error:
                print(f"❌ {resp.error}")
                return True
            results = getattr(resp, 'results', None)
            if results:
                bindings = results.get('bindings', []) if isinstance(results, dict) else []
                if bindings:
                    rows = []
                    for b in bindings:
                        row = {}
                        for k, v in b.items():
                            row[k] = v.get('value', '') if isinstance(v, dict) else str(v)
                        rows.append(row)
                    _print_table(rows, fmt=self.output_format)
                else:
                    print(json.dumps(results, indent=2, default=str))
            else:
                print("No results.")
        except Exception as e:
            print(f"❌ SPARQL error: {e}")
        return True

    def cmd_sparql_multiline(self, args: list[str]) -> bool:
        """Enter multi-line SPARQL mode. End with ;; on its own line."""
        if not self._require_connected():
            return True
        space_id = self._require_space()
        if not space_id:
            return True
        print("Enter SPARQL query (end with ';;' on its own line):")
        lines: list[str] = []
        try:
            while True:
                line = prompt("  ... ")
                if line.strip() == ';;':
                    break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\n(cancelled)")
            return True
        if not lines:
            print("(empty query)")
            return True
        query = '\n'.join(lines)
        req = SPARQLQueryRequest(
            query=query,
            default_graph_uri=None,
            named_graph_uri=None,
            format="application/sparql-results+json",
        )
        try:
            resp = _run_async(self.client.sparql.execute_sparql_query(space_id, req))
            if hasattr(resp, 'error') and resp.error:
                print(f"❌ {resp.error}")
                return True
            results = getattr(resp, 'results', None)
            if results:
                bindings = results.get('bindings', []) if isinstance(results, dict) else []
                if bindings:
                    rows = []
                    for b in bindings:
                        row = {}
                        for k, v in b.items():
                            row[k] = v.get('value', '') if isinstance(v, dict) else str(v)
                        rows.append(row)
                    _print_table(rows, fmt=self.output_format)
                else:
                    print(json.dumps(results, indent=2, default=str))
            else:
                print("No results.")
        except Exception as e:
            print(f"❌ SPARQL error: {e}")
        return True

    # ==================================================================
    # Import/Export Job Monitoring (6e)
    # ==================================================================

    def cmd_import_list(self, args: list[str]) -> bool:
        """List import jobs: import list [--space S] [--status S] [--limit L]"""
        if not self._require_connected():
            return True
        space_id = self._parse_flag(args, '--space') or self.current_space
        status = self._parse_flag(args, '--status')
        limit = int(self._parse_flag(args, '--limit') or '20')
        try:
            resp = _run_async(self.client.imports.list_import_jobs(
                space_id=space_id,
                status=status,
                page_size=limit,
            ))
            jobs = getattr(resp, 'jobs', []) or []
            if not jobs:
                print("No import jobs found.")
                return True
            rows = []
            for j in jobs:
                rows.append({
                    'job_id': getattr(j, 'job_id', ''),
                    'space_id': getattr(j, 'space_id', ''),
                    'status': getattr(j, 'status', ''),
                    'file_format': getattr(j, 'file_format', ''),
                    'created_at': str(getattr(j, 'created_at', ''))[:19],
                })
            _print_table(rows, ['job_id', 'space_id', 'status', 'file_format', 'created_at'], self.output_format)
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_import_status(self, args: list[str]) -> bool:
        """Get import job status: import status <job_id>"""
        if not self._require_connected():
            return True
        job_id = self._parse_flag(args, '--job-id') or (args[0] if args else None)
        if not job_id:
            print("Usage: import status <job_id>")
            return True
        try:
            resp = _run_async(self.client.imports.get_import_status(job_id))
            print(f"Job ID:      {getattr(resp, 'job_id', job_id)}")
            print(f"Status:      {getattr(resp, 'status', '?')}")
            progress = getattr(resp, 'progress_pct', None)
            if progress is not None:
                print(f"Progress:    {progress:.1f}%")
            records = getattr(resp, 'records_done', None)
            total = getattr(resp, 'records_total', None)
            if records is not None:
                print(f"Records:     {records}" + (f" / {total}" if total else ""))
            err = getattr(resp, 'error_message', None)
            if err:
                print(f"Error:       {err}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_export_list(self, args: list[str]) -> bool:
        """List export jobs: export list [--space S] [--status S] [--limit L]"""
        if not self._require_connected():
            return True
        space_id = self._parse_flag(args, '--space') or self.current_space
        status = self._parse_flag(args, '--status')
        limit = int(self._parse_flag(args, '--limit') or '20')
        try:
            resp = _run_async(self.client.exports.list_export_jobs(
                space_id=space_id,
                status=status,
                page_size=limit,
            ))
            jobs = getattr(resp, 'jobs', []) or []
            if not jobs:
                print("No export jobs found.")
                return True
            rows = []
            for j in jobs:
                rows.append({
                    'job_id': getattr(j, 'job_id', ''),
                    'space_id': getattr(j, 'space_id', ''),
                    'status': getattr(j, 'status', ''),
                    'file_format': getattr(j, 'file_format', ''),
                    'created_at': str(getattr(j, 'created_at', ''))[:19],
                })
            _print_table(rows, ['job_id', 'space_id', 'status', 'file_format', 'created_at'], self.output_format)
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_export_status(self, args: list[str]) -> bool:
        """Get export job status: export status <job_id>"""
        if not self._require_connected():
            return True
        job_id = self._parse_flag(args, '--job-id') or (args[0] if args else None)
        if not job_id:
            print("Usage: export status <job_id>")
            return True
        try:
            resp = _run_async(self.client.exports.get_export_status(job_id))
            print(f"Job ID:      {getattr(resp, 'job_id', job_id)}")
            print(f"Status:      {getattr(resp, 'status', '?')}")
            progress = getattr(resp, 'progress_pct', None)
            if progress is not None:
                print(f"Progress:    {progress:.1f}%")
            records = getattr(resp, 'records_done', None)
            total = getattr(resp, 'records_total', None)
            if records is not None:
                print(f"Records:     {records}" + (f" / {total}" if total else ""))
            fname = getattr(resp, 'file_name', None)
            fsize = getattr(resp, 'file_size', None)
            if fname:
                print(f"File:        {fname}" + (f" ({fsize} bytes)" if fsize else ""))
            err = getattr(resp, 'error_message', None)
            if err:
                print(f"Error:       {err}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_export_download(self, args: list[str]) -> bool:
        """Download export file: export download <job_id> [--output PATH]"""
        if not self._require_connected():
            return True
        output_path = self._parse_flag(args, '--output') or self._parse_flag(args, '-o')
        job_id = args[0] if args else None
        if not job_id:
            print("Usage: export download <job_id> [--output PATH]")
            return True
        if not output_path:
            output_path = f"export_{job_id}.out"
        try:
            success = _run_async(self.client.exports.download_export_file(job_id, output_path))
            if success:
                print(f"✅ Downloaded to {output_path}")
            else:
                print("❌ Download failed")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ==================================================================
    # Files (6f)
    # ==================================================================

    def cmd_file_list(self, args: list[str]) -> bool:
        """List files: file list [--space S]"""
        if not self._require_connected():
            return True
        space_id = self._parse_flag(args, '--space') or self.current_space
        if not space_id:
            print("Usage: file list [--space S]  (or 'use <space>' first)")
            return True
        graph_id = self._parse_flag(args, '--graph') or self._require_graph()
        try:
            resp = _run_async(self.client.files.list_files(space_id, graph_id))
            if hasattr(resp, 'error_code') and resp.error_code:
                print(f"❌ {getattr(resp, 'error_message', 'Error')}")
                return True
            files = getattr(resp, 'files', []) or getattr(resp, 'objects', []) or []
            rows = []
            for f in files:
                rows.append({
                    'uri': getattr(f, 'URI', '') or getattr(f, 'uri', '') or str(f),
                    'name': getattr(f, 'name', '') or getattr(f, 'file_name', '') or '',
                })
            _print_table(rows, ['uri', 'name'], self.output_format)
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_file_upload(self, args: list[str]) -> bool:
        """Upload file: file upload <local-path> [--uri U] [--space S] [--graph G]"""
        if not self._require_connected():
            return True
        space_id = self._parse_flag(args, '--space') or self.current_space
        if not space_id:
            print("Usage: file upload <local-path> [--space S] [--graph G] [--uri U]")
            return True
        graph_id = self._parse_flag(args, '--graph') or self._require_graph()
        if not graph_id:
            return True
        file_uri = self._parse_flag(args, '--uri')
        local_path = args[0] if args else None
        if not local_path:
            print("Usage: file upload <local-path> [--uri U]")
            return True
        path_obj = Path(local_path).expanduser()
        if not path_obj.exists():
            print(f"❌ File not found: {local_path}")
            return True
        if not file_uri:
            file_uri = f"urn:file:{path_obj.name}"
        try:
            resp = _run_async(self.client.files.upload_file_content(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                source=str(path_obj),
                filename=path_obj.name,
            ))
            if hasattr(resp, 'error_code') and resp.error_code:
                print(f"❌ {getattr(resp, 'error_message', 'Upload failed')}")
            else:
                size = getattr(resp, 'size', 0)
                print(f"✅ Uploaded {path_obj.name} ({size} bytes) → {file_uri}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_file_download(self, args: list[str]) -> bool:
        """Download file: file download <file-uri> [--output PATH] [--space S] [--graph G]"""
        if not self._require_connected():
            return True
        space_id = self._parse_flag(args, '--space') or self.current_space
        if not space_id:
            print("Usage: file download <file-uri> [--output PATH] [--space S] [--graph G]")
            return True
        graph_id = self._parse_flag(args, '--graph') or self._require_graph()
        if not graph_id:
            return True
        output_path = self._parse_flag(args, '--output') or self._parse_flag(args, '-o')
        file_uri = args[0] if args else None
        if not file_uri:
            print("Usage: file download <file-uri> [--output PATH]")
            return True
        if not output_path:
            # Derive filename from URI
            name_part = file_uri.rsplit('/', 1)[-1] if '/' in file_uri else file_uri.rsplit(':', 1)[-1]
            output_path = name_part or f"download_{file_uri[:8]}"
        try:
            result = _run_async(self.client.files.download_file_content(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                destination=output_path,
            ))
            if isinstance(result, bytes):
                Path(output_path).write_bytes(result)
                print(f"✅ Downloaded {len(result)} bytes → {output_path}")
            else:
                size = getattr(result, 'size', 0)
                print(f"✅ Downloaded {size} bytes → {output_path}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ==================================================================
    # Admin (6g)
    # ==================================================================

    def cmd_user_list(self, args: list[str]) -> bool:
        """List users."""
        if not self._require_connected():
            return True
        try:
            resp = _run_async(self.client.users.list_users())
            users = getattr(resp, 'users', []) or []
            rows = []
            for u in users:
                rows.append({
                    'username': getattr(u, 'username', '') or '',
                    'role': getattr(u, 'role', '') or '',
                    'status': getattr(u, 'status', '') or '',
                })
            _print_table(rows, ['username', 'role', 'status'], self.output_format)
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_process_list(self, args: list[str]) -> bool:
        """List running processes."""
        if not self._require_connected():
            return True
        try:
            resp = _run_async(self.client.processes.list_processes())
            processes = getattr(resp, 'processes', []) or []
            if not processes:
                print("No active processes.")
                return True
            rows = []
            for p in processes:
                rows.append({
                    'process_id': getattr(p, 'process_id', '') or '',
                    'status': getattr(p, 'status', '') or '',
                    'type': getattr(p, 'process_type', '') or '',
                })
            _print_table(rows, ['process_id', 'status', 'type'], self.output_format)
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_server_info(self, args: list[str]) -> bool:
        """Show server info."""
        if not self._require_connected():
            return True
        try:
            resp = _run_async(self.client.admin.resync.__self__._make_authenticated_request(
                'GET', f"{self.client.config.get_server_url()}/api/info"
            ))
            data = resp.json()
            print(json.dumps(data, indent=2, default=str))
        except Exception as e:
            # Fallback: just show client-side info
            print(f"Server URL: {self.client.config.get_server_url()}")
            print(f"(Could not fetch server info: {e})")
        return True

    # ==================================================================
    # Help & Exit
    # ==================================================================

    def cmd_exit(self, args: list[str]) -> bool:
        """Exit the REPL."""
        self._safe_close()
        print("Goodbye!")
        return False

    def cmd_help(self, args: list[str]) -> bool:
        """Show help information."""
        status = "🟢 Connected" if self.connected else "🔴 Disconnected"
        space = self.current_space or "(none)"
        print(f"""
VitalGraph Client REPL  [{status}]  space={space}

Connection:
  open [--api-key K]     Connect to server (JWT or API key)
  close                  Disconnect
  status                 Connection + auth status
  whoami                 Show current identity

Context:
  use <space> [graph]    Set current space/graph
  unuse                  Clear context
  format table|json|csv  Set output format

Exploration:
  list spaces            List all spaces
  list graphs [--space S]  List graphs
  space info [--space S]   Space statistics

  list entities [--type T] [--search Q] [--limit L]
  get entity --uri U     Entity details
  list frames [--entity-uri E] [--limit L]
  list types [--limit L]
  list relations [--entity-uri E] [--limit L]

Query:
  sparql <SPARQL query>  Execute SPARQL SELECT
  sparql multiline       Multi-line SPARQL (end with ;;)

Import/Export Jobs:
  import list [--space S] [--status S] [--limit L]
  import status <job_id>
  export list [--space S] [--status S] [--limit L]
  export status <job_id>
  export download <job_id> [--output PATH]

Files:
  file list [--space S]            List files
  file upload <path> [--uri U]     Upload file content
  file download <uri> [--output P] Download file content

Admin:
  user list              List users
  process list           Running processes
  server info            Server version

  help / ?               This message
  exit / quit            Exit
""")
        return True

    # ==================================================================
    # REPL loop
    # ==================================================================

    def _build_completer(self) -> WordCompleter:
        """Build tab-completer from known command words."""
        words = [
            'open', 'close', 'status', 'whoami', 'use', 'unuse', 'format',
            'list', 'get', 'space', 'spaces', 'graphs', 'entities', 'frames',
            'types', 'relations', 'entity', 'info',
            'sparql', 'multiline',
            'import', 'export', 'download',
            'file', 'upload',
            'user', 'process', 'server',
            'help', 'exit', 'quit',
            '--space', '--graph', '--type', '--search', '--limit', '--offset',
            '--uri', '--output', '--api-key', '--status', '--job-id',
            '--entity-uri',
            'table', 'json', 'csv',
        ]
        return WordCompleter(words, ignore_case=True)

    def run_repl(self):
        """Run the interactive REPL."""
        self.setup_signal_handlers()
        print("VitalGraph Client REPL")
        print("Type 'help' for commands, 'exit' to quit, Ctrl+D to exit.")
        print()

        history_file = Path.home() / ".vitalgraph_history"
        history = FileHistory(str(history_file))
        completer = self._build_completer()

        try:
            while True:
                try:
                    indicator = "🟢" if self.connected else "🔴"
                    space_part = f":{self.current_space}" if self.current_space else ""
                    prompt_text = f"vitalgraph{space_part}{indicator}> "

                    command_line = prompt(
                        prompt_text,
                        history=history,
                        completer=completer,
                        complete_style=CompleteStyle.READLINE_LIKE
                    )
                    if not self.execute_command(command_line):
                        break
                except EOFError:
                    print()
                    self._safe_close()
                    print("Goodbye!")
                    break
                except KeyboardInterrupt:
                    continue
        except Exception as e:
            print(f"REPL error: {e}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Argparse & main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command line arguments for VitalGraph REPL."""
    parser = argparse.ArgumentParser(
        description="VitalGraph Client - Interactive data exploration CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraph                                    # Start REPL
  vitalgraph -c "list spaces"                   # Non-interactive
  vitalgraph --api-key vg_Ab3k... -c "list spaces"
  vitalgraph -c "use myspace" -c "list entities --limit 5"
  vitalgraph -c "use myspace" -c "sparql SELECT ?s WHERE { ?s a ?t } LIMIT 10"
        """
    )
    parser.add_argument(
        "-c", "--command",
        type=str,
        action="append",
        help="Execute command non-interactively (can repeat for multiple commands)"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="API key for authentication (vg_...)"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="VitalGraph Client 1.0.0"
    )
    return parser.parse_args()


def main():
    """Main entry point for VitalGraph client REPL."""
    args = parse_args()

    try:
        repl_instance = VitalGraphREPL(api_key=args.api_key)

        if args.command:
            # Non-interactive mode: execute commands in sequence
            for cmd in args.command:
                result = repl_instance.execute_command(cmd)
                if not result:
                    break
            repl_instance._safe_close()
        else:
            repl_instance.run_repl()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
