"""API tests: Space lifecycle via VitalGraphClient.

Tests create, list, get, delete, info, analytics, update, and filter operations.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_spaces_crud.py
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import TEST_SPACE_PREFIX

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestSpaceLifecycle:
    """Full space CRUD lifecycle through the REST API."""

    async def test_list_spaces(self, vg_client):
        """List spaces returns success with a list."""
        resp = await vg_client.spaces.list_spaces()
        assert resp.is_success
        assert isinstance(resp.spaces, list)

    async def test_create_get_delete_space(self, vg_client):
        """Create → get → verify → delete lifecycle."""
        from vitalgraph.model.spaces_model import Space

        space_id = f"{TEST_SPACE_PREFIX}{uuid.uuid4().hex[:8]}"
        space = Space(
            space=space_id,
            space_name=f"API Test {space_id}",
            space_description="Ephemeral space for Tier 4 API tests",
        )

        # Create
        cr = await vg_client.spaces.create_space(space)
        assert cr.is_success, f"create failed: {cr.error_message}"

        try:
            # Get
            gr = await vg_client.spaces.get_space(space_id)
            assert gr.is_success
            assert gr.space is not None
            assert gr.space.space == space_id

            # List includes the new space
            lr = await vg_client.spaces.list_spaces()
            assert lr.is_success
            space_ids = [s.space for s in lr.spaces]
            assert space_id in space_ids

        finally:
            # Delete
            dr = await vg_client.spaces.delete_space(space_id)
            assert dr.is_success, f"delete failed: {dr.error_message}"

        # Verify deleted
        lr2 = await vg_client.spaces.list_spaces()
        remaining_ids = [s.space for s in lr2.spaces] if lr2.is_success else []
        assert space_id not in remaining_ids

    async def test_get_nonexistent_space(self, vg_client):
        """Getting a space that doesn't exist returns space=None."""
        gr = await vg_client.spaces.get_space(f"{TEST_SPACE_PREFIX}does_not_exist_999")
        assert gr.space is None or not gr.is_success


# ---------------------------------------------------------------------------
# Space Info
# ---------------------------------------------------------------------------

class TestSpaceInfo:
    """GET /spaces/info — detailed space metadata and statistics."""

    async def test_get_space_info(self, vg_client, test_space):
        """Get info for an existing space returns space + statistics."""
        resp = await vg_client.spaces.get_space_info(test_space)
        assert resp.is_success
        assert resp.space is not None
        assert resp.space.space == test_space

    async def test_get_space_info_statistics(self, vg_client, test_space):
        """Info response includes statistics dict."""
        resp = await vg_client.spaces.get_space_info(test_space)
        assert resp.is_success
        assert resp.statistics is not None
        assert isinstance(resp.statistics, dict)

    async def test_get_space_info_nonexistent(self, vg_client):
        """Info for nonexistent space returns error/None."""
        resp = await vg_client.spaces.get_space_info(f"{TEST_SPACE_PREFIX}no_such_space_xyz")
        assert not resp.is_success or resp.space is None


# ---------------------------------------------------------------------------
# Space Analytics
# ---------------------------------------------------------------------------

class TestSpaceAnalytics:
    """GET /spaces/analytics — KG analytics (entity/frame/relation distributions)."""

    async def test_get_space_analytics(self, vg_client, test_space):
        """Get analytics returns success."""
        resp = await vg_client.spaces.get_space_analytics(test_space)
        assert resp.success is True

    async def test_get_space_analytics_refresh(self, vg_client, test_space):
        """Get analytics with refresh=True forces recomputation."""
        resp = await vg_client.spaces.get_space_analytics(test_space, refresh=True)
        assert resp.success is True

    async def test_get_space_analytics_structure(self, vg_client, test_space):
        """Analytics response has expected structure."""
        resp = await vg_client.spaces.get_space_analytics(test_space, refresh=True)
        assert resp.success is True
        if resp.analytics:
            assert resp.analytics.space_id == test_space


# ---------------------------------------------------------------------------
# Space Update
# ---------------------------------------------------------------------------

class TestSpaceUpdate:
    """PUT /spaces — update space properties."""

    async def test_update_space_name(self, vg_client, test_space):
        """Update space display name."""
        from vitalgraph.model.spaces_model import Space

        space = Space(
            space=test_space,
            space_name=f"Updated Name {uuid.uuid4().hex[:4]}",
            space_description="Updated by API test",
        )
        resp = await vg_client.spaces.update_space(test_space, space)
        assert resp.is_success

    async def test_update_space_verify(self, vg_client, test_space):
        """Update and verify the change persists."""
        from vitalgraph.model.spaces_model import Space

        new_desc = f"Desc {uuid.uuid4().hex[:6]}"
        space = Space(
            space=test_space,
            space_name="Verify Update Test",
            space_description=new_desc,
        )
        await vg_client.spaces.update_space(test_space, space)

        gr = await vg_client.spaces.get_space(test_space)
        assert gr.is_success
        assert gr.space.space_description == new_desc


# ---------------------------------------------------------------------------
# Space Filter
# ---------------------------------------------------------------------------

class TestSpaceFilter:
    """GET /spaces/filter — filter spaces by name prefix."""

    async def test_filter_by_prefix(self, vg_client, test_space):
        """Filter by space_id (what list_spaces reports as name) should find the space."""
        # Known failure: Issue #012 — list_spaces returns space_id as space_name
        # but filter_spaces uses the real space_impl.space_name (which diverges
        # after update_space changes it).
        resp = await vg_client.spaces.filter_spaces(name_filter=test_space)
        assert resp.is_success
        assert resp.count >= 1
        assert any(s.space == test_space for s in resp.spaces)

    async def test_filter_no_results(self, vg_client):
        """Filter with nonsense prefix returns empty list."""
        resp = await vg_client.spaces.filter_spaces(name_filter="xyzzy_no_match_99")
        assert resp.is_success
        assert resp.count == 0


class TestSpaceDomainOutcomes:
    """Ordinary domain outcomes arrive as HTTP 200 with a status in the body.

    Creating a space that exists, and deleting one that does not, are not
    server faults. They used to be signalled with HTTP 500 and 404
    respectively (issue 034), which meant callers could not tell "already
    exists" from a genuine failure without string-matching a `detail` field,
    and clients that retry on 5xx retried a request that could never succeed.
    """

    async def _drop(self, vg_client, space_id):
        try:
            await vg_client.spaces.delete_space(space_id=space_id)
        except Exception:
            pass

    async def test_create_existing_space_is_a_domain_outcome(self, vg_client):
        from vitalgraph.model.spaces_model import Space

        space_id = f"{TEST_SPACE_PREFIX}dup_{uuid.uuid4().hex[:8]}"
        await self._drop(vg_client, space_id)
        space = Space(space=space_id, space_name="dup", space_description="d")
        try:
            first = await vg_client.spaces.add_space(space)
            assert first.is_success, "precondition: first create should succeed"

            # The second create must come back as a normal response, not raise
            # and not report a server fault.
            second = await vg_client.spaces.add_space(space)
            assert second.is_success is False
        finally:
            await self._drop(vg_client, space_id)

    async def test_delete_missing_space_is_a_domain_outcome(self, vg_client):
        space_id = f"{TEST_SPACE_PREFIX}gone_{uuid.uuid4().hex[:8]}"
        await self._drop(vg_client, space_id)

        result = await vg_client.spaces.delete_space(space_id=space_id)
        assert result.is_success is False

    async def test_delete_existing_space_still_succeeds(self, vg_client):
        """Guard the neighbour — the not-found branch must not swallow the
        real one."""
        from vitalgraph.model.spaces_model import Space

        space_id = f"{TEST_SPACE_PREFIX}del_{uuid.uuid4().hex[:8]}"
        await self._drop(vg_client, space_id)
        created = await vg_client.spaces.add_space(
            Space(space=space_id, space_name="del", space_description="d"))
        assert created.is_success

        result = await vg_client.spaces.delete_space(space_id=space_id)
        assert result.is_success is True

    async def test_create_is_repeatable_after_delete(self, vg_client):
        """The already-exists path must not leave the space unusable."""
        from vitalgraph.model.spaces_model import Space

        space_id = f"{TEST_SPACE_PREFIX}cyc_{uuid.uuid4().hex[:8]}"
        await self._drop(vg_client, space_id)
        space = Space(space=space_id, space_name="cyc", space_description="d")
        try:
            assert (await vg_client.spaces.add_space(space)).is_success
            assert (await vg_client.spaces.add_space(space)).is_success is False
            assert (await vg_client.spaces.delete_space(space_id=space_id)).is_success
            assert (await vg_client.spaces.add_space(space)).is_success
        finally:
            await self._drop(vg_client, space_id)
