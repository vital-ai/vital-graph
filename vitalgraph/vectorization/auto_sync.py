"""
Auto-sync hooks for vector, geo, fuzzy, and FTS data.

A write calls `schedule_sync`, which queues the changed subjects in
`{space}_index_sync_queue`; `index_sync_worker` consumers re-derive their rows
(`issues/291`). The caller is not blocked. `sync_subjects` is the sync itself.

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
from dataclasses import dataclass, field

import asyncpg
from typing import Dict, List, Literal, Optional, Set
from vitalgraph.db.sparql_sql.space_names import space_prefix

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


@dataclass
class _VectorPlan:
    """One index's share of a sync: what to embed, and where it goes."""
    idx_name: str
    provider: object
    upsert_sql: str
    to_embed: List[tuple]                       # (subj_uuid, search_text)
    embeddings: List[Optional[List[float]]] = field(default_factory=list)


class EmbeddingUnavailable(RuntimeError):
    """Every text of a plan failed to embed: the provider is down, not one
    text bad. Raised so a queued sync is RETRIED rather than recorded as
    done with no vectors (`issues/291`)."""


async def _sync_vectors_for_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> None:
    """Re-vectorize or delete vectors for a list of subject UUIDs, all on one
    connection. `sync_subjects` runs the same three steps but releases its
    connection across the embedding call (`issues/291`)."""
    plans = await _plan_vectors(conn, space_id, subject_uuids, context_uuid, operation)
    await _embed_plans(space_id, plans)
    await _write_vectors(conn, space_id, context_uuid, plans)


async def _plan_vectors(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> List[_VectorPlan]:
    """Everything a vector sync needs from the database before embedding.

    Resolves each index's mapping per subject, builds the search texts, and
    DELETES the vectors of subjects that are out of scope, opted out or
    without text -- those are cheap and need no provider. Returns, per index,
    what remains to embed. Holds `conn` only for SQL.
    """
    from vitalgraph.vectorization.vector_populator import (
        delete_subject_vectors,
        UPSERT_VECTOR_SQL,
    )
    from vitalgraph.vectorization.search_text_builder import (
        build_search_text,
        fetch_literal_properties_batch,
        resolve_search_mapping,
    )
    from vitalgraph.vectorization.registry import get_provider
    from vitalgraph.vectorization.kgtype_description_lookup import KGTypeDescriptionLookup

    # Discover all vector indexes for this space
    try:
        rows = await conn.fetch(
            f"SELECT index_name, provider, provider_config FROM {space_prefix(space_id)}_vector_index"
        )
    except asyncpg.exceptions.UndefinedTableError:
        # No vector indexes configured for this space. Narrow on purpose: a
        # broad `except Exception` here would also swallow real query failures.
        return []

    if not rows:
        return []

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
        return []

    # ── Upsert path: batch fetch → concurrent embed → sequential upsert ──

    # Phase 1: Batch-fetch literal properties for all subjects (1 DB query)
    props_by_subject = await fetch_literal_properties_batch(
        conn, space_id, subject_uuids, context_uuid,
    )

    # WHAT EACH SUBJECT IS, so the index's mapping can be resolved for it.
    #
    # `issues/219`, and the same two defects `issues/217` fixed for FTS —
    # `build_search_text(props, None)` means "every literal property", and
    # nothing checked whether the subject was in the index's SCOPE, so every
    # changed subject was embedded into EVERY vector index in the space.
    #
    # WORSE HERE THAN FOR FTS, because an embedding is opaque: a wrong one
    # reads as a mediocre model rather than a bug, and repairing it costs a
    # provider call per row. Copying 43,783 nurture actions into an archive
    # whose only vector index is for DOCUMENT SEGMENTS put 291,089 embeddings
    # into it before anyone noticed — paid for, and for subjects the index was
    # never meant to hold. The write volume then drove an autovacuum storm that
    # took production query latency from 0.22s to 50s+.
    #
    # NO MAPPING NOW MEANS SKIP, exactly as on the FTS path.
    scope = await _subject_scopes(conn, space_id, subject_uuids, context_uuid)

    # WHO HAS OPTED OUT of vectors altogether (`issues/285`): an explicit
    # `KGIndexStatus_NO_INDEX`, or a document whose type has `auto_vectorize`
    # off. Treated exactly like "out of scope" below, so an opt-out also
    # REMOVES vectors written before it was set.
    from vitalgraph.document.vectorize_policy import vector_opt_outs
    opted_out = await vector_opt_outs(conn, space_id, subject_uuids, context_uuid)

    plans: List[_VectorPlan] = []
    # Process each index
    for row in rows:
        idx_name = row["index_name"]
        try:
            provider = get_provider(
                row["provider"], row["provider_config"] or {},
                cache_key=f"{space_id}:{idx_name}",
            )
        except Exception as e:
            # ONE index whose provider cannot be built must not stop the others.
            # Uncaught, this aborted the whole sync -- every later index, and the
            # geo, fuzzy and FTS steps after it -- for every subject in the
            # batch. An OpenAI index on a stack without a key did exactly that
            # to every new space, which bootstraps one (`issues/285`).
            logger.warning("auto_sync vector %s/%s skipped: provider %s "
                           "unavailable: %s", space_id, idx_name, row["provider"], e)
            continue
        vec_table = f"{space_prefix(space_id)}_vec_{idx_name}"
        upsert_sql = UPSERT_VECTOR_SQL.format(vec_table=vec_table)

        # Phase 2: Build search texts and identify subjects to embed
        to_embed: List[tuple] = []  # (subj_uuid, search_text)
        to_delete: List[uuid.UUID] = []

        rules: Dict[str, object] = {}
        for subj_uuid in subject_uuids:
            # str() on BOTH sides — asyncpg returns uuid.UUID keys and callers
            # may hold either form. A type mismatch here does not raise, it
            # misses, reads as "out of scope", and deletes the subject's
            # vectors. Same trap the FTS path documents.
            mapping_type, type_uri = scope.get(str(subj_uuid), (None, None))
            rule = None
            if str(subj_uuid) in opted_out:
                to_delete.append(subj_uuid)
                continue
            if mapping_type:
                rule = await resolve_search_mapping(
                    conn, space_id, idx_name, mapping_type, type_uri)
            if rule is None or not rule.enabled:
                # Out of scope for this index. Removing any row a previous
                # unscoped sync left behind makes the fix repair what the
                # defect wrote, rather than only stopping new damage.
                to_delete.append(subj_uuid)
                continue
            rules[str(subj_uuid)] = (subj_uuid, rule, mapping_type)

        # THE TYPE DESCRIPTION, for the rules that are built from it
        # (`issues/282`). This built every subject's text from its properties
        # alone, where the populator also resolves the description of the
        # subject's KGType. A `type_description` rule then produced "" and the
        # subject's vector was DELETED — on every entity write, and by the
        # cross-space sync whose whole job is to refresh those vectors after a
        # type changes — and a `properties_type` rule was embedded without its
        # type part. Batched as the populator batches it: one lookup of the
        # subjects' type URIs and one of the descriptions, per mapping type.
        type_desc: Dict[str, str] = {}
        needing: Dict[str, list] = {}
        for _k, (subj_uuid, rule, mapping_type) in rules.items():
            if rule.source_type in ("type_description", "properties_type"):
                needing.setdefault(mapping_type or "kgentity", []).append(subj_uuid)
        for mapping_type, uuids in needing.items():
            lookup = KGTypeDescriptionLookup(mapping_type)
            subj_types = await lookup.get_subject_type_uris_batch(
                conn, space_id, uuids, context_uuid)
            if not subj_types:
                continue
            descs = await lookup.get_descriptions_batch(
                conn, list(set(subj_types.values())))
            for su, type_uri in subj_types.items():
                d = descs.get(type_uri)
                if d:
                    type_desc[str(su)] = d

        for _k, (subj_uuid, rule, _mt) in rules.items():
            desc = type_desc.get(str(subj_uuid))
            props = props_by_subject.get(subj_uuid)
            if rule.source_type == "type_description":
                # Built from the type alone, as the populator does: no
                # description is no text, and the subject's own properties do
                # not matter.
                if not desc:
                    to_delete.append(subj_uuid)
                    continue
            elif not props:
                to_delete.append(subj_uuid)
                continue
            text = build_search_text(props or [], rule, type_description=desc)
            if not text.strip():
                to_delete.append(subj_uuid)
                continue
            to_embed.append((subj_uuid, text))

        if to_delete:
            # Said at DEBUG, because a subject the index does not cover is the
            # normal case — but it is also exactly how a missing scope looks, and
            # with no line at all that took a day to find (`issues/256`).
            logger.debug("auto_sync vector %s/%s: %d of %d subject(s) out of "
                         "scope or without text", space_id, idx_name,
                         len(to_delete), len(subject_uuids))
        # Delete subjects with no embeddable text
        for subj_uuid in to_delete:
            try:
                await delete_subject_vectors(conn, space_id, idx_name, subj_uuid, context_uuid)
            except Exception as e:
                logger.warning(
                    "auto_sync vector delete %s/%s/%s failed: %s",
                    space_id, idx_name, subj_uuid, e,
                )

        if to_embed:
            plans.append(_VectorPlan(idx_name, provider, upsert_sql, to_embed))
    return plans


async def _embed_plans(space_id: str, plans: List[_VectorPlan]) -> None:
    """Embed every plan's texts. Uses NO database connection.

    Raises `EmbeddingUnavailable` when every text of a plan failed, after
    the per-subject fallback: that is the provider failing, and a sync that
    swallowed it would be recorded as done with no vectors written.
    """
    for plan in plans:
        idx_name, provider, to_embed = plan.idx_name, plan.provider, plan.to_embed
        # One request for the whole set, not one per subject.  vectorize_texts
        # chunks internally at the provider's batch_size (100 for OpenAI), so a
        # large set is safe; results come back in input order, which the write
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
            if all(e is None for e in embeddings):
                raise EmbeddingUnavailable(
                    f"{space_id}/{idx_name}: all {len(texts)} text(s) failed to embed")
        plan.embeddings = embeddings


async def _write_vectors(conn, space_id: str, context_uuid: uuid.UUID,
                         plans: List[_VectorPlan]) -> None:
    """Upsert what `_embed_plans` produced, sequentially on `conn`."""
    for plan in plans:
        for i, (subj_uuid, _) in enumerate(plan.to_embed):
            emb = plan.embeddings[i] if i < len(plan.embeddings) else None
            if emb is None:
                continue
            try:
                vec_str = "[" + ",".join(str(v) for v in emb) + "]"
                await conn.execute(plan.upsert_sql, subj_uuid, context_uuid, vec_str)
            except Exception as e:
                logger.warning(
                    "auto_sync vector upsert %s/%s/%s failed: %s",
                    space_id, plan.idx_name, subj_uuid, e,
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
            f"SELECT COUNT(*) FROM {space_prefix(space_id)}_fuzzy_mapping WHERE enabled = TRUE"
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
    from vitalgraph.vectorization.search_text_builder import resolve_search_mapping

    # Quick check: does this space have any FTS indexes?
    try:
        rows = await conn.fetch(
            f"SELECT index_name FROM {space_prefix(space_id)}_fts_index"
        )
    except asyncpg.exceptions.UndefinedTableError:
        # No FTS indexes configured for this space.
        return

    if not rows:
        return

    index_names = [r["index_name"] for r in rows]

    if operation == "delete":
        for subj_uuid in subject_uuids:
            for idx_name in index_names:
                try:
                    await delete_subject_fts(conn, space_id, idx_name,
                                             subj_uuid, context_uuid)
                except Exception as e:
                    logger.warning("auto_sync fts delete %s/%s/%s failed: %s",
                                   space_id, idx_name, subj_uuid, e)
        return

    # WHAT EACH SUBJECT IS, so the index's mapping can be resolved for it.
    #
    # This used to call `update_subject_fts` with NO mapping_rule, and that is
    # two defects rather than one (issues/217):
    #
    #  1. `build_search_text(props, None)` falls back to "every literal
    #     property". So a row written by the bulk populator (the configured
    #     mapping — say `hasTextSlotValue` alone) was REPLACED on the next
    #     write by one holding the slot type URI, the frame URI, the graph URI,
    #     timestamps and the text. The two writers disagreed about what a row
    #     means, and ranking moved the first time anything was touched.
    #
    #  2. Nothing checked whether the subject was in the index's SCOPE, so
    #     every changed subject was upserted into EVERY index in the space. An
    #     index populated for one slot type acquired entities, frames and every
    #     other slot type as soon as they were written.
    #
    # Resolving the mapping fixes both, because NO MAPPING NOW MEANS SKIP. An
    # index whose mapping does not cover a subject should not contain it —
    # which is also what the bulk populator already does (`populate_fts_index`
    # returns early when `resolve_search_mapping` finds nothing).
    scope = await _subject_scopes(conn, space_id, subject_uuids, context_uuid)

    for subj_uuid in subject_uuids:
        # str() on BOTH sides. asyncpg returns uuid.UUID keys; callers may hold
        # either a UUID or its string form, and a type mismatch here does not
        # raise — it misses, reads as "out of scope", and DELETES the subject
        # from every index. Silent data loss is not an acceptable failure mode
        # for a key lookup.
        mapping_type, type_uri = scope.get(str(subj_uuid), (None, None))
        for idx_name in index_names:
            try:
                rule = None
                if mapping_type:
                    rule = await resolve_search_mapping(
                        conn, space_id, idx_name, mapping_type, type_uri)
                if rule is None or not rule.enabled:
                    # Out of scope for this index. Remove any row a previous
                    # (unscoped) sync left behind, so the fix also repairs
                    # what the defect wrote. Said at DEBUG: see the vector path.
                    logger.debug("auto_sync fts %s/%s: %s out of scope (%s, %s)",
                                 space_id, idx_name, subj_uuid, mapping_type, type_uri)
                    await delete_subject_fts(conn, space_id, idx_name,
                                             subj_uuid, context_uuid)
                    continue
                await update_subject_fts(
                    conn, space_id, idx_name, subj_uuid, context_uuid,
                    mapping_rule=rule, mapping_type=mapping_type)
            except Exception as e:
                logger.warning(
                    "auto_sync fts %s/%s/%s failed: %s",
                    space_id, idx_name, subj_uuid, e,
                )


# `hasKGSlotType` for a slot, else `hasKGEntityType`, else rdf:type — the three
# ways a KG object says what it IS, in the order a mapping would key on them.
# `$6` (`hasKGDocumentSegmentIndex`) and `$7` (`hasKGDocumentType`) exist because
# this query used to return only slot/entity/rdf_type, so a DOCUMENT SEGMENT fell
# through to the `kgentity` fallback and could never match a `kgdocument_segment`
# mapping — every segment was treated as out of scope and had its vector row
# DELETED (`issues/245`).
_SCOPE_SQL = """
SELECT q.subject_uuid,
       max(CASE WHEN tp.term_text = $3 THEN tv.term_text END) AS slot_type,
       max(CASE WHEN tp.term_text = $4 THEN tv.term_text END) AS entity_type,
       max(CASE WHEN tp.term_text = $5 THEN tv.term_text END) AS rdf_type,
       max(CASE WHEN tp.term_text = $6 THEN tv.term_text END) AS segment_index,
       max(CASE WHEN tp.term_text = $7 THEN tv.term_text END) AS document_type
FROM {rdf_quad} q
JOIN {term} tp ON tp.term_uuid = q.predicate_uuid
JOIN {term} tv ON tv.term_uuid = q.object_uuid
WHERE q.subject_uuid = ANY($1::uuid[])
  AND q.context_uuid = $2
  AND tp.term_text IN ($3, $4, $5, $6, $7)
GROUP BY q.subject_uuid
"""


async def _subject_scopes(conn, space_id: str, subject_uuids, context_uuid):
    """subject_uuid -> (mapping_type, type_uri) for mapping resolution.

    One query for the whole batch, not one per subject: this runs on every
    write, so a per-subject round trip would put three queries on the hot path
    for a three-object entity graph.
    """
    HALEY = "http://vital.ai/ontology/haley-ai-kg#"
    rows = await conn.fetch(
        _SCOPE_SQL.format(rdf_quad=f"{space_prefix(space_id)}_rdf_quad",
                          term=f"{space_prefix(space_id)}_term"),
        list(subject_uuids), context_uuid,
        f"{HALEY}hasKGSlotType", f"{HALEY}hasKGEntityType",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        f"{HALEY}hasKGDocumentSegmentIndex", f"{HALEY}hasKGDocumentType",
    )
    KGDOC = f"{HALEY}KGDocument"
    # A KGTYPE is classified by its CLASS, before anything else. With no branch
    # for it, a type fell through to the `kgentity` fallback below, matched no
    # mapping in an index whose mappings are all `kgtype`, and was skipped — so
    # NOTHING indexed a new or changed KGType after `issues/219` made this
    # scoped (`issues/256`, found 2026-10-04: six index-backed type searches
    # passed locally only against rows written in August). Resolved the way the
    # bulk populator resolves it: `KGType` and its subclasses, from VitalSigns.
    from .vector_populator import _resolve_vitaltype_filter
    kgtype_classes = set(_resolve_vitaltype_filter("kgtype") or ())
    kgdocument_classes = set(_resolve_vitaltype_filter("kgdocument") or ()) | {KGDOC}
    out = {}
    for r in rows:
        key = str(r["subject_uuid"])   # see the lookup in the caller
        if r["rdf_type"] and r["rdf_type"] in kgtype_classes:
            out[key] = ("kgtype", r["rdf_type"])
        elif r["slot_type"]:
            out[key] = ("kgslot", r["slot_type"])
        elif r["entity_type"]:
            out[key] = ("kgentity", r["entity_type"])
        elif r["segment_index"] is not None:
            # A SEGMENT before a document: both are `rdf:type KGDocument`, and the
            # segment index is what tells them apart (the same discriminator the
            # segment listing queries use). Ordered above `document_type` because a
            # segment carries a document type too -- `urn:kgdoctype:document_segment`,
            # NOT its parent's (`kgdocument_segmentation_processor` sets it) -- so
            # testing that first would classify every segment as a whole document.
            out[key] = ("kgdocument_segment", r["document_type"] or KGDOC)
        elif r["document_type"]:
            out[key] = ("kgdocument", r["document_type"])
        elif r["rdf_type"] and r["rdf_type"] in kgdocument_classes:
            # A document WITHOUT a type is still a document. This fell through
            # to `kgentity` below, so an upload -- which set no
            # `kGDocumentType` -- was embedded into any index with a catch-all
            # entity mapping (`issues/285`). The bulk populator already treats
            # it as `kgdocument` (it selects by vitaltype), so the two now agree.
            out[key] = ("kgdocument", None)
        elif r["rdf_type"]:
            # The fallback stays `kgentity`, which is what it always was — but it
            # is now reached only by subjects that are none of the above, rather
            # than by every document and segment in the space.
            out[key] = ("kgentity", r["rdf_type"])
    return out


async def _space_still_exists(conn, space_id: str) -> bool:
    """Cheap catalog check that the space's tables are still present.

    Guards against syncing a space that was deleted while this task sat in the
    queue. Checked BEFORE any embedding work: the vector step calls out to the
    embedding provider first and only then writes, so a check placed later
    would still incur (billed) API calls for a space that no longer exists.

    Also covers the multi-worker case, where the deletion happened in a
    different process and cancel_space_syncs() could not reach this task.
    """
    # Delegated so there is ONE implementation: the maintenance sweep and the
    # server-property backfill ask the same question (`issues/253`).
    from ..db.sparql_sql.space_presence import space_tables_present
    return await space_tables_present(conn, space_id)


async def sync_subjects(
    pool,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID,
    operation: str,
) -> bool:
    """Re-derive vector, geo, fuzzy and FTS rows for these subjects.

    THE CONNECTION IS NOT HELD ACROSS THE EMBEDDING CALL (`issues/291`). One
    acquire reads and plans (and deletes what needs no provider), the provider
    is called with no connection held, and a second acquire writes. Holding one
    connection throughout kept an internal-pool connection idle for the length
    of every OpenAI round trip, so a burst of writes filled the 3-connection
    pool and starved the segmentation worker, ANALYZE and the maintenance job.

    What was read may be overtaken by a write during the embedding; the queue's
    generation rule (`index_sync_queue`) re-syncs it. Raises on failure, so a
    queued sync is retried. Returns False if the space no longer exists.
    """
    if not subject_uuids:
        return True
    async with pool.acquire() as conn:
        if not await _space_still_exists(conn, space_id):
            logger.debug("auto_sync: space '%s' no longer exists — skipping sync "
                         "of %d subject(s)", space_id, len(subject_uuids))
            return False
        plans = await _plan_vectors(conn, space_id, subject_uuids, context_uuid, operation)
    await _embed_plans(space_id, plans)
    async with pool.acquire() as conn:
        # Checked again: the space may have been deleted, by any process,
        # while the provider was being called.
        if not await _space_still_exists(conn, space_id):
            return False
        await _write_vectors(conn, space_id, context_uuid, plans)
        # Geo, fuzzy, FTS share the same connection — must be sequential
        await _sync_geo_for_subjects(conn, space_id, subject_uuids, context_uuid, operation)
        await _sync_fuzzy_for_subjects(conn, space_id, subject_uuids, context_uuid, operation)
        await _sync_fts_for_subjects(conn, space_id, subject_uuids, context_uuid, operation)
    return True


def _internal_pool(db_impl):
    # THE INTERNAL POOL, NOT THE REQUEST POOL (`issues/231`).
    #
    # This runs AFTER the write it belongs to has returned 200. On the request
    # pool its cost lands on readers: a bulk copy returned success 43,783 times
    # while its consequences kept embedding and analysing on connections the
    # readers needed, and production stopped answering twice in one day.
    #
    # `internal_pool_for` distinguishes "disabled on purpose" from "missing by
    # accident" and reports the second at ERROR; a bare `or` made the bulkhead's
    # absence invisible.
    from ..db.pool import internal_pool_for
    return internal_pool_for(db_impl)


async def _run_sync(
    db_impl,
    space_id: str,
    subject_uris: List[str],
    graph_uri: str,
    operation: str,
) -> None:
    """Sync these subjects NOW, in this task, bypassing the queue.

    For callers that must have the rows before they go on (the archive
    script), and for a space that has no queue table yet. Logs and swallows a
    failure, as it always has; a queued sync is retried instead.
    """
    if not subject_uris:
        return
    pool = _internal_pool(db_impl)
    if pool is None:
        logger.debug("auto_sync: no pool on db_impl, skipping")
        return
    try:
        await sync_subjects(
            pool, space_id, [_generate_term_uuid(u) for u in subject_uris],
            _generate_term_uuid(graph_uri), operation)
    except Exception as e:
        logger.error("auto_sync(%s) failed: %s: %s", space_id, type(e).__name__, e)


# Spaces already warned about running without a queue table, so the warning
# is said once per process rather than on every write.
_NO_QUEUE_WARNED: Set[str] = set()


async def _enqueue_sync(
    db_impl,
    space_id: str,
    subject_uris: List[str],
    graph_uri: str,
    operation: str,
    rederive: bool = False,
) -> None:
    """Queue these subjects for the index sync workers (`issues/291`).

    ON A SPACE WITH THE `rdf_quad` TRIGGER this does nothing unless
    `rederive`: the trigger already queued every subject the write touched,
    inside the write's transaction (`index_sync_trigger`). Enqueueing again
    here would bump the rows' generation, and a bump that lands while a
    consumer is embedding them costs a second embedding. `rederive=True` is
    for "re-derive these although their quads did not change" -- a KGType's
    description, a document type's vectorize default -- which no trigger
    sees.

    A space without `{space}_index_sync_queue` -- not yet migrated
    (`scripts/migrate_index_sync_queue.py`) -- is synced directly, as before,
    so the deploy order does not matter. Tables are never created here.
    """
    if not subject_uris:
        return
    pool = _internal_pool(db_impl)
    if pool is None:
        logger.debug("auto_sync: no pool on db_impl, skipping")
        return
    from . import index_sync_queue as q
    context_uuid = _generate_term_uuid(graph_uri)
    subject_uuids = [_generate_term_uuid(u) for u in subject_uris]
    async with pool.acquire() as conn:
        if not rederive:
            from .index_sync_trigger import installed_cached
            if await installed_cached(conn, space_id):
                return
        if await q.table_exists(conn, space_id):
            async with conn.transaction():
                await q.enqueue(conn, space_id, context_uuid, subject_uuids, operation)
            return
    if space_id not in _NO_QUEUE_WARNED:
        _NO_QUEUE_WARNED.add(space_id)
        logger.warning("auto_sync: %s has no index sync queue table; syncing "
                       "directly. Run scripts/migrate_index_sync_queue.py.", space_id)
    await _run_sync(db_impl, space_id, subject_uris, graph_uri, operation)


async def wait_until_synced(db_impl, space_id: str, subject_uris: List[str],
                            graph_uri: str, *, timeout: float = 600.0,
                            poll: float = 0.5) -> bool:
    """Wait until none of these subjects is queued. True if they drained.

    Holds no connection between polls. A space without a queue table synced
    directly, so it is drained by definition.
    """
    pool = _internal_pool(db_impl)
    if pool is None or not subject_uris:
        return True
    from . import index_sync_queue as q
    context_uuid = _generate_term_uuid(graph_uri)
    subject_uuids = [_generate_term_uuid(u) for u in subject_uris]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        async with pool.acquire() as conn:
            if not await q.table_exists(conn, space_id):
                return True
            if not await q.pending(conn, space_id, context_uuid, subject_uuids):
                return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(poll)


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
    rederive: bool = False,
) -> Optional[asyncio.Task]:
    """Queue these subjects for an index sync (non-blocking).

    The returned task only ENQUEUES (`issues/291`): a short insert into
    `{space}_index_sync_queue`, after which the index sync workers -- in any
    app process -- do the work, bounded, merged per subject, and retried on
    failure. Awaiting the task means "queued", not "synced"; use
    `wait_until_synced` for the latter.

    After a WRITE this is a no-op on a space with the `rdf_quad` trigger,
    which queued the write's subjects in its own transaction; it remains the
    path for a space not yet migrated. Pass `rederive=True` to re-derive
    subjects whose quads did not change.

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
        _enqueue_sync(db_impl, space_id, subject_uris, graph_uri, operation, rederive),
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
