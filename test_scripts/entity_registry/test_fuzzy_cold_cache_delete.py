#!/usr/bin/env python3
"""issues/252 — remove_entity must delete EVERY variant from a COLD cache.

The old code rebuilt the key list from `_entity_cache[...]['_variant_count']`
and defaulted to 1 on a miss, so a removal in a fresh process deleted
`entity_id::0` and left every alias variant behind.

This runs the removal in a fresh process (so the cache is empty by
construction), asserts nothing is left, then re-adds the entity to restore the
local index.
"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import asyncpg

from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
from vitalgraph.entity_registry.entity_fuzzy_storage import (
    TABLE_PRIMARY, TABLE_PHONETIC, ENTITY_ID_EXPR,
)

ENTITY_ID = sys.argv[1] if len(sys.argv) > 1 else 'e_dd1kf9fu5g'


async def counts(pool, eid):
    async with pool.acquire() as conn:
        p = await conn.fetchval(
            f"SELECT COUNT(*) FROM {TABLE_PRIMARY} "
            f"WHERE {ENTITY_ID_EXPR[TABLE_PRIMARY]} = $1", eid)
        h = await conn.fetchval(
            f"SELECT COUNT(*) FROM {TABLE_PHONETIC} "
            f"WHERE {ENTITY_ID_EXPR[TABLE_PHONETIC]} = $1", eid)
        f = await conn.fetchval(
            "SELECT COUNT(*) FROM entity_fuzzy_hash WHERE entity_id = $1", eid)
    return p, h, f


async def load_entity(pool, eid):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT e.*, et.type_key FROM entity e "
            "JOIN entity_type et ON e.entity_type_id = et.type_id "
            "WHERE e.entity_id = $1", eid)
        if not row:
            return None
        entity = dict(row)
        aliases = await conn.fetch(
            "SELECT alias_name FROM entity_alias "
            "WHERE entity_id = $1 AND status = 'active'", eid)
        entity['aliases'] = [dict(a) for a in aliases]
    return entity


async def main():
    cfg = VitalGraphConfig().get_database_config()
    pool = await asyncpg.create_pool(
        host=cfg.get('host', 'localhost'), port=int(cfg.get('port', 5432)),
        database=cfg.get('database'), user=cfg.get('username'),
        password=cfg.get('password', ''), min_size=1, max_size=3,
    )
    try:
        entity = await load_entity(pool, ENTITY_ID)
        if not entity:
            print(f"FAIL: entity {ENTITY_ID} not found")
            return 1

        before = await counts(pool, ENTITY_ID)
        print(f"before remove : primary={before[0]} phonetic={before[1]} hash={before[2]}")
        if before[0] <= 21:
            print("WARNING: entity has a single variant — this cannot "
                  "demonstrate the default-to-1 bug. Pick a multi-alias entity.")

        idx = EntityFuzzyIndexPG.from_env(pool)
        assert not idx._entity_cache, "cache should be empty in a fresh process"
        await idx.remove_entity(ENTITY_ID)

        after = await counts(pool, ENTITY_ID)
        print(f"after remove  : primary={after[0]} phonetic={after[1]} hash={after[2]}")
        ok = after == (0, 0, 0)
        print("REMOVE:", "PASS — every variant gone from a cold cache" if ok
              else f"FAIL — {after[0]}/{after[1]} band rows survived")

        # Restore, also from this (now non-empty) process.
        idx2 = EntityFuzzyIndexPG.from_env(pool)
        await idx2.add_entity(ENTITY_ID, entity)
        restored = await counts(pool, ENTITY_ID)
        print(f"after re-add  : primary={restored[0]} phonetic={restored[1]} hash={restored[2]}")
        restored_ok = restored == before
        print("RESTORE:", "PASS" if restored_ok else f"FAIL — expected {before}")

        return 0 if (ok and restored_ok) else 1
    finally:
        await pool.close()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
