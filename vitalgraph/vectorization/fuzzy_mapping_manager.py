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
from vitalgraph.db.sparql_sql.space_names import space_prefix

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
# The space's fuzzy index (used by the populator, auto-sync and SPARQL resolve)
# ---------------------------------------------------------------------------
#
# A space has ONE pair of band tables, `{space}_fuzzy_band` and
# `{space}_fuzzy_phonetic_band`, keyed by subject; nothing in them records which
# mapping produced a row. So the space has one fuzzy index, and every enabled
# mapping contributes to it: a mapping says which properties of which subjects
# are names. Populate, auto-sync and `vg:fuzzyMatch` all read that same union.
#
# Before `issues/338`/`339` each read a different subset: the query and
# auto-sync used only the FIRST enabled mapping, and populate looked one up as
# `kgentity` whatever the mapping it was asked to populate, so a second mapping
# was silently ignored and a non-kgentity mapping could never be populated.

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# Which subjects a mapping type covers, by their exact rdf:type. A type not
# listed (kgframe, kgslot, ...) has no type filter: every subject with one of
# its properties is indexed.
MAPPING_TYPE_RDF_TYPES = {
    "kgentity": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
    "kgdocument": "http://vital.ai/ontology/haley-ai-kg#KGDocument",
    "kgdocument_segment": "http://vital.ai/ontology/haley-ai-kg#KGDocument",
}

ENABLED_FUZZY_MAPPINGS_SQL = """
SELECT m.mapping_id, m.mapping_type, m.shingle_k, m.num_perm, m.lsh_threshold,
       m.phonetic_bonus, p.property_uri
FROM {fuzzy_mapping} m
JOIN {fuzzy_mapping_property} p ON p.mapping_id = m.mapping_id
WHERE m.enabled = TRUE
ORDER BY m.mapping_id, p.ordinal, p.property_id
"""


@dataclass
class FuzzyScope:
    """One enabled mapping's contribution: these properties of these subjects."""
    mapping_id: int
    rdf_type_uri: Optional[str]          # None: any subject
    property_uris: List[str]


@dataclass
class SpaceFuzzyIndex:
    """The space's one fuzzy index: the union of its enabled mappings.

    The band tables hold one set of MinHash parameters, so the index takes them
    from the enabled mapping with the lowest id (`settings_mapping_id`). Another
    mapping's own parameters are stored but not used; the endpoint says so when
    they differ.
    """
    settings_mapping_id: int
    shingle_k: int
    num_perm: int
    lsh_threshold: float
    phonetic_bonus: float
    scopes: List[FuzzyScope]

    @property
    def property_uris(self) -> List[str]:
        seen: Dict[str, None] = {}
        for s in self.scopes:
            for u in s.property_uris:
                seen.setdefault(u, None)
        return list(seen)


def settings_of(row) -> tuple:
    return (row["shingle_k"] or 3, row["num_perm"] or 64,
            row["lsh_threshold"] or 0.3, row["phonetic_bonus"] or 10.0)


async def resolve_space_fuzzy_index(conn, space_id: str) -> Optional[SpaceFuzzyIndex]:
    """The space's fuzzy index, or None when no enabled mapping has a property."""
    rows = await conn.fetch(ENABLED_FUZZY_MAPPINGS_SQL.format(
        fuzzy_mapping=f"{space_prefix(space_id)}_fuzzy_mapping",
        fuzzy_mapping_property=f"{space_prefix(space_id)}_fuzzy_mapping_property",
    ))
    if not rows:
        return None
    scopes: Dict[int, FuzzyScope] = {}
    for r in rows:
        scope = scopes.get(r["mapping_id"])
        if scope is None:
            scope = scopes[r["mapping_id"]] = FuzzyScope(
                mapping_id=r["mapping_id"],
                rdf_type_uri=MAPPING_TYPE_RDF_TYPES.get(r["mapping_type"]),
                property_uris=[])
        if r["property_uri"] not in scope.property_uris:
            scope.property_uris.append(r["property_uri"])
    first = rows[0]
    shingle_k, num_perm, lsh_threshold, phonetic_bonus = settings_of(first)
    return SpaceFuzzyIndex(
        settings_mapping_id=first["mapping_id"],
        shingle_k=shingle_k, num_perm=num_perm,
        lsh_threshold=lsh_threshold, phonetic_bonus=phonetic_bonus,
        scopes=list(scopes.values()),
    )


def unused_settings_note(index: Optional[SpaceFuzzyIndex], dto) -> Optional[str]:
    """A message when `dto` is enabled but its MinHash settings are not the ones
    the space's index uses, or None. Its properties are indexed either way."""
    if index is None or dto is None or not dto.enabled:
        return None
    if dto.mapping_id == index.settings_mapping_id:
        return None
    mine = (dto.shingle_k, dto.num_perm, dto.lsh_threshold, dto.phonetic_bonus)
    used = (index.shingle_k, index.num_perm, index.lsh_threshold, index.phonetic_bonus)
    if mine == used:
        return None
    return (f"This space's fuzzy index uses the settings of mapping "
            f"{index.settings_mapping_id} (shingle_k={used[0]}, num_perm={used[1]}, "
            f"lsh_threshold={used[2]}, phonetic_bonus={used[3]}). This mapping's "
            f"properties are indexed with those settings; its own are stored but not used.")


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
        self._mapping_table = f"{space_prefix(space_id)}_fuzzy_mapping"
        self._property_table = f"{space_prefix(space_id)}_fuzzy_mapping_property"

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

        band_table = f"{space_prefix(self.space_id)}_fuzzy_band"
        phonetic_band_table = f"{space_prefix(self.space_id)}_fuzzy_phonetic_band"

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
