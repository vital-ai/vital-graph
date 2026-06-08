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


def _classify_node(node) -> Tuple[str, str, Optional[str]]:
    """Classify a pyoxigraph triple node into (value, term_type, lang)."""
    cls_name = type(node).__name__
    if cls_name == "Literal":
        lang = str(node.language) if node.language else None
        return node.value, "L", lang
    elif cls_name == "BlankNode":
        return node.value, "B", None
    else:
        return node.value, "U", None


def _unescape_nquads_string(s: str) -> str:
    """Unescape N-Quads string escape sequences."""
    return (s
            .replace('\\r', '\r')
            .replace('\\n', '\n')
            .replace('\\"', '"')
            .replace('\\\\', '\\'))


def _parse_nquads_term_for_import(term_str: str) -> Tuple[str, str, Optional[str]]:
    """Parse an N-Quads-encoded term into (text, term_type, lang).

    Returns values matching the term table schema:
      ``<http://...>``                → (``http://...``, ``"U"``, None)
      ``_:label``                     → (``label``,      ``"B"``, None)
      ``"value"``                     → (``value``,      ``"L"``, None)
      ``"value"^^<http://...>``       → (``value``,      ``"L"``, None)
      ``"value"@en``                  → (``value``,      ``"L"``, ``"en"``)
    """
    term_str = term_str.strip()

    # URI
    if term_str.startswith('<') and term_str.endswith('>'):
        return term_str[1:-1], "U", None

    # Blank node
    if term_str.startswith('_:'):
        return term_str[2:], "B", None

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

        engine = ImportEngine(pool)
        result = await engine.import_ntriples_bulk(
            space_id="my_space",
            graph_uri="urn:my_space:main",
            file_path="/data/dump.nt",
        )
    """

    def __init__(self, pool):
        """
        Args:
            pool: asyncpg connection pool.
        """
        self._pool = pool

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
                              ) -> Tuple[Dict[Tuple, str], int]:
        """Pass 1: Parse N-Triples file and collect unique terms with UUIDs.

        Returns:
            (terms_dict, triple_count) where terms_dict maps
            (text, type, lang) -> uuid_str.
        """
        from pyoxigraph import parse as ox_parse

        terms: Dict[Tuple, str] = {}
        triple_count = 0
        file_size = os.path.getsize(file_path)
        t0 = time.time()

        def ensure(text: str, ttype: str, lang: Optional[str] = None) -> str:
            key = (text, ttype, lang)
            if key not in terms:
                terms[key] = _term_uuid(text, ttype, lang=lang)
            return terms[key]

        # Pre-register graph URI
        ensure(graph_uri, "U")

        with open(file_path, "rb") as f:
            for triple in ox_parse(f, "application/n-triples"):
                s_val, s_type, _ = _classify_node(triple.subject)
                ensure(s_val, s_type)
                ensure(triple.predicate.value, "U")
                o_val, o_type, o_lang = _classify_node(triple.object)
                ensure(o_val, o_type, o_lang)
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
        terms, triple_count = self._parse_ntriples_terms(
            file_path, graph_uri, progress_cb)
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
            (uid, text, ttype, lang, "primary")
            for (text, ttype, lang), uid in terms.items()
        ]
        async with self._pool.acquire() as conn:
            await conn.copy_records_to_table(
                term_tbl,
                columns=["term_uuid", "term_text", "term_type", "lang", "dataset"],
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

        graph_uuid = terms[(graph_uri, "U", None)]
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

        with open(file_path, "rb") as f:
            for triple in ox_parse(f, "application/n-triples"):
                s_val, s_type, _ = _classify_node(triple.subject)
                s_uuid = terms[(s_val, s_type, None)]
                p_uuid = terms[(triple.predicate.value, "U", None)]
                o_val, o_type, o_lang = _classify_node(triple.object)
                o_uuid = terms[(o_val, o_type, o_lang)]

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

        with open(file_path, "rb") as f:
            if checkpoint_offset > 0:
                f.seek(checkpoint_offset)
                logger.info("Resuming from checkpoint offset %d", checkpoint_offset)

            for triple in ox_parse(f, "application/n-triples"):
                # Subject
                s_val, s_type, _ = _classify_node(triple.subject)
                s_uuid = _term_uuid(s_val, s_type)
                term_batch.append((s_uuid, s_val, s_type, None, "primary"))

                # Predicate
                p_val = triple.predicate.value
                p_uuid = _term_uuid(p_val, "U")
                term_batch.append((p_uuid, p_val, "U", None, "primary"))

                # Object
                o_val, o_type, o_lang = _classify_node(triple.object)
                o_uuid = _term_uuid(o_val, o_type, lang=o_lang)
                term_batch.append((o_uuid, o_val, o_type, o_lang, "primary"))

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
        from vitalgraph.db.sparql_sql.sync_stats_tables import resync_stats_tables

        if progress_cb:
            progress_cb(ImportProgress(
                phase="resync",
                message="Syncing auxiliary tables...",
            ))

        async with self._pool.acquire() as conn:
            await resync_edge_table(conn, space_id)
            await resync_frame_entity_table(conn, space_id)
            await resync_stats_tables(conn, space_id)

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
                s_text, s_type, s_lang = _parse_nquads_term_for_import(s_str)
                p_text, p_type, _      = _parse_nquads_term_for_import(p_str)
                o_text, o_type, o_lang = _parse_nquads_term_for_import(o_str)

                s_uuid = _term_uuid(s_text, s_type, lang=s_lang)
                p_uuid = _term_uuid(p_text, p_type)
                o_uuid = _term_uuid(o_text, o_type, lang=o_lang)

                term_batch.append((s_uuid, s_text, s_type, s_lang, "primary"))
                term_batch.append((p_uuid, p_text, p_type, None, "primary"))
                term_batch.append((o_uuid, o_text, o_type, o_lang, "primary"))

                # Determine graph UUID: use per-line g if present, else default
                if g_str:
                    g_text, g_type, _ = _parse_nquads_term_for_import(g_str)
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
        from vitalgraph.db.sparql_sql.sync_stats_tables import resync_stats_tables

        if progress_cb:
            progress_cb(ImportProgress(
                phase="resync",
                message="Syncing auxiliary tables...",
            ))

        async with self._pool.acquire() as conn:
            await resync_edge_table(conn, space_id)
            await resync_frame_entity_table(conn, space_id)
            await resync_stats_tables(conn, space_id)

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
        from vitalgraph.db.sparql_sql.sync_stats_tables import resync_stats_tables

        if progress_cb:
            progress_cb(ImportProgress(
                phase="resync",
                message="Syncing auxiliary tables...",
            ))

        async with self._pool.acquire() as conn:
            await resync_edge_table(conn, space_id)
            await resync_frame_entity_table(conn, space_id)
            await resync_stats_tables(conn, space_id)

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
                        f"(term_uuid, term_text, term_type, lang, dataset) "
                        f"VALUES ($1, $2, $3, $4, $5) "
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
