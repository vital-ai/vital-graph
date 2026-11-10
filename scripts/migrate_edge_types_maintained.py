#!/usr/bin/env python3
"""Mark existing spaces' edge types as MAINTAINED (`issues/293`).

`{space}_edge.edge_type_uuid` stands in for an edge's vitaltype quad on the
hop-wise walk (`emit_traversal.absorb_edge_types`) only where the space is
marked in `edge_type_maintained`. New spaces start marked. An existing space
may hold rows written before the edge sync kept the column in step: a NULL
where the vitaltype arrived in a later write, or an old type after a SPARQL
update changed it. This reconciles every row of the edge table against the
quads (`sync_edge_table.reconcile_edge_types`) and marks the space, unless a
write dirtied it meanwhile, in which case re-run it.

One UPDATE over the edge table per space, so it can take minutes on a large
space. It holds row locks on the rows it changes, not the table.

RUN AS THE TABLES' OWNER, the app role on production, not the RDS master.

DEFAULT IS A DRY RUN.

    python scripts/migrate_edge_types_maintained.py --all
    python scripts/migrate_edge_types_maintained.py --space <space> --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# The repo root ahead of site-packages: an installed copy resolves a different
# cluster (see `migrate_quad_ctx_pred_index.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402


async def run(args) -> int:
    import asyncpg
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    from vitalgraph.db.sparql_sql.sync_edge_table import (
        EDGE_TYPES_DDL, EDGE_TYPES_TABLE, edge_types_marked, reconcile_edge_types)

    conn = await asyncpg.connect(host=args.host, port=args.port, database=args.database,
                                 user=args.user, password=args.password or None)
    try:
        await load_storage_keys(conn)
        print(f"target: {describe_target(args)}{'' if args.apply else '  [DRY RUN]'}\n")
        if await conn.fetchval("SELECT to_regclass($1)", EDGE_TYPES_TABLE) is None:
            print(f"database: create {EDGE_TYPES_TABLE}")
            if args.apply:
                await conn.execute(EDGE_TYPES_DDL)
        spaces = args.space or [r["space_id"] for r in await conn.fetch(
            "SELECT space_id FROM space ORDER BY space_id")]
        todo = 0
        for sid in spaces:
            t_edge = f"{space_prefix(sid)}_edge"
            if await conn.fetchval("SELECT to_regclass($1)", t_edge) is None:
                print(f"  skip {sid}: no edge table")
                continue
            marked, _ = (await edge_types_marked(conn, sid)
                         if await conn.fetchval("SELECT to_regclass($1)", EDGE_TYPES_TABLE)
                         else (False, None))
            if marked:
                print(f"  {sid}: already marked")
                continue
            todo += 1
            if not args.apply:
                print(f"  {sid}: would reconcile {t_edge} and mark")
                continue
            t0 = time.time()
            out = await reconcile_edge_types(conn, sid)
            print(f"  {sid}: {out['fixed']} row(s) fixed, "
                  f"{'marked' if out['marked'] else 'NOT marked (written meanwhile; re-run)'} "
                  f"in {time.time() - t0:.1f}s")
        print(f"\n{todo} space(s) to mark" + ("" if args.apply else ". Dry run. Re-run with --apply."))
        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space", action="append")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    add_pg_arguments(ap)
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
