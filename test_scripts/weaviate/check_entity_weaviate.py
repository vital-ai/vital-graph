#!/usr/bin/env python3
"""
Check an entity in production Weaviate by entity_id.

Uses the Weaviate REST API directly (no gRPC) so it works from
outside the VPC where the gRPC host may not be resolvable.

Usage:
    python test_scripts/weaviate/check_entity_weaviate.py e_r57jbtenz3
    python test_scripts/weaviate/check_entity_weaviate.py e_r57jbtenz3 --env prod
"""

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def entity_id_to_uuid(entity_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vitalgraph:entity:{entity_id}"))


def location_id_to_uuid(location_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vitalgraph:location:{location_id}"))


def get_keycloak_token(keycloak_url, client_id, client_secret, username, password) -> str:
    resp = httpx.post(keycloak_url, data={
        "grant_type": "password",
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": password,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def main():
    parser = argparse.ArgumentParser(description="Check entity in production Weaviate")
    parser.add_argument("entity_id", help="Entity ID to look up (e.g. e_r57jbtenz3)")
    parser.add_argument("--env", default="prod", help="Environment prefix (default: prod)")
    args = parser.parse_args()

    entity_id = args.entity_id
    env = args.env.upper()

    # Read config from .env
    keycloak_url = os.getenv(f"{env}_WEAVIATE_KEYCLOAK_URL")
    http_host = os.getenv(f"{env}_WEAVIATE_HTTP_HOST")
    client_id = os.getenv(f"{env}_WEAVIATE_CLIENT_ID")
    client_secret = os.getenv(f"{env}_WEAVIATE_CLIENT_SECRET")
    username = os.getenv(f"{env}_WEAVIATE_USERNAME")
    password = os.getenv(f"{env}_WEAVIATE_PASSWORD")

    if not keycloak_url or not http_host:
        logger.error(f"Missing {env}_WEAVIATE_* config in .env")
        sys.exit(1)

    base_url = f"https://{http_host}/v1"

    # Collection names (first letter capitalized per Weaviate convention)
    env_lower = env.lower()
    if env_lower in ('local', ''):
        env_lower = 'dev'
    env_prefix = env_lower.capitalize()
    entity_collection = f"{env_prefix}xxxEntityIndex"
    location_collection = f"{env_prefix}xxxLocationIndex"

    obj_uuid = entity_id_to_uuid(entity_id)

    logger.info(f"Entity ID:  {entity_id}")
    logger.info(f"UUID:       {obj_uuid}")
    logger.info(f"Weaviate:   {base_url}")
    logger.info(f"Collection: {entity_collection}")
    logger.info("")

    # Get Keycloak token
    logger.info("Authenticating via Keycloak...")
    token = get_keycloak_token(keycloak_url, client_id, client_secret, username, password)
    logger.info("  OK\n")

    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(headers=headers, timeout=15) as http:
        # --- EntityIndex ---
        print("=" * 60)
        print(f"  EntityIndex: {entity_id}")
        print("=" * 60)

        url = f"{base_url}/objects/{entity_collection}/{obj_uuid}"
        resp = http.get(url)

        if resp.status_code == 200:
            data = resp.json()
            props = data.get("properties", {})

            print(f"\n  primary_name:    {props.get('primary_name')}")
            print(f"  type_key:        {props.get('type_key')}")
            print(f"  status:          {props.get('status')}")
            print(f"  country:         {props.get('country')}")
            print(f"  region:          {props.get('region')}")
            print(f"  locality:        {props.get('locality')}")
            print(f"  website:         {props.get('website')}")

            geo = props.get('geo_location')
            if geo:
                print(f"\n  ✅ geo_location:")
                print(f"     latitude:     {geo.get('latitude')}")
                print(f"     longitude:    {geo.get('longitude')}")
            else:
                print(f"\n  ❌ geo_location:  NOT SET")

            print(f"\n  category_keys:   {props.get('category_keys')}")
            print(f"  category_labels: {props.get('category_labels')}")
            print(f"  identifier_keys: {props.get('identifier_keys')}")
        elif resp.status_code == 404:
            print(f"\n  ❌ Entity NOT FOUND in Weaviate (uuid={obj_uuid})")
        else:
            print(f"\n  ❌ HTTP {resp.status_code}: {resp.text[:200]}")

        # --- LocationIndex via GraphQL ---
        print("\n" + "=" * 60)
        print(f"  LocationIndex for {entity_id}")
        print("=" * 60)

        graphql_query = {
            "query": f'''{{
                Get {{
                    {location_collection}(
                        where: {{
                            path: ["entity_id"],
                            operator: Equal,
                            valueText: "{entity_id}"
                        }},
                        limit: 20
                    ) {{
                        location_id
                        entity_id
                        location_type_key
                        location_name
                        formatted_address
                        locality
                        admin_area_1
                        country
                        postal_code
                        geo_location {{
                            latitude
                            longitude
                        }}
                        is_primary
                        status
                    }}
                }}
            }}'''
        }

        resp = http.post(f"{base_url}/graphql", json=graphql_query)
        if resp.status_code == 200:
            result = resp.json()
            errors = result.get("errors")
            if errors:
                print(f"\n  ❌ GraphQL errors: {json.dumps(errors, indent=2)}")
            else:
                locations = result.get("data", {}).get("Get", {}).get(location_collection, [])
                if locations:
                    for i, loc in enumerate(locations):
                        print(f"\n  Location #{i + 1}:")
                        print(f"    location_id:     {loc.get('location_id')}")
                        print(f"    type:            {loc.get('location_type_key')}")
                        print(f"    formatted_addr:  {loc.get('formatted_address')}")
                        print(f"    locality:        {loc.get('locality')}")
                        print(f"    admin_area_1:    {loc.get('admin_area_1')}")
                        print(f"    country:         {loc.get('country')}")
                        print(f"    postal_code:     {loc.get('postal_code')}")
                        print(f"    is_primary:      {loc.get('is_primary')}")

                        geo = loc.get('geo_location')
                        if geo:
                            print(f"    ✅ geo_location:")
                            print(f"       latitude:     {geo.get('latitude')}")
                            print(f"       longitude:    {geo.get('longitude')}")
                        else:
                            print(f"    ❌ geo_location:  NOT SET")
                else:
                    print(f"\n  No locations found for {entity_id}")
        else:
            print(f"\n  ❌ GraphQL HTTP {resp.status_code}: {resp.text[:200]}")

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
