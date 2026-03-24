#!/usr/bin/env python3
"""Inspect the registry_output/ data files to find interesting test entities."""
import json
import math
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'registry_output'


def load_jsonl(filename):
    items = []
    with open(DATA_DIR / filename) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def main():
    entities = load_jsonl('entities.jsonl')
    relationships = load_jsonl('relationships.jsonl')
    categories_def = load_jsonl('categories.jsonl')

    # Build relationship map
    rel_map = defaultdict(list)
    for r in relationships:
        rel_map[r['source']].append(r)
        rel_map[r['destination']].append(r)

    print(f'Total entities: {len(entities)}')
    print(f'Total relationships: {len(relationships)}')

    # --- Entities with aliases ---
    with_aliases = [e for e in entities if e.get('aliases')]
    with_aliases.sort(key=lambda e: len(e['aliases']), reverse=True)
    print(f'\n=== ENTITIES WITH ALIASES ({len(with_aliases)}) ===')
    for e in with_aliases[:25]:
        alias_names = [a['alias_name'] for a in e['aliases']]
        print(f'  {e["primary_name"]} ({e["entity_id"]}) [{e["type_key"]}]')
        print(f'    Aliases: {alias_names}')
        print(f'    Region: {e.get("region")}, Locality: {e.get("locality")}')

    # --- Entities with most identifiers ---
    with_idents = [(e, e.get('identifiers', [])) for e in entities if e.get('identifiers')]
    with_idents.sort(key=lambda x: len(x[1]), reverse=True)
    print(f'\n=== ENTITIES WITH MOST IDENTIFIERS ===')
    for e, idents in with_idents[:15]:
        id_summary = [(i['namespace'], i['value']) for i in idents]
        print(f'  {e["primary_name"]} ({e["entity_id"]}): {id_summary}')

    # --- Identifier namespaces ---
    ns_counts = defaultdict(int)
    for e in entities:
        for i in e.get('identifiers', []):
            ns_counts[i['namespace']] += 1
    print(f'\n=== IDENTIFIER NAMESPACES ===')
    for ns, cnt in sorted(ns_counts.items(), key=lambda x: -x[1]):
        print(f'  {ns}: {cnt}')

    # --- Entities with locations + geo ---
    with_locs = [e for e in entities if e.get('locations')]
    with_geo_locs = [e for e in with_locs if any(l.get('latitude') for l in e['locations'])]
    print(f'\n=== LOCATION STATS ===')
    print(f'  Entities with locations: {len(with_locs)}')
    print(f'  Entities with geo locations: {len(with_geo_locs)}')

    # --- DBA names (interesting for phonetic/dedup testing) ---
    dba_entities = [e for e in entities if ' DBA ' in e['primary_name'].upper() or ' dba ' in e['primary_name'].lower()]
    print(f'\n=== DBA ENTITIES (interesting names) ({len(dba_entities)}) ===')
    for e in dba_entities[:15]:
        print(f'  {e["primary_name"]} ({e["entity_id"]})')

    # --- Entities with most relationships ---
    ent_rel_counts = defaultdict(int)
    for r in relationships:
        ent_rel_counts[r['source']] += 1
        ent_rel_counts[r['destination']] += 1
    top_rel = sorted(ent_rel_counts.items(), key=lambda x: -x[1])[:15]
    ent_by_id = {e['entity_id']: e for e in entities}
    print(f'\n=== ENTITIES WITH MOST RELATIONSHIPS ===')
    for eid, cnt in top_rel:
        e = ent_by_id.get(eid)
        name = e['primary_name'] if e else '(unknown)'
        print(f'  {name} ({eid}): {cnt} relationships')

    # --- Category diversity ---
    cat_counts = defaultdict(int)
    for e in entities:
        for c in e.get('categories', []):
            cat_counts[c] += 1
    print(f'\n=== CATEGORY COUNTS ===')
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f'  {cat}: {cnt}')

    # --- Entities near specific cities ---
    cities = {
        'NYC': (40.7128, -74.0060, 15),
        'LA': (34.0522, -118.2437, 20),
        'Chicago': (41.8781, -87.6298, 15),
        'Miami': (25.7617, -80.1918, 15),
        'Houston': (29.7604, -95.3698, 15),
        'SF': (37.7749, -122.4194, 15),
    }
    for city, (clat, clon, radius) in cities.items():
        nearby = []
        for e in entities:
            lat = e.get('latitude')
            lon = e.get('longitude')
            if lat and lon:
                d = haversine_km(clat, clon, lat, lon)
                if d <= radius:
                    nearby.append((e, d))
        nearby.sort(key=lambda x: x[1])
        print(f'\n=== ENTITIES NEAR {city} ({len(nearby)} within {radius}km) ===')
        for e, d in nearby[:10]:
            cats = e.get('categories', [])
            aliases = [a['alias_name'] for a in e.get('aliases', [])]
            print(f'  [{d:.1f}km] {e["primary_name"]} ({e["entity_id"]}) '
                  f'[{e["type_key"]}] cats={cats} aliases={aliases}')

    # --- Entities with websites ---
    with_website = [e for e in entities if e.get('website')]
    print(f'\n=== ENTITIES WITH WEBSITES ({len(with_website)}) ===')
    for e in with_website[:15]:
        print(f'  {e["primary_name"]} ({e["entity_id"]}): {e["website"]}')

    # --- Business entities with rich data (aliases + identifiers + locations + categories) ---
    print(f'\n=== RICHEST ENTITIES (aliases + identifiers + locations + categories) ===')
    scored = []
    for e in entities:
        score = (len(e.get('aliases', [])) * 3 +
                 len(e.get('identifiers', [])) +
                 len(e.get('locations', [])) * 2 +
                 len(e.get('categories', [])) +
                 (1 if e.get('website') else 0) +
                 (1 if e.get('latitude') else 0) +
                 len(rel_map.get(e['entity_id'], [])))
        scored.append((e, score))
    scored.sort(key=lambda x: -x[1])
    for e, score in scored[:20]:
        aliases = [a['alias_name'] for a in e.get('aliases', [])]
        idents = [(i['namespace'], i['value']) for i in e.get('identifiers', [])]
        cats = e.get('categories', [])
        locs = [(l.get('locality'), l.get('admin_area_1')) for l in e.get('locations', [])]
        rels = rel_map.get(e['entity_id'], [])
        print(f'  [score={score}] {e["primary_name"]} ({e["entity_id"]}) [{e["type_key"]}]')
        print(f'    Region={e.get("region")} Locality={e.get("locality")} Geo=({e.get("latitude")}, {e.get("longitude")})')
        print(f'    Desc: {(e.get("description") or "")[:100]}')
        print(f'    Aliases: {aliases}')
        print(f'    Identifiers: {idents}')
        print(f'    Categories: {cats}')
        print(f'    Locations: {locs}')
        print(f'    Relationships: {len(rels)}')
        if e.get('website'):
            print(f'    Website: {e["website"]}')


if __name__ == '__main__':
    main()
