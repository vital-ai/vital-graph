#!/usr/bin/env python3
"""
vitalgraphexport — Standalone CLI for exporting RDF data from VitalGraph.

Connects directly to PostgreSQL (no REST server needed) and uses the
ExportEngine from data_export_impl.py.

Usage:
    vitalgraphexport -s my_space -f dump.nt
    vitalgraphexport -s my_space -g urn:my_space:main -f dump.nq
    vitalgraphexport -s my_space -f dump.nt.gz
    vitalgraphexport -s my_space -f - --format nt  # stdout
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

async def _create_pool(config):
    """Create an asyncpg connection pool from VitalGraphConfig."""
    import asyncpg

    db_cfg = config.get_database_config()
    pool = await asyncpg.create_pool(
        host=db_cfg.get('host', 'localhost'),
        port=int(db_cfg.get('port', 5432)),
        database=db_cfg.get('database', 'vitalgraph'),
        user=db_cfg.get('username', 'vitalgraph_user'),
        password=db_cfg.get('password', 'vitalgraph_pass'),
        min_size=2,
        max_size=6,
    )
    return pool


async def _validate_space(pool, space_id: str) -> bool:
    """Check that the space exists in the admin table."""
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM space WHERE space_id = $1)", space_id)
    return bool(exists)


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------

_LAST_PRINT = 0.0


def _progress_callback(p):
    """Print progress to stderr (throttled to ~2 Hz)."""
    global _LAST_PRINT
    now = time.time()
    if now - _LAST_PRINT < 0.5 and p.phase != "done":
        return
    _LAST_PRINT = now

    if p.phase == "done":
        mb = p.bytes_written / (1024 * 1024)
        print(f"\r✅ Done: {p.records_done:,} quads exported "
              f"({mb:.1f} MB) in {p.elapsed_seconds:.1f}s",
              file=sys.stderr)
    elif p.records_total:
        pct = p.records_done / p.records_total * 100
        rate = p.rate_per_second
        mb = p.bytes_written / (1024 * 1024)
        print(f"\r  [{p.phase}] {p.records_done:,}/{p.records_total:,} "
              f"({pct:.1f}%) {rate:,.0f} rec/s  {mb:.1f} MB",
              end="", file=sys.stderr)
    else:
        print(f"\r  [{p.phase}] {p.records_done:,} records ...",
              end="", file=sys.stderr)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _detect_format(file_path: str, explicit_format: str | None) -> str:
    """Determine output format from explicit flag or file extension."""
    if explicit_format:
        return explicit_format

    lower = file_path.lower()
    if lower.endswith(".nq") or lower.endswith(".nq.gz"):
        return "nq"
    if lower.endswith(".jsonl") or lower.endswith(".jsonl.gz"):
        return "jsonl"
    if lower.endswith(".vital") or lower.endswith(".vital.bz2"):
        return "vital"
    # Default to N-Triples
    return "nt"


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------

async def _run(args: argparse.Namespace) -> int:
    from vitalgraph.config.config_loader import VitalGraphConfig
    from vitalgraph.endpoint.impl.data_export_impl import ExportEngine

    # Load config
    try:
        config = VitalGraphConfig()
    except Exception as e:
        print(f"❌ Failed to load config: {e}", file=sys.stderr)
        return 1

    # Create pool
    try:
        pool = await _create_pool(config)
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}", file=sys.stderr)
        return 1

    try:
        # Validate space
        if not await _validate_space(pool, args.space_id):
            print(f"❌ Space '{args.space_id}' not found.", file=sys.stderr)
            return 1

        file_path = args.file
        fmt = _detect_format(file_path, args.file_format)
        compress = args.compress or (file_path != "-" and file_path.endswith(".gz"))

        print(f"Space:      {args.space_id}", file=sys.stderr)
        if args.graph_uri:
            print(f"Graph:      {args.graph_uri}", file=sys.stderr)
        else:
            print(f"Graph:      (all graphs)", file=sys.stderr)
        print(f"Output:     {file_path}", file=sys.stderr)
        print(f"Format:     {fmt}", file=sys.stderr)
        print(f"Batch size: {args.batch_size:,}", file=sys.stderr)
        if compress:
            print(f"Compress:   gzip", file=sys.stderr)

        engine = ExportEngine(pool)
        cancel_event = asyncio.Event()

        # Install signal handler for graceful cancel
        import signal

        def _on_sigint(sig, frame):
            print("\n⚠️  Cancelling export...", file=sys.stderr)
            cancel_event.set()

        signal.signal(signal.SIGINT, _on_sigint)

        common_kwargs = dict(
            space_id=args.space_id,
            output_path=file_path,
            graph_uri=args.graph_uri,
            batch_size=args.batch_size,
            compress=compress,
            progress_cb=_progress_callback,
            cancel_event=cancel_event,
        )

        if fmt == "jsonl":
            result = await engine.export_jsonl_quads(**common_kwargs)
        elif fmt == "vital":
            entity_type_uri = getattr(args, 'entity_type_uri', None)
            result = await engine.export_vital_block(
                **common_kwargs, entity_type_uri=entity_type_uri)
        elif fmt == "nq":
            result = await engine.export_nquads(**common_kwargs)
        else:
            result = await engine.export_ntriples(**common_kwargs)

        print("", file=sys.stderr)  # newline after progress

        if result.get("success"):
            records = result.get("records", 0)
            elapsed = result.get("elapsed_seconds", 0)
            fsize = result.get("file_size", 0)
            mb = fsize / (1024 * 1024)
            print(f"✅ Export complete: {records:,} quads, "
                  f"{mb:.1f} MB, {elapsed:.1f}s", file=sys.stderr)
            return 0
        else:
            print(f"❌ Export failed.", file=sys.stderr)
            return 1

    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vitalgraphexport",
        description="Export RDF data from a VitalGraph space (direct PostgreSQL).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraphexport -s my_space -f dump.nt
  vitalgraphexport -s my_space -g urn:my_space:main -f dump.nq
  vitalgraphexport -s my_space -f dump.nt.gz
  vitalgraphexport -s my_space -f - --format nt   # write to stdout
""",
    )

    parser.add_argument(
        "--space-id", "-s", required=True,
        help="Source space ID")
    parser.add_argument(
        "--graph-uri", "-g", default=None,
        help="Export only this graph URI (default: all graphs)")
    parser.add_argument(
        "--file", "-f", required=True,
        help="Output file path. Use '-' for stdout.")
    parser.add_argument(
        "--format", dest="file_format", default=None,
        choices=["nt", "nq", "jsonl", "vital"],
        help="Output format (default: auto-detect from extension, fallback nt)")
    parser.add_argument(
        "--batch-size", "-b", type=int, default=50_000,
        help="Rows per cursor fetch (default: 50000)")
    parser.add_argument(
        "--entity-type-uri", default=None,
        help="(vital format only) Filter by KG entity type URI")
    parser.add_argument(
        "--compress", "-z", action="store_true",
        help="Gzip output (auto if file ends in .gz)")
    parser.add_argument(
        "--config", "-c", default=None,
        help="Ignored (config loaded from environment variables)")

    return parser.parse_args()


def main():
    args = parse_args()
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
