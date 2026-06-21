"""Programmatic API for managing shared search_mapping + search_mapping_property rows.

These mappings are shared by both FTS and vector indexes.  A given mapping
defines which entity types and predicates feed into a named search index.
FTS and vector index tables reference these mappings by ``index_name``.

Usage:
    manager = SearchMappingManager(conn, space_id)
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
class SearchMappingPropertyDTO:
    property_id: int
    mapping_id: int
    property_uri: str
    property_role: str = "include"
    ordinal: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'property_id': self.property_id,
            'mapping_id': self.mapping_id,
            'property_uri': self.property_uri,
            'property_role': self.property_role,
            'ordinal': self.ordinal,
        }


@dataclass
class SearchMappingIndexDTO:
    id: int
    mapping_id: int
    index_type: str  # 'vector' or 'fts'
    index_name: str
    created_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'mapping_id': self.mapping_id,
            'index_type': self.index_type,
            'index_name': self.index_name,
            'created_time': str(self.created_time) if self.created_time else None,
        }


@dataclass
class SearchMappingDTO:
    mapping_id: int
    mapping_type: str
    type_uri: Optional[str]
    index_name: str
    enabled: bool
    source_type: str
    separator: str
    include_pred_name: bool
    created_time: Optional[str] = None
    properties: List[SearchMappingPropertyDTO] = field(default_factory=list)
    indexes: List[SearchMappingIndexDTO] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("created_time"):
            d["created_time"] = str(d["created_time"])
        return d


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SearchMappingManager:
    """CRUD operations on the shared search_mapping tables.

    These mappings are consumed by both FTS and vector indexes.
    ``conn`` must be an asyncpg Connection.  All public methods are async.
    """

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self.space_id = space_id
        self._mapping_table = f"{space_id}_search_mapping"
        self._index_table = f"{space_id}_search_mapping_index"
        self._property_table = f"{space_id}_search_mapping_property"

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
    ) -> int:
        """Insert a search_mapping row and return its mapping_id."""
        sql = f"""
            INSERT INTO {self._mapping_table}
                (mapping_type, type_uri, index_name, enabled,
                 source_type, separator, include_pred_name)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING mapping_id
        """
        mapping_id = await self.conn.fetchval(
            sql,
            mapping_type, type_uri, index_name, enabled,
            source_type, separator, include_pred_name,
        )
        logger.info("Created search mapping %s for %s/%s (space=%s)",
                     mapping_id, mapping_type, type_uri, self.space_id)
        return mapping_id

    async def get_mapping(self, mapping_id: int) -> Optional[SearchMappingDTO]:
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
    ) -> List[SearchMappingDTO]:
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
    ) -> Optional[SearchMappingDTO]:
        """Update mutable columns on a mapping row.

        Accepted keyword args: enabled, source_type, separator,
        include_pred_name.
        """
        allowed = {"enabled", "source_type", "separator",
                    "include_pred_name"}
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
            logger.info("Deleted search mapping %s (space=%s)", mapping_id, self.space_id)
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
        """Add a child property row.  Returns the property_id.

        Side-effect: if this is an 'include' property and the mapping's
        source_type is still 'default', automatically upgrades it to
        'properties' so the populator uses the explicit property list.
        """
        sql = f"""
            INSERT INTO {self._property_table}
                (mapping_id, property_uri, property_role, ordinal)
            VALUES ($1, $2, $3, $4)
            RETURNING property_id
        """
        pid = await self.conn.fetchval(sql, mapping_id, property_uri, property_role, ordinal)

        # Auto-upgrade source_type when include properties are added
        if property_role == "include":
            await self.conn.execute(
                f"UPDATE {self._mapping_table} "
                f"SET source_type = 'properties' "
                f"WHERE mapping_id = $1 AND source_type = 'default'",
                mapping_id,
            )

        return pid

    async def remove_property(self, property_id: int) -> bool:
        """Remove a child property row by its property_id."""
        result = await self.conn.execute(
            f"DELETE FROM {self._property_table} WHERE property_id = $1",
            property_id,
        )
        return result == "DELETE 1"

    async def list_properties(self, mapping_id: int) -> List[SearchMappingPropertyDTO]:
        """List child properties for a mapping (ordered by ordinal)."""
        rows = await self.conn.fetch(
            f"SELECT * FROM {self._property_table} "
            f"WHERE mapping_id = $1 ORDER BY ordinal, property_id",
            mapping_id,
        )
        return [SearchMappingPropertyDTO(
            property_id=r["property_id"],
            mapping_id=r["mapping_id"],
            property_uri=r["property_uri"],
            property_role=r["property_role"],
            ordinal=r["ordinal"],
        ) for r in rows]

    # ------------------------------------------------------------------
    # Index association CRUD
    # ------------------------------------------------------------------

    async def add_index(
        self,
        mapping_id: int,
        index_type: str,
        index_name: str,
    ) -> int:
        """Associate an index with a mapping.  Returns the junction row id."""
        sql = f"""
            INSERT INTO {self._index_table}
                (mapping_id, index_type, index_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (mapping_id, index_type, index_name) DO NOTHING
            RETURNING id
        """
        row_id = await self.conn.fetchval(sql, mapping_id, index_type, index_name)
        if row_id is None:
            # Already exists — fetch it
            row_id = await self.conn.fetchval(
                f"SELECT id FROM {self._index_table} "
                f"WHERE mapping_id = $1 AND index_type = $2 AND index_name = $3",
                mapping_id, index_type, index_name,
            )
        logger.info("Associated index %s/%s with mapping %s (space=%s)",
                    index_type, index_name, mapping_id, self.space_id)
        return row_id

    async def remove_index(self, junction_id: int) -> bool:
        """Remove an index association by junction row id."""
        result = await self.conn.execute(
            f"DELETE FROM {self._index_table} WHERE id = $1",
            junction_id,
        )
        return result == "DELETE 1"

    async def list_indexes(self, mapping_id: int) -> List[SearchMappingIndexDTO]:
        """List index associations for a mapping."""
        rows = await self.conn.fetch(
            f"SELECT * FROM {self._index_table} "
            f"WHERE mapping_id = $1 ORDER BY index_type, index_name",
            mapping_id,
        )
        return [SearchMappingIndexDTO(
            id=r["id"],
            mapping_id=r["mapping_id"],
            index_type=r["index_type"],
            index_name=r["index_name"],
            created_time=str(r["created_time"]) if r["created_time"] else None,
        ) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _row_to_dto(self, row, *, include_properties: bool = False) -> SearchMappingDTO:
        dto = SearchMappingDTO(
            mapping_id=row["mapping_id"],
            mapping_type=row["mapping_type"],
            type_uri=row["type_uri"],
            index_name=row["index_name"],
            enabled=row["enabled"],
            source_type=row["source_type"],
            separator=row["separator"],
            include_pred_name=row["include_pred_name"],
            created_time=str(row["created_time"]) if row["created_time"] else None,
        )
        if include_properties:
            dto.properties = await self.list_properties(row["mapping_id"])
            dto.indexes = await self.list_indexes(row["mapping_id"])
        return dto
