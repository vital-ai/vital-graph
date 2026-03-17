"""
LRU cache for SPARQL sidecar compile responses.

Parameterizes SPARQL by replacing ``<URI>`` literals with indexed
placeholders so that structurally identical queries (differing only in
entity / graph / frame URIs) share a single cached algebra.

Cache flow:
  1. Parameterize: ``<http://actual/uri>`` → ``<urn:cparam:N>``
  2. SHA-256 the normalized SPARQL → cache key
  3. Miss → compile parameterized SPARQL via sidecar, store JSON
  4. Hit  → retrieve cached JSON
  5. Restore: replace ``urn:cparam:N`` → actual URIs in JSON, parse
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import OrderedDict
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Matches any URI enclosed in angle brackets (SPARQL IRI syntax).
_URI_RE = re.compile(r'<([^>\s]+)>')

# Placeholder prefix — a synthetic URN that will never collide with real data.
_PARAM_PREFIX = "urn:cparam:"


class SparqlCompileCache:
    """LRU cache for parameterized SPARQL compile results."""

    def __init__(self, maxsize: int = 512):
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compile(
        self,
        sparql: str,
        client,  # AsyncSidecarClient
    ) -> Dict[str, Any]:
        """Compile SPARQL via sidecar with transparent caching.

        Returns the raw JSON response dict, identical to
        ``await client.compile(sparql)`` but potentially served from cache.
        """
        normalized, uri_list = self._parameterize(sparql)
        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        cached_str = self._cache.get(key)
        if cached_str is not None:
            self._hits += 1
            self._cache.move_to_end(key)
            if (self._hits + self._misses) % 200 == 0:
                logger.info(
                    "compile-cache stats: %d hits, %d misses, %.1f%% hit-rate, %d entries",
                    self._hits, self._misses,
                    100.0 * self._hits / (self._hits + self._misses),
                    len(self._cache),
                )
            return self._restore(cached_str, uri_list)

        # Cache miss — call sidecar with parameterized query
        self._misses += 1
        raw = await client.compile(normalized)

        # Only cache successful compiles
        if raw.get("ok", False):
            cached_str = json.dumps(raw)
            self._cache[key] = cached_str
            self._cache.move_to_end(key)
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)
            return self._restore(cached_str, uri_list)

        # Error response — don't cache, but still restore URIs
        return self._restore(json.dumps(raw), uri_list)

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics for monitoring."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (self._hits / total * 100) if total else 0,
            "size": len(self._cache),
            "maxsize": self._maxsize,
        }

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()
        logger.info("compile-cache cleared")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _parameterize(sparql: str) -> Tuple[str, List[str]]:
        """Replace ``<URI>`` values with indexed placeholders.

        Returns ``(normalized_sparql, uri_list)`` where ``uri_list[i]``
        is the original URI for placeholder ``urn:cparam:i``.
        """
        seen: Dict[str, int] = {}
        uri_list: List[str] = []

        def _replacer(match: re.Match) -> str:
            uri = match.group(1)
            if uri not in seen:
                idx = len(uri_list)
                seen[uri] = idx
                uri_list.append(uri)
            return "<" + _PARAM_PREFIX + str(seen[uri]) + ">"

        normalized = _URI_RE.sub(_replacer, sparql)
        return normalized, uri_list

    @staticmethod
    def _restore(json_str: str, uri_list: List[str]) -> Dict[str, Any]:
        """Replace placeholders with actual URIs and parse JSON.

        Replaces in reverse index order to avoid ``urn:cparam:1``
        matching inside ``urn:cparam:10``.
        """
        for i in range(len(uri_list) - 1, -1, -1):
            json_str = json_str.replace(_PARAM_PREFIX + str(i), uri_list[i])
        return json.loads(json_str)
