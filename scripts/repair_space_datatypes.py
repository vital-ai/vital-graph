#!/usr/bin/env python3
"""Put a space's `datatype` table back on the standard positional ids.

`scripts/check_space_datatypes.py` finds spaces whose ids do not match
`STANDARD_DATATYPES`. This repairs them. `issues/126` step 3, which was left
"deliberately not attempted" on the strength of this reasoning:

    Backfilling ids is not possible in place — they are referenced by
    `term.datatype_id` — so a repair means rewriting the datatype table AND
    remapping every term, or recreating the space.

The second half is right and the first half is not, which is why this script
exists. Measured 2026-09-18 on the three known-off spaces: there is NO foreign
key from `{space}_term.datatype_id` to `{space}_datatype`, so the remap is an
UPDATE rather than a constraint fight. And the volume the word "every" implies
was not there either —

    sp_dedup_test   140 terms,   0 carrying a datatype_id
    sp_vgeo_e2e      15 terms,   0 carrying a datatype_id
    sp_geo_test     187 terms,  45 carrying a datatype_id

— so two of the three need no remap at all and the third needs 45 rows. The
cost estimate that deferred this was the 10.4M-row `ADD COLUMN ... STORED`
rewrite quoted at `sparql_sql_schema.py:136`. That is the cost of adding a
generated column, which this does not do: the columns already exist and their
definitions are already correct. It is the DATA underneath them that is wrong.

WHY IT IS WORTH DOING RATHER THAN LEAVING. The ids are not merely wrong, they
are on a collision course. The loader appends unknown datatypes with the next
serial id, and `sp_geo_test` sits at 2, so the next datatype stored there takes
id 3 — `xsd:decimal`, which IS in the array `num_val` calls numeric. The next
19 land in that array too. At that point wrong values are materialized on disk
and indexed, and numeric range filters match them. Repairing costs 45 UPDATEs
today.

WHAT IT DOES NOT DO. It does not reorder `STANDARD_DATATYPES` — those ids are
persisted in `term.datatype_id` across every healthy space and reordering
silently reinterprets all of them. It does not touch a space the checker calls
OK. It refuses a space whose terms reference a datatype row that is not there,
because the URI that id MEANT cannot be recovered and a guess would be
materialized.

    python scripts/repair_space_datatypes.py --all               # dry run
    python scripts/repair_space_datatypes.py --space sp_geo_test --apply

Connection comes from the VG_TEST_PG_* variables, same as the checker.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import pg_kwargs  # noqa: E402

from check_space_datatypes import NOT_EXPOSED, OK, check_space  # noqa: E402


async def plan_repair(conn, space: str):
    """What this space needs, as (remap, final_rows, notes), or None if OK.

    `remap` is {old_id: new_id} for ids a term actually uses. `final_rows` is
    the full (id, uri) list the table should end up holding.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import STANDARD_DATATYPES

    canonical = [(i, uri) for i, (uri, _n) in enumerate(STANDARD_DATATYPES, 1)]
    want = {uri: i for i, uri in canonical}

    rows = await conn.fetch(
        f"SELECT datatype_id, datatype_uri FROM {space}_datatype")
    have = {r["datatype_id"]: r["datatype_uri"] for r in rows}

    used = {r["datatype_id"]: r["n"] for r in await conn.fetch(
        f"SELECT datatype_id, count(*) AS n FROM {space}_term "
        f"WHERE datatype_id IS NOT NULL GROUP BY datatype_id")}

    # A term pointing at an id with no row: the URI it meant is gone. Refuse.
    orphans = {i: n for i, n in used.items() if i not in have}
    if orphans:
        raise RuntimeError(
            f"{space}: {sum(orphans.values())} term(s) reference datatype id(s) "
            f"{sorted(orphans)} that have no row in {space}_datatype. What "
            f"those ids meant cannot be recovered, and this script will not "
            f"guess a datatype that would then be materialized into num_val.")

    # Non-standard URIs already present keep their identity and go after 40.
    extra = sorted(uri for uri in have.values() if uri not in want)
    final = list(canonical) + [(len(canonical) + k, uri)
                               for k, uri in enumerate(extra, start=1)]
    new_of = {uri: i for i, uri in final}

    remap = {old: new_of[uri] for old, uri in have.items()
             if old in used and new_of[uri] != old}
    notes = [f"{len(rows)} row(s) now -> {len(final)}",
             f"{sum(used.values())} term(s) carry a datatype_id",
             f"{len(remap)} id(s) to remap"]
    if extra:
        notes.append(f"preserving {len(extra)} non-standard uri(s) after "
                     f"{len(canonical)}")
    return remap, final, notes


async def apply_repair(conn, space: str, remap, final) -> None:
    """One transaction: remap terms, rewrite the table, reset the sequence."""
    async with conn.transaction():
        # Two-step through a disjoint range. A direct UPDATE can collide when
        # the remap is a permutation (id 1 -> 40 while something else -> 1),
        # and the PK on the datatype table would reject the intermediate state.
        OFFSET = 1_000_000
        for old, new in remap.items():
            await conn.execute(
                f"UPDATE {space}_term SET datatype_id = $1 "
                f"WHERE datatype_id = $2", new + OFFSET, old)
        if remap:
            await conn.execute(
                f"UPDATE {space}_term SET datatype_id = datatype_id - $1 "
                f"WHERE datatype_id > $1", OFFSET)

        await conn.execute(f"DELETE FROM {space}_datatype")
        await conn.executemany(
            f"INSERT INTO {space}_datatype (datatype_id, datatype_uri) "
            f"VALUES ($1, $2)", final)

        # The sequence must clear the seeded block, or the loader's next
        # append reuses a standard id and puts the space straight back into
        # the state this repaired.
        await conn.execute(
            f"SELECT setval('{space}_datatype_datatype_id_seq', $1, true)",
            max(i for i, _u in final))


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space", help="repair one space")
    g.add_argument("--all", action="store_true",
                   help="repair every space the checker reports as off")
    ap.add_argument("--apply", action="store_true",
                    help="write the change; without it this is a dry run")
    a = ap.parse_args()

    import asyncpg
    conn = await asyncpg.connect(**pg_kwargs())
    try:
        if a.all:
            spaces = [r["table_name"][: -len("_datatype")] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                r"WHERE table_name LIKE '%\_datatype' ORDER BY 1")]
        else:
            spaces = [a.space]

        repaired, failed = 0, 0
        for space in spaces:
            status, detail = await check_space(conn, space)
            if status == OK:
                continue
            if status == NOT_EXPOSED:
                # Off, but the space has no `num_val`/`dt_val` to act on it, so
                # a remap would rewrite rows to correct a value nothing reads.
                # Six legacy `vitalgraph2__` spaces are in this state and one
                # of them carries 3.4M terms.
                print(f"  {space}: skipped — {detail}")
                continue
            print(f"  {space}: {status} — {detail}")
            try:
                remap, final, notes = await plan_repair(conn, space)
            except RuntimeError as e:
                print(f"    REFUSED: {e}")
                failed += 1
                continue
            for n in notes:
                print(f"    {n}")
            for old, new in sorted(remap.items()):
                print(f"    remap id {old} -> {new}")
            if not a.apply:
                print("    (dry run — pass --apply to write)")
                continue
            await apply_repair(conn, space, remap, final)
            after, detail_after = await check_space(conn, space)
            if after != OK:
                print(f"    STILL OFF after repair: {detail_after}")
                failed += 1
            else:
                print(f"    repaired — {detail_after}")
                repaired += 1

        print(f"\n{len(spaces)} space(s) examined, {repaired} repaired, "
              f"{failed} failed")
        return 1 if failed else 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
