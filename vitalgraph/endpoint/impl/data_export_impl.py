"""
Export engine for VitalGraph sparql_sql backend.

Exports RDF data from PostgreSQL quad tables to N-Triples or N-Quads format.
Supports single-graph and all-graphs-in-space export modes.

Uses server-side cursors for memory-efficient streaming of large datasets.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TextIO

logger = logging.getLogger(__name__)


@dataclass
class ExportProgress:
    """Snapshot of export progress."""
    phase: str = "init"
    records_done: int = 0
    records_total: int = 0
    bytes_written: int = 0
    elapsed_seconds: float = 0.0
    rate_per_second: float = 0.0
    message: str = ""


ProgressCallback = Callable[[ExportProgress], None]


# N-Triples / N-Quads serialisation helpers

def _escape_ntriples(value: str) -> str:
    """Escape a string for N-Triples literal representation."""
    return (value
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t"))


def _format_term_nt(text: str, term_type: str, lang: Optional[str]) -> str:
    """Format a term for N-Triples output."""
    if term_type == "U":
        return f"<{text}>"
    elif term_type == "B":
        return f"_:{text}"
    elif term_type == "L":
        escaped = _escape_ntriples(text)
        if lang:
            return f'"{escaped}"@{lang}'
        return f'"{escaped}"'
    else:
        return f"<{text}>"


def _format_term_nquads(text: str, term_type: str, lang: Optional[str]) -> str:
    """Format a term for N-Quads / JSONL output (same encoding as _format_term_nt)."""
    if term_type == "U":
        return f"<{text}>"
    elif term_type == "B":
        return f"_:{text}"
    elif term_type == "L":
        escaped = _escape_ntriples(text)
        if lang:
            return f'"{escaped}"@{lang}'
        return f'"{escaped}"'
    else:
        return f"<{text}>"


class ExportEngine:
    """Core export engine for sparql_sql backend.

    Usage::

        engine = ExportEngine(pool)
        result = await engine.export_ntriples(
            space_id="my_space",
            graph_uri="urn:my_space:main",
            output_path="/data/dump.nt",
        )
    """

    def __init__(self, pool):
        """
        Args:
            pool: asyncpg connection pool.
        """
        self._pool = pool

    @staticmethod
    def _get_table_names(space_id: str) -> Dict[str, str]:
        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        return SparqlSQLSchema.get_table_names(space_id)

    async def _validate_tables(self, conn, space_id: str) -> None:
        """Check that per-space tables exist."""
        t = self._get_table_names(space_id)
        for tbl_name in (t['term'], t['rdf_quad']):
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=$1)", tbl_name)
            if not exists:
                raise RuntimeError(
                    f"Table {tbl_name} does not exist. "
                    f"Create the space first.")

    async def _count_quads(self, conn, quad_tbl: str,
                           context_uuid: Optional[str] = None) -> int:
        """Count quads, optionally filtered by graph (context_uuid)."""
        if context_uuid:
            return await conn.fetchval(
                f"SELECT COUNT(*) FROM {quad_tbl} WHERE context_uuid = $1",
                context_uuid)
        return await conn.fetchval(f"SELECT COUNT(*) FROM {quad_tbl}")

    # ------------------------------------------------------------------
    # N-Triples export
    # ------------------------------------------------------------------

    async def export_ntriples(
        self,
        space_id: str,
        output_path: str,
        graph_uri: Optional[str] = None,
        batch_size: int = 50_000,
        compress: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Export quads as N-Triples to a file.

        Args:
            space_id: Source space.
            output_path: Output file path.  Use "-" for stdout.
            graph_uri: If set, export only this graph. Otherwise all graphs.
            batch_size: Rows per cursor fetch.
            compress: If True, gzip the output.
            progress_cb: Optional progress callback.
            cancel_event: Optional asyncio.Event; set to cancel export.

        Returns:
            Dict with keys: success, records, file_size, elapsed_seconds.
        """
        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        async with self._pool.acquire() as conn:
            await self._validate_tables(conn, space_id)

        # Resolve graph UUID if filtering by graph
        context_uuid = None
        if graph_uri:
            from vitalgraph.endpoint.impl.data_import_impl import _term_uuid
            context_uuid = _term_uuid(graph_uri, "U")

        # Count total for progress reporting
        async with self._pool.acquire() as conn:
            total_quads = await self._count_quads(conn, quad_tbl, context_uuid)

        if progress_cb:
            progress_cb(ExportProgress(
                phase="export",
                records_total=total_quads,
                message=f"Exporting {total_quads:,} quads...",
            ))

        # Build the export query — join quads with term table to resolve UUIDs
        # to text values
        query = f"""
            SELECT
                st.term_text AS s_text, st.term_type AS s_type, st.lang AS s_lang,
                pt.term_text AS p_text,
                ot.term_text AS o_text, ot.term_type AS o_type, ot.lang AS o_lang,
                ct.term_text AS c_text
            FROM {quad_tbl} q
            JOIN {term_tbl} st ON st.term_uuid = q.subject_uuid
            JOIN {term_tbl} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_tbl} ot ON ot.term_uuid = q.object_uuid
            JOIN {term_tbl} ct ON ct.term_uuid = q.context_uuid
        """
        params: List[Any] = []
        if context_uuid:
            query += " WHERE q.context_uuid = $1"
            params.append(context_uuid)

        records_written = 0
        bytes_written = 0
        t0 = time.time()

        # Determine output mode
        use_stdout = (output_path == "-")
        auto_compress = compress or (not use_stdout and output_path.endswith(".gz"))

        if use_stdout:
            import sys
            records_written, bytes_written = await self._stream_ntriples_to_file(
                query, params, sys.stdout, batch_size, total_quads,
                progress_cb, cancel_event, t0,
            )
        elif auto_compress:
            with gzip.open(output_path, "wt") as f:
                records_written, bytes_written = await self._stream_ntriples_to_file(
                    query, params, f, batch_size, total_quads,
                    progress_cb, cancel_event, t0,
                )
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                records_written, bytes_written = await self._stream_ntriples_to_file(
                    query, params, f, batch_size, total_quads,
                    progress_cb, cancel_event, t0,
                )

        elapsed = time.time() - t0
        file_size = 0
        if not use_stdout and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)

        if progress_cb:
            progress_cb(ExportProgress(
                phase="done",
                records_done=records_written,
                records_total=total_quads,
                bytes_written=file_size,
                elapsed_seconds=elapsed,
                message="Export complete",
            ))

        return {
            "success": True,
            "records": records_written,
            "file_size": file_size,
            "elapsed_seconds": elapsed,
        }

    async def _stream_ntriples_to_file(
        self,
        query: str,
        params: List[Any],
        f: TextIO,
        batch_size: int,
        total_quads: int,
        progress_cb: Optional[ProgressCallback],
        cancel_event: Optional[asyncio.Event],
        t0: float,
    ) -> tuple[int, int]:
        """Stream N-Triples rows to a file handle using cursor-based fetch."""
        records_written = 0
        bytes_written = 0

        async with self._pool.acquire() as conn:
            # Use a transaction for server-side cursor
            async with conn.transaction():
                cursor = await conn.cursor(query, *params)

                while True:
                    rows = await cursor.fetch(batch_size)
                    if not rows:
                        break

                    lines = []
                    for row in rows:
                        s = _format_term_nt(row['s_text'], row['s_type'], row['s_lang'])
                        p = f"<{row['p_text']}>"
                        o = _format_term_nt(row['o_text'], row['o_type'], row['o_lang'])
                        lines.append(f"{s} {p} {o} .\n")

                    chunk = "".join(lines)
                    f.write(chunk)
                    records_written += len(rows)
                    bytes_written += len(chunk.encode("utf-8"))

                    if progress_cb:
                        elapsed = time.time() - t0
                        progress_cb(ExportProgress(
                            phase="export",
                            records_done=records_written,
                            records_total=total_quads,
                            bytes_written=bytes_written,
                            elapsed_seconds=elapsed,
                            rate_per_second=records_written / elapsed if elapsed > 0 else 0,
                        ))

                    if cancel_event and cancel_event.is_set():
                        return records_written, bytes_written

                    # Yield to event loop
                    await asyncio.sleep(0)

        return records_written, bytes_written

    # ------------------------------------------------------------------
    # N-Quads export (includes graph URI)
    # ------------------------------------------------------------------

    async def export_nquads(
        self,
        space_id: str,
        output_path: str,
        graph_uri: Optional[str] = None,
        batch_size: int = 50_000,
        compress: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Export quads as N-Quads (includes graph URI in each line).

        Same interface as export_ntriples but output format includes the
        graph context: ``<s> <p> <o> <g> .``
        """
        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        async with self._pool.acquire() as conn:
            await self._validate_tables(conn, space_id)

        context_uuid = None
        if graph_uri:
            from vitalgraph.endpoint.impl.data_import_impl import _term_uuid
            context_uuid = _term_uuid(graph_uri, "U")

        async with self._pool.acquire() as conn:
            total_quads = await self._count_quads(conn, quad_tbl, context_uuid)

        if progress_cb:
            progress_cb(ExportProgress(
                phase="export",
                records_total=total_quads,
                message=f"Exporting {total_quads:,} quads as N-Quads...",
            ))

        query = f"""
            SELECT
                st.term_text AS s_text, st.term_type AS s_type, st.lang AS s_lang,
                pt.term_text AS p_text,
                ot.term_text AS o_text, ot.term_type AS o_type, ot.lang AS o_lang,
                ct.term_text AS c_text
            FROM {quad_tbl} q
            JOIN {term_tbl} st ON st.term_uuid = q.subject_uuid
            JOIN {term_tbl} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_tbl} ot ON ot.term_uuid = q.object_uuid
            JOIN {term_tbl} ct ON ct.term_uuid = q.context_uuid
        """
        params: List[Any] = []
        if context_uuid:
            query += " WHERE q.context_uuid = $1"
            params.append(context_uuid)

        records_written = 0
        bytes_written = 0
        t0 = time.time()

        auto_compress = compress or output_path.endswith(".gz")

        if auto_compress:
            f_ctx = gzip.open(output_path, "wt")
        else:
            f_ctx = open(output_path, "w", encoding="utf-8")

        with f_ctx as f:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    cursor = await conn.cursor(query, *params)

                    while True:
                        rows = await cursor.fetch(batch_size)
                        if not rows:
                            break

                        lines = []
                        for row in rows:
                            s = _format_term_nt(row['s_text'], row['s_type'], row['s_lang'])
                            p = f"<{row['p_text']}>"
                            o = _format_term_nt(row['o_text'], row['o_type'], row['o_lang'])
                            g = f"<{row['c_text']}>"
                            lines.append(f"{s} {p} {o} {g} .\n")

                        chunk = "".join(lines)
                        f.write(chunk)
                        records_written += len(rows)
                        bytes_written += len(chunk.encode("utf-8"))

                        if progress_cb:
                            elapsed = time.time() - t0
                            progress_cb(ExportProgress(
                                phase="export",
                                records_done=records_written,
                                records_total=total_quads,
                                bytes_written=bytes_written,
                                elapsed_seconds=elapsed,
                                rate_per_second=records_written / elapsed if elapsed > 0 else 0,
                            ))

                        if cancel_event and cancel_event.is_set():
                            break

                        await asyncio.sleep(0)

        elapsed = time.time() - t0
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

        if progress_cb:
            progress_cb(ExportProgress(
                phase="done",
                records_done=records_written,
                records_total=total_quads,
                bytes_written=file_size,
                elapsed_seconds=elapsed,
                message="N-Quads export complete",
            ))

        return {
            "success": True,
            "records": records_written,
            "file_size": file_size,
            "elapsed_seconds": elapsed,
        }

    # ------------------------------------------------------------------
    # JSONL Quads export
    # ------------------------------------------------------------------

    async def export_jsonl_quads(
        self,
        space_id: str,
        output_path: str,
        graph_uri: Optional[str] = None,
        batch_size: int = 50_000,
        compress: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Export quads as JSONL where each line is ``{"s":..,"p":..,"o":..,"g":..}``.

        Term encoding follows N-Quads rules (same as the REST API wire format).

        Same interface as ``export_ntriples`` / ``export_nquads``.
        """
        import json as _json

        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        async with self._pool.acquire() as conn:
            await self._validate_tables(conn, space_id)

        context_uuid = None
        if graph_uri:
            from vitalgraph.endpoint.impl.data_import_impl import _term_uuid
            context_uuid = _term_uuid(graph_uri, "U")

        async with self._pool.acquire() as conn:
            total_quads = await self._count_quads(conn, quad_tbl, context_uuid)

        if progress_cb:
            progress_cb(ExportProgress(
                phase="export",
                records_total=total_quads,
                message=f"Exporting {total_quads:,} quads as JSONL...",
            ))

        query = f"""
            SELECT
                st.term_text AS s_text, st.term_type AS s_type, st.lang AS s_lang,
                pt.term_text AS p_text,
                ot.term_text AS o_text, ot.term_type AS o_type, ot.lang AS o_lang,
                ct.term_text AS c_text
            FROM {quad_tbl} q
            JOIN {term_tbl} st ON st.term_uuid = q.subject_uuid
            JOIN {term_tbl} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_tbl} ot ON ot.term_uuid = q.object_uuid
            JOIN {term_tbl} ct ON ct.term_uuid = q.context_uuid
        """
        params: List[Any] = []
        if context_uuid:
            query += " WHERE q.context_uuid = $1"
            params.append(context_uuid)

        records_written = 0
        bytes_written = 0
        t0 = time.time()

        auto_compress = compress or output_path.endswith(".gz")

        if auto_compress:
            f_ctx = gzip.open(output_path, "wt")
        else:
            f_ctx = open(output_path, "w", encoding="utf-8")

        with f_ctx as f:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    cursor = await conn.cursor(query, *params)

                    while True:
                        rows = await cursor.fetch(batch_size)
                        if not rows:
                            break

                        lines = []
                        for row in rows:
                            s = _format_term_nquads(row['s_text'], row['s_type'], row['s_lang'])
                            p = f"<{row['p_text']}>"
                            o = _format_term_nquads(row['o_text'], row['o_type'], row['o_lang'])
                            g = f"<{row['c_text']}>"
                            line = _json.dumps({"s": s, "p": p, "o": o, "g": g},
                                               ensure_ascii=False, separators=(',', ':'))
                            lines.append(line + "\n")

                        chunk = "".join(lines)
                        f.write(chunk)
                        records_written += len(rows)
                        bytes_written += len(chunk.encode("utf-8"))

                        if progress_cb:
                            elapsed = time.time() - t0
                            progress_cb(ExportProgress(
                                phase="export",
                                records_done=records_written,
                                records_total=total_quads,
                                bytes_written=bytes_written,
                                elapsed_seconds=elapsed,
                                rate_per_second=records_written / elapsed if elapsed > 0 else 0,
                            ))

                        if cancel_event and cancel_event.is_set():
                            break

                        await asyncio.sleep(0)

        elapsed = time.time() - t0
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

        if progress_cb:
            progress_cb(ExportProgress(
                phase="done",
                records_done=records_written,
                records_total=total_quads,
                bytes_written=file_size,
                elapsed_seconds=elapsed,
                message="JSONL export complete",
            ))

        return {
            "success": True,
            "records": records_written,
            "file_size": file_size,
            "elapsed_seconds": elapsed,
        }

    # ------------------------------------------------------------------
    # VitalSigns Block format (.vital) export
    # ------------------------------------------------------------------

    HAS_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI'

    HAS_KG_ENTITY_TYPE = 'http://vital.ai/ontology/haley-ai-kg#hasKGEntityType'

    async def export_vital_block(
        self,
        space_id: str,
        output_path: str,
        graph_uri: Optional[str] = None,
        entity_type_uri: Optional[str] = None,
        batch_size: int = 50_000,
        compress: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Export KG entities as a VitalSigns Block file (``.vital``).

        Only objects that belong to a KG entity (i.e. have a
        ``hasKGGraphURI`` predicate) are exported.  Quads are fetched
        ordered by grouping URI so all members of a logical entity graph
        (entity + frames + slots + edges) stream together and are
        written into a single ``VitalBlock`` for round-trip import.

        Args:
            space_id: Space to export from.
            output_path: Path to write the ``.vital`` file.
            graph_uri: Optional graph URI filter.
            entity_type_uri: Optional KG entity type filter — only export
                entities whose ``hasKGEntityType`` matches this URI.
            batch_size: Cursor fetch size.
            compress: Not yet used (reserved for bz2).
            progress_cb: Progress callback.
            cancel_event: Cooperative cancellation event.
        """
        from vital_ai_vitalsigns.block.vital_block import VitalBlock
        from vital_ai_vitalsigns.block.vital_block_file import VitalBlockFile
        from vital_ai_vitalsigns.block.vital_block_writer import VitalBlockWriter
        from vitalgraph.model.quad_model import Quad
        from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects

        t = self._get_table_names(space_id)
        term_tbl = t['term']
        quad_tbl = t['rdf_quad']

        async with self._pool.acquire() as conn:
            await self._validate_tables(conn, space_id)

        from vitalgraph.endpoint.impl.data_import_impl import _term_uuid

        context_uuid = None
        if graph_uri:
            context_uuid = _term_uuid(graph_uri, "U")

        # Predicate UUID for hasKGGraphURI — used to find the grouping URI
        grouping_pred_uuid = _term_uuid(self.HAS_KG_GRAPH_URI, "U")

        async with self._pool.acquire() as conn:
            total_quads = await self._count_quads(conn, quad_tbl, context_uuid)

        if progress_cb:
            progress_cb(ExportProgress(
                phase="export",
                records_total=total_quads,
                message=f"Exporting quads as .vital blocks...",
            ))

        # Build WHERE conditions
        conditions: List[str] = []
        params: List[Any] = [grouping_pred_uuid]
        param_idx = 2

        if context_uuid:
            conditions.append(f"q.context_uuid = ${param_idx}")
            params.append(context_uuid)
            param_idx += 1

        # Optional entity type filter: restrict to grouping URIs (entities)
        # that have hasKGEntityType = <entity_type_uri>
        type_join = ""
        if entity_type_uri:
            type_pred_uuid = _term_uuid(self.HAS_KG_ENTITY_TYPE, "U")
            type_obj_uuid = _term_uuid(entity_type_uri, "U")
            type_join = f"""
            JOIN {quad_tbl} tq
                ON tq.subject_uuid = gq.object_uuid
                AND tq.predicate_uuid = ${param_idx}
                AND tq.object_uuid = ${param_idx + 1}
            """
            params.extend([type_pred_uuid, type_obj_uuid])
            param_idx += 2

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT
                st.term_text AS s_text, st.term_type AS s_type, st.lang AS s_lang,
                pt.term_text AS p_text,
                ot.term_text AS o_text, ot.term_type AS o_type, ot.lang AS o_lang,
                ct.term_text AS c_text,
                grp_t.term_text AS grouping_uri
            FROM {quad_tbl} q
            JOIN {term_tbl} st ON st.term_uuid = q.subject_uuid
            JOIN {term_tbl} pt ON pt.term_uuid = q.predicate_uuid
            JOIN {term_tbl} ot ON ot.term_uuid = q.object_uuid
            JOIN {term_tbl} ct ON ct.term_uuid = q.context_uuid
            JOIN {quad_tbl} gq
                ON gq.subject_uuid = q.subject_uuid
                AND gq.predicate_uuid = $1
            JOIN {term_tbl} grp_t ON grp_t.term_uuid = gq.object_uuid
            {type_join}
            {where_clause}
            ORDER BY gq.object_uuid, q.subject_uuid
        """

        records_written = 0
        blocks_written = 0
        t0 = time.time()

        block_file = VitalBlockFile(output_path)
        writer = VitalBlockWriter(block_file)
        writer.write_header()

        # Buffer quads for the current grouping URI
        current_grouping: Optional[str] = None
        group_quads: List[Quad] = []

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.cursor(query, *params)

                while True:
                    rows = await cursor.fetch(batch_size)
                    if not rows:
                        break

                    for row in rows:
                        grouping = row['grouping_uri']
                        s_nq = _format_term_nquads(row['s_text'], row['s_type'], row['s_lang'])

                        # When grouping URI changes, flush the previous group
                        if current_grouping is not None and grouping != current_grouping:
                            blocks_written += self._flush_group_block(
                                writer, group_quads, quad_list_to_graphobjects)
                            group_quads = []

                        current_grouping = grouping

                        p_nq = f"<{row['p_text']}>"
                        o_nq = _format_term_nquads(row['o_text'], row['o_type'], row['o_lang'])
                        g_nq = f"<{row['c_text']}>"
                        group_quads.append(Quad(s=s_nq, p=p_nq, o=o_nq, g=g_nq))

                    records_written += len(rows)

                    if progress_cb:
                        elapsed = time.time() - t0
                        progress_cb(ExportProgress(
                            phase="export",
                            records_done=records_written,
                            records_total=total_quads,
                            elapsed_seconds=elapsed,
                            rate_per_second=records_written / elapsed if elapsed > 0 else 0,
                        ))

                    if cancel_event and cancel_event.is_set():
                        break

                    await asyncio.sleep(0)

        # Flush last group
        if group_quads:
            blocks_written += self._flush_group_block(
                writer, group_quads, quad_list_to_graphobjects)

        writer.close()

        elapsed = time.time() - t0
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

        if progress_cb:
            progress_cb(ExportProgress(
                phase="done",
                records_done=records_written,
                records_total=total_quads,
                bytes_written=file_size,
                elapsed_seconds=elapsed,
                message=f"Block export complete: {blocks_written} blocks",
            ))

        return {
            "success": True,
            "records": records_written,
            "blocks": blocks_written,
            "file_size": file_size,
            "elapsed_seconds": elapsed,
        }

    @staticmethod
    def _flush_group_block(writer, quads, quad_list_to_graphobjects_fn) -> int:
        """Convert all quads for a grouping URI → GraphObjects → one block.

        All objects sharing the same ``hasKGGraphURI`` are written as a
        single ``VitalBlock``, preserving the logical entity graph
        grouping for round-trip import.

        Returns 1 on success (one block written), 0 on failure.
        """
        from vital_ai_vitalsigns.block.vital_block import VitalBlock

        try:
            graph_objects = quad_list_to_graphobjects_fn(quads)
            if graph_objects:
                block = VitalBlock(graph_objects)
                writer.write_block(block)
                return 1
            return 0
        except Exception as e:
            logger.warning("Failed to convert group to VitalBlock: %s", e)
            return 0
