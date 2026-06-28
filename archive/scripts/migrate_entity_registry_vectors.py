"""
One-time migration: create entity registry vector/FTS/geo tables.

Idempotent — all DDL uses CREATE TABLE IF NOT EXISTS.
"""
import asyncio
import asyncpg
from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.entity_registry.entity_registry_vector_schema import (
    create_tables_sql, seed_default_index_sql,
)


async def migrate():
    config = VitalGraphConfig()
    db = config.get_database_config()
    pool = await asyncpg.create_pool(
        host=db.get('host', 'localhost'),
        port=int(db.get('port', 5432)),
        user=db.get('username', 'postgres'),
        password=db.get('password', ''),
        database=db.get('database', 'vitalgraph'),
        min_size=1, max_size=2,
    )
    stmts = create_tables_sql()
    async with pool.acquire() as conn:
        # Ensure pgvector and postgis extensions
        await conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
        await conn.execute('CREATE EXTENSION IF NOT EXISTS postgis')
        for i, sql in enumerate(stmts, 1):
            await conn.execute(sql)
            print(f'  [{i}/{len(stmts)}] OK')
        # Seed default index
        await conn.execute(seed_default_index_sql())
        print('  Default index seeded.')
    await pool.close()
    print('Done — all entity registry vector/FTS/geo tables created.')


if __name__ == '__main__':
    asyncio.run(migrate())
