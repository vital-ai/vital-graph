#!/usr/bin/env python3
"""
Sync missing locations to Weaviate using individual REST upserts (no gRPC).

Fetches recently-updated locations from PostgreSQL and upserts them
one-by-one to Weaviate via the REST API, avoiding gRPC batch timeouts.

Usage:
    python test_scripts/weaviate/sync_missing_locations.py --since 7d
    python test_scripts/weaviate/sync_missing_locations.py --since 7d --dry-run
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def entity_id_to_uuid(entity_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vitalgraph:entity:{entity_id}"))


def location_id_to_uuid(location_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vitalgraph:location:{location_id}"))


def parse_since(value: str) -> datetime:
    match = re.fullmatch(r'(\d+)([mhdw])', value.strip().lower())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = {'m': timedelta(minutes=amount), 'h': timedelta(hours=amount),
                 'd': timedelta(days=amount), 'w': timedelta(weeks=amount)}[unit]
        return datetime.now(timezone.utc) - delta
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def location_to_properties(loc: dict) -> dict:
    props = {
        'location_id': str(loc['location_id']),
        'entity_id': loc['entity_id'],
        'location_type_key': loc.get('location_type_key', ''),
        'location_type_label': loc.get('location_type_label', ''),
        'location_name': loc.get('location_name') or '',
        'description': loc.get('description') or '',
        'address_line_1': loc.get('address_line_1') or '',
        'address_line_2': loc.get('address_line_2') or '',
        'locality': loc.get('locality') or '',
        'admin_area_1': loc.get('admin_area_1') or '',
        'country': loc.get('country') or '',
        'country_code': loc.get('country_code') or '',
        'postal_code': loc.get('postal_code') or '',
        'formatted_address': loc.get('formatted_address') or '',
        'external_location_id': loc.get('external_location_id') or '',
        'is_primary': bool(loc.get('is_primary')),
        'status': loc.get('status', 'active'),
    }
    # search_text for vectorization
    parts = [props['location_type_label'] or props['location_type_key']]
    if props['formatted_address']:
        parts.append(props['formatted_address'])
    elif props['locality']:
        parts.append(f"{props['locality']}, {props['admin_area_1']}, {props['postal_code']}")
    props['search_text'] = '. '.join(p for p in parts if p)

    lat = loc.get('latitude')
    lng = loc.get('longitude')
    if lat is not None and lng is not None:
        props['geo_location'] = {'latitude': float(lat), 'longitude': float(lng)}

    return props


def get_keycloak_token():
    from vitalgraph.config.config_loader import get_scoped_env
    keycloak_url = get_scoped_env('WEAVIATE_KEYCLOAK_URL')
    resp = httpx.post(keycloak_url, data={
        'grant_type': 'password',
        'client_id': get_scoped_env('WEAVIATE_CLIENT_ID'),
        'client_secret': get_scoped_env('WEAVIATE_CLIENT_SECRET'),
        'username': get_scoped_env('WEAVIATE_USERNAME'),
        'password': get_scoped_env('WEAVIATE_PASSWORD'),
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()['access_token']


async def main():
    parser = argparse.ArgumentParser(description="Sync missing locations via REST")
    parser.add_argument('--since', required=True, help="e.g. 7d, 1h, 2026-04-09T00:00:00")
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--concurrency', type=int, default=2,
                        help='Max concurrent requests (keep low for embedding model)')
    args = parser.parse_args()

    since = parse_since(args.since)
    logger.info(f"Since: {since.isoformat()}")

    # Get Weaviate config
    http_host = os.getenv('PROD_WEAVIATE_HTTP_HOST')
    base_url = f"https://{http_host}/v1"

    env_lower = os.getenv('VITALGRAPH_ENVIRONMENT', 'local').strip().lower()
    if env_lower in ('', 'local'):
        env_lower = 'dev'
    env_prefix = env_lower.capitalize()
    loc_collection = f"{env_prefix}xxxLocationIndex"

    logger.info(f"Collection: {loc_collection}")
    logger.info(f"Weaviate: {base_url}")

    # Connect to PostgreSQL
    conn = await asyncpg.connect(
        host='acme-postgres-prod.c65akm0oyqv9.us-east-1.rds.amazonaws.com',
        port=5432, database='vitalgraphdb', user='postgres',
        password='VgProd2026!RdsSecure#X9',
    )

    rows = await conn.fetch(
        "SELECT el.location_id, el.entity_id, el.location_name, el.description, "
        "el.address_line_1, el.address_line_2, el.locality, el.admin_area_1, el.country, "
        "el.country_code, el.postal_code, el.formatted_address, "
        "el.latitude, el.longitude, el.is_primary, el.status, "
        "el.external_location_id, "
        "elt.type_key AS location_type_key, elt.type_label AS location_type_label "
        "FROM entity_location el "
        "JOIN entity_location_type elt ON el.location_type_id = elt.location_type_id "
        "WHERE el.status = 'active' AND el.updated_time >= $1 "
        "ORDER BY el.location_id",
        since
    )
    await conn.close()

    logger.info(f"Locations to sync: {len(rows):,}")
    if args.dry_run:
        logger.info("DRY RUN — exiting")
        return

    # Auth
    token = get_keycloak_token()
    headers = {'Authorization': f'Bearer {token}'}

    upserted = 0
    errors = 0
    start = time.time()
    total = len(rows)

    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        for i, loc_dict in enumerate(rows):
            loc = dict(loc_dict)
            obj_uuid = location_id_to_uuid(loc['location_id'])
            properties = location_to_properties(loc)

            payload = {
                'class': loc_collection,
                'id': obj_uuid,
                'properties': properties,
            }

            # POST to create; if 422 (already exists), PATCH to update
            resp = await http.post(f"{base_url}/objects", json=payload)
            if resp.status_code in (200, 201):
                upserted += 1
            elif resp.status_code == 422:
                url = f"{base_url}/objects/{loc_collection}/{obj_uuid}"
                resp2 = await http.patch(url, json={'properties': properties})
                if resp2.status_code == 200:
                    upserted += 1
                else:
                    errors += 1
                    if errors <= 5:
                        logger.error(f"  PATCH failed loc={loc['location_id']}: "
                                     f"{resp2.status_code} {resp2.text[:200]}")
            else:
                errors += 1
                if errors <= 5:
                    logger.error(f"  POST failed loc={loc['location_id']}: "
                                 f"{resp.status_code} {resp.text[:200]}")

            done = upserted + errors
            if done % 100 == 0 and done > 0:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (total - done) / rate if rate > 0 else 0
                logger.info(f"  {done:,}/{total:,}  {upserted:,} ok, {errors:,} err  "
                            f"({rate:.1f}/s, ~{remaining:.0f}s left)")

    elapsed = time.time() - start
    logger.info(f"\nDone: {upserted:,} upserted, {errors:,} errors in {elapsed:.1f}s")


if __name__ == '__main__':
    asyncio.run(main())
