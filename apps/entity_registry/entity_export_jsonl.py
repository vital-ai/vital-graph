#!/usr/bin/env python3
"""
Entity Registry JSONL Exporter.

Exports entities (with aliases, identifiers, categories, locations) and
relationships from PostgreSQL to JSONL files suitable for bulk import.

Usage:
    python entity_registry/entity_export_jsonl.py --entities entities.jsonl
    python entity_registry/entity_export_jsonl.py --entities entities.jsonl --relationships relationships.jsonl
    python entity_registry/entity_export_jsonl.py --entities entities.jsonl --type-key business
    python entity_registry/entity_export_jsonl.py --entities - (stdout)
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to Python path and load .env
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import asyncpg

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def json_serializer(obj):
    """JSON serializer for types not handled by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


async def export_entities(
    pool: asyncpg.Pool,
    output_path: Optional[str] = None,
    type_key: Optional[str] = None,
    country: Optional[str] = None,
    status_filter: str = 'active',
    include_entity_id: bool = True,
) -> int:
    """Export entities with all nested data to JSONL.

    Returns:
        Number of entities exported.
    """
    # Build lookup maps
    async with pool.acquire() as conn:
        # entity_type: type_id -> type_key
        type_rows = await conn.fetch("SELECT type_id, type_key FROM entity_type")
        type_map = {r['type_id']: r['type_key'] for r in type_rows}

        # category: category_id -> category_key
        cat_rows = await conn.fetch("SELECT category_id, category_key FROM category")
        cat_map = {r['category_id']: r['category_key'] for r in cat_rows}

        # location_type: location_type_id -> type_key
        loc_type_rows = await conn.fetch(
            "SELECT location_type_id, type_key FROM entity_location_type"
        )
        loc_type_map = {r['location_type_id']: r['type_key'] for r in loc_type_rows}

    # Build entity query with optional filters
    conditions = [f"e.status = '{status_filter}'"]
    params = []
    idx = 0

    if type_key:
        idx += 1
        conditions.append(f"et.type_key = ${idx}")
        params.append(type_key)

    if country:
        idx += 1
        conditions.append(f"e.country = ${idx}")
        params.append(country)

    where = "WHERE " + " AND ".join(conditions)

    entity_sql = (
        f"SELECT e.entity_id, e.entity_type_id, e.primary_name, e.description, "
        f"e.country, e.region, e.locality, e.website, e.latitude, e.longitude, "
        f"e.metadata, e.created_by, e.notes "
        f"FROM entity e "
        f"JOIN entity_type et ON et.type_id = e.entity_type_id "
        f"{where} ORDER BY e.entity_id"
    )

    # Open output
    if output_path and output_path != '-':
        out = open(output_path, 'w', encoding='utf-8')
    else:
        out = sys.stdout

    count = 0
    try:
        async with pool.acquire() as conn:
            entities = await conn.fetch(entity_sql, *params)

            for row in entities:
                eid = row['entity_id']
                entity: Dict[str, Any] = {}

                if include_entity_id:
                    entity['entity_id'] = eid

                entity['type_key'] = type_map.get(row['entity_type_id'], 'unknown')
                entity['primary_name'] = row['primary_name']

                # Optional scalar fields (omit nulls for cleaner output)
                for field in ('description', 'country', 'region', 'locality',
                              'website', 'latitude', 'longitude', 'notes'):
                    val = row[field]
                    if val is not None:
                        entity[field] = val

                if row['metadata'] and row['metadata'] != '{}':
                    meta = row['metadata']
                    if isinstance(meta, str):
                        meta = json.loads(meta)
                    if meta:
                        entity['metadata'] = meta

                if row['created_by']:
                    entity['created_by'] = row['created_by']

                # Aliases
                alias_rows = await conn.fetch(
                    "SELECT alias_name, alias_type, is_primary, notes "
                    "FROM entity_alias WHERE entity_id = $1 AND status = 'active' "
                    "ORDER BY alias_id", eid
                )
                if alias_rows:
                    aliases = []
                    for a in alias_rows:
                        alias: Dict[str, Any] = {
                            'alias_name': a['alias_name'],
                            'alias_type': a['alias_type'],
                        }
                        if a['is_primary']:
                            alias['is_primary'] = True
                        if a['notes']:
                            alias['notes'] = a['notes']
                        aliases.append(alias)
                    entity['aliases'] = aliases

                # Identifiers
                ident_rows = await conn.fetch(
                    "SELECT identifier_namespace, identifier_value, is_primary, notes "
                    "FROM entity_identifier WHERE entity_id = $1 AND status = 'active' "
                    "ORDER BY identifier_id", eid
                )
                if ident_rows:
                    identifiers = []
                    for i in ident_rows:
                        ident: Dict[str, Any] = {
                            'namespace': i['identifier_namespace'],
                            'value': i['identifier_value'],
                        }
                        if i['is_primary']:
                            ident['is_primary'] = True
                        if i['notes']:
                            ident['notes'] = i['notes']
                        identifiers.append(ident)
                    entity['identifiers'] = identifiers

                # Categories
                cat_rows_ent = await conn.fetch(
                    "SELECT category_id FROM entity_category_map "
                    "WHERE entity_id = $1 AND status = 'active' "
                    "ORDER BY entity_category_id", eid
                )
                if cat_rows_ent:
                    categories = [
                        cat_map.get(c['category_id'], f"unknown_{c['category_id']}")
                        for c in cat_rows_ent
                    ]
                    entity['categories'] = categories

                # Locations
                loc_rows = await conn.fetch(
                    "SELECT location_type_id, location_name, description, "
                    "address_line_1, address_line_2, locality, admin_area_2, "
                    "admin_area_1, country, country_code, postal_code, "
                    "formatted_address, latitude, longitude, timezone, "
                    "google_place_id, external_location_id, "
                    "effective_from, effective_to, is_primary, notes "
                    "FROM entity_location WHERE entity_id = $1 AND status = 'active' "
                    "ORDER BY location_id", eid
                )
                if loc_rows:
                    locations = []
                    for loc in loc_rows:
                        location: Dict[str, Any] = {
                            'location_type': loc_type_map.get(
                                loc['location_type_id'],
                                f"unknown_{loc['location_type_id']}"
                            ),
                        }
                        for lf in ('location_name', 'description',
                                   'address_line_1', 'address_line_2',
                                   'locality', 'admin_area_2', 'admin_area_1',
                                   'country', 'country_code', 'postal_code',
                                   'formatted_address', 'latitude', 'longitude',
                                   'timezone', 'google_place_id',
                                   'external_location_id',
                                   'effective_from', 'effective_to', 'notes'):
                            val = loc[lf]
                            if val is not None:
                                location[lf] = val
                        if loc['is_primary']:
                            location['is_primary'] = True
                        locations.append(location)
                    entity['locations'] = locations

                # Write JSONL line
                out.write(json.dumps(entity, default=json_serializer, ensure_ascii=False))
                out.write('\n')
                count += 1

    finally:
        if out is not sys.stdout:
            out.close()

    return count


async def _write_jsonl(rows: List[Dict[str, Any]], output_path: Optional[str]) -> int:
    """Write a list of dicts to JSONL. Returns count."""
    if output_path and output_path != '-':
        out = open(output_path, 'w', encoding='utf-8')
    else:
        out = sys.stdout
    count = 0
    try:
        for obj in rows:
            out.write(json.dumps(obj, default=json_serializer, ensure_ascii=False))
            out.write('\n')
            count += 1
    finally:
        if out is not sys.stdout:
            out.close()
    return count


async def export_entity_types(
    pool: asyncpg.Pool,
    output_path: Optional[str] = None,
) -> int:
    """Export entity types to JSONL."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT type_key, type_label, type_description "
            "FROM entity_type ORDER BY type_id"
        )
    items = []
    for r in rows:
        item: Dict[str, Any] = {
            'type_key': r['type_key'],
            'type_label': r['type_label'],
        }
        if r['type_description']:
            item['type_description'] = r['type_description']
        items.append(item)
    return await _write_jsonl(items, output_path)


async def export_categories(
    pool: asyncpg.Pool,
    output_path: Optional[str] = None,
) -> int:
    """Export categories to JSONL."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT category_key, category_label, category_description "
            "FROM category ORDER BY category_id"
        )
    items = []
    for r in rows:
        item: Dict[str, Any] = {
            'category_key': r['category_key'],
            'category_label': r['category_label'],
        }
        if r['category_description']:
            item['category_description'] = r['category_description']
        items.append(item)
    return await _write_jsonl(items, output_path)


async def export_location_types(
    pool: asyncpg.Pool,
    output_path: Optional[str] = None,
) -> int:
    """Export location types to JSONL."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT type_key, type_label, type_description "
            "FROM entity_location_type ORDER BY location_type_id"
        )
    items = []
    for r in rows:
        item: Dict[str, Any] = {
            'type_key': r['type_key'],
            'type_label': r['type_label'],
        }
        if r['type_description']:
            item['type_description'] = r['type_description']
        items.append(item)
    return await _write_jsonl(items, output_path)


async def export_relationship_types(
    pool: asyncpg.Pool,
    output_path: Optional[str] = None,
) -> int:
    """Export relationship types to JSONL."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT type_key, type_label, type_description, inverse_key "
            "FROM relationship_type ORDER BY relationship_type_id"
        )
    items = []
    for r in rows:
        item: Dict[str, Any] = {
            'type_key': r['type_key'],
            'type_label': r['type_label'],
        }
        if r['type_description']:
            item['type_description'] = r['type_description']
        if r['inverse_key']:
            item['inverse_key'] = r['inverse_key']
        items.append(item)
    return await _write_jsonl(items, output_path)


async def export_relationships(
    pool: asyncpg.Pool,
    output_path: Optional[str] = None,
) -> int:
    """Export relationships to JSONL.

    Returns:
        Number of relationships exported.
    """
    # relationship_type lookup
    async with pool.acquire() as conn:
        rt_rows = await conn.fetch(
            "SELECT relationship_type_id, type_key FROM relationship_type"
        )
        rt_map = {r['relationship_type_id']: r['type_key'] for r in rt_rows}

    if output_path and output_path != '-':
        out = open(output_path, 'w', encoding='utf-8')
    else:
        out = sys.stdout

    count = 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT entity_source, entity_destination, relationship_type_id, "
                "description, start_datetime, end_datetime, created_by, notes "
                "FROM entity_relationship WHERE status = 'active' "
                "ORDER BY relationship_id"
            )

            for row in rows:
                rel: Dict[str, Any] = {
                    'source': row['entity_source'],
                    'destination': row['entity_destination'],
                    'type_key': rt_map.get(
                        row['relationship_type_id'],
                        f"unknown_{row['relationship_type_id']}"
                    ),
                }
                for field in ('description', 'start_datetime', 'end_datetime',
                              'created_by', 'notes'):
                    val = row[field]
                    if val is not None:
                        rel[field] = val

                out.write(json.dumps(rel, default=json_serializer, ensure_ascii=False))
                out.write('\n')
                count += 1

    finally:
        if out is not sys.stdout:
            out.close()

    return count


async def export_vectors(
    entity_vectors_path: Optional[str] = None,
    location_vectors_path: Optional[str] = None,
) -> int:
    """Export vectors from Weaviate to JSONL files.

    Format:
      entity_vectors.jsonl:   {"entity_id": "ent_xxx", "vector": [0.1, ...]}
      location_vectors.jsonl: {"location_id": 123, "vector": [0.1, ...]}

    Returns total number of vectors exported.
    """
    from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex

    weaviate_index = await EntityWeaviateIndex.from_env()
    if not weaviate_index:
        logger.error("Cannot connect to Weaviate — skipping vector export")
        return 0

    total = 0
    try:
        # Export entity vectors
        if entity_vectors_path:
            out = open(entity_vectors_path, 'w', encoding='utf-8')
            count = 0
            cursor_uuid = None
            while True:
                kwargs = {"limit": 1000, "include_vector": True}
                if cursor_uuid:
                    kwargs["after"] = cursor_uuid
                response = await weaviate_index.collection.query.fetch_objects(**kwargs)
                if not response.objects:
                    break
                for obj in response.objects:
                    eid = obj.properties.get('entity_id')
                    vec = obj.vector
                    if isinstance(vec, dict):
                        vec = vec.get('default', [])
                    if eid and vec:
                        record = {'entity_id': eid, 'vector': list(vec)}
                        out.write(json.dumps(record))
                        out.write('\n')
                        count += 1
                    cursor_uuid = obj.uuid
            out.close()
            logger.info(f"Exported {count:,} entity vectors to {entity_vectors_path}")
            total += count

        # Export location vectors
        if location_vectors_path:
            out = open(location_vectors_path, 'w', encoding='utf-8')
            count = 0
            cursor_uuid = None
            while True:
                kwargs = {"limit": 1000, "include_vector": True}
                if cursor_uuid:
                    kwargs["after"] = cursor_uuid
                response = await weaviate_index.location_collection.query.fetch_objects(**kwargs)
                if not response.objects:
                    break
                for obj in response.objects:
                    lid = obj.properties.get('location_id')
                    vec = obj.vector
                    if isinstance(vec, dict):
                        vec = vec.get('default', [])
                    if lid and vec:
                        try:
                            lid = int(lid)
                        except (ValueError, TypeError):
                            pass
                        record = {'location_id': lid, 'vector': list(vec)}
                        out.write(json.dumps(record))
                        out.write('\n')
                        count += 1
                    cursor_uuid = obj.uuid
            out.close()
            logger.info(f"Exported {count:,} location vectors to {location_vectors_path}")
            total += count
    finally:
        await weaviate_index.close()

    return total


async def main(args):
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

    try:
        # Reference tables
        if args.entity_types:
            count = await export_entity_types(pool, args.entity_types)
            if args.entity_types != '-':
                logger.info(f"Exported {count:,} entity types to {args.entity_types}")

        if args.categories:
            count = await export_categories(pool, args.categories)
            if args.categories != '-':
                logger.info(f"Exported {count:,} categories to {args.categories}")

        if args.location_types:
            count = await export_location_types(pool, args.location_types)
            if args.location_types != '-':
                logger.info(f"Exported {count:,} location types to {args.location_types}")

        if args.relationship_types:
            count = await export_relationship_types(pool, args.relationship_types)
            if args.relationship_types != '-':
                logger.info(f"Exported {count:,} relationship types to {args.relationship_types}")

        # Data tables
        if args.entities:
            count = await export_entities(
                pool,
                output_path=args.entities,
                type_key=getattr(args, 'type_key', None),
                country=getattr(args, 'country', None),
                status_filter=getattr(args, 'status', 'active'),
                include_entity_id=not getattr(args, 'no_entity_id', False),
            )
            if args.entities != '-':
                logger.info(f"Exported {count:,} entities to {args.entities}")

        if args.relationships:
            count = await export_relationships(
                pool,
                output_path=args.relationships,
            )
            if args.relationships != '-':
                logger.info(f"Exported {count:,} relationships to {args.relationships}")

        # Vector exports (from Weaviate)
        if args.entity_vectors or args.location_vectors:
            count = await export_vectors(
                entity_vectors_path=args.entity_vectors,
                location_vectors_path=args.location_vectors,
            )
            logger.info(f"Exported {count:,} vectors")

        # Convenience: --all
        if getattr(args, 'all', False):
            out_dir = Path(args.all)
            out_dir.mkdir(parents=True, exist_ok=True)
            for name, fn in [
                ('entity_types.jsonl', export_entity_types),
                ('categories.jsonl', export_categories),
                ('location_types.jsonl', export_location_types),
                ('relationship_types.jsonl', export_relationship_types),
            ]:
                c = await fn(pool, str(out_dir / name))
                logger.info(f"Exported {c:,} to {out_dir / name}")

            c = await export_entities(
                pool, output_path=str(out_dir / 'entities.jsonl'),
                include_entity_id=not getattr(args, 'no_entity_id', False),
            )
            logger.info(f"Exported {c:,} entities to {out_dir / 'entities.jsonl'}")

            c = await export_relationships(pool, str(out_dir / 'relationships.jsonl'))
            logger.info(f"Exported {c:,} relationships to {out_dir / 'relationships.jsonl'}")

            # Also export vectors if Weaviate is available
            c = await export_vectors(
                entity_vectors_path=str(out_dir / 'entity_vectors.jsonl'),
                location_vectors_path=str(out_dir / 'location_vectors.jsonl'),
            )
            if c:
                logger.info(f"Exported {c:,} total vectors")
    finally:
        await pool.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='entity_export_jsonl',
        description='Export Entity Registry data to JSONL files for bulk import',
    )
    # Reference tables
    parser.add_argument('--entity-types', help='Output path for entity types JSONL')
    parser.add_argument('--categories', help='Output path for categories JSONL')
    parser.add_argument('--location-types', help='Output path for location types JSONL')
    parser.add_argument('--relationship-types', help='Output path for relationship types JSONL')

    # Data tables
    parser.add_argument('--entities', '-e',
                        help='Output path for entities JSONL (use - for stdout)')
    parser.add_argument('--relationships', '-r',
                        help='Output path for relationships JSONL (use - for stdout)')

    # Vector files
    parser.add_argument('--entity-vectors',
                        help='Output path for entity vectors JSONL (fetched from Weaviate)')
    parser.add_argument('--location-vectors',
                        help='Output path for location vectors JSONL (fetched from Weaviate)')

    # Convenience
    parser.add_argument('--all', metavar='DIR',
                        help='Export everything to a directory (6 files)')

    # Filters
    parser.add_argument('--type-key', help='Filter entities by type_key')
    parser.add_argument('--country', help='Filter entities by country')
    parser.add_argument('--status', default='active',
                        help='Entity status to export (default: active)')
    parser.add_argument('--no-entity-id', action='store_true',
                        help='Omit entity_id from output (for generating new IDs on import)')

    args = parser.parse_args()

    has_output = any([
        args.entities, args.relationships,
        args.entity_types, args.categories,
        args.location_types, args.relationship_types,
        args.entity_vectors, args.location_vectors,
        getattr(args, 'all', None),
    ])
    if not has_output:
        parser.error("At least one output flag is required (use --all DIR for everything)")

    asyncio.run(main(args))
