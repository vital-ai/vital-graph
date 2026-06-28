#!/usr/bin/env python3
"""Quick check: are new entities arriving in the PostgreSQL entity registry?"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg
from vitalgraph.config.config_loader import VitalGraphConfig


async def main():
    config = VitalGraphConfig()
    db = config.get_database_config()
    pool = await asyncpg.create_pool(
        host=db.get('host', 'localhost'),
        port=int(db.get('port', 5432)),
        database=db.get('database', 'vitalgraph'),
        user=db.get('username', 'postgres'),
        password=db.get('password', ''),
        min_size=1, max_size=2,
    )
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM entity WHERE status = 'active'"
        )
        print(f"Total active entities: {total:,}")

        rows = await conn.fetch(
            "SELECT entity_id, primary_name, created_time "
            "FROM entity WHERE status = 'active' "
            "ORDER BY created_time DESC LIMIT 15"
        )
        print(f"\nMost recent 15 entities:")
        for r in rows:
            name = r['primary_name'][:60] if r['primary_name'] else '(no name)'
            print(f"  {r['created_time']}  {r['entity_id']}  {name}")

        for label, interval in [('30 min', '30 minutes'), ('1 hour', '1 hour'),
                                ('6 hours', '6 hours'), ('24 hours', '24 hours')]:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active' "
                f"AND created_time >= NOW() - INTERVAL '{interval}'"
            )
            print(f"  Created in last {label:>9s}: {count:,}")

    await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
