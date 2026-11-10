#!/usr/bin/env python3
"""Mark spaces' edge types as MAINTAINED and turn on reading them (`issues/293`).

`{space}_edge.edge_type_uuid` stands in for an edge's vitaltype quad on the
hop-wise walk (`emit_traversal.absorb_edge_types`) only where the space is
marked in `edge_type_maintained` AND the database-wide flag
`edge_type_maintenance_enabled` is set. This script is the only thing that
sets the flag.

FIRST RUN, after a rollout has finished and no old task is left (`--all
--apply`, flag not yet set): clear every mark (any mark written while old and
new tasks overlapped is untrustworthy: an old task neither keeps the column in
step nor dirties a space), reconcile every space's edge table against the
quads (`sync_edge_table.reconcile_edge_types`) and mark it, then set the flag,
but only if every space ended up marked.

LATER RUNS (flag set): reconcile and mark only the spaces not marked.

`--disable`: clear the flag and every mark. Run it after a ROLLBACK, before
rolling forward again: the old image's writes did not keep the column.

One UPDATE over each edge table: minutes on a large space. It takes row locks
on the rows it changes, not the table.

RUN AS THE TABLES' OWNER, the app role on production, not the RDS master.

DEFAULT IS A DRY RUN.

    python scripts/migrate_edge_types_maintained.py --all
    python scripts/migrate_edge_types_maintained.py --all --apply
    python scripts/migrate_edge_types_maintained.py --space <space> --apply
    python scripts/migrate_edge_types_maintained.py --disable --apply
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
        EDGE_TYPES_DDL, EDGE_TYPES_ENABLED_DDL, EDGE_TYPES_TABLE,
        disable_edge_types, edge_types_enabled, enable_edge_types, reconcile_edge_types)

    conn = await asyncpg.connect(host=args.host, port=args.port, database=args.database,
                                 user=args.user, password=args.password or None)
    try:
        await load_storage_keys(conn)
        print(f"target: {describe_target(args)}{'' if args.apply else '  [DRY RUN]'}\n")

        if args.disable:
            print("disable: clear the flag and every mark")
            if args.apply:
                await disable_edge_types(conn)
                print("done: no space's edge types are read off the column")
            return 0

        for name, ddl in ((EDGE_TYPES_TABLE, EDGE_TYPES_DDL),
                          ("edge_type_maintenance_enabled", EDGE_TYPES_ENABLED_DDL)):
            if await conn.fetchval("SELECT to_regclass($1)", name) is None:
                print(f"database: create {name}")
                if args.apply:
                    await conn.execute(ddl)
        has_table = await conn.fetchval("SELECT to_regclass($1)", EDGE_TYPES_TABLE) is not None
        enabled = has_table and await edge_types_enabled(conn)
        first = bool(args.all) and not enabled
        if first:
            print("first run: clear every mark, reconcile every space, then set the flag")
            if args.apply and has_table:
                await conn.execute(f"DELETE FROM {EDGE_TYPES_TABLE}")
        elif not enabled:
            print("the flag is not set: this run reconciles, and only --all may set it")

        spaces = args.space or [r["space_id"] for r in await conn.fetch(
            "SELECT space_id FROM space ORDER BY space_id")]
        todo = unmarked = 0
        for sid in spaces:
            t_edge = f"{space_prefix(sid)}_edge"
            if await conn.fetchval("SELECT to_regclass($1)", t_edge) is None:
                print(f"  skip {sid}: no edge table")
                continue
            if has_table and not first:
                row = await conn.fetchrow(
                    f"SELECT dirty_gen, clean_gen FROM {EDGE_TYPES_TABLE} WHERE space_id = $1", sid)
                if row is not None and row["dirty_gen"] == row["clean_gen"]:
                    print(f"  {sid}: already marked")
                    continue
            todo += 1
            if not args.apply:
                print(f"  {sid}: would reconcile {t_edge} and mark")
                continue
            t0 = time.time()
            out = await reconcile_edge_types(conn, sid)
            if not out["marked"]:
                unmarked += 1
            print(f"  {sid}: {out['fixed']} row(s) fixed, "
                  f"{'marked' if out['marked'] else 'NOT marked (written meanwhile; re-run)'} "
                  f"in {time.time() - t0:.1f}s")

        if first and args.apply:
            if unmarked:
                print(f"\n{unmarked} space(s) not marked: the flag is NOT set. Re-run.")
                return 1
            await enable_edge_types(conn)
            print("\nflag set: marked spaces' edge types are read off the column")
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
    g.add_argument("--disable", action="store_true",
                   help="clear the flag and every mark (after a rollback)")
    ap.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    add_pg_arguments(ap)
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
