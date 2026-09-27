"""Rename a space — `issues/232` step 2.

Renaming is already the SANCTIONED remedy for an over-long space id: the schema
refuses one and tells the operator to rename. Until now it did not exist.

CATALOGUE ONLY, IN ONE TRANSACTION. PostgreSQL DDL is transactional, which is the
only reason this is feasible: ~313 `ALTER` statements per space either all land or
none do. Nothing here rewrites data — see "graph URIs are not touched".

FOUR-PLUS OBJECT CLASSES, NOT ONE. `ALTER TABLE … RENAME TO` renames the table and
nothing it owns. Measured on PostgreSQL 18, it leaves behind the partition
children, every index, every constraint — including PG18's NAMED NOT-NULL
constraints, which are 126 of a space's 166 — and every sequence. They keep
WORKING, because the catalogue links by oid, which is exactly what makes a partial
rename dangerous: the names silently stop describing reality, and the next
`CREATE INDEX IF NOT EXISTS idx_{new}_…` finds nothing by that name and builds a
SECOND index alongside the old one.

TWO ORDERING FACTS THAT ARE NOT PREFERENCES
-------------------------------------------
**Constraints before indexes.** Renaming a PK or UNIQUE constraint ALSO renames
its backing index (measured). So the index pass must skip any name that is also a
constraint name, or it fails with "index does not exist" — and a failure there
aborts a rename that was half applied to the catalogue, which the transaction
saves but which would look like a bug in the rename rather than in its order.

**Constraints and triggers before tables.** `ALTER TABLE … RENAME CONSTRAINT` and
`ALTER TRIGGER … ON <table>` both name the table, so they run while the table
still has its old name. Renaming tables first would mean tracking which name each
statement should use, for no benefit.

A NAME IT CANNOT MAP IS A HARD FAILURE, never a skip. A skipped object is an
orphan under the old id, which is the defect this whole issue is about — so
`_map_name` returns None for anything it cannot confidently rewrite and the
rename refuses. Silence is the one outcome that must be impossible.

GRAPH URIs ARE NOT TOUCHED, which `issues/232` decided explicitly. The default
graph URI is `urn:{space_id}` and it is stored as a term whose uuid is DERIVED
FROM ITS TEXT, so rewriting it would change every `context_uuid` in `rdf_quad`,
`edge`, `frame_slot`, the three sort tables, `geo` and every `_vec_`/`_fts_`
table — a full rewrite of the largest tables in the space, not a catalogue
operation. So a renamed space legitimately holds a graph named for its old id.
That is intended, and it is documented here because it looks like a bug.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .space_rename_enumerate import enumerate_space_objects
from .sparql_sql_schema import max_space_id_bytes

logger = logging.getLogger(__name__)

#: Prefixes a space id can sit behind in an object name. Longest first, and the
#: empty string last so `{space}_term_pkey` maps only after `idx_`/`trg_` fail.
_DECORATORS = ("idx_", "trg_", "")

#: A space id must be a bare identifier: it is concatenated into object names
#: unescaped, so anything else is an injection surface as well as a broken name.
_VALID_ID = re.compile(r"^[a-z_][a-z0-9_]*$")

#: PostgreSQL's identifier limit (NAMEDATALEN - 1). Over this it TRUNCATES
#: SILENTLY, which is how `issues/196` ended up with indexes under names the
#: schema never asked for.
#:
#: `max_space_id_bytes()` does NOT cover this. That ceiling (34) is derived from
#: the longest name the schema CREATES explicitly, but a rename also has to carry
#: PostgreSQL's AUTO-generated constraint names, which can be longer — e.g.
#: `{space}_document_document_type_uri_segment_met_key`. A new id that passes the
#: 34-byte check can therefore still overflow an individual constraint name, and
#: the symptom is a truncated name that a rename-back cannot undo. Found by the
#: round-trip test, which came back with `…_met_k` where `…_met_key` had been.
_MAX_IDENTIFIER_BYTES = 63


class SpaceRenameRefused(Exception):
    """The rename cannot proceed, and nothing was changed."""


def _map_name(name: str, old: str, new: str) -> Optional[str]:
    """`name` with the space id replaced, or None if it cannot be mapped.

    Matches `{decorator}{old}` as a whole leading token, NOT as a substring. A
    substring replace is the obvious implementation and it is wrong: for a space
    called `x`, `idx_x_edge_ctx` has its first `x` inside `idx_`, so the first
    occurrence is not the space id at all.
    """
    for dec in _DECORATORS:
        head = f"{dec}{old}"
        if name == head or name.startswith(f"{head}_"):
            return f"{dec}{new}{name[len(head):]}"
    return None


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


async def _validate(conn, old: str, new: str) -> None:
    if not _VALID_ID.match(new):
        raise SpaceRenameRefused(
            f"new id {new!r} is not a bare lowercase identifier; it is "
            f"concatenated into object names unescaped")

    ceiling = max_space_id_bytes()
    if len(new.encode("utf-8")) > ceiling:
        raise SpaceRenameRefused(
            f"new id {new!r} is {len(new.encode('utf-8'))} bytes, over the "
            f"schema's {ceiling}-byte ceiling — the same limit that makes rename "
            f"the remedy in the first place")

    from vitalgraph.constants import PROTECTED_SPACES
    for sid, role in ((old, "source"), (new, "target")):
        if sid in PROTECTED_SPACES:
            raise SpaceRenameRefused(f"{role} id {sid!r} is protected")

    ids = [r["space_id"] for r in await conn.fetch("SELECT space_id FROM space")]
    if old not in ids:
        raise SpaceRenameRefused(f"no space {old!r} is registered")
    if new in ids:
        raise SpaceRenameRefused(f"space {new!r} already exists")

    # PREFIX SHADOWING. Attribution of an object to a space is by longest
    # matching prefix, so a new id that is a prefix of an existing one — or vice
    # versa — makes every later audit, orphan sweep and drop ambiguous. This is
    # not hypothetical: a production space id is a prefix of another's in
    # production today. Renaming INTO that relationship is refused; the pair that
    # already exists is left alone, because refusing to work on it would make the
    # tool useless exactly where it is needed.
    others = [s for s in ids if s != old]
    clashes = [s for s in others
               if s.startswith(f"{new}_") or new.startswith(f"{s}_")]
    if clashes:
        raise SpaceRenameRefused(
            f"new id {new!r} would shadow or be shadowed by {clashes} — object "
            f"attribution is by longest prefix, so the two spaces could not be "
            f"told apart by any later audit or drop")


async def _detail(conn, tables: List[str]) -> Dict[str, Any]:
    """Constraints, triggers and functions WITH the table they hang off.

    The enumerator returns flat name lists because it is an audit; a rename needs
    the association, because `RENAME CONSTRAINT` and `ALTER TRIGGER` both name the
    table.
    """
    # `coninhcount = 0` — LOCAL constraints only. A partition child INHERITS its
    # parent's not-null constraints under the SAME name, and renaming one on the
    # child is rejected ("constraint … for table … does not exist"); renaming it
    # on the parent carries the children with it. Measured on PostgreSQL 18:
    #
    #   pc_a     pc_a_ctx_not_null  coninhcount=0  conislocal=t
    #   pc_a_p0  pc_a_ctx_not_null  coninhcount=1  conislocal=f
    #
    # so including the child row produced one ALTER per partition that could only
    # ever fail. Found by the partitioned-space test, not by reading.
    constraints = await conn.fetch(
        "SELECT rel.relname AS tbl, con.conname FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid = con.conrelid "
        "WHERE rel.relname = ANY($1) AND con.coninhcount = 0 "
        "ORDER BY rel.relname, con.conname", tables)
    triggers = await conn.fetch(
        "SELECT rel.relname AS tbl, tg.tgname FROM pg_trigger tg "
        "JOIN pg_class rel ON rel.oid = tg.tgrelid "
        "WHERE NOT tg.tgisinternal AND rel.relname = ANY($1)", tables)
    return {"constraints": constraints, "triggers": triggers}


async def plan_rename(conn, old: str, new: str, *,
                      allow_retruncation: bool = False) -> List[Tuple[str, str]]:
    """The exact statements a rename would run, in order. Read-only.

    Returns `(kind, sql)` pairs so a caller can show the plan and a test can
    assert on shape without executing it.
    """
    await _validate(conn, old, new)

    found = await enumerate_space_objects(conn, old)
    tables = list(found["tables"]) + list(found["partition_children"])
    detail = await _detail(conn, tables)

    unmappable: List[str] = []

    def mapped(name: str) -> str:
        out = _map_name(name, old, new)
        if out is None:
            unmappable.append(name)
            return name
        return out

    stmts: List[Tuple[str, str]] = []

    # 1. CONSTRAINTS — before indexes, because renaming a PK/UNIQUE constraint
    #    renames its backing index too.
    constraint_names = set()
    for r in detail["constraints"]:
        constraint_names.add(r["conname"])
        stmts.append(("constraint",
                      f'ALTER TABLE {_quote(r["tbl"])} RENAME CONSTRAINT '
                      f'{_quote(r["conname"])} TO {_quote(mapped(r["conname"]))}'))

    # 2. TRIGGERS — while the table still has its old name.
    for r in detail["triggers"]:
        stmts.append(("trigger",
                      f'ALTER TRIGGER {_quote(r["tgname"])} ON {_quote(r["tbl"])} '
                      f'RENAME TO {_quote(mapped(r["tgname"]))}'))

    # 3. INDEXES that are NOT constraint-backed. The others already moved in
    #    step 1, and naming them here would fail on a name that no longer exists.
    for name in found["indexes"]:
        if name in constraint_names:
            continue
        stmts.append(("index",
                      f'ALTER INDEX {_quote(name)} RENAME TO '
                      f'{_quote(mapped(name))}'))

    for name in found["sequences"]:
        stmts.append(("sequence",
                      f'ALTER SEQUENCE {_quote(name)} RENAME TO '
                      f'{_quote(mapped(name))}'))

    # 4. FUNCTIONS — the FTS trigger functions. Identity arguments come from the
    #    catalogue rather than being assumed empty.
    for name in found["functions"]:
        for r in await conn.fetch(
                "SELECT pg_get_function_identity_arguments(p.oid) AS args "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.proname = $1", name):
            stmts.append(("function",
                          f'ALTER FUNCTION {_quote(name)}({r["args"]}) '
                          f'RENAME TO {_quote(mapped(name))}'))

    # 5. TABLES LAST, including partition children — renaming a partitioned
    #    parent does NOT rename its children (measured).
    for name in tables:
        stmts.append(("table",
                      f'ALTER TABLE {_quote(name)} RENAME TO '
                      f'{_quote(mapped(name))}'))

    # 6. THE REGISTRY. One UPDATE, and the eleven FK children plus
    #    `user_space_access` follow via ON UPDATE CASCADE (`issues/232` step 3).
    stmts.append(("registry",
                  f"UPDATE space SET space_id = {_lit(new)} "
                  f"WHERE space_id = {_lit(old)}"))
    # `process.process_subtype` holds the space id with NO foreign key, so
    # nothing carries it. Missed, it strands process rows against a dead id.
    stmts.append(("process",
                  f"UPDATE process SET process_subtype = {_lit(new)} "
                  f"WHERE process_subtype = {_lit(old)}"))

    # ALREADY-TRUNCATED NAMES, when the length would change (`issues/246`).
    #
    # Five auto-named UNIQUE constraints sit at exactly 63 bytes on EVERY space —
    # `{space}_document_segmentation_config_document_type_uri_segment_method_uri_key`
    # is 70 bytes of suffix before any id, so PostgreSQL truncated the middle at
    # CREATE time. Renaming such a name to a different-length id produces
    # something that is neither the old name nor what a fresh CREATE would
    # produce, and renaming back does not restore it.
    #
    # REFUSING is the whole remedy here. There is no ceiling that prevents this —
    # an honest one computed over every auto-generated name is NEGATIVE — so the
    # only thing that can be done is to decline the renames that would make it
    # worse. A same-length rename is unaffected and still allowed.
    if len(old) != len(new) and not allow_retruncation:
        at_limit = sorted({
            name for _, sql in stmts
            for name in _renamed_sources(sql)
            if len(name.encode("utf-8")) == _MAX_IDENTIFIER_BYTES})
        if at_limit:
            raise SpaceRenameRefused(
                f"{len(at_limit)} object name(s) are already at the "
                f"{_MAX_IDENTIFIER_BYTES}-byte limit and were TRUNCATED when the "
                f"space was created (`issues/246`). Renaming to an id of a "
                f"different length re-truncates them to something neither name, "
                f"and renaming back cannot restore it. Use a new id of the same "
                f"byte length as {old!r} ({len(old)}), or accept the loss by "
                f"passing allow_retruncation=True. Examples: "
                + ", ".join(at_limit[:2]))

    too_long = sorted({
        new_name for _, sql in stmts
        for new_name in _renamed_targets(sql)
        if len(new_name.encode("utf-8")) > _MAX_IDENTIFIER_BYTES})
    if too_long:
        raise SpaceRenameRefused(
            f"{len(too_long)} object name(s) would exceed PostgreSQL's "
            f"{_MAX_IDENTIFIER_BYTES}-byte identifier limit and be TRUNCATED "
            f"silently, leaving names no rename-back can undo. Choose a shorter "
            f"new id. Longest: " + ", ".join(sorted(too_long, key=len,
                                                    reverse=True)[:3]))

    if unmappable:
        raise SpaceRenameRefused(
            f"{len(unmappable)} object name(s) could not be mapped from {old!r} "
            f"to {new!r}, and skipping one would orphan it under the old id: "
            + ", ".join(sorted(unmappable)[:10]))
    return stmts


def _renamed_sources(sql: str):
    """The EXISTING names a statement renames away from.

    Used for the already-truncated check, which asks about the name that is there
    now rather than the one being introduced.
    """
    for marker, tail in ((" RENAME CONSTRAINT ", " TO "),
                         (" RENAME TO ", None)):
        if marker not in sql:
            continue
        if tail is None:
            head = sql.split(marker)[0]
            # `ALTER {KIND} "name"` — the last quoted token before RENAME TO
            if '"' in head:
                yield head.rsplit('"', 2)[-2]
        else:
            yield sql.split(marker)[1].split(tail)[0].strip().strip('"')
        return


def _renamed_targets(sql: str):
    """The NEW names a statement introduces, for the length check.

    Parsed from the generated SQL rather than tracked alongside it, so a statement
    kind added later cannot quietly escape the check.
    """
    # BOTH FORMS. `ALTER TABLE t RENAME CONSTRAINT a TO b` also ends in " TO b",
    # but it does NOT contain " RENAME TO " — so the first version of this checked
    # only `RENAME TO` statements and never length-checked a single CONSTRAINT
    # name. Constraints are 166 of a space's ~313 objects and the auto-named ones
    # are the LONGEST, so the check was blind to exactly the names it was for.
    # Exposed by the already-truncated check in `plan_rename`, not by review.
    marker = " RENAME TO "
    if marker in sql:
        yield sql.split(marker)[1].strip().rstrip(";").strip('"')
        return
    if " RENAME CONSTRAINT " in sql and " TO " in sql:
        yield sql.rsplit(" TO ", 1)[1].strip().rstrip(";").strip('"')


def _lit(value: str) -> str:
    """A single-quoted SQL literal. Space ids are validated to a bare identifier
    before reaching here, so this is defence rather than the only guard."""
    return "'" + value.replace("'", "''") + "'"


async def rename_space(conn, old: str, new: str, *,
                       dry_run: bool = False,
                       require_quiet: bool = True,
                       allow_retruncation: bool = False,
                       space_manager: Optional[Any] = None) -> Dict[str, Any]:
    """Rename space *old* to *new*. All of it, or none of it.

    Catalogue only — no data is rewritten and no graph URI changes. Raises
    `SpaceRenameRefused` before doing anything if validation fails or any object
    name cannot be mapped.

    QUIESCES FIRST AND INVALIDATES AFTER (`issues/232` step 4). In-flight vector
    syncs for the space are cancelled before the transaction, and every
    process-local cache keyed by the space id is dropped for BOTH ids after it
    commits — the old id because its entries now describe nothing, the new id
    because anything cached under that name was cached before the space existed
    there.

    `quiesce_space` REPORTS a job holding a per-space advisory lock rather than
    waiting for it, and `require_quiet=True` turns that report into a refusal.
    The lock key is a sha256 over the space id, so a job holding the OLD id's
    lock does not exclude one that starts under the NEW name — two passes over
    the same physical tables, neither aware of the other.

    The caches are PROCESS-LOCAL, so this clears this process. Other processes
    keep their entries until restarted; `issues/232`'s "signal carrying BOTH ids"
    is not built.
    """
    stmts = await plan_rename(conn, old, new,
                              allow_retruncation=allow_retruncation)
    by_kind: Dict[str, int] = {}
    for kind, _ in stmts:
        by_kind[kind] = by_kind.get(kind, 0) + 1

    report = {"old": old, "new": new, "dry_run": dry_run,
              "statements": len(stmts), "by_kind": by_kind}
    if dry_run:
        report["sql"] = [s for _, s in stmts]
        return report

    from .space_cache_invalidation import invalidate_space_caches, quiesce_space

    quiesced = await quiesce_space(old, conn)
    report["quiesced"] = quiesced
    if require_quiet and quiesced["locks_held"]:
        # BEFORE the transaction, so nothing has changed. Refusing is the point:
        # the holder's lock is keyed on the OLD id and will not exclude work that
        # starts under the new one.
        raise SpaceRenameRefused(
            f"jobs hold per-space locks on {old!r}: {quiesced['locks_held']}. "
            f"Their locks are keyed on the old id and would not exclude work "
            f"starting under {new!r}. Wait, or pass require_quiet=False if you "
            f"know the holder is harmless.")

    logger.warning("renaming space %s -> %s: %d catalogue statements %s",
                   old, new, len(stmts), by_kind)
    async with conn.transaction():
        for kind, sql in stmts:
            await conn.execute(sql)

    # BOTH IDS. The old id's entries describe a space that no longer exists; the
    # new id's were cached before the space existed under that name, which is the
    # half that is easy to forget and answers just as confidently.
    report["invalidated"] = {
        old: invalidate_space_caches(old, space_manager=space_manager),
        new: invalidate_space_caches(new, space_manager=space_manager),
    }
    logger.warning("renamed space %s -> %s. Process-local caches cleared for "
                   "both ids; OTHER processes keep theirs. The space's graph "
                   "URIs still name %s, which is intended.", old, new, old)
    return report
