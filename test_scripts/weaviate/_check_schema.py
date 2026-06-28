#!/usr/bin/env python3
"""Check Weaviate collection schema and vectorizer config."""
import httpx, os, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / '.env')

keycloak_url = os.getenv('PROD_WEAVIATE_KEYCLOAK_URL')
resp = httpx.post(keycloak_url, data={
    'grant_type': 'password',
    'client_id': os.getenv('PROD_WEAVIATE_CLIENT_ID'),
    'client_secret': os.getenv('PROD_WEAVIATE_CLIENT_SECRET'),
    'username': os.getenv('PROD_WEAVIATE_USERNAME'),
    'password': os.getenv('PROD_WEAVIATE_PASSWORD'),
}, timeout=15)
token = resp.json()['access_token']
headers = {'Authorization': f'Bearer {token}'}
base = 'https://weaviate.cardiffbank.co/v1'

for coll in ['ProdxxxEntityIndex', 'ProdxxxLocationIndex']:
    print(f'\n{"=" * 60}')
    print(f'  {coll}')
    print(f'{"=" * 60}')
    r = httpx.get(f'{base}/schema/{coll}', headers=headers, timeout=15)
    schema = r.json()
    print(f'  vectorizer:       {schema.get("vectorizer")}')
    print(f'  vectorIndexType:  {schema.get("vectorIndexType")}')
    mc = schema.get('moduleConfig', {})
    print(f'  moduleConfig:     {json.dumps(mc, indent=4)}')

    # Try a single POST to see the actual error body
    print(f'\n  --- Test POST (dummy object) ---')
    test_payload = {
        'class': coll,
        'properties': {'search_text': 'test location sync', 'entity_id': 'test_dummy'},
    }
    r2 = httpx.post(f'{base}/objects', json=test_payload, headers=headers, timeout=30)
    print(f'  Status: {r2.status_code}')
    print(f'  Body:   {r2.text[:500]}')

    # Clean up test object if created
    if r2.status_code in (200, 201):
        obj_id = r2.json().get('id')
        if obj_id:
            httpx.delete(f'{base}/objects/{coll}/{obj_id}', headers=headers, timeout=15)
            print(f'  (cleaned up test object {obj_id})')
