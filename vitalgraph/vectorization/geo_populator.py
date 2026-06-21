"""
Geo population pipeline.

Extracts geo-typed literals from RDF quads and populates the
``{space}_geo`` side-table with PostGIS geography points.

Detection is **datatype-driven**: any quad whose object literal has a
recognized geo datatype URI is indexed into the geo side-table.

Recognized geo datatype URIs:
- http://www.opengis.net/ont/geosparql#wktLiteral  (OGC GeoSPARQL)
- http://vital.ai/ontology/vital-core#geoLocation  (VitalSigns)

The literal value is expected to be in WKT format, e.g.:
  "POINT(-73.9855 40.7580)"  (lon lat order per WKT/GeoSPARQL)

Legacy formats ("lat,lon" or "lat lon" strings) are supported as fallback.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from vitalgraph.vectorization.geo_config_manager import (
    GeoConfigManager, GeoConfigDTO,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Recognized geo datatype URIs
# ---------------------------------------------------------------------------

GEO_DATATYPE_URIS = {
    "http://www.opengis.net/ont/geosparql#wktLiteral",
    "http://vital.ai/ontology/vital-core#geoLocation",
}


@dataclass
class GeoPopulationStats:
    """Statistics for a geo population run."""
    subjects_scanned: int = 0
    points_upserted: int = 0
    points_removed: int = 0
    parse_failures: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------
# SQL
# -----------------------------------------------------------------------

GEO_UPSERT_SQL = """
INSERT INTO {geo_table} (subject_uuid, predicate_uuid, location, latitude, longitude, context_uuid, updated_time)
VALUES ($1, $2, ST_SetSRID(ST_GeomFromText($3), 4326)::geography, $4, $5, $6, CURRENT_TIMESTAMP)
ON CONFLICT (subject_uuid, context_uuid)
DO UPDATE SET predicate_uuid = EXCLUDED.predicate_uuid,
              location       = EXCLUDED.location,
              latitude       = EXCLUDED.latitude,
              longitude      = EXCLUDED.longitude,
              updated_time   = EXCLUDED.updated_time
"""

GEO_DELETE_SQL = """
DELETE FROM {geo_table} WHERE subject_uuid = $1 AND context_uuid = $2
"""

# Fetch all geo-typed literal quads for a graph (datatype-driven detection)
GEO_QUADS_SQL = """
SELECT q.subject_uuid,
       t_pred.term_uuid   AS predicate_uuid,
       t_obj.term_text    AS value_text
FROM {rdf_quad} q
JOIN {term} t_obj  ON q.object_uuid = t_obj.term_uuid
JOIN {term} t_pred ON q.predicate_uuid = t_pred.term_uuid
JOIN {datatype} dt ON t_obj.datatype_id = dt.datatype_id
WHERE q.context_uuid = $1
  AND t_obj.term_type = 'L'
  AND dt.datatype_uri = ANY($2)
"""


# Regex to extract lon/lat from WKT POINT
_WKT_POINT_RE = re.compile(
    r"POINT\s*\(\s*([\-+]?[0-9]*\.?[0-9]+)\s+([\-+]?[0-9]*\.?[0-9]+)\s*\)",
    re.IGNORECASE,
)


def parse_geo_wkt(text: str) -> Optional[Tuple[float, float, str]]:
    """Parse a geo literal value into (latitude, longitude, wkt_text).

    Supports:
    - WKT POINT format: "POINT(lon lat)" → (lat, lon, "POINT(lon lat)")
    - Legacy "lat,lon" format → (lat, lon, "POINT(lon lat)")
    - Legacy "lat lon" format → (lat, lon, "POINT(lon lat)")

    Returns:
        (latitude, longitude, wkt_string) or None if parsing fails.
    """
    if not text:
        return None

    clean = text.strip()
    # Strip XSD typed literal suffix if present
    if "^^" in clean:
        clean = clean.split("^^")[0].strip('"').strip("'")

    # Try WKT POINT
    m = _WKT_POINT_RE.search(clean)
    if m:
        lon, lat = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon, f"POINT({lon} {lat})")
        return None

    # Legacy: comma-separated "lat,lon"
    if "," in clean:
        parts = clean.split(",", 1)
        try:
            lat, lon = float(parts[0].strip()), float(parts[1].strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon, f"POINT({lon} {lat})")
        except (ValueError, IndexError):
            pass
        return None

    # Legacy: space-separated "lat lon"
    parts = clean.split()
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon, f"POINT({lon} {lat})")
        except ValueError:
            pass

    return None


async def resolve_geo_config(
    conn, space_id: str,
) -> Optional[GeoConfigDTO]:
    """Load the geo config row for a space (or None if table absent / empty)."""
    mgr = GeoConfigManager(conn, space_id)
    try:
        return await mgr.get_config()
    except Exception:
        # Table may not exist on older spaces
        logger.debug("resolve_geo_config: geo_config table not found for %s", space_id)
        return None


async def populate_geo(
    conn,
    space_id: str,
    context_uuid,
    *,
    geo_datatype_uris: Optional[Set[str]] = None,
    subject_uuids: Optional[List] = None,
    geo_config: Optional[GeoConfigDTO] = None,
) -> GeoPopulationStats:
    """Populate the geo side-table from geo-typed RDF literals.

    Detection is datatype-driven: finds quads whose object literal has a
    recognized geo datatype URI, parses the WKT value, and upserts into
    the geo side-table.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        context_uuid: Graph context UUID.
        geo_datatype_uris: Override set of recognized geo datatype URIs.
        subject_uuids: Optional filter — only process these subjects.
        geo_config: Pre-resolved GeoConfigDTO.  If None, loaded from DB.

    Returns:
        GeoPopulationStats with counts and timing.
    """
    stats = GeoPopulationStats()
    t0 = time.monotonic()

    # Resolve config from DB if not provided
    if geo_config is None:
        geo_config = await resolve_geo_config(conn, space_id)

    # If config exists and is disabled → skip
    if geo_config is not None and not geo_config.enabled:
        logger.info("populate_geo: %s — geo disabled, skipping", space_id)
        stats.elapsed_seconds = time.monotonic() - t0
        return stats

    # Determine geo datatype URIs: explicit args > config > defaults
    if geo_datatype_uris is not None:
        dtypes = geo_datatype_uris
    elif geo_config is not None and geo_config.geo_datatype_uris:
        dtypes = set(geo_config.geo_datatype_uris)
    else:
        dtypes = GEO_DATATYPE_URIS

    geo_table = f"{space_id}_geo"
    rdf_quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"
    datatype = f"{space_id}_datatype"

    # Fetch all geo-typed literal quads
    sql = GEO_QUADS_SQL.format(rdf_quad=rdf_quad, term=term, datatype=datatype)
    if subject_uuids is not None:
        sql += " AND q.subject_uuid = ANY($3)"
        rows = await conn.fetch(sql, context_uuid, list(dtypes), subject_uuids)
    else:
        rows = await conn.fetch(sql, context_uuid, list(dtypes))

    stats.subjects_scanned = len(rows)

    upsert_sql = GEO_UPSERT_SQL.format(geo_table=geo_table)

    # Deduplicate: keep first geo value per subject
    seen_subjects: set = set()
    for r in rows:
        subj_uuid = r["subject_uuid"]
        if subj_uuid in seen_subjects:
            continue

        parsed = parse_geo_wkt(r["value_text"])
        if parsed is None:
            stats.parse_failures += 1
            continue

        lat, lon, wkt = parsed
        seen_subjects.add(subj_uuid)

        try:
            await conn.execute(
                upsert_sql,
                subj_uuid,
                r["predicate_uuid"],
                wkt,
                lat,
                lon,
                context_uuid,
            )
            stats.points_upserted += 1
        except Exception as e:
            stats.errors.append(f"Upsert failed for {subj_uuid}: {e}")

    stats.elapsed_seconds = time.monotonic() - t0
    logger.info(
        "populate_geo: %s — %d upserted, %d parse failures, %.1fs",
        space_id, stats.points_upserted, stats.parse_failures,
        stats.elapsed_seconds,
    )
    return stats


async def delete_subject_geo(
    conn, space_id: str, subject_uuid, context_uuid,
) -> bool:
    """Remove a subject's geo point."""
    geo_table = f"{space_id}_geo"
    try:
        await conn.execute(
            GEO_DELETE_SQL.format(geo_table=geo_table),
            subject_uuid, context_uuid,
        )
        return True
    except Exception as e:
        logger.error("delete_subject_geo(%s) failed: %s", space_id, e)
        return False


async def update_subject_geo(
    conn,
    space_id: str,
    subject_uuid,
    context_uuid,
    *,
    geo_datatype_uris: Optional[Set[str]] = None,
    geo_config: Optional[GeoConfigDTO] = None,
) -> bool:
    """Re-check and upsert a single subject's geo point (for auto-sync).

    Finds geo-typed literals for this subject and upserts the first valid one.
    """
    # Resolve config if not provided
    if geo_config is None:
        geo_config = await resolve_geo_config(conn, space_id)

    # Skip if geo is disabled
    if geo_config is not None and not geo_config.enabled:
        return False

    # Determine geo datatype URIs
    if geo_datatype_uris is not None:
        dtypes = geo_datatype_uris
    elif geo_config is not None and geo_config.geo_datatype_uris:
        dtypes = set(geo_config.geo_datatype_uris)
    else:
        dtypes = GEO_DATATYPE_URIS

    rdf_quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"
    datatype = f"{space_id}_datatype"

    sql = GEO_QUADS_SQL.format(rdf_quad=rdf_quad, term=term, datatype=datatype)
    sql += " AND q.subject_uuid = $3"
    rows = await conn.fetch(sql, context_uuid, list(dtypes), subject_uuid)

    geo_table = f"{space_id}_geo"
    for r in rows:
        parsed = parse_geo_wkt(r["value_text"])
        if parsed is None:
            continue
        lat, lon, wkt = parsed
        try:
            await conn.execute(
                GEO_UPSERT_SQL.format(geo_table=geo_table),
                subject_uuid, r["predicate_uuid"], wkt, lat, lon, context_uuid,
            )
            return True
        except Exception as e:
            logger.error("update_subject_geo(%s) upsert failed: %s", space_id, e)
            return False

    # No geo-typed data found → remove if exists
    await delete_subject_geo(conn, space_id, subject_uuid, context_uuid)
    return True
