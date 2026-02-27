#!/usr/bin/env python3
"""
Entity Registry Administration CLI.

Provides commands for stats, search, dedup index management,
Weaviate index management, and data export.

Usage:
    python entity_registry/entity_admin.py stats
    python entity_registry/entity_admin.py stats types
    python entity_registry/entity_admin.py search sql --name "Acme"
    python entity_registry/entity_admin.py dedup status
    python entity_registry/entity_admin.py weaviate status
    python entity_registry/entity_admin.py export --format json -o entities.json
"""

import argparse
import asyncio
import csv
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('weaviate').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

LINE = '─' * 50


class EntityAdmin:
    """CLI application for Entity Registry administration."""

    def __init__(self):
        self.pool = None
        self.registry = None
        self.dedup = None
        self.weaviate = None

    async def connect(self):
        """Connect to PostgreSQL and optional backends."""
        from vitalgraph.config.config_loader import VitalGraphConfig
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

        # Initialize dedup index (optional)
        try:
            from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex
            self.dedup = EntityDedupIndex.from_env()
            if self.dedup:
                count = await self.dedup.initialize(self.pool)
                logger.info(f"Dedup index loaded {count} entities")
        except Exception as e:
            logger.debug(f"Dedup index not available: {e}")

        # Initialize Weaviate index (optional)
        try:
            from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
            self.weaviate = await EntityWeaviateIndex.from_env()
        except Exception as e:
            logger.debug(f"Weaviate index not available: {e}")

    async def disconnect(self):
        """Clean up connections."""
        if self.pool:
            await self.pool.close()
        if self.weaviate:
            await self.weaviate.close()

    async def run(self, args):
        """Main entry point — connect, dispatch, disconnect."""
        await self.connect()
        try:
            cmd = args.command
            sub = getattr(args, 'sub', None)

            if cmd == 'stats':
                if sub == 'types':
                    await self.cmd_stats_types(args)
                elif sub == 'aliases':
                    await self.cmd_stats_aliases(args)
                elif sub == 'categories':
                    await self.cmd_stats_categories(args)
                elif sub == 'identifiers':
                    await self.cmd_stats_identifiers(args)
                elif sub == 'changelog':
                    await self.cmd_stats_changelog(args)
                else:
                    await self.cmd_stats(args)
            elif cmd == 'dedup':
                if sub == 'status':
                    await self.cmd_dedup_status(args)
                elif sub == 'sync':
                    await self.cmd_dedup_sync(args)
                elif sub == 'check':
                    await self.cmd_dedup_check(args)
                else:
                    print("Usage: entity_admin.py dedup {status|sync|check}")
            elif cmd == 'weaviate':
                if sub == 'status':
                    await self.cmd_weaviate_status(args)
                elif sub == 'collections':
                    await self.cmd_weaviate_collections(args)
                elif sub == 'rebuild':
                    await self.cmd_weaviate_rebuild(args)
                elif sub == 'sync':
                    await self.cmd_weaviate_sync(args)
                elif sub == 'check':
                    await self.cmd_weaviate_check(args)
                else:
                    print("Usage: entity_admin.py weaviate {status|collections|rebuild|sync|check}")
            elif cmd == 'search':
                if sub == 'sql':
                    await self.cmd_search_sql(args)
                elif sub == 'similar':
                    await self.cmd_search_similar(args)
                elif sub == 'topic':
                    await self.cmd_search_topic(args)
                else:
                    print("Usage: entity_admin.py search {sql|similar|topic}")
            elif cmd == 'export':
                await self.cmd_export(args)
            elif cmd == 'types':
                if sub == 'list':
                    await self.cmd_types_list(args)
                elif sub == 'add':
                    await self.cmd_types_add(args)
                else:
                    print("Usage: entity_admin.py types {list|add}")
            elif cmd == 'delete':
                if sub == 'by-prefix':
                    await self.cmd_delete_by_prefix(args)
                else:
                    print("Usage: entity_admin.py delete {by-prefix}")
            elif cmd == 'migrate':
                await self.cmd_migrate(args)
            else:
                print("Usage: entity_admin.py {stats|dedup|weaviate|search|export|types|delete|migrate}")
        finally:
            await self.disconnect()

    # ==================================================================
    # Stats commands
    # ==================================================================

    async def cmd_stats(self, args):
        """Full summary stats."""
        async with self.pool.acquire() as conn:
            # Entity counts
            row = await conn.fetchrow(
                "SELECT COUNT(*) FILTER (WHERE status = 'active') AS active, "
                "COUNT(*) FILTER (WHERE status = 'deleted') AS deleted, "
                "COUNT(*) AS total FROM entity"
            )
            # Type count
            type_count = await conn.fetchval("SELECT COUNT(*) FROM entity_type")
            # Category counts
            cat_defined = await conn.fetchval("SELECT COUNT(*) FROM entity_category")
            cat_assignments = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_category_map WHERE status = 'active'"
            )
            # Alias counts
            alias_row = await conn.fetchrow(
                "SELECT COUNT(*) FILTER (WHERE status = 'active') AS active, "
                "COUNT(*) FILTER (WHERE status = 'retracted') AS retracted "
                "FROM entity_alias"
            )
            # Identifier count
            ident_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_identifier WHERE status = 'active'"
            )
            # Same-as counts
            sa_row = await conn.fetchrow(
                "SELECT COUNT(*) FILTER (WHERE status = 'active') AS active, "
                "COUNT(*) FILTER (WHERE status = 'retracted') AS retracted "
                "FROM entity_same_as"
            )
            # Changelog
            cl_count = await conn.fetchval("SELECT COUNT(*) FROM entity_change_log")
            last_change = await conn.fetchval("SELECT MAX(created_time) FROM entity_change_log")

        print("Entity Registry Stats")
        print(LINE)
        print(f"Entities:      {row['active']:,} active / {row['deleted']:,} deleted / {row['total']:,} total")
        print(f"Entity Types:  {type_count}")
        print(f"Categories:    {cat_defined} defined / {cat_assignments:,} assignments")
        print(f"Aliases:       {alias_row['active']:,} active / {alias_row['retracted']:,} retracted")
        print(f"Identifiers:   {ident_count:,} active")
        print(f"Same-As:       {sa_row['active']:,} active / {sa_row['retracted']:,} retracted")
        print(f"Change Log:    {cl_count:,} entries")
        print(f"Last Change:   {last_change or 'N/A'}")

    async def cmd_stats_types(self, args):
        """Entity counts by type."""
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
            print(f"{r['type_key']:<20} {r['count']:>6,}  ({pct:.1f}%)")
        print(LINE)
        print(f"{'Total':<20} {total:>6,}")

    async def cmd_stats_aliases(self, args):
        """Alias stats."""
        async with self.pool.acquire() as conn:
            total_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active'"
            )
            entities_with = await conn.fetchval(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_alias WHERE status = 'active'"
            )
            active_aliases = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_alias WHERE status = 'active'"
            )
            type_rows = await conn.fetch(
                "SELECT alias_type, COUNT(*) AS count FROM entity_alias "
                "WHERE status = 'active' GROUP BY alias_type ORDER BY count DESC"
            )

        pct = (entities_with / total_entities * 100) if total_entities > 0 else 0
        avg = (active_aliases / entities_with) if entities_with > 0 else 0

        print("Alias Stats")
        print(LINE)
        print(f"Entities with aliases:  {entities_with:,} / {total_entities:,}  ({pct:.1f}%)")
        print(f"Total active aliases:   {active_aliases:,}")
        print(f"Avg aliases per entity: {avg:.1f}")
        types_str = '  '.join(f"{r['alias_type']}={r['count']:,}" for r in type_rows)
        print(f"Alias types:  {types_str}")

    async def cmd_stats_categories(self, args):
        """Category stats."""
        async with self.pool.acquire() as conn:
            total_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active'"
            )
            entities_with = await conn.fetchval(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_category_map WHERE status = 'active'"
            )
            active_assignments = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_category_map WHERE status = 'active'"
            )
            cat_rows = await conn.fetch(
                "SELECT ec.category_key, ec.category_label, COUNT(ecm.entity_id) AS count "
                "FROM entity_category ec "
                "LEFT JOIN entity_category_map ecm ON ec.category_id = ecm.category_id AND ecm.status = 'active' "
                "GROUP BY ec.category_key, ec.category_label ORDER BY count DESC"
            )

        pct = (entities_with / total_entities * 100) if total_entities > 0 else 0
        avg = (active_assignments / entities_with) if entities_with > 0 else 0

        print("Category Stats")
        print(LINE)
        print(f"Entities with categories: {entities_with:,} / {total_entities:,}  ({pct:.1f}%)")
        print(f"Total active assignments: {active_assignments:,}")
        print(f"Avg categories per entity: {avg:.1f}")
        print()
        print("Category Breakdown:")
        for r in cat_rows:
            cat_pct = (r['count'] / total_entities * 100) if total_entities > 0 else 0
            print(f"  {r['category_key']:<20} {r['count']:>6,}  ({cat_pct:.1f}%)")

    async def cmd_stats_identifiers(self, args):
        """Identifier stats."""
        async with self.pool.acquire() as conn:
            total_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active'"
            )
            entities_with = await conn.fetchval(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_identifier WHERE status = 'active'"
            )
            active_idents = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_identifier WHERE status = 'active'"
            )
            ns_rows = await conn.fetch(
                "SELECT identifier_namespace, COUNT(*) AS count FROM entity_identifier "
                "WHERE status = 'active' GROUP BY identifier_namespace ORDER BY count DESC"
            )

        pct = (entities_with / total_entities * 100) if total_entities > 0 else 0
        print("Identifier Stats")
        print(LINE)
        print(f"Entities with identifiers: {entities_with:,} / {total_entities:,}  ({pct:.1f}%)")
        print(f"Total active identifiers:  {active_idents:,}")
        ns_str = '  '.join(f"{r['identifier_namespace']}={r['count']:,}" for r in ns_rows)
        print(f"Namespaces:  {ns_str}" if ns_str else "Namespaces:  (none)")

    async def cmd_stats_changelog(self, args):
        """Changelog activity summary."""
        days = getattr(args, 'days', 7)
        since = datetime.now(timezone.utc) - timedelta(days=days)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT change_type, COUNT(*) AS count FROM entity_change_log "
                "WHERE created_time >= $1 GROUP BY change_type ORDER BY count DESC",
                since
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_change_log WHERE created_time >= $1", since
            )
            last = await conn.fetchval("SELECT MAX(created_time) FROM entity_change_log")

        print(f"Changelog Activity (last {days} days)")
        print(LINE)
        for r in rows:
            print(f"  {r['change_type']:<25} {r['count']:>6,}")
        print(LINE)
        print(f"  {'Total':<25} {total:>6,}")
        print(f"  Last change: {last or 'N/A'}")

    # ==================================================================
    # Dedup commands
    # ==================================================================

    async def cmd_dedup_status(self, args):
        """Show MinHash LSH dedup index status."""
        if not self.dedup:
            print("Dedup index is not enabled. Set ENTITY_DEDUP_ENABLED=true")
            return
        print("Dedup Index Status")
        print(LINE)
        print(f"  Entities indexed:  {self.dedup.entity_count:,}")
        print(f"  Initialized:       {self.dedup._initialized}")
        print(f"  Num permutations:  {self.dedup.num_perm}")
        print(f"  LSH threshold:     {self.dedup.threshold}")
        print(f"  Shingle k:         {self.dedup.shingle_k}")
        backend = 'redis' if self.dedup.storage_config else 'memory'
        print(f"  Backend:           {backend}")

    async def cmd_dedup_sync(self, args):
        """Sync dedup index from PostgreSQL."""
        if not self.dedup:
            print("Dedup index is not enabled. Set ENTITY_DEDUP_ENABLED=true")
            return

        if getattr(args, 'entity_id', None):
            # Single entity sync
            eid = args.entity_id
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT e.*, et.type_key, et.type_label FROM entity e "
                    "JOIN entity_type et ON e.entity_type_id = et.type_id "
                    "WHERE e.entity_id = $1", eid
                )
                if not row:
                    print(f"Entity not found: {eid}")
                    return
                entity = dict(row)
                alias_rows = await conn.fetch(
                    "SELECT alias_name FROM entity_alias WHERE entity_id = $1 AND status = 'active'", eid
                )
                entity['aliases'] = [dict(a) for a in alias_rows]

            if getattr(args, 'dry_run', False):
                print(f"DRY RUN: Would sync entity {eid} to dedup index")
                return

            self.dedup.add_entity(eid, entity)
            print(f"Synced entity {eid} to dedup index")
        else:
            # Full sync
            if getattr(args, 'dry_run', False):
                async with self.pool.acquire() as conn:
                    count = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE status = 'active'")
                print(f"DRY RUN: Would sync {count:,} entities to dedup index")
                return

            start = time.time()
            count = await self.dedup.initialize(self.pool)
            duration = time.time() - start
            print(f"Full dedup sync complete: {count:,} entities in {duration:.1f}s")

    async def cmd_dedup_check(self, args):
        """Verify dedup index matches PostgreSQL."""
        if not self.dedup:
            print("Dedup index is not enabled. Set ENTITY_DEDUP_ENABLED=true")
            return

        async with self.pool.acquire() as conn:
            pg_count = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE status = 'active'")

        dedup_count = self.dedup.entity_count

        print("Dedup Index Consistency Check")
        print(LINE)
        print(f"  PostgreSQL active entities: {pg_count:,}")
        print(f"  Dedup index entities:       {dedup_count:,}")
        if pg_count == dedup_count:
            print("  ✅ Counts match")
        else:
            print(f"  ⚠️  Mismatch: {abs(pg_count - dedup_count):,} difference")
            print("  Run 'dedup sync --full' to re-sync")

    # ==================================================================
    # Weaviate commands
    # ==================================================================

    async def cmd_weaviate_status(self, args):
        """Show Weaviate collection status with detailed info."""
        if not self.weaviate:
            print("Weaviate is not enabled. Set ENTITY_WEAVIATE_ENABLED=true")
            return
        status = await self.weaviate.get_status()

        print("Weaviate Collection Status")
        print(LINE)
        for label, info in status.items():
            display = label.replace('_', ' ').title()
            if info.get('error'):
                print(f"\n  {display}:")
                print(f"    ❌ Error: {info['error'][:120]}")
                continue
            if not info.get('exists'):
                print(f"\n  {display}:")
                print(f"    ⚠️  Does not exist")
                continue

            print(f"\n  {display}:")
            print(f"    Collection:   {info.get('collection_name', 'N/A')}")
            print(f"    Objects:      {info.get('object_count', 0):,}")
            if info.get('properties'):
                print(f"    Properties:   {len(info['properties'])} — {', '.join(info['properties'])}")
            if info.get('references'):
                print(f"    References:   {', '.join(info['references'])}")
            else:
                print(f"    References:   (none)")
            if info.get('vectorizer'):
                print(f"    Vectorizer:   {info['vectorizer'][:80]}")

        # Also show PostgreSQL counts for comparison
        async with self.pool.acquire() as conn:
            pg_entities = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE status = 'active'")
            pg_locations = await conn.fetchval("SELECT COUNT(*) FROM entity_location WHERE status = 'active'")
        print(f"\n  PostgreSQL Comparison:")
        print(f"    Active entities:   {pg_entities:,}")
        print(f"    Active locations:  {pg_locations:,}")
        print(LINE)

    async def cmd_weaviate_collections(self, args):
        """List all collections on the Weaviate instance."""
        if not self.weaviate:
            print("Weaviate is not enabled. Set ENTITY_WEAVIATE_ENABLED=true")
            return
        collections = await self.weaviate.list_all_collections()
        if not collections:
            print("No collections found on the Weaviate instance.")
            return
        print(f"Weaviate Collections ({len(collections)} total)")
        print(LINE)
        for c in sorted(collections, key=lambda x: x['name']):
            obj_str = f"{c['object_count']:,}" if isinstance(c.get('object_count'), int) else '?'
            props = c.get('properties', '?')
            refs = c.get('references', '?')
            print(f"  {c['name']:<45} objects={obj_str:<8} props={props}  refs={refs}")
        print(LINE)

    async def cmd_weaviate_rebuild(self, args):
        """Drop and recreate Weaviate collections, then full sync."""
        if not self.weaviate:
            print("Weaviate is not enabled. Set ENTITY_WEAVIATE_ENABLED=true")
            return

        import time
        print("Rebuilding Weaviate collections (drop + recreate)...")
        ok = await self.weaviate.rebuild_collection()
        if not ok:
            print("ERROR: Failed to rebuild collections")
            return
        print("Collections recreated. Starting full sync...")

        start = time.time()
        batch_size = getattr(args, 'batch_size', 100)
        upserted, deleted = await self.weaviate.full_sync(self.pool, batch_size=batch_size)
        loc_upserted, loc_deleted = await self.weaviate.location_sync(self.pool, batch_size=200)
        duration = time.time() - start
        print(f"Rebuild complete in {duration:.1f}s:")
        print(f"  Entities:  {upserted:,} upserted, {deleted:,} deleted")
        print(f"  Locations: {loc_upserted:,} upserted, {loc_deleted:,} deleted")

    async def cmd_weaviate_sync(self, args):
        """Sync entities to Weaviate."""
        if not self.weaviate:
            print("Weaviate is not enabled. Set ENTITY_WEAVIATE_ENABLED=true")
            return

        if getattr(args, 'entity_id', None):
            eid = args.entity_id
            # Delegate to the sync script logic
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT e.*, et.type_key, et.type_label, et.type_description "
                    "FROM entity e JOIN entity_type et ON e.entity_type_id = et.type_id "
                    "WHERE e.entity_id = $1", eid
                )
                if not row:
                    print(f"Entity not found: {eid}")
                    return
                entity = dict(row)
                alias_rows = await conn.fetch(
                    "SELECT alias_name, alias_type FROM entity_alias "
                    "WHERE entity_id = $1 AND status = 'active'", eid
                )
                entity['aliases'] = [dict(a) for a in alias_rows]
                cat_rows = await conn.fetch(
                    "SELECT ec.category_key, ec.category_label "
                    "FROM entity_category_map ecm JOIN entity_category ec ON ecm.category_id = ec.category_id "
                    "WHERE ecm.entity_id = $1 AND ecm.status = 'active'", eid
                )
                entity['categories'] = [dict(c) for c in cat_rows]

            if getattr(args, 'dry_run', False):
                from vitalgraph.entity_registry.entity_weaviate_schema import entity_to_weaviate_properties
                props = entity_to_weaviate_properties(entity)
                print(f"DRY RUN: Would upsert entity {eid}:")
                for k, v in props.items():
                    print(f"  {k}: {v}")
                return

            await self.weaviate.ensure_collection()
            if entity.get('status') == 'deleted':
                await self.weaviate.delete_entity(eid)
                print(f"Deleted {eid} from Weaviate")
            else:
                await self.weaviate.upsert_entity(entity)
                print(f"Upserted {eid} to Weaviate")
        else:
            # Full sync
            batch_size = getattr(args, 'batch_size', 100)
            if getattr(args, 'dry_run', False):
                async with self.pool.acquire() as conn:
                    count = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE status = 'active'")
                print(f"DRY RUN: Would sync {count:,} entities to Weaviate (batch_size={batch_size})")
                return

            await self.weaviate.ensure_collection()
            start = time.time()
            upserted, deleted = await self.weaviate.full_sync(self.pool, batch_size=batch_size)
            duration = time.time() - start
            print(f"Full Weaviate sync complete: {upserted:,} upserted, {deleted:,} deleted in {duration:.1f}s")

    async def cmd_weaviate_check(self, args):
        """Verify Weaviate index matches PostgreSQL."""
        if not self.weaviate:
            print("Weaviate is not enabled. Set ENTITY_WEAVIATE_ENABLED=true")
            return

        async with self.pool.acquire() as conn:
            pg_entities = await conn.fetchval("SELECT COUNT(*) FROM entity WHERE status = 'active'")
            pg_locations = await conn.fetchval("SELECT COUNT(*) FROM entity_location WHERE status = 'active'")

        wv_status = await self.weaviate.get_status()
        ent_info = wv_status.get('entity_index', {})
        loc_info = wv_status.get('location_index', {})
        wv_entities = ent_info.get('object_count', 0) if ent_info.get('exists') else 0
        wv_locations = loc_info.get('object_count', 0) if loc_info.get('exists') else 0

        print("Weaviate Index Consistency Check")
        print(LINE)
        print(f"\n  EntityIndex:")
        print(f"    PostgreSQL active:  {pg_entities:,}")
        print(f"    Weaviate objects:   {wv_entities:,}")
        print(f"    Collection:         {ent_info.get('collection_name', 'N/A')}")
        if ent_info.get('error'):
            print(f"    ❌ Error: {ent_info['error'][:100]}")
        elif not ent_info.get('exists'):
            print(f"    ⚠️  Collection does not exist")
        elif pg_entities == wv_entities:
            print(f"    ✅ Counts match")
        else:
            print(f"    ⚠️  Mismatch: {abs(pg_entities - wv_entities):,} difference")

        print(f"\n  LocationIndex:")
        print(f"    PostgreSQL active:  {pg_locations:,}")
        print(f"    Weaviate objects:   {wv_locations:,}")
        print(f"    Collection:         {loc_info.get('collection_name', 'N/A')}")
        if loc_info.get('error'):
            print(f"    ❌ Error: {loc_info['error'][:100]}")
        elif not loc_info.get('exists'):
            print(f"    ⚠️  Collection does not exist")
        elif pg_locations == wv_locations:
            print(f"    ✅ Counts match")
        else:
            print(f"    ⚠️  Mismatch: {abs(pg_locations - wv_locations):,} difference")

        print(LINE)
        if (pg_entities != wv_entities or pg_locations != wv_locations) and not ent_info.get('error'):
            print("  Run 'weaviate sync --full' to re-sync")

    # ==================================================================
    # Search commands
    # ==================================================================

    async def cmd_search_sql(self, args):
        """Search entities via SQL."""
        conditions = []
        params = []
        idx = 0

        if getattr(args, 'status', None):
            idx += 1
            conditions.append(f"e.status = ${idx}")
            params.append(args.status)

        if getattr(args, 'type_key', None):
            idx += 1
            conditions.append(f"et.type_key = ${idx}")
            params.append(args.type_key)

        if getattr(args, 'category_key', None):
            idx += 1
            conditions.append(
                f"EXISTS (SELECT 1 FROM entity_category_map ecm "
                f"JOIN entity_category ec ON ecm.category_id = ec.category_id "
                f"WHERE ecm.entity_id = e.entity_id AND ecm.status = 'active' "
                f"AND ec.category_key = ${idx})"
            )
            params.append(args.category_key)

        if getattr(args, 'country', None):
            idx += 1
            conditions.append(f"e.country ILIKE ${idx}")
            params.append(f"%{args.country}%")

        if getattr(args, 'region', None):
            idx += 1
            conditions.append(f"e.region ILIKE ${idx}")
            params.append(f"%{args.region}%")

        if getattr(args, 'locality', None):
            idx += 1
            conditions.append(f"e.locality ILIKE ${idx}")
            params.append(f"%{args.locality}%")

        if args.name:
            idx += 1
            name_cond = f"e.primary_name ILIKE ${idx}"
            if getattr(args, 'include_aliases', False):
                name_cond = (
                    f"({name_cond} OR EXISTS (SELECT 1 FROM entity_alias ea "
                    f"WHERE ea.entity_id = e.entity_id AND ea.status != 'retracted' "
                    f"AND ea.alias_name ILIKE ${idx}))"
                )
            conditions.append(name_cond)
            params.append(f"%{args.name}%")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        limit = getattr(args, 'limit', 50)
        idx += 1
        params.append(limit)

        sql = (
            f"SELECT DISTINCT e.entity_id, e.primary_name, et.type_key, "
            f"e.country, e.region, e.locality, e.status "
            f"FROM entity e JOIN entity_type et ON e.entity_type_id = et.type_id "
            f"{where} ORDER BY e.primary_name LIMIT ${idx}"
        )

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        fmt = getattr(args, 'format', 'table')
        filters_desc = []
        if getattr(args, 'type_key', None):
            filters_desc.append(f"type={args.type_key}")
        if getattr(args, 'category_key', None):
            filters_desc.append(f"category={args.category_key}")
        if getattr(args, 'country', None):
            filters_desc.append(f"country={args.country}")
        if getattr(args, 'region', None):
            filters_desc.append(f"region={args.region}")
        filter_str = f" ({', '.join(filters_desc)})" if filters_desc else ""

        if fmt == 'json':
            print(json.dumps([dict(r) for r in rows], indent=2, default=str))
        elif fmt == 'csv':
            if rows:
                writer = csv.DictWriter(sys.stdout, fieldnames=dict(rows[0]).keys())
                writer.writeheader()
                for r in rows:
                    writer.writerow(dict(r))
        else:
            print(f'SQL Search: "{args.name}"{filter_str}')
            print(LINE)
            for r in rows:
                loc = ' '.join(filter(None, [r['country'], r['region'], r['locality']]))
                print(f"  {r['entity_id']}  {r['primary_name']:<30} {r['type_key']:<12} {loc}")
            print(LINE)
            print(f"  {len(rows)} results")

    async def cmd_search_similar(self, args):
        """Find near-duplicates via MinHash LSH."""
        if not self.dedup:
            print("Dedup index is not enabled. Set ENTITY_DEDUP_ENABLED=true")
            return

        name = getattr(args, 'name', None)
        entity_id = getattr(args, 'entity_id', None)

        if not name and not entity_id:
            print("Must specify --name or --entity-id")
            return

        limit = getattr(args, 'limit', 10)
        min_score = getattr(args, 'min_score', 50.0)

        if entity_id:
            # Find duplicates for an existing entity
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT e.*, et.type_key, et.type_label FROM entity e "
                    "JOIN entity_type et ON e.entity_type_id = et.type_id "
                    "WHERE e.entity_id = $1", entity_id
                )
                if not row:
                    print(f"Entity not found: {entity_id}")
                    return
                entity = dict(row)
                alias_rows = await conn.fetch(
                    "SELECT alias_name FROM entity_alias WHERE entity_id = $1 AND status = 'active'",
                    entity_id
                )
                entity['aliases'] = [dict(a) for a in alias_rows]

            candidates = self.dedup.find_similar(
                entity, limit=limit, min_score=min_score,
            )
            # Exclude the entity itself from results
            candidates = [c for c in candidates if c['entity_id'] != entity_id]
            label = f"Duplicates for {entity_id} ({entity['primary_name']})"
        else:
            candidates = self.dedup.find_similar_by_name(
                name=name,
                country=getattr(args, 'country', None),
                region=getattr(args, 'region', None),
                locality=getattr(args, 'locality', None),
                limit=limit,
                min_score=min_score,
            )
            label = f'Similar to "{name}"'

        fmt = getattr(args, 'format', 'table')
        verbose = getattr(args, 'verbose', False)

        if fmt == 'json':
            print(json.dumps(candidates, indent=2, default=str))
        else:
            print(label)
            print(LINE)
            for c in candidates:
                score_str = f"score={c['score']:.1f} [{c['match_level']}]"
                print(f"  {c['entity_id']}  {c['primary_name']:<30} {score_str}")
                if verbose and c.get('score_detail'):
                    detail = ', '.join(f"{k}={v:.1f}" for k, v in c['score_detail'].items())
                    print(f"    {detail}")
            print(LINE)
            print(f"  {len(candidates)} candidates")

    async def cmd_search_topic(self, args):
        """Semantic topic search via Weaviate."""
        if not self.weaviate:
            print("Weaviate is not enabled. Set ENTITY_WEAVIATE_ENABLED=true")
            return

        query = args.query
        use_hybrid = getattr(args, 'hybrid', False)

        if use_hybrid:
            results = await self.weaviate.search_hybrid(
                query=query,
                alpha=getattr(args, 'alpha', 0.5),
                type_key=getattr(args, 'type_key', None),
                category_key=getattr(args, 'category_key', None),
                country=getattr(args, 'country', None),
                region=getattr(args, 'region', None),
                locality=getattr(args, 'locality', None),
                limit=getattr(args, 'limit', 10),
            )
        else:
            results = await self.weaviate.search_topic(
                query=query,
                type_key=getattr(args, 'type_key', None),
                category_key=getattr(args, 'category_key', None),
                country=getattr(args, 'country', None),
                region=getattr(args, 'region', None),
                locality=getattr(args, 'locality', None),
                latitude=getattr(args, 'latitude', None),
                longitude=getattr(args, 'longitude', None),
                radius_km=getattr(args, 'radius_km', None),
                limit=getattr(args, 'limit', 10),
                min_certainty=getattr(args, 'min_certainty', 0.7),
            )

        fmt = getattr(args, 'format', 'table')
        verbose = getattr(args, 'verbose', False)

        if fmt == 'json':
            print(json.dumps(results, indent=2, default=str))
        else:
            mode = "hybrid" if use_hybrid else "topic"
            print(f'Topic Search ({mode}): "{query}"')
            print(LINE)
            for r in results:
                score_str = f"certainty={r['score']:.4f}, distance={r['distance']:.4f}"
                cats = ','.join(r.get('category_keys', []))
                cat_str = f"  [{cats}]" if cats else ""
                print(f"  {r['entity_id']}  {r['primary_name']:<30} ({score_str}){cat_str}")
                if verbose and r.get('description'):
                    desc = r['description'][:80] + '...' if len(r.get('description', '')) > 80 else r.get('description', '')
                    print(f"    {desc}")
            print(LINE)
            print(f"  {len(results)} results")

    # ==================================================================
    # Data commands
    # ==================================================================

    async def cmd_export(self, args):
        """Export entities to JSON or CSV."""
        conditions = ["e.status = 'active'"]
        params = []
        idx = 0

        if getattr(args, 'type_key', None):
            idx += 1
            conditions.append(f"et.type_key = ${idx}")
            params.append(args.type_key)

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

            if getattr(args, 'include_aliases', False):
                for entity in entities:
                    alias_rows = await conn.fetch(
                        "SELECT alias_name, alias_type FROM entity_alias "
                        "WHERE entity_id = $1 AND status = 'active'",
                        entity['entity_id']
                    )
                    entity['aliases'] = [dict(a) for a in alias_rows]

            if getattr(args, 'include_identifiers', False):
                for entity in entities:
                    ident_rows = await conn.fetch(
                        "SELECT identifier_namespace, identifier_value FROM entity_identifier "
                        "WHERE entity_id = $1 AND status = 'active'",
                        entity['entity_id']
                    )
                    entity['identifiers'] = [dict(i) for i in ident_rows]

        fmt = getattr(args, 'format', 'json')
        output = getattr(args, 'output', None)

        if fmt == 'json':
            content = json.dumps(entities, indent=2, default=str)
        else:
            buf = io.StringIO()
            if entities:
                fieldnames = list(entities[0].keys())
                writer = csv.DictWriter(buf, fieldnames=fieldnames)
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

    async def cmd_types_list(self, args):
        """List entity types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT et.type_key, et.type_label, et.type_description, "
                "COUNT(e.entity_id) AS entity_count "
                "FROM entity_type et "
                "LEFT JOIN entity e ON et.type_id = e.entity_type_id AND e.status = 'active' "
                "GROUP BY et.type_key, et.type_label, et.type_description "
                "ORDER BY et.type_key"
            )

        print("Entity Types")
        print(LINE)
        for r in rows:
            desc = r['type_description'] or ''
            desc_short = desc[:40] + '...' if len(desc) > 40 else desc
            print(f"  {r['type_key']:<15} {r['type_label']:<20} {desc_short:<45} ({r['entity_count']:,} entities)")

    async def cmd_types_add(self, args):
        """Add a new entity type."""
        async with self.pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT 1 FROM entity_type WHERE type_key = $1", args.key
            )
            if existing:
                print(f"Entity type '{args.key}' already exists")
                return
            await conn.execute(
                "INSERT INTO entity_type (type_key, type_label, type_description) VALUES ($1, $2, $3)",
                args.key, args.label, args.description
            )
        print(f"Created entity type: {args.key} ({args.label})")


    # ==================================================================
    # Delete commands
    # ==================================================================

    async def cmd_delete_by_prefix(self, args):
        """Delete all entities (and related data) matching an entity_id prefix."""
        prefix = args.prefix
        dry_run = getattr(args, 'dry_run', False)

        pattern = prefix + '%'

        async with self.pool.acquire() as conn:
            ent_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE entity_id LIKE $1", pattern
            )
            rel_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_relationship "
                "WHERE entity_source LIKE $1 OR entity_destination LIKE $1", pattern
            )
            alias_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_alias WHERE entity_id LIKE $1", pattern
            )
            ident_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_identifier WHERE entity_id LIKE $1", pattern
            )
            cat_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_category_map WHERE entity_id LIKE $1", pattern
            )
            loc_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_location WHERE entity_id LIKE $1", pattern
            )

        print(f"Delete by prefix: '{prefix}'")
        print(LINE)
        print(f"  Entities:      {ent_count:,}")
        print(f"  Relationships: {rel_count:,}")
        print(f"  Aliases:       {alias_count:,}")
        print(f"  Identifiers:   {ident_count:,}")
        print(f"  Categories:    {cat_count:,}")
        print(f"  Locations:     {loc_count:,}")

        if ent_count == 0:
            print("\nNo entities match this prefix.")
            return

        if dry_run:
            print(f"\nDRY RUN — would delete all of the above.")
            return

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                r1 = await conn.execute(
                    "DELETE FROM entity_relationship "
                    "WHERE entity_source LIKE $1 OR entity_destination LIKE $1", pattern
                )
                r2 = await conn.execute(
                    "DELETE FROM entity WHERE entity_id LIKE $1", pattern
                )
                print(f"\nDeleted: {r2}, {r1}")

    # ==================================================================
    # Schema migration
    # ==================================================================

    async def cmd_migrate(self, args):
        """Run pending schema migrations."""
        from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
        schema = EntityRegistrySchema()
        migrations = schema.migrations_sql()

        if not migrations:
            print("No pending migrations.")
            return

        dry_run = getattr(args, 'dry_run', False)

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


# ==================================================================
# Argparse setup
# ==================================================================

def main():
    parser = argparse.ArgumentParser(
        prog='entity_admin',
        description='Entity Registry administration CLI',
    )
    subparsers = parser.add_subparsers(dest='command')

    # stats
    stats_parser = subparsers.add_parser('stats', help='Entity table stats and breakdowns')
    stats_sub = stats_parser.add_subparsers(dest='sub')
    stats_sub.add_parser('types', help='Entity counts per type')
    stats_sub.add_parser('aliases', help='Alias counts and coverage')
    stats_sub.add_parser('categories', help='Category assignment breakdown')
    stats_sub.add_parser('identifiers', help='Identifier namespace breakdown')
    changelog_p = stats_sub.add_parser('changelog', help='Recent change activity')
    changelog_p.add_argument('--days', type=int, default=7, help='Days to look back (default: 7)')

    # dedup
    dedup_parser = subparsers.add_parser('dedup', help='MinHash LSH dedup index')
    dedup_sub = dedup_parser.add_subparsers(dest='sub')
    dedup_sub.add_parser('status', help='Dedup index health and stats')
    sync_p = dedup_sub.add_parser('sync', help='Sync dedup index')
    sync_p.add_argument('--full', action='store_true', help='Full re-sync from PostgreSQL')
    sync_p.add_argument('--entity-id', help='Sync a single entity')
    sync_p.add_argument('--dry-run', action='store_true', help='Report what would change')
    dedup_sub.add_parser('check', help='Verify dedup index matches PostgreSQL')

    # weaviate
    weav_parser = subparsers.add_parser('weaviate', help='Weaviate EntityIndex')
    weav_sub = weav_parser.add_subparsers(dest='sub')
    weav_sub.add_parser('status', help='Weaviate collection status (detailed)')
    weav_sub.add_parser('collections', help='List all Weaviate collections with stats')
    wrebuild_p = weav_sub.add_parser('rebuild', help='Drop, recreate collections and full sync')
    wrebuild_p.add_argument('--batch-size', type=int, default=100, help='Batch size (default: 100)')
    wsync_p = weav_sub.add_parser('sync', help='Sync entities to Weaviate')
    wsync_p.add_argument('--full', action='store_true', help='Full re-sync')
    wsync_p.add_argument('--entity-id', help='Sync a single entity')
    wsync_p.add_argument('--dry-run', action='store_true', help='Report what would change')
    wsync_p.add_argument('--batch-size', type=int, default=100, help='Batch size (default: 100)')
    weav_sub.add_parser('check', help='Verify Weaviate index matches PostgreSQL')

    # search
    search_parser = subparsers.add_parser('search', help='Search entities')
    search_sub = search_parser.add_subparsers(dest='sub')

    sql_p = search_sub.add_parser('sql', help='SQL search (name, type, location)')
    sql_p.add_argument('--name', required=True, help='Name pattern (ILIKE)')
    sql_p.add_argument('--type-key', help='Filter by entity type')
    sql_p.add_argument('--category-key', help='Filter by category')
    sql_p.add_argument('--country', help='Filter by country')
    sql_p.add_argument('--region', help='Filter by region')
    sql_p.add_argument('--locality', help='Filter by city')
    sql_p.add_argument('--include-aliases', action='store_true', help='Also search alias names')
    sql_p.add_argument('--status', default='active', help='Entity status (default: active)')
    sql_p.add_argument('--limit', type=int, default=50, help='Max results (default: 50)')
    sql_p.add_argument('--format', choices=['table', 'json', 'csv'], default='table')

    sim_p = search_sub.add_parser('similar', help='MinHash near-duplicate search')
    sim_p.add_argument('--name', help='Name to search for')
    sim_p.add_argument('--entity-id', help='Find duplicates for this entity')
    sim_p.add_argument('--country', help='Country filter')
    sim_p.add_argument('--region', help='Region filter')
    sim_p.add_argument('--locality', help='Locality filter')
    sim_p.add_argument('--min-score', type=float, default=50.0, help='Min score 0-100 (default: 50)')
    sim_p.add_argument('--limit', type=int, default=10, help='Max results (default: 10)')
    sim_p.add_argument('--verbose', action='store_true', help='Show score detail')
    sim_p.add_argument('--format', choices=['table', 'json'], default='table')

    topic_p = search_sub.add_parser('topic', help='Weaviate semantic topic search')
    topic_p.add_argument('--query', '-q', required=True, help='Free-text query')
    topic_p.add_argument('--type-key', help='Filter by entity type')
    topic_p.add_argument('--category-key', help='Filter by category')
    topic_p.add_argument('--country', help='Country filter')
    topic_p.add_argument('--region', help='Region filter')
    topic_p.add_argument('--locality', help='Locality filter')
    topic_p.add_argument('--latitude', type=float, help='Center latitude for geo range')
    topic_p.add_argument('--longitude', type=float, help='Center longitude for geo range')
    topic_p.add_argument('--radius-km', type=float, help='Radius in km for geo range filter')
    topic_p.add_argument('--min-certainty', type=float, default=0.7, help='Min certainty 0-1 (default: 0.7)')
    topic_p.add_argument('--limit', type=int, default=10, help='Max results (default: 10)')
    topic_p.add_argument('--hybrid', action='store_true', help='Use hybrid search (BM25 + vector)')
    topic_p.add_argument('--alpha', type=float, default=0.5, help='Hybrid alpha (default: 0.5)')
    topic_p.add_argument('--verbose', action='store_true', help='Show descriptions')
    topic_p.add_argument('--format', choices=['table', 'json'], default='table')

    # export
    export_p = subparsers.add_parser('export', help='Export entities')
    export_p.add_argument('--format', choices=['json', 'csv'], default='json', help='Output format')
    export_p.add_argument('--output', '-o', help='Output file (default: stdout)')
    export_p.add_argument('--type-key', help='Filter by entity type')
    export_p.add_argument('--include-aliases', action='store_true', help='Include aliases')
    export_p.add_argument('--include-identifiers', action='store_true', help='Include identifiers')

    # types
    types_parser = subparsers.add_parser('types', help='Entity type management')
    types_sub = types_parser.add_subparsers(dest='sub')
    types_sub.add_parser('list', help='List entity types')
    add_p = types_sub.add_parser('add', help='Add a new entity type')
    add_p.add_argument('--key', required=True, help='Type key (e.g. contractor)')
    add_p.add_argument('--label', required=True, help='Type label (e.g. Contractor)')
    add_p.add_argument('--description', default='', help='Type description')

    # delete
    delete_parser = subparsers.add_parser('delete', help='Delete entities')
    delete_sub = delete_parser.add_subparsers(dest='sub')
    prefix_p = delete_sub.add_parser('by-prefix', help='Delete entities by entity_id prefix')
    prefix_p.add_argument('--prefix', required=True, help="Entity ID prefix (e.g. 'ent_')")
    prefix_p.add_argument('--dry-run', action='store_true', help='Show what would be deleted')

    # migrate
    migrate_p = subparsers.add_parser('migrate', help='Run schema migrations')
    migrate_p.add_argument('--dry-run', action='store_true', help='Show migrations without applying')

    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable DEBUG logging (per-batch details)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    admin = EntityAdmin()
    asyncio.run(admin.run(args))


if __name__ == '__main__':
    main()
