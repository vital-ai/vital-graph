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
"""

from __future__ import annotations


def space_prefix(space_id: str) -> str:
    """The prefix every database object of this space is named with."""
    return space_id


def space_id_for_prefix(prefix: str) -> str:
    """The space whose objects carry `prefix`. Inverse of `space_prefix`."""
    return prefix

