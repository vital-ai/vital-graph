"""
VitalGraph Authentication module.

Manages JWT-based authentication with database-backed user storage,
bcrypt password hashing, and per-space access control.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from .api_key import is_api_key, extract_prefix, verify_api_key
from .audit import emit_audit_event
from .jwt_auth import JWTAuth
from .password import hash_password, verify_password
from .token_version_cache import TokenVersionCache

logger = logging.getLogger(__name__)

# Valid roles (ordered by privilege level)
VALID_ROLES = ('admin', 'user', 'reader')


class VitalGraphAuth:
    """JWT authentication handler with database-backed user management.

    Args:
        secret_key: JWT signing secret (required).
        db_impl: Database implementation providing user query methods.
                 May be None at init time if DB is connected later.
    """

    def __init__(self, secret_key: str, db_impl=None, token_version_cache_ttl: int = 60):
        self.jwt_auth = JWTAuth(secret_key)
        self.db_impl = db_impl
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")

        # Token version cache — reduces DB lookups for revocation checks
        self._token_version_cache = TokenVersionCache(ttl_seconds=token_version_cache_ttl)

        # First-run bootstrap admin: an in-memory, config/env-provided admin
        # credential honored ONLY while the DB has no real admin user yet, so a
        # fresh deployment can log in and provision the first real admin. It
        # self-retires permanently the moment a real admin exists.
        self._bootstrap_admin: Optional[Dict] = None
        # Latches True once a real admin is observed — bootstrap never re-enables
        # within this process after that.
        self._bootstrap_retired: bool = False

    def set_db_impl(self, db_impl) -> None:
        """Set or update the database implementation reference."""
        self.db_impl = db_impl

    def set_bootstrap_admin(self, username: str, password: str) -> None:
        """Configure the first-run bootstrap admin.

        Honored on both login and per-request authorization, but only while the
        database contains no active admin user. Use it to create the first real
        admin; once that exists, the bootstrap credential stops working.
        """
        self._bootstrap_admin = {
            "username": username,
            "password_hash": hash_password(password),
            "full_name": "Admin User",
            "email": "",
            "role": "admin",
            "is_active": True,
            "token_version": 0,
            "spaces": {},
        }

    async def _bootstrap_available(self, username: str) -> bool:
        """Whether the bootstrap admin may be used for ``username`` right now.

        True only when: a bootstrap admin is configured, it matches ``username``,
        it has not retired, and the DB has no active admin user yet. Retires
        permanently (for this process) as soon as a real admin is observed.

        If the DB is unreachable the service has no functionality anyway, so we
        do NOT enable bootstrap on error — it returns False rather than fail-open.
        """
        if not self._bootstrap_admin or self._bootstrap_retired:
            return False
        if self._bootstrap_admin["username"] != username:
            return False
        if self.db_impl is None:
            # DB not wired yet (very early startup) — allow bootstrap.
            return True
        try:
            admin_count = await self.db_impl.count_active_admins()
        except Exception as e:
            logger.warning(f"Bootstrap gate: admin-count query failed: {e}")
            return False
        if admin_count > 0:
            self._bootstrap_retired = True
            return False
        return True

    async def authenticate_user(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate a user by username and password.

        Checks the database first. Falls back to bootstrap admin if no
        DB users exist. Returns user dict on success, None on failure.
        """
        user = await self._get_user_from_db(username)

        if user is None:
            # Fallback to bootstrap admin, but only while no real admin exists.
            if await self._bootstrap_available(username):
                if verify_password(password, self._bootstrap_admin["password_hash"]):
                    emit_audit_event("auth.bootstrap.used", username, level="WARN")
                    return self._bootstrap_admin
            emit_audit_event("auth.login.failure", username, level="WARN",
                             reason="user_not_found")
            return None

        # Check active status
        if not user.get("is_active", True):
            emit_audit_event("auth.login.failure", username, level="WARN",
                             reason="account_inactive")
            return None

        # Verify password against hash
        stored_hash = user.get("password_hash")
        if stored_hash and verify_password(password, stored_hash):
            emit_audit_event("auth.login.success", username, method="password")
            return user

        # Legacy: check plaintext password column and auto-migrate
        stored_plain = user.get("password")
        if stored_plain and stored_plain == password:
            # Auto-migrate to hashed password
            await self._migrate_password_to_hash(username, password)
            emit_audit_event("auth.login.success", username, method="password_legacy")
            return user

        emit_audit_event("auth.login.failure", username, level="WARN",
                         reason="invalid_credentials")
        return None

    async def _get_user_from_db(self, username: str) -> Optional[Dict]:
        """Fetch user record from database including space access."""
        if self.db_impl is None:
            return None
        try:
            user = await self.db_impl.get_user_by_username(username)
            if user is None:
                return None
            # Attach spaces map
            spaces = await self.db_impl.get_user_spaces(user["user_id"])
            user["spaces"] = spaces
            return user
        except Exception as e:
            logger.warning(f"Failed to fetch user '{username}' from DB: {e}")
            return None

    async def _migrate_password_to_hash(self, username: str, password: str) -> None:
        """Auto-migrate a plaintext password to bcrypt hash."""
        if self.db_impl is None:
            return
        try:
            hashed = hash_password(password)
            await self.db_impl.update_user_password_hash(username, hashed)
            logger.info(f"Auto-migrated password to bcrypt for user '{username}'")
        except Exception as e:
            logger.warning(f"Failed to auto-migrate password for '{username}': {e}")

    def create_tokens(self, user_data: Dict, token_expiry_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Create access and refresh tokens for an authenticated user.

        The JWT payload includes role and per-space access map.
        """
        token_data = {
            "sub": user_data["username"],
            "full_name": user_data.get("full_name", ""),
            "email": user_data.get("email", ""),
            "role": user_data.get("role", "user"),
            "spaces": user_data.get("spaces", {}),
            "token_version": user_data.get("token_version", 0),
        }

        access_token = self.jwt_auth.create_access_token(
            token_data, expiry_seconds=token_expiry_seconds
        )
        refresh_token = self.jwt_auth.create_refresh_token(token_data)

        if token_expiry_seconds is not None:
            expires_in = token_expiry_seconds
        else:
            expires_in = self.jwt_auth.access_token_expire_minutes * 60

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    def invalidate_token_cache(self, username: str) -> None:
        """Invalidate cached token version for a user.

        Call this after password change, deactivation, role change, or
        explicit token revocation so the next request re-checks the DB.
        """
        self._token_version_cache.invalidate(username)

    async def _validate_api_key(self, token: str) -> Dict:
        """Validate an API key and return user dict.

        Steps:
        1. Extract prefix for DB lookup
        2. Find matching active keys by prefix
        3. Verify full key against bcrypt hash
        4. Check expiry and user active status
        5. Load user spaces
        6. Update last_used (fire-and-forget)
        """
        from datetime import datetime, timezone
        import asyncio

        prefix = extract_prefix(token)
        if not prefix:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key format",
            )

        if not self.db_impl:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available",
            )

        candidates = await self.db_impl.get_api_keys_by_prefix(prefix)
        if not candidates:
            emit_audit_event("auth.apikey.failure", "unknown", level="WARN",
                             reason="prefix_not_found", prefix=prefix)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Verify against each candidate (typically just 1)
        matched_key = None
        for candidate in candidates:
            if verify_api_key(token, candidate['key_hash']):
                matched_key = candidate
                break

        if not matched_key:
            emit_audit_event("auth.apikey.failure", "unknown", level="WARN",
                             reason="hash_mismatch", prefix=prefix)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Check expiry
        expires_at = matched_key.get('expires_at')
        if expires_at and expires_at < datetime.now(timezone.utc):
            emit_audit_event("auth.apikey.failure", matched_key['username'],
                             level="WARN", reason="expired",
                             key_id=str(matched_key['key_id']))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired",
            )

        # Check user is active
        if not matched_key.get('user_is_active', True):
            emit_audit_event("auth.apikey.failure", matched_key['username'],
                             level="WARN", reason="user_inactive")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive",
            )

        username = matched_key['username']

        # Load user spaces
        user = await self.db_impl.get_user_by_username(username)
        spaces = {}
        if user:
            spaces_data = await self.db_impl.get_user_spaces(user['user_id'])
            spaces = spaces_data if spaces_data else {}

        # Update last_used (fire-and-forget)
        key_id = str(matched_key['key_id'])
        try:
            asyncio.ensure_future(self.db_impl.update_api_key_last_used(key_id))
        except Exception:
            pass

        emit_audit_event("auth.apikey.used", username,
                         level="DEBUG", prefix=prefix)

        return {
            "username": username,
            "full_name": user.get("full_name", "") if user else "",
            "email": user.get("email", "") if user else "",
            "role": matched_key['role'],
            "spaces": spaces,
            "auth_method": "api_key",
            "api_key_id": key_id,
        }

    def create_get_current_user_dependency(self):
        """Create a FastAPI dependency that validates the JWT and returns user info.

        The returned user dict includes: username, full_name, email, role, spaces.
        Token version is checked against an in-memory cache (with DB fallback)
        to detect revoked tokens within the cache TTL window.
        """
        async def get_current_user(token: str = Depends(self.oauth2_scheme)) -> Dict:
            # API key detection: vg_ prefix
            if is_api_key(token):
                return await self._validate_api_key(token)

            # Try access token first
            try:
                payload = self.jwt_auth.verify_token(token, "access")
            except HTTPException:
                # Fall back to refresh token
                try:
                    payload = self.jwt_auth.verify_token(token, "refresh")
                except HTTPException:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired token",
                    )

            username = payload.get("sub")
            if not username:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token payload",
                )

            token_version_in_jwt = payload.get("token_version", 0)

            # Check token version against cache (DB fallback on miss)
            cached_version = self._token_version_cache.get(username)
            if cached_version is None and self.db_impl is not None:
                try:
                    user = await self.db_impl.get_user_by_username(username)
                except Exception as e:
                    # The service has no functionality without the DB, so failing
                    # open would only wave requests through to a dead backend.
                    # Fail closed with 503 instead.
                    logger.warning(f"Token version cache DB lookup failed for '{username}': {e}")
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Authentication backend unavailable",
                    )
                if user is None or not user.get("is_active", True):
                    # No DB row: honor the first-run bootstrap admin while no real
                    # admin exists yet, so a fresh deployment can provision one.
                    if await self._bootstrap_available(username):
                        emit_audit_event("auth.bootstrap.used", username, level="WARN")
                        return {
                            "username": self._bootstrap_admin["username"],
                            "full_name": self._bootstrap_admin["full_name"],
                            "email": self._bootstrap_admin["email"],
                            "role": self._bootstrap_admin["role"],
                            "spaces": self._bootstrap_admin["spaces"],
                            "token_version": self._bootstrap_admin["token_version"],
                        }
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="User not found or inactive",
                    )
                cached_version = user.get("token_version", 0)
                self._token_version_cache.set(username, cached_version)

            if cached_version is not None and token_version_in_jwt < cached_version:
                emit_audit_event("auth.token.revoked", username, level="WARN",
                                 token_version=token_version_in_jwt,
                                 current_version=cached_version)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                )

            # Build user dict from JWT claims (no DB hit on cache hit)
            return {
                "username": username,
                "full_name": payload.get("full_name", ""),
                "email": payload.get("email", ""),
                "role": payload.get("role", "user"),
                "spaces": payload.get("spaces", {}),
                "token_version": token_version_in_jwt,
            }

        return get_current_user
