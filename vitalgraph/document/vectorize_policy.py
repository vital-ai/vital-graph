"""Whether a subject is vectorized — the one rule every vector writer applies.

Research documents must not be embedded, and there was no way to say so: a
create scheduled vectorization, segmentation queued it again, and nothing could
opt out per request or per document type (`issues/285`).

THE RULE, in precedence order, for any subject a vector writer is about to
embed:

  1. An explicit `hasKGIndexStatusURI` on the subject decides.
     `KGIndexStatus_NO_INDEX` means skip, and any existing vectors are removed.
     `KGIndexStatus_VECTOR` means embed, overriding the document type's default.
     This is the per-request override: `vectorize=false|true` on create, upload
     and segment writes it, so it survives later updates and re-segmentation.
  2. Otherwise, a WHOLE document (not a segment) whose `kGDocumentType` has
     enabled segmentation configs is skipped when none of them sets
     `auto_vectorize`. This is the per-type default, on the setting that already
     existed and was never read.
  3. Otherwise it is embedded, as before.

SEGMENTS FOLLOW THEIR ORIGINAL BY STAMP, not by lookup. A segment's
`kGDocumentType` is `urn:kgdoctype:document_segment` and nothing on it names the
source document, so rule 2 cannot reach it. The segmentation worker therefore
resolves the original's decision and writes it onto the parent copy and every
segment (`segment_index_status`), after which rule 1 covers them everywhere --
auto-sync, the worker's own vectorization, and a bulk reindex.

THE ONTOLOGY ALREADY HAD THIS. `hasKGIndexStatusURI` is declared on every
`KGNode` with exactly these two values; it was simply unused. `NO_INDEX` is read
as "no VECTOR index" -- `VECTOR` is the only alternative the ontology defines,
and full-text search is unaffected.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, Optional, Set

logger = logging.getLogger(__name__)

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
INDEX_STATUS_PROPERTY = f"{HALEY}hasKGIndexStatusURI"
INDEX_STATUS_NO_INDEX = f"{HALEY}KGIndexStatus_NO_INDEX"
INDEX_STATUS_VECTOR = f"{HALEY}KGIndexStatus_VECTOR"

_SEGMENT_INDEX = f"{HALEY}hasKGDocumentSegmentIndex"
_DOCUMENT_TYPE = f"{HALEY}hasKGDocumentType"


def status_for(vectorize: Optional[bool]) -> Optional[str]:
    """The status URI a `vectorize` request flag writes, or None for unset."""
    if vectorize is None:
        return None
    return INDEX_STATUS_VECTOR if vectorize else INDEX_STATUS_NO_INDEX


async def types_with_vectorize_off(conn, space_id: str,
                                   doc_types: Iterable[str]) -> Set[str]:
    """The document types whose enabled segmentation configs all leave
    `auto_vectorize` off. A type with no enabled config is not in the set.

    A space without the config table has no configs, so nothing is off --
    checked with `to_regclass` rather than caught, so a real failure is not
    mistaken for "no configs".
    """
    types = sorted({t for t in doc_types if t})
    if not types:
        return set()
    table = f"{space_id}_document_segmentation_config"
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table):
        return set()
    rows = await conn.fetch(
        f"SELECT document_type_uri FROM {table} "
        f"WHERE enabled AND document_type_uri = ANY($1::text[]) "
        f"GROUP BY document_type_uri HAVING NOT bool_or(auto_vectorize)",
        types)
    return {r["document_type_uri"] for r in rows}


_STATE_SQL = """
SELECT q.subject_uuid,
       max(CASE WHEN tp.term_text = $3 THEN tv.term_text END) AS index_status,
       max(CASE WHEN tp.term_text = $4 THEN tv.term_text END) AS segment_index,
       max(CASE WHEN tp.term_text = $5 THEN tv.term_text END) AS document_type
FROM {rdf_quad} q
JOIN {term} tp ON tp.term_uuid = q.predicate_uuid
JOIN {term} tv ON tv.term_uuid = q.object_uuid
WHERE q.subject_uuid = ANY($1::uuid[])
  AND q.context_uuid = $2
  AND tp.term_text IN ($3, $4, $5)
GROUP BY q.subject_uuid
"""


async def vector_opt_outs(conn, space_id: str, subject_uuids,
                          context_uuid) -> Set[str]:
    """`str(subject_uuid)` of every subject the rule says NOT to embed.

    Keys are strings for the reason `auto_sync` records: asyncpg returns
    `uuid.UUID` and callers hold either form, and a mismatch does not raise --
    it misses.
    """
    subject_uuids = list(subject_uuids)
    if not subject_uuids:
        return set()
    rows = await conn.fetch(
        _STATE_SQL.format(rdf_quad=f"{space_id}_rdf_quad",
                          term=f"{space_id}_term"),
        subject_uuids, context_uuid,
        INDEX_STATUS_PROPERTY, _SEGMENT_INDEX, _DOCUMENT_TYPE)
    off: Set[str] = set()
    by_type: Dict[str, list] = {}
    for r in rows:
        key = str(r["subject_uuid"])
        status = r["index_status"]
        if status == INDEX_STATUS_NO_INDEX:
            off.add(key)
        elif status == INDEX_STATUS_VECTOR:
            continue
        elif r["segment_index"] is None and r["document_type"]:
            # Rule 2 is for WHOLE documents. A segment or parent copy carries
            # `document_segment` as its type, never the original's.
            by_type.setdefault(r["document_type"], []).append(key)
    if by_type:
        for t in await types_with_vectorize_off(conn, space_id, by_type):
            off.update(by_type[t])
    return off


async def segment_index_status(conn, space_id: str,
                               original_status: Optional[str],
                               document_type: Optional[str]) -> Optional[str]:
    """The status the worker stamps on a document's parent copy and segments.

    The original's explicit status if it has one, else `NO_INDEX` when its type
    has vectorization off, else None -- unstamped segments are embedded, as
    before, and follow any LATER change to the type's setting only when
    re-segmented.
    """
    if original_status in (INDEX_STATUS_NO_INDEX, INDEX_STATUS_VECTOR):
        return original_status
    if document_type and document_type in await types_with_vectorize_off(
            conn, space_id, [document_type]):
        return INDEX_STATUS_NO_INDEX
    return None
