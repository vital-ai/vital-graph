#!/usr/bin/env python3
"""Check if a recently synced location has a vector."""
import httpx, os, json, uuid
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
base = 'https://weaviate.acmebank.co/v1'

# Check location_id=1584341 (entity e_r57jbtenz3)
loc_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'vitalgraph:location:1584341'))
print(f'Location UUID: {loc_uuid}')

r = httpx.get(f'{base}/objects/ProdxxxLocationIndex/{loc_uuid}?include=vector',
              headers=headers, timeout=15)
print(f'Status: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    vec = data.get('vector')
    props = data.get('properties', {})
    print(f"search_text:  {props.get('search_text')}")
    print(f"geo_location: {props.get('geo_location')}")
    print(f"vector:       {'YES' if vec else 'NO'} (len={len(vec) if vec else 0})")
    if vec:
        print(f"sample:       {vec[:5]}")
else:
    print(f'Not found: {r.text[:300]}')

# Also check a few recently inserted ones via GraphQL
print('\n--- Recent 3 locations with vectors ---')
r2 = httpx.post(f'{base}/graphql', headers=headers, timeout=15, json={
    'query': '''{
        Get {
            ProdxxxLocationIndex(
                limit: 3,
                sort: [{ path: ["location_id"], order: desc }]
            ) {
                location_id entity_id search_text
                geo_location { latitude longitude }
                _additional { vector }
            }
        }
    }'''
})
result = r2.json()
if 'errors' in result:
    print(json.dumps(result['errors'], indent=2))
else:
    locs = result.get('data', {}).get('Get', {}).get('ProdxxxLocationIndex', [])
    for loc in locs:
        add = loc.get('_additional', {})
        vec = add.get('vector')
        print(f"  loc_id={loc.get('location_id')}  "
              f"geo={loc.get('geo_location')}  "
              f"vector={'YES' if vec else 'NO'} "
              f"(len={len(vec) if vec else 0})")
