#!/usr/bin/env python3
"""Move a space's objects onto its storage key (`vgs_<key>_…`), or back.

See `vitalgraph/db/sparql_sql/space_rekey.py`. Catalogue-only, one transaction
per space, all or nothing. Names of auto-generated objects come from a fresh
create under the key, so a re-keyed space matches one created under it.

THREE MODES

  (default)     dry run: print the plan, change nothing.
  --round-trip  re-key and move back inside ONE transaction, then roll it all
                back. Times the move on real data and proves it reversible;
                the space is never visible under its key. Holds ACCESS
                EXCLUSIVE on every object of the space for the duration.
  --apply       commit the move. BEFORE THE CUTOVER THIS MAKES THE SPACE
                UNREACHABLE, because the code still names its objects by id;
                refused unless --cutover is also given.

`--reverse --apply` moves a re-keyed space back to its id prefix. The key stays
recorded.

RUN AS THE TABLES' OWNER, with writers stopped for an --apply.

    python scripts/rekey_space.py --space lead_prod
    python scripts/rekey_space.py --space lead_prod --round-trip
    python scripts/rekey_space.py --all --round-trip
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.space_rekey import rekey_space, round_trip  # noqa: E402
from vitalgraph.db.sparql_sql.space_rename import SpaceRenameRefused  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    m = ap.add_mutually_exclusive_group()
    m.add_argument("--round-trip", action="store_true")
    m.add_argument("--apply", action="store_true")
    ap.add_argument("--reverse", action="store_true",
                    help="move from vgs_<key> back to the id prefix")
    ap.add_argument("--cutover", action="store_true",
                    help="required with --apply: the code reads keyed names")
    ap.add_argument("--lock-timeout-ms", type=int, default=5000)
    ap.add_argument("--show-sql", action="store_true")
    add_pg_arguments(ap)
    a = ap.parse_args()

    if a.apply and not a.reverse and not a.cutover:
        print("REFUSED: until the cutover the code names a space's objects by "
              "its id, so a committed re-key makes the space unreachable. Use "
              "--round-trip to measure it, or add --cutover if this IS the "
              "cutover.")
        return 2
    if a.round_trip and a.reverse:
        print("--round-trip already goes there and back")
        return 2

    print(f"\U0001F5C4  target: {describe_target(a)}", flush=True)
    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    failed = []
    try:
        spaces = ([r["space_id"] for r in await conn.fetch(
            "SELECT space_id FROM space ORDER BY space_id")]
            if a.all else [a.space])
        for sp in spaces:
            try:
                if a.round_trip:
                    r = await round_trip(conn, sp, lock_timeout_ms=a.lock_timeout_ms)
                    ok = all(r["restored"].values())
                    print(f"{sp}: key {r['key']}  {r['statements']} statements  "
                          f"plan {r['plan_forward_s']:.2f}s  "
                          f"forward {r['forward_s']:.2f}s  "
                          f"back {r['reverse_s']:.2f}s  "
                          f"{'restored' if ok else 'NOT RESTORED'}  "
                          f"{len(r['fresh_named'])} truncated name(s) re-derived")
                    if not ok:
                        failed.append(sp)
                else:
                    r = await rekey_space(conn, sp, reverse=a.reverse,
                                          dry_run=not a.apply,
                                          lock_timeout_ms=a.lock_timeout_ms)
                    print(f"{sp}: {r['from_prefix']} -> {r['to_prefix']}  "
                          f"{r['statements']} statements {json.dumps(r['by_kind'])}"
                          + (f"  done in {r['seconds']:.2f}s" if a.apply else
                             "  (dry run)"))
                    if a.show_sql and not a.apply:
                        for s in r["sql"]:
                            print("    " + s)
            except SpaceRenameRefused as e:
                failed.append(sp)
                print(f"{sp}: REFUSED — {e}")
    finally:
        await conn.close()
    if failed:
        print(f"\n{len(failed)} space(s) failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
