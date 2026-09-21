#!/usr/bin/env python3
"""T3 — create and populate the message FTS index.

Plan §5 T3, Option A: the index holds ONE ROW PER MESSAGE SLOT, not per
entity. Slots are what the FTS table can key on, a conversation search wants
to know WHICH message matched, and it needs no entity rollup and no populator
traversal.

Four steps, all through APIs that already exist:

    1. ensure_fts_index            the registry row, data table, tsv trigger
    2. create_mapping              kgslot / <slot type> / properties
    3. add_property                hasTextSlotValue — the ONLY indexed property
    4. populate_fts_index          with slot_type_uri, the item-1 filter

RUNS AGAINST THE DATABASE, NOT THE SERVER, deliberately. The containerised
server runs a built image; `slot_type_uri` and the issues/217 auto-sync fixes
are in the repo, not in that image. Driving this host-side uses current code.
Re-run it through the client once the image is rebuilt if you want to prove
the REST path too.

The mapping is what makes populate and auto-sync agree (issues/217): the
populator resolves `(kgslot, <slot type>)` to this row, and so does
`_sync_fts_for_subjects` on every subsequent write. A subject outside that
mapping is now SKIPPED rather than indexed with every literal it owns.

    VG_SEARCH_SPACE=... VG_SEARCH_GRAPH=... VG_KG_NS=... \\
        python3 test_scripts/search/setup_message_fts_index.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid as _uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
HAS_TEXT_SLOT_VALUE = HALEY + "hasTextSlotValue"


def _context_uuid(graph_uri: str):
    """Same derivation the populate endpoint uses (uuid5 over the graph URI)."""
    ns = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return _uuid.uuid5(ns, f"{graph_uri}\x00U")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default=os.environ.get("VG_SEARCH_SPACE"))
    ap.add_argument("--graph", default=os.environ.get("VG_SEARCH_GRAPH"))
    ap.add_argument("--ns", default=os.environ.get("VG_KG_NS"))
    ap.add_argument("--slot-type", default=None)
    ap.add_argument("--index", default="message_content")
    ap.add_argument("--languages", default="english")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--host", default=os.environ.get("VG_PG_HOST", "localhost"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("VG_PG_PORT", "5433")))
    ap.add_argument("--db", default=os.environ.get("VG_PG_DB", "sparql_sql_graph"))
    ap.add_argument("--user", default=os.environ.get("VG_PG_USER", "postgres"))
    ap.add_argument("--password", default=os.environ.get("VG_PG_PASSWORD", "testpass"))
    a = ap.parse_args()

    if not a.space or not a.graph or not (a.slot_type or a.ns):
        print("Set VG_SEARCH_SPACE, VG_SEARCH_GRAPH and VG_KG_NS "
              "(or pass --slot-type).")
        return 2
    slot_type = a.slot_type or f"{a.ns}:slot:MsgContent"
    languages = [x.strip() for x in a.languages.split(",") if x.strip()]

    import asyncpg
    from vitalgraph.vectorization.fts_index_lifecycle import (
        ensure_fts_index, get_fts_stats)
    from vitalgraph.vectorization.search_mapping_manager import SearchMappingManager
    from vitalgraph.vectorization.fts_populator import populate_fts_index

    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.db,
                                 user=a.user, password=a.password)
    try:
        ctx_uuid = _context_uuid(a.graph)
        print(f"space={a.space}  graph={a.graph}\nslot={slot_type}  "
              f"index={a.index}  languages={languages}\n")

        # 1 --------------------------------------------------------------
        ok = await ensure_fts_index(conn, a.space, a.index, languages)
        print(f"1. fts index           {'ok' if ok else 'FAILED'}")
        if not ok:
            return 1

        # 2 + 3 ----------------------------------------------------------
        mgr = SearchMappingManager(conn, a.space)
        existing = await conn.fetchrow(
            f"SELECT mapping_id FROM {a.space}_search_mapping "
            f"WHERE index_name = $1 AND mapping_type = 'kgslot' "
            f"AND type_uri = $2", a.index, slot_type)
        if existing:
            mapping_id = existing["mapping_id"]
            print(f"2. mapping             reusing {mapping_id}")
        else:
            mapping_id = await mgr.create_mapping(
                a.index, "kgslot", type_uri=slot_type,
                source_type="properties")
            # `hasTextSlotValue` ALONE. Indexing the slot's other literals
            # would put the slot type URI, frame URI and timestamps into the
            # tsvector — which is exactly what the issues/217 auto-sync defect
            # was doing, and what made ranking drift.
            await mgr.add_property(mapping_id, HAS_TEXT_SLOT_VALUE, ordinal=0)
            print(f"2. mapping             created {mapping_id} "
                  f"(kgslot / properties / hasTextSlotValue)")

        # 4 --------------------------------------------------------------
        print(f"3. populating (slot_type_uri={slot_type.split(':')[-1]}) ...",
              flush=True)
        t0 = time.monotonic()
        stats = await populate_fts_index(
            conn, a.space, a.index, ctx_uuid,
            slot_type_uri=slot_type,
            mapping_type="kgslot",
            batch_size=a.batch_size,
        )
        dt = time.monotonic() - t0
        print(f"   processed {stats.subjects_processed:,}  "
              f"stored {stats.rows_stored:,}  "
              f"skipped {stats.subjects_skipped:,}  in {dt:.0f}s")
        for e in stats.errors[:5]:
            print(f"   ERROR: {e}")

        # ------------------------------------------------------------------
        st = await get_fts_stats(conn, a.space, a.index)
        print(f"\n4. index stats         {st}")

        size = await conn.fetchval(
            "SELECT pg_size_pretty(pg_total_relation_size($1))",
            f"{a.space}_fts_{a.index}")
        print(f"   table+index size    {size}")

        if stats.rows_stored == 0:
            print("\nNothing indexed. Check the slot type URI and the graph.")
            return 1
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
