"""
Direct Weaviate query test — bypasses the server to diagnose search issues.

Usage:
    python vitalgraph_client_test/test_weaviate_direct.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
from vitalgraph.entity_registry.entity_weaviate_schema import (
    get_collection_name, get_location_collection_name,
)

LINE = "─" * 60
passed = 0
failed = 0


def report(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}{' — ' + detail if detail else ''}")
    else:
        failed += 1
        print(f"  ❌ {name}{' — ' + detail if detail else ''}")


def main():
    global passed, failed

    print(f"\n{LINE}")
    print("Direct Weaviate Query Tests")
    print(LINE)

    # Connect
    index = EntityWeaviateIndex.from_env()
    if not index:
        print("ERROR: Could not connect to Weaviate (check env vars)")
        sys.exit(1)

    cname = get_collection_name()
    lname = get_location_collection_name()
    print(f"  Entity collection:   {cname}")
    print(f"  Location collection: {lname}")

    # ── Object inventory ──
    print(f"\n{'— Object Inventory —':^60}")
    entities = []
    for obj in index.collection.iterator(include_vector=True):
        p = obj.properties
        vec = obj.vector
        has_vec = vec is not None and (
            (isinstance(vec, dict) and len(vec) > 0) or
            (isinstance(vec, list) and len(vec) > 0)
        )
        entities.append({
            'entity_id': p.get('entity_id'),
            'primary_name': p.get('primary_name'),
            'type_key': p.get('type_key'),
            'country': p.get('country'),
            'identifier_keys': p.get('identifier_keys', []),
            'identifier_values': p.get('identifier_values', []),
            'has_vector': has_vec,
        })
    print(f"  Entities: {len(entities)}")
    for e in entities:
        ids_str = ', '.join(e['identifier_keys']) if e['identifier_keys'] else '(none)'
        print(f"    {e['entity_id']}: {e['primary_name']} "
              f"[{e['type_key']}] vec={e['has_vector']} ids=[{ids_str}]")

    report("Entities loaded", len(entities) > 0, f"count={len(entities)}")
    report("All entities have vectors",
           all(e['has_vector'] for e in entities),
           f"without_vector={[e['entity_id'] for e in entities if not e['has_vector']]}")

    locations = []
    for obj in index.location_collection.iterator(include_vector=False):
        p = obj.properties
        geo = p.get('geo_location')
        locations.append({
            'location_id': p.get('location_id'),
            'entity_id': p.get('entity_id'),
            'location_name': p.get('location_name'),
            'has_geo': geo is not None,
            'lat': getattr(geo, 'latitude', None) if geo else None,
            'lng': getattr(geo, 'longitude', None) if geo else None,
        })
    print(f"\n  Locations: {len(locations)}")
    for loc in locations:
        print(f"    loc {loc['location_id']}: entity={loc['entity_id']} "
              f"name={loc['location_name']} geo=({loc['lat']}, {loc['lng']})")

    report("Locations loaded", len(locations) > 0, f"count={len(locations)}")

    # ── Topic search (semantic) ──
    print(f"\n{'— Topic Search (semantic) —':^60}")
    results = index.search_topic(query="manufacturing company", limit=5, min_certainty=0.3)
    print(f"  Query: 'manufacturing company' → {len(results)} results")
    for r in results:
        print(f"    {r['entity_id']}: {r['primary_name']} score={r.get('score', 0):.4f}")
    report("Topic search returns results", len(results) > 0, f"count={len(results)}")

    # ── Topic search with type filter ──
    print(f"\n{'— Topic Search + type filter —':^60}")
    results_typed = index.search_topic(
        query="consulting", type_key="business", limit=5, min_certainty=0.3)
    print(f"  Query: 'consulting' type_key=business → {len(results_typed)} results")
    for r in results_typed:
        print(f"    {r['entity_id']}: {r['primary_name']} type={r.get('type_key')}")
    report("Typed topic search returns results", len(results_typed) > 0)

    # ── Location search (geo) ──
    print(f"\n{'— Location Search (geo-radius) —':^60}")
    loc_results = index.search_locations_near(
        latitude=37.79, longitude=-122.4, radius_km=20, limit=10)
    print(f"  Near SF (37.79, -122.4, 20km) → {len(loc_results)} results")
    for r in loc_results:
        print(f"    loc {r.get('location_id')}: {r.get('location_name')} "
              f"entity={r.get('entity_id')}")
    report("Locations near SF", len(loc_results) > 0, f"count={len(loc_results)}")

    # ── Entities near (geo via cross-ref) ──
    print(f"\n{'— Entities Near (cross-ref geo) —':^60}")
    ent_near = index.search_entities_near(
        latitude=37.79, longitude=-122.4, radius_km=20, limit=10)
    print(f"  Entities near SF → {len(ent_near)} results")
    for r in ent_near:
        locs = r.get('locations', [])
        print(f"    {r['entity_id']}: {r['primary_name']} locations={len(locs)}")
    report("Entities near SF", len(ent_near) > 0, f"count={len(ent_near)}")

    # ── Topic + geo (combined) ──
    print(f"\n{'— Topic + Geo (combined) —':^60}")
    combined = index.search_topic_near(
        query="manufacturing company",
        latitude=37.79, longitude=-122.4, radius_km=20,
        limit=10, min_certainty=0.3)
    print(f"  'manufacturing company' near SF → {len(combined)} results")
    for r in combined:
        print(f"    {r['entity_id']}: {r['primary_name']} score={r.get('score', 0):.4f}")
    report("Topic+geo returns results", len(combined) > 0, f"count={len(combined)}")

    # ── Identifier filter ──
    print(f"\n{'— Identifier Filter —':^60}")
    # Check if any entity has identifiers
    entities_with_ids = [e for e in entities if e['identifier_keys']]
    if entities_with_ids:
        sample = entities_with_ids[0]
        sample_key = sample['identifier_keys'][0]  # e.g. "duns:123456"
        ns, val = sample_key.split(':', 1) if ':' in sample_key else ('', sample_key)
        print(f"  Testing with identifier: {sample_key} (entity={sample['entity_id']})")

        id_results = index.search_topic(
            query=sample['primary_name'],
            identifier_value=val, identifier_namespace=ns,
            limit=5, min_certainty=0.0)
        print(f"  Results: {len(id_results)}")
        for r in id_results:
            print(f"    {r['entity_id']}: {r['primary_name']}")
        report("Identifier filter returns matching entity",
               any(r['entity_id'] == sample['entity_id'] for r in id_results),
               f"expected={sample['entity_id']}")
    else:
        print("  No entities with identifiers — skipping")
        report("Entities have identifiers", False, "none found")

    # ── Summary ──
    print(f"\n{LINE}")
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print(LINE)

    index.close()
    sys.exit(1 if failed > 0 else 0)


if __name__ == '__main__':
    main()
