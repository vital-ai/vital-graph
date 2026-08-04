"""Relationship-based discovery and deletion of KGDocument segmentation output.

Segmentation produces, for one original document and one segmentation method:

    original --Edge_hasKGDocumentSegment--> parent copy
    parent copy --Edge_hasKGDocumentSegment--> segment (xN)

This module finds that subtree by **traversing those edges** and deletes exactly
the objects it finds.

It replaces four separate implementations that identified the subtree by
string-matching the subject URI prefix (``STRSTARTS(STR(?s), "…_parent_…")``).
That was wrong in two ways: it deleted any subject whose URI merely *extended*
the prefix, and it scanned the whole graph to do it. See
``issues/021_uri_prefix_string_matching_in_deletes.md``.

**Invariant:** a URI is opaque to readers. Objects are identified by traversal
and by exact URI equality — never by inspecting URI structure. ``mint_uri``
below composes descriptive URIs for debuggability, but nothing may read that
structure back.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HALEY_NS = "http://vital.ai/ontology/haley-ai-kg#"
VITAL_CORE_NS = "http://vital.ai/ontology/vital-core#"

EDGE_HAS_SEGMENT = f"{HALEY_NS}Edge_hasKGDocumentSegment"
HAS_SEGMENT_TYPE_URI = f"{HALEY_NS}hasKGDocumentSegmentTypeURI"
HAS_SEGMENT_METHOD_URI = f"{HALEY_NS}hasKGDocumentSegmentMethodURI"
HAS_EDGE_SOURCE = f"{VITAL_CORE_NS}hasEdgeSource"
HAS_EDGE_DESTINATION = f"{VITAL_CORE_NS}hasEdgeDestination"
VITALTYPE = f"{VITAL_CORE_NS}vitaltype"

SEGMENTATION_PARENT_TYPE = "urn:segtype:segmentation_parent"

# Cap on URIs per DELETE, to keep the VALUES clause a sane size.
_DELETE_BATCH_SIZE = 200

# Characters that cannot appear inside a SPARQL IRIREF. A URI carrying one of
# these cannot be interpolated safely, so it is dropped rather than escaped —
# these URIs are read back out of the store, so a hit means the data is already
# malformed.
_ILLEGAL_IRI_CHARS = set('<>"{}|^`\\ \t\n\r')


def mint_uri(prefix: str) -> str:
    """Mint a unique URI carrying a human-readable prefix.

    The prefix exists solely so objects are recognizable when debugging — in a
    log line, a SPARQL result dump, or a database row. It carries **no
    semantics**: nothing parses it, matches on it, or infers type/method/parent
    /ordinal from it. Uniqueness comes entirely from the random tail, so the
    prefix is free to change without breaking anything.

    Mirrors the Vital URI convention (descriptive prefix + unique tail) that
    ``URIGenerator.generateURI(app, clazz, _transient, randomPart)`` implements
    in the Groovy/Java VitalSigns. The Python port of ``URIGenerator`` is a
    reduced, no-argument form that cannot carry a prefix, hence this local
    helper.
    """
    return f"{prefix}_{uuid.uuid4().hex}"


def _is_safe_uri(uri: str) -> bool:
    return bool(uri) and not (_ILLEGAL_IRI_CHARS & set(uri))


def sparql_bindings(result: Any) -> List[Dict[str, Any]]:
    """Extract binding rows from a backend SPARQL result.

    Backends differ: some return SPARQL JSON Results
    (``{'results': {'bindings': [...]}}``), others a plain list of row dicts.
    """
    if isinstance(result, dict):
        return result.get("results", {}).get("bindings", []) or []
    if isinstance(result, list):
        return result
    return []


def _value(row: Dict[str, Any], key: str) -> Optional[str]:
    """Read one variable from a binding row, tolerating both row encodings."""
    raw = row.get(key)
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        return None
    text = str(raw)
    return text or None


async def find_segmentation_uris(
    backend,
    space_id: str,
    graph_id: str,
    original_uri: str,
    method_uri: Optional[str] = None,
) -> List[str]:
    """Find every URI belonging to an original document's segmentation output.

    Traverses ``Edge_hasKGDocumentSegment`` from the original to its parent
    copies, and from each parent copy to its segments. Returns the parent
    copies, the segments, **and** the edges connecting them — edges are subjects
    in their own right and must be deleted too.

    Args:
        method_uri: when given, restrict to parent copies whose
            ``hasKGDocumentSegmentMethodURI`` equals this URI, so re-running one
            method leaves other methods' output alone. When ``None``, every
            method's output is returned (the document-delete cascade).

    Returns:
        Deduplicated URIs, order not significant. Empty if nothing is segmented.
    """
    if not _is_safe_uri(original_uri):
        logger.warning("Refusing to traverse from unsafe URI: %r", original_uri)
        return []

    method_clause = ""
    if method_uri:
        if not _is_safe_uri(method_uri):
            logger.warning("Refusing to scope by unsafe method URI: %r", method_uri)
            return []
        method_clause = (
            f"        ?parent <{HAS_SEGMENT_METHOD_URI}> <{method_uri}> .\n"
        )

    sparql = f"""
        SELECT DISTINCT ?parent_edge ?parent ?seg_edge ?seg WHERE {{
            GRAPH <{graph_id}> {{
                ?parent_edge <{HAS_EDGE_SOURCE}> <{original_uri}> .
                ?parent_edge <{VITALTYPE}> <{EDGE_HAS_SEGMENT}> .
                ?parent_edge <{HAS_EDGE_DESTINATION}> ?parent .
                ?parent <{HAS_SEGMENT_TYPE_URI}> <{SEGMENTATION_PARENT_TYPE}> .
{method_clause}                OPTIONAL {{
                    ?seg_edge <{HAS_EDGE_SOURCE}> ?parent .
                    ?seg_edge <{VITALTYPE}> <{EDGE_HAS_SEGMENT}> .
                    ?seg_edge <{HAS_EDGE_DESTINATION}> ?seg .
                }}
            }}
        }}
    """

    result = await backend.execute_sparql_query(space_id, sparql)

    uris: List[str] = []
    seen = set()
    for row in sparql_bindings(result):
        for var in ("parent_edge", "parent", "seg_edge", "seg"):
            uri = _value(row, var)
            if uri and uri not in seen:
                seen.add(uri)
                uris.append(uri)

    return uris


async def delete_segmentation(
    backend,
    space_id: str,
    graph_id: str,
    original_uri: str,
    method_uri: Optional[str] = None,
) -> int:
    """Delete an original document's segmentation output. Returns URIs deleted.

    Discovery is by traversal (:func:`find_segmentation_uris`); deletion targets
    exactly those URIs via an explicit ``VALUES`` list. Nothing is matched by URI
    shape, so an unrelated document whose URI happens to extend this one's is
    untouched.

    The URI list is the *only* thing constraining the delete, so a caller that
    passes an empty batch must issue no statement at all — an unconstrained
    ``?s ?p ?o`` would match the whole graph. The early return above and the
    batching below both preserve that.

    The original document itself is never deleted — only its segmentation
    output. Callers that want the original gone delete it separately.
    """
    uris = await find_segmentation_uris(
        backend, space_id, graph_id, original_uri, method_uri
    )
    if not uris:
        return 0

    safe_uris = [u for u in uris if _is_safe_uri(u)]
    if len(safe_uris) != len(uris):
        logger.warning(
            "Skipping %d segmentation URI(s) that cannot be safely interpolated "
            "for %s", len(uris) - len(safe_uris), original_uri,
        )
    if not safe_uris:
        return 0

    deleted = 0
    for start in range(0, len(safe_uris), _DELETE_BATCH_SIZE):
        batch = safe_uris[start:start + _DELETE_BATCH_SIZE]
        # One DELETE per batch, restricted to an explicit subject list.
        #
        # This shape used to be unusable: the SQL backend dropped a VALUES
        # clause from an update's WHERE, leaving `?s ?p ?o` to match every
        # triple in the graph. Until that was fixed this function issued one
        # bound-subject DELETE per URI instead. See
        # ``issues/023_values_clause_ignored_in_sparql_update.md`` — fixed, with
        # regression coverage in ``tests/integration/test_update_where_constraints.py``.
        values = " ".join(f"<{u}>" for u in batch)
        update = (
            f"DELETE {{ GRAPH <{graph_id}> {{ ?s ?p ?o . }} }} "
            f"WHERE {{ GRAPH <{graph_id}> {{ VALUES ?s {{ {values} }} ?s ?p ?o . }} }}"
        )
        await backend.execute_sparql_update(space_id, update)
        deleted += len(batch)

    logger.info(
        "Deleted %d segmentation object(s) for %s (method=%s)",
        deleted, original_uri, method_uri or "<all>",
    )
    return deleted
