"""Integration: placeholder names stay out of the PG fuzzy index — issue 249.

Through the real registry and the real PG fuzzy index, against the test
database. Covers the issue's "Verify after fixing" list that does not need
production data: a placeholder matches nothing and has no bands; an entity with
a placeholder primary and a REAL alias is still found by the alias; the writer
can override the policy at create time and correct it later; an all-placeholder
entity still gets its hash, so the sync path does not re-index it forever; and
deleting a skipped entity leaves no orphan bands.

Requires PostgreSQL with the registry migrations applied
(`apps/entity_registry/migrate.py --migrate-only`).
"""

from __future__ import annotations

import random
import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest_asyncio.fixture(loop_scope="session")
async def reg(pg_pool):
    from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
    from vitalgraph.entity_registry.entity_registry_impl import EntityRegistryImpl
    has_col = await pg_pool.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'entity' AND column_name = 'is_placeholder_name'")
    if not has_col:
        pytest.skip("registry migrations not applied to the test database")
    fuzzy = EntityFuzzyIndexPG(pg_pool)
    registry = EntityRegistryImpl(pg_pool, fuzzy_index=fuzzy)
    created: list = []
    yield registry, fuzzy, created, pg_pool
    for eid in created:
        name = await pg_pool.fetchval(
            "SELECT primary_name FROM entity WHERE entity_id = $1", eid)
        await registry.delete_entity(eid, deleted_by="test-249")
        if name:
            await registry.purge_deleted_entities(primary_name=name)


def _placeholder() -> str:
    return f"company-9{random.randint(10**8, 10**9 - 1)}"


async def _create(reg_tuple, name, **kw):
    registry, _, created, _ = reg_tuple
    e = await registry.create_entity(type_key="business", primary_name=name,
                                     created_by="test-249", **kw)
    created.append(e["entity_id"])
    return e


async def _bands(pool, eid) -> tuple:
    p = await pool.fetchval(
        "SELECT count(*) FROM entity_fuzzy_band WHERE entity_key LIKE $1", f"{eid}::%")
    ph = await pool.fetchval(
        "SELECT count(*) FROM entity_fuzzy_phonetic_band WHERE entity_key LIKE $1",
        f"P::{eid}::%")
    return p, ph


async def test_a_placeholder_is_stored_flagged_and_gets_no_bands(reg):
    _, fuzzy, _, pool = reg
    e = await _create(reg, _placeholder())
    assert e["is_placeholder_name"] is True
    assert await _bands(pool, e["entity_id"]) == (0, 0)
    assert await fuzzy.storage.get_fuzzy_hash(e["entity_id"]), (
        "an all-placeholder entity must still have its hash, or the sync path "
        "re-indexes it on every pass")


async def test_placeholders_do_not_match_each_other(reg):
    """Before: `company-4471000` vs `company-4471008` scored 93.3, 'high'."""
    _, fuzzy, _, _ = reg
    a = await _create(reg, _placeholder())
    await _create(reg, a["primary_name"][:-1] + "7")
    assert await fuzzy.find_similar({"primary_name": a["primary_name"]}) == []


async def test_a_real_alias_on_a_placeholder_entity_is_still_found(reg):
    """The case an entity-level flag breaks: the alias must stay indexed."""
    _, fuzzy, _, pool = reg
    alias = f"Zyntrax Fabrication {uuid.uuid4().hex[:6]}"
    e = await _create(reg, _placeholder(), aliases=[{"alias_name": alias}])
    primary_bands, _ = await _bands(pool, e["entity_id"])
    assert primary_bands > 0
    keys = await pool.fetch(
        "SELECT DISTINCT entity_key FROM entity_fuzzy_band WHERE entity_key LIKE $1",
        f"{e['entity_id']}::%")
    assert {r["entity_key"] for r in keys} == {f"{e['entity_id']}::1"}, (
        "only the alias (variant 1) is banded; the placeholder (variant 0) is "
        "skipped without renumbering")
    hits = await fuzzy.find_similar({"primary_name": alias})
    assert e["entity_id"] in {h["entity_id"] for h in hits}


async def test_the_writer_can_override_the_policy(reg):
    _, _, _, pool = reg
    e = await _create(reg, _placeholder(), is_placeholder_name=False)
    assert e["is_placeholder_name"] is False
    assert (await _bands(pool, e["entity_id"]))[0] > 0


async def test_a_correction_reindexes_the_entity(reg):
    registry, fuzzy, _, pool = reg
    e = await _create(reg, _placeholder())
    before = await fuzzy.storage.get_fuzzy_hash(e["entity_id"])
    assert await _bands(pool, e["entity_id"]) == (0, 0)

    updated = await registry.update_entity(e["entity_id"], is_placeholder_name=False)
    assert updated["is_placeholder_name"] is False
    assert (await _bands(pool, e["entity_id"]))[0] > 0, (
        "correcting the flag must re-index the entity")
    assert await fuzzy.storage.get_fuzzy_hash(e["entity_id"]) != before


async def test_renaming_to_a_placeholder_drops_the_bands(reg):
    registry, _, _, pool = reg
    e = await _create(reg, f"Quorvane Logistics {uuid.uuid4().hex[:6]}")
    assert (await _bands(pool, e["entity_id"]))[0] > 0
    updated = await registry.update_entity(e["entity_id"], primary_name=_placeholder())
    assert updated["is_placeholder_name"] is True
    assert await _bands(pool, e["entity_id"]) == (0, 0)


async def test_a_placeholder_alias_is_skipped(reg):
    registry, _, _, pool = reg
    e = await _create(reg, f"Brennick Supply {uuid.uuid4().hex[:6]}")
    alias = await registry.add_alias(e["entity_id"], _placeholder())
    assert alias["is_placeholder_name"] is True
    keys = await pool.fetch(
        "SELECT DISTINCT entity_key FROM entity_fuzzy_band WHERE entity_key LIKE $1",
        f"{e['entity_id']}::%")
    assert {r["entity_key"] for r in keys} == {f"{e['entity_id']}::0"}


async def test_deleting_a_skipped_entity_leaves_no_bands(reg):
    registry, _, created, pool = reg
    alias = f"Velmont Partners {uuid.uuid4().hex[:6]}"
    e = await _create(reg, _placeholder(), aliases=[{"alias_name": alias}])
    assert (await _bands(pool, e["entity_id"]))[0] > 0
    await registry.delete_entity(e["entity_id"], deleted_by="test-249")
    assert await _bands(pool, e["entity_id"]) == (0, 0)


async def test_a_typo_query_with_geo_finds_its_target_first(reg):
    """`issues/248`: `'Aur Trdaing Corp'` with geo passed lost `'Aur Trading
    Corp'` entirely (rank 1 by name alone) because geo shingles let same-city
    entities crowd the candidate set. Geo is now a tie-break only."""
    _, fuzzy, _, _ = reg
    tag = uuid.uuid4().hex[:5]
    tampa = {"country": "US", "region": "FL", "locality": "Tampa"}
    target = await _create(reg, f"Aur Trading Corp {tag}", **tampa)
    for word in ("Harbor", "Sunset", "Palm", "Bayshore", "Gulf", "Coastal",
                 "Seminole", "Hillsborough", "Ybor", "Westshore"):
        await _create(reg, f"{word} Dental Group {tag}", **tampa)
    hits = await fuzzy.find_similar({"primary_name": f"Aur Trdaing Corp {tag}", **tampa})
    assert hits and hits[0]["entity_id"] == target["entity_id"], \
        [(h["primary_name"], h["score"]) for h in hits[:5]]
