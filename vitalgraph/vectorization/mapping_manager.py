"""Programmatic API for managing vector_mapping + vector_mapping_property rows.

Usage:
    manager = MappingManager(conn, space_id)
    mid = await manager.create_mapping(index_name="entity_default",
                                        mapping_type="kgentity",
                                        source_type="default", enabled=True)
    await manager.add_property(mid, "http://...#hasName", ordinal=1)
    mappings = await manager.list_mappings()
    await manager.delete_mapping(mid)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class MappingPropertyDTO:
    property_id: int
    mapping_id: int
    property_uri: str
    property_role: str = "include"
    ordinal: int = 0


@dataclass
class MappingDTO:
    mapping_id: int
    mapping_type: str
    type_uri: Optional[str]
    index_name: str
    enabled: bool
    source_type: str
    separator: str
    include_pred_name: bool
    include_type_desc: bool
    created_time: Optional[str] = None
    properties: List[MappingPropertyDTO] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("created_time"):
            d["created_time"] = str(d["created_time"])
        return d


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class MappingManager:
    """CRUD operations on the normalized vector_mapping tables.

    ``conn`` must be an asyncpg Connection (or pool-acquired connection).
    All public methods are async.
    """

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self.space_id = space_id
        self._mapping_table = f"{space_id}_vector_mapping"
        self._property_table = f"{space_id}_vector_mapping_property"

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
        source_type: str = "default",
        separator: str = ". ",
        include_pred_name: bool = False,
        include_type_desc: bool = True,
    ) -> int:
        """Insert a vector_mapping row and return its mapping_id."""
        sql = f"""
            INSERT INTO {self._mapping_table}
                (mapping_type, type_uri, index_name, enabled,
                 source_type, separator, include_pred_name, include_type_desc)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING mapping_id
        """
        mapping_id = await self.conn.fetchval(
            sql,
            mapping_type, type_uri, index_name, enabled,
            source_type, separator, include_pred_name, include_type_desc,
        )
        logger.info("Created mapping %s for %s/%s (space=%s)",
                     mapping_id, mapping_type, type_uri, self.space_id)
        return mapping_id

    async def get_mapping(self, mapping_id: int) -> Optional[MappingDTO]:
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
    ) -> List[MappingDTO]:
        """List mappings with optional filters.  Always includes child properties."""
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

    async def update_mapping(
        self,
        mapping_id: int,
        **fields,
    ) -> Optional[MappingDTO]:
        """Update mutable columns on a mapping row.

        Accepted keyword args: enabled, source_type, separator,
        include_pred_name, include_type_desc.
        """
        allowed = {"enabled", "source_type", "separator",
                    "include_pred_name", "include_type_desc"}
        to_set = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not to_set:
            return await self.get_mapping(mapping_id)

        set_parts: List[str] = []
        params: List[Any] = []
        idx = 1
        for col, val in to_set.items():
            set_parts.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1
        params.append(mapping_id)

        sql = (f"UPDATE {self._mapping_table} SET {', '.join(set_parts)} "
               f"WHERE mapping_id = ${idx} RETURNING *")
        row = await self.conn.fetchrow(sql, *params)
        if row is None:
            return None
        return await self._row_to_dto(row, include_properties=True)

    async def delete_mapping(self, mapping_id: int) -> bool:
        """Delete a mapping (CASCADE deletes child properties)."""
        result = await self.conn.execute(
            f"DELETE FROM {self._mapping_table} WHERE mapping_id = $1",
            mapping_id,
        )
        deleted = result == "DELETE 1"
        if deleted:
            logger.info("Deleted mapping %s (space=%s)", mapping_id, self.space_id)
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
        """Add a child property row.  Returns the property_id."""
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

    async def list_properties(self, mapping_id: int) -> List[MappingPropertyDTO]:
        """List child properties for a mapping (ordered by ordinal)."""
        rows = await self.conn.fetch(
            f"SELECT * FROM {self._property_table} "
            f"WHERE mapping_id = $1 ORDER BY ordinal, property_id",
            mapping_id,
        )
        return [MappingPropertyDTO(
            property_id=r["property_id"],
            mapping_id=r["mapping_id"],
            property_uri=r["property_uri"],
            property_role=r["property_role"],
            ordinal=r["ordinal"],
        ) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _row_to_dto(self, row, *, include_properties: bool = False) -> MappingDTO:
        dto = MappingDTO(
            mapping_id=row["mapping_id"],
            mapping_type=row["mapping_type"],
            type_uri=row["type_uri"],
            index_name=row["index_name"],
            enabled=row["enabled"],
            source_type=row["source_type"],
            separator=row["separator"],
            include_pred_name=row["include_pred_name"],
            include_type_desc=row["include_type_desc"],
            created_time=str(row["created_time"]) if row["created_time"] else None,
        )
        if include_properties:
            dto.properties = await self.list_properties(row["mapping_id"])
        return dto
