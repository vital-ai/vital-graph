"""
Geo population pipeline.

Extracts lat/long values from RDF quads and populates the
``{space}_geo`` side-table with PostGIS geography points.

A complete geo point requires **both** latitude and longitude for the
same subject.  The pipeline pairs them by subject_uuid + context_uuid.

Recognized predicates (configurable):
- http://www.w3.org/2003/01/geo/wgs84_pos#lat / #long
- http://vital.ai/ontology/haley-ai-kg#hasLatitude / #hasLongitude
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from vitalgraph.vectorization.geo_config_manager import (
    GeoConfigManager, GeoConfigDTO, DEFAULT_LAT_PREDICATES, DEFAULT_LON_PREDICATES,
)

logger = logging.getLogger(__name__)


@dataclass
class GeoPopulationStats:
    """Statistics for a geo population run."""
    subjects_scanned: int = 0
    points_upserted: int = 0
    points_removed: int = 0
    incomplete_pairs: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------
# SQL
# -----------------------------------------------------------------------

GEO_UPSERT_SQL = """
INSERT INTO {geo_table} (subject_uuid, predicate_uuid, location, latitude, longitude, context_uuid, updated_time)
VALUES ($1, $2, ST_MakePoint($4, $3)::geography, $3, $4, $5, CURRENT_TIMESTAMP)
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

# Fetch all lat/lon literal quads for a graph
LATLON_QUADS_SQL = """
SELECT q.subject_uuid,
       t_pred.term_text   AS predicate_uri,
       t_pred.term_uuid   AS predicate_uuid,
       t_obj.term_text    AS value_text
FROM {rdf_quad} q
JOIN {term} t_pred ON q.predicate_uuid = t_pred.term_uuid
JOIN {term} t_obj  ON q.object_uuid    = t_obj.term_uuid
WHERE q.context_uuid = $1
  AND t_pred.term_text = ANY($2)
  AND t_obj.term_type = 'L'
"""


def _parse_float(text: str) -> Optional[float]:
    """Parse a float from an RDF literal string, handling XSD typed literals."""
    try:
        # Strip XSD datatype suffix if present (e.g., "40.73"^^xsd:double)
        clean = text.strip()
        if "^^" in clean:
            clean = clean.split("^^")[0].strip('"').strip("'")
        return float(clean)
    except (ValueError, TypeError):
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
    lat_predicates: Optional[Set[str]] = None,
    lon_predicates: Optional[Set[str]] = None,
    subject_uuids: Optional[List] = None,
    geo_config: Optional[GeoConfigDTO] = None,
) -> GeoPopulationStats:
    """Populate the geo side-table from lat/long RDF triples.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        context_uuid: Graph context UUID.
        lat_predicates: Override predicate URIs for latitude.
        lon_predicates: Override predicate URIs for longitude.
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

    # Determine predicate sets: explicit args > config > defaults
    if lat_predicates is not None:
        lat_preds = lat_predicates
    elif geo_config is not None:
        lat_preds = set(geo_config.lat_predicates)
    else:
        lat_preds = set(DEFAULT_LAT_PREDICATES)

    if lon_predicates is not None:
        lon_preds = lon_predicates
    elif geo_config is not None:
        lon_preds = set(geo_config.lon_predicates)
    else:
        lon_preds = set(DEFAULT_LON_PREDICATES)

    all_preds = list(lat_preds | lon_preds)

    geo_table = f"{space_id}_geo"
    rdf_quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"

    # Fetch all lat/lon quads
    sql = LATLON_QUADS_SQL.format(rdf_quad=rdf_quad, term=term)
    rows = await conn.fetch(sql, context_uuid, all_preds)

    # Group by subject: collect lat and lon
    subject_data: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        subj = r["subject_uuid"]
        pred_uri = r["predicate_uri"]
        value = _parse_float(r["value_text"])
        if value is None:
            continue

        if subj not in subject_data:
            subject_data[subj] = {}

        if pred_uri in lat_preds:
            subject_data[subj]["lat"] = value
            subject_data[subj]["pred_uuid"] = r["predicate_uuid"]
        elif pred_uri in lon_preds:
            subject_data[subj]["lon"] = value

    # Filter to requested subjects if specified
    if subject_uuids is not None:
        subject_set = set(subject_uuids)
        subject_data = {k: v for k, v in subject_data.items() if k in subject_set}

    stats.subjects_scanned = len(subject_data)

    upsert_sql = GEO_UPSERT_SQL.format(geo_table=geo_table)
    delete_sql = GEO_DELETE_SQL.format(geo_table=geo_table)

    for subj_uuid, data in subject_data.items():
        lat = data.get("lat")
        lon = data.get("lon")

        if lat is not None and lon is not None:
            # Validate ranges
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                stats.errors.append(
                    f"Invalid lat/lon for {subj_uuid}: ({lat}, {lon})"
                )
                continue
            try:
                await conn.execute(
                    upsert_sql,
                    subj_uuid,
                    data.get("pred_uuid"),
                    lat,
                    lon,
                    context_uuid,
                )
                stats.points_upserted += 1
            except Exception as e:
                stats.errors.append(f"Upsert failed for {subj_uuid}: {e}")
        else:
            stats.incomplete_pairs += 1

    stats.elapsed_seconds = time.monotonic() - t0
    logger.info(
        "populate_geo: %s — %d upserted, %d incomplete, %.1fs",
        space_id, stats.points_upserted, stats.incomplete_pairs,
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
    lat_predicates: Optional[Set[str]] = None,
    lon_predicates: Optional[Set[str]] = None,
    geo_config: Optional[GeoConfigDTO] = None,
) -> bool:
    """Re-check and upsert a single subject's geo point (for auto-sync)."""
    # Resolve config if not provided
    if geo_config is None:
        geo_config = await resolve_geo_config(conn, space_id)

    # Skip if geo is disabled
    if geo_config is not None and not geo_config.enabled:
        return False

    # Determine predicate sets: explicit args > config > defaults
    if lat_predicates is not None:
        lat_preds = lat_predicates
    elif geo_config is not None:
        lat_preds = set(geo_config.lat_predicates)
    else:
        lat_preds = set(DEFAULT_LAT_PREDICATES)

    if lon_predicates is not None:
        lon_preds = lon_predicates
    elif geo_config is not None:
        lon_preds = set(geo_config.lon_predicates)
    else:
        lon_preds = set(DEFAULT_LON_PREDICATES)

    all_preds = list(lat_preds | lon_preds)

    rdf_quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"

    sql = LATLON_QUADS_SQL.format(rdf_quad=rdf_quad, term=term)
    # Add subject filter
    sql += " AND q.subject_uuid = $3"
    rows = await conn.fetch(sql, context_uuid, all_preds, subject_uuid)

    lat = None
    lon = None
    pred_uuid = None
    for r in rows:
        val = _parse_float(r["value_text"])
        if val is None:
            continue
        if r["predicate_uri"] in lat_preds:
            lat = val
            pred_uuid = r["predicate_uuid"]
        elif r["predicate_uri"] in lon_preds:
            lon = val

    geo_table = f"{space_id}_geo"
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        try:
            await conn.execute(
                GEO_UPSERT_SQL.format(geo_table=geo_table),
                subject_uuid, pred_uuid, lat, lon, context_uuid,
            )
            return True
        except Exception as e:
            logger.error("update_subject_geo(%s) upsert failed: %s", space_id, e)
            return False
    else:
        # No complete geo data → remove if exists
        await delete_subject_geo(conn, space_id, subject_uuid, context_uuid)
        return True
