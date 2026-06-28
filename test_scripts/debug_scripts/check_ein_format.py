"""Check how EIN identifiers are stored in production."""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

async def main():
    import asyncpg
    pool = await asyncpg.create_pool(
        host=os.getenv('PROD_RDS_HOST'),
        port=int(os.getenv('PROD_RDS_PORT', '5432')),
        database=os.getenv('PROD_RDS_DBNAME'),
        user=os.getenv('PROD_RDS_USERNAME'),
        password=os.getenv('PROD_RDS_PASSWORD'),
        min_size=1, max_size=2,
    )
    async with pool.acquire() as conn:
        # Sample EINs
        rows = await conn.fetch(
            "SELECT identifier_namespace, identifier_value, entity_id "
            "FROM entity_identifier "
            "WHERE identifier_namespace = 'EIN' AND status = 'active' "
            "LIMIT 10"
        )
        print("Sample EINs:")
        for r in rows:
            print(f"  {r['identifier_namespace']}:{r['identifier_value']} -> {r['entity_id']}")

        # Search for the specific value
        rows2 = await conn.fetch(
            "SELECT identifier_namespace, identifier_value, entity_id "
            "FROM entity_identifier "
            "WHERE (identifier_value LIKE '%320518589%' OR identifier_value LIKE '%32-0518589%') "
            "AND status = 'active'"
        )
        print(f"\nMatches for 320518589 / 32-0518589:")
        for r in rows2:
            print(f"  {r['identifier_namespace']}:{r['identifier_value']} -> {r['entity_id']}")

        # Count
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM entity_identifier WHERE identifier_namespace = 'EIN' AND status = 'active'"
        )
        print(f"\nTotal active EINs: {count}")
    await pool.close()

asyncio.run(main())
