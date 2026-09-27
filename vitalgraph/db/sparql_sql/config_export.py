"""Export a space's SEARCH CONFIG as a reviewable document — `issues/233` step 1.

`bulk_export` moves `datatype`, `term` and `rdf_quad`. It moves no config at all,
so a round trip through it silently drops every index mapping — and the config IS
the search behaviour: a space with the same data and different mappings answers
differently, with no error, just different hits.

EXPORT FIRST AND ALONE, which is `issues/233`'s stated order. It is independently
useful — it makes the current config of prod and dev diffable and reviewable —
and it cannot break anything, because it only reads.

THREE PROPERTIES THE DOCUMENT IS BUILT FOR
------------------------------------------
**Applicable to a differently-named space.** `source_space_id` is provenance
only and is never matched on import. Renaming a space and applying its old config
to the replacement is the entire use case (`issues/232` is the other half), so a
document that insists on its origin is useless.

**Diffable.** Every list is ordered by a stable natural key and no surrogate key
or timestamp appears, so two exports of the same config are byte-identical and a
diff shows only real differences. `mapping_id`, `index_id`, `property_id` and
`config_id` are local SERIALs — including them would both break diffs and
recreate the remapping problem the nesting exists to avoid.

**Safe to check into a repo.** `provider_config` is free-form JSONB and can hold
an API key. Secrets are REDACTED by default and the redaction is RECORDED, so a
future apply can fail loudly on a placeholder rather than writing one into a
provider config. Pass `include_secrets=True` for a document that can actually be
applied, and treat that document as a credential.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
No apply, no diff-against-a-space, and no physical objects. Those are steps 2-4
of `issues/233`, and apply in particular must go through the lifecycle managers
rather than writing rows — an imported `vector_index` row without its
`{space}_vec_{name}` table is a registry entry pointing at nothing.

It also does not decide the `document_segments` question. Every space has those
bootstrap rows by construction (`bootstrap_space_extras` →
`setup_document_segments_vectorization`), so exporting them is at best a no-op on
apply and at worst a conflict — but OMITTING them would make the document an
incomplete description of the space, and this step's job is to describe. The
decision belongs to apply; the document is faithful so that apply can make it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Bumped when the document's SHAPE changes, so an apply can refuse a document it
#: does not understand instead of half-reading it.
CONFIG_VERSION = 1

#: Substrings that make a `provider_config` key a secret. Matched on the key, not
#: the value: a value-shaped heuristic ("looks like a token") both misses opaque
#: keys and redacts innocent model names.
_SECRET_KEY_HINTS = ("key", "secret", "token", "password", "passwd",
                     "credential", "auth")

_REDACTED = "__REDACTED__"


def _is_secret(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in _SECRET_KEY_HINTS)


def _as_object(value: Any) -> Any:
    """JSONB as a Python object, whatever the driver handed back.

    asyncpg returns JSONB as a string by default; psycopg parses it. Accepting
    both keeps this usable from either, and the failure mode of getting it wrong
    is silent — see the call site.
    """
    if isinstance(value, str):
        import json
        try:
            return json.loads(value)
        except ValueError:
            # Not JSON after all. Return it as-is rather than dropping it: an
            # unparseable provider_config is a thing a reader needs to SEE.
            return value
    return value


def _scrub(value: Any, path: str, found: List[str]) -> Any:
    """Recursively redact secret-looking keys, recording each path redacted."""
    if isinstance(value, dict):
        out = {}
        for k in sorted(value):
            p = f"{path}.{k}" if path else k
            if _is_secret(k):
                found.append(p)
                out[k] = _REDACTED
            else:
                out[k] = _scrub(value[k], p, found)
        return out
    if isinstance(value, list):
        return [_scrub(v, f"{path}[]", found) for v in value]
    return value


async def _rows(conn, space_id: str, suffix: str, columns: str,
                order: str, absent: List[str]) -> List[Dict]:
    """Read one config table, or record it absent and return nothing.

    A space created by an older schema version can legitimately lack a table.
    Failing the whole export for that would make the tool unusable exactly where
    it is most needed — on the oldest space — so the absence is reported in the
    document instead.
    """
    table = f"{space_id}_{suffix}"
    try:
        rows = await conn.fetch(
            f"SELECT {columns} FROM {table} ORDER BY {order}")
    except Exception as e:
        logger.debug("config_export: %s unreadable (%s)", table, e)
        absent.append(suffix)
        return []
    return [dict(r) for r in rows]


async def export_space_config(conn, space_id: str, *,
                              include_secrets: bool = False) -> Dict[str, Any]:
    """Return *space_id*'s search config as a plain, JSON-serialisable dict.

    Read-only. Never raises for a missing config table — see `_rows`.
    """
    absent: List[str] = []
    redacted: List[str] = []

    vector_indexes = await _rows(
        conn, space_id, "vector_index",
        "index_name, dimensions, distance_metric, provider, model_name, "
        "provider_config, description",
        "index_name", absent)
    for vi in vector_indexes:
        # PARSE IT FIRST. asyncpg hands JSONB back as a raw STRING unless a codec
        # is registered, and a string is not something `_scrub` can walk — so the
        # first version of this redacted nothing at all and passed the secret
        # straight into the document, with the only visible symptom being that
        # `provider_config` was a string. Parsing also normalises whatever
        # whitespace and key order PostgreSQL happened to store, which is what
        # makes two exports of the same config byte-identical.
        cfg = _as_object(vi.get("provider_config"))
        if cfg is not None and not include_secrets:
            cfg = _scrub(cfg, f"vector_indexes[{vi['index_name']}]"
                              f".provider_config", redacted)
        vi["provider_config"] = cfg

    fts_indexes = await _rows(
        conn, space_id, "fts_index",
        "index_name, languages, rank_normalization", "index_name", absent)

    # Mappings carry their children by NESTING, so `mapping_id` never reaches the
    # document. Read the children once and group in Python rather than issuing a
    # query per mapping.
    mappings = await _rows(
        conn, space_id, "search_mapping",
        "mapping_id, mapping_type, type_uri, index_name, enabled, "
        "source_type, separator, include_pred_name",
        "mapping_type, type_uri, index_name", absent)
    props = await _rows(
        conn, space_id, "search_mapping_property",
        "mapping_id, property_uri, property_role, ordinal",
        "mapping_id, ordinal, property_uri", absent)
    junction = await _rows(
        conn, space_id, "search_mapping_index",
        "mapping_id, index_type, index_name",
        "mapping_id, index_type, index_name", absent)
    _nest(mappings, props, junction)

    fuzzy = await _rows(
        conn, space_id, "fuzzy_mapping",
        "mapping_id, mapping_type, type_uri, index_name, enabled, "
        "shingle_k, num_perm, lsh_threshold, phonetic_bonus",
        "mapping_type, type_uri, index_name", absent)
    fuzzy_props = await _rows(
        conn, space_id, "fuzzy_mapping_property",
        "mapping_id, property_uri, property_role, ordinal",
        "mapping_id, ordinal, property_uri", absent)
    _nest(fuzzy, fuzzy_props, None)

    # ONE ROW, not a list: `geo_config` is per space. Kept as a nullable object
    # rather than an empty list so "no geo config" and "geo config disabled" are
    # different things in the document.
    geo = await _rows(
        conn, space_id, "geo_config",
        "enabled, auto_sync, geo_datatype_uris, lat_predicates, lon_predicates",
        "config_id", absent)

    segmentation = await _rows(
        conn, space_id, "document_segmentation_config",
        "document_type_uri, segment_method_uri, max_segment_tokens, "
        "min_segment_tokens, overlap_tokens, enabled, auto_vectorize",
        "document_type_uri, segment_method_uri", absent)

    doc: Dict[str, Any] = {
        "version": CONFIG_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        # PROVENANCE ONLY. An apply must not require this to match its target.
        "source_space_id": space_id,
        "vector_indexes": vector_indexes,
        "fts_indexes": fts_indexes,
        "mappings": mappings,
        "fuzzy_mappings": fuzzy,
        "geo_config": geo[0] if geo else None,
        "segmentation_config": segmentation,
    }
    # Only when non-empty, so the common document stays clean and a reader who
    # sees either key knows it means something.
    if absent:
        doc["absent_tables"] = sorted(set(absent))
    if redacted:
        doc["redacted"] = sorted(redacted)
    return doc


def _nest(mappings: List[Dict], properties: List[Dict],
          junction: Optional[List[Dict]]) -> None:
    """Attach children to their mapping and drop every `mapping_id`.

    Mutates in place. The id is the join key and nothing else — it is a local
    SERIAL, so carrying it into the document would make two spaces with identical
    config produce different documents, and would hand an apply the remapping
    problem this nesting exists to remove.
    """
    by_id: Dict[Any, Dict] = {m["mapping_id"]: m for m in mappings}
    for m in mappings:
        m["properties"] = []
        if junction is not None:
            m["indexes"] = []
    for p in properties:
        owner = by_id.get(p.pop("mapping_id"))
        if owner is not None:
            owner["properties"].append(p)
    for j in (junction or []):
        owner = by_id.get(j.pop("mapping_id"))
        if owner is not None:
            owner["indexes"].append(j)
    for m in mappings:
        m.pop("mapping_id", None)


def config_to_json(doc: Dict[str, Any]) -> str:
    """Stable JSON for the document — sorted keys, so diffs are minimal."""
    import json
    return json.dumps(doc, indent=2, sort_keys=True, default=str)
