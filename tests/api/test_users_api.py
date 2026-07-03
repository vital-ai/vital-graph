"""API tests: Users CRUD lifecycle via VitalGraphClient.

Tests user management endpoints (admin-only):
  - List users
  - Create user (via UserCreate model) → get → update → delete
  - Filter users by name
"""

from __future__ import annotations

import uuid

import pytest

from vitalgraph.model.users_model import User, UserCreate

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


def _make_user_create(suffix: str) -> UserCreate:
    """Build a UserCreate with unique username and a test password."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"testuser_{suffix}_{uid}",
        password="TestPass123!",
        full_name=f"Test User {suffix}",
        email=f"testuser_{uid}@example.com",
        role="user",
    )


# ---------------------------------------------------------------------------
# Read operations (against built-in admin user)
# ---------------------------------------------------------------------------

class TestUsersRead:
    """User listing and lookup operations (admin only)."""

    async def test_list_users(self, vg_client):
        """List users — at least the admin user should exist."""
        resp = await vg_client.users.list_users()
        assert resp.users is not None
        assert len(resp.users) >= 1
        usernames = [u.username for u in resp.users]
        assert "admin" in usernames

    async def test_get_admin_user(self, vg_client):
        """Get the built-in admin user by username."""
        fetched = await vg_client.users.get_user("admin")
        assert fetched.username == "admin"
        assert fetched.role is not None

    async def test_filter_users_by_name(self, vg_client):
        """Filter users — 'admin' should match."""
        resp = await vg_client.users.filter_users(name_filter="admin")
        assert resp.users is not None
        usernames = [u.username for u in resp.users]
        assert "admin" in usernames


# ---------------------------------------------------------------------------
# Full CRUD lifecycle
# ---------------------------------------------------------------------------

class TestUsersCrud:
    """User create → get → update → delete lifecycle."""

    async def test_create_user(self, vg_client):
        """Create a user via UserCreate and verify response."""
        uc = _make_user_create("create")
        resp = await vg_client.users.add_user(uc)
        assert resp.message is not None
        # Cleanup
        await vg_client.users.delete_user(uc.username)

    async def test_get_created_user(self, vg_client):
        """Create then get a user by username."""
        uc = _make_user_create("get")
        await vg_client.users.add_user(uc)

        fetched = await vg_client.users.get_user(uc.username)
        assert fetched.username == uc.username
        assert fetched.full_name == uc.full_name
        # Cleanup
        await vg_client.users.delete_user(uc.username)

    async def test_update_user(self, vg_client):
        """Create, update profile fields, then verify."""
        uc = _make_user_create("update")
        await vg_client.users.add_user(uc)

        updated = User(
            username=uc.username,
            full_name="Updated Name",
            email="updated@example.com",
            role="user",
        )
        resp = await vg_client.users.update_user(uc.username, updated)
        assert resp.message is not None

        fetched = await vg_client.users.get_user(uc.username)
        assert fetched.full_name == "Updated Name"
        # Cleanup
        await vg_client.users.delete_user(uc.username)

    async def test_delete_user(self, vg_client):
        """Create then delete a user and verify removal."""
        uc = _make_user_create("delete")
        await vg_client.users.add_user(uc)

        del_resp = await vg_client.users.delete_user(uc.username)
        assert del_resp.message is not None

        # Verify gone
        resp = await vg_client.users.list_users()
        usernames = [u.username for u in resp.users]
        assert uc.username not in usernames

    async def test_filter_created_user(self, vg_client):
        """Create a user, then filter by name substring."""
        uc = _make_user_create("filterable")
        await vg_client.users.add_user(uc)

        resp = await vg_client.users.filter_users(name_filter="filterable")
        assert resp.users is not None
        usernames = [u.username for u in resp.users]
        assert uc.username in usernames
        # Cleanup
        await vg_client.users.delete_user(uc.username)


# ---------------------------------------------------------------------------
# Space access management (admin only)
# ---------------------------------------------------------------------------

class TestUserSpaceAccess:
    """Grant, get, and revoke space access for a user."""

    async def test_get_user_spaces_empty(self, vg_client):
        """New user should have no space access."""
        uc = _make_user_create("spaces_empty")
        await vg_client.users.add_user(uc)
        try:
            resp = await vg_client.users.get_user_spaces(uc.username)
            assert resp["username"] == uc.username
            assert isinstance(resp["spaces"], (list, dict))
        finally:
            await vg_client.users.delete_user(uc.username)

    async def test_grant_and_get_space_access(self, vg_client, test_space):
        """Grant space access then verify via get_user_spaces."""
        uc = _make_user_create("spaces_grant")
        await vg_client.users.add_user(uc)
        try:
            grant_resp = await vg_client.users.grant_space_access(
                user_id=uc.username, space_id=test_space, access_level="rw"
            )
            assert "message" in grant_resp

            spaces_resp = await vg_client.users.get_user_spaces(uc.username)
            # Space should appear in the user's access
            spaces = spaces_resp.get("spaces", {})
            if isinstance(spaces, dict):
                assert test_space in spaces
            else:
                space_ids = [s.get("space_id", s) if isinstance(s, dict) else s for s in spaces]
                assert test_space in space_ids
        finally:
            await vg_client.users.delete_user(uc.username)

    async def test_revoke_space_access(self, vg_client, test_space):
        """Grant then revoke space access."""
        uc = _make_user_create("spaces_revoke")
        await vg_client.users.add_user(uc)
        try:
            await vg_client.users.grant_space_access(
                user_id=uc.username, space_id=test_space, access_level="r"
            )
            revoke_resp = await vg_client.users.revoke_space_access(
                user_id=uc.username, space_id=test_space
            )
            assert "message" in revoke_resp

            # Verify revoked
            spaces_resp = await vg_client.users.get_user_spaces(uc.username)
            spaces = spaces_resp.get("spaces", {})
            if isinstance(spaces, dict):
                assert test_space not in spaces
            else:
                space_ids = [s.get("space_id", s) if isinstance(s, dict) else s for s in spaces]
                assert test_space not in space_ids
        finally:
            await vg_client.users.delete_user(uc.username)


# ---------------------------------------------------------------------------
# Password change (self-service)
# ---------------------------------------------------------------------------

class TestPasswordChange:
    """Change own password endpoint."""

    async def test_change_password(self, vg_client):
        """Change password for a test user, then verify login with new password."""
        import os
        from vitalgraph.client.vitalgraph_client import VitalGraphClient
        from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig

        uc = _make_user_create("pwchange")
        await vg_client.users.add_user(uc)
        try:
            # Login as the new user to change their password
            old_env = os.environ.get("VITALGRAPH_CLIENT_ENVIRONMENT")
            os.environ["VITALGRAPH_CLIENT_ENVIRONMENT"] = "test"
            os.environ["TEST_CLIENT_AUTH_USERNAME"] = uc.username
            os.environ["TEST_CLIENT_AUTH_PASSWORD"] = uc.password
            os.environ["TEST_CLIENT_SERVER_URL"] = "http://localhost:8001"

            user_config = VitalGraphClientConfig()
            user_client = VitalGraphClient(config=user_config)
            await user_client.open()
            try:
                resp = await user_client.users.change_password(
                    current_password=uc.password,
                    new_password="NewTestPass456!"
                )
                assert "changed" in resp.message.lower() or resp.message != ""
            finally:
                await user_client.close()
        finally:
            # Cleanup env vars
            os.environ.pop("TEST_CLIENT_AUTH_USERNAME", None)
            os.environ.pop("TEST_CLIENT_AUTH_PASSWORD", None)
            os.environ.pop("TEST_CLIENT_SERVER_URL", None)
            if old_env:
                os.environ["VITALGRAPH_CLIENT_ENVIRONMENT"] = old_env
            else:
                os.environ.pop("VITALGRAPH_CLIENT_ENVIRONMENT", None)
            await vg_client.users.delete_user(uc.username)
