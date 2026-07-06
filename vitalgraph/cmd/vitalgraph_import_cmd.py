#!/usr/bin/env python3
"""
vitalgraphimport — Standalone CLI for importing RDF data into VitalGraph.

Connects directly to PostgreSQL (no REST server needed) and uses the
ImportEngine from data_import_impl.py.

Usage:
    vitalgraphimport -s my_space -f data.nt
    vitalgraphimport -s my_space -g urn:my_space:main -f data.nt --mode bulk
    vitalgraphimport -s my_space -f data.nt.gz --batch-size 100000
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
    if now - _LAST_PRINT < 0.5 and p.phase not in ("done", "resync", "register"):
        return
    _LAST_PRINT = now

    if p.phase == "done":
        print(f"\r✅ Done: {p.records_done:,} quads imported in "
              f"{p.elapsed_seconds:.1f}s", file=sys.stderr)
    elif p.records_total:
        pct = p.records_done / p.records_total * 100
        rate = p.rate_per_second
        print(f"\r  [{p.phase}] {p.records_done:,}/{p.records_total:,} "
              f"({pct:.1f}%) {rate:,.0f} rec/s",
              end="", file=sys.stderr)
    else:
        print(f"\r  [{p.phase}] {p.records_done:,} records ...",
              end="", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------

async def _run(args: argparse.Namespace) -> int:
    from vitalgraph.config.config_loader import VitalGraphConfig
    from vitalgraph.endpoint.impl.data_import_impl import ImportEngine

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
            print(f"❌ Space '{args.space_id}' not found. "
                  f"Create it first with vitalgraphadmin.", file=sys.stderr)
            return 1

        # Resolve graph URI
        graph_uri = args.graph_uri or f"urn:{args.space_id}"

        # Resolve file path
        file_path = args.file
        if not os.path.isfile(file_path):
            print(f"❌ File not found: {file_path}", file=sys.stderr)
            return 1

        file_size = os.path.getsize(file_path)

        # Detect format
        fmt = args.file_format
        if not fmt:
            lower = file_path.lower()
            if lower.endswith(".jsonl") or lower.endswith(".jsonl.gz"):
                fmt = "jsonl"
            elif lower.endswith(".vital") or lower.endswith(".vital.bz2"):
                fmt = "vital"
            else:
                fmt = "nt"

        print(f"Space:      {args.space_id}", file=sys.stderr)
        print(f"Graph:      {graph_uri}", file=sys.stderr)
        print(f"File:       {file_path} ({file_size:,} bytes)", file=sys.stderr)
        print(f"Format:     {fmt}", file=sys.stderr)
        print(f"Mode:       {args.mode}", file=sys.stderr)
        print(f"Batch size: {args.batch_size:,}", file=sys.stderr)

        if args.dry_run:
            print("🔍 Dry run — no data will be written.", file=sys.stderr)
            return 0

        engine = ImportEngine(pool)
        cancel_event = asyncio.Event()

        # Install signal handler for graceful cancel
        import signal

        def _on_sigint(sig, frame):
            print("\n⚠️  Cancelling import...", file=sys.stderr)
            cancel_event.set()

        signal.signal(signal.SIGINT, _on_sigint)

        if fmt == "jsonl":
            result = await engine.import_jsonl_quads_incremental(
                space_id=args.space_id,
                graph_uri=graph_uri,
                file_path=file_path,
                batch_size=args.batch_size,
                mode=args.replace_mode,
                progress_cb=_progress_callback,
                cancel_event=cancel_event,
            )
        elif fmt == "vital":
            result = await engine.import_vital_block_incremental(
                space_id=args.space_id,
                graph_uri=graph_uri,
                file_path=file_path,
                batch_size=args.batch_size,
                mode=args.replace_mode,
                progress_cb=_progress_callback,
                cancel_event=cancel_event,
            )
        elif args.mode == "bulk":
            result = await engine.import_ntriples_bulk(
                space_id=args.space_id,
                graph_uri=graph_uri,
                file_path=file_path,
                batch_size=args.batch_size,
                progress_cb=_progress_callback,
                cancel_event=cancel_event,
            )
        else:
            result = await engine.import_ntriples_incremental(
                space_id=args.space_id,
                graph_uri=graph_uri,
                file_path=file_path,
                batch_size=args.batch_size,
                mode=args.replace_mode,
                progress_cb=_progress_callback,
                cancel_event=cancel_event,
            )

        print("", file=sys.stderr)  # newline after progress

        if result.get("cancelled"):
            print("⚠️  Import cancelled.", file=sys.stderr)
            return 2
        elif result.get("success"):
            quads = result.get("quads", result.get("records", 0))
            elapsed = result.get("elapsed_seconds", 0)
            print(f"✅ Import complete: {quads:,} quads in {elapsed:.1f}s",
                  file=sys.stderr)
            # Nudge the backfill task (if running) so it stamps
            # server-managed properties on newly imported entities.
            try:
                async with pool.acquire() as conn:
                    await conn.execute("NOTIFY vitalgraph_backfill_nudge")
            except Exception:
                pass  # best-effort; backfill safety-net poll will catch up
            return 0
        else:
            print(f"❌ Import failed: {result.get('error', 'Unknown error')}",
                  file=sys.stderr)
            return 1

    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vitalgraphimport",
        description="Import RDF data into a VitalGraph space (direct PostgreSQL).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraphimport -s my_space -f data.nt
  vitalgraphimport -s my_space -g urn:my_space:main -f data.nt --mode bulk
  vitalgraphimport -s my_space -f data.nt.gz --batch-size 100000
  vitalgraphimport -s my_space -f data.nt --mode incremental --replace-mode replace
""",
    )

    parser.add_argument(
        "--space-id", "-s", required=True,
        help="Target space ID (must already exist)")
    parser.add_argument(
        "--graph-uri", "-g", default=None,
        help="Target graph URI (default: urn:{space_id})")
    parser.add_argument(
        "--file", "-f", required=True,
        help="Path to input file (.nt, .nt.gz)")
    parser.add_argument(
        "--format", dest="file_format", default=None,
        choices=["nt", "nq", "ttl", "jsonl"],
        help="File format (default: auto-detect from extension)")
    parser.add_argument(
        "--batch-size", "-b", type=int, default=50_000,
        help="Records per batch (default: 50000)")
    parser.add_argument(
        "--mode", default="bulk",
        choices=["bulk", "incremental"],
        help="Import strategy: bulk (COPY + index drop) or incremental (INSERT ON CONFLICT)")
    parser.add_argument(
        "--replace-mode", default="append",
        choices=["append", "replace"],
        help="For incremental mode: append or replace existing data (default: append)")
    parser.add_argument(
        "--config", "-c", default=None,
        help="Path to vitalgraphdb-config.yaml (default: env / standard locations)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate parameters only, do not write data")

    return parser.parse_args()


def main():
    args = parse_args()
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
