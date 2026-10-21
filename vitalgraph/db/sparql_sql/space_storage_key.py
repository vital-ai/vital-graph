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

from typing import List

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


async def key_shaped_space_ids(conn) -> List[str]:
    """Existing space ids that the key rule would now refuse.

    They predate the rule. Each must be renamed before the cutover, or it could
    one day equal a space's key.
    """
    return [r["space_id"] for r in await conn.fetch(
        "SELECT space_id FROM space WHERE space_id ~ '^[a-z2-7]{8}$' "
        "ORDER BY space_id")]
