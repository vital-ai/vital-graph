"""Check which location IDs from entity_location don't exist in Weaviate LocationIndex."""
import asyncio
import os
import sys
import logging

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['VITALGRAPH_ENVIRONMENT'] = 'prod'

logging.basicConfig(level=logging.WARNING, format='%(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)


async def main():
    import asyncpg
    from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex, location_id_to_weaviate_uuid

    pool = await asyncpg.create_pool(
        host=os.getenv('PROD_RDS_HOST'),
        port=int(os.getenv('PROD_RDS_PORT', '5432')),
        database=os.getenv('PROD_RDS_DBNAME'),
        user=os.getenv('PROD_RDS_USERNAME'),
        password=os.getenv('PROD_RDS_PASSWORD'),
        min_size=1, max_size=2,
    )

    weaviate_index = await EntityWeaviateIndex.from_env()
    if not weaviate_index:
        print("Failed to connect to Weaviate")
        return

    # Get all distinct location IDs from entity_location
    async with pool.acquire() as conn:
        pg_loc_rows = await conn.fetch(
            "SELECT DISTINCT location_id FROM entity_location WHERE status = 'active'"
        )
    pg_loc_ids = {r['location_id'] for r in pg_loc_rows}
    print(f"PG distinct location IDs: {len(pg_loc_ids):,}")

    # Sample check
    import random
    sample = random.sample(sorted(pg_loc_ids), min(500, len(pg_loc_ids)))

    missing = []
    for lid in sample:
        uuid = location_id_to_weaviate_uuid(lid)
        try:
            obj = await weaviate_index.location_collection.query.fetch_object_by_id(uuid)
            if obj is None:
                missing.append(lid)
        except Exception:
            missing.append(lid)

    print(f"Sample: {len(sample)} checked, {len(missing)} missing from Weaviate ({len(missing)/len(sample)*100:.1f}%)")
    if missing:
        estimated = int(len(missing) / len(sample) * len(pg_loc_ids))
        print(f"Estimated total missing: ~{estimated:,}")
        print(f"Sample missing location IDs: {missing[:10]}")

        # Check what entities these belong to
        async with pool.acquire() as conn:
            for lid in missing[:5]:
                row = await conn.fetchrow(
                    "SELECT el.entity_id, el.location_id, el.status, e.primary_name "
                    "FROM entity_location el JOIN entity e ON el.entity_id = e.entity_id "
                    "WHERE el.location_id = $1", lid
                )
                if row:
                    print(f"  loc {row['location_id']}: entity={row['entity_id']} "
                          f"({row['primary_name']}), status={row['status']}")

    await pool.close()
    await weaviate_index.close()


asyncio.run(main())
