#!/usr/bin/env python3
"""Bring an existing space up to the current table schema.

Spaces are created once and the schema keeps moving. Nothing reconciles the two,
so a space carries whatever `sparql_sql_schema.py` looked like on the day it was
made. Measured on the local cluster, 2026-08-14: of 77 spaces with a geo table,
**21 lack `geo.source_slot_uuid`** and **18 have no `fuzzy_band` table at all**.

That is not cosmetic. `tests/performance/test_fixture_indexes_match_schema.py`
fails on `sp_sql_lead_dataset` for exactly this, and its docstring explains why
it matters: a benchmark measures a CONFIGURATION, and if that configuration is
not the one the schema produces, the number is about nothing. The same class of
gap hides real capability loss — `wordnet_frames` has no `rdf_value_stats` at
all, so every range criterion there goes unmeasured and the traversal pipeline
silently declines to optimise.

WHAT IT WILL AND WILL NOT DO

Missing TABLES are created. The schema's own `CREATE TABLE IF NOT EXISTS`
statements are idempotent, so this is safe to re-run and cannot disturb a table
that already exists.

A table whose COLUMNS differ is a harder case, because the fix depends on what
the table holds:

  Tables on the DERIVED allowlist are dropped and recreated. Each is rebuilt
  from rdf_quad, so the definition is the only thing of value in them, and
  recreating is how a structural change lands at all — the lead-dataset geo
  table is not merely missing a column, it has the OLD primary key
  (subject_uuid, context_uuid) where the schema now has a geo_id serial plus a
  wider UNIQUE, and no ALTER sequence reconciles that safely.

  EVERYTHING ELSE is reported and left alone. That is an allowlist rather than a
  denylist because the safety default matters more than the coverage: primary
  data (rdf_quad, term), configuration (geo_config), and registrations
  (vector_index) are all unrecoverable by a resync, and vector_index in
  particular drifted on every older space — a denylist would have deleted index
  registrations while "repairing" the schema.

RUN THE RESYNC AFTERWARDS. Recreating a derived table leaves it EMPTY. This
script does not repopulate, because the resync is a long operation with its own
progress reporting and belongs under the caller's control:

    vitalgraphdb-admin  resync <space>          (or resync_all_auxiliary_tables)

Usage:

    python scripts/migrate_space_schema.py --space sp_sql_lead_dataset --dry-run
    python scripts/migrate_space_schema.py --space sp_sql_lead_dataset
    python scripts/migrate_space_schema.py --all --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_space_schema")

# Tables this script may DROP and recreate, because they are rebuilt from
# rdf_quad and hold nothing else.
#
# An ALLOWLIST, deliberately. The first version listed the tables to PROTECT and
# treated everything else as droppable, which had the safety default backwards:
# `vector_index` holds index REGISTRATIONS (name, dimensions, provider, model)
# that no resync can reconstruct, and it drifted on every older space — so a
# denylist would have destroyed configuration while "repairing" a schema. With
# an allowlist, a table added later is left alone until someone decides it is
# rebuildable.
DERIVED = {
    "geo",                    # resync_all rebuilds from geo-typed quads
    "fuzzy_band", "fuzzy_phonetic_band",   # rebuilt by the fuzzy populator
    "rdf_stats", "rdf_pred_stats",         # resync_stats_tables
    "rdf_value_stats", "edge_fanout",      # resync_all
}

# NOT in DERIVED on purpose:
#   rdf_quad, term, datatype   primary data; a change needs a real backfill
#   geo_config, vector_index   configuration and registrations, not derived
#   edge, frame_entity         derived, but the edge resync is known to
#                              under-count (~25% on one production space), so
#                              dropping one trades a schema gap for a data gap.
#                              Reported for a human instead.

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>[A-Za-z0-9_.\"]+)\s*\(",
    re.IGNORECASE)

# Line-leading tokens that introduce a CONSTRAINT rather than a column.
_NOT_A_COLUMN = {
    "primary", "unique", "foreign", "constraint", "check", "exclude", "like",
}


def _strip_comments(sql: str) -> str:
    """Remove `--` line comments, ignoring `--` inside a string literal.

    Not optional. The first version of this parser skipped it and read the prose
    in the edge table's comment as five column names, so EVERY space looked like
    it had a drifted `edge` table. Acting on that would have dropped a 112k-row
    derived table on 77 spaces to fix nothing — and the edge resync is itself
    known to under-count, so the "rebuild" would not have been clean either.
    """
    out, i, in_str = [], 0, False
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            in_str = not in_str
        if not in_str and ch == "-" and sql[i + 1:i + 2] == "-":
            nl = sql.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top_level(body: str):
    """Split a CREATE TABLE body on commas at paren depth 0, outside strings.

    Brackets count as depth, not just parens: `geo_config` defaults three
    columns to `ARRAY[...]` literals whose commas are nested in `[]` and would
    otherwise split the body mid-default, reporting a column named
    `'http://vital.ai/ontology/vital-core#geoLocation'`. The string check is
    needed for the same defaults.
    """
    depth, cur, out, in_str = 0, [], [], False
    for ch in body:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
        if ch == "," and depth == 0 and not in_str:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def expected_columns(space_id: str):
    """table name -> [column names], from the schema's own DDL.

    Parses the statements the schema generates rather than maintaining a second
    list of columns here. A hand-kept copy of a schema is precisely what drifted
    to produce this script's reason for existing.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    out = {}
    for stmt in SparqlSQLSchema().create_space_tables_sql(space_id):
        m = _CREATE_TABLE_RE.search(stmt or "")
        if not m:
            continue
        table = m.group("table").strip('"').split(".")[-1]
        body = _strip_comments(stmt)[
            _CREATE_TABLE_RE.search(_strip_comments(stmt)).end():]
        depth, end = 1, None
        for i, ch in enumerate(body):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            continue
        cols = []
        for part in _split_top_level(body[:end]):
            tok = part.strip().split(None, 1)
            if not tok:
                continue
            name = tok[0].strip('"')
            if name.lower() in _NOT_A_COLUMN:
                continue
            cols.append(name)
        if cols:
            out[table] = cols
    return out


async def actual_columns(conn, tables):
    rows = await conn.fetch(
        "SELECT table_name, column_name, ordinal_position "
        "FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name = ANY($1::text[]) "
        "ORDER BY table_name, ordinal_position", list(tables))
    out = {}
    for r in rows:
        out.setdefault(r["table_name"], []).append(r["column_name"])
    return out


def _suffix(space_id: str, table: str) -> str:
    return table[len(space_id) + 1:] if table.startswith(space_id + "_") else table


async def migrate_space(conn, space_id: str, dry_run: bool = True) -> dict:
    """Reconcile one space with the schema. Returns a summary dict."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    expected = expected_columns(space_id)
    if not expected:
        raise RuntimeError("schema produced no CREATE TABLE statements to compare")

    actual = await actual_columns(conn, expected.keys())
    missing_tables = sorted(set(expected) - set(actual))
    drifted, refused = [], []

    for table, want in sorted(expected.items()):
        have = actual.get(table)
        if have is None:
            continue
        if set(want) - set(have):
            bucket = drifted if _suffix(space_id, table) in DERIVED else refused
            bucket.append((table, sorted(set(want) - set(have))))

    summary = {
        "space": space_id,
        "missing_tables": missing_tables,
        "recreated": [t for t, _ in drifted],
        "needs_manual_migration": refused,
    }
    if dry_run:
        return summary

    # Drop drifted DERIVED tables first, so the CREATE pass below rebuilds them
    # at the current definition. CASCADE frees dependent indexes and views.
    for table, _cols in drifted:
        logger.info("%s: dropping derived table %s to recreate at current schema",
                    space_id, table)
        await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Every CREATE is IF NOT EXISTS, so this creates what is absent and leaves
    # everything else untouched.
    for stmt in SparqlSQLSchema().create_space_tables_sql(space_id):
        try:
            await conn.execute(stmt)
        except Exception as exc:
            logger.warning("%s: table statement failed (continuing): %s",
                           space_id, exc)

    for stmt in SparqlSQLSchema().create_space_indexes_sql(space_id):
        try:
            await conn.execute(stmt)
        except Exception as exc:
            logger.debug("%s: index statement skipped: %s", space_id, exc)

    return summary


async def spaces_on(conn):
    return [r["tablename"][: -len("_rdf_quad")] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_rdf\\_quad' ORDER BY tablename")]


async def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space", help="space id to migrate")
    g.add_argument("--all", action="store_true", help="every space in the database")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and make no changes")
    add_pg_arguments(ap)
    args = ap.parse_args()
    print(f"🗄  target: {describe_target(args)}", flush=True)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        targets = await spaces_on(conn) if args.all else [args.space]
        changed = 0
        for sid in targets:
            try:
                s = await migrate_space(conn, sid, dry_run=args.dry_run)
            except Exception as exc:
                logger.warning("%-40s ERROR %s", sid, exc)
                continue
            if not (s["missing_tables"] or s["recreated"]
                    or s["needs_manual_migration"]):
                continue
            changed += 1
            verb = "would create" if args.dry_run else "created"
            logger.info("%s", sid)
            if s["missing_tables"]:
                logger.info("  %s: %s", verb, ", ".join(
                    _suffix(sid, t) for t in s["missing_tables"]))
            if s["recreated"]:
                logger.info("  %s derived (drops data, resync to repopulate): %s",
                            "would recreate" if args.dry_run else "recreated",
                            ", ".join(_suffix(sid, t) for t in s["recreated"]))
            for t, cols in s["needs_manual_migration"]:
                logger.info("  MANUAL: %s is missing %s — not rebuildable from "
                            "rdf_quad, so it needs a considered migration",
                            _suffix(sid, t), ", ".join(cols))
        logger.info("\n%d space(s) %s of %d examined", changed,
                    "need changes" if args.dry_run else "changed", len(targets))
        if not args.dry_run and changed:
            logger.info("Recreated derived tables are EMPTY — run the resync to "
                        "repopulate them.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
