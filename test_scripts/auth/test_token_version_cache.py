"""
Unit tests for TokenVersionCache.

Tests cache hit, miss, expiry, invalidation, and clear operations.
Run: /opt/homebrew/anaconda3/envs/vital-graph/bin/python -m pytest test_scripts/auth/test_token_version_cache.py -v
"""

import time
from unittest.mock import patch

import pytest

from vitalgraph.auth.token_version_cache import TokenVersionCache


class TestTokenVersionCache:
    """Unit tests for TokenVersionCache."""

    def test_set_and_get(self):
        """Cache returns stored version on hit."""
        cache = TokenVersionCache(ttl_seconds=60)
        cache.set("alice", 3)
        assert cache.get("alice") == 3

    def test_miss_returns_none(self):
        """Cache returns None for unknown user."""
        cache = TokenVersionCache(ttl_seconds=60)
        assert cache.get("unknown") is None

    def test_expiry(self):
        """Cache returns None after TTL expires."""
        cache = TokenVersionCache(ttl_seconds=1)
        cache.set("bob", 5)
        assert cache.get("bob") == 5

        # Advance monotonic clock past TTL
        with patch("vitalgraph.auth.token_version_cache.time.monotonic") as mock_time:
            # First call is inside set (already happened), next calls are in get
            mock_time.return_value = time.monotonic() + 2
            assert cache.get("bob") is None

    def test_invalidate(self):
        """Invalidate removes user from cache."""
        cache = TokenVersionCache(ttl_seconds=60)
        cache.set("carol", 7)
        assert cache.get("carol") == 7
        cache.invalidate("carol")
        assert cache.get("carol") is None

    def test_invalidate_nonexistent(self):
        """Invalidate on missing user doesn't raise."""
        cache = TokenVersionCache(ttl_seconds=60)
        cache.invalidate("nobody")  # Should not raise

    def test_clear(self):
        """Clear removes all entries."""
        cache = TokenVersionCache(ttl_seconds=60)
        cache.set("alice", 1)
        cache.set("bob", 2)
        cache.clear()
        assert cache.get("alice") is None
        assert cache.get("bob") is None

    def test_overwrite(self):
        """Setting same user again overwrites version."""
        cache = TokenVersionCache(ttl_seconds=60)
        cache.set("dave", 1)
        cache.set("dave", 5)
        assert cache.get("dave") == 5

    def test_zero_ttl_always_misses(self):
        """TTL=0 means cache always returns None (disabled)."""
        cache = TokenVersionCache(ttl_seconds=0)
        cache.set("eve", 10)
        # With TTL=0, expires_at = monotonic() + 0, so immediate expiry
        # monotonic() will be >= expires_at on the very next call
        assert cache.get("eve") is None

    def test_multiple_users_independent(self):
        """Different users have independent cache entries."""
        cache = TokenVersionCache(ttl_seconds=60)
        cache.set("alice", 1)
        cache.set("bob", 2)
        cache.set("carol", 3)
        cache.invalidate("bob")
        assert cache.get("alice") == 1
        assert cache.get("bob") is None
        assert cache.get("carol") == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
