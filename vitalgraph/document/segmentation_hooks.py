"""
Quad-level segmentation detection hooks.

Scans changed quads (from SPARQL UPDATE or generic quad writes) for
KGDocument content-affecting predicates.  When detected, enqueues a
background segmentation job via the SegmentationJobManager.

Integrates alongside the existing entity-graph-cache invalidation in
``sparql_sql_space_impl.execute_sparql_update`` and the auto_sync hooks
in endpoint code.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Predicates whose change implies the document's segments may be stale.
_SEGMENTATION_PREDICATES = frozenset([
    "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentContent",
    "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentExtractedContent",
    "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentHTMLContent",
])

# Segment types that should NOT trigger re-segmentation (they are managed).
_MANAGED_SEGMENT_TYPES = frozenset([
    "urn:segtype:segmentation_parent",
    "urn:segtype:markdown_section",
    "urn:segtype:text_chunk",
    "urn:segtype:paragraph",
])

_HAS_SEGMENT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTypeURI"


# -----------------------------------------------------------------------
# Detection: collect (subject_uri, graph_uri) pairs that need re-segment
# -----------------------------------------------------------------------

def collect_segmentation_targets_from_update_ops(
    ops: list,
    space_id: str,
) -> Set[Tuple[str, str]]:
    """Scan SPARQL UPDATE ops for document content changes.

    Returns set of ``(document_uri, graph_uri)`` pairs to re-segment.
    Pure in-memory — no DB queries.
    """
    from ..db.jena_sparql.jena_types import (
        URINode,
        UpdateDataInsert, UpdateDataDelete, UpdateModify, UpdateDeleteWhere,
    )

    def _uri_of(node) -> Optional[str]:
        return node.value if isinstance(node, URINode) else None

    targets: Set[Tuple[str, str]] = set()
    # Track subjects that are managed segments (skip them)
    managed_subjects: Set[str] = set()

    for op in ops:
        quads: list = []
        if isinstance(op, UpdateDataInsert):
            quads = op.quads
        elif isinstance(op, UpdateDataDelete):
            quads = op.quads
        elif isinstance(op, UpdateModify):
            quads = op.delete_quads + op.insert_quads
        elif isinstance(op, UpdateDeleteWhere):
            quads = op.quads

        # First pass: identify managed segments so we skip them
        for q in quads:
            sub_uri = _uri_of(q.subject)
            pred_uri = _uri_of(q.predicate)
            obj_uri = _uri_of(q.object) if hasattr(q.object, 'value') else None
            obj_text = getattr(q.object, 'value', None) if not obj_uri else None

            if sub_uri and pred_uri == _HAS_SEGMENT_TYPE:
                val = obj_uri or obj_text
                if val and val in _MANAGED_SEGMENT_TYPES:
                    managed_subjects.add(sub_uri)

        # Second pass: detect content changes
        for q in quads:
            sub_uri = _uri_of(q.subject)
            pred_uri = _uri_of(q.predicate)
            graph_uri = _uri_of(q.graph) if q.graph else None

            if sub_uri and pred_uri in _SEGMENTATION_PREDICATES:
                if sub_uri not in managed_subjects:
                    if graph_uri:
                        targets.add((sub_uri, graph_uri))

    return targets


def collect_segmentation_targets_from_quads(
    quads: list,
    space_id: str,
) -> Set[Tuple[str, str]]:
    """Scan raw rdflib quads (s, p, o, g) for document content changes.

    Returns set of ``(document_uri, graph_uri)`` pairs to re-segment.
    """
    from rdflib import URIRef

    targets: Set[Tuple[str, str]] = set()
    managed_subjects: Set[str] = set()

    # First pass: identify managed segments
    for s, p, o, g in quads:
        s_str = str(s) if isinstance(s, URIRef) else None
        p_str = str(p) if isinstance(p, URIRef) else None
        o_str = str(o)

        if s_str and p_str == _HAS_SEGMENT_TYPE:
            if o_str in _MANAGED_SEGMENT_TYPES:
                managed_subjects.add(s_str)

    # Second pass: detect content changes
    for s, p, o, g in quads:
        s_str = str(s) if isinstance(s, URIRef) else None
        p_str = str(p) if isinstance(p, URIRef) else None
        g_str = str(g) if isinstance(g, URIRef) else None

        if s_str and p_str in _SEGMENTATION_PREDICATES:
            if s_str not in managed_subjects and g_str:
                targets.add((s_str, g_str))

    return targets


# -----------------------------------------------------------------------
# Enqueue: fire-and-forget background task
# -----------------------------------------------------------------------

def schedule_resegmentation(
    *,
    db_impl,
    space_id: str,
    targets: Set[Tuple[str, str]],
) -> Optional[asyncio.Task]:
    """Schedule background re-segmentation jobs for detected targets.

    Non-blocking fire-and-forget, same pattern as ``auto_sync.schedule_sync``.

    Args:
        db_impl: Database impl with ``connection_pool`` attribute.
        space_id: Space identifier.
        targets: Set of (document_uri, graph_uri) pairs.

    Returns:
        asyncio.Task or None.
    """
    if not targets:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("schedule_resegmentation: no running event loop, skipping")
        return None

    task = loop.create_task(
        _enqueue_jobs(db_impl, space_id, targets),
        name=f"reseg_hook:{space_id}:{len(targets)}",
    )

    def _on_done(t: asyncio.Task):
        if t.exception():
            logger.error("resegmentation hook task failed: %s", t.exception())

    task.add_done_callback(_on_done)
    return task


async def _enqueue_jobs(
    db_impl,
    space_id: str,
    targets: Set[Tuple[str, str]],
) -> None:
    """Enqueue segmentation jobs for each target."""
    from .segmentation_job_manager import SegmentationJobManager

    pool = getattr(db_impl, 'connection_pool', None)
    if pool is None:
        logger.debug("resegmentation hook: no connection_pool, skipping")
        return

    try:
        async with pool.acquire() as conn:
            manager = SegmentationJobManager(conn, space_id)
            await manager.ensure_table()
            for document_uri, graph_uri in targets:
                try:
                    job_id = await manager.enqueue(
                        graph_id=graph_uri,
                        document_uri=document_uri,
                    )
                    logger.info(
                        "Quad-level hook: enqueued segmentation job %d for %s in %s",
                        job_id, document_uri, space_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Quad-level hook: failed to enqueue segmentation for %s: %s",
                        document_uri, e,
                    )
    except Exception as e:
        logger.error("resegmentation hook failed: %s", e)
