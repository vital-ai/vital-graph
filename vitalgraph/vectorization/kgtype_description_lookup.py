"""Cross-space lookup for KG Type descriptions.

Fetches type-specific description fields from the centralized sp_kg_types space
to enrich search text during vector/FTS population.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from vitalgraph.constants import (
    SP_KG_TYPES,
    SP_KG_TYPES_GRAPH,
    TYPE_DESCRIPTION_PROPERTIES,
    TYPE_URI_PROPERTIES,
)

logger = logging.getLogger(__name__)

# LRU-style cache: {type_uri: (description_text, timestamp)}
_CACHE: Dict[str, tuple] = {}
_CACHE_TTL_SECONDS = 600  # 10 minutes


class KGTypeDescriptionLookup:
    """Look up KGType descriptions from the centralized sp_kg_types space.

    Uses the per-space rdf_quad + term tables for sp_kg_types to resolve
    type-specific description properties (e.g. hasKGEntityTypeDescription).
    """

    SPACE_ID = SP_KG_TYPES
    GRAPH_ID = SP_KG_TYPES_GRAPH

    def __init__(self, mapping_type: str):
        """Initialize with the mapping_type to determine which description property to use.

        Args:
            mapping_type: One of 'kgentity', 'kgframe', 'kgdocument', 'kgslot'.
        """
        self.mapping_type = mapping_type
        self.type_uri_property = TYPE_URI_PROPERTIES.get(mapping_type)
        self.desc_property = TYPE_DESCRIPTION_PROPERTIES.get(mapping_type)

    async def get_description(self, conn, type_uri: str) -> Optional[str]:
        """Fetch the type-specific description for a single type URI.

        Args:
            conn: asyncpg connection.
            type_uri: The KGType URI (e.g., urn:kgtype:RestaurantEntity).

        Returns:
            The description text, or None if not found.
        """
        if not self.desc_property:
            return None

        # Check cache
        cached = _CACHE.get(type_uri)
        if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
            return cached[0]

        result = await self._fetch_description(conn, type_uri)
        _CACHE[type_uri] = (result, time.time())
        return result

    async def get_descriptions_batch(
        self, conn, type_uris: List[str]
    ) -> Dict[str, Optional[str]]:
        """Batch fetch descriptions for multiple type URIs.

        Returns:
            Dict mapping type_uri → description (or None).
        """
        if not self.desc_property or not type_uris:
            return {}

        now = time.time()
        results: Dict[str, Optional[str]] = {}
        to_fetch: List[str] = []

        for uri in type_uris:
            cached = _CACHE.get(uri)
            if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
                results[uri] = cached[0]
            else:
                to_fetch.append(uri)

        if to_fetch:
            fetched = await self._fetch_descriptions_batch(conn, to_fetch)
            now2 = time.time()
            for uri in to_fetch:
                desc = fetched.get(uri)
                _CACHE[uri] = (desc, now2)
                results[uri] = desc

        return results

    async def get_subject_type_uri(
        self, conn, space_id: str, subject_uuid, context_uuid
    ) -> Optional[str]:
        """Read the subject's type URI property from its own space.

        Args:
            conn: asyncpg connection.
            space_id: The space the subject lives in.
            subject_uuid: The subject's UUID.
            context_uuid: The graph context UUID.

        Returns:
            The type URI string, or None.
        """
        if not self.type_uri_property:
            return None

        term_table = f"{space_id}_term"
        quad_table = f"{space_id}_rdf_quad"

        sql = f"""
            SELECT ot.term_text
            FROM {quad_table} q
            JOIN {term_table} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_table} ot ON ot.term_uuid = q.object_uuid
            WHERE q.subject_uuid = $1
              AND q.context_uuid = $2
              AND pt.term_text = $3
              AND ot.term_type = 'U'
            LIMIT 1
        """
        row = await conn.fetchrow(sql, subject_uuid, context_uuid, self.type_uri_property)
        return row["term_text"] if row else None

    async def get_subject_type_uris_batch(
        self, conn, space_id: str, subject_uuids: List, context_uuid
    ) -> Dict:
        """Batch read type URIs for multiple subjects.

        Returns:
            Dict mapping subject_uuid → type_uri (or absent if none).
        """
        if not self.type_uri_property or not subject_uuids:
            return {}

        term_table = f"{space_id}_term"
        quad_table = f"{space_id}_rdf_quad"

        sql = f"""
            SELECT q.subject_uuid, ot.term_text
            FROM {quad_table} q
            JOIN {term_table} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_table} ot ON ot.term_uuid = q.object_uuid
            WHERE q.subject_uuid = ANY($1)
              AND q.context_uuid = $2
              AND pt.term_text = $3
              AND ot.term_type = 'U'
        """
        rows = await conn.fetch(sql, subject_uuids, context_uuid, self.type_uri_property)
        return {row["subject_uuid"]: row["term_text"] for row in rows}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_description(self, conn, type_uri: str) -> Optional[str]:
        """Fetch a single type description from sp_kg_types tables."""
        term_table = f"{self.SPACE_ID}_term"
        quad_table = f"{self.SPACE_ID}_rdf_quad"

        sql = f"""
            SELECT ot.term_text
            FROM {quad_table} q
            JOIN {term_table} st ON st.term_uuid = q.subject_uuid
            JOIN {term_table} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_table} ot ON ot.term_uuid = q.object_uuid
            WHERE st.term_text = $1
              AND pt.term_text = $2
              AND ot.term_type = 'L'
            LIMIT 1
        """
        row = await conn.fetchrow(sql, type_uri, self.desc_property)
        return row["term_text"] if row else None

    async def _fetch_descriptions_batch(
        self, conn, type_uris: List[str]
    ) -> Dict[str, str]:
        """Batch fetch descriptions from sp_kg_types tables."""
        term_table = f"{self.SPACE_ID}_term"
        quad_table = f"{self.SPACE_ID}_rdf_quad"

        sql = f"""
            SELECT st.term_text AS type_uri, ot.term_text AS description
            FROM {quad_table} q
            JOIN {term_table} st ON st.term_uuid = q.subject_uuid
            JOIN {term_table} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_table} ot ON ot.term_uuid = q.object_uuid
            WHERE st.term_text = ANY($1)
              AND pt.term_text = $2
              AND ot.term_type = 'L'
        """
        rows = await conn.fetch(sql, type_uris, self.desc_property)
        return {row["type_uri"]: row["description"] for row in rows}


def invalidate_cache(type_uri: Optional[str] = None):
    """Invalidate the description cache.

    Args:
        type_uri: If provided, invalidate only that entry. Otherwise clear all.
    """
    if type_uri:
        _CACHE.pop(type_uri, None)
    else:
        _CACHE.clear()
