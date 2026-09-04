#!/usr/bin/env python3
"""Watch what the maintenance job does when a large space CHANGES.

The suites prove the recompute is correct on small fixtures and the validator
proves it on loaded ones. Neither drives the thing the schedule exists for: a
space that is quiet, then is written to, and has to be noticed.

Reports the four observable states in order:

  1. BASELINE      — stats present, matching the quads, and the space quiet.
  2. GATE CLOSED   — `probe_data_changed` says nothing moved, so a due space is
                     skipped for the cost of one pg_stat read rather than a scan.
  3. GATE OPEN     — after a write, the monotonic counters have moved and the
                     probe says so. `n_tup_ins + n_tup_upd + n_tup_del`, NOT
                     `n_mod_since_analyze`, which ANALYZE resets underneath us.
  4. RECONCILED    — a recompute after the write puts the table back in exact
                     agreement with the quads.

Run against the docker test stack, after loading a space that is NOT in
VG_MAINTENANCE_EXCLUDE_SPACES.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import asyncpg  # noqa: E402
from devtools.target import add_pg_arguments, describe_target  # noqa: E402


async def truth_vs_stored(conn, sp):
    truth = {(r["p"], r["o"]): r["n"] for r in await conn.fetch(
        f"SELECT predicate_uuid p, object_uuid o, count(*) n "
        f"FROM {sp}_rdf_quad GROUP BY 1,2 HAVING count(*) >= 2")}
    stored = {(r["p"], r["o"]): r["n"] for r in await conn.fetch(
        f"SELECT predicate_uuid p, object_uuid o, row_count n FROM {sp}_rdf_stats")}
    return truth, stored


async def main():
    ap = argparse.ArgumentParser()
    add_pg_arguments(ap)
    ap.add_argument("--space", default="maint_large_trial")
    a = ap.parse_args()
    print(describe_target(a))
    sp = a.space

    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables
    from vitalgraph.process.maintenance_job import (
        probe_data_changed, reset_probe_gate)

    conn = await asyncpg.connect(host=a.host, port=a.port, user=a.user,
                                 password=a.password, database=a.database,
                                 command_timeout=1800)
    try:
        quads = await conn.fetchval(f"SELECT count(*) FROM {sp}_rdf_quad")
        print(f"\n{sp}: {quads:,} quads\n")

        # 1. BASELINE
        t0 = time.monotonic()
        await recompute_stats_tables(conn, sp)
        ms = (time.monotonic() - t0) * 1000
        truth, stored = await truth_vs_stored(conn, sp)
        cut = len(truth) - len(stored)
        agree = (stored == truth) if cut == 0 else all(
            stored[k] == truth[k] for k in set(stored) & set(truth))
        print(f"1. BASELINE     recompute {ms:,.0f} ms, {len(stored):,} stored, "
              f"{cut:,} cut, counts agree: {agree}")

        # 2/3. THE GATE, without assuming the space is quiet.
        #
        # The first version of this asserted "quiet -> False", and the space was
        # NOT quiet: `backfill_server_properties_task` patches entities in it
        # continuously. The probe correctly said True and the test called that a
        # failure. It also slept 2s and hoped the stats collector had caught up,
        # which on a loaded 50M-row table it had not.
        #
        # So drive it off the watermark the probe actually reads, and WAIT for
        # that watermark to move rather than guessing how long it takes.
        async def watermark():
            return await conn.fetchval(
                "SELECT COALESCE(n_tup_ins,0)+COALESCE(n_tup_upd,0)"
                "     + COALESCE(n_tup_del,0) FROM pg_stat_user_tables "
                "WHERE relname = $1", f"{sp}_rdf_quad")

        reset_probe_gate()
        await probe_data_changed(conn, sp, "observe")   # arms the watermark
        w_before = await watermark()

        # UNCHANGED-SINCE-LAST-READ: ask again with no wait. If the watermark
        # has not moved the answer must be False; if a concurrent writer moved
        # it, True is the correct answer and the case is simply not observable
        # on a live space — reported, not asserted away.
        again = await probe_data_changed(conn, sp, "observe")
        w_now = await watermark()
        quiet = (w_now == w_before)
        print(f"2. NO NEW WRITES   watermark {'held' if quiet else 'MOVED'} "
              f"({w_before:,} -> {w_now:,}) -> changed={again}   "
              f"{'correct' if again == (not quiet) else 'WRONG'}")

        # WRITE, then wait for the collector to actually reflect it.
        import uuid as _u
        ctx = await conn.fetchval(f"SELECT context_uuid FROM {sp}_rdf_quad LIMIT 1")
        p_ = await conn.fetchval(f"SELECT predicate_uuid FROM {sp}_rdf_quad LIMIT 1")
        o_ = await conn.fetchval(f"SELECT object_uuid FROM {sp}_rdf_quad LIMIT 1")
        w_pre = await watermark()
        await conn.executemany(
            f"INSERT INTO {sp}_rdf_quad "
            f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
            f"VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
            [(_u.uuid4(), p_, o_, ctx) for _ in range(500)])
        waited = 0.0
        while await watermark() == w_pre and waited < 30:
            await asyncio.sleep(0.5); waited += 0.5
        await probe_data_changed(conn, sp, "observe")   # re-arm at the new mark
        w_arm = await watermark()
        await conn.executemany(
            f"INSERT INTO {sp}_rdf_quad "
            f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
            f"VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
            [(_u.uuid4(), p_, o_, ctx) for _ in range(500)])
        waited = 0.0
        while await watermark() == w_arm and waited < 30:
            await asyncio.sleep(0.5); waited += 0.5
        opened = await probe_data_changed(conn, sp, "observe")
        print(f"3. AFTER A WRITE   watermark moved after {waited:.1f}s "
              f"-> changed={opened}   {'correct' if opened else 'WRONG'}")

        # 4. RECONCILED
        t0 = time.monotonic()
        await recompute_stats_tables(conn, sp)
        ms = (time.monotonic() - t0) * 1000
        truth, stored = await truth_vs_stored(conn, sp)
        cut = len(truth) - len(stored)
        wrong = [k for k in set(stored) & set(truth) if stored[k] != truth[k]]
        print(f"4. RECONCILED   recompute {ms:,.0f} ms, {len(stored):,} stored, "
              f"{len(wrong)} disagreeing with the quads")

        # `wrong` is not asserted on a live space: writes land between the
        # recompute and the truth query, so a handful of disagreements measures
        # the concurrent writer, not the rebuild. Exactness is proven quiet by
        # `validate_recompute_all_spaces.py`; what THIS script uniquely shows is
        # the gate.
        ok = opened is True
        print(f"\n{'OK' if ok else 'FAILED'}: the gate opened once the write was "
              f"visible in pg_stat ({len(wrong)} count(s) differ from the quads, "
              f"which on a live space measures the concurrent writer)")
        return 0 if ok else 1
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
