"""Giving a space its storage key (`space.storage_key`).

The key's shape and the prefix built from it live in `space_names`; this module
is the database side: picking a key nothing else uses, and recording it.

NEVER REUSED. A key is checked against the live `space` rows AND against the
catalogue: a key whose `vgs_<key>_` prefix already names any relation is
refused. A dropped space's key therefore stays unavailable for as long as
anything it left behind exists, so a new space can never adopt an old one's
orphans. Past that, 32^8 values make an accidental repeat negligible.
"""

from __future__ import annotations

from typing import List, Optional

from .space_names import new_storage_key, storage_key_prefix


class StorageKeyUnavailable(RuntimeError):
    """No unused key was found, which with 32^8 keys means something is wrong."""


async def storage_key_in_use(conn, key: str) -> bool:
    """Is `key` held by a space row, or does any relation carry its prefix?"""
    like = storage_key_prefix(key).replace("_", "\\_") + "\\_%"
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM space WHERE storage_key = $1) "
        "    OR EXISTS (SELECT 1 FROM pg_class WHERE relname LIKE $2)",
        key, like)


async def allocate_storage_key(conn, attempts: int = 8) -> str:
    """A key no space holds and no relation is named under.

    Not reserved by this call: the caller writes it in the same transaction as
    the row, and the UNIQUE constraint settles a race between two allocators.
    """
    for _ in range(attempts):
        key = new_storage_key()
        if not await storage_key_in_use(conn, key):
            return key
    raise StorageKeyUnavailable(
        f"no unused storage key after {attempts} attempts")


#: A space is keyed when its key is recorded AND its quad table carries it. A
#: recorded key whose objects are still named by id (created before the
#: cutover, or moved back) is not, and keeps its id names.
_KEYED_EXPR = (
    "storage_key IS NOT NULL AND to_regclass('public.' || "
    "quote_ident('vgs_' || storage_key || '_rdf_quad')) IS NOT NULL")
_KEYED_SQL = f"SELECT space_id, storage_key, {_KEYED_EXPR} AS keyed FROM space"


async def load_storage_keys(conn, space_id: Optional[str] = None) -> int:
    """Bring this process's key map up to date from `space`. Returns how many
    spaces are keyed.

    Only spaces read here are touched, so a space being created in this process
    — registered before its row exists — is left alone. A database without the
    column (not yet migrated) leaves the map as it is: every space is then
    named by its id, which is what such a database holds.
    """
    import asyncpg
    from .space_names import forget_storage_key, register_storage_key
    try:
        if space_id is None:
            rows = await conn.fetch(_KEYED_SQL)
        else:
            rows = await conn.fetch(_KEYED_SQL + " WHERE space_id = $1", space_id)
    except (asyncpg.UndefinedColumnError, asyncpg.UndefinedTableError):
        return 0
    keyed = 0
    for r in rows:
        if r["keyed"]:
            register_storage_key(r["space_id"], r["storage_key"])
            keyed += 1
        else:
            forget_storage_key(r["space_id"])
    return keyed


async def is_keyed(conn, space_id: str) -> bool:
    """Are this space's objects named under its storage key right now?"""
    return bool(await conn.fetchval(
        f"SELECT {_KEYED_EXPR} FROM space WHERE space_id = $1", space_id))


async def spaces_with_tables(conn) -> List[str]:
    """Every space that has a quad table, registered or not, by id.

    For scripts that sweep "every space in the database". Reading the ids off
    `*_rdf_quad` table names, which is what they all did, yields a prefix — the
    space id only for a space not yet keyed. This maps each back.
    """
    from .space_names import space_id_for_prefix
    await load_storage_keys(conn)
    return sorted(space_id_for_prefix(r["tablename"][: -len("_rdf_quad")])
                  for r in await conn.fetch(
                      "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                      "AND tablename LIKE '%\\_rdf\\_quad'"))


async def key_shaped_space_ids(conn) -> List[str]:
    """Existing space ids that the key rules would now refuse: a key's shape,
    or the `vgs_` namespace.

    They predate the rule. Each must be renamed before the cutover, or it could
    one day equal a space's key.
    """
    return [r["space_id"] for r in await conn.fetch(
        "SELECT space_id FROM space WHERE space_id ~ '^[a-z2-7]{8}$' "
        "OR space_id LIKE 'vgs\\_%' ORDER BY space_id")]
