"""Keep named spaces resident in shared_buffers — issues/271.

PostgreSQL cannot pin a table in memory. Pages are evicted by a clock sweep over
usage counts (0-5, +1 per access, -1 per pass of the sweep, evicted at 0), so
the only way to keep a small, latency-critical space resident next to a much
larger one is to keep ACCESSING it. `pg_prewarm(rel, 'buffer')` is an access:
run over a space's relations more often than the sweep can age them to zero,
it keeps them in the cache.

Measured on production on 2026-10-16: before a single pass only ~4 % of
prod_uw's 234k blocks were in shared_buffers, because the main KG space's
41 GB of quad table and indexes keeps evicting it. UW quad inserts spent 96 % of
their time waiting on block reads, 3.05 reads per row. After one pass: 0.27-0.95
reads per row and its 5-9k-quad decision writes went from 6.5-18.7 s to
2.1-4.8 s. At the eviction rate measured then (~11,800 buffers/s against ~1.0M
buffers) one sweep pass takes at most ~85 s, so a 60 s interval keeps a touched
page from ever reaching zero.

OPT-IN AND NAMED. `VG_PREWARM_SPACES` lists the spaces; nothing is warmed by
default. Every block kept resident displaces a block of something else, which
is the trade being made deliberately for a small space whose writes have a
latency target — and why this must never be "all spaces".

ONE RUNNER ACROSS ALL TASKS. Registered with `single_runner=True`: shared_buffers
belong to the database, not to a task, so one task warming them serves every
task, and N tasks doing it would only multiply the work. If the runner stops,
its session advisory lock dies with its connection and another task takes over.

The extension is created by an explicit setup step, never here: a missing
`pg_prewarm` is reported once at WARNING and the job does nothing until it
appears.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

PREWARM_INTERVAL_S = float(os.getenv("VG_PREWARM_INTERVAL_S", "60"))
# Cap on the bytes one pass will warm, across all its spaces. A misconfigured
# large space must not be able to flood shared_buffers; what does not fit is
# skipped and LOGGED, never silently dropped.
PREWARM_MAX_BYTES = int(float(os.getenv("VG_PREWARM_MAX_BYTES", str(3 * 1024**3))))
# Per relation. A cold relation reads at storage speed (production: 1.8 GB in
# 14.5 s for the whole of prod_uw); a stalled storage layer must not hold the
# job, and each relation is its own statement so no lock outlives its read.
PREWARM_STATEMENT_TIMEOUT_S = float(os.getenv("VG_PREWARM_STATEMENT_TIMEOUT_S", "60"))


def prewarm_spaces_from_env() -> List[str]:
    return [s.strip() for s in os.getenv("VG_PREWARM_SPACES", "").split(",") if s.strip()]


# The two tables every write maintains first; their indexes carry the insert
# cost, so they are warmed before anything else in case the cap cuts the pass.
_CORE = ("rdf_quad", "term")

_RELATIONS_SQL = """
SELECT c.oid::regclass::text AS rel, c.relname, t.relname AS table_name,
       c.relkind IN ('i', 'I') AS is_index, pg_relation_size(c.oid) AS bytes
FROM pg_class t
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_class c ON c.oid = t.oid
                OR c.oid IN (SELECT indexrelid FROM pg_index WHERE indrelid = t.oid)
WHERE n.nspname = 'public' AND t.relkind = 'r' AND t.relname = ANY($1::text[])
"""

_READS_SQL = """
SELECT coalesce(sum(heap_blks_read + coalesce(idx_blks_read, 0)), 0)::bigint
FROM pg_statio_user_tables WHERE relname = ANY($1::text[])
"""


def order_relations(rows: Sequence[dict], space_tables: Dict[str, str]) -> List[dict]:
    """Core indexes, then core heaps, then everything else; larger first within each."""
    core = {space_tables[k] for k in _CORE if k in space_tables}

    def rank(r):
        if r["table_name"] in core:
            return 0 if r["is_index"] else 1
        return 2
    return sorted(rows, key=lambda r: (rank(r), -int(r["bytes"] or 0)))


def apply_cap(rows: Sequence[dict], cap: int):
    """(kept, skipped) — whole relations, in order, until the next would exceed `cap`."""
    kept, skipped, total = [], [], 0
    for r in rows:
        b = int(r["bytes"] or 0)
        if b == 0:
            continue
        if total + b > cap:
            skipped.append(r)
            continue
        kept.append(r)
        total += b
    return kept, skipped


class PrewarmJob:
    """One pass: `pg_prewarm(..., 'buffer')` over every relation of each space."""

    def __init__(self, pool, spaces: Sequence[str], max_bytes: int = PREWARM_MAX_BYTES):
        self._pool = pool
        self._spaces = list(spaces)
        self._max_bytes = max_bytes
        self._warned_missing_ext = False
        self._warned_no_tables: set = set()

    def _space_tables(self, space_id: str) -> Dict[str, str]:
        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        return {k: v.split(".")[-1]
                for k, v in SparqlSQLSchema.get_table_names(space_id).items()}

    async def run(self) -> Dict:
        start = time.monotonic()
        summary: Dict = {"spaces": {}, "skipped": []}
        if not self._spaces:
            return summary
        async with self._pool.acquire() as conn:
            if not await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_prewarm')"):
                if not self._warned_missing_ext:
                    logger.warning(
                        "prewarm: extension pg_prewarm is not installed, so %s will "
                        "NOT be kept resident. Create it once (CREATE EXTENSION "
                        "pg_prewarm, as an owner/superuser); this job picks it up "
                        "on its next pass.", ", ".join(self._spaces))
                    self._warned_missing_ext = True
                summary["missing_extension"] = True
                return summary
            self._warned_missing_ext = False

            budget = self._max_bytes
            for space_id in self._spaces:
                tables = self._space_tables(space_id)
                rows = [dict(r) for r in await conn.fetch(
                    _RELATIONS_SQL, list(tables.values()))]
                if not rows:
                    if space_id not in self._warned_no_tables:
                        logger.warning("prewarm: space %s has no tables; check "
                                       "VG_PREWARM_SPACES", space_id)
                        self._warned_no_tables.add(space_id)
                    continue
                kept, skipped = apply_cap(order_relations(rows, tables), budget)
                budget -= sum(int(r["bytes"]) for r in kept)

                t0 = time.monotonic()
                reads0 = await conn.fetchval(_READS_SQL, list(tables.values()))
                blocks = 0
                for r in kept:
                    blocks += int(await conn.fetchval(
                        "SELECT pg_prewarm($1::regclass, 'buffer')", r["rel"],
                        timeout=PREWARM_STATEMENT_TIMEOUT_S) or 0)
                reads1 = await conn.fetchval(_READS_SQL, list(tables.values()))
                read = max(0, int(reads1) - int(reads0))
                stats = {"relations": len(kept), "blocks": blocks, "read": read,
                         "seconds": round(time.monotonic() - t0, 3)}
                summary["spaces"][space_id] = stats
                # The measurement is the log: `read` near 0 pass after pass means
                # the space stayed resident between passes; a rising share means
                # the interval is too long for the current eviction rate. It
                # counts every read of these tables during the pass, concurrent
                # queries included, so it is an upper bound on the pass's own.
                logger.info(
                    "prewarm %s: %d relations, %d blocks in %.2fs, %d read (%.1f%%)",
                    space_id, len(kept), blocks, stats["seconds"], read,
                    100.0 * read / blocks if blocks else 0.0)
                if skipped:
                    names = [r["relname"] for r in skipped]
                    summary["skipped"] += names
                    logger.warning(
                        "prewarm %s: %d relation(s) NOT warmed, over the %d-byte "
                        "cap (VG_PREWARM_MAX_BYTES): %s", space_id, len(names),
                        self._max_bytes, ", ".join(names[:10]))
        summary["seconds"] = round(time.monotonic() - start, 3)
        return summary
