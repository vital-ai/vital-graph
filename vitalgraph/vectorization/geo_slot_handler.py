"""
Geo slot handler — auto-populates the geo table from KGGeoLocationSlot data.

When a KGGeoLocationSlot is created or updated, this module:
1. Parses the hasGeoLocationSlotValue for lat/lon
2. Resolves the owning entity via the edge path (entity → frame → slot)
3. Upserts the entity's location into the geo side-table

Slot value formats supported:
- "lat,lon" (e.g. "40.73,-73.93")
- JSON object: {"lat": 40.73, "lon": -73.93} or {"latitude": ..., "longitude": ...}

This is called from the auto_sync write-path hooks alongside the existing
geo_populator (which handles direct lat/lon predicates on subjects).
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HALEY_NS = "http://vital.ai/ontology/haley-ai-kg#"
GEO_SLOT_CLASS_URI = f"{_HALEY_NS}KGGeoLocationSlot"
GEO_SLOT_VALUE_PRED = f"{_HALEY_NS}hasGeoLocationSlotValue"

# Predicates used in the KG edge model to navigate from slot → entity
EDGE_HAS_KG_SLOT_TYPE = "http://vital.ai/ontology/vital-core#vitaltype"
EDGE_HAS_EDGE_SOURCE = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_HAS_EDGE_DEST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
EDGE_HAS_KG_SLOT_VITALTYPE = f"{_HALEY_NS}Edge_hasKGSlot"
EDGE_HAS_KG_FRAME_VITALTYPE = f"{_HALEY_NS}Edge_hasEntityKGFrame"


# ---------------------------------------------------------------------------
# SQL templates
# ---------------------------------------------------------------------------

# Get the slot's hasGeoLocationSlotValue
_SLOT_VALUE_SQL = """
SELECT t_obj.term_text AS value_text
FROM {rdf_quad} q
JOIN {term} t_pred ON q.predicate_uuid = t_pred.term_uuid
JOIN {term} t_obj  ON q.object_uuid    = t_obj.term_uuid
WHERE q.subject_uuid = $1
  AND q.context_uuid = $2
  AND t_pred.term_text = $3
"""

# Navigate from slot → frame via Edge_hasKGSlot (slot is edge destination)
_SLOT_TO_FRAME_SQL = """
SELECT t_src.term_text AS frame_uri, q_src.object_uuid AS frame_uuid
FROM {rdf_quad} q_edge
JOIN {term} t_type ON q_edge.predicate_uuid = t_type.term_uuid
JOIN {term} t_type_val ON q_edge.object_uuid = t_type_val.term_uuid
JOIN {rdf_quad} q_dst ON q_dst.subject_uuid = q_edge.subject_uuid
    AND q_dst.context_uuid = q_edge.context_uuid
JOIN {term} t_dst_pred ON q_dst.predicate_uuid = t_dst_pred.term_uuid
JOIN {rdf_quad} q_src ON q_src.subject_uuid = q_edge.subject_uuid
    AND q_src.context_uuid = q_edge.context_uuid
JOIN {term} t_src_pred ON q_src.predicate_uuid = t_src_pred.term_uuid
JOIN {term} t_src ON q_src.object_uuid = t_src.term_uuid
WHERE q_dst.object_uuid = $1
  AND q_edge.context_uuid = $2
  AND t_type.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
  AND t_type_val.term_text = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot'
  AND t_dst_pred.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
  AND t_src_pred.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
LIMIT 1
"""

# Navigate from frame → entity via Edge_hasEntityKGFrame (frame is edge destination)
_FRAME_TO_ENTITY_SQL = """
SELECT t_src.term_text AS entity_uri, q_src.object_uuid AS entity_uuid
FROM {rdf_quad} q_edge
JOIN {term} t_type ON q_edge.predicate_uuid = t_type.term_uuid
JOIN {term} t_type_val ON q_edge.object_uuid = t_type_val.term_uuid
JOIN {rdf_quad} q_dst ON q_dst.subject_uuid = q_edge.subject_uuid
    AND q_dst.context_uuid = q_edge.context_uuid
JOIN {term} t_dst_pred ON q_dst.predicate_uuid = t_dst_pred.term_uuid
JOIN {rdf_quad} q_src ON q_src.subject_uuid = q_edge.subject_uuid
    AND q_src.context_uuid = q_edge.context_uuid
JOIN {term} t_src_pred ON q_src.predicate_uuid = t_src_pred.term_uuid
JOIN {term} t_src ON q_src.object_uuid = t_src.term_uuid
WHERE q_dst.object_uuid = $1
  AND q_edge.context_uuid = $2
  AND t_type.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
  AND t_type_val.term_text = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame'
  AND t_dst_pred.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
  AND t_src_pred.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
LIMIT 1
"""

# Simplified: resolve entity UUID directly from slot UUID via frame_entity table
_SLOT_TO_ENTITY_VIA_FRAME_ENTITY_SQL = """
SELECT fe.entity_uuid
FROM {frame_entity} fe
JOIN {frame_entity} fe_slot ON fe_slot.entity_uuid = fe.entity_uuid
    AND fe_slot.context_uuid = fe.context_uuid
WHERE fe_slot.frame_uuid = $1
  AND fe_slot.context_uuid = $2
LIMIT 1
"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_geo_slot_value(value_text: str) -> Optional[Tuple[float, float, str]]:
    """Parse a geo slot value string into (latitude, longitude, wkt).

    Delegates to geo_populator.parse_geo_wkt which handles:
    - WKT POINT format: "POINT(lon lat)"
    - Legacy "lat,lon" (comma-separated)
    - Legacy "lat lon" (space-separated)

    Also handles JSON format as an additional legacy fallback:
    - JSON: {"lat": ..., "lon": ...}
    - JSON: {"latitude": ..., "longitude": ...}

    Returns:
        (latitude, longitude, wkt_string) tuple or None if parsing fails.
    """
    from vitalgraph.vectorization.geo_populator import parse_geo_wkt

    if not value_text:
        return None

    # Try the standard WKT / legacy lat,lon parser first
    result = parse_geo_wkt(value_text)
    if result is not None:
        return result

    # Additional fallback: JSON format
    text = value_text.strip()
    if "^^" in text:
        text = text.split("^^")[0].strip('"').strip("'")

    if text.startswith("{"):
        try:
            obj = json.loads(text)
            lat = obj.get("lat") or obj.get("latitude")
            lon = obj.get("lon") or obj.get("lng") or obj.get("longitude")
            if lat is not None and lon is not None:
                lat_f, lon_f = float(lat), float(lon)
                if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                    return (lat_f, lon_f, f"POINT({lon_f} {lat_f})")
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    return None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

async def resolve_entity_uuid_for_slot(
    conn,
    space_id: str,
    slot_uuid,
    context_uuid,
) -> Optional[Any]:
    """Resolve the owning entity UUID for a slot UUID.

    Uses the frame_entity table if available (fast path), otherwise
    falls back to edge traversal in the quad store.
    """
    frame_entity = f"{space_id}_frame_entity"

    # Fast path: use frame_entity table
    try:
        row = await conn.fetchrow(
            _SLOT_TO_ENTITY_VIA_FRAME_ENTITY_SQL.format(frame_entity=frame_entity),
            slot_uuid, context_uuid,
        )
        if row:
            return row["entity_uuid"]
    except Exception:
        # Table might not exist — fall through to edge traversal
        pass

    # Slow path: edge traversal slot → frame → entity
    rdf_quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"

    # Step 1: slot → frame
    sql_s2f = _SLOT_TO_FRAME_SQL.format(rdf_quad=rdf_quad, term=term)
    row = await conn.fetchrow(sql_s2f, slot_uuid, context_uuid)
    if not row:
        return None
    frame_uuid = row["frame_uuid"]

    # Step 2: frame → entity
    sql_f2e = _FRAME_TO_ENTITY_SQL.format(rdf_quad=rdf_quad, term=term)
    row = await conn.fetchrow(sql_f2e, frame_uuid, context_uuid)
    if not row:
        return None
    return row["entity_uuid"]


async def process_geo_slot(
    conn,
    space_id: str,
    slot_uuid,
    context_uuid,
    *,
    operation: str = "upsert",
) -> bool:
    """Process a KGGeoLocationSlot — extract lat/lon and upsert the owning entity's geo point.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        slot_uuid: UUID of the KGGeoLocationSlot subject.
        context_uuid: Graph context UUID.
        operation: "upsert" or "delete".

    Returns:
        True if geo point was successfully upserted/deleted.
    """
    from vitalgraph.vectorization.geo_populator import GEO_UPSERT_SQL, GEO_DELETE_BY_SLOT_SQL

    geo_table = f"{space_id}_geo"

    # Resolve the owning entity
    entity_uuid = await resolve_entity_uuid_for_slot(conn, space_id, slot_uuid, context_uuid)
    if entity_uuid is None:
        logger.debug("process_geo_slot: could not resolve entity for slot %s", slot_uuid)
        return False

    if operation == "delete":
        # Delete both slot-keyed and entity-keyed rows for this slot
        try:
            await conn.execute(
                GEO_DELETE_BY_SLOT_SQL.format(geo_table=geo_table),
                slot_uuid, context_uuid,
            )
            return True
        except Exception as e:
            logger.error("process_geo_slot delete failed: %s", e)
            return False

    # Read the slot's hasGeoLocationSlotValue
    rdf_quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"
    sql = _SLOT_VALUE_SQL.format(rdf_quad=rdf_quad, term=term)
    row = await conn.fetchrow(sql, slot_uuid, context_uuid, GEO_SLOT_VALUE_PRED)

    if not row:
        # No value → remove geo points for this slot
        try:
            await conn.execute(
                GEO_DELETE_BY_SLOT_SQL.format(geo_table=geo_table),
                slot_uuid, context_uuid,
            )
        except Exception:
            pass
        return True

    # Parse geo value → (lat, lon, wkt)
    parsed = parse_geo_slot_value(row["value_text"])
    if parsed is None:
        logger.warning(
            "process_geo_slot: unparseable geo value for slot %s: %s",
            slot_uuid, row["value_text"],
        )
        return False

    lat, lon, wkt = parsed
    upsert_sql = GEO_UPSERT_SQL.format(geo_table=geo_table)

    # Row 1: slot-keyed (subject_uuid=slot, source_slot_uuid=slot)
    try:
        await conn.execute(
            upsert_sql,
            slot_uuid,
            slot_uuid,   # source_slot_uuid = self
            None,        # predicate_uuid (not applicable for slot-based geo)
            wkt,
            lat,
            lon,
            context_uuid,
        )
    except Exception as e:
        logger.error("process_geo_slot slot upsert failed for %s: %s", slot_uuid, e)
        return False

    # Row 2: entity-keyed (subject_uuid=entity, source_slot_uuid=slot)
    try:
        await conn.execute(
            upsert_sql,
            entity_uuid,
            slot_uuid,   # source_slot_uuid = originating slot
            None,        # predicate_uuid
            wkt,
            lat,
            lon,
            context_uuid,
        )
        logger.debug(
            "process_geo_slot: upserted slot %s + entity %s → (%s, %s)",
            slot_uuid, entity_uuid, lat, lon,
        )
        return True
    except Exception as e:
        logger.error("process_geo_slot entity upsert failed for %s: %s", entity_uuid, e)
        return False


async def detect_and_process_geo_slots(
    conn,
    space_id: str,
    subject_uuids: List,
    context_uuid,
    *,
    operation: str = "upsert",
) -> int:
    """Check if any of the given subjects are KGGeoLocationSlots and process them.

    Called from auto_sync alongside the regular geo populator.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        subject_uuids: List of subject UUIDs to check.
        context_uuid: Graph context UUID.
        operation: "upsert" or "delete".

    Returns:
        Number of geo points successfully processed.
    """
    if not subject_uuids:
        return 0

    rdf_quad = f"{space_id}_rdf_quad"
    term = f"{space_id}_term"

    # Find which subjects are KGGeoLocationSlots (check vitaltype)
    detect_sql = f"""
        SELECT q.subject_uuid
        FROM {rdf_quad} q
        JOIN {term} t_pred ON q.predicate_uuid = t_pred.term_uuid
        JOIN {term} t_obj  ON q.object_uuid    = t_obj.term_uuid
        WHERE q.subject_uuid = ANY($1)
          AND q.context_uuid = $2
          AND t_pred.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
          AND t_obj.term_text = $3
    """

    try:
        rows = await conn.fetch(detect_sql, subject_uuids, context_uuid, GEO_SLOT_CLASS_URI)
    except Exception as e:
        logger.debug("detect_and_process_geo_slots: detection query failed: %s", e)
        return 0

    count = 0
    for row in rows:
        slot_uuid = row["subject_uuid"]
        ok = await process_geo_slot(conn, space_id, slot_uuid, context_uuid, operation=operation)
        if ok:
            count += 1

    if count > 0:
        logger.info(
            "detect_and_process_geo_slots: %s — processed %d geo slots (%s)",
            space_id, count, operation,
        )
    return count
