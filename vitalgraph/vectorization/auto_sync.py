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

import asyncpg
from typing import Dict, List, Literal, Optional, Set

logger = logging.getLogger(__name__)

# In-flight auto-sync tasks, keyed by space, so a space deletion can cancel work
# that would otherwise run against dropped tables.  Callers of schedule_sync()
# discard the returned Task, so without this registry those tasks are
# unreachable.  Process-local by nature — see cancel_space_syncs().
_IN_FLIGHT: Dict[str, Set[asyncio.Task]] = {}

# Deterministic UUID namespace (matches sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _generate_term_uuid(term_text: str, term_type: str = 'U') -> uuid.UUID:
    """Deterministic UUID for a term (same algorithm as sparql_sql_space_impl)."""
    raw = f"{term_text}\x00{term_type}"
    return uuid.uuid5(_VITALGRAPH_NS, raw)


# -----------------------------------------------------------------------
# Core sync logic (runs inside a background task)
# -----------------------------------------------------------------------

# Max concurrent embedding calls (limits CPU pressure for ONNX inference)
_VECTOR_CONCURRENCY = 8


async def _sync_vectors_for_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> None:
    """Re-vectorize or delete vectors for a list of subject UUIDs.

    For upserts with multiple subjects, uses a three-phase approach:
      1. Batch-fetch all literal properties (single DB query)
      2. Embed all texts in one batched provider call (falls back to
         per-subject, bounded by _VECTOR_CONCURRENCY, if the batch fails)
      3. Sequentially upsert embeddings on the single connection
    """
    from vitalgraph.vectorization.vector_populator import (
        delete_subject_vectors,
        UPSERT_VECTOR_SQL,
    )
    from vitalgraph.vectorization.search_text_builder import (
        build_search_text,
        fetch_literal_properties_batch,
    )
    from vitalgraph.vectorization.registry import get_provider

    # Discover all vector indexes for this space
    try:
        rows = await conn.fetch(
            f"SELECT index_name, provider, provider_config FROM {space_id}_vector_index"
        )
    except asyncpg.exceptions.UndefinedTableError:
        # No vector indexes configured for this space. Narrow on purpose: a
        # broad `except Exception` here would also swallow real query failures.
        return

    if not rows:
        return

    # For deletes, run sequentially (fast DB-only operations)
    if operation == "delete":
        for subj_uuid in subject_uuids:
            for row in rows:
                try:
                    await delete_subject_vectors(
                        conn, space_id, row["index_name"], subj_uuid, context_uuid)
                except Exception as e:
                    logger.warning(
                        "auto_sync vector delete %s/%s/%s failed: %s",
                        space_id, row["index_name"], subj_uuid, e,
                    )
        return

    # ── Upsert path: batch fetch → concurrent embed → sequential upsert ──

    # Phase 1: Batch-fetch literal properties for all subjects (1 DB query)
    props_by_subject = await fetch_literal_properties_batch(
        conn, space_id, subject_uuids, context_uuid,
    )

    # Process each index
    for row in rows:
        idx_name = row["index_name"]
        provider = get_provider(
            row["provider"], row["provider_config"] or {},
            cache_key=f"{space_id}:{idx_name}",
        )
        vec_table = f"{space_id}_vec_{idx_name}"
        upsert_sql = UPSERT_VECTOR_SQL.format(vec_table=vec_table)

        # Phase 2: Build search texts and identify subjects to embed
        to_embed: List[tuple] = []  # (subj_uuid, search_text)
        to_delete: List[uuid.UUID] = []

        for subj_uuid in subject_uuids:
            props = props_by_subject.get(subj_uuid)
            if not props:
                to_delete.append(subj_uuid)
                continue
            text = build_search_text(props, None)
            if not text.strip():
                to_delete.append(subj_uuid)
                continue
            to_embed.append((subj_uuid, text))

        # Delete subjects with no embeddable text
        for subj_uuid in to_delete:
            try:
                await delete_subject_vectors(conn, space_id, idx_name, subj_uuid, context_uuid)
            except Exception as e:
                logger.warning(
                    "auto_sync vector delete %s/%s/%s failed: %s",
                    space_id, idx_name, subj_uuid, e,
                )

        if not to_embed:
            continue

        # Phase 3: Batch embedding.
        #
        # One request for the whole set, not one per subject.  vectorize_texts
        # chunks internally at the provider's batch_size (100 for OpenAI), so a
        # large set is safe; results come back in input order, which Phase 4
        # relies on when it zips embeddings[i] against to_embed[i].
        #
        # This used to fire vectorize_text() per subject through a semaphore of
        # _VECTOR_CONCURRENCY, i.e. one HTTP round trip per entity/frame/slot
        # covered by the index — 100 subjects meant 100 requests in 13 waves of
        # 8.  See issues/037.
        embeddings: List[Optional[List[float]]] = [None] * len(to_embed)
        texts = [text for _, text in to_embed]
        try:
            embeddings = list(await provider.vectorize_texts(texts))
        except Exception as e:
            # A batch failure would otherwise lose every subject in the set, so
            # fall back to per-subject embedding to preserve the previous
            # behaviour of isolating one bad text from the rest.
            logger.warning(
                "auto_sync batch embed %s/%s (%d texts) failed: %s — "
                "falling back to per-subject",
                space_id, idx_name, len(texts), e,
            )
            sem = asyncio.Semaphore(_VECTOR_CONCURRENCY)

            async def _embed(idx: int, text: str):
                async with sem:
                    try:
                        embeddings[idx] = await provider.vectorize_text(text)
                    except Exception as e2:
                        logger.warning(
                            "auto_sync embed %s/%s/%s failed: %s",
                            space_id, idx_name, to_embed[idx][0], e2,
                        )

            await asyncio.gather(*[
                _embed(i, text) for i, text in enumerate(texts)
            ])

        # Phase 4: Sequential upsert on the single connection
        for i, (subj_uuid, _) in enumerate(to_embed):
            emb = embeddings[i]
            if emb is None:
                continue
            try:
                vec_str = "[" + ",".join(str(v) for v in emb) + "]"
                await conn.execute(upsert_sql, subj_uuid, context_uuid, vec_str)
            except Exception as e:
                logger.warning(
                    "auto_sync vector upsert %s/%s/%s failed: %s",
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
    except asyncpg.exceptions.UndefinedTableError:
        # No fuzzy mappings configured for this space.
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
    except asyncpg.exceptions.UndefinedTableError:
        # No FTS indexes configured for this space.
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


async def _space_still_exists(conn, space_id: str) -> bool:
    """Cheap catalog check that the space's tables are still present.

    Guards against syncing a space that was deleted while this task sat in the
    queue. Checked BEFORE any embedding work: the vector step calls out to the
    embedding provider first and only then writes, so a check placed later
    would still incur (billed) API calls for a space that no longer exists.

    Also covers the multi-worker case, where the deletion happened in a
    different process and cancel_space_syncs() could not reach this task.
    """
    return bool(
        await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{space_id}_rdf_quad")
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
            if not await _space_still_exists(conn, space_id):
                logger.debug(
                    "auto_sync: space '%s' no longer exists — skipping sync of "
                    "%d subject(s)", space_id, len(subject_uuids),
                )
                return

            # Vector sync (uses concurrent embedding internally)
            await _sync_vectors_for_subjects(
                conn, space_id, subject_uuids, context_uuid, operation,
            )
            # Geo, fuzzy, FTS share the same connection — must be sequential
            await _sync_geo_for_subjects(
                conn, space_id, subject_uuids, context_uuid, operation,
            )
            await _sync_fuzzy_for_subjects(
                conn, space_id, subject_uuids, context_uuid, operation,
            )
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

    # Track it so deleting the space can cancel work still in flight.  Without
    # this the task is unreachable: callers fire-and-forget the return value.
    _IN_FLIGHT.setdefault(space_id, set()).add(task)

    # Swallow exceptions so they don't surface as "unhandled task exception"
    def _on_done(t: asyncio.Task):
        pending = _IN_FLIGHT.get(space_id)
        if pending is not None:
            pending.discard(t)
            if not pending:
                _IN_FLIGHT.pop(space_id, None)
        if t.cancelled():
            return
        if t.exception():
            logger.error("auto_sync task failed: %s", t.exception())

    task.add_done_callback(_on_done)
    return task


async def cancel_space_syncs(space_id: str, *, timeout: float = 5.0) -> int:
    """Cancel auto-sync tasks still in flight for a space, and wait for them.

    Call this BEFORE dropping a space's tables. Otherwise queued tasks wake up
    against a half-dropped schema: they log a wall of "relation ... does not
    exist" errors (PostgreSQL records every failed statement server-side even
    though the client swallows it) and, worse, spend real money embedding text
    for a space that is being deleted.

    Only reaches tasks in THIS process; `_space_still_exists()` in `_run_sync`
    is the backstop for multi-worker deployments.

    Returns:
        The number of tasks cancelled.
    """
    pending = _IN_FLIGHT.get(space_id)
    if not pending:
        return 0

    tasks = list(pending)
    for t in tasks:
        t.cancel()

    # Await them so the tables are not dropped while a cancelled task is still
    # unwinding mid-statement.
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "auto_sync: %d task(s) for space '%s' did not stop within %.1fs",
            len(tasks), space_id, timeout,
        )

    logger.info(
        "auto_sync: cancelled %d in-flight task(s) for space '%s'",
        len(tasks), space_id,
    )
    return len(tasks)
