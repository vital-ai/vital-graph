"""
In-memory LRU cache for count query results.

Stores integer counts keyed by (space_id, graph_id, query_hash) where
query_hash is a deterministic hash of the generated SPARQL count query string.

Simpler than EntityGraphCache — values are ints (no compression needed).
Invalidation is coarse-grained: any write to a (space_id, graph_id) invalidates
ALL cached counts for that graph, because a single entity change can affect
any filtered count.

Two eviction triggers: LRU entry count cap and TTL safety net.
"""

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CountCache:
    """LRU cache for SPARQL count query results."""

    def __init__(
        self,
        max_entries: int = 5_000,
        ttl_seconds: float = 900,  # 15 minutes
    ):
        self._cache: OrderedDict = OrderedDict()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds

        # Counters for observability
        self._hits: int = 0
        self._misses: int = 0
        self._evictions_lru: int = 0
        self._evictions_ttl: int = 0
        self._invalidations: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def query_hash(sparql: str) -> str:
        """Deterministic hash of a SPARQL query string for use as cache key."""
        return hashlib.sha256(sparql.encode("utf-8")).hexdigest()

    def get(self, space_id: str, graph_id: str, sparql_hash: str) -> Optional[int]:
        """Return cached count or None on miss / TTL expiry."""
        key = (space_id, graph_id, sparql_hash)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        count, ts = entry
        if time.time() - ts > self._ttl_seconds:
            self._cache.pop(key, None)
            self._evictions_ttl += 1
            self._misses += 1
            return None
        self._cache.move_to_end(key)
        self._hits += 1
        return count

    def put(self, space_id: str, graph_id: str, sparql_hash: str, count: int) -> None:
        """Store a count result."""
        key = (space_id, graph_id, sparql_hash)
        self._cache.pop(key, None)  # remove old entry if present
        self._cache[key] = (count, time.time())
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)
            self._evictions_lru += 1

    def invalidate_graph(self, space_id: str, graph_id: str) -> None:
        """Remove all cached counts for a given (space_id, graph_id)."""
        keys = [k for k in self._cache if k[0] == space_id and k[1] == graph_id]
        for k in keys:
            self._cache.pop(k, None)
            self._invalidations += 1

    def invalidate_space(self, space_id: str) -> None:
        """Remove all cached counts for a given space."""
        keys = [k for k in self._cache if k[0] == space_id]
        for k in keys:
            self._cache.pop(k, None)
            self._invalidations += 1

    # ------------------------------------------------------------------
    # Stats / observability
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict:
        total_requests = self._hits + self._misses
        return {
            "entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total_requests, 3) if total_requests else 0.0,
            "evictions_lru": self._evictions_lru,
            "evictions_ttl": self._evictions_ttl,
            "invalidations": self._invalidations,
        }

    def log_stats(self) -> None:
        """Log current cache statistics at INFO level."""
        s = self.stats
        logger.info(
            "CountCache stats: entries=%d hit_rate=%.1f%% "
            "hits=%d misses=%d invalidations=%d evictions(lru=%d ttl=%d)",
            s["entries"], s["hit_rate"] * 100,
            s["hits"], s["misses"], s["invalidations"],
            s["evictions_lru"], s["evictions_ttl"],
        )


# Module-level singleton — shared across all endpoint instances within one process.
# TTL raised from 15 minutes to 6 hours, because it is now a BACKSTOP rather
# than the mechanism. Until 2026-08-13 the quad write paths never invalidated,
# so the TTL was the only thing that made a count correct again and it had to be
# short. Writes now invalidate — add/remove of a quad, the batch and bulk
# variants, clear/drop graph, the SPARQL update path and the entity endpoints —
# so expiry is only needed for changes that bypass all of those.
#
# The cost of a short TTL is real and user-visible: the graph page's
# entity/frame/relation counts are a type-grouped aggregate over every vitaltype
# quad, measured at 3,343 ms warm and 9,722 ms cold on `sp_lead_synth_100k`.
# With a 15 minute TTL a user returning after lunch pays that again.
#
# Override with VITALGRAPH_COUNT_CACHE_TTL (seconds) if a deployment has write
# paths that do not invalidate.
def _ttl_from_env(default: float = 21_600.0) -> float:
    import os
    try:
        return float(os.environ.get("VITALGRAPH_COUNT_CACHE_TTL", default))
    except ValueError:
        return default


_count_cache = CountCache(ttl_seconds=_ttl_from_env())
