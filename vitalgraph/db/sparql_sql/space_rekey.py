"""Move a space's objects onto its storage key — `vgs_<key>_…` (storage-key Stage 2).

The same catalogue-only, one-transaction move as `space_rename`, with two
differences:

* THE TARGET IS A PREFIX, NOT AN ID. The space keeps its id; `space.storage_key`
  is set instead, and nothing else in the registry changes.

* NAMES COME FROM A FRESH CREATE. PostgreSQL truncates an auto-generated name to
  63 bytes by shortening the middle, so five UNIQUE constraints on every space
  already hold names no prefix substitution can reproduce (`issues/246`). The
  rename refuses a length change for that reason. Every space's prefix changes
  length here, so instead the move asks PostgreSQL: it creates the schema under
  the new prefix inside a savepoint, reads the names it chose for each
  auto-named object, and rolls the savepoint back. A re-keyed space then carries
  exactly the names a space created under that key would.

  Only names a substitution cannot get right are mapped that way: one already
  at 63 bytes, or one the new prefix would push past it. Each is matched by
  what the object IS (table, kind, columns; or, for a partition child's index,
  its parent index), not by its name. Every other name keeps exactly what the
  space has, prefix swapped — a re-key moves a space, it does not tidy one.

REVERSIBLE: `reverse=True` moves the objects from `vgs_<key>` back to the id
prefix, by the same rule. The key stays recorded; it is never released.

A RE-KEYED SPACE IS REACHABLE ONLY BY CODE THAT READS KEYS (Stage 3 on): a
process names a space by its key once its key map holds it. A committed move
updates this process's map and NOTIFYs the space channel, so each running
`SpaceManager` reloads the space; anything else picks it up on its next key
load. Run it with writers stopped: the move takes ACCESS EXCLUSIVE on every
object of the space, and a process that has not yet reloaded names the
objects by the prefix they just left.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .space_names import (forget_storage_key, key_shaped_id_problem,
                          register_storage_key, registered_storage_key,
                          storage_key_prefix)
from .space_rename import (SpaceRenameRefused, _DECORATORS, _MAX_IDENTIFIER_BYTES,
                           _lit, _renamed_sources, object_rename_statements,
                           refuse_overlong_targets)
from .space_rename_enumerate import enumerate_space_objects
from .space_storage_key import allocate_storage_key, is_keyed

logger = logging.getLogger(__name__)


class _Discard(Exception):
    """Raised inside the probe's savepoint to roll it back."""


def _map_prefix(name: str, old: str, new: str) -> Optional[str]:
    """`name` with the leading `{decorator}{old}` replaced, or None."""
    for dec in _DECORATORS:
        head = f"{dec}{old}"
        if name == head or name.startswith(f"{head}_"):
            return f"{dec}{new}{name[len(head):]}"
    return None


async def _auto_named(conn, prefix: str) -> Dict[Tuple, Optional[str]]:
    """`{role: name}` for the auto-named objects on tables under `prefix`.

    A role is what an object IS — `("con", table suffix, contype, columns)`,
    `("seq", table suffix, column)`, `("idx", table suffix, columns, unique)` —
    so the same object can be found on two spaces whatever either is called.
    A role held by more than one object maps to None: ambiguous, so not used.
    """
    like = prefix.replace("_", "\\_") + "\\_%"
    cut = len(prefix) + 1
    out: Dict[Tuple, Optional[str]] = {}

    def put(role, name):
        out[role] = None if role in out else name

    for r in await conn.fetch(
            "SELECT rel.relname AS tbl, con.conname, con.contype::text AS kind, "
            "  ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY "
            "        k(n, o) JOIN pg_attribute a ON a.attrelid = con.conrelid "
            "        AND a.attnum = k.n ORDER BY k.o)::text[] AS cols "
            "FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid "
            "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
            "WHERE ns.nspname = 'public' AND rel.relname LIKE $1 "
            "AND con.coninhcount = 0", like):
        put(("con", r["tbl"][cut:], r["kind"], tuple(r["cols"] or ())),
            r["conname"])

    for r in await conn.fetch(
            "SELECT t.relname AS tbl, s.relname AS seq, a.attname AS col "
            "FROM pg_class s JOIN pg_depend d ON d.objid = s.oid "
            "AND d.deptype = 'a' JOIN pg_class t ON t.oid = d.refobjid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid "
            "WHERE s.relkind = 'S' AND t.relname LIKE $1", like):
        put(("seq", r["tbl"][cut:], r["col"]), r["seq"])

    # A partition child's copy of a parent index is named by PostgreSQL, with an
    # `idx1`, `idx2`… tiebreak in creation order once truncation makes two
    # alike — so columns cannot tell them apart. The PARENT index can: it is
    # named explicitly, and identified here with the prefix taken out.
    for r in await conn.fetch(
            "SELECT t.relname AS tbl, ci.relname AS idx, i.indisunique AS uq, "
            "  pi.relname AS parent, "
            "  ARRAY(SELECT coalesce(a.attname, '(expr)') "
            "        FROM unnest(i.indkey::int2[]) WITH ORDINALITY k(n, o) "
            "        LEFT JOIN pg_attribute a ON a.attrelid = t.oid "
            "        AND a.attnum = k.n ORDER BY k.o)::text[] AS cols "
            "FROM pg_index i JOIN pg_class ci ON ci.oid = i.indexrelid "
            "JOIN pg_class t ON t.oid = i.indrelid "
            "LEFT JOIN pg_inherits ih ON ih.inhrelid = i.indexrelid "
            "LEFT JOIN pg_class pi ON pi.oid = ih.inhparent "
            "WHERE t.relname LIKE $1 "
            "AND NOT EXISTS (SELECT 1 FROM pg_constraint c "
            "                WHERE c.conindid = i.indexrelid)", like):
        if r["parent"]:
            role = ("pidx", r["tbl"][cut:], _map_prefix(r["parent"], prefix, "*"))
        else:
            role = ("idx", r["tbl"][cut:], tuple(r["cols"] or ()), r["uq"])
        put(role, r["idx"])
    return out


async def fresh_names(conn, prefix: str,
                      partition_quads: int) -> Dict[Tuple, Optional[str]]:
    """The auto-generated names a space created under `prefix` would carry.

    Creates the schema under `prefix` in a savepoint and rolls it back, so the
    answer is PostgreSQL's own naming rather than a reimplementation of it.
    """
    from .sparql_sql_schema import SparqlSQLSchema
    names: Dict[Tuple, Optional[str]] = {}
    # The generators name objects by `space_prefix(<the id they are given>)`, so
    # the probe hands them the prefix as an id that the key map does not hold —
    # which for a move BACK to the id prefix means taking the space out of the
    # map for the duration.
    held = registered_storage_key(prefix)
    if held is not None:
        forget_storage_key(prefix)
    try:
        async with conn.transaction():
            await SparqlSQLSchema.create_space_core(conn, prefix, partition_quads)
            await SparqlSQLSchema.bootstrap_space_extras(conn, prefix, strict=True)
            names = await _auto_named(conn, prefix)
            raise _Discard
    except _Discard:
        pass
    finally:
        if held is not None:
            register_storage_key(prefix, held)
    return names


def _partition_count(found: Dict[str, Any], prefix: str) -> int:
    quad = f"{prefix}_rdf_quad_p"
    return sum(1 for c in found["partition_children"]
               if c.startswith(quad) and c[len(quad):].isdigit())


async def plan_rekey(conn, space_id: str, *, key: Optional[str] = None,
                     reverse: bool = False) -> Dict[str, Any]:
    """What a re-key would run, in order, without running it.

    Returns `{key, from_prefix, to_prefix, statements, fresh_named}`. Uses a
    savepoint for the name probe, so it must be called on a connection that is
    free to open one; it leaves nothing behind.
    """
    row = await conn.fetchrow(
        "SELECT storage_key FROM space WHERE space_id = $1", space_id)
    if row is None:
        raise SpaceRenameRefused(f"no space {space_id!r} is registered")
    problem = key_shaped_id_problem(space_id)
    if problem:
        raise SpaceRenameRefused(
            f"{problem} — rename it before re-keying it")

    recorded = row["storage_key"]
    if key is not None and recorded is not None and key != recorded:
        raise SpaceRenameRefused(
            f"space {space_id!r} already has storage key {recorded!r}; a key is "
            f"never changed")
    if reverse and recorded is None:
        raise SpaceRenameRefused(
            f"space {space_id!r} has no storage key, so nothing to move back from")
    key = recorded or key or await allocate_storage_key(conn)

    # The id itself, not `space_prefix(space_id)`: for a keyed space that is
    # already the key's prefix.
    id_prefix, key_prefix = space_id, storage_key_prefix(key)
    old, new = (key_prefix, id_prefix) if reverse else (id_prefix, key_prefix)

    found = await enumerate_space_objects(conn, space_id, prefix=old)
    if not found["tables"]:
        raise SpaceRenameRefused(
            f"no tables of {space_id!r} are named under {old!r}; "
            + ("is it re-keyed already?" if not reverse else "is it re-keyed?"))
    # By ownership, not LIKE: under an id prefix, a space whose id merely
    # extends this one (`prod_kg_test` for `prod_kg`) is not in the way.
    already = (await enumerate_space_objects(conn, space_id, prefix=new))["total"]
    if already:
        raise SpaceRenameRefused(
            f"{already} object(s) are already named under {new!r}; moving "
            f"{space_id!r} there would mix two sets of objects")

    fresh = await fresh_names(conn, new, _partition_count(found, old))
    current = await _auto_named(conn, old)
    by_name = {name: role for role, name in current.items() if name}

    unmappable: List[str] = []
    from_fresh: List[str] = []      # took a fresh-create name ...
    differs: List[str] = []         # ... that a prefix substitution would miss

    def mapped(name: str) -> str:
        out = _map_prefix(name, old, new)
        # A substitution keeps every name the space has, which is the point —
        # it is a move, not a tidy-up. Only where it CANNOT be right is the
        # fresh-create name used: a name already at the limit (PostgreSQL may
        # have truncated it) or one the substitution would push past it.
        unsafe = (len(name.encode("utf-8")) >= _MAX_IDENTIFIER_BYTES
                  or (out is not None
                      and len(out.encode("utf-8")) > _MAX_IDENTIFIER_BYTES))
        role = by_name.get(name)
        if unsafe and role is not None and fresh.get(role):
            from_fresh.append(name)
            if fresh[role] != out:
                differs.append(name)
            return fresh[role]
        if out is None:
            unmappable.append(name)
            return name
        return out

    stmts = await object_rename_statements(conn, found, mapped)
    if not reverse:
        # `IS NULL OR = key`: setting a key is the only write this makes, and
        # it can never replace one.
        stmts.append(("registry",
                      f"UPDATE space SET storage_key = {_lit(key)} "
                      f"WHERE space_id = {_lit(space_id)} "
                      f"AND (storage_key IS NULL OR storage_key = {_lit(key)})"))

    refuse_overlong_targets(stmts, "This space's object names cannot be keyed.")
    if unmappable:
        raise SpaceRenameRefused(
            f"{len(unmappable)} object name(s) of {space_id!r} could not be "
            f"mapped from {old!r} to {new!r}: " + ", ".join(sorted(unmappable)[:10]))
    # A name already truncated at 63 bytes that no fresh create accounts for
    # would be re-truncated to something neither name (`issues/246`).
    stranded = sorted(
        name for _, sql in stmts for name in _renamed_sources(sql)
        if len(name.encode("utf-8")) == _MAX_IDENTIFIER_BYTES
        and name not in from_fresh and len(old) != len(new))
    if stranded:
        raise SpaceRenameRefused(
            f"{len(stranded)} name(s) are at the {_MAX_IDENTIFIER_BYTES}-byte "
            f"limit and match nothing a fresh create makes: "
            + ", ".join(stranded[:5]))

    return {"space_id": space_id, "key": key, "from_prefix": old,
            "to_prefix": new, "statements": stmts,
            "fresh_named": sorted(differs)}


async def _execute(conn, stmts: List[Tuple[str, str]]) -> None:
    for _, sql in stmts:
        await conn.execute(sql)


def _by_kind(stmts) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for kind, _ in stmts:
        out[kind] = out.get(kind, 0) + 1
    return out


async def rekey_space(conn, space_id: str, *, reverse: bool = False,
                      dry_run: bool = True,
                      lock_timeout_ms: int = 5000) -> Dict[str, Any]:
    """Re-key one space in one transaction. Dry run unless told otherwise.

    `lock_timeout_ms` bounds the wait for each object's ACCESS EXCLUSIVE lock, so
    a busy space fails the re-key rather than stalling every query behind it.
    """
    async with conn.transaction():
        await conn.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
        plan = await plan_rekey(conn, space_id, reverse=reverse)
        stmts = plan["statements"]
        report = {**{k: v for k, v in plan.items() if k != "statements"},
                  "reverse": reverse, "dry_run": dry_run,
                  "statements": len(stmts), "by_kind": _by_kind(stmts)}
        if dry_run:
            report["sql"] = [s for _, s in stmts]
            return report
        t0 = time.monotonic()
        await _execute(conn, stmts)
        report["seconds"] = time.monotonic() - t0
    # Committed: this process names the space by where its objects now are,
    # and other instances are told to reload it (`SpaceManager`'s signal).
    if reverse:
        forget_storage_key(space_id)
    else:
        register_storage_key(space_id, plan["key"])
    await notify_space_rekeyed(conn, space_id)
    logger.warning("re-keyed space %s: %s -> %s, %d statements in %.2fs",
                   space_id, plan["from_prefix"], plan["to_prefix"],
                   len(stmts), report["seconds"])
    return report


async def notify_space_rekeyed(conn, space_id: str) -> None:
    """Tell every instance's space manager to reload this space's key."""
    import json
    from vitalgraph.signal.signal_manager import CHANNEL_SPACE, SIGNAL_TYPE_UPDATED
    await conn.execute(
        "SELECT pg_notify($1, $2)", CHANNEL_SPACE,
        json.dumps({"type": SIGNAL_TYPE_UPDATED, "space_id": space_id,
                    "timestamp": str(time.time())}))


async def round_trip(conn, space_id: str, *,
                     check: Optional[Callable] = None,
                     lock_timeout_ms: int = 5000) -> Dict[str, Any]:
    """Move a space and move it back in ONE transaction, then roll it all back.

    An unkeyed space goes onto its key and back; a keyed one goes to its id
    prefix and back. Measures the move on real data and proves it reversible
    with nothing ever committed. `check(conn, plan)` runs between the halves,
    while the objects sit under the OTHER prefix; `report["under_key"]` is the
    enumeration under the key in either case.
    """
    report: Dict[str, Any] = {"space_id": space_id}
    try:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
            keyed = await is_keyed(conn, space_id)
            report["was_keyed"] = keyed
            key_now = await conn.fetchval(
                "SELECT storage_key FROM space WHERE space_id = $1", space_id)
            start_prefix = storage_key_prefix(key_now) if keyed else space_id
            before = await enumerate_space_objects(conn, space_id,
                                                   prefix=start_prefix)

            t0 = time.monotonic()
            fwd = await plan_rekey(conn, space_id, reverse=keyed)
            report["plan_forward_s"] = time.monotonic() - t0
            t0 = time.monotonic()
            await _execute(conn, fwd["statements"])
            report["forward_s"] = time.monotonic() - t0
            report["key"] = fwd["key"]
            report["statements"] = len(fwd["statements"])
            report["by_kind"] = _by_kind(fwd["statements"])
            report["fresh_named"] = fwd["fresh_named"]
            report["under_key"] = (before if keyed else
                                   await enumerate_space_objects(
                                       conn, space_id, prefix=fwd["to_prefix"]))
            if check is not None:
                await check(conn, fwd)

            t0 = time.monotonic()
            back = await plan_rekey(conn, space_id, reverse=not keyed)
            await _execute(conn, back["statements"])
            report["reverse_s"] = time.monotonic() - t0
            after = await enumerate_space_objects(conn, space_id,
                                                  prefix=start_prefix)
            report["restored"] = {
                cls: after[cls] == before[cls]
                for cls in ("tables", "partition_children", "indexes",
                            "constraints", "sequences", "functions", "triggers")}
            raise _Discard
    except _Discard:
        pass
    return report
