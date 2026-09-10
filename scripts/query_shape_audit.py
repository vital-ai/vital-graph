#!/usr/bin/env python3
"""Rank a corpus of SPARQL queries by whether they do work proportional to their ANSWER.

    loops of the busiest plan node / rows returned

On the `issues/178` reference CONSTRUCT that ratio was **285,348 / 425 = 671**
before the fix and **341 / 425 = 0.8** after. It needs no baseline, no domain
knowledge and no intuition about what "should" be fast — which is the point.
Six shape rewrites were implemented, measured and reverted on that query, and
EVERY failed attempt left the ratio near 671 while the successful one took it
to 0.8. Wall-clock did not separate them: two of the failures looked like
improvements on a warm cache.

This is the harness that finds the NEXT one without anyone guessing.

Usage
-----
    # a directory or file of .sparql
    scripts/query_shape_audit.py --space wordnet_frames --queries path/to/queries/

    # close the loop with production: read the WARNING lines the app emits
    scripts/query_shape_audit.py --space prod_kg --from-log /var/log/app.log

    # machine-readable, for tracking over time
    scripts/query_shape_audit.py --space s --queries q/ --json audit.json

`--from-log` parses the `slow_query {...}` records written by
`plan_shape.report_slow_query`, so a query that was slow in production can be
re-audited here against the same space without anyone transcribing it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vitalgraph.db.sparql_sql.plan_shape import analyse  # noqa: E402

logger = logging.getLogger("query_shape_audit")


def _load_env(path: str = ".env") -> Dict[str, str]:
    out: Dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k] = v.strip().strip('"').strip("'")
    return out


def collect_queries(paths: List[str], from_log: Optional[str]) -> List[Tuple[str, str]]:
    """(label, sparql) pairs from files, directories, or an application log."""
    out: List[Tuple[str, str]] = []
    for raw in paths or []:
        p = Path(raw)
        files = sorted(p.rglob("*.sparql")) if p.is_dir() else [p]
        for f in files:
            try:
                out.append((f.name, f.read_text()))
            except Exception as exc:
                logger.warning("skipping %s: %s", f, exc)

    if from_log:
        seen = set()
        for line in Path(from_log).read_text(errors="replace").splitlines():
            if "slow_query " not in line:
                continue
            try:
                rec = json.loads(line.split("slow_query ", 1)[1])
            except Exception:
                continue
            sparql = rec.get("sparql")
            fp = rec.get("sql_fingerprint") or (sparql or "")[:80]
            # One entry per SHAPE. A query that was slow a thousand times is
            # one thing to fix, not a thousand.
            if sparql and fp not in seen:
                seen.add(fp)
                out.append((f"log:{fp}", sparql))
    return out


async def audit_one(conn, cr, space_id: str, db_params: Dict[str, Any],
                    label: str) -> Dict[str, Any]:
    from vitalgraph.db.sparql_sql.generator import generate_sql

    row: Dict[str, Any] = {"label": label}
    t0 = time.monotonic()
    gen = await generate_sql(cr, space_id, conn_params=db_params, conn=conn)
    row["gen_ms"] = round((time.monotonic() - t0) * 1000, 1)
    if not gen.ok or not gen.sql:
        row["error"] = gen.error or "generation produced no SQL"
        return row
    row["plan_decisions"] = gen.plan_decisions

    t1 = time.monotonic()
    rows = await conn.fetch(gen.sql)
    row["exec_ms"] = round((time.monotonic() - t1) * 1000, 1)

    plan = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + gen.sql)
    shape = analyse([r[0] for r in plan], rows_returned=len(rows))
    row.update(shape.as_dict())
    row["busiest"] = shape.busiest[:1]      # one line is enough to recognise it
    return row


async def main_async(args) -> int:
    env = _load_env()
    db_params = {
        "host": args.host or env.get("SPARQL_SQL_HOST", "localhost"),
        "port": int(args.port or env.get("SPARQL_SQL_PORT", 5432)),
        "user": args.user or env.get("SPARQL_SQL_USER", "postgres"),
        "password": args.password or env.get("SPARQL_SQL_PASSWORD", ""),
        "database": args.database or env.get("SPARQL_SQL_DB", "sparql_sql_graph"),
    }
    queries = collect_queries(args.queries, args.from_log)
    if not queries:
        print("no queries found — pass --queries and/or --from-log", file=sys.stderr)
        return 2

    from vitalgraph_sparql_sql_dev.jena_sparql_orchestrator import SparqlOrchestrator
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql import db_provider as db

    orch = SparqlOrchestrator(space_id=args.space, sidecar_url=args.sidecar,
                              db_params=db_params)
    await orch._ensure_db_provider()
    client = AsyncSidecarClient(base_url=args.sidecar)

    results: List[Dict[str, Any]] = []
    async with db.get_connection(db_params) as conn:
        await conn.execute(f"SET statement_timeout = '{int(args.timeout_s)}s'")
        for label, sparql in queries:
            try:
                cr = map_compile_response(await client.compile(sparql))
                if not cr.ok:
                    results.append({"label": label, "error": f"compile: {cr.error}"})
                    continue
                results.append(await audit_one(conn, cr, args.space, db_params, label))
            except Exception as exc:
                results.append({"label": label,
                                "error": f"{type(exc).__name__}: {exc}"})
    await client.close()

    # Worst first: this is a ranking, not a pass/fail.
    results.sort(key=lambda r: r.get("ratio", -1), reverse=True)

    print(f"\n{'ratio':>9} {'rows':>7} {'loops':>10} {'buffers':>11} "
          f"{'gen_ms':>8} {'exec_ms':>9}  query")
    print("-" * 100)
    bad = 0
    for r in results:
        if "error" in r:
            print(f"{'ERROR':>9} {'':>7} {'':>10} {'':>11} {'':>8} {'':>9}  "
                  f"{r['label']}  ({r['error'][:60]})")
            continue
        flag = "  <-- DISPROPORTIONATE" if r.get("disproportionate") else ""
        bad += 1 if r.get("disproportionate") else 0
        print(f"{r.get('ratio', 0):9.1f} {r.get('rows', 0):7d} "
              f"{r.get('max_loops', 0):10,} {r.get('root_buffers', 0):11,} "
              f"{r.get('gen_ms', 0):8.1f} {r.get('exec_ms', 0):9.1f}  "
              f"{r['label']}{flag}")

    print(f"\n{bad} of {len(results)} queries do work disproportionate to their answer.")
    if bad:
        print("A high ratio is an ORDERING problem. Establish that before "
              "reaching for a new derived table — a materialisation makes the "
              "wrong-order scan cheaper instead of removing it.")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=str))
        print(f"wrote {args.json}")
    return 1 if (bad and args.fail_on_disproportionate) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True)
    ap.add_argument("--queries", action="append", default=[],
                    help="a .sparql file or a directory of them (repeatable)")
    ap.add_argument("--from-log", help="application log containing slow_query records")
    ap.add_argument("--sidecar", default=os.environ.get("VG_SIDECAR_URL",
                                                        "http://localhost:7071"))
    ap.add_argument("--json", help="write the full records here")
    ap.add_argument("--timeout-s", type=int, default=120)
    ap.add_argument("--fail-on-disproportionate", action="store_true",
                    help="exit non-zero when any query is flagged (for CI)")
    for opt in ("host", "port", "user", "password", "database"):
        ap.add_argument(f"--{opt}")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
