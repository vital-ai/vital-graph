"""GeoConfigManager — lightweight CRUD for the per-space geo_config table.

The ``geo_config`` table stores a single row per space controlling:
- **enabled**: whether geo population is active
- **auto_sync**: whether entity create/update triggers geo update
- **geo_datatype_uris**: recognized geo datatype URIs for datatype-driven detection
- **lat_predicates / lon_predicates**: (legacy) configurable predicate URI sets

Usage:
    mgr = GeoConfigManager(conn, space_id)
    cfg = await mgr.get_config()          # returns GeoConfigDTO or None
    cfg = await mgr.ensure_config()       # get-or-create with defaults
    cfg = await mgr.update_config(enabled=True, auto_sync=True)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default geo datatype URIs (datatype-driven detection)
# ---------------------------------------------------------------------------

DEFAULT_GEO_DATATYPE_URIS = [
    "http://www.opengis.net/ont/geosparql#wktLiteral",
    "http://vital.ai/ontology/vital-core#geoLocation",
]

# Legacy predicate sets (kept for backward compat with existing config rows)
DEFAULT_LAT_PREDICATES = [
    "http://vital.ai/ontology/vital-aimp#hasLatitude",
]

DEFAULT_LON_PREDICATES = [
    "http://vital.ai/ontology/vital-aimp#hasLongitude",
]


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------

@dataclass
class GeoConfigDTO:
    config_id: int
    enabled: bool = False
    auto_sync: bool = False
    geo_datatype_uris: List[str] = field(default_factory=lambda: list(DEFAULT_GEO_DATATYPE_URIS))
    lat_predicates: List[str] = field(default_factory=lambda: list(DEFAULT_LAT_PREDICATES))
    lon_predicates: List[str] = field(default_factory=lambda: list(DEFAULT_LON_PREDICATES))
    updated_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("updated_time"):
            d["updated_time"] = str(d["updated_time"])
        return d


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class GeoConfigManager:
    """CRUD for the single-row ``{space}_geo_config`` table."""

    def __init__(self, conn, space_id: str):
        self.conn = conn
        self.space_id = space_id
        self._table = f"{space_id}_geo_config"

    async def get_config(self) -> Optional[GeoConfigDTO]:
        """Return the geo config row, or None if not yet created."""
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self._table} ORDER BY config_id LIMIT 1"
        )
        if row is None:
            return None
        return self._row_to_dto(row)

    async def ensure_config(self) -> GeoConfigDTO:
        """Get-or-create: return existing config or insert defaults."""
        cfg = await self.get_config()
        if cfg is not None:
            return cfg

        row = await self.conn.fetchrow(f"""
            INSERT INTO {self._table} (enabled, auto_sync, lat_predicates, lon_predicates)
            VALUES ($1, $2, $3, $4)
            RETURNING *
        """, False, False, DEFAULT_LAT_PREDICATES, DEFAULT_LON_PREDICATES)
        logger.info("Created default geo config for space=%s", self.space_id)
        return self._row_to_dto(row)

    async def update_config(self, **fields) -> Optional[GeoConfigDTO]:
        """Update mutable columns.

        Accepted kwargs: enabled, auto_sync, geo_datatype_uris, lat_predicates, lon_predicates.
        """
        allowed = {"enabled", "auto_sync", "geo_datatype_uris", "lat_predicates", "lon_predicates"}
        to_set = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not to_set:
            return await self.get_config()

        set_parts: List[str] = []
        params: List[Any] = []
        idx = 1
        for col, val in to_set.items():
            set_parts.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1
        set_parts.append("updated_time = CURRENT_TIMESTAMP")

        sql = (f"UPDATE {self._table} SET {', '.join(set_parts)} "
               f"WHERE config_id = (SELECT config_id FROM {self._table} ORDER BY config_id LIMIT 1) "
               f"RETURNING *")
        row = await self.conn.fetchrow(sql, *params)
        if row is None:
            return None
        logger.info("Updated geo config for space=%s: %s", self.space_id, to_set)
        return self._row_to_dto(row)

    async def delete_config(self) -> bool:
        """Delete the geo config row (reset to unconfigured)."""
        result = await self.conn.execute(f"DELETE FROM {self._table}")
        return "DELETE" in result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dto(row) -> GeoConfigDTO:
        geo_dt = None
        if "geo_datatype_uris" in row.keys():
            geo_dt = list(row["geo_datatype_uris"]) if row["geo_datatype_uris"] else None
        return GeoConfigDTO(
            config_id=row["config_id"],
            enabled=row["enabled"],
            auto_sync=row["auto_sync"],
            geo_datatype_uris=geo_dt if geo_dt else list(DEFAULT_GEO_DATATYPE_URIS),
            lat_predicates=list(row["lat_predicates"]) if row.get("lat_predicates") else list(DEFAULT_LAT_PREDICATES),
            lon_predicates=list(row["lon_predicates"]) if row.get("lon_predicates") else list(DEFAULT_LON_PREDICATES),
            updated_time=str(row["updated_time"]) if row["updated_time"] else None,
        )
