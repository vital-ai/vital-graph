"""Integration tests: purging soft-deleted registry entities — issue 035.

`delete_entity` is a soft delete, so tombstones accumulate for the life of the
database — one per delete, forever. A local stack reached 426 against 2 live
rows, and that residue caused real e2e failures (issues/022).

There is deliberately **no REST path** for this: destroying audit rows is a
maintenance action, not something a caller should be able to trigger over HTTP.
These tests exercise the low-level method directly.

Requires PostgreSQL.
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest.fixture
async def registry(pg_pool):
    from vitalgraph.entity_registry.entity_registry_impl import EntityRegistryImpl
    return EntityRegistryImpl(pg_pool)


async def _make_entity(registry, name):
    return await registry.create_entity(
        primary_name=name, type_key="person", created_by="test-035")


class TestPurgeDeletedEntities:

    async def test_purges_only_tombstones(self, registry):
        """A live entity with the same name must survive the purge."""
        name = f"purge-probe-{uuid.uuid4().hex[:8]}"
        doomed = await _make_entity(registry, name)
        keeper = await _make_entity(registry, name)
        await registry.delete_entity(doomed["entity_id"])

        purged = await registry.purge_deleted_entities(primary_name=name)
        assert purged == 1

        rows, total = await registry.search_entities(query=name, status="")
        assert total == 1
        assert rows[0]["entity_id"] == keeper["entity_id"]

        await registry.delete_entity(keeper["entity_id"])
        await registry.purge_deleted_entities(primary_name=name)

    async def test_tombstone_is_really_gone_not_just_hidden(self, registry):
        """`status='deleted'` is how a tombstone is still reachable after
        issue 035's filter change — so it is the honest check that the row is
        actually deleted rather than merely filtered out."""
        name = f"purge-gone-{uuid.uuid4().hex[:8]}"
        e = await _make_entity(registry, name)
        await registry.delete_entity(e["entity_id"])

        _, before = await registry.search_entities(query=name, status="deleted")
        assert before == 1

        await registry.purge_deleted_entities(primary_name=name)

        _, after = await registry.search_entities(query=name, status="deleted")
        assert after == 0

    async def test_is_idempotent(self, registry):
        name = f"purge-idem-{uuid.uuid4().hex[:8]}"
        e = await _make_entity(registry, name)
        await registry.delete_entity(e["entity_id"])
        assert await registry.purge_deleted_entities(primary_name=name) == 1
        assert await registry.purge_deleted_entities(primary_name=name) == 0

    async def test_no_tombstones_is_a_noop(self, registry):
        name = f"purge-none-{uuid.uuid4().hex[:8]}"
        e = await _make_entity(registry, name)
        try:
            assert await registry.purge_deleted_entities(primary_name=name) == 0
            _, total = await registry.search_entities(query=name, status="")
            assert total == 1, "a live entity must not be touched"
        finally:
            await registry.delete_entity(e["entity_id"])
            await registry.purge_deleted_entities(primary_name=name)


class TestStatusFilterExcludesTheGraveyard:
    """Issue 035 item 5: an empty status means "any status except deleted",
    not "literally everything". The old reading is what made the e2e registry
    cleanup page through tombstones and silently do nothing."""

    async def test_empty_status_excludes_deleted(self, registry):
        name = f"filter-probe-{uuid.uuid4().hex[:8]}"
        e = await _make_entity(registry, name)
        await registry.delete_entity(e["entity_id"])
        try:
            _, empty_filter = await registry.search_entities(query=name, status="")
            assert empty_filter == 0
        finally:
            await registry.purge_deleted_entities(primary_name=name)

    async def test_deleted_is_still_reachable_by_name(self, registry):
        """Excluding tombstones by default must not make them unreachable —
        otherwise nothing could audit or purge them."""
        name = f"filter-dele-{uuid.uuid4().hex[:8]}"
        e = await _make_entity(registry, name)
        await registry.delete_entity(e["entity_id"])
        try:
            _, total = await registry.search_entities(query=name, status="deleted")
            assert total == 1
        finally:
            await registry.purge_deleted_entities(primary_name=name)

    async def test_active_still_works(self, registry):
        name = f"filter-act-{uuid.uuid4().hex[:8]}"
        e = await _make_entity(registry, name)
        try:
            _, total = await registry.search_entities(query=name, status="active")
            assert total == 1
        finally:
            await registry.delete_entity(e["entity_id"])
            await registry.purge_deleted_entities(primary_name=name)
