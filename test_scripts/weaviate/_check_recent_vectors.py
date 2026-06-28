#!/usr/bin/env python3
"""Check vectors on the most recently synced locations (highest location_ids)."""
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
base = 'https://weaviate.cardiffbank.co/v1'

# Check specific recently-synced locations by UUID
# location_id 1584341 = entity e_r57jbtenz3 (just synced)
test_ids = [1584341, 1584886, 1585025, 1585110, 1585112]

print("=== Check specific recently-synced locations ===\n")
for lid in test_ids:
    loc_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'vitalgraph:location:{lid}'))
    r = httpx.get(f'{base}/objects/ProdxxxLocationIndex/{loc_uuid}?include=vector',
                  headers=headers, timeout=15)
    if r.status_code == 200:
        data = r.json()
        vec = data.get('vector')
        props = data.get('properties', {})
        has_vec = vec is not None and len(vec) > 0
        print(f"  loc_id={lid}  entity={props.get('entity_id','?'):20s}  "
              f"vector={'YES' if has_vec else '** NO **'} "
              f"(len={len(vec) if vec else 0})  "
              f"geo={props.get('geo_location')}")
    else:
        print(f"  loc_id={lid}  NOT FOUND ({r.status_code})")

# Also check the entity e_r57jbtenz3 itself
print("\n=== Entity e_r57jbtenz3 vector ===\n")
ent_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'vitalgraph:entity:e_r57jbtenz3'))
r = httpx.get(f'{base}/objects/ProdxxxEntityIndex/{ent_uuid}?include=vector',
              headers=headers, timeout=15)
if r.status_code == 200:
    data = r.json()
    vec = data.get('vector')
    props = data.get('properties', {})
    has_vec = vec is not None and len(vec) > 0
    print(f"  entity_id=e_r57jbtenz3  name={props.get('primary_name')}")
    print(f"  vector={'YES' if has_vec else '** NO **'} (len={len(vec) if vec else 0})")
    if vec:
        print(f"  sample={vec[:5]}")
    print(f"  geo={props.get('geo_location')}")
else:
    print(f"  NOT FOUND ({r.status_code})")

# Check 5 highest location_ids via GraphQL to see if they have vectors
print("\n=== 5 highest location_id objects in Weaviate ===\n")
r2 = httpx.post(f'{base}/graphql', headers=headers, timeout=15, json={
    'query': '''{
        Get {
            ProdxxxLocationIndex(
                limit: 5,
                where: {
                    path: ["location_id"],
                    operator: GreaterThan,
                    valueText: "1584000"
                }
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
        has_vec = vec is not None and len(vec) > 0
        print(f"  loc_id={loc.get('location_id'):>10s}  "
              f"entity={loc.get('entity_id','?'):20s}  "
              f"vector={'YES' if has_vec else '** NO **'} "
              f"(len={len(vec) if vec else 0})  "
              f"search_text={loc.get('search_text','')[:60]}")
