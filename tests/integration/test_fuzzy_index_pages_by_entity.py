"""Integration: the fuzzy index load does not drop aliases at a page boundary (`issues/252`).

`EntityFuzzyIndexPG._do_initialize` reads entities joined to their aliases, one
row per (entity, alias). It paged with `LIMIT` over those ROWS and started the
next page at `entity_id >` the last one, so an entity whose alias rows
straddled the cut lost the rest: its trailing aliases were never indexed, and a
search by one of them could not find the entity. It now pages by ENTITY.

Pinned by building the same data with a page far smaller than one entity's
alias rows and with one page, for a full rebuild and an incremental re-index:
the band rows must be identical. Runs in a scratch database.
"""

from __future__ import annotations

import datetime
import uuid

import asyncpg
import pytest
import pytest_asyncio

from .conftest import PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, skip_no_infra

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

BAND_TABLES = ("entity_fuzzy_band", "entity_fuzzy_phonetic_band")
WIDE = "e_0003"                     # the entity whose aliases straddle pages
ALIASES = ["Harbor Lights Plumbing", "Harborlight Plumbers", "HL Plumbing Co",
           "Lights of the Harbor", "Harbour Lite Pipes", "Bayview Plumbing"]


@pytest_asyncio.fixture(loop_scope="session")
async def scratch_pool():
    from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
    db = f"fuzzy_pages_{uuid.uuid4().hex[:8]}"
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
            await c.copy_records_to_table(
                "entity", records=[(f"e_{i:04d}", 2, f"Company Number {i}", "US", "FL",
                                    "Tampa", "active") for i in range(10)],
                columns=["entity_id", "entity_type_id", "primary_name", "country",
                         "region", "locality", "status"])
            # The write path upserts the alias type first (FK); so does this.
            await c.execute("INSERT INTO alias_type (type_key, type_label) "
                            "VALUES ('aka', 'aka') ON CONFLICT (type_key) DO NOTHING")
            await c.executemany(
                "INSERT INTO entity_alias (entity_id, alias_name) VALUES ($1, $2)",
                [(WIDE, a) for a in ALIASES] + [("e_0007", "Seventh Street Bakery")])
        yield pool
    finally:
        await pool.close()
        await admin.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        await admin.close()


async def _bands(pool):
    async with pool.acquire() as c:
        return {t: set(map(tuple, await c.fetch(
            f"SELECT band_id, band_hash, entity_key FROM {t}"))) for t in BAND_TABLES}


async def _build(pool, page_size, since=None):
    from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
    idx = EntityFuzzyIndexPG(pool=pool)
    if since is not None:
        await idx.initialize(pool, skip_lock=True, page_size=10_000)       # a base to replace
    await idx.initialize(pool, since=since, skip_lock=True, page_size=page_size)
    return await _bands(pool)


async def test_a_small_page_indexes_every_alias(scratch_pool):
    one_page = await _build(scratch_pool, page_size=10_000)
    assert all(one_page[t] for t in BAND_TABLES), "the index built nothing"
    # 2 entities per page: the boundary lands inside the wide entity's rows
    # under the old row-counted LIMIT (its 6 alias rows alone exceed a page).
    small = await _build(scratch_pool, page_size=2)
    assert small == one_page, (
        f"a page boundary lost band rows: "
        f"{sum(len(one_page[t] - small[t]) for t in BAND_TABLES)} missing")


async def test_an_incremental_reindex_with_small_pages_matches(scratch_pool):
    one_page = await _build(scratch_pool, page_size=10_000)
    epoch = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    small = await _build(scratch_pool, page_size=2, since=epoch)
    assert small == one_page
