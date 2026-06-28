"""Debug: inspect fuzzy_band table and test MinHash LSH lookup."""
import asyncio
import uuid
import asyncpg


DB_URL = "postgresql://postgres@localhost:5432/sparql_sql_graph"
SPACE = "sp_semantic_search_test"


async def main():
    conn = await asyncpg.connect(DB_URL)

    band_table = f"{SPACE}_fuzzy_band"
    phonetic_table = f"{SPACE}_fuzzy_phonetic_band"

    # --- Table stats ---
    count = await conn.fetchval(f"SELECT COUNT(*) FROM {band_table}")
    distinct = await conn.fetchval(
        f"SELECT COUNT(DISTINCT split_part(entity_key, '::', 1)) FROM {band_table}"
    )
    print(f"fuzzy_band: {count} rows, {distinct} distinct subjects")

    rows = await conn.fetch(f"SELECT band_id, band_hash, entity_key FROM {band_table} LIMIT 5")
    print("\nSample rows:")
    for r in rows:
        print(f"  band_id={r['band_id']}  hash={r['band_hash']}  key={r['entity_key']}")

    # --- Phonetic table ---
    try:
        pcount = await conn.fetchval(f"SELECT COUNT(*) FROM {phonetic_table}")
        print(f"\nphonetic_band: {pcount} rows")
    except Exception as e:
        print(f"\nphonetic_band: {e}")

    # --- Fuzzy mapping properties ---
    try:
        mrows = await conn.fetch(f"SELECT * FROM {SPACE}_fuzzy_mapping ORDER BY mapping_id")
        print(f"\nFuzzy mappings: {len(mrows)}")
        for r in mrows:
            print(f"  id={r['mapping_id']} type={r.get('mapping_type')} enabled={r['enabled']}")
        prows = await conn.fetch(f"SELECT * FROM {SPACE}_fuzzy_mapping_property ORDER BY mapping_id, ordinal")
        print(f"Fuzzy mapping properties: {len(prows)}")
        for r in prows:
            print(f"  mapping_id={r['mapping_id']} uri={r['property_uri']} role={r['property_role']}")
    except Exception as e:
        print(f"Mapping tables error: {e}")

    # --- Test MinHash LSH lookup for "Joes Piza" ---
    print("\n--- MinHash LSH test for 'Joes Piza' ---")
    try:
        from vitalgraph.vectorization.fuzzy_core import (
            build_band_queries, build_minhash, build_typo_variants,
            compute_band_hash, compute_band_ranges, compute_shingles as cs,
        )
        from vitalgraph.vectorization.fuzzy_mapping_manager import resolve_any_fuzzy_mapping

        rule = await resolve_any_fuzzy_mapping(conn, SPACE)
        if rule is None:
            print("ERROR: no fuzzy mapping found!")
            await conn.close()
            return

        print(f"Mapping: id={rule.mapping_id}, shingle_k={rule.shingle_k}, "
              f"num_perm={rule.num_perm}, lsh_threshold={rule.lsh_threshold}")
        print(f"  primary_uris={rule.primary_uris}")
        print(f"  alias_uris={rule.alias_uris}")
        print(f"  include_uris={rule.include_uris}")
        print(f"  mapping_type={rule.mapping_type}")

        # Find Pizza entity UUID
        quad_table = f"{SPACE}_rdf_quad"
        term_table = f"{SPACE}_term"
        pizza_row = await conn.fetchrow(f"""
            SELECT q.subject_uuid, obj_t.term_text
            FROM {quad_table} q
            JOIN {term_table} pred_t ON pred_t.term_uuid = q.predicate_uuid
            JOIN {term_table} obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L'
            WHERE pred_t.term_text = 'http://vital.ai/ontology/vital-core#hasName'
              AND obj_t.term_text ILIKE '%pizza%'
            LIMIT 1
        """)
        if pizza_row:
            pizza_uuid = str(pizza_row['subject_uuid'])
            print(f"\nPizza entity: uuid={pizza_uuid}, name='{pizza_row['term_text']}'")
        else:
            print("\nWARNING: No Pizza entity found in term table!")
            pizza_uuid = None

        # Build MinHash for query
        search_text = "Joes Piza"
        shingles = cs(search_text, rule.shingle_k)
        primary_ranges = compute_band_ranges(rule.num_perm, rule.lsh_threshold)
        print(f"\nQuery shingles ({len(shingles)}): {sorted(shingles)}")

        # Compute what the INDEXED bands for "Joe's Pizza" should look like
        target_shingles = cs("Joe's Pizza", rule.shingle_k)
        target_mh = build_minhash(target_shingles, rule.num_perm)
        print(f"Target 'Joe's Pizza' shingles ({len(target_shingles)}): {sorted(target_shingles)}")

        # Compare locally-computed target bands vs what's in the DB
        if pizza_uuid:
            print(f"\n--- Comparing LOCAL target hashes vs DB stored hashes ---")
            db_bands = await conn.fetch(
                f"SELECT band_id, band_hash FROM {band_table} WHERE entity_key = $1 ORDER BY band_id",
                f"{pizza_uuid}::0"
            )
            matches = 0
            mismatches = 0
            for db_row in db_bands:
                bid = db_row['band_id']
                db_hash = bytes(db_row['band_hash'])
                start, end = primary_ranges[bid]
                local_hash = compute_band_hash(target_mh.hashvalues, start, end)
                if db_hash == local_hash:
                    matches += 1
                else:
                    mismatches += 1
                    if mismatches <= 3:
                        print(f"  MISMATCH band {bid}: db={db_hash.hex()[:16]} local={local_hash.hex()[:16]}")
            print(f"  Band hash comparison: {matches} match, {mismatches} mismatch (out of {len(db_bands)})")

        # Step 1: Direct LSH lookup
        mh = build_minhash(shingles, rule.num_perm)
        band_queries = build_band_queries([mh], primary_ranges)
        hits = {}
        for band_id, hashes in band_queries:
            brows = await conn.fetch(
                f"SELECT entity_key FROM {band_table} WHERE band_id = $1 AND band_hash = ANY($2)",
                band_id, hashes,
            )
            for br in brows:
                key = br["entity_key"]
                hits[key] = hits.get(key, 0) + 1
        print(f"\nStep 1 (primary LSH) hits: {len(hits)}")

        # Step 2: Phonetic LSH lookup (reproduces server behavior)
        from vitalgraph.vectorization.fuzzy_core import compute_phonetic_codes
        phonetic_codes = compute_phonetic_codes(search_text)
        phonetic_table = f"{SPACE}_fuzzy_phonetic_band"
        if phonetic_codes:
            ph_mh = build_minhash(set(phonetic_codes), rule.num_perm)
            ph_ranges = compute_band_ranges(rule.num_perm, 0.3)
            ph_queries = build_band_queries([ph_mh], ph_ranges)
            for band_id, hashes in ph_queries:
                brows = await conn.fetch(
                    f"SELECT entity_key FROM {phonetic_table} WHERE band_id = $1 AND band_hash = ANY($2)",
                    band_id, hashes,
                )
                for br in brows:
                    key = br["entity_key"]
                    hits[key] = hits.get(key, 0) + 1
        print(f"Step 2 (phonetic LSH) hits after merge: {len(hits)}")
        if hits:
            print("  Raw keys in hits dict:")
            for k, v in sorted(hits.items(), key=lambda x: -x[1])[:5]:
                print(f"    '{k}': {v} bands")
            # Show what extract_entity_ids does with these
            from vitalgraph.vectorization.fuzzy_core import extract_entity_ids as _ei
            eids = _ei(hits)
            print(f"  extract_entity_ids → {len(eids)} IDs: {list(eids)[:5]}")
            # Try UUID conversion
            import uuid as _uuid
            valid = []
            invalid = []
            for eid in eids:
                try:
                    _uuid.UUID(eid)
                    valid.append(eid)
                except ValueError:
                    invalid.append(eid)
            print(f"  Valid UUIDs: {len(valid)}, Invalid: {len(invalid)}")
            if invalid:
                print(f"  ⚠️  INVALID IDs (P:: bug): {invalid[:3]}")

        # Step 3: Typo variants
        typo_mhs = build_typo_variants(
            [search_text], shingle_k=rule.shingle_k, num_perm=rule.num_perm, max_variants=50
        )
        print(f"Step 3: {len(typo_mhs)} typo variant MinHashes")
        typo_queries = build_band_queries(typo_mhs, primary_ranges)
        for band_id, hashes in typo_queries:
            brows = await conn.fetch(
                f"SELECT entity_key FROM {band_table} WHERE band_id = $1 AND band_hash = ANY($2)",
                band_id, hashes,
            )
            for br in brows:
                key = br["entity_key"]
                hits[key] = hits.get(key, 0) + 1
        print(f"After typo variants, total hits: {len(hits)}")
        for key, cnt in sorted(hits.items(), key=lambda x: -x[1])[:10]:
            print(f"  {key}: {cnt} band matches")

    except Exception as e:
        import traceback
        traceback.print_exc()

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
