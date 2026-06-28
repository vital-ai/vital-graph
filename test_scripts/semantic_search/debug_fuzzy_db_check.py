"""Check what's actually stored in the fuzzy_band table for the Pizza entity."""
import asyncio
import asyncpg

DB_URL = "postgresql://postgres@localhost:5432/sparql_sql_graph"
SPACE = "sp_semantic_search_test"
PIZZA_UUID = "1bb7c664-21c1-534f-a5e9-2ba34389c05f"


async def main():
    conn = await asyncpg.connect(DB_URL)

    # Get all literal properties for the Pizza entity
    sql = (
        f"SELECT pred_t.term_text as predicate, obj_t.term_text as value "
        f"FROM {SPACE}_rdf_quad q "
        f"JOIN {SPACE}_term pred_t ON pred_t.term_uuid = q.predicate_uuid "
        f"JOIN {SPACE}_term obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L' "
        f"WHERE q.subject_uuid = $1::uuid "
        f"ORDER BY pred_t.term_text, obj_t.term_text"
    )
    rows = await conn.fetch(sql, PIZZA_UUID)
    print("Pizza entity literal properties:")
    for r in rows:
        pred = r['predicate'].split('#')[-1]
        val = r['value'][:100]
        print(f"  {pred} = {val}")

    # Get all variants in fuzzy_band
    variants = await conn.fetch(
        f"SELECT DISTINCT entity_key FROM {SPACE}_fuzzy_band "
        f"WHERE entity_key LIKE $1",
        f"{PIZZA_UUID}%"
    )
    print(f"\nVariants in fuzzy_band: {len(variants)}")
    for v in variants:
        print(f"  {v['entity_key']}")

    # For each variant, compute what text would produce matching bands
    from vitalgraph.vectorization.fuzzy_core import (
        compute_shingles, build_minhash, compute_band_ranges, compute_band_hash,
    )

    primary_ranges = compute_band_ranges(64, 0.3)

    # Try each property value to see which one matches variant 0
    print(f"\n--- Checking which text produced variant ::0 bands ---")
    db_bands_0 = await conn.fetch(
        f"SELECT band_id, band_hash FROM {SPACE}_fuzzy_band "
        f"WHERE entity_key = $1 ORDER BY band_id",
        f"{PIZZA_UUID}::0"
    )
    print(f"Variant ::0 has {len(db_bands_0)} band entries")

    for r in rows:
        pred = r['predicate'].split('#')[-1]
        val = r['value']
        shingles = compute_shingles(val, 3)
        if not shingles:
            continue
        mh = build_minhash(shingles, 64)
        # Compare band 0
        if db_bands_0:
            start, end = primary_ranges[db_bands_0[0]['band_id']]
            local_hash = compute_band_hash(mh.hashvalues, start, end)
            db_hash = bytes(db_bands_0[0]['band_hash'])
            match = "✓ MATCH" if local_hash == db_hash else "✗"
            print(f"  {pred}={val[:50]}...  band0: {match}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
