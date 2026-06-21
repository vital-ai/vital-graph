"""Programmatic API for managing fuzzy_mapping + fuzzy_mapping_property rows.

Usage:
    manager = FuzzyMappingManager(conn, space_id)
    mid = await manager.create_mapping(index_name="entity_fuzzy",
                                        mapping_type="kgentity",
                                        enabled=True)
    await manager.add_property(mid, "http://...#hasName", property_role="primary")
    mappings = await manager.list_mappings()
    await manager.delete_mapping(mid)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class FuzzyMappingPropertyDTO:
    property_id: int
    mapping_id: int
    property_uri: str
    property_role: str = "include"
    ordinal: int = 0

    def to_dict(self) -> Dict:
        return {
            'property_id': self.property_id,
            'mapping_id': self.mapping_id,
            'property_uri': self.property_uri,
            'property_role': self.property_role,
            'ordinal': self.ordinal,
        }


@dataclass
class FuzzyMappingDTO:
    mapping_id: int
    mapping_type: str
    type_uri: Optional[str]
    index_name: str
    enabled: bool
    shingle_k: int
    num_perm: int
    lsh_threshold: float
    phonetic_bonus: float
    created_time: Optional[str] = None
    properties: List[FuzzyMappingPropertyDTO] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'mapping_id': self.mapping_id,
            'mapping_type': self.mapping_type,
            'type_uri': self.type_uri,
            'index_name': self.index_name,
            'enabled': self.enabled,
            'shingle_k': self.shingle_k,
            'num_perm': self.num_perm,
            'lsh_threshold': self.lsh_threshold,
            'phonetic_bonus': self.phonetic_bonus,
            'created_time': self.created_time,
            'properties': [p.to_dict() for p in self.properties],
        }


# ---------------------------------------------------------------------------
# Resolve helper (used by populator and SPARQL resolve)
# ---------------------------------------------------------------------------

RESOLVE_FUZZY_MAPPING_SQL = """
SELECT m.mapping_id, m.enabled, m.shingle_k, m.num_perm, m.lsh_threshold, m.phonetic_bonus
FROM {fuzzy_mapping} m
WHERE m.index_name = $1
  AND (
    (m.mapping_type = $2 AND m.type_uri = $3)
    OR (m.mapping_type = $2 AND m.type_uri IS NULL)
  )
ORDER BY m.type_uri IS NULL, m.mapping_id
LIMIT 1
"""

FUZZY_MAPPING_PROPERTIES_SQL = """
SELECT property_uri, property_role, ordinal
FROM {fuzzy_mapping_property}
WHERE mapping_id = $1
ORDER BY ordinal, property_id
"""

# Simpler: get the first enabled mapping for a space (any type)
RESOLVE_ANY_FUZZY_MAPPING_SQL = """
SELECT m.mapping_id, m.mapping_type, m.type_uri, m.enabled,
       m.shingle_k, m.num_perm, m.lsh_threshold, m.phonetic_bonus
FROM {fuzzy_mapping} m
WHERE m.enabled = TRUE
ORDER BY m.mapping_id
LIMIT 1
"""


@dataclass
class FuzzyMappingRule:
    """Resolved fuzzy mapping with its properties."""
    mapping_id: int
    enabled: bool = True
    shingle_k: int = 3
    num_perm: int = 64
    lsh_threshold: float = 0.3
    phonetic_bonus: float = 10.0
    mapping_type: Optional[str] = None
    include_uris: List[str] = field(default_factory=list)
    primary_uris: List[str] = field(default_factory=list)
    alias_uris: List[str] = field(default_factory=list)


async def resolve_fuzzy_mapping(
    conn,
    space_id: str,
    index_name: str,
    mapping_type: str,
    type_uri: Optional[str] = None,
) -> Optional[FuzzyMappingRule]:
    """Resolve the fuzzy mapping rule for a given index + KG type.

    Precedence:
    1. Specific type_uri match
    2. Class-level match (type_uri IS NULL)
    3. None (no fuzzy mapping configured)
    """
    sql = RESOLVE_FUZZY_MAPPING_SQL.format(
        fuzzy_mapping=f"{space_id}_fuzzy_mapping",
    )
    row = await conn.fetchrow(sql, index_name, mapping_type, type_uri)
    if row is None:
        return None

    rule = FuzzyMappingRule(
        mapping_id=row["mapping_id"],
        enabled=row["enabled"] if row["enabled"] is not None else True,
        shingle_k=row["shingle_k"] or 3,
        num_perm=row["num_perm"] or 64,
        lsh_threshold=row["lsh_threshold"] or 0.3,
        phonetic_bonus=row["phonetic_bonus"] or 10.0,
    )

    # Fetch child property rows
    prop_sql = FUZZY_MAPPING_PROPERTIES_SQL.format(
        fuzzy_mapping_property=f"{space_id}_fuzzy_mapping_property",
    )
    prop_rows = await conn.fetch(prop_sql, row["mapping_id"])
    for pr in prop_rows:
        uri = pr["property_uri"]
        role = pr["property_role"]
        if role == "primary":
            rule.primary_uris.append(uri)
        elif role == "alias":
            rule.alias_uris.append(uri)
        else:
            rule.include_uris.append(uri)

    return rule


async def resolve_any_fuzzy_mapping(conn, space_id: str) -> Optional[FuzzyMappingRule]:
    """Resolve the first enabled fuzzy mapping for a space (any type).

    Used by vg_resolve when we just need to know if fuzzy is configured.
    """
    sql = RESOLVE_ANY_FUZZY_MAPPING_SQL.format(
        fuzzy_mapping=f"{space_id}_fuzzy_mapping",
    )
    row = await conn.fetchrow(sql)
    if row is None:
        return None

    rule = FuzzyMappingRule(
        mapping_id=row["mapping_id"],
        enabled=row["enabled"],
        shingle_k=row["shingle_k"] or 3,
        num_perm=row["num_perm"] or 64,
        lsh_threshold=row["lsh_threshold"] or 0.3,
        phonetic_bonus=row["phonetic_bonus"] or 10.0,
        mapping_type=row.get("mapping_type"),
    )

    # Fetch properties
    prop_sql = FUZZY_MAPPING_PROPERTIES_SQL.format(
        fuzzy_mapping_property=f"{space_id}_fuzzy_mapping_property",
    )
    prop_rows = await conn.fetch(prop_sql, row["mapping_id"])
    for pr in prop_rows:
        uri = pr["property_uri"]
        role = pr["property_role"]
        if role == "primary":
            rule.primary_uris.append(uri)
        elif role == "alias":
            rule.alias_uris.append(uri)
        else:
            rule.include_uris.append(uri)

    return rule


# ---------------------------------------------------------------------------
# Manager class
# ---------------------------------------------------------------------------

class FuzzyMappingManager:
    """CRUD operations on the normalized fuzzy_mapping tables.

    ``conn`` must be an asyncpg Connection (or pool-acquired connection).
    All public methods are async.
    """

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self.space_id = space_id
        self._mapping_table = f"{space_id}_fuzzy_mapping"
        self._property_table = f"{space_id}_fuzzy_mapping_property"

    # ------------------------------------------------------------------
    # Mapping CRUD
    # ------------------------------------------------------------------

    async def create_mapping(
        self,
        index_name: str,
        mapping_type: str,
        *,
        type_uri: Optional[str] = None,
        enabled: bool = True,
        shingle_k: int = 3,
        num_perm: int = 64,
        lsh_threshold: float = 0.3,
        phonetic_bonus: float = 10.0,
    ) -> int:
        """Insert a fuzzy_mapping row and return its mapping_id."""
        sql = f"""
            INSERT INTO {self._mapping_table}
                (mapping_type, type_uri, index_name, enabled,
                 shingle_k, num_perm, lsh_threshold, phonetic_bonus)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING mapping_id
        """
        mapping_id = await self.conn.fetchval(
            sql,
            mapping_type, type_uri, index_name, enabled,
            shingle_k, num_perm, lsh_threshold, phonetic_bonus,
        )
        logger.info("Created fuzzy mapping %s for %s/%s (space=%s)",
                     mapping_id, mapping_type, type_uri, self.space_id)
        return mapping_id

    async def get_mapping(self, mapping_id: int) -> Optional[FuzzyMappingDTO]:
        """Get a single mapping with its child properties."""
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self._mapping_table} WHERE mapping_id = $1",
            mapping_id,
        )
        if row is None:
            return None
        return await self._row_to_dto(row, include_properties=True)

    async def list_mappings(
        self,
        *,
        index_name: Optional[str] = None,
        mapping_type: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> List[FuzzyMappingDTO]:
        """List mappings with optional filters."""
        clauses: List[str] = []
        params: List[Any] = []
        idx = 1

        if index_name is not None:
            clauses.append(f"index_name = ${idx}")
            params.append(index_name)
            idx += 1
        if mapping_type is not None:
            clauses.append(f"mapping_type = ${idx}")
            params.append(mapping_type)
            idx += 1
        if enabled is not None:
            clauses.append(f"enabled = ${idx}")
            params.append(enabled)
            idx += 1

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM {self._mapping_table}{where} ORDER BY mapping_id"
        rows = await self.conn.fetch(sql, *params)
        return [await self._row_to_dto(r, include_properties=True) for r in rows]

    async def update_mapping(self, mapping_id: int, **kwargs) -> Optional[FuzzyMappingDTO]:
        """Update a fuzzy mapping's fields. Pass only the fields to change."""
        allowed = {"enabled", "shingle_k", "num_perm", "lsh_threshold", "phonetic_bonus"}
        sets: List[str] = []
        params: List[Any] = []
        idx = 1
        for key, val in kwargs.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ${idx}")
            params.append(val)
            idx += 1
        if not sets:
            return await self.get_mapping(mapping_id)
        params.append(mapping_id)
        sql = f"UPDATE {self._mapping_table} SET {', '.join(sets)} WHERE mapping_id = ${idx}"
        await self.conn.execute(sql, *params)
        return await self.get_mapping(mapping_id)

    async def delete_mapping(self, mapping_id: int) -> bool:
        """Delete a mapping (CASCADE deletes child properties)."""
        result = await self.conn.execute(
            f"DELETE FROM {self._mapping_table} WHERE mapping_id = $1",
            mapping_id,
        )
        deleted = result == "DELETE 1"
        if deleted:
            logger.info("Deleted fuzzy mapping %s (space=%s)", mapping_id, self.space_id)
        return deleted

    # ------------------------------------------------------------------
    # Property CRUD
    # ------------------------------------------------------------------

    async def add_property(
        self,
        mapping_id: int,
        property_uri: str,
        *,
        property_role: str = "include",
        ordinal: int = 0,
    ) -> int:
        """Add a child property row. Returns the property_id."""
        sql = f"""
            INSERT INTO {self._property_table}
                (mapping_id, property_uri, property_role, ordinal)
            VALUES ($1, $2, $3, $4)
            RETURNING property_id
        """
        return await self.conn.fetchval(sql, mapping_id, property_uri, property_role, ordinal)

    async def remove_property(self, property_id: int) -> bool:
        """Remove a child property row by its property_id."""
        result = await self.conn.execute(
            f"DELETE FROM {self._property_table} WHERE property_id = $1",
            property_id,
        )
        return result == "DELETE 1"

    async def list_properties(self, mapping_id: int) -> List[FuzzyMappingPropertyDTO]:
        """List child properties for a mapping (ordered by ordinal)."""
        rows = await self.conn.fetch(
            f"SELECT * FROM {self._property_table} "
            f"WHERE mapping_id = $1 ORDER BY ordinal, property_id",
            mapping_id,
        )
        return [FuzzyMappingPropertyDTO(
            property_id=r["property_id"],
            mapping_id=r["mapping_id"],
            property_uri=r["property_uri"],
            property_role=r["property_role"],
            ordinal=r["ordinal"],
        ) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self, mapping_id: int) -> Optional[Dict[str, Any]]:
        """Get index statistics for a fuzzy mapping.

        Returns band_count, entity_count (distinct subjects), and phonetic_band_count.
        """
        # Verify mapping exists
        mapping = await self.get_mapping(mapping_id)
        if mapping is None:
            return None

        band_table = f"{self.space_id}_fuzzy_band"
        phonetic_band_table = f"{self.space_id}_fuzzy_phonetic_band"

        band_count = await self.conn.fetchval(
            f"SELECT COUNT(*) FROM {band_table}"
        ) or 0

        entity_count = await self.conn.fetchval(
            f"SELECT COUNT(DISTINCT split_part(entity_key, ':', 1)) FROM {band_table}"
        ) or 0

        phonetic_band_count = await self.conn.fetchval(
            f"SELECT COUNT(*) FROM {phonetic_band_table}"
        ) or 0

        return {
            'mapping_id': mapping_id,
            'band_count': band_count,
            'entity_count': entity_count,
            'phonetic_band_count': phonetic_band_count,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _row_to_dto(self, row, *, include_properties: bool = False) -> FuzzyMappingDTO:
        dto = FuzzyMappingDTO(
            mapping_id=row["mapping_id"],
            mapping_type=row["mapping_type"],
            type_uri=row["type_uri"],
            index_name=row["index_name"],
            enabled=row["enabled"],
            shingle_k=row["shingle_k"],
            num_perm=row["num_perm"],
            lsh_threshold=row["lsh_threshold"],
            phonetic_bonus=row["phonetic_bonus"],
            created_time=str(row["created_time"]) if row["created_time"] else None,
        )
        if include_properties:
            dto.properties = await self.list_properties(row["mapping_id"])
        return dto
