"""The one place a space id becomes part of a database object name.

Every per-space table, partition child, index, trigger, trigger function and
constraint is named `{prefix}_…` (or `idx_{prefix}_…`, `trg_{prefix}_…`,
`ck_{prefix}_…`), and the prefix comes from `space_prefix` and nowhere else.
Code that writes `f"{space_id}_rdf_quad"` is the coupling this module exists to
remove.

TODAY THE PREFIX IS THE SPACE ID, unchanged, so the names are the ones every
existing database already holds. The planned change
(`planning/planning_db/space_storage_key_plan.md`) makes it `vgs_<storage key>`:
a short random key, fixed at creation, so the user-facing space id can be
renamed without DDL and is no longer bound by PostgreSQL's identifier rules.
That change is made HERE; callers pass the space id and never see the key.

The reverse direction — a table name back to its space — goes through
`space_id_for_prefix`, for the same reason. Splitting `myspace_term` on
`_term` yields a prefix, which is a space id only for as long as the two are
the same string.

THE STORAGE KEY. Each space gets one at creation (`space.storage_key`): eight
characters of lowercase base32, random, never changed and never reused. Its
object prefix will be `vgs_<key>`. Two rules keep a key and a space id apart:

* a space id may not have the key's shape (`is_storage_key`), so no id can
  ever name another space's objects; and
* `storage_key_prefix` refuses anything that is not key-shaped, so passing an
  id where a key belongs fails before any SQL is built.

Nothing names objects by key yet; `space_prefix` is still the identity.
"""

from __future__ import annotations

import re
import secrets

#: Every object of a keyed space is named under `vgs_<key>`. No admin or global
#: object may start with it, which is what makes "anything under `vgs_` with no
#: matching key is an orphan" a safe rule.
STORAGE_KEY_NAMESPACE = "vgs_"

_KEY_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_KEY_LENGTH = 8
_KEY_RE = re.compile(r"[a-z2-7]{8}")


def space_prefix(space_id: str) -> str:
    """The prefix every database object of this space is named with."""
    return space_id


def space_id_for_prefix(prefix: str) -> str:
    """The space whose objects carry `prefix`. Inverse of `space_prefix`."""
    return prefix


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
    return None
