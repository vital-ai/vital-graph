#!/usr/bin/env python3
"""
VitalGraph Entity Registry CLI.

Interactive REPL and non-interactive CLI for managing entities,
entity types, aliases, identifiers, categories, relationships,
same-as mappings, fuzzy search, vector indexes, geo, and schema migrations.

Usage:
    vitalgraphentityregistry                              # Start REPL
    vitalgraphentityregistry -c list-entities              # Non-interactive
    vitalgraphentityregistry -c search --name "Acme"       # Search
    vitalgraphentityregistry -c migrate --dry-run          # Preview migration
"""

import argparse
import asyncio
import csv as csv_mod
import io
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
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
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
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
# Entity Registry CLI
# ---------------------------------------------------------------------------

class EntityRegistryCLI:
    """Entity Registry REPL and CLI."""

    def __init__(self):
        self.pool = None
        self.registry = None
        self.fuzzy = None
        self.connected = False
        self.output_format = "table"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def _connect(self):
        """Connect to PostgreSQL and initialize registry impl."""
        import asyncpg
        from vitalgraph.config.config_loader import VitalGraphConfig
        from vitalgraph.entity_registry.entity_registry_impl import EntityRegistryImpl

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

        # Initialize fuzzy index (optional)
        fuzzy_index = None
        try:
            import os
            if os.environ.get('ENTITY_FUZZY_BACKEND') == 'postgresql':
                from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
                fuzzy_index = EntityFuzzyIndexPG(self.pool)
                count = await fuzzy_index.initialize(self.pool)
                logger.info(f"Fuzzy index (PG) loaded {count} entities")
                self.fuzzy = fuzzy_index
            elif os.environ.get('ENTITY_FUZZY_ENABLED', '').lower() == 'true':
                from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex
                fuzzy_index = EntityFuzzyIndex.from_env()
                if fuzzy_index:
                    count = await fuzzy_index.initialize(self.pool)
                    logger.info(f"Fuzzy index loaded {count} entities")
                    self.fuzzy = fuzzy_index
        except Exception as e:
            logger.debug(f"Fuzzy index not available: {e}")

        self.registry = EntityRegistryImpl(
            self.pool,
            fuzzy_index=fuzzy_index,
        )
        self.connected = True

    async def _disconnect(self):
        if self.pool:
            await self.pool.close()
        self.connected = False

    def connect(self):
        _run_async(self._connect())
        extras = []
        if self.fuzzy:
            extras.append("fuzzy")
        extra_str = f" (+{', '.join(extras)})" if extras else ""
        print(f"✅ Connected to database{extra_str}")

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
    # Entity Type commands
    # ------------------------------------------------------------------

    def cmd_list_types(self, args: list[str]) -> bool:
        """List entity types."""
        if not self._require_connected():
            return True
        types = _run_async(self.registry.list_entity_types())
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
        """Create entity type: create-type <type_key> <type_label> [description]"""
        if not self._require_connected():
            return True
        if len(args) < 2:
            print("Usage: create-type <type_key> <type_label> [description]")
            return True
        type_key, type_label = args[0], args[1]
        desc = ' '.join(args[2:]) if len(args) > 2 else None
        try:
            result = _run_async(self.registry.create_entity_type(type_key, type_label, desc))
            print(f"✅ Created entity type: {result['type_key']} (id={result['type_id']})")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Entity CRUD commands
    # ------------------------------------------------------------------

    def cmd_list_entities(self, args: list[str]) -> bool:
        """List entities with optional filters."""
        if not self._require_connected():
            return True
        type_key = self._extract_flag(args, '--type')
        status = self._extract_flag(args, '--status') or 'active'
        query = self._extract_flag(args, '--search')
        country = self._extract_flag(args, '--country')
        region = self._extract_flag(args, '--region')
        page_size = int(self._extract_flag(args, '--limit') or '20')
        page = int(self._extract_flag(args, '--page') or '1')

        entities, total = _run_async(self.registry.search_entities(
            query=query, type_key=type_key, status=status,
            country=country, region=region,
            page=page, page_size=page_size,
        ))
        rows = []
        for e in entities:
            loc = ' '.join(filter(None, [e.get('country'), e.get('region'), e.get('locality')]))
            rows.append({
                'entity_id': e['entity_id'],
                'primary_name': e['primary_name'],
                'type': e.get('type_key', ''),
                'status': e['status'],
                'location': loc[:30],
            })
        _print_table(rows, ['entity_id', 'primary_name', 'type', 'status', 'location'], self.output_format)
        print(f"Total: {total}")
        return True

    def cmd_get_entity(self, args: list[str]) -> bool:
        """Get entity details: get-entity <entity_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: get-entity <entity_id>")
            return True
        identifier = args[0]
        entity = _run_async(self.registry.get_entity(identifier))
        if not entity:
            # Try by URI
            entity = _run_async(self.registry.get_entity_by_uri(identifier))
        if not entity:
            print(f"❌ Entity not found: {identifier}")
            return True
        print(json.dumps(entity, indent=2, default=str))
        return True

    def cmd_create_entity(self, args: list[str]) -> bool:
        """Create entity: create-entity --type <key> --name <name> [options]"""
        if not self._require_connected():
            return True
        type_key = self._extract_flag(args, '--type')
        name = self._extract_flag(args, '--name')
        if not type_key or not name:
            print("Usage: create-entity --type <type_key> --name <name> [--country C] [--region R] [--locality L] [--website W] [--description D]")
            return True
        country = self._extract_flag(args, '--country')
        region = self._extract_flag(args, '--region')
        locality = self._extract_flag(args, '--locality')
        website = self._extract_flag(args, '--website')
        description = self._extract_flag(args, '--description')
        try:
            entity = _run_async(self.registry.create_entity(
                type_key=type_key,
                primary_name=name,
                country=country,
                region=region,
                locality=locality,
                website=website,
                description=description,
            ))
            print(f"✅ Created entity: {entity['entity_id']} ({name})")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_update_entity(self, args: list[str]) -> bool:
        """Update entity: update-entity <entity_id> [--name N] [--status S] [--country C] ..."""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: update-entity <entity_id> [--name N] [--status S] [--country C] [--region R] [--locality L] [--website W] [--description D]")
            return True
        entity_id = args.pop(0)
        name = self._extract_flag(args, '--name')
        status = self._extract_flag(args, '--status')
        country = self._extract_flag(args, '--country')
        region = self._extract_flag(args, '--region')
        locality = self._extract_flag(args, '--locality')
        website = self._extract_flag(args, '--website')
        description = self._extract_flag(args, '--description')
        try:
            result = _run_async(self.registry.update_entity(
                entity_id=entity_id,
                primary_name=name,
                status=status,
                country=country,
                region=region,
                locality=locality,
                website=website,
                description=description,
            ))
            if result:
                print(f"✅ Updated entity: {entity_id}")
            else:
                print(f"❌ Entity not found: {entity_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_delete_entity(self, args: list[str], yes: bool = False) -> bool:
        """Soft-delete entity: delete-entity <entity_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: delete-entity <entity_id>")
            return True
        entity_id = args[0]
        if not yes:
            confirm = input(f"⚠️  Soft-delete entity '{entity_id}'? (yes/no): ").strip().lower()
            if confirm not in ('yes', 'y'):
                print("Cancelled.")
                return True
        success = _run_async(self.registry.delete_entity(entity_id))
        if success:
            print(f"✅ Entity soft-deleted: {entity_id}")
        else:
            print(f"❌ Entity not found or already deleted: {entity_id}")
        return True

    # ------------------------------------------------------------------
    # Alias commands
    # ------------------------------------------------------------------

    def cmd_list_aliases(self, args: list[str]) -> bool:
        """List aliases: list-aliases <entity_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: list-aliases <entity_id>")
            return True
        entity_id = args[0]
        aliases = _run_async(self.registry.list_aliases(entity_id))
        rows = []
        for a in aliases:
            rows.append({
                'alias_id': a.get('alias_id', ''),
                'alias_name': a['alias_name'],
                'alias_type': a.get('alias_type', ''),
                'is_primary': a.get('is_primary', False),
                'status': a.get('status', ''),
            })
        _print_table(rows, ['alias_id', 'alias_name', 'alias_type', 'is_primary', 'status'], self.output_format)
        return True

    def cmd_add_alias(self, args: list[str]) -> bool:
        """Add alias: add-alias <entity_id> --name <name> [--type aka]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: add-alias <entity_id> --name <name> [--type aka|trade_name|abbreviation]")
            return True
        entity_id = args.pop(0)
        name = self._extract_flag(args, '--name')
        alias_type = self._extract_flag(args, '--type') or 'aka'
        if not name:
            print("❌ --name is required")
            return True
        try:
            result = _run_async(self.registry.add_alias(entity_id, name, alias_type))
            print(f"✅ Added alias '{name}' to {entity_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_retract_alias(self, args: list[str]) -> bool:
        """Retract (remove) alias: retract-alias <alias_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: retract-alias <alias_id>")
            return True
        alias_id = int(args[0])
        try:
            success = _run_async(self.registry.remove_alias(alias_id))
            if success:
                print(f"✅ Alias {alias_id} retracted")
            else:
                print(f"❌ Alias not found: {alias_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Identifier commands
    # ------------------------------------------------------------------

    def cmd_list_identifiers(self, args: list[str]) -> bool:
        """List identifiers: list-identifiers <entity_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: list-identifiers <entity_id>")
            return True
        entity_id = args[0]
        idents = _run_async(self.registry.list_identifiers(entity_id))
        rows = []
        for i in idents:
            rows.append({
                'identifier_id': i.get('identifier_id', ''),
                'namespace': i['identifier_namespace'],
                'value': i['identifier_value'],
                'is_primary': i.get('is_primary', False),
                'status': i.get('status', ''),
            })
        _print_table(rows, ['identifier_id', 'namespace', 'value', 'is_primary', 'status'], self.output_format)
        return True

    def cmd_add_identifier(self, args: list[str]) -> bool:
        """Add identifier: add-identifier <entity_id> --namespace <ns> --value <val>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: add-identifier <entity_id> --namespace <ns> --value <val>")
            return True
        entity_id = args.pop(0)
        namespace = self._extract_flag(args, '--namespace')
        value = self._extract_flag(args, '--value')
        if not namespace or not value:
            print("❌ --namespace and --value are required")
            return True
        try:
            result = _run_async(self.registry.add_identifier(entity_id, namespace, value))
            print(f"✅ Added identifier {namespace}:{value} to {entity_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_lookup_identifier(self, args: list[str]) -> bool:
        """Lookup by identifier: lookup-identifier --namespace <ns> --value <val>"""
        if not self._require_connected():
            return True
        namespace = self._extract_flag(args, '--namespace')
        value = self._extract_flag(args, '--value')
        if not value:
            # Try positional: lookup-identifier <value>
            value = args[0] if args else None
        if not value:
            print("Usage: lookup-identifier --namespace <ns> --value <val>  OR  lookup-identifier <value>")
            return True
        if namespace:
            entities = _run_async(self.registry.lookup_by_identifier(namespace, value))
        else:
            entities = _run_async(self.registry.lookup_by_identifier_value(value))
        if not entities:
            print("(no matches)")
            return True
        rows = []
        for e in entities:
            rows.append({
                'entity_id': e['entity_id'],
                'primary_name': e.get('primary_name', ''),
                'type': e.get('type_key', ''),
                'status': e.get('status', ''),
            })
        _print_table(rows, ['entity_id', 'primary_name', 'type', 'status'], self.output_format)
        return True

    # ------------------------------------------------------------------
    # Category commands
    # ------------------------------------------------------------------

    def cmd_list_categories(self, args: list[str]) -> bool:
        """List all categories."""
        if not self._require_connected():
            return True
        categories = _run_async(self.registry.list_categories())
        rows = []
        for c in categories:
            rows.append({
                'category_id': c.get('category_id', ''),
                'category_key': c['category_key'],
                'category_label': c.get('category_label', ''),
            })
        _print_table(rows, ['category_id', 'category_key', 'category_label'], self.output_format)
        return True

    def cmd_assign_category(self, args: list[str]) -> bool:
        """Assign category: assign-category <entity_id> <category_key>"""
        if not self._require_connected():
            return True
        if len(args) < 2:
            print("Usage: assign-category <entity_id> <category_key>")
            return True
        entity_id, category_key = args[0], args[1]
        try:
            _run_async(self.registry.add_entity_category(entity_id, category_key))
            print(f"✅ Assigned category '{category_key}' to {entity_id}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_remove_category(self, args: list[str]) -> bool:
        """Remove category: remove-category <entity_id> <category_key>"""
        if not self._require_connected():
            return True
        if len(args) < 2:
            print("Usage: remove-category <entity_id> <category_key>")
            return True
        entity_id, category_key = args[0], args[1]
        try:
            result = _run_async(self.registry.remove_entity_category(entity_id, category_key))
            if result:
                print(f"✅ Removed category '{category_key}' from {entity_id}")
            else:
                print(f"❌ Category assignment not found")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Relationship commands
    # ------------------------------------------------------------------

    def cmd_list_relationship_types(self, args: list[str]) -> bool:
        """List relationship types."""
        if not self._require_connected():
            return True
        types = _run_async(self.registry.list_relationship_types())
        rows = []
        for t in types:
            rows.append({
                'type_key': t['type_key'],
                'type_label': t['type_label'],
                'inverse_key': t.get('inverse_key', '') or '',
                'description': (t.get('type_description') or '')[:40],
            })
        _print_table(rows, ['type_key', 'type_label', 'inverse_key', 'description'], self.output_format)
        return True

    def cmd_list_relationships(self, args: list[str]) -> bool:
        """List relationships: list-relationships <entity_id> [--direction both|outgoing|incoming]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: list-relationships <entity_id> [--direction both|outgoing|incoming]")
            return True
        entity_id = args.pop(0)
        direction = self._extract_flag(args, '--direction') or 'both'
        rels = _run_async(self.registry.list_relationships(entity_id, direction=direction))
        rows = []
        for r in rels:
            rows.append({
                'relationship_id': r.get('relationship_id', ''),
                'type': r.get('relationship_type_key', ''),
                'source': r.get('entity_source', ''),
                'destination': r.get('entity_destination', ''),
                'status': r.get('status', ''),
            })
        _print_table(rows, ['relationship_id', 'type', 'source', 'destination', 'status'], self.output_format)
        return True

    def cmd_create_relationship(self, args: list[str]) -> bool:
        """Create relationship: create-relationship --source <id> --dest <id> --type <type_key>"""
        if not self._require_connected():
            return True
        source = self._extract_flag(args, '--source')
        dest = self._extract_flag(args, '--dest')
        type_key = self._extract_flag(args, '--type')
        if not source or not dest or not type_key:
            print("Usage: create-relationship --source <entity_id> --dest <entity_id> --type <type_key>")
            return True
        try:
            result = _run_async(self.registry.create_relationship(
                entity_source=source,
                entity_destination=dest,
                relationship_type_key=type_key,
            ))
            if result:
                print(f"✅ Created relationship {result.get('relationship_id', '?')}: {source} → {dest} ({type_key})")
            else:
                print("❌ Failed to create relationship")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Same-as commands
    # ------------------------------------------------------------------

    def cmd_resolve_entity(self, args: list[str]) -> bool:
        """Resolve entity to canonical: resolve <entity_id>"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: resolve <entity_id>")
            return True
        entity_id = args[0]
        try:
            result = _run_async(self.registry.resolve_entity(entity_id))
            canonical_id = result.get('entity_id', entity_id)
            if canonical_id == entity_id:
                print(f"Entity {entity_id} is canonical (no same-as chain)")
            else:
                print(f"Entity {entity_id} → canonical: {canonical_id} ({result.get('primary_name', '')})")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Search commands
    # ------------------------------------------------------------------

    def cmd_search(self, args: list[str]) -> bool:
        """Search entities: search --name <name> [--type T] [--country C] [--limit N]"""
        if not self._require_connected():
            return True
        name = self._extract_flag(args, '--name')
        type_key = self._extract_flag(args, '--type')
        country = self._extract_flag(args, '--country')
        region = self._extract_flag(args, '--region')
        status = self._extract_flag(args, '--status') or 'active'
        limit = int(self._extract_flag(args, '--limit') or '50')
        # If no --name flag, use remaining args as query
        if not name and args:
            name = ' '.join(args)
        if not name:
            print("Usage: search --name <name> [--type T] [--country C] [--region R] [--limit N]")
            return True

        entities, total = _run_async(self.registry.search_entities(
            query=name, type_key=type_key, country=country, region=region,
            status=status, page_size=limit,
        ))
        rows = []
        for e in entities:
            loc = ' '.join(filter(None, [e.get('country'), e.get('region'), e.get('locality')]))
            rows.append({
                'entity_id': e['entity_id'],
                'primary_name': e['primary_name'],
                'type': e.get('type_key', ''),
                'location': loc[:30],
            })
        _print_table(rows, ['entity_id', 'primary_name', 'type', 'location'], self.output_format)
        print(f"Total: {total}")
        return True

    def cmd_search_similar(self, args: list[str]) -> bool:
        """Find near-duplicates: search-similar --name <name> [--entity-id E]"""
        if not self._require_connected():
            return True
        if not self.fuzzy:
            print("❌ Fuzzy index not enabled. Set ENTITY_FUZZY_ENABLED=true or ENTITY_FUZZY_BACKEND=postgresql")
            return True
        name = self._extract_flag(args, '--name')
        entity_id = self._extract_flag(args, '--entity-id')
        limit = int(self._extract_flag(args, '--limit') or '10')
        min_score = float(self._extract_flag(args, '--min-score') or '50.0')

        if entity_id:
            entity = _run_async(self.registry.get_entity(entity_id))
            if not entity:
                print(f"❌ Entity not found: {entity_id}")
                return True
            candidates = self.fuzzy.find_similar(entity, limit=limit, min_score=min_score)
            candidates = [c for c in candidates if c['entity_id'] != entity_id]
        elif name:
            country = self._extract_flag(args, '--country')
            region = self._extract_flag(args, '--region')
            candidates = self.fuzzy.find_similar_by_name(
                name=name, country=country, region=region,
                limit=limit, min_score=min_score,
            )
        else:
            print("Usage: search-similar --name <name> OR --entity-id <id> [--limit N] [--min-score S]")
            return True

        rows = []
        for c in candidates:
            rows.append({
                'entity_id': c['entity_id'],
                'primary_name': c['primary_name'],
                'score': f"{c['score']:.1f}",
                'match_level': c.get('match_level', ''),
            })
        _print_table(rows, ['entity_id', 'primary_name', 'score', 'match_level'], self.output_format)
        return True

    # ------------------------------------------------------------------
    # Stats commands
    # ------------------------------------------------------------------

    def cmd_stats(self, args: list[str]) -> bool:
        """Show registry statistics."""
        if not self._require_connected():
            return True

        async def _stats():
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) FILTER (WHERE status = 'active') AS active, "
                    "COUNT(*) FILTER (WHERE status = 'deleted') AS deleted, "
                    "COUNT(*) AS total FROM entity"
                )
                type_count = await conn.fetchval("SELECT COUNT(*) FROM entity_type")
                cat_assignments = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_category_map WHERE status = 'active'"
                )
                alias_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_alias WHERE status = 'active'"
                )
                ident_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_identifier WHERE status = 'active'"
                )
                rel_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_relationship WHERE status = 'active'"
                )
                log_count = await conn.fetchval("SELECT COUNT(*) FROM entity_change_log")

                print(f"\n📊 Entity Registry Statistics")
                print(LINE)
                print(f"  Entities:       {row['active']:,} active / {row['deleted']:,} deleted / {row['total']:,} total")
                print(f"  Entity types:   {type_count:,}")
                print(f"  Aliases:        {alias_count:,}")
                print(f"  Identifiers:    {ident_count:,}")
                print(f"  Categories:     {cat_assignments:,} assignments")
                print(f"  Relationships:  {rel_count:,}")
                print(f"  Change log:     {log_count:,}")

                # Status breakdown
                rows = await conn.fetch(
                    "SELECT status, COUNT(*) AS cnt FROM entity GROUP BY status ORDER BY cnt DESC"
                )
                if rows:
                    print(f"\n  Entity Status Breakdown:")
                    for r in rows:
                        print(f"    {r['status']:15} {r['cnt']:,}")

        _run_async(_stats())
        return True

    def cmd_stats_types(self, args: list[str]) -> bool:
        """Entity counts by type."""
        if not self._require_connected():
            return True

        async def _stats_types():
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT et.type_key, et.type_label, COUNT(e.entity_id) AS count "
                    "FROM entity_type et "
                    "LEFT JOIN entity e ON et.type_id = e.entity_type_id AND e.status = 'active' "
                    "GROUP BY et.type_key, et.type_label ORDER BY count DESC"
                )
                total = sum(r['count'] for r in rows)
                print("Entity Counts by Type")
                print(LINE)
                for r in rows:
                    pct = (r['count'] / total * 100) if total > 0 else 0
                    print(f"  {r['type_key']:<20} {r['count']:>6,}  ({pct:.1f}%)")
                print(LINE)
                print(f"  {'Total':<20} {total:>6,}")

        _run_async(_stats_types())
        return True

    # ------------------------------------------------------------------
    # Change log
    # ------------------------------------------------------------------

    def cmd_changelog(self, args: list[str]) -> bool:
        """Show change log: changelog <entity_id> [--limit N]"""
        if not self._require_connected():
            return True
        if not args:
            print("Usage: changelog <entity_id> [--limit N]")
            return True
        entity_id = args.pop(0)
        limit = int(self._extract_flag(args, '--limit') or '50')
        entries, total = _run_async(self.registry.get_change_log(entity_id, limit=limit))
        rows = []
        for e in entries:
            rows.append({
                'log_id': e.get('log_id', ''),
                'change_type': e['change_type'],
                'changed_by': e.get('changed_by', '') or '',
                'created_time': str(e.get('created_time', ''))[:19],
                'comment': (e.get('comment') or '')[:40],
            })
        _print_table(rows, ['log_id', 'change_type', 'changed_by', 'created_time', 'comment'], self.output_format)
        return True

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def cmd_export(self, args: list[str]) -> bool:
        """Export entities: export [--type T] [--format json|csv] [--output file]"""
        if not self._require_connected():
            return True
        type_key = self._extract_flag(args, '--type')
        fmt = self._extract_flag(args, '--format') or 'json'
        output = self._extract_flag(args, '--output')
        include_aliases = '--include-aliases' in args
        include_identifiers = '--include-identifiers' in args
        # Remove boolean flags from args
        args[:] = [a for a in args if a not in ('--include-aliases', '--include-identifiers')]

        async def _export():
            conditions = ["e.status = 'active'"]
            params = []
            idx = 0
            if type_key:
                idx += 1
                conditions.append(f"et.type_key = ${idx}")
                params.append(type_key)
            where = "WHERE " + " AND ".join(conditions)

            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT e.entity_id, e.primary_name, e.description, "
                    f"et.type_key, et.type_label, e.country, e.region, e.locality, "
                    f"e.website, e.status, e.created_time, e.updated_time "
                    f"FROM entity e JOIN entity_type et ON e.entity_type_id = et.type_id "
                    f"{where} ORDER BY e.primary_name",
                    *params
                )
                entities = [dict(r) for r in rows]

                if include_aliases:
                    for entity in entities:
                        alias_rows = await conn.fetch(
                            "SELECT alias_name, alias_type FROM entity_alias "
                            "WHERE entity_id = $1 AND status = 'active'",
                            entity['entity_id']
                        )
                        entity['aliases'] = [dict(a) for a in alias_rows]

                if include_identifiers:
                    for entity in entities:
                        ident_rows = await conn.fetch(
                            "SELECT identifier_namespace, identifier_value FROM entity_identifier "
                            "WHERE entity_id = $1 AND status = 'active'",
                            entity['entity_id']
                        )
                        entity['identifiers'] = [dict(i) for i in ident_rows]

            if fmt == 'json':
                content = json.dumps(entities, indent=2, default=str)
            else:
                buf = io.StringIO()
                if entities:
                    fieldnames = list(entities[0].keys())
                    writer = csv_mod.DictWriter(buf, fieldnames=fieldnames)
                    writer.writeheader()
                    for e in entities:
                        flat = {}
                        for k, v in e.items():
                            flat[k] = json.dumps(v) if isinstance(v, (list, dict)) else v
                        writer.writerow(flat)
                content = buf.getvalue()

            if output:
                with open(output, 'w') as f:
                    f.write(content)
                print(f"Exported {len(entities):,} entities to {output}")
            else:
                print(content)

        _run_async(_export())
        return True

    # ------------------------------------------------------------------
    # Fuzzy commands
    # ------------------------------------------------------------------

    def cmd_fuzzy_status(self, args: list[str]) -> bool:
        """Show fuzzy index status."""
        if not self._require_connected():
            return True
        if not self.fuzzy:
            print("❌ Fuzzy index not enabled")
            return True
        print("Fuzzy Index Status")
        print(LINE)
        print(f"  Entities indexed:  {self.fuzzy.entity_count:,}")
        print(f"  Initialized:       {self.fuzzy._initialized}")
        return True

    def cmd_fuzzy_check(self, args: list[str]) -> bool:
        """Verify fuzzy index matches PostgreSQL."""
        if not self._require_connected():
            return True
        if not self.fuzzy:
            print("❌ Fuzzy index not enabled")
            return True

        async def _check():
            async with self.pool.acquire() as conn:
                pg_count = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE status = 'active'")
            fuzzy_count = self.fuzzy.entity_count
            print("Fuzzy Index Consistency Check")
            print(LINE)
            print(f"  PostgreSQL active entities: {pg_count:,}")
            print(f"  Fuzzy index entities:       {fuzzy_count:,}")
            if pg_count == fuzzy_count:
                print("  ✅ Counts match")
            else:
                print(f"  ⚠️  Mismatch: {abs(pg_count - fuzzy_count):,} difference")

        _run_async(_check())
        return True

    # ------------------------------------------------------------------
    # Vector commands (entity registry dedicated tables)
    # ------------------------------------------------------------------

    def cmd_vector_status(self, args: list[str]) -> bool:
        """Show entity registry vector/FTS/geo table status: vector-status"""
        if not self._require_connected():
            return True

        async def _status():
            from vitalgraph.entity_registry.entity_registry_vector_schema import (
                VECTOR_INDEX_TABLE, ENTITY_VECTOR_TABLE, LOCATION_VECTOR_TABLE,
                GEO_TABLE, FTS_ENTITY_TABLE, FTS_LOCATION_TABLE,
            )
            tables = [
                ('Vector Index Registry', VECTOR_INDEX_TABLE),
                ('Entity Vectors', ENTITY_VECTOR_TABLE),
                ('Location Vectors', LOCATION_VECTOR_TABLE),
                ('Geo Points', GEO_TABLE),
                ('FTS Entities', FTS_ENTITY_TABLE),
                ('FTS Locations', FTS_LOCATION_TABLE),
            ]
            print(f"Entity Registry Vector/FTS/Geo Status")
            print(LINE)
            async with self.pool.acquire() as conn:
                for label, table in tables:
                    try:
                        count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                        print(f"  {label:25s} {table:45s} ({count:,} rows)")
                    except Exception:
                        print(f"  {label:25s} {table:45s} (not created)")

                # Show index details
                try:
                    rows = await conn.fetch(
                        f"SELECT index_name, dimensions, provider, model_name, created_time "
                        f"FROM {VECTOR_INDEX_TABLE} ORDER BY index_name"
                    )
                    if rows:
                        print(f"\n  Registered Indexes:")
                        for r in rows:
                            print(f"    {r['index_name']}: {r['dimensions']}d, "
                                  f"{r['provider']}, model={r['model_name']}")
                except Exception:
                    pass

        _run_async(_status())
        return True

    def cmd_vector_check(self, args: list[str]) -> bool:
        """Consistency check: vector-check — compare entity count vs vector/FTS/geo counts"""
        if not self._require_connected():
            return True

        async def _check():
            from vitalgraph.entity_registry.entity_registry_vector_schema import (
                ENTITY_VECTOR_TABLE, LOCATION_VECTOR_TABLE, GEO_TABLE,
                FTS_ENTITY_TABLE, FTS_LOCATION_TABLE,
            )
            async with self.pool.acquire() as conn:
                entity_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity WHERE status = 'active'"
                )
                location_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_location WHERE status = 'active'"
                )
                entities_with_geo = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity WHERE status = 'active' "
                    "AND latitude IS NOT NULL AND longitude IS NOT NULL"
                )
                locations_with_geo = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_location WHERE status = 'active' "
                    "AND latitude IS NOT NULL AND longitude IS NOT NULL"
                )

                print(f"Entity Registry Vector Consistency Check")
                print(LINE)
                print(f"  Source Data:")
                print(f"    Active entities:            {entity_count:,}")
                print(f"    Active locations:           {location_count:,}")
                print(f"    Entities with lat/lon:      {entities_with_geo:,}")
                print(f"    Locations with lat/lon:     {locations_with_geo:,}")

                checks = [
                    ('Entity Vectors', ENTITY_VECTOR_TABLE, entity_count),
                    ('Location Vectors', LOCATION_VECTOR_TABLE, location_count),
                    ('FTS Entities', FTS_ENTITY_TABLE, entity_count),
                    ('FTS Locations', FTS_LOCATION_TABLE, location_count),
                    ('Geo Points', GEO_TABLE, entities_with_geo + locations_with_geo),
                ]

                print(f"\n  Index Tables:")
                for label, table, expected in checks:
                    try:
                        actual = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                        if actual == expected:
                            print(f"    ✅ {label:25s} {actual:,} (matches)")
                        else:
                            diff = expected - actual
                            print(f"    ⚠️  {label:25s} {actual:,} (expected {expected:,}, diff {diff:,})")
                    except Exception:
                        print(f"    ❌ {label:25s} (table not found)")

        _run_async(_check())
        return True

    def cmd_vector_rebuild(self, args: list[str]) -> bool:
        """Full rebuild of entity registry vectors/FTS/geo: vector-rebuild"""
        if not self._require_connected():
            return True

        async def _rebuild():
            from vitalgraph.entity_registry.entity_registry_vector_populator import (
                EntityRegistryVectorPopulator,
            )
            populator = EntityRegistryVectorPopulator(self.pool)
            print("Rebuilding entity registry vectors/FTS/geo ...")
            stats = await populator.full_rebuild()
            print(f"  ✅ Entities: {stats.entities_vectorized:,} vectorized")
            print(f"  ✅ Locations: {stats.locations_vectorized:,} vectorized")
            print(f"  ✅ Geo points: {stats.geo_rows_inserted:,} inserted")
            print(f"  ⏱  {stats.elapsed_seconds:.1f}s")
            if stats.errors:
                print(f"  ⚠️  {stats.errors} errors")

        _run_async(_rebuild())
        return True

    def cmd_vector_sync(self, args: list[str]) -> bool:
        """Incremental sync: vector-sync --entity <entity_id> | --location <location_id>"""
        if not self._require_connected():
            return True
        entity_id = self._extract_flag(args, '--entity')
        location_id_str = self._extract_flag(args, '--location')

        if not entity_id and not location_id_str:
            print("❌ --entity <entity_id> or --location <location_id> is required")
            return True

        async def _sync():
            from vitalgraph.entity_registry.entity_registry_vector_populator import (
                EntityRegistryVectorPopulator,
            )
            populator = EntityRegistryVectorPopulator(self.pool)
            if entity_id:
                await populator.sync_entity(entity_id)
                print(f"  ✅ Synced entity {entity_id}")
            if location_id_str:
                await populator.sync_location(int(location_id_str))
                print(f"  ✅ Synced location {location_id_str}")

        _run_async(_sync())
        return True

    # ------------------------------------------------------------------
    # Search topic (entity registry pgvector similarity)
    # ------------------------------------------------------------------

    def cmd_search_topic(self, args: list[str]) -> bool:
        """Semantic search: search-topic --query <text> [--type <key>] [--limit N]"""
        if not self._require_connected():
            return True
        query = self._extract_flag(args, '--query')
        if not query:
            print("❌ --query <text> is required")
            return True
        type_key = self._extract_flag(args, '--type')
        limit_str = self._extract_flag(args, '--limit')
        limit = int(limit_str) if limit_str else 10

        async def _search():
            from vitalgraph.entity_registry.entity_registry_search import EntityRegistrySearch
            search = EntityRegistrySearch(self.pool)
            results = await search.search_topic(
                query=query, type_key=type_key, limit=limit,
            )

            if not results:
                print("(no results)")
                return

            print(f"\nSemantic Search Results (top {limit})")
            print(LINE)
            for i, r in enumerate(results, 1):
                score = r.get('score', 0)
                name = r.get('primary_name', '')
                etype = r.get('type_label', '')
                print(f"  {i:3d}. [{score:.4f}] {name} ({etype})")
                desc = (r.get('description') or '')[:100]
                if desc:
                    print(f"       {desc}")

        _run_async(_search())
        return True

    # ------------------------------------------------------------------
    # Geo commands (entity registry dedicated geo table)
    # ------------------------------------------------------------------

    def cmd_geo_status(self, args: list[str]) -> bool:
        """Show entity registry geo table status: geo-status"""
        if not self._require_connected():
            return True

        async def _status():
            from vitalgraph.entity_registry.entity_registry_vector_schema import GEO_TABLE
            async with self.pool.acquire() as conn:
                print(f"Entity Registry Geo Status")
                print(LINE)
                try:
                    total = await conn.fetchval(f"SELECT COUNT(*) FROM {GEO_TABLE}")
                    entity_geo = await conn.fetchval(
                        f"SELECT COUNT(*) FROM {GEO_TABLE} WHERE source_type = 'entity'"
                    )
                    location_geo = await conn.fetchval(
                        f"SELECT COUNT(*) FROM {GEO_TABLE} WHERE source_type = 'location'"
                    )
                    print(f"  Total geo points:   {total:,}")
                    print(f"    From entities:    {entity_geo:,}")
                    print(f"    From locations:   {location_geo:,}")
                except Exception:
                    print(f"  ❌ Geo table '{GEO_TABLE}' not found")

        _run_async(_status())
        return True

    def cmd_geo_populate(self, args: list[str]) -> bool:
        """Populate geo table from entity + location lat/lon: geo-populate"""
        if not self._require_connected():
            return True

        async def _populate():
            from vitalgraph.entity_registry.entity_registry_vector_populator import (
                EntityRegistryVectorPopulator,
            )
            populator = EntityRegistryVectorPopulator(self.pool)
            print("Rebuilding entity registry geo + vectors ...")
            stats = await populator.full_rebuild()
            print(f"  ✅ {stats.geo_rows_inserted:,} geo points populated")
            print(f"  ⏱  {stats.elapsed_seconds:.1f}s")

        _run_async(_populate())
        return True

    def cmd_geo_check(self, args: list[str]) -> bool:
        """Consistency check: geo-check — entities/locations with coords vs geo table"""
        if not self._require_connected():
            return True

        async def _check():
            from vitalgraph.entity_registry.entity_registry_vector_schema import GEO_TABLE
            async with self.pool.acquire() as conn:
                entities_with_geo = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity WHERE status = 'active' "
                    "AND latitude IS NOT NULL AND longitude IS NOT NULL"
                )
                locations_with_geo = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_location WHERE status = 'active' "
                    "AND latitude IS NOT NULL AND longitude IS NOT NULL"
                )
                expected = entities_with_geo + locations_with_geo

                try:
                    geo_count = await conn.fetchval(f"SELECT COUNT(*) FROM {GEO_TABLE}")
                except Exception:
                    geo_count = '?'

                print(f"Geo Consistency Check — Entity Registry")
                print(LINE)
                print(f"  Entities with lat/lon:   {entities_with_geo:,}")
                print(f"  Locations with lat/lon:  {locations_with_geo:,}")
                print(f"  Expected geo rows:       {expected:,}")
                print(f"  Actual geo rows:         {geo_count}")
                if isinstance(geo_count, int):
                    if geo_count >= expected:
                        print("  ✅ Geo table covers all sources")
                    else:
                        diff = expected - geo_count
                        print(f"  ⚠️  {diff:,} sources missing from geo table")

        _run_async(_check())
        return True

    # ------------------------------------------------------------------
    # Schema migration
    # ------------------------------------------------------------------

    def cmd_migrate(self, args: list[str], dry_run: bool = False) -> bool:
        """Run schema migration."""
        if not self._require_connected():
            return True

        async def _migrate():
            from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
            schema = EntityRegistrySchema()
            migrations = schema.migrations_sql()

            if not migrations:
                print("No pending migrations.")
                return

            print(f"Schema Migrations ({len(migrations)} statements)")
            print(LINE)
            for i, sql in enumerate(migrations, 1):
                print(f"  {i}. {sql}")

            if dry_run:
                print("\nDRY RUN — no changes applied.")
                return

            async with self.pool.acquire() as conn:
                for sql in migrations:
                    await conn.execute(sql)
                    print(f"  ✅ {sql}")
            print(f"\nApplied {len(migrations)} migrations.")

        _run_async(_migrate())
        return True

    def cmd_delete_by_prefix(self, args: list[str], yes: bool = False, dry_run: bool = False) -> bool:
        """Delete entities by prefix: delete-by-prefix --prefix <prefix> [--dry-run]"""
        if not self._require_connected():
            return True
        prefix = self._extract_flag(args, '--prefix')
        if not prefix and args:
            prefix = args[0]
        if not prefix:
            print("Usage: delete-by-prefix --prefix <prefix> [--dry-run]")
            return True
        if '--dry-run' in args:
            dry_run = True
            args.remove('--dry-run')

        async def _delete():
            pattern = prefix + '%'
            async with self.pool.acquire() as conn:
                ent_count = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE entity_id LIKE $1", pattern)
                rel_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM entity_relationship "
                    "WHERE entity_source LIKE $1 OR entity_destination LIKE $1", pattern
                )
                alias_count = await conn.fetchval("SELECT COUNT(*) FROM entity_alias WHERE entity_id LIKE $1", pattern)

            print(f"Delete by prefix: '{prefix}'")
            print(LINE)
            print(f"  Entities:      {ent_count:,}")
            print(f"  Relationships: {rel_count:,}")
            print(f"  Aliases:       {alias_count:,}")

            if ent_count == 0:
                print("\nNo entities match this prefix.")
                return

            if dry_run:
                print(f"\nDRY RUN — would delete all of the above.")
                return

            if not yes:
                confirm = input("⚠️  Proceed with deletion? (yes/no): ").strip().lower()
                if confirm not in ('yes', 'y'):
                    print("Cancelled.")
                    return

            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM entity_relationship "
                        "WHERE entity_source LIKE $1 OR entity_destination LIKE $1", pattern
                    )
                    result = await conn.execute("DELETE FROM entity WHERE entity_id LIKE $1", pattern)
                    print(f"\n✅ Deleted: {result}")

        _run_async(_delete())
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
            # Entity types
            'list-types':            self.cmd_list_types,
            'create-type':           self.cmd_create_type,
            # Entities
            'list-entities':         self.cmd_list_entities,
            'get-entity':            self.cmd_get_entity,
            'create-entity':         self.cmd_create_entity,
            'update-entity':         self.cmd_update_entity,
            'delete-entity':         self.cmd_delete_entity,
            # Aliases
            'list-aliases':          self.cmd_list_aliases,
            'add-alias':             self.cmd_add_alias,
            'retract-alias':         self.cmd_retract_alias,
            # Identifiers
            'list-identifiers':      self.cmd_list_identifiers,
            'add-identifier':        self.cmd_add_identifier,
            'lookup-identifier':     self.cmd_lookup_identifier,
            # Categories
            'list-categories':       self.cmd_list_categories,
            'assign-category':       self.cmd_assign_category,
            'remove-category':       self.cmd_remove_category,
            # Relationships
            'list-relationship-types': self.cmd_list_relationship_types,
            'list-relationships':    self.cmd_list_relationships,
            'create-relationship':   self.cmd_create_relationship,
            # Same-as
            'resolve':               self.cmd_resolve_entity,
            # Search
            'search':                self.cmd_search,
            'search-similar':        self.cmd_search_similar,
            # Info
            'stats':                 self.cmd_stats,
            'stats-types':           self.cmd_stats_types,
            'changelog':             self.cmd_changelog,
            # Export
            'export':                self.cmd_export,
            # Fuzzy
            'fuzzy-status':          self.cmd_fuzzy_status,
            'fuzzy-check':           self.cmd_fuzzy_check,
            # Vector
            'vector-status':         self.cmd_vector_status,
            'vector-check':          self.cmd_vector_check,
            'vector-rebuild':        self.cmd_vector_rebuild,
            'vector-sync':           self.cmd_vector_sync,
            # Search
            'search-topic':          self.cmd_search_topic,
            # Geo
            'geo-status':            self.cmd_geo_status,
            'geo-populate':          self.cmd_geo_populate,
            'geo-check':             self.cmd_geo_check,
            # Schema
            'migrate':               lambda a: self.cmd_migrate(a, dry_run=('--dry-run' in a)),
            'delete-by-prefix':      lambda a: self.cmd_delete_by_prefix(a),
            # Output format
            'format':                self.cmd_format,
            # Help / exit
            'help':                  self.cmd_help,
            '?':                     self.cmd_help,
            'exit':                  lambda a: False,
            'quit':                  lambda a: False,
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
Entity Registry CLI  [{'🟢 Connected' if self.connected else '🔴 Disconnected'}]

Entity Types:
  list-types                                List all entity types
  create-type <key> <label> [desc]          Create entity type

Entities:
  list-entities [--type T] [--status S] [--search Q] [--country C] [--region R] [--limit N] [--page P]
  get-entity <id_or_uri>                    Full entity details (JSON)
  create-entity --type <key> --name <name> [--country C] [--region R] [--locality L] [--website W] [--description D]
  update-entity <id> [--name N] [--status S] [--country C] [--region R] [--locality L] [--website W] [--description D]
  delete-entity <id>                        Soft-delete entity

Aliases:
  list-aliases <entity_id>                  List entity aliases
  add-alias <entity_id> --name <name> [--type aka|trade_name|abbreviation]
  retract-alias <alias_id>                  Retract alias

Identifiers:
  list-identifiers <entity_id>              List entity identifiers
  add-identifier <entity_id> --namespace <ns> --value <val>
  lookup-identifier --namespace <ns> --value <val>    Find entity by identifier

Categories:
  list-categories                           List all categories
  assign-category <entity_id> <category_key>
  remove-category <entity_id> <category_key>

Relationships:
  list-relationship-types                   List relationship types
  list-relationships <entity_id> [--direction both|outgoing|incoming]
  create-relationship --source <id> --dest <id> --type <type_key>

Same-As:
  resolve <entity_id>                       Follow same-as chain to canonical

Search:
  search --name <name> [--type T] [--country C] [--region R] [--limit N]
  search-similar --name <name> OR --entity-id <id> [--limit N] [--min-score S]

Info:
  stats                                     Registry summary statistics
  stats-types                               Entity counts by type
  changelog <entity_id> [--limit N]         Change history

Data:
  export [--type T] [--format json|csv] [--output file] [--include-aliases] [--include-identifiers]
  delete-by-prefix --prefix <prefix> [--dry-run]

Fuzzy:
  fuzzy-status                              Fuzzy index status
  fuzzy-check                               Verify fuzzy index vs PostgreSQL

Vector / FTS / Geo (entity registry dedicated tables):
  vector-status                             Show vector/FTS/geo table status
  vector-check                              Consistency: entity count vs index counts
  vector-rebuild                            Full rebuild all vectors/FTS/geo
  vector-sync --entity <id> | --location N  Incremental re-vectorize

Search:
  search-topic --query <text> [--type <key>] [--limit N]   Semantic entity search

Geo:
  geo-status                                Show geo point counts
  geo-populate                              Populate geo table from entity/location coords
  geo-check                                 Consistency: sources with coords vs geo table

Schema:
  migrate [--dry-run]                       Run schema migrations

  format table|json|csv                     Set output format
  help / ?                                  This message
  exit / quit                               Exit
""")
        return True

    # ------------------------------------------------------------------
    # REPL loop
    # ------------------------------------------------------------------

    def run_repl(self):
        """Run interactive REPL."""
        signal.signal(signal.SIGINT, lambda s, f: (self.disconnect(), print("Goodbye!"), sys.exit(0)))

        print("VitalGraph Entity Registry CLI")
        print("Type 'help' for commands, 'exit' to quit.")
        print()

        try:
            self.connect()
        except Exception as e:
            print(f"⚠️  Could not auto-connect: {e}")

        history_file = Path.home() / ".vitalgraph_entity_registry_history"
        history = FileHistory(str(history_file))

        try:
            while True:
                try:
                    indicator = "🟢" if self.connected else "🔴"
                    prompt_text = f"entity-registry{indicator}> "
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

            elif command == 'list-entities':
                cmd_args = []
                if args.type:
                    cmd_args.extend(['--type', args.type])
                if args.status:
                    cmd_args.extend(['--status', args.status])
                if args.search:
                    cmd_args.extend(['--search', args.search])
                if args.country:
                    cmd_args.extend(['--country', args.country])
                if args.region:
                    cmd_args.extend(['--region', args.region])
                if args.limit:
                    cmd_args.extend(['--limit', str(args.limit)])
                self.cmd_list_entities(cmd_args)

            elif command == 'get-entity':
                self.cmd_get_entity([args.entity_id])

            elif command == 'create-entity':
                cmd_args = ['--type', args.type, '--name', args.name]
                if args.country:
                    cmd_args.extend(['--country', args.country])
                if args.region:
                    cmd_args.extend(['--region', args.region])
                if args.locality:
                    cmd_args.extend(['--locality', args.locality])
                if args.website:
                    cmd_args.extend(['--website', args.website])
                if args.description:
                    cmd_args.extend(['--description', args.description])
                self.cmd_create_entity(cmd_args)

            elif command == 'update-entity':
                cmd_args = [args.entity_id]
                if args.name:
                    cmd_args.extend(['--name', args.name])
                if args.status:
                    cmd_args.extend(['--status', args.status])
                if args.country:
                    cmd_args.extend(['--country', args.country])
                if args.region:
                    cmd_args.extend(['--region', args.region])
                if args.locality:
                    cmd_args.extend(['--locality', args.locality])
                if args.website:
                    cmd_args.extend(['--website', args.website])
                if args.description:
                    cmd_args.extend(['--description', args.description])
                self.cmd_update_entity(cmd_args)

            elif command == 'delete-entity':
                self.cmd_delete_entity([args.entity_id], yes=args.yes)

            elif command == 'list-aliases':
                self.cmd_list_aliases([args.entity_id])

            elif command == 'add-alias':
                cmd_args = [args.entity_id, '--name', args.name]
                if args.alias_type:
                    cmd_args.extend(['--type', args.alias_type])
                self.cmd_add_alias(cmd_args)

            elif command == 'retract-alias':
                self.cmd_retract_alias([str(args.alias_id)])

            elif command == 'list-identifiers':
                self.cmd_list_identifiers([args.entity_id])

            elif command == 'add-identifier':
                self.cmd_add_identifier([args.entity_id, '--namespace', args.namespace, '--value', args.value])

            elif command == 'lookup-identifier':
                cmd_args = []
                if args.namespace:
                    cmd_args.extend(['--namespace', args.namespace])
                cmd_args.extend(['--value', args.value])
                self.cmd_lookup_identifier(cmd_args)

            elif command == 'list-categories':
                self.cmd_list_categories([])

            elif command == 'assign-category':
                self.cmd_assign_category([args.entity_id, args.category_key])

            elif command == 'remove-category':
                self.cmd_remove_category([args.entity_id, args.category_key])

            elif command == 'list-relationship-types':
                self.cmd_list_relationship_types([])

            elif command == 'list-relationships':
                cmd_args = [args.entity_id]
                if args.direction:
                    cmd_args.extend(['--direction', args.direction])
                self.cmd_list_relationships(cmd_args)

            elif command == 'create-relationship':
                self.cmd_create_relationship(
                    ['--source', args.source, '--dest', args.dest, '--type', args.type]
                )

            elif command == 'resolve':
                self.cmd_resolve_entity([args.entity_id])

            elif command == 'search':
                cmd_args = ['--name', args.name]
                if args.type:
                    cmd_args.extend(['--type', args.type])
                if args.country:
                    cmd_args.extend(['--country', args.country])
                if args.region:
                    cmd_args.extend(['--region', args.region])
                if args.limit:
                    cmd_args.extend(['--limit', str(args.limit)])
                self.cmd_search(cmd_args)

            elif command == 'search-similar':
                cmd_args = []
                if args.name:
                    cmd_args.extend(['--name', args.name])
                if args.entity_id:
                    cmd_args.extend(['--entity-id', args.entity_id])
                if args.limit:
                    cmd_args.extend(['--limit', str(args.limit)])
                self.cmd_search_similar(cmd_args)

            elif command == 'stats':
                self.cmd_stats([])

            elif command == 'stats-types':
                self.cmd_stats_types([])

            elif command == 'changelog':
                cmd_args = [args.entity_id]
                if args.limit:
                    cmd_args.extend(['--limit', str(args.limit)])
                self.cmd_changelog(cmd_args)

            elif command == 'export':
                cmd_args = []
                if args.type:
                    cmd_args.extend(['--type', args.type])
                if args.format:
                    cmd_args.extend(['--format', args.format])
                if args.output:
                    cmd_args.extend(['--output', args.output])
                if getattr(args, 'include_aliases', False):
                    cmd_args.append('--include-aliases')
                if getattr(args, 'include_identifiers', False):
                    cmd_args.append('--include-identifiers')
                self.cmd_export(cmd_args)

            elif command == 'fuzzy-status':
                self.cmd_fuzzy_status([])

            elif command == 'fuzzy-check':
                self.cmd_fuzzy_check([])

            elif command == 'vector-status':
                self.cmd_vector_status(['--space', args.space] if args.space else [])

            elif command == 'vector-check':
                cmd_args = []
                if args.space:
                    cmd_args.extend(['--space', args.space])
                if args.index:
                    cmd_args.extend(['--index', args.index])
                self.cmd_vector_check(cmd_args)

            elif command == 'vector-rebuild':
                cmd_args = []
                if args.space:
                    cmd_args.extend(['--space', args.space])
                if args.graph:
                    cmd_args.extend(['--graph', args.graph])
                if args.index:
                    cmd_args.extend(['--index', args.index])
                self.cmd_vector_rebuild(cmd_args)

            elif command == 'vector-sync':
                cmd_args = []
                if args.space:
                    cmd_args.extend(['--space', args.space])
                if args.graph:
                    cmd_args.extend(['--graph', args.graph])
                if args.subject:
                    cmd_args.extend(['--subject', args.subject])
                self.cmd_vector_sync(cmd_args)

            elif command == 'search-topic':
                cmd_args = []
                if args.space:
                    cmd_args.extend(['--space', args.space])
                if args.query_text:
                    cmd_args.extend(['--query', args.query_text])
                if args.index:
                    cmd_args.extend(['--index', args.index])
                if args.limit:
                    cmd_args.extend(['--limit', str(args.limit)])
                self.cmd_search_topic(cmd_args)

            elif command == 'geo-status':
                self.cmd_geo_status(['--space', args.space] if args.space else [])

            elif command == 'geo-populate':
                cmd_args = []
                if args.space:
                    cmd_args.extend(['--space', args.space])
                if args.graph:
                    cmd_args.extend(['--graph', args.graph])
                self.cmd_geo_populate(cmd_args)

            elif command == 'geo-check':
                self.cmd_geo_check(['--space', args.space] if args.space else [])

            elif command == 'migrate':
                self.cmd_migrate([], dry_run=args.dry_run)

            elif command == 'delete-by-prefix':
                cmd_args = ['--prefix', args.prefix]
                if args.dry_run:
                    cmd_args.append('--dry-run')
                self.cmd_delete_by_prefix(cmd_args, yes=args.yes)

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
        description="VitalGraph Entity Registry CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraphentityregistry                                        # Start REPL
  vitalgraphentityregistry -c list-types                          # List entity types
  vitalgraphentityregistry -c list-entities --status active       # List active entities
  vitalgraphentityregistry -c search --name "Acme" --type company
  vitalgraphentityregistry -c create-entity --type company --name "Acme Corp" --country US
  vitalgraphentityregistry -c export --format json --output entities.json
  vitalgraphentityregistry -c migrate --dry-run                   # Preview schema migration
        """,
    )

    parser.add_argument(
        "-c", "--command",
        type=str,
        choices=[
            # Entity types
            "list-types", "create-type",
            # Entities
            "list-entities", "get-entity", "create-entity", "update-entity", "delete-entity",
            # Aliases
            "list-aliases", "add-alias", "retract-alias",
            # Identifiers
            "list-identifiers", "add-identifier", "lookup-identifier",
            # Categories
            "list-categories", "assign-category", "remove-category",
            # Relationships
            "list-relationship-types", "list-relationships", "create-relationship",
            # Same-as
            "resolve",
            # Search
            "search", "search-similar",
            # Info
            "stats", "stats-types", "changelog",
            # Data
            "export", "delete-by-prefix",
            # Fuzzy
            "fuzzy-status", "fuzzy-check",
            # Vector
            "vector-status", "vector-check", "vector-rebuild", "vector-sync",
            # Search
            "search-topic",
            # Geo
            "geo-status", "geo-populate", "geo-check",
            # Schema
            "migrate",
        ],
        help="Execute command non-interactively (omit for REPL mode)",
    )

    # Entity type args
    parser.add_argument("--type-key", type=str, help="Entity type key for create-type")
    parser.add_argument("--type-label", type=str, help="Entity type label for create-type")

    # Entity identification
    parser.add_argument("--entity-id", type=str, help="Entity ID")
    parser.add_argument("--type", type=str, help="Entity type key filter")
    parser.add_argument("--name", type=str, help="Entity/alias name")
    parser.add_argument("--description", type=str, help="Description")
    parser.add_argument("--country", type=str, help="Country")
    parser.add_argument("--region", type=str, help="Region")
    parser.add_argument("--locality", type=str, help="Locality/city")
    parser.add_argument("--website", type=str, help="Website URL")
    parser.add_argument("--status", type=str, help="Status filter or new status")
    parser.add_argument("--search", type=str, help="Search query")
    parser.add_argument("--limit", type=int, help="Result limit")

    # Alias args
    parser.add_argument("--alias-id", type=int, help="Alias ID for retract")
    parser.add_argument("--alias-type", type=str, help="Alias type (aka, trade_name, abbreviation)")

    # Identifier args
    parser.add_argument("--namespace", type=str, help="Identifier namespace")
    parser.add_argument("--value", type=str, help="Identifier value")

    # Category args
    parser.add_argument("--category-key", type=str, help="Category key")

    # Relationship args
    parser.add_argument("--source", type=str, help="Source entity ID for relationship")
    parser.add_argument("--dest", type=str, help="Destination entity ID for relationship")
    parser.add_argument("--direction", type=str, help="Relationship direction (both|outgoing|incoming)")

    # Export args
    parser.add_argument("--format", type=str, choices=["json", "csv", "table"], help="Output format")
    parser.add_argument("--output", "-o", type=str, help="Output file")
    parser.add_argument("--include-aliases", action="store_true", help="Include aliases in export")
    parser.add_argument("--include-identifiers", action="store_true", help="Include identifiers in export")

    # Vector / Geo / Search args
    parser.add_argument("--space", type=str, help="Space ID for vector/geo commands")
    parser.add_argument("--graph", type=str, help="Graph URI for vector-rebuild/sync/geo-populate")
    parser.add_argument("--index", type=str, help="Vector index name")
    parser.add_argument("--subject", type=str, help="Subject URI for vector-sync")
    parser.add_argument("--query-text", type=str, help="Query text for search-topic")

    # Delete args
    parser.add_argument("--prefix", type=str, help="Entity ID prefix for delete-by-prefix")

    # Flags
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--dry-run", action="store_true", help="Dry run for migrate/delete")

    parser.add_argument("--version", action="version", version="VitalGraph Entity Registry CLI 1.0.0")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    cli = EntityRegistryCLI()

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
