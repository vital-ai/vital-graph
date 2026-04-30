"""
Server-managed KG entity properties: timestamps, status, and entity type.

This module provides utilities for enforcing server-side property management
on KGEntity objects.  Timestamps are always set by the server; status and
entity type default on create and are preserved on update when the client
omits them.
"""

import asyncio as _asyncio
import logging
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Property URIs
# ---------------------------------------------------------------------------

CREATION_TIME_URI = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
MODIFICATION_TIME_URI = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
STATUS_TYPE_URI = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
ENTITY_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

DEFAULT_STATUS = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
DEFAULT_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"

# Epoch sentinel — distinguishes backfilled creation times from real ones.
EPOCH_SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Dataclass for fetched properties
# ---------------------------------------------------------------------------

@dataclass
class ExistingEntityProps:
    """Server-managed properties read from an existing entity."""
    creation_time: Optional[datetime] = None
    status: Optional[str] = None
    entity_type: Optional[str] = None


# ---------------------------------------------------------------------------
# Stamping utility
# ---------------------------------------------------------------------------

def stamp_entity_server_properties(
    entity: KGEntity,
    now: datetime,
    existing_creation_time: Optional[datetime] = None,
    existing_status: Optional[str] = None,
    existing_entity_type: Optional[str] = None,
    is_create: bool = False,
) -> None:
    """Stamp server-managed properties on a KGEntity in place.

    Args:
        entity: The KGEntity to stamp.
        now: The current server time (UTC).
        existing_creation_time: Creation time from the DB (updates only).
        existing_status: Status URI from the DB (updates only).
        existing_entity_type: Entity type URI from the DB (updates only).
        is_create: True for entity creation, False for update.
    """
    # Timestamps — always server-set
    if is_create:
        entity.objectCreationTime = now
    else:
        entity.objectCreationTime = existing_creation_time or now
    entity.objectModificationDateTime = now

    # Status — default on create, preserve on update if client omits
    if is_create:
        if not entity.objectStatusType:
            entity.objectStatusType = DEFAULT_STATUS
    else:
        if not entity.objectStatusType:
            entity.objectStatusType = existing_status or DEFAULT_STATUS

    # Entity type — default on create, preserve on update if client omits
    if is_create:
        if not entity.kGEntityType:
            entity.kGEntityType = DEFAULT_ENTITY_TYPE
    else:
        if not entity.kGEntityType:
            entity.kGEntityType = existing_entity_type or DEFAULT_ENTITY_TYPE


# ---------------------------------------------------------------------------
# Fetch existing server-managed properties
# ---------------------------------------------------------------------------

def _parse_datetime_binding(value_str: Optional[str]) -> Optional[datetime]:
    """Parse an xsd:dateTime string from a SPARQL binding into a datetime."""
    if not value_str:
        return None
    try:
        # Handle both ISO-format and common xsd:dateTime variants
        cleaned = value_str.rstrip("Z")
        if "+" in cleaned[10:]:
            cleaned = cleaned[:cleaned.rindex("+")]
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        logger.warning("Could not parse datetime from SPARQL binding: %s", value_str)
        return None


def _extract_binding_value(bindings: List[Dict], var_name: str) -> Optional[str]:
    """Extract a single value from SPARQL result bindings."""
    if not bindings:
        return None
    binding = bindings[0]
    entry = binding.get(var_name)
    if entry is None:
        return None
    return entry.get("value")


async def fetch_entity_server_props(
    backend_adapter,
    space_id: str,
    graph_id: str,
    entity_uri: str,
) -> Optional[ExistingEntityProps]:
    """Fetch creation time, status, and entity type from an existing entity.

    Returns None if the entity does not exist (no triples at all).
    Returns ExistingEntityProps with possibly-None fields if the entity
    exists but is missing some properties.
    """
    sparql = f"""
    SELECT ?ct ?st ?et ?_any WHERE {{
        GRAPH <{graph_id}> {{
            <{entity_uri}> ?_any_pred ?_any .
            OPTIONAL {{ <{entity_uri}> <{CREATION_TIME_URI}> ?ct . }}
            OPTIONAL {{ <{entity_uri}> <{STATUS_TYPE_URI}> ?st . }}
            OPTIONAL {{ <{entity_uri}> <{ENTITY_TYPE_URI}> ?et . }}
        }}
    }} LIMIT 1
    """
    try:
        result = await backend_adapter.execute_sparql_query(space_id, sparql)
        bindings = result.get("results", {}).get("bindings", [])
        if not bindings:
            return None  # entity does not exist

        ct_str = _extract_binding_value(bindings, "ct")
        st_str = _extract_binding_value(bindings, "st")
        et_str = _extract_binding_value(bindings, "et")

        return ExistingEntityProps(
            creation_time=_parse_datetime_binding(ct_str),
            status=st_str,
            entity_type=et_str,
        )
    except Exception as e:
        logger.error("fetch_entity_server_props(%s) failed: %s", entity_uri, e)
        return None


async def batch_fetch_entity_server_props(
    backend_adapter,
    space_id: str,
    graph_id: str,
    entity_uris: List[str],
) -> Dict[str, ExistingEntityProps]:
    """Fetch server-managed props for multiple entities in one query.

    Returns a dict keyed by entity URI.  Missing URIs (entity doesn't
    exist) are absent from the dict.
    """
    if not entity_uris:
        return {}

    values_clause = " ".join(f"<{uri}>" for uri in entity_uris)
    sparql = f"""
    SELECT ?entity ?ct ?st ?et WHERE {{
        VALUES ?entity {{ {values_clause} }}
        GRAPH <{graph_id}> {{
            ?entity ?_any_pred ?_any_obj .
            OPTIONAL {{ ?entity <{CREATION_TIME_URI}> ?ct . }}
            OPTIONAL {{ ?entity <{STATUS_TYPE_URI}> ?st . }}
            OPTIONAL {{ ?entity <{ENTITY_TYPE_URI}> ?et . }}
        }}
    }}
    """
    try:
        result = await backend_adapter.execute_sparql_query(space_id, sparql)
        bindings = result.get("results", {}).get("bindings", [])

        props: Dict[str, ExistingEntityProps] = {}
        for binding in bindings:
            ent_entry = binding.get("entity")
            if not ent_entry:
                continue
            ent_uri = ent_entry.get("value")
            if not ent_uri or ent_uri in props:
                continue  # skip duplicates from OPTIONAL fan-out

            ct_str = binding.get("ct", {}).get("value") if binding.get("ct") else None
            st_str = binding.get("st", {}).get("value") if binding.get("st") else None
            et_str = binding.get("et", {}).get("value") if binding.get("et") else None

            props[ent_uri] = ExistingEntityProps(
                creation_time=_parse_datetime_binding(ct_str),
                status=st_str,
                entity_type=et_str,
            )
        return props
    except Exception as e:
        logger.error("batch_fetch_entity_server_props failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Targeted modification-time update (for frame writes)
# ---------------------------------------------------------------------------

async def touch_entity_modification_time(
    backend_adapter,
    space_id: str,
    graph_id: str,
    entity_uri: str,
    now: datetime,
) -> bool:
    """Update only the modification timestamp on an entity.

    Uses a single DELETE/INSERT SPARQL UPDATE — lightweight, single-triple
    operation.  Returns True on success.
    """
    now_str = now.isoformat()
    sparql = f"""
    DELETE {{
        GRAPH <{graph_id}> {{
            <{entity_uri}> <{MODIFICATION_TIME_URI}> ?old_mod .
        }}
    }}
    INSERT {{
        GRAPH <{graph_id}> {{
            <{entity_uri}> <{MODIFICATION_TIME_URI}> "{now_str}"^^<http://www.w3.org/2001/XMLSchema#dateTime> .
        }}
    }}
    WHERE {{
        GRAPH <{graph_id}> {{
            OPTIONAL {{ <{entity_uri}> <{MODIFICATION_TIME_URI}> ?old_mod . }}
        }}
    }}
    """
    try:
        result = await backend_adapter.execute_sparql_update(space_id, sparql)
        return bool(result)
    except Exception as e:
        logger.error("touch_entity_modification_time(%s) failed: %s", entity_uri, e)
        return False


# ---------------------------------------------------------------------------
# Backfill support — direct SQL against PostgreSQL term / rdf_quad tables
# ---------------------------------------------------------------------------

KGENTITY_CLASS_URI = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_DATETIME_URI = "http://www.w3.org/2001/XMLSchema#dateTime"

# UUID v5 namespace (matches sparql_sql_space_impl._VITALGRAPH_NS)
_VITALGRAPH_NS = _uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _term_uuid(text: str, term_type: str = 'U',
               lang: Optional[str] = None,
               datatype_id: Optional[int] = None) -> _uuid.UUID:
    """Deterministic UUID v5 for an RDF term — mirrors _generate_term_uuid."""
    parts = [text, term_type]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return _uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))


@dataclass
class BackfillResult:
    """Result of a backfill run for one graph."""
    space_id: str
    graph_id: str
    entities_scanned: int = 0
    entities_patched: int = 0
    errors: int = 0
    patched_entity_uris: List[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.patched_entity_uris is None:
            self.patched_entity_uris = []


async def _resolve_xsd_datetime_id(conn, space_id: str) -> Optional[int]:
    """Return the datatype_id for xsd:dateTime, creating it if needed."""
    dt_table = f"{space_id}_datatype"
    row = await conn.fetchrow(
        f"SELECT datatype_id FROM {dt_table} WHERE datatype_uri = $1",
        XSD_DATETIME_URI,
    )
    if row:
        return row['datatype_id']
    return await conn.fetchval(
        f"INSERT INTO {dt_table} (datatype_uri) VALUES ($1) "
        f"ON CONFLICT (datatype_uri) DO UPDATE SET datatype_uri = EXCLUDED.datatype_uri "
        f"RETURNING datatype_id",
        XSD_DATETIME_URI,
    )


async def _ensure_term_row(conn, term_table: str,
                           text: str, term_type: str = 'U',
                           lang: Optional[str] = None,
                           datatype_id: Optional[int] = None) -> _uuid.UUID:
    """Insert a term row if it doesn't exist; return its UUID."""
    tuuid = _term_uuid(text, term_type, lang, datatype_id)
    await conn.execute(
        f"INSERT INTO {term_table} (term_uuid, term_text, term_type, lang, datatype_id) "
        f"VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
        tuuid, text, term_type, lang, datatype_id,
    )
    return tuuid


async def discover_graphs_sql(pool, space_id: str) -> List[str]:
    """Return graph URIs in a space that contain KGEntity instances (direct SQL)."""
    t_quad = f"{space_id}_rdf_quad"
    t_term = f"{space_id}_term"
    rdf_type_uuid = _term_uuid(RDF_TYPE_URI)
    kgentity_uuid = _term_uuid(KGENTITY_CLASS_URI)
    sql = f"""
    SELECT DISTINCT gt.term_text AS graph_uri
    FROM {t_quad} q
    JOIN {t_term} gt ON gt.term_uuid = q.context_uuid
    WHERE q.predicate_uuid = $1 AND q.object_uuid = $2
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, rdf_type_uuid, kgentity_uuid)
    return [r['graph_uri'] for r in rows]


async def count_entities_needing_backfill_sql(pool, space_id: str, graph_id: str) -> int:
    """Count KGEntity subjects in *graph_id* that are missing any managed property."""
    t_quad = f"{space_id}_rdf_quad"
    rdf_type_uuid = _term_uuid(RDF_TYPE_URI)
    kgentity_uuid = _term_uuid(KGENTITY_CLASS_URI)
    graph_uuid = _term_uuid(graph_id)

    prop_uuids = [
        _term_uuid(CREATION_TIME_URI),
        _term_uuid(MODIFICATION_TIME_URI),
        _term_uuid(STATUS_TYPE_URI),
        _term_uuid(ENTITY_TYPE_URI),
    ]

    sql = f"""
    SELECT COUNT(*) FROM (
        SELECT q.subject_uuid
        FROM {t_quad} q
        WHERE q.predicate_uuid = $1 AND q.object_uuid = $2 AND q.context_uuid = $3
        AND (
            NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $4 AND x.context_uuid = $3) OR
            NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $5 AND x.context_uuid = $3) OR
            NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $6 AND x.context_uuid = $3) OR
            NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $7 AND x.context_uuid = $3)
        )
    ) sub
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            sql, rdf_type_uuid, kgentity_uuid, graph_uuid, *prop_uuids,
        )


async def _backfill_one_batch_sql(
    pool,
    space_id: str,
    graph_id: str,
    batch_size: int,
    now: datetime,
) -> List[str]:
    """Backfill one batch via direct SQL.  Returns list of patched entity URIs (empty = done)."""
    t_quad = f"{space_id}_rdf_quad"
    t_term = f"{space_id}_term"
    rdf_type_uuid = _term_uuid(RDF_TYPE_URI)
    kgentity_uuid = _term_uuid(KGENTITY_CLASS_URI)
    graph_uuid = _term_uuid(graph_id)

    ct_pred = _term_uuid(CREATION_TIME_URI)
    mt_pred = _term_uuid(MODIFICATION_TIME_URI)
    st_pred = _term_uuid(STATUS_TYPE_URI)
    et_pred = _term_uuid(ENTITY_TYPE_URI)

    # Find entity subject_uuids missing any property
    find_sql = f"""
    SELECT q.subject_uuid
    FROM {t_quad} q
    WHERE q.predicate_uuid = $1 AND q.object_uuid = $2 AND q.context_uuid = $3
    AND (
        NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $4 AND x.context_uuid = $3) OR
        NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $5 AND x.context_uuid = $3) OR
        NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $6 AND x.context_uuid = $3) OR
        NOT EXISTS (SELECT 1 FROM {t_quad} x WHERE x.subject_uuid = q.subject_uuid AND x.predicate_uuid = $7 AND x.context_uuid = $3)
    )
    LIMIT $8
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            find_sql, rdf_type_uuid, kgentity_uuid, graph_uuid,
            ct_pred, mt_pred, st_pred, et_pred,
            batch_size,
        )
        if not rows:
            return []

        entity_uuids = [r['subject_uuid'] for r in rows]

        # Resolve subject UUIDs to entity URIs for cache invalidation
        uri_rows = await conn.fetch(
            f"SELECT term_uuid, term_text FROM {t_term} WHERE term_uuid = ANY($1)",
            entity_uuids,
        )
        uuid_to_uri = {r['term_uuid']: r['term_text'] for r in uri_rows}

        # Resolve xsd:dateTime datatype_id for literal terms
        dt_id = await _resolve_xsd_datetime_id(conn, space_id)

        # Pre-compute object-value term UUIDs and ensure they exist
        now_str = now.isoformat()
        sentinel_str = EPOCH_SENTINEL.isoformat()

        ct_val_uuid = await _ensure_term_row(conn, t_term, sentinel_str, 'L', datatype_id=dt_id)
        mt_val_uuid = await _ensure_term_row(conn, t_term, now_str, 'L', datatype_id=dt_id)
        st_val_uuid = await _ensure_term_row(conn, t_term, DEFAULT_STATUS, 'U')
        et_val_uuid = await _ensure_term_row(conn, t_term, DEFAULT_ENTITY_TYPE, 'U')

        # For each entity, check which properties are missing and insert
        patched_uris: List[str] = []
        for subj_uuid in entity_uuids:
            # Which predicates already exist for this entity in this graph?
            existing = await conn.fetch(
                f"SELECT predicate_uuid FROM {t_quad} "
                f"WHERE subject_uuid = $1 AND context_uuid = $2 "
                f"AND predicate_uuid = ANY($3)",
                subj_uuid, graph_uuid,
                [ct_pred, mt_pred, st_pred, et_pred],
            )
            existing_preds = {r['predicate_uuid'] for r in existing}

            insert_rows = []
            if ct_pred not in existing_preds:
                insert_rows.append((subj_uuid, ct_pred, ct_val_uuid, graph_uuid))
            if mt_pred not in existing_preds:
                insert_rows.append((subj_uuid, mt_pred, mt_val_uuid, graph_uuid))
            if st_pred not in existing_preds:
                insert_rows.append((subj_uuid, st_pred, st_val_uuid, graph_uuid))
            if et_pred not in existing_preds:
                insert_rows.append((subj_uuid, et_pred, et_val_uuid, graph_uuid))

            if insert_rows:
                await conn.executemany(
                    f"INSERT INTO {t_quad} (subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                    f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                    insert_rows,
                )
                uri = uuid_to_uri.get(subj_uuid)
                if uri:
                    patched_uris.append(uri)

        return patched_uris


async def backfill_entity_server_properties_sql(
    pool,
    space_id: str,
    graph_id: str,
    batch_size: int = 200,
    batch_delay: float = 0.1,
    max_batches: int = 0,
) -> BackfillResult:
    """Backfill missing server-managed properties via direct SQL.

    Processes entities in batches until none remain (or *max_batches* reached).
    Set ``max_batches=1`` to process exactly one batch (incremental mode).

    Args:
        pool: asyncpg connection pool.
        space_id: Space identifier (table prefix).
        graph_id: Graph URI.
        batch_size: Entities per batch.
        batch_delay: Seconds to sleep between batches.
        max_batches: Stop after this many batches (0 = unlimited).

    Returns:
        BackfillResult with counts.
    """
    from ..cache.entity_graph_cache import _entity_graph_cache
    from ..cache.count_cache import _count_cache
    import hashlib as _hashlib

    result = BackfillResult(space_id=space_id, graph_id=graph_id)

    # Derive a stable advisory lock key from (space_id, graph_id).
    # pg_try_advisory_lock takes a single bigint; we use a hash to avoid collisions.
    _lock_input = f"backfill:{space_id}:{graph_id}".encode()
    _lock_key = int.from_bytes(_hashlib.sha256(_lock_input).digest()[:8], 'big', signed=True)

    async with pool.acquire() as lock_conn:
        got_lock = await lock_conn.fetchval(
            "SELECT pg_try_advisory_lock($1)", _lock_key
        )
        if not got_lock:
            logger.info("Backfill skipped %s/%s — another instance holds the lock",
                        space_id, graph_id)
            return result

        try:
            now = datetime.now(timezone.utc)
            batch_num = 0
            _count_invalidated = False

            while True:
                if max_batches and batch_num >= max_batches:
                    break
                try:
                    patched_uris = await _backfill_one_batch_sql(
                        pool, space_id, graph_id, batch_size, now
                    )
                except Exception as e:
                    logger.error("backfill batch %d for %s/%s failed: %s",
                                 batch_num, space_id, graph_id, e)
                    result.errors += 1
                    break

                result.entities_scanned += batch_size if patched_uris else 0
                result.entities_patched += len(patched_uris)
                result.patched_entity_uris.extend(patched_uris)
                batch_num += 1

                if not patched_uris:
                    break

                # Invalidate caches for patched entities
                for uri in patched_uris:
                    _entity_graph_cache.invalidate(space_id, graph_id, uri)
                if not _count_invalidated:
                    _count_cache.invalidate_graph(space_id, graph_id)
                    _count_invalidated = True

                if batch_delay > 0:
                    await _asyncio.sleep(batch_delay)
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", _lock_key)

    return result
