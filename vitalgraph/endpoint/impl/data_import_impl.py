"""
Import engine for VitalGraph sparql_sql backend.

Provides two import strategies:
  - **bulk**: Aggressive COPY-based loading with index drop/recreate.
    Suitable for CLI / offline batch loads.
  - **incremental**: Batched INSERT ON CONFLICT for production use.
    No index drops, yields between batches, checkpoint support.

Both strategies share term UUID generation and pyoxigraph N-Triples parsing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid as uuid_mod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Deterministic namespace for term UUID v5 generation
_NS = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


class ImportMode(str, Enum):
    BULK = "bulk"
    INCREMENTAL = "incremental"


@dataclass
class ImportProgress:
    """Snapshot of import progress."""
    phase: str = "init"
    records_done: int = 0
    records_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    batch_number: int = 0
    elapsed_seconds: float = 0.0
    rate_per_second: float = 0.0
    message: str = ""


# Type alias for progress callback
_XSD = "http://www.w3.org/2001/XMLSchema#"

ProgressCallback = Callable[[ImportProgress], None]


def _term_uuid(text: str, ttype: str, lang: Optional[str] = None,
               datatype_id: Optional[int] = None) -> str:
    """Generate deterministic UUID v5 for a term."""
    parts = [text, ttype]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return str(uuid_mod.uuid5(_NS, "\x00".join(parts)))


async def _resolve_datatype_ids(conn, space_id: str,
                                uris) -> Dict[str, int]:
    """Map datatype URI -> the space's integer id, creating any that are new.

    `_term_uuid` hashes the datatype_ID, not the URI, so this has to run BEFORE
    the terms are hashed — otherwise the import mints uuids against ids it has
    not resolved yet and no other writer would agree with them (`issues/157`).

    The insert is `ON CONFLICT DO NOTHING` followed by a re-read rather than
    `RETURNING`, because a concurrent importer may have created the same row:
    RETURNING gives nothing for the conflicting insert and the id would come
    back None for a datatype that plainly exists.
    """
    uris = {u for u in uris if u}
    if not uris:
        return {}
    t_dt = f"{space_id}_datatype"
    await conn.executemany(
        f"INSERT INTO {t_dt} (datatype_uri) VALUES ($1) ON CONFLICT DO NOTHING",
        [(u,) for u in sorted(uris)])
    rows = await conn.fetch(
        f"SELECT datatype_uri, datatype_id FROM {t_dt} "
        f"WHERE datatype_uri = ANY($1::text[])", list(uris))
    return {r["datatype_uri"]: r["datatype_id"] for r in rows}


def _scan_datatype_uris(file_path: str) -> set:
    """Every literal datatype URI in the file.

    A separate cheap pass rather than folding it into pass 1: the ids must be
    known before the first term is hashed, and pass 1 is where the hashing
    happens.
    """
    from pyoxigraph import parse as ox_parse
    out = set()
    with open(file_path, "rb") as f:
        for triple in ox_parse(f, "application/n-triples"):
            o = triple.object
            if type(o).__name__ == "Literal" and not o.language:
                dt = getattr(o, "datatype", None)
                if dt is not None:
                    out.add(str(dt.value))
    return out


def _classify_node(node, bnode_scope: Optional[str] = None
                   ) -> Tuple[str, str, Optional[str], Optional[str]]:
    """Classify a pyoxigraph triple node into (value, term_type, lang, datatype).

    THE DATATYPE IS PART OF THE TERM, not decoration (`issues/157`). This
    returned a three-tuple and dropped `node.datatype` on the floor, with two
    consequences:

      * every typed comparator matched NOTHING on imported data — measured at
        6,636 typed terms via the CSV loader against 26 via this path, and a
        `MQLRating >= 65` criterion returning 698 rows on one and 0 on the
        other, from the same generator;
      * worse, `_term_uuid` HASHES the datatype, so a bulk-imported "58.0" got a
        different uuid from the same literal written by `add_rdf_quads_batch` or
        a SPARQL UPDATE. One value, two terms, and a query against either could
        not see quads written through the other. Latent until a space is both
        imported and incrementally written, which is the normal lifecycle.

    pyoxigraph gives a Literal's datatype as an IRI whose `.value` is the URI.
    `xsd:string` is returned as-is rather than normalised away: the writers this
    has to agree with resolve it to a datatype_id like any other, and dropping
    it here would recreate the same split for every plain string.

    `bnode_scope` skolemises blank-node labels against the document they came
    from. RDF scopes labels to the document, so two files using `_:b0` describe
    two different nodes; without a scope they merge, which is a conformance
    defect regardless of whether anyone has imported such a file here.

    Shared by both N-Triples importers, which is why the scope belongs on this
    function rather than at each of its call sites.
    """
    cls_name = type(node).__name__
    if cls_name == "Literal":
        lang = str(node.language) if node.language else None
        dt = getattr(node, "datatype", None)
        # A language-tagged literal is rdf:langString by definition; carrying
        # both would double-key the same term.
        dt_uri = str(dt.value) if (dt is not None and lang is None) else None
        # `xsd:string` IS KEPT, because that is what the system actually does
        # everywhere else — verified against production, not inferred.
        #
        #     space                 string    other typed    UNTYPED
        #     prod_kg              375,186        525,022          0
        #     lead_data            326,323        127,526          0
        #     kg_crud_stress_test      499             25          0
        #
        # Zero untyped literals anywhere, including a space written through the
        # CRUD path rather than loaded from a file. `rdflib.Literal("CA")`
        # reports `datatype is None`, which is what led an earlier version of
        # this to normalise xsd:string away — but the KG model emits TYPED
        # values, so `_ensure_term` receives literals that already carry
        # xsd:string and stores it.
        #
        # Normalising here would therefore SPLIT production terms rather than
        # unify them: an import into an existing space would write "CA" untyped
        # against 375,186 typed ones, which is `issues/157` reintroduced by its
        # own fix.
        #
        # RDF 1.1 says a plain literal and an xsd:string literal denote the same
        # value, so the stored form is arguably wrong — but it is CONSISTENTLY
        # wrong, and consistency is what term identity needs. Changing it is a
        # migration, not an importer edit (`issues/158`).
        return node.value, "L", lang, dt_uri
    elif cls_name == "BlankNode":
        label = node.value
        if bnode_scope:
            from vitalgraph.db.sparql_sql.term_normalize import (
                is_skolem_label, skolem_label)
            # NOT if it is already skolemised. A skolem label is globally
            # unique and document-independent — that is the whole point of
            # minting it — so scoping it again treats a global identifier as a
            # document-local one. Our own export re-imported would then land on
            # a DIFFERENT node, and every export/import cycle would mint
            # another, so identity would drift instead of round-tripping.
            if not is_skolem_label(label):
                label = skolem_label(bnode_scope, label)
        return label, "B", None, None
    else:
        # One of our own Skolem IRIs read back becomes the blank node it was,
        # rather than an ordinary IRI — the export round-trip.
        from vitalgraph.db.sparql_sql.term_normalize import deskolemize_iri
        inner = deskolemize_iri(node.value)
        if inner is not None:
            return inner, "B", None, None
        return node.value, "U", None, None


def _unescape_nquads_string(s: str) -> str:
    """Unescape N-Quads string escape sequences."""
    return (s
            .replace('\\r', '\r')
            .replace('\\n', '\n')
            .replace('\\"', '"')
            .replace('\\\\', '\\'))


def _bnode_scope_for(graph_uri: str, file_path: str) -> str:
    """The document scope a blank-node label is interpreted in.

    RDF scopes labels to the document, so the scope has to identify the
    document — and it has to be STABLE across reloads, or re-importing a file
    would mint new nodes every time and reload would stop being idempotent
    (issues/041).

    Graph URI plus source basename, not the full path: the same file imported
    from a different working directory or a different machine is the same
    document, and a path would make it a different one.
    """
    import os
    return f"{graph_uri}\x00{os.path.basename(file_path or '')}"


def _parse_nquads_term_for_import(
        term_str: str,
        bnode_scope: Optional[str] = None) -> Tuple[str, str, Optional[str]]:
    """Parse an N-Quads-encoded term into (text, term_type, lang).

    Returns values matching the term table schema:
      ``<http://...>``                → (``http://...``, ``"U"``, None)
      ``_:label``                     → (``label``,      ``"B"``, None)
      ``"value"``                     → (``value``,      ``"L"``, None)
      ``"value"^^<http://...>``       → (``value``,      ``"L"``, None)
      ``"value"@en``                  → (``value``,      ``"L"``, ``"en"``)
    """
    term_str = term_str.strip()

    # URI. One of OUR OWN Skolem IRIs is checked FIRST, because this branch
    # returns unconditionally and would otherwise read an exported blank node
    # back as an ordinary IRI — losing that it was ever a blank node, which is
    # exactly the round-trip skolemisation exists to preserve.
    if term_str.startswith('<') and term_str.endswith('>'):
        from vitalgraph.db.sparql_sql.term_normalize import deskolemize_iri
        inner = deskolemize_iri(term_str[1:-1])
        if inner is not None:
            return inner, "B", None
        return term_str[1:-1], "U", None

    # Blank node
    if term_str.startswith('_:'):
        label = term_str[2:]
        # SKOLEMISE against the document this term came from. RDF 1.1: blank
        # node identifiers are "locally scoped to the file or RDF store, and
        # are *not* persistent or portable" — so two files each using `_:b0`
        # describe two different nodes. Without a scope they collapsed into
        # one, silently and unrecoverably (issues/076 facet 2).
        #
        # Deterministic in the scope, so re-importing the same document
        # reproduces the same nodes and reload stays idempotent (issues/041).
        # A random per-load label would satisfy RDF and break that.
        if bnode_scope:
            from vitalgraph.db.sparql_sql.term_normalize import (
                is_skolem_label, skolem_label)
            # NOT if it is already skolemised. A skolem label is globally
            # unique and document-independent — that is the whole point of
            # minting it — so scoping it again treats a global identifier as a
            # document-local one. Our own export re-imported would then land on
            # a DIFFERENT node, and every export/import cycle would mint
            # another, so identity would drift instead of round-tripping.
            if not is_skolem_label(label):
                label = skolem_label(bnode_scope, label)
        return label, "B", None


    # Literal
    if term_str.startswith('"'):
        i = 1
        while i < len(term_str):
            if term_str[i] == '\\':
                i += 2
                continue
            if term_str[i] == '"':
                break
            i += 1

        lexical = _unescape_nquads_string(term_str[1:i])
        rest = term_str[i + 1:]

        if rest.startswith('@'):
            lang = rest[1:]
            return lexical, "L", lang
        # Typed literals and plain strings both stored as "L" with no lang
        return lexical, "L", None

    # Fallback: treat as URI
    return term_str, "U", None


class ImportEngine:
    """Core import engine for sparql_sql backend.

    Usage::

        engine = ImportEngine(pool, signal_manager=signal_manager)
        result = await engine.import_ntriples_bulk(
            space_id="my_space",
            graph_uri="urn:my_space:main",
            file_path="/data/dump.nt",
        )
    """

    def __init__(self, pool, signal_manager=None):
        """
        Args:
            pool: asyncpg connection pool.
            signal_manager: optional; used to tell OTHER processes to drop their
                term cache after a load. A bulk import TRUNCATES the term table
                and reloads it, so every cached literal->uuid mapping for the
                space is stale — and a running server that keeps the old one
                resolves constants to terms that no longer exist, so affected
                queries return 0 rows and report success. The CLI has no signal
                manager, which is exactly the case that bit: an import from the
                command line cannot reach the server's memory, so the server
                must be told or restarted.
        """
        self._pool = pool
        self._signal_manager = signal_manager

    async def _invalidate_term_cache(self, space_id: str) -> None:
        """Drop this process's term cache for *space_id*, and tell the others."""
        from vitalgraph.db.sparql_sql.generator import invalidate_term_cache
        invalidate_term_cache(space_id)
        sm = self._signal_manager
        if sm is None:
            logger.warning(
                "Import of %s changed term uuids, but this process has no "
                "SignalManager: any RUNNING server still holds the old "
                "literal->uuid mappings and will return 0 rows for affected "
                "queries until it is restarted.", space_id)
            return
        try:
            await sm.notify_cache_invalidate("term", space_id)
            logger.info("Notified term-cache invalidation for %s", space_id)
        except Exception as exc:
            logger.warning("Could not notify term-cache invalidation for %s: %s",
                           space_id, exc)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_table_names(space_id: str) -> Dict[str, str]:
        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        return SparqlSQLSchema.get_table_names(space_id)

    async def _validate_tables(self, conn, space_id: str) -> Tuple[str, str]:
        """Check that per-space tables exist.  Returns (term_tbl, quad_tbl)."""
        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']
        for tbl in (term_tbl, quad_tbl):
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=$1)", tbl)
            if not exists:
                raise RuntimeError(
                    f"Table {tbl} does not exist. "
                    f"Create the space first.")
        return term_tbl, quad_tbl

    @staticmethod
    def _parse_ntriples_terms(file_path: str, graph_uri: str,
                              progress_cb: Optional[ProgressCallback] = None,
                              datatype_ids: Optional[Dict[str, int]] = None,
                              ) -> Tuple[Dict[Tuple, str], int]:
        """Pass 1: Parse N-Triples file and collect unique terms with UUIDs.

        Returns:
            (terms_dict, triple_count) where terms_dict maps
            (text, type, lang, datatype_uri) -> uuid_str.
        """
        datatype_ids = datatype_ids or {}
        from pyoxigraph import parse as ox_parse

        terms: Dict[Tuple, str] = {}
        triple_count = 0
        file_size = os.path.getsize(file_path)
        t0 = time.time()
        # Labels are scoped to this document (issues/076 facet 2). Must match
        # the scope pass 2 uses, or the two passes would mint different labels
        # for one node and the quads would reference terms that do not exist.
        bnode_scope = _bnode_scope_for(graph_uri, file_path)

        # The datatype is part of the KEY and of the HASH. `_term_uuid` mixes
        # `datatype_id` in, so omitting it here minted a uuid no other writer
        # would ever produce for the same literal (`issues/157`).
        #
        # `datatype_ids` maps uri -> the space's integer id; it is resolved
        # BEFORE this pass so the hash can use the same id the row will carry.
        def ensure(text: str, ttype: str, lang: Optional[str] = None,
                   dt_uri: Optional[str] = None) -> str:
            key = (text, ttype, lang, dt_uri)
            if key not in terms:
                terms[key] = _term_uuid(text, ttype, lang=lang,
                                        datatype_id=datatype_ids.get(dt_uri))
            return terms[key]

        # Pre-register graph URI
        ensure(graph_uri, "U")

        with open(file_path, "rb") as f:
            for triple in ox_parse(f, "application/n-triples"):
                s_val, s_type, _, _ = _classify_node(triple.subject, bnode_scope)
                ensure(s_val, s_type)
                ensure(triple.predicate.value, "U")
                o_val, o_type, o_lang, o_dt = _classify_node(triple.object, bnode_scope)
                ensure(o_val, o_type, o_lang, o_dt)
                triple_count += 1

                if progress_cb and triple_count % 500_000 == 0:
                    elapsed = time.time() - t0
                    progress_cb(ImportProgress(
                        phase="parse_terms",
                        records_done=triple_count,
                        bytes_total=file_size,
                        elapsed_seconds=elapsed,
                        rate_per_second=triple_count / elapsed if elapsed > 0 else 0,
                        message=f"{triple_count:,} triples, {len(terms):,} unique terms",
                    ))

        return terms, triple_count

    # ------------------------------------------------------------------
    # Bulk import (CLI-aggressive)
    # ------------------------------------------------------------------

    async def import_ntriples_bulk(
        self,
        space_id: str,
        graph_uri: str,
        file_path: str,
        batch_size: int = 50_000,
        force: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Aggressive bulk import using COPY with index drop/recreate.

        Suitable for CLI / offline loads where the service is not live.

        Args:
            space_id: Target space.
            graph_uri: Graph URI to assign to all triples.
            file_path: Path to N-Triples file.
            batch_size: Quads per COPY batch.
            force: If True, truncate existing data first.
            progress_cb: Optional progress callback.
            cancel_event: Optional asyncio.Event; set to cancel import.

        Returns:
            Dict with keys: success, terms, quads, elapsed_seconds, phases.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        phases: Dict[str, float] = {}

        async with self._pool.acquire() as conn:
            term_tbl, quad_tbl = await self._validate_tables(conn, space_id)

            # Check existing data
            existing_terms = await conn.fetchval(f"SELECT COUNT(*) FROM {term_tbl}")
            existing_quads = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_tbl}")
            if existing_terms > 0 or existing_quads > 0:
                if force:
                    logger.info("Truncating tables (%d terms, %d quads)",
                                existing_terms, existing_quads)
                    await conn.execute(f"TRUNCATE {quad_tbl}")
                    await conn.execute(f"TRUNCATE {term_tbl} CASCADE")
                else:
                    raise RuntimeError(
                        f"Tables not empty ({existing_terms:,} terms, "
                        f"{existing_quads:,} quads). Use force=True to truncate.")

            # Drop non-PK indexes
            saved_indexes = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename = ANY($1::text[]) "
                "AND indexname NOT LIKE '%_pkey'",
                [term_tbl, quad_tbl])
            for row in saved_indexes:
                await conn.execute(f"DROP INDEX IF EXISTS {row['indexname']}")
            logger.info("Dropped %d indexes for bulk load", len(saved_indexes))

        # --- Pass 1: collect terms ---
        if progress_cb:
            progress_cb(ImportProgress(phase="parse_terms", message="Collecting terms..."))

        t0 = time.time()
        # Datatypes FIRST. `_term_uuid` hashes the datatype_id, so the ids have
        # to exist before a single term is hashed (`issues/157`).
        async with self._pool.acquire() as conn:
            datatype_ids = await _resolve_datatype_ids(
                conn, space_id, _scan_datatype_uris(file_path))
        if datatype_ids:
            logger.info("Resolved %d literal datatype(s) for %s",
                        len(datatype_ids), space_id)

        terms, triple_count = self._parse_ntriples_terms(
            file_path, graph_uri, progress_cb, datatype_ids)
        phases['parse_terms'] = time.time() - t0

        if cancel_event and cancel_event.is_set():
            return {"success": False, "cancelled": True}

        # --- COPY terms ---
        if progress_cb:
            progress_cb(ImportProgress(
                phase="copy_terms",
                records_total=len(terms),
                message=f"COPY {len(terms):,} terms...",
            ))

        t0 = time.time()
        term_records = [
            (uid, text, ttype, lang, datatype_ids.get(dt_uri), "primary")
            for (text, ttype, lang, dt_uri), uid in terms.items()
        ]
        async with self._pool.acquire() as conn:
            await conn.copy_records_to_table(
                term_tbl,
                columns=["term_uuid", "term_text", "term_type", "lang",
                         "datatype_id", "dataset"],
                records=term_records,
            )
        phases['copy_terms'] = time.time() - t0
        del term_records

        if cancel_event and cancel_event.is_set():
            return {"success": False, "cancelled": True}

        # --- Pass 2: COPY quads ---
        if progress_cb:
            progress_cb(ImportProgress(
                phase="copy_quads",
                records_total=triple_count,
                message=f"COPY quads (batch_size={batch_size:,})...",
            ))

        from pyoxigraph import parse as ox_parse

        graph_uuid = terms[(graph_uri, "U", None, None)]
        quad_batch: List[Tuple] = []
        total_quads = 0
        t0 = time.time()

        async def flush(batch: List[Tuple]) -> None:
            nonlocal total_quads
            if not batch:
                return
            async with self._pool.acquire() as conn:
                await conn.copy_records_to_table(
                    quad_tbl,
                    columns=["subject_uuid", "predicate_uuid", "object_uuid",
                             "context_uuid", "dataset"],
                    records=batch,
                )
            total_quads += len(batch)

        # SAME scope as pass 1, which resolved the terms. A different scope here
        # would mint different labels for the same node, and the quads would
        # reference term uuids that pass 1 never inserted.
        bnode_scope = _bnode_scope_for(graph_uri, file_path)

        with open(file_path, "rb") as f:
            for triple in ox_parse(f, "application/n-triples"):
                s_val, s_type, _, _ = _classify_node(triple.subject, bnode_scope)
                s_uuid = terms[(s_val, s_type, None, None)]
                p_uuid = terms[(triple.predicate.value, "U", None, None)]
                o_val, o_type, o_lang, o_dt = _classify_node(triple.object, bnode_scope)
                o_uuid = terms[(o_val, o_type, o_lang, o_dt)]

                quad_batch.append((s_uuid, p_uuid, o_uuid, graph_uuid, "primary"))

                if len(quad_batch) >= batch_size:
                    await flush(quad_batch)
                    quad_batch = []
                    if progress_cb and total_quads % 500_000 == 0:
                        elapsed = time.time() - t0
                        progress_cb(ImportProgress(
                            phase="copy_quads",
                            records_done=total_quads,
                            records_total=triple_count,
                            elapsed_seconds=elapsed,
                            rate_per_second=total_quads / elapsed if elapsed > 0 else 0,
                        ))
                    if cancel_event and cancel_event.is_set():
                        return {"success": False, "cancelled": True}

        await flush(quad_batch)
        phases['copy_quads'] = time.time() - t0

        # --- Recreate indexes ---
        if progress_cb:
            progress_cb(ImportProgress(
                phase="recreate_indexes",
                message=f"Recreating {len(saved_indexes)} indexes...",
            ))

        t0 = time.time()
        async with self._pool.acquire() as conn:
            for row in saved_indexes:
                await conn.execute(row['indexdef'])
        phases['recreate_indexes'] = time.time() - t0

        # --- Resync auxiliary tables ---
        if progress_cb:
            progress_cb(ImportProgress(
                phase="resync",
                message="Syncing auxiliary tables (edge, frame_entity, stats)...",
            ))

        t0 = time.time()
        from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables
        async with self._pool.acquire() as conn:
            resync_result = await resync_all_auxiliary_tables(conn, space_id)
        phases['resync'] = time.time() - t0

        # --- Drop stale literal->uuid mappings ---
        # AFTER the data is in, so nothing re-caches the old terms in between.
        await self._invalidate_term_cache(space_id)

        # --- Register graph ---
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO graph (space_id, graph_uri, graph_name, created_time) "
                "VALUES ($1, $2, $3, NOW()) "
                "ON CONFLICT DO NOTHING",
                space_id, graph_uri, graph_uri,
            )

        # --- Verify ---
        async with self._pool.acquire() as conn:
            final_terms = await conn.fetchval(f"SELECT COUNT(*) FROM {term_tbl}")
            final_quads = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_tbl}")

        total_elapsed = sum(phases.values())
        if progress_cb:
            progress_cb(ImportProgress(
                phase="done",
                records_done=final_quads,
                records_total=final_quads,
                elapsed_seconds=total_elapsed,
                message="Import complete",
            ))

        return {
            "success": True,
            "terms": final_terms,
            "quads": final_quads,
            "resync": resync_result,
            "elapsed_seconds": total_elapsed,
            "phases": phases,
        }

    # ------------------------------------------------------------------
    # Incremental import (REST-safe)
    # ------------------------------------------------------------------

    async def import_ntriples_incremental(
        self,
        space_id: str,
        graph_uri: str,
        file_path: str,
        batch_size: int = 5_000,
        mode: str = "append",
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        checkpoint_offset: int = 0,
    ) -> Dict[str, Any]:
        """Conservative import using INSERT ON CONFLICT for production use.

        No index drops.  Smaller batches.  Yields between batches so the
        event loop stays responsive.

        Args:
            space_id: Target space.
            graph_uri: Graph URI to assign to all triples.
            file_path: Path to N-Triples file (local or downloaded from S3).
            batch_size: Records per INSERT batch.
            mode: 'append' or 'replace'. Replace clears graph first.
            progress_cb: Optional progress callback.
            cancel_event: Optional asyncio.Event; set to cancel.
            checkpoint_offset: Byte offset to resume from (0 = start).

        Returns:
            Dict with keys: success, terms_inserted, quads_inserted,
            elapsed_seconds, checkpoint_offset.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        from pyoxigraph import parse as ox_parse

        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        async with self._pool.acquire() as conn:
            await self._validate_tables(conn, space_id)

        # Replace mode: clear graph first
        if mode == "replace" and checkpoint_offset == 0:
            logger.info("Replace mode: clearing graph %s in space %s",
                        graph_uri, space_id)
            graph_term_uuid = _term_uuid(graph_uri, "U")
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"DELETE FROM {quad_tbl} WHERE context_uuid = $1",
                    graph_term_uuid)

        file_size = os.path.getsize(file_path)
        graph_uuid = _term_uuid(graph_uri, "U")

        # Collect terms and quads in batches, INSERT ON CONFLICT
        term_batch: List[Tuple] = []
        quad_batch: List[Tuple] = []
        total_terms_inserted = 0
        total_quads_inserted = 0
        batch_number = 0
        current_offset = 0
        t0 = time.time()

        if progress_cb:
            progress_cb(ImportProgress(
                phase="incremental_import",
                bytes_total=file_size,
                message="Starting incremental import...",
            ))

        # Ensure graph term exists
        term_batch.append((graph_uuid, graph_uri, "U", None, "primary"))

        # Document scope for blank-node labels (issues/076 facet 2).
        bnode_scope = _bnode_scope_for(graph_uri, file_path)

        # Datatypes first, for the same reason as the bulk path: the id is
        # hashed into the term uuid, so it must exist before any term is hashed
        # (`issues/157`).
        async with self._pool.acquire() as conn:
            datatype_ids = await _resolve_datatype_ids(
                conn, space_id, _scan_datatype_uris(file_path))

        with open(file_path, "rb") as f:
            if checkpoint_offset > 0:
                f.seek(checkpoint_offset)
                logger.info("Resuming from checkpoint offset %d", checkpoint_offset)

            for triple in ox_parse(f, "application/n-triples"):
                # Subject
                s_val, s_type, _, _ = _classify_node(triple.subject, bnode_scope)
                s_uuid = _term_uuid(s_val, s_type)
                term_batch.append((s_uuid, s_val, s_type, None, None, "primary"))

                # Predicate
                p_val = triple.predicate.value
                p_uuid = _term_uuid(p_val, "U")
                term_batch.append((p_uuid, p_val, "U", None, None, "primary"))

                # Object. The datatype goes into BOTH the hash and the row —
                # see `_classify_node` and `issues/157`. Dropping it here would
                # mint a uuid the bulk path and the write path never produce.
                o_val, o_type, o_lang, o_dt = _classify_node(triple.object, bnode_scope)
                o_dt_id = datatype_ids.get(o_dt)
                o_uuid = _term_uuid(o_val, o_type, lang=o_lang, datatype_id=o_dt_id)
                term_batch.append((o_uuid, o_val, o_type, o_lang, o_dt_id, "primary"))

                # Quad
                quad_batch.append((s_uuid, p_uuid, o_uuid, graph_uuid, "primary"))

                if len(quad_batch) >= batch_size:
                    await self._flush_incremental_batch(
                        term_tbl, quad_tbl, term_batch, quad_batch)
                    total_terms_inserted += len(term_batch)
                    total_quads_inserted += len(quad_batch)
                    batch_number += 1
                    current_offset = f.tell()
                    term_batch = []
                    quad_batch = []

                    # Yield to event loop
                    await asyncio.sleep(0)

                    if progress_cb:
                        elapsed = time.time() - t0
                        progress_cb(ImportProgress(
                            phase="incremental_import",
                            records_done=total_quads_inserted,
                            bytes_done=current_offset,
                            bytes_total=file_size,
                            batch_number=batch_number,
                            elapsed_seconds=elapsed,
                            rate_per_second=total_quads_inserted / elapsed if elapsed > 0 else 0,
                        ))

                    if cancel_event and cancel_event.is_set():
                        return {
                            "success": False,
                            "cancelled": True,
                            "quads_inserted": total_quads_inserted,
                            "checkpoint_offset": current_offset,
                            "checkpoint_batch": batch_number,
                        }

        # Flush remaining
        if quad_batch:
            await self._flush_incremental_batch(
                term_tbl, quad_tbl, term_batch, quad_batch)
            total_terms_inserted += len(term_batch)
            total_quads_inserted += len(quad_batch)
            batch_number += 1
            current_offset = file_size

        # Incremental aux table sync
        from vitalgraph.db.sparql_sql.sync_edge_table import resync_edge_table
        from vitalgraph.db.sparql_sql.sync_frame_entity_table import resync_frame_entity_table
        from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

        if progress_cb:
            progress_cb(ImportProgress(
                phase="resync",
                message="Syncing auxiliary tables...",
            ))

        async with self._pool.acquire() as conn:
            await resync_edge_table(conn, space_id)
            await resync_frame_entity_table(conn, space_id)
            await recompute_stats_tables(conn, space_id)

        # Register graph
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO graph (space_id, graph_uri, graph_name, created_time) "
                "VALUES ($1, $2, $3, NOW()) "
                "ON CONFLICT DO NOTHING",
                space_id, graph_uri, graph_uri,
            )

        elapsed = time.time() - t0
        if progress_cb:
            progress_cb(ImportProgress(
                phase="done",
                records_done=total_quads_inserted,
                elapsed_seconds=elapsed,
                message="Import complete",
            ))

        return {
            "success": True,
            "terms_inserted": total_terms_inserted,
            "quads_inserted": total_quads_inserted,
            "elapsed_seconds": elapsed,
            "checkpoint_offset": current_offset,
            "checkpoint_batch": batch_number,
        }

    # ------------------------------------------------------------------
    # JSONL Quads incremental import
    # ------------------------------------------------------------------

    async def import_jsonl_quads_incremental(
        self,
        space_id: str,
        graph_uri: str,
        file_path: str,
        batch_size: int = 5_000,
        mode: str = "append",
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        checkpoint_offset: int = 0,
    ) -> Dict[str, Any]:
        """Import from a JSONL file where each line is a ``{s,p,o,g}`` quad.

        Term strings use N-Quads encoding (``<uri>``, ``"lit"``,
        ``"lit"^^<dt>``, ``"lit"@lang``, ``_:bn``).

        Same checkpoint / cancel / progress semantics as
        ``import_ntriples_incremental``.
        """
        import json as _json

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        async with self._pool.acquire() as conn:
            await self._validate_tables(conn, space_id)

        # Replace mode: clear graph first
        if mode == "replace" and checkpoint_offset == 0:
            logger.info("Replace mode: clearing graph %s in space %s",
                        graph_uri, space_id)
            graph_term_uuid = _term_uuid(graph_uri, "U")
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"DELETE FROM {quad_tbl} WHERE context_uuid = $1",
                    graph_term_uuid)

        file_size = os.path.getsize(file_path)
        default_graph_uuid = _term_uuid(graph_uri, "U")
        # Blank-node labels are scoped to this document, so two files each
        # using `_:b0` describe two different nodes (issues/076 facet 2).
        bnode_scope = _bnode_scope_for(graph_uri, file_path)

        term_batch: List[Tuple] = []
        quad_batch: List[Tuple] = []
        total_terms_inserted = 0
        total_quads_inserted = 0
        batch_number = 0
        current_offset = 0
        line_number = 0
        t0 = time.time()

        if progress_cb:
            progress_cb(ImportProgress(
                phase="jsonl_import",
                bytes_total=file_size,
                message="Starting JSONL quads import...",
            ))

        # Ensure default graph term exists
        term_batch.append((default_graph_uuid, graph_uri, "U", None, "primary"))

        with open(file_path, "r", encoding="utf-8") as f:
            if checkpoint_offset > 0:
                f.seek(checkpoint_offset)
                logger.info("Resuming from checkpoint offset %d", checkpoint_offset)

            for raw_line in f:
                line_number += 1
                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                try:
                    quad = _json.loads(raw_line)
                except _json.JSONDecodeError:
                    logger.warning("Skipping invalid JSON at line %d", line_number)
                    continue

                s_str = quad.get("s", "")
                p_str = quad.get("p", "")
                o_str = quad.get("o", "")
                g_str = quad.get("g")

                # Parse N-Quads-encoded terms → (text, type, lang)
                s_text, s_type, s_lang = _parse_nquads_term_for_import(s_str, bnode_scope)
                p_text, p_type, _      = _parse_nquads_term_for_import(p_str, bnode_scope)
                o_text, o_type, o_lang = _parse_nquads_term_for_import(o_str, bnode_scope)

                s_uuid = _term_uuid(s_text, s_type, lang=s_lang)
                p_uuid = _term_uuid(p_text, p_type)
                o_uuid = _term_uuid(o_text, o_type, lang=o_lang)

                term_batch.append((s_uuid, s_text, s_type, s_lang, "primary"))
                term_batch.append((p_uuid, p_text, p_type, None, "primary"))
                term_batch.append((o_uuid, o_text, o_type, o_lang, "primary"))

                # Determine graph UUID: use per-line g if present, else default
                if g_str:
                    g_text, g_type, _ = _parse_nquads_term_for_import(g_str, bnode_scope)
                    g_uuid = _term_uuid(g_text, g_type)
                    term_batch.append((g_uuid, g_text, g_type, None, "primary"))
                else:
                    g_uuid = default_graph_uuid

                quad_batch.append((s_uuid, p_uuid, o_uuid, g_uuid, "primary"))

                if len(quad_batch) >= batch_size:
                    await self._flush_incremental_batch(
                        term_tbl, quad_tbl, term_batch, quad_batch)
                    total_terms_inserted += len(term_batch)
                    total_quads_inserted += len(quad_batch)
                    batch_number += 1
                    current_offset = f.tell()
                    term_batch = []
                    quad_batch = []

                    await asyncio.sleep(0)

                    if progress_cb:
                        elapsed = time.time() - t0
                        progress_cb(ImportProgress(
                            phase="jsonl_import",
                            records_done=total_quads_inserted,
                            bytes_done=current_offset,
                            bytes_total=file_size,
                            batch_number=batch_number,
                            elapsed_seconds=elapsed,
                            rate_per_second=total_quads_inserted / elapsed if elapsed > 0 else 0,
                        ))

                    if cancel_event and cancel_event.is_set():
                        return {
                            "success": False,
                            "cancelled": True,
                            "quads_inserted": total_quads_inserted,
                            "checkpoint_offset": current_offset,
                            "checkpoint_batch": batch_number,
                        }

        # Flush remaining
        if quad_batch:
            await self._flush_incremental_batch(
                term_tbl, quad_tbl, term_batch, quad_batch)
            total_terms_inserted += len(term_batch)
            total_quads_inserted += len(quad_batch)
            batch_number += 1
            current_offset = file_size

        # Incremental aux table sync
        from vitalgraph.db.sparql_sql.sync_edge_table import resync_edge_table
        from vitalgraph.db.sparql_sql.sync_frame_entity_table import resync_frame_entity_table
        from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

        if progress_cb:
            progress_cb(ImportProgress(
                phase="resync",
                message="Syncing auxiliary tables...",
            ))

        async with self._pool.acquire() as conn:
            await resync_edge_table(conn, space_id)
            await resync_frame_entity_table(conn, space_id)
            await recompute_stats_tables(conn, space_id)

        # Register graph
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO graph (space_id, graph_uri, graph_name, created_time) "
                "VALUES ($1, $2, $3, NOW()) "
                "ON CONFLICT DO NOTHING",
                space_id, graph_uri, graph_uri,
            )

        elapsed = time.time() - t0
        if progress_cb:
            progress_cb(ImportProgress(
                phase="done",
                records_done=total_quads_inserted,
                elapsed_seconds=elapsed,
                message="JSONL import complete",
            ))

        return {
            "success": True,
            "terms_inserted": total_terms_inserted,
            "quads_inserted": total_quads_inserted,
            "elapsed_seconds": elapsed,
            "checkpoint_offset": current_offset,
            "checkpoint_batch": batch_number,
        }

    # ------------------------------------------------------------------
    # VitalSigns Block format (.vital) incremental import
    # ------------------------------------------------------------------

    async def import_vital_block_incremental(
        self,
        space_id: str,
        graph_uri: str,
        file_path: str,
        batch_size: int = 5_000,
        mode: str = "append",
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        checkpoint_offset: int = 0,
    ) -> Dict[str, Any]:
        """Import from a VitalSigns Block file (``.vital`` / ``.vital.bz2``).

        Each block is a group of related ``GraphObject`` instances (entity +
        frames + slots + edges).  Objects are converted to quads via
        ``graphobjects_to_quad_list`` (fast property-map path, no rdflib)
        and inserted into the term/quad tables.

        ``checkpoint_offset`` here counts *blocks processed* (not bytes),
        allowing resume after cancel.
        """
        from vital_ai_vitalsigns.block.vital_block_file import VitalBlockFile
        from vital_ai_vitalsigns.block.vital_block_reader import VitalBlockReader
        from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        async with self._pool.acquire() as conn:
            await self._validate_tables(conn, space_id)

        # Replace mode: clear graph first
        if mode == "replace" and checkpoint_offset == 0:
            logger.info("Replace mode: clearing graph %s in space %s",
                        graph_uri, space_id)
            graph_term_uuid = _term_uuid(graph_uri, "U")
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"DELETE FROM {quad_tbl} WHERE context_uuid = $1",
                    graph_term_uuid)

        graph_uuid = _term_uuid(graph_uri, "U")

        term_batch: List[Tuple] = []
        quad_batch: List[Tuple] = []
        total_terms_inserted = 0
        total_quads_inserted = 0
        blocks_processed = 0
        batch_number = 0
        t0 = time.time()

        if progress_cb:
            progress_cb(ImportProgress(
                phase="vital_block_import",
                message="Starting VitalSigns Block import...",
            ))

        # Ensure graph term exists
        term_batch.append((graph_uuid, graph_uri, "U", None, "primary"))

        block_file = VitalBlockFile(file_path)
        reader = VitalBlockReader(block_file)

        for block in reader:
            blocks_processed += 1

            # Skip blocks before checkpoint
            if blocks_processed <= checkpoint_offset:
                continue

            # Convert block objects → Quad list (fast property-map path, no rdflib)
            quads = graphobjects_to_quad_list(block.objects, graph_uri)

            for quad in quads:
                s_text, s_type, s_lang = _parse_nquads_term_for_import(quad.s)
                p_text, p_type, _      = _parse_nquads_term_for_import(quad.p)
                o_text, o_type, o_lang = _parse_nquads_term_for_import(quad.o)

                s_uuid = _term_uuid(s_text, s_type, lang=s_lang)
                p_uuid = _term_uuid(p_text, p_type)
                o_uuid = _term_uuid(o_text, o_type, lang=o_lang)

                term_batch.append((s_uuid, s_text, s_type, s_lang, "primary"))
                term_batch.append((p_uuid, p_text, p_type, None, "primary"))
                term_batch.append((o_uuid, o_text, o_type, o_lang, "primary"))

                # Graph from the quad (set by graphobjects_to_quad_list)
                if quad.g:
                    g_text, g_type, _ = _parse_nquads_term_for_import(quad.g)
                    g_uuid = _term_uuid(g_text, g_type)
                    term_batch.append((g_uuid, g_text, g_type, None, "primary"))
                else:
                    g_uuid = graph_uuid

                quad_batch.append((s_uuid, p_uuid, o_uuid, g_uuid, "primary"))

            # Flush when batch is full
            if len(quad_batch) >= batch_size:
                await self._flush_incremental_batch(
                    term_tbl, quad_tbl, term_batch, quad_batch)
                total_terms_inserted += len(term_batch)
                total_quads_inserted += len(quad_batch)
                batch_number += 1
                term_batch = []
                quad_batch = []

                await asyncio.sleep(0)

                if progress_cb:
                    elapsed = time.time() - t0
                    progress_cb(ImportProgress(
                        phase="vital_block_import",
                        records_done=total_quads_inserted,
                        batch_number=batch_number,
                        elapsed_seconds=elapsed,
                        rate_per_second=total_quads_inserted / elapsed if elapsed > 0 else 0,
                        message=f"{blocks_processed} blocks, {total_quads_inserted:,} quads",
                    ))

                if cancel_event and cancel_event.is_set():
                    return {
                        "success": False,
                        "cancelled": True,
                        "quads_inserted": total_quads_inserted,
                        "checkpoint_offset": blocks_processed,
                        "checkpoint_batch": batch_number,
                    }

        # Flush remaining
        if quad_batch:
            await self._flush_incremental_batch(
                term_tbl, quad_tbl, term_batch, quad_batch)
            total_terms_inserted += len(term_batch)
            total_quads_inserted += len(quad_batch)
            batch_number += 1

        # Incremental aux table sync
        from vitalgraph.db.sparql_sql.sync_edge_table import resync_edge_table
        from vitalgraph.db.sparql_sql.sync_frame_entity_table import resync_frame_entity_table
        from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

        if progress_cb:
            progress_cb(ImportProgress(
                phase="resync",
                message="Syncing auxiliary tables...",
            ))

        async with self._pool.acquire() as conn:
            await resync_edge_table(conn, space_id)
            await resync_frame_entity_table(conn, space_id)
            await recompute_stats_tables(conn, space_id)

        # Register graph
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO graph (space_id, graph_uri, graph_name, created_time) "
                "VALUES ($1, $2, $3, NOW()) "
                "ON CONFLICT DO NOTHING",
                space_id, graph_uri, graph_uri,
            )

        elapsed = time.time() - t0
        if progress_cb:
            progress_cb(ImportProgress(
                phase="done",
                records_done=total_quads_inserted,
                elapsed_seconds=elapsed,
                message=f"Block import complete: {blocks_processed} blocks",
            ))

        return {
            "success": True,
            "terms_inserted": total_terms_inserted,
            "quads_inserted": total_quads_inserted,
            "blocks_processed": blocks_processed,
            "elapsed_seconds": elapsed,
            "checkpoint_offset": blocks_processed,
            "checkpoint_batch": batch_number,
        }

    async def _flush_incremental_batch(
        self,
        term_tbl: str,
        quad_tbl: str,
        term_batch: List[Tuple],
        quad_batch: List[Tuple],
    ) -> None:
        """INSERT ON CONFLICT a batch of terms and quads."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Deduplicate terms within the batch
                seen = set()
                unique_terms = []
                for rec in term_batch:
                    if rec[0] not in seen:
                        seen.add(rec[0])
                        unique_terms.append(rec)

                if unique_terms:
                    await conn.executemany(
                        f"INSERT INTO {term_tbl} "
                        f"(term_uuid, term_text, term_type, lang, "
                        f"datatype_id, dataset) "
                        f"VALUES ($1, $2, $3, $4, $5, $6) "
                        f"ON CONFLICT (term_uuid) DO NOTHING",
                        unique_terms,
                    )

                if quad_batch:
                    await conn.executemany(
                        f"INSERT INTO {quad_tbl} "
                        f"(subject_uuid, predicate_uuid, object_uuid, "
                        f"context_uuid, dataset) "
                        f"VALUES ($1, $2, $3, $4, $5) ",
                        quad_batch,
                    )
