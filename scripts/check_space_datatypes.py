#!/usr/bin/env python3
"""Report spaces whose `datatype` table does not match `STANDARD_DATATYPES`.

Four helpers derived `datatype_id` values by enumerating `STANDARD_DATATYPES`
in order, on the assumption that every space seeded those 40 rows at creation.
Measured 2026-08-23: 161 of 164 spaces hold `xsd:string` at id 1 and three do
not hold it at all. `sp_geo_test` has `vital-core#geoLocation` at id 1.

The query-side uses now resolve ids per space, so they are correct either way
(`issues/126` category A). What remains is category B: `num_val` and `dt_val`
are `GENERATED ALWAYS AS (...) STORED` with the id list baked into the column
definition. In a space whose ids do not match, that column computes the wrong
thing — and because the loader appends unknown datatypes with the next serial
id, the ids a broken space hands out next are exactly the ones the generated
column already claims are numeric.

This script does not repair anything. Repair cannot be a metadata change:
`term.datatype_id` already references these ids, so it means remapping every
term or recreating the space. Detection first, deliberately.

    python scripts/check_space_datatypes.py --all
    python scripts/check_space_datatypes.py --space sp_lead_synth_100k

Exit status is 1 if any space is off, so it can gate a pipeline.
Connection comes from the VG_TEST_PG_* variables, same as
`scripts/ensure_space_indexes.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import pg_kwargs  # noqa: E402

_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

OK, EMPTY, MISSING_STRING, WRONG_ID = "ok", "empty", "no-xsd-string", "wrong-id"


async def check_space(conn, space: str):
    """Return (status, detail) for one space's datatype table.

    Compares against the positional ids the generated columns assume, which is
    the thing that has to hold — not merely that the table is non-empty.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import STANDARD_DATATYPES

    expected = {uri: i for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)}
    rows = await conn.fetch(
        f"SELECT datatype_id, datatype_uri FROM {space}_datatype ORDER BY datatype_id")
    if not rows:
        return EMPTY, "0 rows — nothing was seeded"

    actual = {r["datatype_uri"]: r["datatype_id"] for r in rows}
    if _XSD_STRING not in actual:
        first = rows[0]
        return MISSING_STRING, (f"no xsd:string row; id 1 is "
                                f"{first['datatype_uri']}")

    off = [(uri, expected[uri], actual[uri])
           for uri in expected if uri in actual and actual[uri] != expected[uri]]
    if off:
        uri, exp, act = off[0]
        return WRONG_ID, (f"{len(off)} id(s) differ, e.g. {uri} "
                          f"expected {exp} got {act}")
    return OK, f"{len(rows)} rows, standard ids intact"


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space", help="check one space")
    g.add_argument("--all", action="store_true", help="sweep every space")
    ap.add_argument("--quiet", action="store_true",
                    help="print only the spaces that are off")
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

        bad = []
        for space in spaces:
            try:
                status, detail = await check_space(conn, space)
            except Exception as e:                     # missing table, permissions
                status, detail = "error", str(e).split("\n")[0]
            if status != OK:
                bad.append((space, status, detail))
                print(f"  {status:14} {space}: {detail}")
            elif not a.quiet:
                print(f"  {OK:14} {space}: {detail}")

        print(f"\nchecked {len(spaces)} space(s), {len(bad)} off")
        if bad:
            print("\nThese spaces' num_val/dt_val generated columns reference ids\n"
                  "that mean something else there. See issues/126 — do not repair\n"
                  "by reordering STANDARD_DATATYPES, which would silently\n"
                  "reinterpret term.datatype_id across every healthy space.")
            return 1
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
