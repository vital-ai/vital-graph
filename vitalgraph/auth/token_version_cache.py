"""
Token version cache with TTL expiry.

Provides an in-memory cache mapping username → token_version so that
access-token validation can detect revoked tokens without hitting the
database on every request. Entries expire after a configurable TTL
(default 60 seconds).
"""

import time
from typing import Dict, Optional, Tuple


class TokenVersionCache:
    """In-memory cache for user token versions with TTL expiry."""

    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._cache: Dict[str, Tuple[int, float]] = {}  # username → (version, expires_at)

    def get(self, username: str) -> Optional[int]:
        """Get cached token version, or None if expired/missing."""
        entry = self._cache.get(username)
        if entry is None:
            return None
        version, expires_at = entry
        if time.monotonic() > expires_at:
            del self._cache[username]
            return None
        return version

    def set(self, username: str, version: int) -> None:
        """Cache a token version with TTL."""
        self._cache[username] = (version, time.monotonic() + self.ttl)

    def invalidate(self, username: str) -> None:
        """Force-evict a user (called on password change, deactivation)."""
        self._cache.pop(username, None)

    def clear(self) -> None:
        """Clear entire cache (e.g. on server restart)."""
        self._cache.clear()
