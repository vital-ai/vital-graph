"""
Search text builder — constructs composite text from RDF properties.

Given a subject_uuid and its literal properties from the rdf_quad + term tables,
builds a single ``search_text`` string suitable for:
  1. Vectorization (embedding provider)
  2. Full-text search (auto-generated tsvector column)
  3. Debugging / re-vectorization (stored as-is)

The builder is driven by the normalized ``search_mapping`` +
``search_mapping_property`` tables.  Source modes:

- **type_description**: Use ONLY the KGType description (cross-space lookup).
- **properties**: Concatenate specific predicate values (listed in child table).
- **properties_type**: Properties + type description appended.
- **default**: Use ``hasKGraphDescription`` + optional type description.
- **slots**: Concatenate slot type values (listed in child table).

If no mapping exists, all literal-valued predicates are included (fallback).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Canonical default property for KG object vectorization
HAS_KGRAPH_DESCRIPTION = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"


@dataclass
class MappingRule:
    """Resolved mapping rule from search_mapping + search_mapping_property tables."""
    mapping_id: Optional[int] = None
    enabled: bool = True                    # on/off switch at class or type level
    source_type: str = "default"            # 'type_description', 'properties', 'properties_type', 'default'
    separator: str = ". "
    include_pred_name: bool = False
    include_uris: List[str] = field(default_factory=list)   # ordered by ordinal
    exclude_uris: Set[str] = field(default_factory=set)


def build_search_text(
    literal_properties: List[Tuple[str, str]],
    rule: Optional[MappingRule] = None,
    type_description: Optional[str] = None,
) -> str:
    """Build composite search text from a subject's literal properties.

    Args:
        literal_properties: List of (predicate_uri, object_text) pairs.
            Only literal-valued properties should be passed.
        rule: Optional resolved mapping rule. If None, includes all literals.
        type_description: Optional type description text (from KG Type lookup).

    Returns:
        Composite text string ready for vectorization and FTS indexing.
    """
    if rule is None:
        # Fallback: include all literal properties
        return _build_all_properties(literal_properties, ". ", False)

    separator = rule.separator or ". "

    if rule.source_type == "type_description":
        # Type description ONLY — no subject properties
        if type_description and type_description.strip():
            return type_description.strip()
        return ""
    elif rule.source_type == "properties_type":
        # Properties + type description appended
        return _build_from_mapping(literal_properties, rule, separator, type_description)
    elif rule.source_type == "default":
        return _build_default(literal_properties, separator, type_description)
    elif rule.source_type in ("properties", "slots", "concat_properties"):
        # Properties only — no type description
        return _build_from_mapping(literal_properties, rule, separator, None)
    else:
        # Unknown source type — fall back to all properties
        return _build_all_properties(literal_properties, separator, rule.include_pred_name)


def _build_default(
    literal_properties: List[Tuple[str, str]],
    separator: str,
    type_description: Optional[str],
) -> str:
    """Default mode: use hasKGraphDescription + optional type description."""
    parts: List[str] = []

    # Find hasKGraphDescription value
    for pred_uri, obj_text in literal_properties:
        if pred_uri == HAS_KGRAPH_DESCRIPTION:
            text = obj_text.strip()
            if text:
                parts.append(text)
            break

    if type_description and type_description.strip():
        parts.append(type_description.strip())

    return separator.join(parts)


def _build_from_mapping(
    literal_properties: List[Tuple[str, str]],
    rule: MappingRule,
    separator: str,
    type_description: Optional[str],
) -> str:
    """Properties/slots mode: concatenate values from child table URIs."""
    include_set: Optional[Set[str]] = None
    if rule.include_uris:
        include_set = set(rule.include_uris)

    # Build a lookup: predicate_uri → list of values
    prop_values: Dict[str, List[str]] = {}
    for pred_uri, obj_text in literal_properties:
        if include_set is not None and pred_uri not in include_set:
            continue
        if pred_uri in rule.exclude_uris:
            continue
        text = obj_text.strip()
        if text:
            prop_values.setdefault(pred_uri, []).append(text)

    # Emit in ordinal order (include_uris is already sorted by ordinal)
    parts: List[str] = []
    if rule.include_uris:
        for uri in rule.include_uris:
            for val in prop_values.get(uri, []):
                if rule.include_pred_name:
                    parts.append(f"{_predicate_local_name(uri)} {val}")
                else:
                    parts.append(val)
    else:
        # No explicit includes — use all (minus excludes), sorted for determinism
        for pred_uri in sorted(prop_values.keys()):
            for val in prop_values[pred_uri]:
                if rule.include_pred_name:
                    parts.append(f"{_predicate_local_name(pred_uri)} {val}")
                else:
                    parts.append(val)

    if type_description and type_description.strip():
        parts.append(type_description.strip())

    return separator.join(parts)


def _build_all_properties(
    literal_properties: List[Tuple[str, str]],
    separator: str,
    include_pred_name: bool,
) -> str:
    """Fallback: include all literal properties, sorted by predicate URI."""
    props = sorted(literal_properties, key=lambda x: x[0])
    parts: List[str] = []
    for pred_uri, obj_text in props:
        text = obj_text.strip()
        if not text:
            continue
        if include_pred_name:
            parts.append(f"{_predicate_local_name(pred_uri)} {text}")
        else:
            parts.append(text)
    return separator.join(parts)


def _predicate_local_name(uri: str) -> str:
    """Extract the local name from a predicate URI and make it readable.

    'http://vital.ai/ontology/haley-ai-kg#hasName' → 'has Name'
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' → 'type'
    """
    # Take fragment or last path segment
    if "#" in uri:
        local = uri.rsplit("#", 1)[1]
    elif "/" in uri:
        local = uri.rsplit("/", 1)[1]
    else:
        local = uri
    return _separate_camel_case(local)


def _separate_camel_case(name: str) -> str:
    """Split camelCase/PascalCase into space-separated words.

    'hasName' → 'has Name'
    'primaryDescription' → 'primary Description'
    """
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


# -----------------------------------------------------------------------
# SQL helpers for fetching literal properties from the quad/term tables
# -----------------------------------------------------------------------

LITERAL_PROPERTIES_SQL = """
SELECT t_pred.term_text AS predicate_uri,
       t_obj.term_text  AS object_text
FROM {rdf_quad} q
JOIN {term} t_pred ON q.predicate_uuid = t_pred.term_uuid
JOIN {term} t_obj  ON q.object_uuid    = t_obj.term_uuid
WHERE q.subject_uuid = $1
  AND q.context_uuid = $2
  AND t_obj.term_type = 'L'
ORDER BY t_pred.term_text
"""

LITERAL_PROPERTIES_BATCH_SQL = """
SELECT q.subject_uuid,
       t_pred.term_text AS predicate_uri,
       t_obj.term_text  AS object_text
FROM {rdf_quad} q
JOIN {term} t_pred ON q.predicate_uuid = t_pred.term_uuid
JOIN {term} t_obj  ON q.object_uuid    = t_obj.term_uuid
WHERE q.subject_uuid = ANY($1)
  AND q.context_uuid = $2
  AND t_obj.term_type = 'L'
ORDER BY q.subject_uuid, t_pred.term_text
"""


# -----------------------------------------------------------------------
# Mapping resolution from normalized tables
# -----------------------------------------------------------------------

RESOLVE_SEARCH_MAPPING_SQL = """
SELECT m.mapping_id, m.enabled, m.source_type, m.separator, m.include_pred_name
FROM {search_mapping} m
WHERE m.index_name = $1
  AND (
    (m.mapping_type = $2 AND m.type_uri = $3)
    OR (m.mapping_type = $2 AND m.type_uri IS NULL)
  )
ORDER BY m.type_uri IS NULL, m.mapping_id
LIMIT 1
"""

SEARCH_MAPPING_PROPERTIES_SQL = """
SELECT property_uri, property_role, ordinal
FROM {search_mapping_property}
WHERE mapping_id = $1
ORDER BY ordinal, property_id
"""


async def resolve_search_mapping(
    conn,
    space_id: str,
    index_name: str,
    mapping_type: str,
    type_uri: Optional[str] = None,
) -> Optional[MappingRule]:
    """Resolve the mapping rule from the search_mapping tables.

    Used by both FTS and vector populators.

    Precedence:
    1. Specific type_uri match
    2. Class-level match (type_uri IS NULL)
    3. None (caller should use default behavior)
    """
    sql = RESOLVE_SEARCH_MAPPING_SQL.format(
        search_mapping=f"{space_id}_search_mapping",
    )
    row = await conn.fetchrow(sql, index_name, mapping_type, type_uri)
    if row is None:
        return None

    rule = MappingRule(
        mapping_id=row["mapping_id"],
        enabled=row["enabled"] if row["enabled"] is not None else True,
        source_type=row["source_type"] or "default",
        separator=row["separator"] or ". ",
        include_pred_name=row["include_pred_name"] or False,
    )

    # Fetch child property rows
    prop_sql = SEARCH_MAPPING_PROPERTIES_SQL.format(
        search_mapping_property=f"{space_id}_search_mapping_property",
    )
    prop_rows = await conn.fetch(prop_sql, row["mapping_id"])
    for pr in prop_rows:
        if pr["property_role"] == "exclude":
            rule.exclude_uris.add(pr["property_uri"])
        else:
            rule.include_uris.append(pr["property_uri"])

    return rule


async def fetch_literal_properties(
    conn, space_id: str, subject_uuid, context_uuid,
) -> List[Tuple[str, str]]:
    """Fetch all literal-valued properties for a single subject."""
    sql = LITERAL_PROPERTIES_SQL.format(
        rdf_quad=f"{space_id}_rdf_quad",
        term=f"{space_id}_term",
    )
    rows = await conn.fetch(sql, subject_uuid, context_uuid)
    return [(r["predicate_uri"], r["object_text"]) for r in rows]


async def fetch_literal_properties_batch(
    conn, space_id: str, subject_uuids: List, context_uuid,
) -> Dict[Any, List[Tuple[str, str]]]:
    """Fetch literal properties for a batch of subjects.

    Returns a dict mapping subject_uuid → [(predicate_uri, object_text), ...].
    """
    sql = LITERAL_PROPERTIES_BATCH_SQL.format(
        rdf_quad=f"{space_id}_rdf_quad",
        term=f"{space_id}_term",
    )
    rows = await conn.fetch(sql, subject_uuids, context_uuid)

    result: Dict[Any, List[Tuple[str, str]]] = {}
    for r in rows:
        subj = r["subject_uuid"]
        result.setdefault(subj, []).append((r["predicate_uri"], r["object_text"]))
    return result
