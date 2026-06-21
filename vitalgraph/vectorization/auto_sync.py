"""
Auto-sync hooks for vector, geo, fuzzy, and FTS data.

Provides fire-and-forget post-CRUD sync that re-vectorizes and/or
re-populates geo and fuzzy data for changed subjects.  The caller is not blocked;
sync runs as a background asyncio task.

Usage from an endpoint::

    from vitalgraph.vectorization.auto_sync import schedule_sync

    # After a successful entity create/update:
    schedule_sync(
        db_impl=backend_impl.db_impl,
        space_id=space_id,
        subject_uris=created_uris,   # list of changed subject URIs
        graph_uri=graph_id,           # named graph URI
        operation="upsert",           # "upsert" or "delete"
    )
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import List, Literal, Optional

logger = logging.getLogger(__name__)

# Deterministic UUID namespace (matches sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _generate_term_uuid(term_text: str, term_type: str = 'U') -> uuid.UUID:
    """Deterministic UUID for a term (same algorithm as sparql_sql_space_impl)."""
    raw = f"{term_text}\x00{term_type}"
    return uuid.uuid5(_VITALGRAPH_NS, raw)


# -----------------------------------------------------------------------
# Core sync logic (runs inside a background task)
# -----------------------------------------------------------------------

async def _sync_vectors_for_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> None:
    """Re-vectorize or delete vectors for a list of subject UUIDs."""
    from vitalgraph.vectorization.vector_populator import (
        update_subject_vector,
        delete_subject_vectors,
    )

    # Discover all vector indexes for this space
    try:
        rows = await conn.fetch(
            f"SELECT index_name FROM {space_id}_vector_index"
        )
    except Exception:
        # Table may not exist on spaces without vector indexes
        return

    if not rows:
        return

    index_names = [r["index_name"] for r in rows]

    for subj_uuid in subject_uuids:
        for idx_name in index_names:
            try:
                if operation == "delete":
                    await delete_subject_vectors(conn, space_id, idx_name, subj_uuid, context_uuid)
                else:
                    await update_subject_vector(conn, space_id, idx_name, subj_uuid, context_uuid)
            except Exception as e:
                logger.warning(
                    "auto_sync vector %s/%s/%s failed: %s",
                    space_id, idx_name, subj_uuid, e,
                )


async def _sync_geo_for_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> None:
    """Re-populate or delete geo data for a list of subject UUIDs."""
    from vitalgraph.vectorization.geo_populator import (
        update_subject_geo,
        delete_subject_geo,
        resolve_geo_config,
    )
    from vitalgraph.vectorization.geo_slot_handler import detect_and_process_geo_slots

    geo_config = await resolve_geo_config(conn, space_id)

    # If geo is not enabled or auto_sync is off, skip
    if geo_config is None:
        return
    if not geo_config.enabled or not geo_config.auto_sync:
        return

    # Path 1: Datatype-driven geo (detects geo-typed literals on subject)
    for subj_uuid in subject_uuids:
        try:
            if operation == "delete":
                await delete_subject_geo(conn, space_id, subj_uuid, context_uuid)
            else:
                await update_subject_geo(
                    conn, space_id, subj_uuid, context_uuid,
                    geo_config=geo_config,
                )
        except Exception as e:
            logger.warning(
                "auto_sync geo %s/%s failed: %s",
                space_id, subj_uuid, e,
            )

    # Path 2: KGGeoLocationSlot-based geo (detects slots and populates entity geo)
    try:
        await detect_and_process_geo_slots(
            conn, space_id, subject_uuids, context_uuid, operation=operation,
        )
    except Exception as e:
        logger.warning("auto_sync geo_slot %s failed: %s", space_id, e)


async def _sync_fuzzy_for_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> None:
    """Re-index or delete fuzzy bands for a list of subject UUIDs."""
    from vitalgraph.vectorization.fuzzy_populator import (
        update_subject_fuzzy,
        remove_subject_fuzzy,
    )

    # Quick check: does this space have any fuzzy mappings?
    try:
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM {space_id}_fuzzy_mapping WHERE enabled = TRUE"
        )
    except Exception:
        # Table may not exist
        return

    if not count:
        return

    for subj_uuid in subject_uuids:
        try:
            if operation == "delete":
                await remove_subject_fuzzy(conn, space_id, subj_uuid)
            else:
                await update_subject_fuzzy(conn, space_id, subj_uuid, context_uuid)
        except Exception as e:
            logger.warning(
                "auto_sync fuzzy %s/%s failed: %s",
                space_id, subj_uuid, e,
            )


async def _sync_fts_for_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> None:
    """Re-index or delete FTS data for a list of subject UUIDs."""
    from vitalgraph.vectorization.fts_populator import (
        update_subject_fts,
        delete_subject_fts,
    )

    # Quick check: does this space have any FTS indexes?
    try:
        rows = await conn.fetch(
            f"SELECT index_name FROM {space_id}_fts_index"
        )
    except Exception:
        # Table may not exist
        return

    if not rows:
        return

    index_names = [r["index_name"] for r in rows]

    for subj_uuid in subject_uuids:
        for idx_name in index_names:
            try:
                if operation == "delete":
                    await delete_subject_fts(conn, space_id, idx_name, subj_uuid, context_uuid)
                else:
                    await update_subject_fts(conn, space_id, idx_name, subj_uuid, context_uuid)
            except Exception as e:
                logger.warning(
                    "auto_sync fts %s/%s/%s failed: %s",
                    space_id, idx_name, subj_uuid, e,
                )


async def _run_sync(
    db_impl,
    space_id: str,
    subject_uris: List[str],
    graph_uri: str,
    operation: str,
) -> None:
    """Core sync coroutine: acquire connection and sync vector + geo + fuzzy."""
    if not subject_uris:
        return

    pool = getattr(db_impl, 'connection_pool', None)
    if pool is None:
        logger.debug("auto_sync: no connection_pool on db_impl, skipping")
        return

    context_uuid = _generate_term_uuid(graph_uri)
    subject_uuids = [_generate_term_uuid(uri) for uri in subject_uris]

    try:
        async with pool.acquire() as conn:
            # Vector sync
            await _sync_vectors_for_subjects(
                conn, space_id, subject_uuids, context_uuid, operation,
            )
            # Geo sync
            await _sync_geo_for_subjects(
                conn, space_id, subject_uuids, context_uuid, operation,
            )
            # Fuzzy sync
            await _sync_fuzzy_for_subjects(
                conn, space_id, subject_uuids, context_uuid, operation,
            )
            # FTS sync
            await _sync_fts_for_subjects(
                conn, space_id, subject_uuids, context_uuid, operation,
            )
    except Exception as e:
        logger.error("auto_sync(%s) failed: %s", space_id, e)


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def schedule_sync(
    *,
    db_impl,
    space_id: str,
    subject_uris: List[str],
    graph_uri: str,
    operation: Literal["upsert", "delete"] = "upsert",
) -> Optional[asyncio.Task]:
    """Schedule a background auto-sync task (non-blocking).

    Args:
        db_impl: Database implementation with ``connection_pool`` attribute.
        space_id: Space identifier.
        subject_uris: List of changed subject URIs.
        graph_uri: Named graph URI.
        operation: ``"upsert"`` for create/update, ``"delete"`` for deletion.

    Returns:
        The asyncio.Task if scheduled, or None if nothing to sync.
    """
    if not subject_uris:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("auto_sync: no running event loop, skipping")
        return None

    task = loop.create_task(
        _run_sync(db_impl, space_id, subject_uris, graph_uri, operation),
        name=f"auto_sync:{space_id}:{len(subject_uris)}",
    )

    # Swallow exceptions so they don't surface as "unhandled task exception"
    def _on_done(t: asyncio.Task):
        if t.exception():
            logger.error("auto_sync task failed: %s", t.exception())

    task.add_done_callback(_on_done)
    return task
