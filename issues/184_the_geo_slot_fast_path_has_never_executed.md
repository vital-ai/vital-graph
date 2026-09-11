# The Geo Slot Handler's `frame_entity` Fast Path Has Never Executed

## Status: RESOLVED 2026-09-10 — the fast path is DELETED, not repaired.
##
## This issue ends "repairing it means deciding what the query was meant to
## return, and it has never returned anything." That decision is made, and the
## answer is that no correct fast path exists.
##
## The obvious repair — point it at `{space}_frame_slot.entity_uuid`, which DOES
## have the column the old query selected — is WRONG, and silently so. That
## column is the entity FILLING THE SLOT (`hasEntitySlotValue`). The function
## returns the entity that OWNS THE FRAME, reached by `Edge_hasEntityKGFrame`
## with the frame as edge destination. On any relationship frame — the normal
## case, and the point of the construct — the two disagree, and
## `process_geo_slot` would key geo points to a different entity with no error
## and no drift signal.
##
## `frame_slot` does not record frame ownership at all, so the repoint was never
## available; the choice was delete or keep dead code. The traversal remains,
## which is what has always run, so behaviour is unchanged.
##
## It was briefly repointed during the `frame_entity` retirement and reverted in
## review before shipping — the review caught what the sweep did not.

**Raised:** 2026-09-09, while auditing readers of `frame_entity` before
retiring it (`issues/183`).

**Related:** `issues/183`, `vitalgraph/vectorization/geo_slot_handler.py`

## The defect

`_resolve_entity_for_slot` has a documented fast path:

```python
# Fast path: use frame_entity table
try:
    row = await conn.fetchrow(
        _SLOT_TO_ENTITY_VIA_FRAME_ENTITY_SQL.format(frame_entity=frame_entity),
        slot_uuid, context_uuid)
    if row:
        return row["entity_uuid"]
except Exception:
    # Table might not exist — fall through to edge traversal
    pass
```

The query it runs is:

```sql
SELECT fe.entity_uuid
FROM {frame_entity} fe
JOIN {frame_entity} fe_slot ON fe_slot.entity_uuid = fe.entity_uuid ...
```

`frame_entity` has no `entity_uuid` column. It has `frame_uuid`,
`source_entity_uuid`, `dest_entity_uuid`, `context_uuid`, `frame_type_uuid`.
Run against a real space:

    ERROR:  column fe_slot.entity_uuid does not exist

So the statement raises on every call, the `except` swallows it, and the
handler falls through to the slow path — **every time, on every space, since the
code was written**. The comment on the `except` says "Table might not exist",
which is a plausible reason to be lenient and is not the reason it is firing.

The query is confused in a second way: `$1` is a slot uuid and it is compared
against `fe_slot.frame_uuid`. Even with a valid column list it would be asking
the wrong question.

## Why nothing noticed

The fallback produces correct answers. The only symptom is that geo slot
resolution does two extra round trips per slot, which looks like the cost of the
work rather than the cost of a broken optimisation. A bare `except Exception`
around a fast path makes a permanent failure indistinguishable from a
by-design fallback.

## What is NOT established

- **What the fast path should return.** It has never returned anything, so
  there is no behaviour to preserve and no way to tell from the code whether
  "the owning entity for a slot" means another slot's entity on the same frame,
  or something else. That question belongs to whoever owns the geo path.
- **What it is worth.** The slow path is two indexed lookups. It may be that
  the fast path was never worth having, in which case the honest fix is to
  delete it rather than repair it.

## What should change regardless

The `except Exception: pass` should log. A fast path that cannot execute is a
defect wherever it appears, and this one hid for as long as it has because
nothing said so. `{space}_frame_slot` (`issues/183`) does carry an
`entity_uuid` column, so a repaired fast path has somewhere to point — but
pointing it there is writing new behaviour, not fixing old, and should be done
deliberately.
