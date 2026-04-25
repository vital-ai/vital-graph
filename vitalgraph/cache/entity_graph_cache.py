"""
In-memory LRU cache for entity graph quads with zlib compression and memory tracking.

Stores compressed serialized quads keyed by (space_id, graph_id, entity_uri).
On cache hit, decompresses and returns List[dict] directly — skipping the entire
SPARQL → GraphObject → quad conversion pipeline.

Two eviction triggers: LRU entry count cap and total byte cap.
TTL safety net bounds staleness if a NOTIFY signal is lost.
"""

import json
import logging
import time
import zlib
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class EntityGraphCache:
    """LRU cache for entity graph quads with zlib compression and memory tracking."""

    def __init__(
        self,
        max_entries: int = 10_000,
        ttl_seconds: float = 900,          # 15 minutes
        max_bytes: int = 256 * 1024 * 1024,  # 256 MB
    ):
        self._cache: OrderedDict = OrderedDict()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._max_bytes = max_bytes
        self._total_bytes: int = 0

        # Counters for observability
        self._hits: int = 0
        self._misses: int = 0
        self._evictions_lru: int = 0
        self._evictions_ttl: int = 0
        self._evictions_bytes: int = 0
        self._invalidations: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, space_id: str, graph_id: str, entity_uri: str) -> Optional[List[Any]]:
        """Return cached quads or None on miss / TTL expiry."""
        key = (space_id, graph_id, entity_uri)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        compressed, byte_size, ts = entry
        if time.time() - ts > self._ttl_seconds:
            self._remove(key)
            self._evictions_ttl += 1
            self._misses += 1
            return None
        self._cache.move_to_end(key)
        self._hits += 1
        return json.loads(zlib.decompress(compressed))

    def put(self, space_id: str, graph_id: str, entity_uri: str, quads: List[Any]) -> None:
        """Compress and store quads. Silently skips if byte cap would be exceeded."""
        key = (space_id, graph_id, entity_uri)
        # Remove old entry if present (reclaim bytes)
        if key in self._cache:
            self._remove(key)
        # Quad objects are Pydantic models — convert to dicts for JSON serialization
        serializable = [q.model_dump() if hasattr(q, 'model_dump') else q for q in quads]
        compressed = zlib.compress(json.dumps(serializable).encode(), level=1)  # fast compression
        byte_size = len(compressed)
        # Skip caching if total memory would exceed cap
        if self._total_bytes + byte_size > self._max_bytes:
            self._evictions_bytes += 1
            return
        self._cache[key] = (compressed, byte_size, time.time())
        self._cache.move_to_end(key)
        self._total_bytes += byte_size
        # Evict oldest if over entry count
        while len(self._cache) > self._max_entries:
            self._evict_oldest()
            self._evictions_lru += 1

    def contains(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """Check if an entity_uri is in the cache (ignores TTL for invalidation checks)."""
        return (space_id, graph_id, entity_uri) in self._cache

    def invalidate(self, space_id: str, graph_id: str, entity_uri: str) -> None:
        """Remove a single entity graph from the cache."""
        key = (space_id, graph_id, entity_uri)
        if key in self._cache:
            self._remove(key)
            self._invalidations += 1

    def invalidate_graph(self, space_id: str, graph_id: str) -> None:
        """Remove all entity graph entries for a given graph."""
        keys = [k for k in self._cache if k[0] == space_id and k[1] == graph_id]
        for k in keys:
            self._remove(k)
            self._invalidations += 1

    def invalidate_space(self, space_id: str) -> None:
        """Remove all entity graph entries for a given space."""
        keys = [k for k in self._cache if k[0] == space_id]
        for k in keys:
            self._remove(k)
            self._invalidations += 1

    # ------------------------------------------------------------------
    # SPARQL UPDATE support
    # ------------------------------------------------------------------

    def collect_invalidation_targets(
        self,
        ops: list,
        space_id: str,
    ) -> Set[Tuple[str, str]]:
        """Scan changed quads and return (graph_id, entity_uri) pairs to invalidate.

        Pure in-memory — no DB queries. Two rules per quad:
        1. Subject URI is a cached entity → invalidate it.
        2. Predicate is hasKGGraphURI → object is the entity URI to invalidate.

        For graph-level ops (CLEAR, DROP) returns all cached entries for that graph.
        """
        from ..db.jena_sparql.jena_types import (
            UpdateDataInsert, UpdateDataDelete, UpdateModify, UpdateDeleteWhere,
            UpdateClear, UpdateDrop,
        )

        HAS_KG_GRAPH_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"
        targets: Set[Tuple[str, str]] = set()  # (graph_id, entity_uri)

        for op in ops:
            # Graph-level ops → invalidate entire graph
            if isinstance(op, (UpdateClear, UpdateDrop)):
                g = getattr(op, 'graph', None)
                if g:
                    self.invalidate_graph(space_id, g)
                elif getattr(op, 'target', '') == 'ALL':
                    self.invalidate_space(space_id)
                continue

            quads: list = []
            if isinstance(op, UpdateDataInsert):
                quads = op.quads
            elif isinstance(op, UpdateDataDelete):
                quads = op.quads
            elif isinstance(op, UpdateModify):
                quads = op.delete_quads + op.insert_quads
            elif isinstance(op, UpdateDeleteWhere):
                quads = op.quads

            for q in quads:
                sub_uri = getattr(q.subject, 'uri', None)
                pred_uri = getattr(q.predicate, 'uri', None)
                obj_uri = getattr(q.object, 'uri', None)
                graph_uri = getattr(q.graph, 'uri', None) if q.graph else None

                # Rule 1: subject is a cached entity → invalidate it
                if sub_uri:
                    # Check all graphs in cache for this space + subject
                    matched = [k for k in self._cache
                               if k[0] == space_id and k[2] == sub_uri]
                    for k in matched:
                        targets.add((k[1], sub_uri))

                # Rule 2: quad is ?sub hasKGGraphURI ?entity_uri → invalidate ?entity_uri
                if pred_uri == HAS_KG_GRAPH_URI and obj_uri:
                    if graph_uri:
                        targets.add((graph_uri, obj_uri))
                    else:
                        # Check all graphs in cache for this entity URI
                        matched = [k for k in self._cache
                                   if k[0] == space_id and k[2] == obj_uri]
                        for k in matched:
                            targets.add((k[1], obj_uri))

        return targets

    # ------------------------------------------------------------------
    # Stats / observability
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict:
        total_requests = self._hits + self._misses
        return {
            "entries": len(self._cache),
            "total_bytes": self._total_bytes,
            "total_mb": round(self._total_bytes / (1024 * 1024), 2),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total_requests, 3) if total_requests else 0.0,
            "evictions_lru": self._evictions_lru,
            "evictions_ttl": self._evictions_ttl,
            "evictions_bytes_cap": self._evictions_bytes,
            "invalidations": self._invalidations,
        }

    def log_stats(self) -> None:
        """Log current cache statistics at INFO level."""
        s = self.stats
        logger.info(
            "EntityGraphCache stats: entries=%d size=%.1fMB hit_rate=%.1f%% "
            "hits=%d misses=%d invalidations=%d evictions(lru=%d ttl=%d bytes=%d)",
            s["entries"], s["total_mb"], s["hit_rate"] * 100,
            s["hits"], s["misses"], s["invalidations"],
            s["evictions_lru"], s["evictions_ttl"], s["evictions_bytes_cap"],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _remove(self, key: Tuple) -> None:
        entry = self._cache.pop(key, None)
        if entry:
            self._total_bytes -= entry[1]  # entry[1] = byte_size

    def _evict_oldest(self) -> None:
        if self._cache:
            _, entry = self._cache.popitem(last=False)
            self._total_bytes -= entry[1]


# Module-level singleton — shared across all endpoint instances within one process.
_entity_graph_cache = EntityGraphCache()
