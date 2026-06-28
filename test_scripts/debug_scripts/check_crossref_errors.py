"""Check which entities from entity_location don't exist in Weaviate."""
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
    from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex, entity_id_to_weaviate_uuid
    from vitalgraph.config.config_loader import get_scoped_env

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

    # Get all entity IDs that have locations in PG
    async with pool.acquire() as conn:
        pg_entity_ids = await conn.fetch(
            "SELECT DISTINCT entity_id FROM entity_location WHERE status = 'active'"
        )
    pg_ids = {r['entity_id'] for r in pg_entity_ids}
    print(f"PG entities with locations: {len(pg_ids):,}")

    # Sample check: pick 500 random entity IDs and check if they exist in Weaviate
    import random
    sample = random.sample(sorted(pg_ids), min(500, len(pg_ids)))

    missing = []
    for eid in sample:
        uuid = entity_id_to_weaviate_uuid(eid)
        try:
            obj = await weaviate_index.collection.query.fetch_object_by_id(uuid)
            if obj is None:
                missing.append(eid)
        except Exception:
            missing.append(eid)

    print(f"Sample: {len(sample)} checked, {len(missing)} missing from Weaviate ({len(missing)/len(sample)*100:.1f}%)")
    if missing:
        print(f"Estimated total missing: ~{int(len(missing)/len(sample)*len(pg_ids)):,}")
        print(f"Sample missing IDs: {missing[:10]}")

        # Check status of missing entities in PG
        async with pool.acquire() as conn:
            for eid in missing[:5]:
                row = await conn.fetchrow(
                    "SELECT entity_id, status, primary_name FROM entity WHERE entity_id = $1", eid
                )
                if row:
                    print(f"  {row['entity_id']}: status={row['status']}, name={row['primary_name']}")
                else:
                    print(f"  {eid}: NOT FOUND in entity table")

    await pool.close()
    await weaviate_index.close()


asyncio.run(main())
