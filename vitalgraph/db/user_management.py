"""
User management database operations.

Provides a mixin class that adds user CRUD and space-access operations
to any DbImplInterface implementation. Uses the generic execute_query
and execute_update methods.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .common.models import UserData, UserSpaceAccess

logger = logging.getLogger(__name__)

# Valid roles
VALID_ROLES = ('admin', 'user', 'reader')


class UserManagementMixin:
    """Mixin providing user management DB operations.

    Requires self to implement execute_query() and execute_update()
    from DbImplInterface.
    """

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Fetch a single user by username. Returns dict or None."""
        rows = await self.execute_query(
            'SELECT user_id, username, password, password_hash, email, full_name, '
            'role, is_active, token_version, tenant, created_time, last_login, update_time '
            'FROM "user" WHERE username = $1',
            [username]
        )
        if not rows:
            return None
        row = rows[0]
        return row

    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single user by user_id. Returns dict or None."""
        rows = await self.execute_query(
            'SELECT user_id, username, password, password_hash, email, full_name, '
            'role, is_active, token_version, tenant, created_time, last_login, update_time '
            'FROM "user" WHERE user_id = $1',
            [user_id]
        )
        if not rows:
            return None
        return rows[0]

    async def list_all_users(self) -> List[Dict[str, Any]]:
        """List all users (without password fields exposed)."""
        rows = await self.execute_query(
            'SELECT user_id, username, email, full_name, role, is_active, '
            'token_version, tenant, created_time, last_login, update_time '
            'FROM "user" ORDER BY username'
        )
        return rows if rows else []

    async def count_active_admins(self) -> int:
        """Count active users with the admin role.

        Used to gate the bootstrap-admin fallback, which self-retires once a
        real admin exists in the database.
        """
        rows = await self.execute_query(
            'SELECT COUNT(*) AS n FROM "user" WHERE role = $1 AND is_active = true',
            ['admin']
        )
        if not rows:
            return 0
        return int(rows[0].get('n', 0) or 0)

    async def create_user(
        self,
        username: str,
        password_hash: str,
        role: str = 'user',
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        tenant: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a new user. Returns the created user dict or None on failure.

        Raises ValueError if role is invalid or username already exists.
        """
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {VALID_ROLES}")

        try:
            rows = await self.execute_query(
                'INSERT INTO "user" (username, password_hash, email, full_name, role, tenant) '
                'VALUES ($1, $2, $3, $4, $5, $6) RETURNING user_id, username, email, full_name, '
                'role, is_active, token_version, tenant, created_time',
                [username, password_hash, email, full_name, role, tenant]
            )
            if rows:
                return rows[0]
            return None
        except Exception as e:
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                raise ValueError(f"Username '{username}' already exists")
            raise

    async def update_user(
        self,
        user_id: int,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> bool:
        """Update user fields. Only non-None values are updated.

        If role is changed to 'reader', this also downgrades all space
        access entries to 'r'.
        """
        updates = []
        params = []
        idx = 1

        if email is not None:
            updates.append(f"email = ${idx}")
            params.append(email)
            idx += 1
        if full_name is not None:
            updates.append(f"full_name = ${idx}")
            params.append(full_name)
            idx += 1
        if role is not None:
            if role not in VALID_ROLES:
                raise ValueError(f"Invalid role '{role}'. Must be one of: {VALID_ROLES}")
            updates.append(f"role = ${idx}")
            params.append(role)
            idx += 1
        if is_active is not None:
            updates.append(f"is_active = ${idx}")
            params.append(is_active)
            idx += 1
            # Bump token_version to invalidate tokens on deactivation
            if not is_active:
                updates.append("token_version = token_version + 1")

        if not updates:
            return True

        updates.append(f"update_time = ${idx}")
        params.append(datetime.utcnow())
        idx += 1

        params.append(user_id)
        query = f'UPDATE "user" SET {", ".join(updates)} WHERE user_id = ${idx}'

        await self.execute_update(query, params)

        # If role changed to reader, downgrade all space access to 'r'
        if role == 'reader':
            await self.execute_update(
                "UPDATE user_space_access SET access_level = 'r' WHERE user_id = $1 AND access_level = 'rw'",
                [user_id]
            )

        return True

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user and cascade space access."""
        await self.execute_update('DELETE FROM "user" WHERE user_id = $1', [user_id])
        return True

    async def update_user_password_hash(self, username: str, password_hash: str) -> bool:
        """Update the password hash for a user (also bumps token_version)."""
        await self.execute_update(
            'UPDATE "user" SET password_hash = $1, password = NULL, '
            'token_version = token_version + 1 WHERE username = $2',
            [password_hash, username]
        )
        return True

    async def bump_token_version(self, user_id: int) -> bool:
        """Increment token_version to invalidate all issued tokens."""
        await self.execute_update(
            'UPDATE "user" SET token_version = token_version + 1 WHERE user_id = $1',
            [user_id]
        )
        return True

    async def update_last_login(self, username: str) -> None:
        """Record last login timestamp."""
        try:
            await self.execute_update(
                'UPDATE "user" SET last_login = $1 WHERE username = $2',
                [datetime.utcnow(), username]
            )
        except Exception:
            pass  # Non-critical

    # ------------------------------------------------------------------
    # Space Access
    # ------------------------------------------------------------------

    async def get_user_spaces(self, user_id: int) -> Dict[str, str]:
        """Get user's space access map: {space_id: access_level}.

        Returns dict like {"space_a": "rw", "space_b": "r"}.
        """
        rows = await self.execute_query(
            'SELECT space_id, access_level FROM user_space_access WHERE user_id = $1',
            [user_id]
        )
        if not rows:
            return {}
        return {row["space_id"]: row["access_level"] for row in rows}

    async def set_user_space_access(
        self,
        user_id: int,
        space_id: str,
        access_level: str,
        granted_by: Optional[str] = None,
    ) -> bool:
        """Grant or update space access for a user.

        Validates that readers cannot be assigned 'rw'.
        Uses upsert (INSERT ... ON CONFLICT UPDATE).
        """
        if access_level not in ('rw', 'r'):
            raise ValueError(f"access_level must be 'rw' or 'r', got '{access_level}'")

        # Validate reader constraint
        if access_level == 'rw':
            user = await self.get_user_by_id(user_id)
            if user and user.get("role") == 'reader':
                raise ValueError("Cannot assign 'rw' access to a reader role user")

        await self.execute_update(
            'INSERT INTO user_space_access (user_id, space_id, access_level, granted_by) '
            'VALUES ($1, $2, $3, $4) '
            'ON CONFLICT (user_id, space_id) DO UPDATE SET access_level = $3, granted_by = $4, granted_time = now()',
            [user_id, space_id, access_level, granted_by]
        )
        return True

    async def revoke_user_space_access(self, user_id: int, space_id: str) -> bool:
        """Remove a user's access to a specific space."""
        await self.execute_update(
            'DELETE FROM user_space_access WHERE user_id = $1 AND space_id = $2',
            [user_id, space_id]
        )
        return True

    async def set_user_spaces_bulk(
        self,
        user_id: int,
        spaces: Dict[str, str],
        granted_by: Optional[str] = None,
    ) -> bool:
        """Replace all space access for a user with the provided map.

        Args:
            user_id: Target user.
            spaces: Dict of {space_id: access_level}.
            granted_by: Admin username performing the grant.
        """
        # Validate reader constraint
        user = await self.get_user_by_id(user_id)
        if user and user.get("role") == 'reader':
            for level in spaces.values():
                if level == 'rw':
                    raise ValueError("Cannot assign 'rw' access to a reader role user")

        # Remove existing access
        await self.execute_update(
            'DELETE FROM user_space_access WHERE user_id = $1',
            [user_id]
        )

        # Insert new access entries
        for space_id, access_level in spaces.items():
            if access_level not in ('rw', 'r'):
                raise ValueError(f"access_level must be 'rw' or 'r', got '{access_level}'")
            await self.execute_update(
                'INSERT INTO user_space_access (user_id, space_id, access_level, granted_by) '
                'VALUES ($1, $2, $3, $4)',
                [user_id, space_id, access_level, granted_by]
            )

        return True

    async def list_users_for_space(self, space_id: str) -> List[Dict[str, Any]]:
        """List all users that have access to a specific space."""
        rows = await self.execute_query(
            'SELECT u.user_id, u.username, u.email, u.full_name, u.role, u.is_active, '
            'usa.access_level '
            'FROM "user" u JOIN user_space_access usa ON u.user_id = usa.user_id '
            'WHERE usa.space_id = $1 ORDER BY u.username',
            [space_id]
        )
        return rows if rows else []

    # ------------------------------------------------------------------
    # API Key Management
    # ------------------------------------------------------------------

    async def create_api_key(
        self,
        user_id: int,
        name: str,
        key_prefix: str,
        key_hash: str,
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Insert a new API key record. Returns the created record."""
        rows = await self.execute_query(
            'INSERT INTO api_key (user_id, name, key_prefix, key_hash, expires_at) '
            'VALUES ($1, $2, $3, $4, $5) '
            'RETURNING key_id, key_prefix, name, user_id, is_active, created_time, expires_at',
            [user_id, name, key_prefix, key_hash, expires_at]
        )
        return dict(rows[0]) if rows else {}

    async def list_api_keys(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List API keys, optionally filtered by user. Never returns key_hash."""
        if user_id is not None:
            rows = await self.execute_query(
                'SELECT ak.key_id, ak.key_prefix, ak.name, ak.is_active, '
                'ak.created_time, ak.last_used, ak.expires_at, '
                'u.username '
                'FROM api_key ak JOIN "user" u ON ak.user_id = u.user_id '
                'WHERE ak.user_id = $1 ORDER BY ak.created_time DESC',
                [user_id]
            )
        else:
            rows = await self.execute_query(
                'SELECT ak.key_id, ak.key_prefix, ak.name, ak.is_active, '
                'ak.created_time, ak.last_used, ak.expires_at, '
                'u.username '
                'FROM api_key ak JOIN "user" u ON ak.user_id = u.user_id '
                'ORDER BY ak.created_time DESC',
                []
            )
        return rows if rows else []

    async def get_api_keys_by_prefix(self, prefix: str) -> List[Dict[str, Any]]:
        """Lookup active API keys by prefix. Returns full records including key_hash."""
        rows = await self.execute_query(
            'SELECT ak.key_id, ak.key_prefix, ak.key_hash, ak.name, '
            'ak.user_id, ak.is_active, ak.expires_at, ak.last_used, '
            'u.username, u.role, u.is_active as user_is_active '
            'FROM api_key ak JOIN "user" u ON ak.user_id = u.user_id '
            'WHERE ak.key_prefix = $1 AND ak.is_active = true',
            [prefix]
        )
        return rows if rows else []

    async def get_api_key_by_id(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get a single API key by its UUID."""
        rows = await self.execute_query(
            'SELECT ak.key_id, ak.key_prefix, ak.name, ak.user_id, '
            'ak.is_active, ak.created_time, ak.last_used, ak.expires_at, '
            'u.username '
            'FROM api_key ak JOIN "user" u ON ak.user_id = u.user_id '
            'WHERE ak.key_id = $1::uuid',
            [key_id]
        )
        return dict(rows[0]) if rows else None

    async def deactivate_api_key(self, key_id: str) -> bool:
        """Set is_active = false for the key."""
        await self.execute_update(
            'UPDATE api_key SET is_active = false WHERE key_id = $1::uuid',
            [key_id]
        )
        return True

    async def update_api_key_last_used(self, key_id: str) -> None:
        """Update last_used timestamp. Best-effort."""
        try:
            await self.execute_update(
                'UPDATE api_key SET last_used = now() WHERE key_id = $1::uuid',
                [key_id]
            )
        except Exception:
            pass  # fire-and-forget

    async def count_user_api_keys(self, user_id: int) -> int:
        """Count active API keys for a user."""
        rows = await self.execute_query(
            'SELECT COUNT(*) as cnt FROM api_key WHERE user_id = $1 AND is_active = true',
            [user_id]
        )
        return rows[0]['cnt'] if rows else 0
