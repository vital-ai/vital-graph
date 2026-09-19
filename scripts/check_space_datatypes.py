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

# Off, but nothing in the space can act on it. Reported and NOT counted as a
# failure, because an exit code that fires where there is no defect is an exit
# code that gets ignored.
NOT_EXPOSED = "off-inert"

# Every id present is CORRECT, but the tail of `STANDARD_DATATYPES` was never
# seeded. Not wrong today and not counted as a failure; it is a trap that has
# not sprung yet, and the repair script tops it up as a pure INSERT.
INCOMPLETE = "incomplete"


async def _has_positional_consumer(conn, space: str) -> bool:
    """Does this space have the generated columns that bake positional ids?

    `num_val` and `dt_val` are `GENERATED ALWAYS AS (...) STORED` with the id
    list written into the column definition, and they are the ONLY thing left
    that reads a datatype id positionally — the query side resolves per space
    through `ctx.dt_ids_for_uris` (`issues/126` category A). A space without
    them can have every id shifted and nothing will act on it.

    Measured 2026-09-18: six `vitalgraph2__` spaces on the host `vitalgraphdb`
    report 29 differing ids each, and all six are a LEGACY schema — partitioned
    term tables with no generated columns at all. Repairing them would have
    remapped millions of rows to fix a value nothing reads. Without this check
    the sweep exits 1 on a database where nothing is wrong.
    """
    return bool(await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_attribute a JOIN pg_class c "
        "ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = $1 "
        "AND a.attgenerated <> '' AND a.attname IN ('num_val', 'dt_val'))",
        f"{space}_term"))


async def check_space(conn, space: str):
    """Return (status, detail) for one space's datatype table.

    Compares against the positional ids the generated columns assume, which is
    the thing that has to hold — not merely that the table is non-empty.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import STANDARD_DATATYPES

    expected = {uri: i for i, (uri, _n) in enumerate(STANDARD_DATATYPES, start=1)}
    rows = await conn.fetch(
        f"SELECT datatype_id, datatype_uri FROM {space}_datatype ORDER BY datatype_id")
    exposed = await _has_positional_consumer(conn, space)
    if not rows:
        return (EMPTY if exposed else NOT_EXPOSED), (
            "0 rows — nothing was seeded"
            + ("" if exposed else "; no num_val/dt_val here, so nothing reads "
                                  "these ids positionally"))

    actual = {r["datatype_uri"]: r["datatype_id"] for r in rows}
    if _XSD_STRING not in actual:
        first = rows[0]
        return (MISSING_STRING if exposed else NOT_EXPOSED), (
            f"no xsd:string row; id 1 is {first['datatype_uri']}"
            + ("" if exposed else "; legacy schema, no generated columns"))

    off = [(uri, expected[uri], actual[uri])
           for uri in expected if uri in actual and actual[uri] != expected[uri]]
    if off:
        uri, exp, act = off[0]
        return (WRONG_ID if exposed else NOT_EXPOSED), (
            f"{len(off)} id(s) differ, e.g. {uri} expected {exp} got {act}"
            + ("" if exposed else "; legacy schema, no generated columns, so "
                                  "nothing acts on these ids"))

    # Correct so far, but is it COMPLETE? Everything above compares only the
    # ids that are THERE, so a space holding positions 1..38 of a 40-entry list
    # passes every check and is still a trap: the three write paths append an
    # unknown datatype with the next serial id
    # (`data_import_impl.py:85`, `emit_update.py:92`,
    # `kg_server_properties.py:316`), and nothing seeds a space after creation.
    # So whichever of the missing entries is stored FIRST takes the lowest free
    # id, which is its canonical position only by luck of arrival order.
    #
    # Measured 2026-09-18: three production spaces are in exactly this state,
    # missing positions 39 and 40 — the two geo datatypes, added to
    # `STANDARD_DATATYPES` after those spaces were created. Load `geoLocation`
    # before `wktLiteral` and they land transposed.
    # Reported whether or not the space has the generated columns. The
    # `exposed` downgrade above is about WRONGNESS, which only matters if
    # something reads the ids. Incompleteness is about the table and its
    # SEQUENCE, and the append-by-next-serial hazard is the same either way.
    missing = sorted(expected[uri] for uri in expected if uri not in actual)
    if missing:
        contiguous_tail = missing == list(range(min(missing), len(expected) + 1))
        return INCOMPLETE, (
            f"{len(rows)} rows, ids intact, but position(s) {missing} were "
            f"never seeded"
            + (" (tail — nothing reads them positionally today, but the next "
               "one stored takes the lowest free id by arrival order)"
               if contiguous_tail else
               " (GAP, not a tail — an append will land INSIDE the standard "
               "range)"))
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
            if status in (NOT_EXPOSED, INCOMPLETE):
                # Printed, never counted: neither is wrong TODAY, and a gate
                # that fails where there is no defect gets switched off.
                print(f"  {status:14} {space}: {detail}")
            elif status != OK:
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
