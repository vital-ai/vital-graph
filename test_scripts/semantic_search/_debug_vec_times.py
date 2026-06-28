#!/usr/bin/env python3
"""Check vec table updated_time to see if sushi was overwritten."""
import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@host.docker.internal:5432/sparql_sql_graph"
    )
    sp = "sp_semantic_search_test"

    cnt = await conn.fetchval(f"SELECT count(*) FROM {sp}_vec_entity_vector")
    print(f"Total vec rows: {cnt}")

    # Sushi saito
    r = await conn.fetchrow(
        f"SELECT term_uuid FROM {sp}_term "
        "WHERE term_text = 'http://vital.ai/test/semantic/entity/sushi_saito'"
    )
    sushi_uuid = r["term_uuid"]

    vec_row = await conn.fetchrow(
        f"SELECT updated_time FROM {sp}_vec_entity_vector WHERE subject_uuid = $1",
        sushi_uuid,
    )
    print(f"Sushi updated_time: {vec_row['updated_time']}")

    # Group by time
    latest = await conn.fetch(
        f"SELECT updated_time, count(*) as n "
        f"FROM {sp}_vec_entity_vector "
        f"GROUP BY updated_time ORDER BY updated_time DESC LIMIT 5"
    )
    for row in latest:
        ut = row["updated_time"]
        n = row["n"]
        print(f"  {ut}: {n} rows")

    await conn.close()


asyncio.run(main())
