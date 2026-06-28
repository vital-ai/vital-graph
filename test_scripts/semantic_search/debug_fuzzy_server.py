"""Run the full fuzzy resolution logic INSIDE Docker to debug."""
import asyncio
import uuid as _uuid
import asyncpg


async def main():
    conn = await asyncpg.connect('postgresql://postgres@localhost:5432/sparql_sql_graph')
    space_id = 'sp_semantic_search_test'
    search_text = 'Joes Piza'

    from vitalgraph.vectorization.fuzzy_core import (
        build_band_queries, build_minhash, build_typo_variants,
        compute_band_ranges, compute_shingles, extract_entity_ids, score_with_phonetic,
    )
    from vitalgraph.vectorization.fuzzy_mapping_manager import resolve_any_fuzzy_mapping

    rule = await resolve_any_fuzzy_mapping(conn, space_id)
    print(f'Rule: shingle_k={rule.shingle_k}, num_perm={rule.num_perm}, threshold={rule.lsh_threshold}')
    print(f'  include_uris={rule.include_uris}')

    shingles = compute_shingles(search_text, rule.shingle_k)
    mh = build_minhash(shingles, rule.num_perm)
    primary_ranges = compute_band_ranges(rule.num_perm, rule.lsh_threshold)

    band_table = f'{space_id}_fuzzy_band'
    band_queries = build_band_queries([mh], primary_ranges)
    hits = {}
    for band_id, hashes in band_queries:
        rows = await conn.fetch(
            f"SELECT entity_key FROM {band_table} WHERE band_id = $1 AND band_hash = ANY($2)",
            band_id, hashes,
        )
        for row in rows:
            hits[row['entity_key']] = hits.get(row['entity_key'], 0) + 1
    print(f'Step 1 hits: {len(hits)}')

    # Step 3: typo variants
    if not extract_entity_ids(hits):
        typo_mhs = build_typo_variants(
            [search_text], shingle_k=rule.shingle_k, num_perm=rule.num_perm, max_variants=50,
        )
        print(f'Step 3: {len(typo_mhs)} typo variants')
        typo_queries = build_band_queries(typo_mhs, primary_ranges)
        for band_id, hashes in typo_queries:
            rows = await conn.fetch(
                f"SELECT entity_key FROM {band_table} WHERE band_id = $1 AND band_hash = ANY($2)",
                band_id, hashes,
            )
            for row in rows:
                hits[row['entity_key']] = hits.get(row['entity_key'], 0) + 1
        print(f'After typo variants hits: {len(hits)}')
        for k, v in hits.items():
            print(f'  {k}: {v} bands')

    candidate_ids = extract_entity_ids(hits)
    print(f'Candidate IDs: {candidate_ids}')

    if candidate_ids:
        all_property_uris = rule.include_uris or ['http://vital.ai/ontology/vital-core#hasName']
        uuids = [_uuid.UUID(cid) for cid in candidate_ids]
        rows = await conn.fetch(
            f"SELECT q.subject_uuid, obj_t.term_text "
            f"FROM {space_id}_rdf_quad q "
            f"JOIN {space_id}_term pred_t ON pred_t.term_uuid = q.predicate_uuid "
            f"JOIN {space_id}_term obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L' "
            f"WHERE q.subject_uuid = ANY($1) AND pred_t.term_text = ANY($2)",
            uuids, all_property_uris,
        )
        print(f'Name rows: {len(rows)}')
        for r in rows:
            print(f'  {r["subject_uuid"]}: {r["term_text"]}')

        # Score
        subject_names = {}
        for row in rows:
            uuid_str = str(row['subject_uuid'])
            subject_names.setdefault(uuid_str, []).append(row['term_text'].strip())
        for uuid_str, names in subject_names.items():
            result = score_with_phonetic([search_text], names, rule.phonetic_bonus)
            print(f'  Score for {uuid_str}: {result.score}')

    await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
