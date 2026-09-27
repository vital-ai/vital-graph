"""Apply a config document to a space — `issues/233` steps 3 (merge) and 4 (replace).

Steps 1 and 2 made a config readable and checkable. This makes it movable: given
a document and a space, bring the space up to what the document describes.

THROUGH THE LIFECYCLE MANAGERS, NEVER BY WRITING ROWS. This is the issue's
central instruction and the reason is concrete: config implies PHYSICAL objects.
An imported `{s}_vector_index` row without its `{s}_vec_{name}` table is a
registry entry pointing at nothing, and an FTS index needs its table, three
indexes, a trigger function and a trigger. Writing rows directly is the obvious
implementation and produces a config that looks right in every listing and does
not work. So: `ensure_index`, `ensure_fts_index`, `SearchMappingManager`,
`FuzzyMappingManager`, `GeoConfigManager`, `SegmentationConfigManager`.

MERGE IS THE DEFAULT; REPLACE IS OPT-IN. The target is NEVER empty — creating a
space already runs `bootstrap_space_extras`, which registers a `document_segments`
vector index, its search mapping and its FTS index. So a merge reconciles: it
creates what is missing, updates what differs, and removes nothing.

`replace=True` additionally removes config the document does not mention, and
DROPS THE PHYSICAL TABLES for removed indexes — decided 2026-09-26, and the
reason it needed deciding is that a `_vec_` table holds computed EMBEDDINGS which
re-applying the document cannot bring back. Every removal is therefore reported
with the exact row count it destroyed, and a `dry_run` reports the counts it WOULD
destroy, which is what makes the dry run a safety tool rather than a formality.
See `_remove_absent`.

THE ORDERING TRAP THAT MAKES THIS MORE THAN A LOOP
--------------------------------------------------
`SearchMappingManager.add_property` AUTO-UPGRADES `source_type` from `default` to
`properties` as a side effect. So the obvious sequence — create the mapping with
the document's `source_type`, then add its properties — silently produces a
mapping whose `source_type` is not what the document said. `issues/233` records
this being hit for real while cloning config between spaces, and having to be
corrected with an explicit `PUT` afterwards.

So every mapping's scalar fields are RE-ASSERTED after its properties are added.
That is not belt-and-braces; it is the only order that reproduces the document.
`config_diff` is what proves it worked, which is why step 2 came first.

IDEMPOTENT. Applying twice changes nothing the second time, and a `diff` after an
apply reports no difference — both asserted by test. Anything else makes this
unusable in a workflow where you apply, look, and apply again.

A REDACTED DOCUMENT IS REFUSED. `provider_config` may hold an API key, so the
default export redacts it. Applying such a document would write `__REDACTED__`
into a provider config, and the failure mode of that is an index that exists,
looks configured, and produces wrong embeddings — `issues/219`'s shape exactly.
Refusing names the paths and tells the caller to re-export with
`include_secrets=True`; that document is a credential, which is the honest cost.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .config_export import CONFIG_VERSION, _REDACTED

logger = logging.getLogger(__name__)

#: Mapping scalar fields `update_mapping` accepts, and therefore the ones that
#: can be re-asserted after `add_property`'s side effect.
_MAPPING_SCALARS = ("enabled", "source_type", "separator", "include_pred_name")


def _find_redactions(node: Any, path: str = "") -> List[str]:
    if isinstance(node, dict):
        out = []
        for k, v in node.items():
            out.extend(_find_redactions(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(node, list):
        out = []
        for i, v in enumerate(node):
            out.extend(_find_redactions(v, f"{path}[{i}]"))
        return out
    return [path] if node == _REDACTED else []


def _identity(item: Dict, fields: Tuple[str, ...]) -> Tuple:
    return tuple(item.get(f) for f in fields)


class ConfigApplyRefused(Exception):
    """The document cannot be applied, and no change was made."""


async def apply_space_config(conn, space_id: str, document: Dict[str, Any], *,
                             dry_run: bool = False,
                             replace: bool = False) -> Dict[str, Any]:
    """Bring *space_id* up to what *document* describes.

    Merge by default: creates what is missing, updates what differs, removes
    nothing. With ``replace=True`` it also REMOVES config the document does not
    mention, including DROPPING the physical `_vec_` and `_fts_` tables — see
    `_remove_absent` for what that destroys and why the report says so.

    Returns a report of what was created, updated and removed. With
    ``dry_run=True`` nothing is written and the report says what WOULD happen —
    a weaker statement than `config_diff`'s, because it is the plan rather than
    the difference; use the diff to decide, this to see the steps. For
    ``replace`` the dry run is the safety tool: it reports the ROW COUNTS a real
    run would destroy.

    Raises `ConfigApplyRefused` before touching anything if the document is a
    version this code does not understand, or carries redacted secrets.
    """
    if document.get("version") != CONFIG_VERSION:
        raise ConfigApplyRefused(
            f"document version {document.get('version')!r} != "
            f"{CONFIG_VERSION!r}; refusing rather than guessing which fields "
            f"still mean what they did")

    redactions = _find_redactions(document)
    if redactions:
        raise ConfigApplyRefused(
            "document carries redacted secrets and cannot be applied: "
            + ", ".join(sorted(redactions))
            + ". Re-export with include_secrets=True — and treat that document "
              "as a credential.")

    report: Dict[str, Any] = {
        "space_id": space_id,
        "source_space_id": document.get("source_space_id"),
        "dry_run": dry_run,
        "replace": replace,
        "created": [],
        "updated": [],
        "removed": [],
        "failed": [],
    }

    # REMOVALS FIRST, and deliberately. `teardown_index` deletes every
    # `search_mapping` row naming the index it drops, so running it AFTER the
    # mapping reconciliation would delete mappings this apply had just created.
    if replace:
        await _remove_absent(conn, space_id, document, report, dry_run)

    await _apply_vector_indexes(conn, space_id, document, report, dry_run)
    await _apply_fts_indexes(conn, space_id, document, report, dry_run)
    await _apply_search_mappings(conn, space_id, document, report, dry_run)
    await _apply_fuzzy_mappings(conn, space_id, document, report, dry_run)
    await _apply_geo_config(conn, space_id, document, report, dry_run)
    await _apply_segmentation(conn, space_id, document, report, dry_run)

    report["changed"] = bool(report["created"] or report["updated"]
                             or report["removed"])
    return report


async def _apply_vector_indexes(conn, space_id, document, report, dry_run):
    from vitalgraph.vectorization.vector_index_lifecycle import ensure_index

    existing = {r["index_name"] for r in await conn.fetch(
        f"SELECT index_name FROM {space_id}_vector_index")}
    for vi in document.get("vector_indexes") or []:
        name = vi.get("index_name")
        if name in existing:
            continue                      # ensure_index is a no-op; say nothing
        if dry_run:
            report["created"].append(f"vector_index/{name}")
            continue
        # THROUGH THE LIFECYCLE, so the `{space}_vec_{name}` table and its
        # indexes come with the registry row. It also validates provider and
        # dimensions against the registry, which a row write would not — an
        # index whose model cannot produce that width fails much later, as an
        # insert error during reindex.
        ok = await ensure_index(conn, space_id, name, {
            "dimensions": vi.get("dimensions"),
            "distance_metric": vi.get("distance_metric"),
            "provider": vi.get("provider"),
            "model_name": vi.get("model_name"),
            "provider_config": vi.get("provider_config"),
            "description": vi.get("description"),
        })
        (report["created"] if ok else report["failed"]).append(
            f"vector_index/{name}")


async def _apply_fts_indexes(conn, space_id, document, report, dry_run):
    from vitalgraph.vectorization.fts_index_lifecycle import (
        ensure_fts_index, get_fts_index, update_fts_languages,
        update_rank_normalization)

    for fi in document.get("fts_indexes") or []:
        name = fi.get("index_name")
        languages = fi.get("languages") or ["english"]
        rank = fi.get("rank_normalization") or 0
        current = await get_fts_index(conn, space_id, name)
        if current is None:
            if dry_run:
                report["created"].append(f"fts_index/{name}")
                continue
            ok = await ensure_fts_index(conn, space_id, name, languages, rank)
            (report["created"] if ok else report["failed"]).append(
                f"fts_index/{name}")
            continue

        # Present, so `ensure_fts_index` is a no-op and would leave a DIFFERENT
        # configuration in place — apply would report success while the index
        # kept scoring the old way. The two fields need different treatment and
        # are deliberately not combined:
        #
        #   languages          recreates the trigger function and, by default,
        #                      recomputes every tsvector in the data table. Real
        #                      work, so only when it actually differs.
        #   rank_normalization read at QUERY time by `ts_rank_cd`, so a registry
        #                      update is the whole change. There was NO manager
        #                      path for this until `issues/233` step 3 added one.
        changed = False
        if list(current.get("languages") or []) != list(languages):
            if not dry_run:
                await update_fts_languages(conn, space_id, name, languages)
            changed = True
        if (current.get("rank_normalization") or 0) != rank:
            if not dry_run:
                await update_rank_normalization(conn, space_id, name, rank)
            changed = True
        if changed:
            report["updated"].append(f"fts_index/{name}")


async def _apply_search_mappings(conn, space_id, document, report, dry_run):
    from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

    mgr = SearchMappingManager(conn, space_id)
    identity = ("mapping_type", "type_uri", "index_name")
    existing = {}
    for dto in await mgr.list_mappings():
        d = dto.to_dict()
        existing[_identity(d, identity)] = d

    for want in document.get("mappings") or []:
        key = _identity(want, identity)
        label = "/".join(str(k) for k in key)
        current = existing.get(key)

        if current is None:
            if dry_run:
                report["created"].append(f"mapping/{label}")
                continue
            mapping_id = await mgr.create_mapping(
                index_name=want.get("index_name"),
                mapping_type=want.get("mapping_type"),
                type_uri=want.get("type_uri"),
                enabled=want.get("enabled", True),
                source_type=want.get("source_type", "default"),
                separator=want.get("separator", ". "),
                include_pred_name=want.get("include_pred_name", False),
            )
            report["created"].append(f"mapping/{label}")
        else:
            mapping_id = current.get("mapping_id")

        if dry_run:
            continue

        await _reconcile_properties(mgr, mapping_id, want, label, report)
        await _reconcile_indexes(mgr, mapping_id, want, label, report)

        # RE-ASSERT THE SCALARS, ALWAYS AND LAST. `add_property` silently
        # upgrades `source_type` to 'properties', so a mapping the document says
        # is 'default' comes out 'properties' unless this runs after the
        # properties. See the module docstring.
        desired = {f: want.get(f) for f in _MAPPING_SCALARS
                   if want.get(f) is not None}
        if desired:
            await mgr.update_mapping(mapping_id, **desired)
            if current is not None and any(
                    current.get(f) != want.get(f) for f in desired):
                report["updated"].append(f"mapping/{label}")


async def _reconcile_properties(mgr, mapping_id, want, label, report) -> None:
    """Add the document's properties that are missing. Never removes."""
    have = {(p.property_uri, p.property_role, p.ordinal)
            for p in await mgr.list_properties(mapping_id)}
    for p in want.get("properties") or []:
        triple = (p.get("property_uri"), p.get("property_role", "include"),
                  p.get("ordinal", 0))
        if triple in have:
            continue
        await mgr.add_property(mapping_id, triple[0],
                               property_role=triple[1], ordinal=triple[2])
        report["updated"].append(f"mapping/{label}/property/{triple[0]}")


async def _reconcile_indexes(mgr, mapping_id, want, label, report) -> None:
    have = {(i.index_type, i.index_name)
            for i in await mgr.list_indexes(mapping_id)}
    for j in want.get("indexes") or []:
        pair = (j.get("index_type"), j.get("index_name"))
        if pair in have:
            continue
        await mgr.add_index(mapping_id, pair[0], pair[1])
        report["updated"].append(f"mapping/{label}/index/{pair[1]}")


async def _apply_fuzzy_mappings(conn, space_id, document, report, dry_run):
    from vitalgraph.vectorization.fuzzy_mapping_manager import FuzzyMappingManager

    wanted = document.get("fuzzy_mappings") or []
    if not wanted:
        return
    mgr = FuzzyMappingManager(conn, space_id)
    identity = ("mapping_type", "type_uri", "index_name")
    existing = {}
    for dto in await mgr.list_mappings():
        d = dto.to_dict() if hasattr(dto, "to_dict") else dict(dto)
        existing[_identity(d, identity)] = d

    for want in wanted:
        key = _identity(want, identity)
        label = "/".join(str(k) for k in key)
        if key in existing:
            continue                      # merge does not rewrite tuning
        if dry_run:
            report["created"].append(f"fuzzy_mapping/{label}")
            continue
        mapping_id = await mgr.create_mapping(
            index_name=want.get("index_name"),
            mapping_type=want.get("mapping_type"),
            type_uri=want.get("type_uri"),
            **{k: want[k] for k in ("enabled", "shingle_k", "num_perm",
                                    "lsh_threshold", "phonetic_bonus")
               if want.get(k) is not None})
        report["created"].append(f"fuzzy_mapping/{label}")
        for p in want.get("properties") or []:
            await mgr.add_property(mapping_id, p.get("property_uri"),
                                   property_role=p.get("property_role", "include"),
                                   ordinal=p.get("ordinal", 0))


async def _apply_geo_config(conn, space_id, document, report, dry_run):
    from vitalgraph.vectorization.geo_config_manager import GeoConfigManager

    want = document.get("geo_config")
    if want is None:
        return                            # merge: silence is not "delete it"
    mgr = GeoConfigManager(conn, space_id)
    current = await mgr.get_config()
    fields = {k: v for k, v in want.items() if v is not None}
    if current is None:
        if dry_run:
            report["created"].append("geo_config")
            return
        await mgr.ensure_config()
        await mgr.update_config(**fields)
        report["created"].append("geo_config")
        return
    have = current.to_dict() if hasattr(current, "to_dict") else dict(current)
    if any(have.get(k) != v for k, v in fields.items()):
        if not dry_run:
            await mgr.update_config(**fields)
        report["updated"].append("geo_config")


async def _apply_segmentation(conn, space_id, document, report, dry_run):
    from vitalgraph.document.segmentation_config_manager import (
        SegmentationConfigManager)

    wanted = document.get("segmentation_config") or []
    if not wanted:
        return
    mgr = SegmentationConfigManager(conn, space_id)
    existing = set()
    for dto in await mgr.list_configs():
        d = dto.to_dict() if hasattr(dto, "to_dict") else dict(dto)
        existing.add((d.get("document_type_uri"), d.get("segment_method_uri")))

    for want in wanted:
        key = (want.get("document_type_uri"), want.get("segment_method_uri"))
        label = "/".join(str(k) for k in key)
        if key in existing:
            continue
        if dry_run:
            report["created"].append(f"segmentation_config/{label}")
            continue
        await mgr.create_config(
            document_type_uri=key[0], segment_method_uri=key[1],
            **{k: want[k] for k in ("max_segment_tokens", "min_segment_tokens",
                                    "overlap_tokens", "enabled",
                                    "auto_vectorize")
               if want.get(k) is not None})
        report["created"].append(f"segmentation_config/{label}")


async def _row_count(conn, table: str) -> Optional[int]:
    """Rows in *table*, or None if it does not exist.

    Exact, not an estimate: this number is the only warning an operator gets
    before embeddings are destroyed, and `reltuples` can be stale or -1 on a
    table that has never been analyzed — which a freshly built index is.
    """
    try:
        return await conn.fetchval(f"SELECT count(*) FROM {table}")
    except Exception:
        return None


async def _remove_absent(conn, space_id, document, report, dry_run):
    """REPLACE semantics: remove config the document does not mention.

    DESTRUCTIVE, AND THE DESTRUCTION IS NOT RECOVERABLE BY RE-APPLYING. Dropping
    a vector index drops its `{space}_vec_{name}` table, and that table holds
    computed EMBEDDINGS — money and wall-clock, not just rows. Re-applying the
    document recreates the index empty; it cannot bring the vectors back. The
    same applies to an FTS index's tsvectors, which are cheaper but still a
    rebuild over the whole corpus.

    So every removal is reported with the ROW COUNT it destroyed — or, under
    `dry_run`, the row count it WOULD destroy. That makes the dry run the actual
    safety tool rather than a formality, and it is why the counts are exact
    rather than estimated.

    Through the lifecycle teardowns (`teardown_index`, `teardown_fts_index`), so
    the trigger function, the trigger and the three FTS indexes go with the
    table. A `DELETE` from the registry would leave all of them behind.

    NO SPECIAL CASE FOR `document_segments`, deliberately. Every space gets it
    from `bootstrap_space_extras` AT CREATION ONLY, so dropping it is permanent
    for that space — but replace means replace, and a document that omits it is
    a document someone edited. The row count and the WARNING log are the guard;
    refusing would be guessing at intent.
    """
    from vitalgraph.vectorization.vector_index_lifecycle import teardown_index
    from vitalgraph.vectorization.fts_index_lifecycle import (
        list_fts_indexes, teardown_fts_index)
    from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager

    wanted_vec = {v.get("index_name") for v in document.get("vector_indexes") or []}
    wanted_fts = {f.get("index_name") for f in document.get("fts_indexes") or []}

    for row in await conn.fetch(
            f"SELECT index_name FROM {space_id}_vector_index ORDER BY index_name"):
        name = row["index_name"]
        if name in wanted_vec:
            continue
        rows = await _row_count(conn, f"{space_id}_vec_{name}")
        entry = {"what": f"vector_index/{name}",
                 "table": f"{space_id}_vec_{name}", "rows_destroyed": rows}
        if dry_run:
            entry["rows_destroyed"] = rows          # would destroy
            report["removed"].append(entry)
            continue
        logger.warning("REPLACE: dropping vector index %s/%s and its %s rows of "
                       "embeddings — not recoverable by re-applying",
                       space_id, name, rows)
        ok = await teardown_index(conn, space_id, name)
        (report["removed"] if ok else report["failed"]).append(entry)

    for idx in await list_fts_indexes(conn, space_id):
        name = idx.get("index_name")
        if name in wanted_fts:
            continue
        rows = await _row_count(conn, f"{space_id}_fts_{name}")
        entry = {"what": f"fts_index/{name}",
                 "table": f"{space_id}_fts_{name}", "rows_destroyed": rows}
        if dry_run:
            report["removed"].append(entry)
            continue
        logger.warning("REPLACE: dropping FTS index %s/%s and its %s rows",
                       space_id, name, rows)
        ok = await teardown_fts_index(conn, space_id, name)
        (report["removed"] if ok else report["failed"]).append(entry)

    # Mappings LAST of the removals, and re-read: `teardown_index` above already
    # deleted every mapping naming a dropped index, so a list taken before it ran
    # would name rows that no longer exist.
    mgr = SearchMappingManager(conn, space_id)
    identity = ("mapping_type", "type_uri", "index_name")
    wanted = {_identity(m, identity) for m in document.get("mappings") or []}
    for dto in await mgr.list_mappings():
        d = dto.to_dict()
        key = _identity(d, identity)
        if key in wanted:
            continue
        label = "/".join(str(k) for k in key)
        entry = {"what": f"mapping/{label}", "table": None, "rows_destroyed": None}
        if dry_run:
            report["removed"].append(entry)
            continue
        logger.warning("REPLACE: deleting search mapping %s/%s", space_id, label)
        ok = await mgr.delete_mapping(d.get("mapping_id"))
        (report["removed"] if ok else report["failed"]).append(entry)

    await _remove_absent_fuzzy(conn, space_id, document, report, dry_run)
    await _remove_absent_segmentation(conn, space_id, document, report, dry_run)
    await _remove_absent_geo(conn, space_id, document, report, dry_run)


async def _remove_absent_fuzzy(conn, space_id, document, report, dry_run):
    from vitalgraph.vectorization.fuzzy_mapping_manager import FuzzyMappingManager

    mgr = FuzzyMappingManager(conn, space_id)
    identity = ("mapping_type", "type_uri", "index_name")
    wanted = {_identity(m, identity) for m in document.get("fuzzy_mappings") or []}
    try:
        current = await mgr.list_mappings()
    except Exception:
        return                            # table absent on an older space
    for dto in current:
        d = dto.to_dict() if hasattr(dto, "to_dict") else dict(dto)
        key = _identity(d, identity)
        if key in wanted:
            continue
        label = "/".join(str(k) for k in key)
        entry = {"what": f"fuzzy_mapping/{label}", "table": None,
                 "rows_destroyed": None}
        if dry_run:
            report["removed"].append(entry)
            continue
        logger.warning("REPLACE: deleting fuzzy mapping %s/%s", space_id, label)
        ok = await mgr.delete_mapping(d.get("mapping_id"))
        (report["removed"] if ok else report["failed"]).append(entry)


async def _remove_absent_segmentation(conn, space_id, document, report, dry_run):
    from vitalgraph.document.segmentation_config_manager import (
        SegmentationConfigManager)

    mgr = SegmentationConfigManager(conn, space_id)
    wanted = {(s.get("document_type_uri"), s.get("segment_method_uri"))
              for s in document.get("segmentation_config") or []}
    try:
        current = await mgr.list_configs()
    except Exception:
        return
    for dto in current:
        d = dto.to_dict() if hasattr(dto, "to_dict") else dict(dto)
        key = (d.get("document_type_uri"), d.get("segment_method_uri"))
        if key in wanted:
            continue
        label = "/".join(str(k) for k in key)
        entry = {"what": f"segmentation_config/{label}", "table": None,
                 "rows_destroyed": None}
        if dry_run:
            report["removed"].append(entry)
            continue
        logger.warning("REPLACE: deleting segmentation config %s/%s",
                       space_id, label)
        ok = await mgr.delete_config(d.get("config_id"))
        (report["removed"] if ok else report["failed"]).append(entry)


async def _remove_absent_geo(conn, space_id, document, report, dry_run):
    """Only when the document says nothing about geo AND the space has a row.

    A document WITH a geo_config is handled by the merge phase; this is the
    remove-what-is-absent half.
    """
    from vitalgraph.vectorization.geo_config_manager import GeoConfigManager

    if document.get("geo_config") is not None:
        return
    mgr = GeoConfigManager(conn, space_id)
    try:
        if await mgr.get_config() is None:
            return
    except Exception:
        return
    entry = {"what": "geo_config", "table": None, "rows_destroyed": None}
    if dry_run:
        report["removed"].append(entry)
        return
    logger.warning("REPLACE: deleting geo config for %s", space_id)
    ok = await mgr.delete_config()
    (report["removed"] if ok else report["failed"]).append(entry)
