#!/usr/bin/env python3
"""
Bulk import of Entity Registry data from JSONL files.

Two-pass processing:
  Pass 1 — Validate all records (no writes). Abort on any errors.
  Pass 2 — Batch INSERT into PostgreSQL.

See IMPORT_FORMAT.md for file format documentation.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import asyncpg

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Append project root so vitalgraph imports work when running standalone
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(Path(_PROJECT_ROOT) / '.env')

from vitalgraph.entity_registry.entity_registry_id import is_valid_entity_id


# ===================================================================
# Reference-type helpers
# ===================================================================

async def _load_reference_sets(pool: asyncpg.Pool) -> Dict[str, Set[str]]:
    """Load all reference type keys from the database into in-memory sets."""
    async with pool.acquire() as conn:
        et_rows = await conn.fetch("SELECT type_key FROM entity_type")
        cat_rows = await conn.fetch("SELECT category_key FROM category")
        lt_rows = await conn.fetch("SELECT type_key FROM entity_location_type")
        rt_rows = await conn.fetch("SELECT type_key FROM relationship_type")
    return {
        'entity_types': {r['type_key'] for r in et_rows},
        'categories': {r['category_key'] for r in cat_rows},
        'location_types': {r['type_key'] for r in lt_rows},
        'relationship_types': {r['type_key'] for r in rt_rows},
    }


async def _import_reference_file(
    pool: asyncpg.Pool,
    file_path: str,
    table: str,
    key_field: str,
    label_field: str,
    desc_field: str,
    extra_fields: Optional[List[str]] = None,
) -> int:
    """Import a small reference-type JSONL file into the database.

    Uses ON CONFLICT DO NOTHING so it is idempotent.
    Returns number of rows inserted.
    """
    items = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))

    if not items:
        return 0

    inserted = 0
    async with pool.acquire() as conn:
        for item in items:
            key = item[key_field]
            label = item[label_field]
            desc = item.get(desc_field)

            cols = [key_field, label_field, desc_field]
            vals = [key, label, desc]

            if extra_fields:
                for ef in extra_fields:
                    cols.append(ef)
                    vals.append(item.get(ef))

            placeholders = ', '.join(f'${i}' for i in range(1, len(vals) + 1))
            col_str = ', '.join(cols)

            result = await conn.execute(
                f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) "
                f"ON CONFLICT ({key_field}) DO NOTHING",
                *vals,
            )
            if result == 'INSERT 0 1':
                inserted += 1

    return inserted


async def import_entity_types(pool: asyncpg.Pool, path: str) -> int:
    return await _import_reference_file(
        pool, path, 'entity_type', 'type_key', 'type_label', 'type_description')


async def import_categories(pool: asyncpg.Pool, path: str) -> int:
    return await _import_reference_file(
        pool, path, 'category', 'category_key', 'category_label', 'category_description')


async def import_location_types(pool: asyncpg.Pool, path: str) -> int:
    return await _import_reference_file(
        pool, path, 'entity_location_type', 'type_key', 'type_label', 'type_description')


async def import_relationship_types(pool: asyncpg.Pool, path: str) -> int:
    return await _import_reference_file(
        pool, path, 'relationship_type', 'type_key', 'type_label', 'type_description',
        extra_fields=['inverse_key'])


# ===================================================================
# Validation error collector
# ===================================================================

class ValidationErrors:
    """Collects validation errors with line numbers."""

    def __init__(self):
        self.errors: List[Dict[str, Any]] = []

    def add(self, file: str, line: int, field: str, error: str,
            value: Any = None):
        entry: Dict[str, Any] = {
            'line': line, 'file': file, 'field': field, 'error': error,
        }
        if value is not None:
            entry['value'] = str(value)[:200]
        self.errors.append(entry)

    @property
    def count(self) -> int:
        return len(self.errors)

    def write_log(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            for e in self.errors:
                f.write(json.dumps(e, ensure_ascii=False))
                f.write('\n')

    def print_summary(self):
        if not self.errors:
            return
        # Group by error type
        by_error: Dict[str, List[int]] = {}
        for e in self.errors:
            key = f"{e['field']}: {e['error']}"
            by_error.setdefault(key, []).append(e['line'])
        for key, lines in by_error.items():
            sample = ', '.join(str(ln) for ln in lines[:5])
            suffix = f' ... (+{len(lines) - 5} more)' if len(lines) > 5 else ''
            logger.error(f"  {key} — line {sample}{suffix}")


# ===================================================================
# Pass 1 — Validation
# ===================================================================

async def validate_entities(
    pool: asyncpg.Pool,
    entity_path: str,
    refs: Dict[str, Set[str]],
    errors: ValidationErrors,
    id_check_batch: int = 1000,
) -> Tuple[int, Set[str]]:
    """Stream-scan entity file. Returns (line_count, set_of_entity_ids).

    Entity IDs are accumulated in a set (for duplicate detection within file)
    and checked against the database in batches.
    """
    fname = os.path.basename(entity_path)
    seen_ids: Set[str] = set()
    id_batch: List[Tuple[int, str]] = []  # (line_no, entity_id)
    line_count = 0

    async def _flush_id_batch():
        """Check a batch of entity IDs against the database."""
        if not id_batch:
            return
        ids = [eid for _, eid in id_batch]
        async with pool.acquire() as conn:
            existing = await conn.fetch(
                "SELECT entity_id FROM entity WHERE entity_id = ANY($1::text[])",
                ids,
            )
        existing_set = {r['entity_id'] for r in existing}
        for ln, eid in id_batch:
            if eid in existing_set:
                errors.add(fname, ln, 'entity_id',
                           'already exists in database', eid)
        id_batch.clear()

    with open(entity_path, 'r', encoding='utf-8') as f:
        for line_no, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            line_count += 1

            # Parse JSON
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError as e:
                errors.add(fname, line_no, 'json', f'malformed JSON: {e}')
                continue

            if not isinstance(obj, dict):
                errors.add(fname, line_no, 'json', 'line is not a JSON object')
                continue

            # entity_id — required
            eid = obj.get('entity_id')
            if not eid:
                errors.add(fname, line_no, 'entity_id', 'missing required field')
            elif not is_valid_entity_id(eid):
                errors.add(fname, line_no, 'entity_id',
                           'invalid format (expected 1-4 alphanum prefix + _ + 10 alphanum)', eid)
            elif eid in seen_ids:
                errors.add(fname, line_no, 'entity_id',
                           'duplicate entity_id in file', eid)
            else:
                seen_ids.add(eid)
                id_batch.append((line_no, eid))
                if len(id_batch) >= id_check_batch:
                    await _flush_id_batch()

            # type_key — required
            tk = obj.get('type_key')
            if not tk:
                errors.add(fname, line_no, 'type_key', 'missing required field')
            elif tk not in refs['entity_types']:
                errors.add(fname, line_no, 'type_key',
                           'unknown entity type', tk)

            # primary_name — required
            if not obj.get('primary_name'):
                errors.add(fname, line_no, 'primary_name', 'missing required field')

            # categories
            for cat in obj.get('categories', []):
                if cat not in refs['categories']:
                    errors.add(fname, line_no, 'categories',
                               'unknown category_key', cat)

            # locations
            for i, loc in enumerate(obj.get('locations', [])):
                lt = loc.get('location_type')
                if not lt:
                    errors.add(fname, line_no, f'locations[{i}].location_type',
                               'missing required field')
                elif lt not in refs['location_types']:
                    errors.add(fname, line_no, f'locations[{i}].location_type',
                               'unknown location type', lt)

                # coordinate validation
                lat = loc.get('latitude')
                lon = loc.get('longitude')
                if lat is not None and (lat < -90 or lat > 90):
                    errors.add(fname, line_no, f'locations[{i}].latitude',
                               'out of range (-90..90)', lat)
                if lon is not None and (lon < -180 or lon > 180):
                    errors.add(fname, line_no, f'locations[{i}].longitude',
                               'out of range (-180..180)', lon)

            # entity-level coordinates
            lat = obj.get('latitude')
            lon = obj.get('longitude')
            if lat is not None and (lat < -90 or lat > 90):
                errors.add(fname, line_no, 'latitude',
                           'out of range (-90..90)', lat)
            if lon is not None and (lon < -180 or lon > 180):
                errors.add(fname, line_no, 'longitude',
                           'out of range (-180..180)', lon)

            # Progress
            if line_count % 100_000 == 0:
                logger.info(f"  Validated {line_count:,} entity lines ...")

    # Flush remaining ID batch
    await _flush_id_batch()

    return line_count, seen_ids


def validate_relationships(
    rel_path: str,
    refs: Dict[str, Set[str]],
    errors: ValidationErrors,
) -> int:
    """Stream-scan relationship file (sync — no DB calls needed).

    Returns line count.
    """
    fname = os.path.basename(rel_path)
    line_count = 0

    with open(rel_path, 'r', encoding='utf-8') as f:
        for line_no, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            line_count += 1

            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError as e:
                errors.add(fname, line_no, 'json', f'malformed JSON: {e}')
                continue

            if not isinstance(obj, dict):
                errors.add(fname, line_no, 'json', 'line is not a JSON object')
                continue

            # source — required, must be valid entity ID format
            src = obj.get('source')
            if not src:
                errors.add(fname, line_no, 'source', 'missing required field')
            elif not is_valid_entity_id(src):
                errors.add(fname, line_no, 'source',
                           'invalid entity ID format', src)

            # destination — required
            dst = obj.get('destination')
            if not dst:
                errors.add(fname, line_no, 'destination', 'missing required field')
            elif not is_valid_entity_id(dst):
                errors.add(fname, line_no, 'destination',
                           'invalid entity ID format', dst)

            # type_key — required
            tk = obj.get('type_key')
            if not tk:
                errors.add(fname, line_no, 'type_key', 'missing required field')
            elif tk not in refs['relationship_types']:
                errors.add(fname, line_no, 'type_key',
                           'unknown relationship type', tk)

            if line_count % 100_000 == 0:
                logger.info(f"  Validated {line_count:,} relationship lines ...")

    return line_count


# ===================================================================
# Pass 2 — Batch inserts
# ===================================================================

async def _resolve_type_id_maps(pool: asyncpg.Pool) -> Dict[str, Dict[str, int]]:
    """Build key→id maps for all reference tables."""
    async with pool.acquire() as conn:
        et = await conn.fetch("SELECT type_id, type_key FROM entity_type")
        cat = await conn.fetch("SELECT category_id, category_key FROM category")
        lt = await conn.fetch(
            "SELECT location_type_id, type_key FROM entity_location_type")
        rt = await conn.fetch(
            "SELECT relationship_type_id, type_key FROM relationship_type")
    return {
        'entity_types': {r['type_key']: r['type_id'] for r in et},
        'categories': {r['category_key']: r['category_id'] for r in cat},
        'location_types': {r['type_key']: r['location_type_id'] for r in lt},
        'relationship_types': {r['type_key']: r['relationship_type_id'] for r in rt},
    }


def _none_if_empty(val):
    """Return None for empty strings so they are stored as NULL."""
    if val is None or val == '':
        return None
    return val


def _parse_date(val):
    """Parse a date string to a date object, or return None."""
    if not val:
        return None
    if isinstance(val, str):
        return datetime.fromisoformat(val).date()
    return val


async def insert_entities(
    pool: asyncpg.Pool,
    entity_path: str,
    type_maps: Dict[str, Dict[str, int]],
    batch_size: int = 100,
    created_by: str = 'bulk_import',
) -> int:
    """Pass 2: stream entity file and batch-insert into PostgreSQL.

    Returns number of entities inserted.
    """
    et_map = type_maps['entity_types']
    cat_map = type_maps['categories']
    lt_map = type_maps['location_types']

    total = 0
    batch: List[Dict[str, Any]] = []

    async def _flush_batch():
        nonlocal total
        if not batch:
            return
        async with pool.acquire() as conn:
            async with conn.transaction():
                for obj in batch:
                    eid = obj['entity_id']
                    type_id = et_map[obj['type_key']]
                    metadata_json = json.dumps(obj.get('metadata') or {})

                    await conn.execute(
                        "INSERT INTO entity "
                        "(entity_id, entity_type_id, primary_name, description, "
                        "country, region, locality, website, latitude, longitude, "
                        "metadata, created_by, notes) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13)",
                        eid, type_id,
                        obj['primary_name'],
                        _none_if_empty(obj.get('description')),
                        _none_if_empty(obj.get('country')),
                        _none_if_empty(obj.get('region')),
                        _none_if_empty(obj.get('locality')),
                        _none_if_empty(obj.get('website')),
                        obj.get('latitude'),
                        obj.get('longitude'),
                        metadata_json,
                        _none_if_empty(obj.get('created_by', created_by)),
                        _none_if_empty(obj.get('notes')),
                    )

                    # Aliases
                    for alias in obj.get('aliases', []):
                        await conn.execute(
                            "INSERT INTO entity_alias "
                            "(entity_id, alias_name, alias_type, is_primary, "
                            "created_by, notes) "
                            "VALUES ($1,$2,$3,$4,$5,$6)",
                            eid, alias['alias_name'],
                            alias.get('alias_type', 'aka'),
                            alias.get('is_primary', False),
                            obj.get('created_by', created_by),
                            alias.get('notes'),
                        )

                    # Identifiers
                    for ident in obj.get('identifiers', []):
                        await conn.execute(
                            "INSERT INTO entity_identifier "
                            "(entity_id, identifier_namespace, identifier_value, "
                            "is_primary, created_by, notes) "
                            "VALUES ($1,$2,$3,$4,$5,$6)",
                            eid, ident['namespace'], ident['value'],
                            ident.get('is_primary', False),
                            obj.get('created_by', created_by),
                            ident.get('notes'),
                        )

                    # Categories
                    for cat_key in obj.get('categories', []):
                        cat_id = cat_map[cat_key]
                        await conn.execute(
                            "INSERT INTO entity_category_map "
                            "(entity_id, category_id, created_by) "
                            "VALUES ($1,$2,$3) "
                            "ON CONFLICT (entity_id, category_id) DO NOTHING",
                            eid, cat_id,
                            obj.get('created_by', created_by),
                        )

                    # Locations
                    for loc in obj.get('locations', []):
                        lt_id = lt_map[loc['location_type']]
                        await conn.execute(
                            "INSERT INTO entity_location "
                            "(entity_id, location_type_id, location_name, "
                            "description, address_line_1, address_line_2, "
                            "locality, admin_area_2, admin_area_1, "
                            "country, country_code, postal_code, "
                            "formatted_address, latitude, longitude, "
                            "timezone, google_place_id, external_location_id, "
                            "effective_from, effective_to, is_primary, "
                            "created_by, notes) "
                            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,"
                            "$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)",
                            eid, lt_id,
                            loc.get('location_name'),
                            loc.get('description'),
                            loc.get('address_line_1'),
                            loc.get('address_line_2'),
                            loc.get('locality'),
                            loc.get('admin_area_2'),
                            loc.get('admin_area_1'),
                            loc.get('country'),
                            loc.get('country_code'),
                            loc.get('postal_code'),
                            loc.get('formatted_address'),
                            loc.get('latitude'),
                            loc.get('longitude'),
                            loc.get('timezone'),
                            loc.get('google_place_id'),
                            loc.get('external_location_id'),
                            _parse_date(loc.get('effective_from')),
                            _parse_date(loc.get('effective_to')),
                            loc.get('is_primary', False),
                            obj.get('created_by', created_by),
                            loc.get('notes'),
                        )

        total += len(batch)
        logger.info(f"  Entity batch committed: {len(batch)} rows (total {total:,})")
        batch.clear()

    with open(entity_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            obj = json.loads(raw_line)
            batch.append(obj)
            if len(batch) >= batch_size:
                await _flush_batch()
                if total % 1_000 == 0:
                    logger.info(f"  Inserted {total:,} entities ...")

    # Final partial batch
    await _flush_batch()

    return total


async def insert_relationships(
    pool: asyncpg.Pool,
    rel_path: str,
    type_maps: Dict[str, Dict[str, int]],
    batch_size: int = 100,
    created_by: str = 'bulk_import',
) -> int:
    """Pass 2: stream relationship file and batch-insert.

    Returns number of relationships inserted.
    """
    rt_map = type_maps['relationship_types']

    total = 0
    batch: List[Dict[str, Any]] = []

    async def _flush_batch():
        nonlocal total
        if not batch:
            return
        async with pool.acquire() as conn:
            async with conn.transaction():
                for obj in batch:
                    rt_id = rt_map[obj['type_key']]
                    start_dt = obj.get('start_datetime')
                    if isinstance(start_dt, str) and start_dt:
                        start_dt = datetime.fromisoformat(start_dt)
                    else:
                        start_dt = None

                    end_dt = obj.get('end_datetime')
                    if isinstance(end_dt, str) and end_dt:
                        end_dt = datetime.fromisoformat(end_dt)
                    else:
                        end_dt = None

                    await conn.execute(
                        "INSERT INTO entity_relationship "
                        "(entity_source, entity_destination, relationship_type_id, "
                        "description, start_datetime, end_datetime, "
                        "created_by, notes) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                        obj['source'], obj['destination'], rt_id,
                        _none_if_empty(obj.get('description')),
                        start_dt,
                        end_dt,
                        _none_if_empty(obj.get('created_by', created_by)),
                        _none_if_empty(obj.get('notes')),
                    )
        total += len(batch)
        logger.info(f"  Relationship batch committed: {len(batch)} rows (total {total:,})")
        batch.clear()

    with open(rel_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            obj = json.loads(raw_line)
            batch.append(obj)
            if len(batch) >= batch_size:
                await _flush_batch()
                if total % 1_000 == 0:
                    logger.info(f"  Inserted {total:,} relationships ...")

    await _flush_batch()

    return total


# ===================================================================
# Changelog
# ===================================================================

async def write_changelog_entry(
    pool: asyncpg.Pool,
    entity_path: str,
    rel_path: Optional[str],
    entities_imported: int,
    relationships_imported: int,
    created_by: str = 'bulk_import',
):
    """Write a single changelog entry for the entire import run."""
    detail = {
        'action': 'bulk_import',
        'entity_file': entity_path,
        'entities_imported': entities_imported,
        'relationships_imported': relationships_imported,
    }
    if rel_path:
        detail['relationship_file'] = rel_path

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO entity_change_log "
            "(entity_id, change_type, change_detail, changed_by) "
            "VALUES (NULL, $1, $2::jsonb, $3)",
            'bulk_import',
            json.dumps(detail),
            created_by,
        )


# ===================================================================
# Main orchestrator
# ===================================================================

async def run_import(args):
    from vitalgraph.config.config_loader import VitalGraphConfig
    config = VitalGraphConfig()
    db_config = config.get_database_config()

    pool = await asyncpg.create_pool(
        host=db_config.get('host', 'localhost'),
        port=int(db_config.get('port', 5432)),
        database=db_config.get('database', 'vitalgraph'),
        user=db_config.get('username', 'postgres'),
        password=db_config.get('password', ''),
        min_size=1,
        max_size=5,
    )

    errors = ValidationErrors()
    t0 = time.time()

    try:
        # ---------------------------------------------------------------
        # Step 0: Import reference type files (if provided)
        # ---------------------------------------------------------------
        if args.entity_types:
            n = await import_entity_types(pool, args.entity_types)
            logger.info(f"Imported {n} new entity types from {args.entity_types}")

        if args.categories:
            n = await import_categories(pool, args.categories)
            logger.info(f"Imported {n} new categories from {args.categories}")

        if args.location_types:
            n = await import_location_types(pool, args.location_types)
            logger.info(f"Imported {n} new location types from {args.location_types}")

        if args.relationship_types:
            n = await import_relationship_types(pool, args.relationship_types)
            logger.info(f"Imported {n} new relationship types from {args.relationship_types}")

        # ---------------------------------------------------------------
        # Step 1: Load reference sets (DB + any newly imported types)
        # ---------------------------------------------------------------
        refs = await _load_reference_sets(pool)
        logger.info(
            f"Reference types loaded: "
            f"{len(refs['entity_types'])} entity types, "
            f"{len(refs['categories'])} categories, "
            f"{len(refs['location_types'])} location types, "
            f"{len(refs['relationship_types'])} relationship types"
        )

        # ---------------------------------------------------------------
        # Pass 1: Validation
        # ---------------------------------------------------------------
        logger.info("Pass 1 — Validation (no writes)")

        entity_count = 0
        entity_ids: Set[str] = set()
        if args.entities:
            entity_count, entity_ids = await validate_entities(
                pool, args.entities, refs, errors,
                id_check_batch=1000,
            )
            logger.info(f"  Entities: {entity_count:,} lines scanned")

        rel_count = 0
        if args.relationships:
            rel_count = validate_relationships(
                args.relationships, refs, errors,
            )
            logger.info(f"  Relationships: {rel_count:,} lines scanned")

        if errors.count > 0:
            logger.error(f"Validation FAILED — {errors.count} error(s). "
                         f"No data was written.")
            errors.print_summary()
            if args.error_log:
                errors.write_log(args.error_log)
                logger.info(f"Errors written to: {args.error_log}")
            await pool.close()
            sys.exit(1)

        logger.info("  Validation passed.")

        if args.dry_run:
            elapsed = time.time() - t0
            logger.info(
                f"Dry run complete in {elapsed:.1f}s. "
                f"{entity_count:,} entities, {rel_count:,} relationships validated."
            )
            await pool.close()
            return

        # ---------------------------------------------------------------
        # Pass 2: Batch inserts
        # ---------------------------------------------------------------
        logger.info(f"Pass 2 — Insert (batch size {args.batch_size})")

        type_maps = await _resolve_type_id_maps(pool)

        entities_inserted = 0
        if args.entities:
            entities_inserted = await insert_entities(
                pool, args.entities, type_maps,
                batch_size=args.batch_size,
            )
            logger.info(f"  Entities inserted: {entities_inserted:,}")

        relationships_inserted = 0
        if args.relationships:
            relationships_inserted = await insert_relationships(
                pool, args.relationships, type_maps,
                batch_size=args.batch_size,
            )
            logger.info(f"  Relationships inserted: {relationships_inserted:,}")

        # ---------------------------------------------------------------
        # Changelog
        # ---------------------------------------------------------------
        await write_changelog_entry(
            pool,
            entity_path=args.entities or '',
            rel_path=args.relationships,
            entities_imported=entities_inserted,
            relationships_imported=relationships_inserted,
        )

        elapsed = time.time() - t0
        logger.info(
            f"Import complete in {elapsed:.1f}s. "
            f"{entities_inserted:,} entities, "
            f"{relationships_inserted:,} relationships."
        )

    finally:
        await pool.close()


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        prog='entity_import_jsonl',
        description='Bulk import Entity Registry data from JSONL files',
    )

    # Data files
    parser.add_argument('--entities', '-e',
                        help='Path to entity JSONL file')
    parser.add_argument('--relationships', '-r',
                        help='Path to relationship JSONL file')

    # Reference type files
    parser.add_argument('--entity-types',
                        help='Path to entity types JSONL file')
    parser.add_argument('--categories',
                        help='Path to categories JSONL file')
    parser.add_argument('--location-types',
                        help='Path to location types JSONL file')
    parser.add_argument('--relationship-types',
                        help='Path to relationship types JSONL file')

    # Options
    parser.add_argument('--batch-size', type=int, default=100,
                        help='Records per INSERT batch (default: 100)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run validation only (Pass 1), no writes')
    parser.add_argument('--error-log',
                        help='Path to write validation errors (JSONL)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable DEBUG logging (per-batch details)')

    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    asyncio.run(run_import(args))


if __name__ == '__main__':
    main()
