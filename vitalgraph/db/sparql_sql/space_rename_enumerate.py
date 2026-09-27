"""Enumerate every catalogue object that names a space — `issues/232` step 1.

Renaming a space is the documented remedy for an over-long space id
(`sparql_sql_schema.py` refuses one and says to rename) and does not exist. This
is the first half of building it, and the issue's stated order: a DRY-RUN
enumerator, before anything that writes.

It is useful on its own, which is why it comes first. It is the audit that answers
"is any existing space already carrying mismatched index or constraint names?" —
and because `ALTER TABLE … RENAME TO` renames only the table, that question has a
real chance of being yes wherever a table has ever been renamed by hand.

MEASURED, NOT ASSUMED. `issues/232` listed as "not established" whether renaming a
partitioned parent renames its children. It does not, and the same experiment
showed the damage is wider than the issue recorded. On PostgreSQL 18, after
`ALTER TABLE ren_old RENAME TO ren_new`:

    tables       ren_new, and ren_old_p0 — the PARTITION CHILD keeps its name
    indexes      idx_ren_old_val, ren_old_pkey, ren_old_p0_val_idx, …
    constraints  ren_old_pkey, ren_old_ctx_val_key, ren_old_p0_pkey, and
                 ren_old_ctx_not_null — PG18 NAMES NOT-NULL CONSTRAINTS, which
                 the issue's "~26 constraints" estimate did not account for
    sequences    ren_old_id_seq

Everything keeps WORKING, because the catalogue links by oid. That is exactly what
makes it dangerous: the names silently stop describing reality, and the next
`CREATE INDEX IF NOT EXISTS idx_{new}_…` finds no index by that name and builds a
SECOND one alongside the old — a duplicate index on a large table, created
silently.

So a rename is four object classes, not one, and this enumerates all four.

DERIVED FROM THE CATALOGUE, NOT FROM A LIST. A hardcoded list is how the three
retired suffixes (`frame_entity`, `vector_mapping`, `vector_mapping_property`)
get orphaned under the old name, and it cannot know the dynamic `_vec_{name}` /
`_fts_{name}` tables at all.

PREFIX SHADOWING IS THE WHOLE DIFFICULTY of deriving it. `data` is a prefix of
`data_orig`, and renaming `data` to `data_orig` is the issue's own example — so
attribution uses the same longest-prefix rule as
`SparqlSQLSchema.orphan_tables_for_space`, reused rather than reimplemented,
because two rules that are supposed to agree will not.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)


def _owned(names: List[str], space_id: str, other_ids: List[str]) -> List[str]:
    """`names` belonging to *space_id*, by the shared longest-prefix rule.

    Also accepts a name equal to the space id itself, which the table rule does
    not need but trigger and function names can produce.
    """
    return SparqlSQLSchema.orphan_tables_for_space(names, space_id, other_ids)


async def _all_space_ids(conn) -> List[str]:
    try:
        return [r["space_id"] for r in
                await conn.fetch("SELECT space_id FROM space")]
    except Exception:
        # No registry (a bare database, or a test fixture). Attribution then has
        # no shadowing information, which is reported rather than hidden: see
        # `shadowing_unknown` in the result.
        return []


async def enumerate_space_objects(conn, space_id: str) -> Dict[str, Any]:
    """Every catalogue object whose NAME contains *space_id* as its prefix.

    Read-only. Returns object names grouped by class, plus the bookkeeping a
    caller needs to trust the answer:

        tables, partition_children, indexes, constraints, sequences,
        functions, triggers            — the four-plus object classes
        shadowed_by                    — other space ids this one is a prefix of
        shadowing_unknown              — True when the `space` registry was
                                         unreadable, so attribution could not
                                         exclude a longer-named space
        mismatched                     — objects whose name does NOT start with
                                         the space id but which belong to a table
                                         that does: evidence of a PREVIOUS rename
                                         that only renamed tables
    """
    other_ids = [s for s in await _all_space_ids(conn) if s != space_id]
    prefix = f"{space_id}_"
    result: Dict[str, Any] = {
        "space_id": space_id,
        "shadowed_by": sorted(s for s in other_ids if s.startswith(prefix)),
        "shadowing_unknown": not other_ids,
    }

    tables = _owned([r["tablename"] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")],
        space_id, other_ids)
    # Partition children are reported SEPARATELY because they need their own
    # ALTER: renaming the parent leaves them behind, which is the measured fact
    # in the module docstring.
    children = set()
    if tables:
        for r in await conn.fetch(
                "SELECT c.relname AS child FROM pg_inherits i "
                "JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent "
                "WHERE p.relname = ANY($1)", tables):
            children.add(r["child"])
    result["tables"] = sorted(set(tables) - children)
    result["partition_children"] = sorted(children)

    owned_tables = set(tables) | children

    result["indexes"] = sorted({r["indexname"] for r in await conn.fetch(
        "SELECT indexname, tablename FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename = ANY($1)",
        sorted(owned_tables))}) if owned_tables else []

    result["constraints"] = sorted({r["conname"] for r in await conn.fetch(
        "SELECT con.conname FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid = con.conrelid "
        "WHERE rel.relname = ANY($1)", sorted(owned_tables))}
    ) if owned_tables else []

    # Sequences are found by OWNERSHIP, not by name. A sequence behind a
    # BIGSERIAL is named from the table, so the name usually matches — but after
    # a partial rename it does not, and that case is the one worth finding.
    result["sequences"] = sorted({r["seq"] for r in await conn.fetch(
        "SELECT s.relname AS seq FROM pg_class s "
        "JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a' "
        "JOIN pg_class t ON t.oid = d.refobjid "
        "WHERE s.relkind = 'S' AND t.relname = ANY($1)",
        sorted(owned_tables))}) if owned_tables else []

    result["triggers"] = sorted({r["tgname"] for r in await conn.fetch(
        "SELECT tg.tgname FROM pg_trigger tg "
        "JOIN pg_class rel ON rel.oid = tg.tgrelid "
        "WHERE NOT tg.tgisinternal AND rel.relname = ANY($1)",
        sorted(owned_tables))}) if owned_tables else []

    # Functions are matched by NAME only — there is no dependency edge from a
    # trigger function to the space. The FTS trigger functions are
    # `{space_id}_fts_{name}_tsv_trigger`.
    result["functions"] = _owned([r["proname"] for r in await conn.fetch(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n "
        "ON n.oid = p.pronamespace WHERE n.nspname = 'public'")],
        space_id, other_ids)

    # EVIDENCE OF A PREVIOUS PARTIAL RENAME. Anything attached to this space's
    # tables whose own name does not start with the space id was left behind by a
    # rename that only renamed tables — the exact damage this whole issue is
    # about, and the reason the enumerator is useful before the rename exists.
    # The test is CONTAINMENT, not a prefix. Names carry decorators the space id
    # sits behind — `idx_{space}_…`, `trg_{space}_fts_…` — and an auto-named
    # constraint is `{space}_term_pkey`. A prefix test rejected all 105 indexes of
    # every healthy space, i.e. it cried wolf on everything, which is worse than
    # not checking: an audit nobody believes is an audit nobody runs.
    result["mismatched"] = sorted(
        name for cls in ("indexes", "constraints", "sequences", "triggers")
        for name in result[cls] if prefix not in name)

    result["total"] = sum(len(result[k]) for k in
                          ("tables", "partition_children", "indexes",
                           "constraints", "sequences", "functions", "triggers"))
    return result


def format_enumeration(result: Dict[str, Any]) -> str:
    """A reviewable summary — this is an audit tool, so it has to read well."""
    lines = [f"space: {result['space_id']}  ({result['total']} objects)"]
    for cls in ("tables", "partition_children", "indexes", "constraints",
                "sequences", "functions", "triggers"):
        lines.append(f"  {cls:<20} {len(result[cls])}")
    if result["shadowed_by"]:
        lines.append(f"  NOTE: this id is a prefix of {result['shadowed_by']} — "
                     f"their objects are excluded")
    if result["shadowing_unknown"]:
        lines.append("  WARNING: the `space` registry was unreadable, so a "
                     "longer-named space's objects could NOT be excluded")
    if result["mismatched"]:
        lines.append(f"  MISMATCHED ({len(result['mismatched'])}) — attached to "
                     f"this space but not named for it, i.e. a previous rename "
                     f"renamed only the tables:")
        for name in result["mismatched"][:20]:
            lines.append(f"      {name}")
        if len(result["mismatched"]) > 20:
            lines.append(f"      … and {len(result['mismatched']) - 20} more")
    return "\n".join(lines)
