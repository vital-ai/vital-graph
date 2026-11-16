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
    """Core indexes, then core heaps, then everything else; larger first within each.

    The DEFAULT order, used for relations the job has not measured yet (its first pass,
    a new index). Once measured, `order_by_access` ranks them; see why there.
    """
    core = {space_tables[k] for k in _CORE if k in space_tables}

    def rank(r):
        if r["table_name"] in core:
            return 0 if r["is_index"] else 1
        return 2
    return sorted(rows, key=lambda r: (rank(r), -int(r["bytes"] or 0)))


# RANKED BY MEASURED ACCESS, NOT BY SIZE (`issues/346`).
#
# "Core first, largest first" assumed the space fits the cap, which it did when
# `issues/271` sized it (234 k blocks, ~1.8 GB). By 2026-11-16 production's prewarmed
# space was 23.1 GiB against a 12 GiB cap, so largest-first filled the cap with the
# biggest relations rather than the hottest. Measured over 30 minutes from
# `pg_statio` (lookups AND the index maintenance each insert does), minus this
# job's own touches: the warm set covered **37.6 %** of the space's block accesses;
# ranked by accesses per byte, the same cap covers **97.9 %**. `quad_ctx_pred`
# (3.35 GiB, 303 accesses/MiB) and `term_trgm` (0.94 GiB, 128/MiB) were warmed,
# while every relation the write path's sync lookups read (`edge`, `frame_slot`,
# `entity_slot_sort` and their indexes) was not. Those lookups take 0.2-0.8 ms warm
# and averaged 173 ms and 80 ms on production, almost every block a read.
#
# Measured by the job itself, every pass, so it follows the workload with no
# per-install configuration:
#
#     accesses(rel) = delta(heap|idx _blks_hit + _blks_read) - blocks this job touched
#
# `pg_prewarm` returns the blocks it touched, so the subtraction is exact. The rate is
# a decayed average over passes (`PREWARM_ACCESS_ALPHA` per pass), so one burst
# does not reorder the set. A counter that moved BACKWARDS (`pg_stat_reset`) or
# cannot be read updates nothing; an unmeasured relation keeps the default order.
PREWARM_ACCESS_ALPHA = float(os.getenv("VG_PREWARM_ACCESS_ALPHA", "0.1"))

_ACCESS_SQL = """
SELECT c.oid::regclass::text AS rel,
       COALESCE(CASE WHEN c.relkind IN ('i', 'I') THEN si.idx_blks_hit + si.idx_blks_read
                     ELSE st.heap_blks_hit + st.heap_blks_read END, 0)::bigint AS acc
FROM pg_class c
LEFT JOIN pg_statio_user_indexes si ON si.indexrelid = c.oid
LEFT JOIN pg_statio_user_tables  st ON st.relid = c.oid
WHERE c.oid = ANY($1::regclass[])
"""


def order_by_access(rows: Sequence[dict], space_tables: Dict[str, str],
                    rate: Dict[str, float]) -> List[dict]:
    """Measured relations by accesses per MiB, highest first; the rest after, in the default order."""
    default = order_relations(rows, space_tables)
    measured = sorted((r for r in default if r["rel"] in rate),
                      key=lambda r: -rate[r["rel"]])
    return measured + [r for r in default if r["rel"] not in rate]


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
        # Per relation (`issues/346`): the access counter at the start of the last
        # pass, the blocks this job touched in it, and the decayed accesses per MiB.
        self._acc_prev: Dict[str, int] = {}
        self._own_prev: Dict[str, int] = {}
        self.access_rate: Dict[str, float] = {}

    async def _measure(self, conn, rows: Sequence[dict]) -> None:
        """Fold the accesses since the last pass into `access_rate`. Never raises."""
        try:
            acc = {r["rel"]: int(r["acc"]) for r in await conn.fetch(
                _ACCESS_SQL, [r["rel"] for r in rows])}
        except Exception as exc:
            logger.debug("prewarm: access counters unreadable (%s); keeping the order", exc)
            return
        size = {r["rel"]: max(int(r["bytes"] or 0), 8192) for r in rows}
        for rel, now in acc.items():
            prev = self._acc_prev.get(rel)
            self._acc_prev[rel] = now
            if prev is None:
                continue
            real = now - prev - self._own_prev.get(rel, 0)
            if now < prev:
                continue                    # a stats reset: no information this pass
            per_mib = max(real, 0) / (size.get(rel, 8192) / 2**20)
            old = self.access_rate.get(rel)
            self.access_rate[rel] = per_mib if old is None else (
                PREWARM_ACCESS_ALPHA * per_mib + (1 - PREWARM_ACCESS_ALPHA) * old)

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
                await self._measure(conn, rows)
                ranked = any(r["rel"] in self.access_rate for r in rows)
                kept, skipped = apply_cap(
                    order_by_access(rows, tables, self.access_rate), budget)
                budget -= sum(int(r["bytes"]) for r in kept)

                t0 = time.monotonic()
                reads0 = await conn.fetchval(_READS_SQL, list(tables.values()))
                blocks = 0
                for r in rows:
                    self._own_prev[r["rel"]] = 0
                for r in kept:
                    n = int(await conn.fetchval(
                        "SELECT pg_prewarm($1::regclass, 'buffer')", r["rel"],
                        timeout=PREWARM_STATEMENT_TIMEOUT_S) or 0)
                    self._own_prev[r["rel"]] = n      # subtracted at the next pass
                    blocks += n
                reads1 = await conn.fetchval(_READS_SQL, list(tables.values()))
                read = max(0, int(reads1) - int(reads0))
                stats = {"relations": len(kept), "blocks": blocks, "read": read,
                         "seconds": round(time.monotonic() - t0, 3),
                         "order": "measured access" if ranked else "default"}
                summary["spaces"][space_id] = stats
                # The measurement is the log: `read` near 0 pass after pass means
                # the space stayed resident between passes; a rising share means
                # the interval is too long for the current eviction rate. It
                # counts every read of these tables during the pass, concurrent
                # queries included, so it is an upper bound on the pass's own.
                logger.info(
                    "prewarm %s: %d relations, %d blocks in %.2fs, %d read (%.1f%%), "
                    "order: %s",
                    space_id, len(kept), blocks, stats["seconds"], read,
                    100.0 * read / blocks if blocks else 0.0, stats["order"])
                if skipped:
                    names = [r["relname"] for r in skipped]
                    summary["skipped"] += names
                    logger.warning(
                        "prewarm %s: %d relation(s) NOT warmed, over the %d-byte "
                        "cap (VG_PREWARM_MAX_BYTES): %s", space_id, len(names),
                        self._max_bytes, ", ".join(names[:10]))
        summary["seconds"] = round(time.monotonic() - start, 3)
        return summary
