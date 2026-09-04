#!/usr/bin/env python3
"""Recompute every registered space and check the four properties it promises.

Run against the docker test stack after a change to `recompute_stats_tables`.
The unit and integration suites use small synthetic fixtures; this is the same
claims against loaded spaces of 45 to 50,570,000 quads, where the cap actually
binds and the predicate distribution is real.

  1. EXACT below the cap — where nothing was cut, the table IS
     `GROUP BY predicate, object HAVING count(*) >= STATS_MIN_ROW_COUNT`.
     Compared as sets of (pair -> count), because a matching row TOTAL can be
     two errors cancelling.
  2. ANCHORS KEPT — every predicate's largest pair is stored. This is the
     property `ORDER BY count(*) DESC` exists for, and the one an ascending
     order silently broke: the table is read to RECOGNISE a huge end so the
     planner does not drive from it, and a pair it cannot see it cannot avoid.
  3. ABSENCE IS AN UPPER BOUND — every pair NOT stored is `<=` the bound
     `absence_bounds` reports for its predicate. This is what lets the traversal
     price a constrained end that has no row (`issues/153`); if it is ever
     violated the planner is being handed a number that is too small.
  4. FAIRNESS — every predicate with a qualifying pair is represented, so
     absence can be interpreted per predicate rather than being ambiguous
     between "nothing qualifies" and "starved by the cap".
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


async def check(conn, sp: str) -> dict:
    from vitalgraph.db.sparql_sql.sync_stats_tables import (
        STATS_MIN_ROW_COUNT, absence_bounds, recompute_stats_tables)

    quads = await conn.fetchval(f"SELECT count(*) FROM {sp}_rdf_quad")
    if not quads:
        return {"space": sp, "quads": 0, "skip": "no quads"}

    t0 = time.monotonic()
    await recompute_stats_tables(conn, sp)
    ms = (time.monotonic() - t0) * 1000

    stored = {(r["predicate_uuid"], r["object_uuid"]): r["row_count"]
              for r in await conn.fetch(
                  f"SELECT predicate_uuid, object_uuid, row_count "
                  f"FROM {sp}_rdf_stats")}
    preds = {r["predicate_uuid"]: r["row_count"] for r in await conn.fetch(
        f"SELECT predicate_uuid, row_count FROM {sp}_rdf_pred_stats")}
    truth = {(r["predicate_uuid"], r["object_uuid"]): r["rc"]
             for r in await conn.fetch(
                 f"SELECT predicate_uuid, object_uuid, count(*) AS rc "
                 f"FROM {sp}_rdf_quad GROUP BY 1, 2 "
                 f"HAVING count(*) >= {STATS_MIN_ROW_COUNT}")}
    bounds = absence_bounds(stored, preds)

    cut = len(truth) - len(stored)
    out = {"space": sp, "quads": quads, "ms": ms, "stored": len(stored),
           "truth": len(truth), "cut": cut, "bounds": len(bounds)}

    # 1. exact where nothing was cut
    if cut == 0:
        out["exact"] = "YES" if stored == truth else "NO"
    else:
        wrong = [k for k in set(stored) & set(truth) if stored[k] != truth[k]]
        out["exact"] = "capped" if not wrong else f"NO ({len(wrong)} wrong)"

    # 2. every predicate's largest pair is stored
    true_max: dict = {}
    for (p, _o), rc in truth.items():
        true_max[p] = max(rc, true_max.get(p, 0))
    stored_max: dict = {}
    for (p, _o), rc in stored.items():
        stored_max[p] = max(rc, stored_max.get(p, 0))
    missing_anchor = [p for p, mx in true_max.items()
                      if stored_max.get(p, -1) != mx]
    out["anchors"] = "ALL" if not missing_anchor else f"{len(missing_anchor)} LOST"

    # 3. absence is an upper bound
    violations = [(p, o, rc) for (p, o), rc in truth.items()
                  if (p, o) not in stored and p in bounds and rc > bounds[p]]
    out["bound"] = "SOUND" if not violations else f"{len(violations)} VIOLATED"
    if violations:
        p, o, rc = violations[0]
        out["worst"] = f"pair={rc} bound={bounds[p]}"

    # 4. fairness
    out["fair"] = "ALL" if set(true_max) <= set(stored_max) else (
        f"{len(set(true_max) - set(stored_max))} predicate(s) unrepresented")
    return out


async def main():
    ap = argparse.ArgumentParser()
    add_pg_arguments(ap)
    a = ap.parse_args()
    print(describe_target(a))

    conn = await asyncpg.connect(host=a.host, port=a.port, user=a.user,
                                 password=a.password, database=a.database,
                                 command_timeout=1800)
    try:
        spaces = [r["space_id"] for r in await conn.fetch(
            "SELECT space_id FROM space ORDER BY space_id")]
        print(f"\n{'space':<24}{'quads':>12}{'ms':>8}{'stored':>8}{'cut':>9}"
              f"  {'exact':<10}{'anchors':<9}{'bound':<8}{'fair'}")
        bad = 0
        for sp in spaces:
            try:
                r = await check(conn, sp)
            except asyncpg.UndefinedTableError:
                continue
            if r.get("skip"):
                continue
            print(f"{r['space']:<24}{r['quads']:>12,}{r['ms']:>8.0f}"
                  f"{r['stored']:>8,}{r['cut']:>9,}  {r['exact']:<10}"
                  f"{r['anchors']:<9}{r['bound']:<8}{r['fair']}")
            if ("NO" in r["exact"] or "LOST" in r["anchors"]
                    or "VIOLATED" in r["bound"] or "unrepresented" in r["fair"]):
                bad += 1
                if r.get("worst"):
                    print(f"    worst bound violation: {r['worst']}")
        print(f"\n{'FAILED' if bad else 'OK'}: {bad} space(s) violated a property")
        return 1 if bad else 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
