"""Integration: the bulk fuzzy rebuild restores exactly what it dropped.

`apps/fuzzy_index/migrate_fuzzy_redis_to_pg.py --rebuild` drops the band tables'
primary keys and indexes for the load and recreates them afterwards, because
maintaining them row by row made a production-sized rebuild a 3+ hour window
(`issues/248`, measured 2026-10-11). Dropping indexes on a live table is only
safe if they always come back, identically, so these pin that:

* the bulk and in-place rebuilds produce the SAME band rows and the SAME index
  definitions;
* a duplicate row from a concurrent writer does not stop the primary key from
  being rebuilt;
* a load that fails still restores the indexes.

Runs in a scratch database with its own registry schema, so it neither reads nor
truncates the test stack's own fuzzy index.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from .conftest import PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, skip_no_infra

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

ROOT = Path(__file__).resolve().parents[2]


def _rebuild_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_fuzzy", ROOT / "apps" / "fuzzy_index" / "migrate_fuzzy_redis_to_pg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NAMES = ["Beach Runners Landscaping", "Tropical Smoothie Cafe", "Aur Trading Corp",
         "Zenith Dental Group", "Rocking Rays Auto Detailing", "Dice Druid", "Cabral",
         "Harbor Lights Plumbing", "Summit Roofing", "Blue Fern Bakery"]


@pytest_asyncio.fixture(loop_scope="session")
async def scratch_pool(tmp_path, monkeypatch):
    from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
    db = f"fuzzy_bulk_{uuid.uuid4().hex[:8]}"
    conn = dict(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD)
    admin = await asyncpg.connect(database="postgres", **conn)
    await admin.execute(f"CREATE DATABASE {db}")
    pool = await asyncpg.create_pool(database=db, min_size=1, max_size=4, **conn)
    try:
        s = EntityRegistrySchema()
        async with pool.acquire() as c:
            for sql in s.create_tables_sql() + s.migrations_sql() + s.create_indexes_sql():
                await c.execute(sql)
            await c.execute(s.seed_entity_types_sql())
            rows = [(f"e_{i:04d}", 2, f"{NAMES[i % len(NAMES)]} {i}", "US", "FL", "Tampa", "active")
                    for i in range(300)]
            await c.copy_records_to_table(
                "entity", records=rows,
                columns=["entity_id", "entity_type_id", "primary_name", "country",
                         "region", "locality", "status"])
        monkeypatch.chdir(tmp_path)          # the rebuild writes its saved-DDL file to cwd
        yield pool
    finally:
        await pool.close()
        await admin.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        await admin.close()


async def _state(pool, mod):
    async with pool.acquire() as c:
        ddl = sorted(stmt for *_, stmt in await mod._band_index_ddl(c))
        bands = {t: set(map(tuple, await c.fetch(
            f"SELECT band_id, band_hash, entity_key FROM {t}"))) for t in mod.BAND_TABLES}
    return ddl, bands


async def test_bulk_and_in_place_rebuilds_agree(scratch_pool):
    mod = _rebuild_module()
    await mod.cmd_rebuild(scratch_pool, bulk=False)
    ddl_in_place, bands_in_place = await _state(scratch_pool, mod)
    await mod.cmd_rebuild(scratch_pool, bulk=True)
    ddl_bulk, bands_bulk = await _state(scratch_pool, mod)
    assert ddl_in_place, "the band tables have no indexes to compare"
    assert any("PRIMARY KEY" in d for d in ddl_bulk)
    assert ddl_bulk == ddl_in_place
    assert all(bands_bulk[t] for t in mod.BAND_TABLES), "the rebuild indexed nothing"
    assert bands_bulk == bands_in_place
    assert not list(Path.cwd().glob("fuzzy_band_indexes_*.sql")), \
        "the saved DDL outlived a successful restore"


async def test_a_concurrent_duplicate_does_not_block_the_primary_key(scratch_pool):
    mod = _rebuild_module()
    await mod.cmd_rebuild(scratch_pool, bulk=False)
    ddl_before, bands_before = await _state(scratch_pool, mod)
    async with scratch_pool.acquire() as c:
        ddl = await mod._band_index_ddl(c)
    await mod._drop_band_indexes(scratch_pool, ddl)
    async with scratch_pool.acquire() as c:
        # what a live writer and the rebuild both inserting one entity leaves behind
        await c.execute("INSERT INTO entity_fuzzy_band SELECT * FROM entity_fuzzy_band LIMIT 5")
    await mod._restore_band_indexes(scratch_pool, ddl)
    ddl_after, bands_after = await _state(scratch_pool, mod)
    assert ddl_after == ddl_before
    assert bands_after == bands_before
    async with scratch_pool.acquire() as c:
        n = await c.fetchval("SELECT count(*) FROM entity_fuzzy_band")
    assert n == len(bands_before["entity_fuzzy_band"]), "duplicates survived the restore"


async def test_a_failed_load_still_restores_the_indexes(scratch_pool, monkeypatch):
    mod = _rebuild_module()
    await mod.cmd_rebuild(scratch_pool, bulk=False)
    ddl_before, _ = await _state(scratch_pool, mod)
    from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG

    async def boom(self, *a, **k):
        raise RuntimeError("load failed")
    monkeypatch.setattr(EntityFuzzyIndexPG, "initialize", boom)
    with pytest.raises(RuntimeError, match="load failed"):
        await mod.cmd_rebuild(scratch_pool, bulk=True)
    ddl_after, _ = await _state(scratch_pool, mod)
    assert ddl_after == ddl_before
    # the restore succeeded, so its safety net is no longer needed
    assert not list(Path.cwd().glob("fuzzy_band_indexes_*.sql"))
