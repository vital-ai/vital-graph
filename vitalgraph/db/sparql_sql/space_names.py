"""The one place a space id becomes part of a database object name.

Every per-space table, partition child, index, trigger, trigger function and
constraint is named `{prefix}_…` (or `idx_{prefix}_…`, `trg_{prefix}_…`,
`ck_{prefix}_…`), and the prefix comes from `space_prefix` and nowhere else.
Code that writes `f"{space_id}_rdf_quad"` is the coupling this module exists to
remove.

A SPACE'S PREFIX IS `vgs_<storage key>` once its objects have been moved onto
its key (`space.storage_key`, `space_rekey`), and its id until then. The
user-facing id can then be renamed without DDL and is no longer bound by
PostgreSQL's identifier rules. Callers pass the space id and never see the key.

The reverse direction — a table name back to its space — goes through
`space_id_for_prefix`, for the same reason. Splitting `vgs_ab2cd3ef_term` on
`_term` yields a prefix, not a space id.

THE KEY MAP. `space_prefix` is called from synchronous string builders, so it
cannot ask the database; it reads an in-process map of space id -> key. The map
holds a space only when its key's quad table EXISTS — a recorded key whose
objects are still named by id (a space created before the cutover) is not in
it — and is loaded by `space_storage_key.load_storage_keys`: on every
`list_spaces` / `get_space_metadata` of the backend (so at startup, on the space
manager's refresh and on a cache miss), on a space signal, and by every script
after it connects. Creation, deletion and rename update it directly.

THE ID FALLBACK IS TEMPORARY. A space the map does not hold is named by its id,
which is what lets this code run before every space is re-keyed. Once every
database is keyed, Stage 4 of `planning/planning_db/space_storage_key_plan.md`
removes the fallback and makes `storage_key` NOT NULL.

THE STORAGE KEY: eight characters of lowercase base32, random, never changed.
Two rules keep a key and a space id apart:

* a space id may not have the key's shape (`is_storage_key`), so no id can
  ever name another space's objects; and
* `storage_key_prefix` refuses anything that is not key-shaped, so passing an
  id where a key belongs fails before any SQL is built.
"""

from __future__ import annotations

import re
import secrets
from typing import Dict, Optional

#: Every object of a keyed space is named under `vgs_<key>`. No admin or global
#: object may start with it, which is what makes "anything under `vgs_` with no
#: matching key is an orphan" a safe rule.
STORAGE_KEY_NAMESPACE = "vgs_"

_KEY_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_KEY_LENGTH = 8
_KEY_RE = re.compile(r"[a-z2-7]{8}")


#: space id -> storage key, for spaces whose objects are named under their key;
#: and the reverse. See "THE KEY MAP" above.
_KEYS: Dict[str, str] = {}
_IDS: Dict[str, str] = {}


def space_prefix(space_id: str) -> str:
    """The prefix every database object of this space is named with."""
    key = _KEYS.get(space_id)
    if key is not None:
        return STORAGE_KEY_NAMESPACE + key
    return space_id          # TEMPORARY id fallback; removed in Stage 4


def space_id_for_prefix(prefix: str) -> str:
    """The space whose objects carry `prefix`. Inverse of `space_prefix`.

    An unknown `vgs_` prefix comes back unchanged: it names no live space.
    """
    if prefix.startswith(STORAGE_KEY_NAMESPACE):
        sid = _IDS.get(prefix[len(STORAGE_KEY_NAMESPACE):])
        if sid is not None:
            return sid
    return prefix


def register_storage_key(space_id: str, key: str) -> None:
    """Name `space_id`'s objects under `key` from now on, in this process."""
    storage_key_prefix(key)                      # refuses a non-key
    forget_storage_key(space_id)
    stale = _IDS.pop(key, None)
    if stale is not None:
        _KEYS.pop(stale, None)
    _KEYS[space_id] = key
    _IDS[key] = space_id


def forget_storage_key(space_id: str) -> None:
    """Name `space_id`'s objects by its id again (or: it no longer exists)."""
    key = _KEYS.pop(space_id, None)
    if key is not None and _IDS.get(key) == space_id:
        del _IDS[key]


def registered_storage_key(space_id: str) -> Optional[str]:
    return _KEYS.get(space_id)


def is_storage_key(value: str) -> bool:
    """Does `value` have a storage key's shape?

    Also the rule a space id must FAIL: an id with this shape could equal some
    space's key, and then a call site that passed the id where the key belongs
    would reach that space's objects instead of failing.
    """
    return isinstance(value, str) and _KEY_RE.fullmatch(value) is not None


def new_storage_key() -> str:
    """A fresh random key. Uniqueness is the allocator's job, not this one's."""
    return "".join(secrets.choice(_KEY_ALPHABET) for _ in range(_KEY_LENGTH))


def storage_key_prefix(key: str) -> str:
    """The object prefix for a storage key: `vgs_<key>`. Refuses a non-key."""
    if not is_storage_key(key):
        raise ValueError(
            f"{key!r} is not a storage key (8 characters of [a-z2-7]); a space "
            f"id passed where a key belongs is the mistake this refuses")
    return STORAGE_KEY_NAMESPACE + key


def key_shaped_id_problem(space_id: str):
    """Why `space_id` cannot be a space id under the key rule, or None.

    Only the storage-key rule; an id's other limits are checked where they
    always were.
    """
    if is_storage_key(space_id):
        return (f"space id {space_id!r} has the shape of a storage key (8 "
                f"characters of [a-z2-7]); that shape is reserved, so that no "
                f"space id can ever equal another space's key")
    # Until every space is keyed, an unkeyed space is named by its id; one
    # starting `vgs_` would put its tables in the key namespace, where an object
    # matching no key is taken for an orphan.
    if space_id.startswith(STORAGE_KEY_NAMESPACE):
        return (f"space id {space_id!r} starts with {STORAGE_KEY_NAMESPACE!r}, "
                f"which is reserved for storage-key object names")
    return None
