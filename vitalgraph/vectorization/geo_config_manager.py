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

# Predicate sets for predicate-driven detection.
#
# These are RECOGNITION lists: geo_populator matches them against predicates
# already in the data, it never mints them. So an entry that matches nothing is
# free, while a missing entry is a silent under-population — the same asymmetry
# that runs through the rest of the derived-data layer, and the reason these
# lists should be generous rather than minimal.
#
# W3C Basic Geo (`wgs84_pos`) is the standard vocabulary for point coordinates
# and is what most third-party RDF uses. It was in the deployed geo_config
# defaults but never in the code, so a schema realignment dropped it — this
# restores it as the first-class entry rather than an artifact of old tables.
#
# NOTE ON THE NAMESPACE: it is `http://`, not `https://`. The W3C serves the
# vocabulary document over https, but the namespace URI that appears in RDF —
# and therefore the string that has to match a predicate in the data — is the
# http form. Using https here would match nothing.
#
# EVERY ENTRY MUST BE A PREDICATE THAT EXISTS. "An entry matching nothing is
# free" is true of query cost and false of everything else: a URI listed here
# reads as evidence that the predicate exists, and it propagates into the DDL
# and every deployed table. `haley-ai-kg#hasLatitude` / `#hasLongitude` were
# briefly listed on exactly that reasoning and are not defined by that ontology
# at all — it has `hasLongSlotValue` and `hasLongTextSlotValue`, nothing geo.
# The two real sources are W3C Basic Geo and vital-aimp, which is what
# `haley-ai-kg-0.1.0-schema.json` names for latitude and longitude.
DEFAULT_LAT_PREDICATES = [
    "http://www.w3.org/2003/01/geo/wgs84_pos#lat",
    "http://vital.ai/ontology/vital-aimp#hasLatitude",
]

# `long`, not `lon` — that is the term W3C Basic Geo actually defines.
DEFAULT_LON_PREDICATES = [
    "http://www.w3.org/2003/01/geo/wgs84_pos#long",
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
