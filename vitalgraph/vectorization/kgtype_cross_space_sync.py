"""Cross-space re-sync when KG Type descriptions change.

When a KGType is created or updated in sp_kg_types, any subjects in other
spaces that reference that type URI (via hasKGEntityType, hasKGFrameType, etc.)
may need their vector/FTS embeddings refreshed — but only if the space has a
search mapping with source_type in ('type_description', 'properties_type').

This module provides a fire-and-forget background task that:
1. Iterates all registered spaces (except sp_kg_types itself).
2. Checks each space for search mappings with type-description source modes.
3. For each such mapping, finds subjects whose type URI matches an updated type.
4. Schedules vector + FTS re-sync for those subjects.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Set

from vitalgraph.constants import SP_KG_TYPES, TYPE_URI_PROPERTIES

logger = logging.getLogger(__name__)

# Deterministic UUID namespace (matches auto_sync / sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _generate_term_uuid(term_text: str, term_type: str = 'U') -> uuid.UUID:
    raw = f"{term_text}\x00{term_type}"
    return uuid.uuid5(_VITALGRAPH_NS, raw)


async def _find_affected_subjects(
    conn,
    space_id: str,
    mapping_type: str,
    type_uris: List[str],
) -> List[str]:
    """Find subject URIs in *space_id* whose type URI is in *type_uris*.

    Looks up the type-URI property (e.g. hasKGEntityType) for the given
    mapping_type and queries the space's rdf_quad + term tables.
    """
    type_uri_property = TYPE_URI_PROPERTIES.get(mapping_type)
    if not type_uri_property:
        return []

    pred_uuid = _generate_term_uuid(type_uri_property)
    obj_uuids = [_generate_term_uuid(uri) for uri in type_uris]

    if not obj_uuids:
        return []

    # Build parameterised IN clause
    placeholders = ", ".join(f"${i+2}" for i in range(len(obj_uuids)))
    sql = f"""
        SELECT DISTINCT t_subj.text AS subject_uri
        FROM {space_id}_rdf_quad q
        JOIN {space_id}_term t_subj ON q.subject = t_subj.id
        WHERE q.predicate = $1
          AND q.object IN ({placeholders})
    """
    params = [pred_uuid, *obj_uuids]

    try:
        rows = await conn.fetch(sql, *params)
        return [r["subject_uri"] for r in rows]
    except Exception as e:
        logger.warning("cross_space_sync: query subjects in %s failed: %s", space_id, e)
        return []


async def _run_cross_space_sync(
    space_manager,
    updated_type_uris: List[str],
) -> None:
    """Core coroutine: scan all spaces and re-sync affected subjects."""
    from vitalgraph.vectorization.auto_sync import schedule_sync

    all_space_ids = space_manager.list_spaces()
    # Exclude sp_kg_types — its own vectors are synced by the normal auto_sync
    target_spaces = [s for s in all_space_ids if s != SP_KG_TYPES]

    if not target_spaces:
        return

    # We need a DB connection to query search_mapping tables
    # Get db_impl from the space_manager
    db_impl = space_manager.db_impl
    pool = getattr(db_impl, 'connection_pool', None)
    if pool is None:
        logger.debug("cross_space_sync: no connection_pool, skipping")
        return

    total_synced = 0

    try:
        async with pool.acquire() as conn:
            for space_id in target_spaces:
                try:
                    # Check if this space has any mappings that use type descriptions
                    rows = await conn.fetch(
                        f"SELECT DISTINCT mapping_type FROM {space_id}_search_mapping "
                        f"WHERE source_type IN ('type_description', 'properties_type') "
                        f"AND enabled = TRUE"
                    )
                except Exception:
                    # Table may not exist
                    continue

                if not rows:
                    continue

                mapping_types = [r["mapping_type"] for r in rows]

                # For each mapping_type, find subjects referencing the updated types
                affected_uris: Set[str] = set()
                for mt in mapping_types:
                    uris = await _find_affected_subjects(conn, space_id, mt, updated_type_uris)
                    affected_uris.update(uris)

                if not affected_uris:
                    continue

                # Determine graph URI for the space
                # Use the default graph pattern
                graph_uri = f"urn:vitalgraph:{space_id}:graph_default"

                logger.info(
                    "cross_space_sync: scheduling re-sync for %d subjects in %s "
                    "(mapping_types=%s, updated_types=%s)",
                    len(affected_uris), space_id, mapping_types, updated_type_uris,
                )

                # Get the space's db_impl for schedule_sync
                space_record = space_manager.get_space(space_id)
                if not space_record:
                    continue
                space_db_impl = getattr(
                    space_record.space_impl.get_db_space_impl(), 'db_impl', None
                )
                if space_db_impl is None:
                    space_db_impl = db_impl

                schedule_sync(
                    db_impl=space_db_impl,
                    space_id=space_id,
                    subject_uris=list(affected_uris),
                    graph_uri=graph_uri,
                    operation="upsert",
                )
                total_synced += len(affected_uris)

    except Exception as e:
        logger.error("cross_space_sync failed: %s", e)

    if total_synced:
        logger.info("cross_space_sync: queued re-sync for %d total subjects across spaces", total_synced)


def schedule_cross_space_sync(
    *,
    space_manager,
    updated_type_uris: List[str],
) -> Optional[asyncio.Task]:
    """Schedule a background cross-space re-sync (non-blocking).

    Call this after KGType create/update in sp_kg_types to propagate
    description changes to subjects in other spaces.

    Args:
        space_manager: The SpaceManager instance (for listing spaces).
        updated_type_uris: URIs of the KGTypes that were created/updated.

    Returns:
        The asyncio.Task if scheduled, or None.
    """
    if not updated_type_uris:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("cross_space_sync: no running event loop, skipping")
        return None

    task = loop.create_task(
        _run_cross_space_sync(space_manager, updated_type_uris),
        name=f"cross_space_sync:{len(updated_type_uris)}types",
    )

    def _on_done(t: asyncio.Task):
        if t.exception():
            logger.error("cross_space_sync task failed: %s", t.exception())

    task.add_done_callback(_on_done)
    return task
