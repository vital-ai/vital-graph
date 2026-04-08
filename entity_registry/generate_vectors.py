#!/usr/bin/env python3
"""
Generate pre-computed vector JSONL files for Weaviate entity and location loading.

Produces two companion files alongside the registry_output:
  - entity_vectors.jsonl:   {"entity_id": "ent_xxx", "vector": [0.1, ...]}
  - location_vectors.jsonl: {"location_id": 123, "vector": [0.1, ...]}

These files can be passed to `weaviate_admin.py load --vectors <dir>` to skip
server-side vectorization during Weaviate loading, significantly speeding up
the full sync process.

Vectorization replicates Weaviate's HuggingFaceVectorizer exactly:
  - NLTK sent_tokenize → AutoModel + AutoTokenizer → masked_mean pooling
  - Produces cosine=1.0 match with Weaviate's auto-vectorized vectors

Usage:
    python entity_registry/generate_vectors.py [--output-dir DIR] [--limit N]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg

from vitalgraph.entity_registry.entity_weaviate_schema import (
    entity_to_weaviate_properties,
    location_to_weaviate_properties,
)
from vitalgraph.entity_registry.entity_vectorizer import (
    WeaviateLocalVectorizer,
    best_device,
    build_entity_vectorization_text,
    build_location_vectorization_text,
    load_vectors_from_jsonl,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
)
logger = logging.getLogger(__name__)

LINE = '─' * 60


async def create_pool(db_url: str = None) -> asyncpg.Pool:
    if db_url:
        return await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    from vitalgraph.config.config_loader import VitalGraphConfig
    config = VitalGraphConfig()
    db_config = config.get_database_config()
    return await asyncpg.create_pool(
        host=db_config.get('host', 'localhost'),
        port=int(db_config.get('port', 5432)),
        database=db_config.get('database', 'vitalgraph'),
        user=db_config.get('username', 'postgres'),
        password=db_config.get('password', ''),
        min_size=1,
        max_size=5,
    )


async def generate_entity_vectors(pool, vectorizer, output_path: Path,
                                  limit: int = None) -> int:
    """Generate entity vectors and write to JSONL file.

    Returns the number of entities vectorized.
    """
    entity_sql = (
        "SELECT e.entity_id, e.primary_name, e.description, e.country, "
        "e.region, e.locality, e.website, e.latitude, e.longitude, e.status, "
        "e.notes, "
        "et.type_key, et.type_label, et.type_description, "
        "ea.alias_name, ea.alias_type, "
        "ec.category_key, ec.category_label "
        "FROM entity e "
        "JOIN entity_type et ON e.entity_type_id = et.type_id "
        "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id "
        "AND ea.status = 'active' "
        "LEFT JOIN entity_category_map ecm ON ecm.entity_id = e.entity_id "
        "AND ecm.status = 'active' "
        "LEFT JOIN category ec ON ec.category_id = ecm.category_id "
        "WHERE e.status = 'active' "
        "ORDER BY e.entity_id"
    )

    # Also need locations and identifiers per entity for accurate vectorization
    count = 0
    current_entity_id = None
    current_entity = None
    seen_aliases = set()
    seen_categories = set()

    entities_pending = []

    def _flush_entity():
        nonlocal current_entity
        if current_entity is not None:
            entities_pending.append(current_entity)
            current_entity = None

    async def _enrich_with_locations(conn, batch):
        eids = [e['entity_id'] for e in batch]
        loc_rows = await conn.fetch(
            "SELECT el.entity_id, el.location_name, el.formatted_address, "
            "el.locality, el.admin_area_1, el.country "
            "FROM entity_location el "
            "WHERE el.entity_id = ANY($1) AND el.status = 'active' "
            "ORDER BY el.entity_id, el.is_primary DESC, el.location_id",
            eids
        )
        loc_map = {}
        for lr in loc_rows:
            loc_map.setdefault(lr['entity_id'], []).append(dict(lr))
        for entity in batch:
            entity['locations'] = loc_map.get(entity['entity_id'], [])

    async def _enrich_with_identifiers(conn, batch):
        eids = [e['entity_id'] for e in batch]
        id_rows = await conn.fetch(
            "SELECT entity_id, identifier_namespace, identifier_value "
            "FROM entity_identifier "
            "WHERE entity_id = ANY($1) AND status = 'active' "
            "ORDER BY entity_id",
            eids
        )
        id_map = {}
        for ir in id_rows:
            id_map.setdefault(ir['entity_id'], []).append(dict(ir))
        for entity in batch:
            entity['identifiers'] = id_map.get(entity['entity_id'], [])

    with open(output_path, 'w') as f:
        async with pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.cursor(entity_sql)
                while True:
                    rows = await cursor.fetch(5000)
                    if not rows:
                        break
                    for row in rows:
                        entity_id = row['entity_id']
                        if entity_id != current_entity_id:
                            _flush_entity()
                            current_entity_id = entity_id
                            seen_aliases = set()
                            seen_categories = set()
                            current_entity = {
                                'entity_id': entity_id,
                                'primary_name': row['primary_name'],
                                'description': row['description'],
                                'country': row['country'],
                                'region': row['region'],
                                'locality': row['locality'],
                                'website': row['website'],
                                'latitude': row['latitude'],
                                'longitude': row['longitude'],
                                'status': row['status'],
                                'notes': row.get('notes') or '',
                                'type_key': row['type_key'],
                                'type_label': row['type_label'],
                                'type_description': row['type_description'],
                                'aliases': [],
                                'categories': [],
                            }

                        alias_name = row['alias_name']
                        if alias_name and alias_name not in seen_aliases:
                            seen_aliases.add(alias_name)
                            current_entity['aliases'].append({
                                'alias_name': alias_name,
                                'alias_type': row['alias_type'],
                            })

                        cat_key = row['category_key']
                        if cat_key and cat_key not in seen_categories:
                            seen_categories.add(cat_key)
                            current_entity['categories'].append({
                                'category_key': cat_key,
                                'category_label': row['category_label'],
                            })

            _flush_entity()

            # Process in batches for enrichment + vectorization
            batch_size = 100
            for i in range(0, len(entities_pending), batch_size):
                batch = entities_pending[i:i + batch_size]
                await _enrich_with_locations(conn, batch)
                await _enrich_with_identifiers(conn, batch)

                for entity in batch:
                    if limit is not None and count >= limit:
                        break
                    props = entity_to_weaviate_properties(entity)
                    text = build_entity_vectorization_text(props)
                    vec = vectorizer.vectorize_text(text)
                    record = {
                        'entity_id': entity['entity_id'],
                        'vector': vec.tolist(),
                    }
                    f.write(json.dumps(record) + '\n')
                    count += 1
                    if count % 500 == 0:
                        logger.info(f"  Entity vectors: {count:,}")

                if limit is not None and count >= limit:
                    break

    return count


async def generate_location_vectors(pool, vectorizer, output_path: Path,
                                    limit: int = None) -> int:
    """Generate location vectors and write to JSONL file.

    Returns the number of locations vectorized.
    """
    loc_sql = (
        "SELECT el.location_id, el.entity_id, el.location_name, el.description, "
        "el.address_line_1, el.address_line_2, el.locality, el.admin_area_1, el.country, "
        "el.country_code, el.postal_code, el.formatted_address, "
        "el.latitude, el.longitude, el.is_primary, el.status, "
        "el.external_location_id, "
        "elt.type_key AS location_type_key, elt.type_label AS location_type_label "
        "FROM entity_location el "
        "JOIN entity_location_type elt ON el.location_type_id = elt.location_type_id "
        "WHERE el.status = 'active' "
        "ORDER BY el.entity_id, el.location_id"
    )

    count = 0
    with open(output_path, 'w') as f:
        async with pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.cursor(loc_sql)
                while True:
                    rows = await cursor.fetch(5000)
                    if not rows:
                        break
                    for row in rows:
                        if limit is not None and count >= limit:
                            break
                        loc = dict(row)
                        props = location_to_weaviate_properties(loc)
                        text = build_location_vectorization_text(props)
                        vec = vectorizer.vectorize_text(text)
                        record = {
                            'location_id': loc['location_id'],
                            'vector': vec.tolist(),
                        }
                        f.write(json.dumps(record) + '\n')
                        count += 1
                        if count % 500 == 0:
                            logger.info(f"  Location vectors: {count:,}")
                    if limit is not None and count >= limit:
                        break

    return count


async def main():
    parser = argparse.ArgumentParser(
        prog='generate_vectors',
        description='Generate pre-computed Weaviate vectors for entities and locations',
    )
    parser.add_argument(
        '--output-dir', '-o', type=str,
        default=str(project_root / 'registry_output'),
        help='Output directory for vector JSONL files (default: registry_output/)',
    )
    parser.add_argument(
        '--limit', '-n', type=int, default=None,
        help='Limit number of entities/locations to vectorize (for testing)',
    )
    parser.add_argument(
        '--entities-only', action='store_true',
        help='Only generate entity vectors',
    )
    parser.add_argument(
        '--locations-only', action='store_true',
        help='Only generate location vectors',
    )
    parser.add_argument(
        '--device', type=str, default=None,
        choices=['cpu', 'mps', 'cuda'],
        help='Torch device for inference (default: auto-detect best)',
    )
    parser.add_argument(
        '--db-url', type=str, default=None,
        help='PostgreSQL connection URL (e.g. postgresql://user:pass@host:5432/dbname). '
             'Overrides config/env vars when provided.',
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Generate Weaviate Vectors")
    print(LINE)

    # Load model
    device = args.device or best_device()
    print(f"\n  Loading vectorizer model (device={device})...")
    t0 = time.time()
    vectorizer = WeaviateLocalVectorizer(device=device)
    t1 = time.time()
    print(f"  Model loaded in {t1-t0:.1f}s (dim={vectorizer.dim})")

    # Create DB pool
    pool = await create_pool(db_url=args.db_url)

    try:
        async with pool.acquire() as conn:
            pg_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active'"
            )
            pg_locations = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_location WHERE status = 'active'"
            )

        if args.limit:
            print(f"  Limit: {args.limit}")
        print(f"  PostgreSQL active entities:  {pg_entities:,}")
        print(f"  PostgreSQL active locations: {pg_locations:,}")

        do_entities = not args.locations_only
        do_locations = not args.entities_only

        # Generate entity vectors
        if do_entities:
            entity_path = output_dir / 'entity_vectors.jsonl'
            print(f"\n  Generating entity vectors → {entity_path.name}")
            t2 = time.time()
            n_ent = await generate_entity_vectors(pool, vectorizer, entity_path,
                                                  limit=args.limit)
            t3 = time.time()
            rate = n_ent / (t3 - t2) if t3 > t2 else 0
            print(f"  ✅ {n_ent:,} entity vectors in {t3-t2:.1f}s ({rate:.0f}/sec)")

        # Generate location vectors
        if do_locations:
            location_path = output_dir / 'location_vectors.jsonl'
            print(f"\n  Generating location vectors → {location_path.name}")
            t4 = time.time()
            n_loc = await generate_location_vectors(pool, vectorizer, location_path,
                                                    limit=args.limit)
            t5 = time.time()
            rate = n_loc / (t5 - t4) if t5 > t4 else 0
            print(f"  ✅ {n_loc:,} location vectors in {t5-t4:.1f}s ({rate:.0f}/sec)")

        print(LINE)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
