# 173 — The upsert is not atomic, and production holds no entity lock

**Status:** open
**Found:** 2026-09-07, while repairing the data damage it caused
**Related:** `scripts/repair_duplicate_server_timestamps.py` (repairs the
damage), `sparql_sql_db_objects._materialize` (bounds the blast radius)

## The damage, first

On the production space, **243 entity subjects carry two to four values for
`hasObjectModificationDateTime`**, and 241 for `hasObjectCreationTime`. Both are
single-valued.

That is not a cosmetic defect. The object layer groups repeated predicates into
a list, a list is not a datetime, and `GraphObject.from_property_maps` is
all-or-nothing over the batch it is given — so **one** such subject returned
zero rows for an entire 25-row page of the KG entity listing, with no error
surfaced. Page 9 was empty while pages 8 and 10 were fine.

It also breaks sorting: a sort joins each entity to each of its values, so those
entities appear two to four times and every later page shifts. Measured: the
sorted join yields **82,498 rows against 81,882 entities** — exactly the surplus.

## Defect 1 — UPSERT is delete-then-store with no transaction

`kgentity_create_impl._handle_upsert_mode`:

```python
for entity in existing_entities:
    await self.backend.delete_object(space_id, graph_id, entity_uri)   # separate
result = await self.backend.store_objects(space_id, graph_id, objects) # separate
```

Two independent operations. A client that times out and retries while the first
request is still in flight produces:

| | request A | request B (~31s later) |
|---|---|---|
| 1 | `object_exists` → false | |
| 2 | no delete; begins storing | |
| 3 | | `object_exists` → false (A uncommitted) |
| 4 | | no delete; stores too |
| 5 | commits | commits |

Both inserts land. Nothing rolls back, because neither request did anything
wrong on its own.

## Why only the two timestamps are corrupted

This is the detail that identifies the mechanism, and it is worth keeping.

Every *client-supplied* property carries the same value on each attempt, so the
quad primary key `(subject, predicate, object, context)` silently dedupes the
retry — the second insert is a no-op. The two timestamps are stamped
**server-side per request** by `stamp_entity_server_properties`, which calls
`datetime.now()`. Each attempt therefore writes a *different* value, and each is
a distinct row that the primary key cannot collapse.

So the corruption is precisely the shape a retry race produces and nothing else.
The production evidence agrees: duplicates cluster into two incidents
(2026-06-08, 82 subjects; 2026-07-29, 157 subjects), spans under 95 seconds,
values ~31 seconds apart — a client retry interval, two to four attempts deep.

## Defect 2 — the lock that should have prevented this does not exist in production

The endpoint *does* try to serialize on the entity:

```python
_lm = getattr(space_impl.backend, 'entity_lock_manager', None)
if _lm:
    ...
```

`EntityLockManager` — a PostgreSQL advisory lock keyed by a SHA-256 of the URI,
held on a dedicated connection, with a per-entity `asyncio.Lock` layered on top
because PG advisory locks are reentrant on one connection — would serialize A
and B above.

It is **Fuseki-backend code and is not to be reused.** It is described here only
to record that the endpoints call into something that does not exist for the
production backend; the fix below is native and does not depend on it.

**It is defined only on `FusekiPostgreSQLSpaceImpl`.** Production runs
`SparqlSQLSpaceImpl`, which has no such attribute — verified:

```
SparqlSQLSpaceImpl (PRODUCTION) has entity_lock_manager: False
class attr present at all                            : False
```

So `_lm` is `None` on every request, `if _lm:` is false, and no lock is ever
taken. **Silently** — the only log line in this area fires when *acquiring* a
lock fails, not when there is no lock manager at all.

This is not one call site. `getattr(space_impl.backend, 'entity_lock_manager',
None)` appears **7 times in `kgentities_endpoint.py` and once in
`kgdocuments_endpoint.py`**, plus `segmentation_worker.py`. Every one of those
write paths runs unserialized in production, and every one looks locked when
read.

`getattr(..., None)` is what makes this invisible: it turns "this backend does
not implement the concurrency control" into "no locking needed here", and those
are not the same statement.

## Proposed fix

**No Fuseki code is to be reused.** The lock manager above is Fuseki-backend
code; the fix is native to `vitalgraph/db/sparql_sql/`, and it turns out to be
smaller than porting anything would have been.

The two defects collapse into **one** change. `with_deadlock_retry` already
hands `body` a pooled connection inside an open transaction:

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        return await body(conn)
```

So make the upsert run as that `body`, and take a **transaction-scoped** advisory
lock as its first statement:

```python
async def _upsert(conn):
    await conn.execute("SELECT pg_advisory_xact_lock($1)", _entity_lock_key(uri))
    # delete + store, now serialized and atomic together
```

That single change gives atomicity and serialization at once: request B blocks
on the lock until A commits, then sees A's committed state and deletes it
properly. The corruption cannot occur.

`pg_advisory_xact_lock` is deliberately the *transaction*-scoped variant, and it
is a better fit here than the session-scoped design it replaces:

- **It releases at commit or rollback**, automatically. Nothing has to remember
  to unlock, and a crashed request cannot strand a lock.
- **It needs no dedicated connection**, so there is no single-connection
  bottleneck and no shared-connection lifecycle to manage.
- **It needs no `asyncio.Lock` layer.** That layer exists in the Fuseki design
  only because session locks on one shared connection are reentrant — two
  requests would both "acquire" the same key. Each transaction here has its own
  pooled connection, so PostgreSQL serializes them directly and the reentrancy
  problem never arises.

Write `_entity_lock_key(uri) -> int` natively in the `sparql_sql` package: a
SHA-256 of the URI truncated to a signed 64-bit integer. It is four lines and a
standard technique; deriving it independently is cheaper than a dependency on
another backend's module.

Then, separately:

- **Delete the dead ceremony.** Once serialization lives in the write path where
  the transaction is, the eight
  `getattr(space_impl.backend, 'entity_lock_manager', None)` blocks in the
  endpoints are no-ops for this backend and should go, rather than being left to
  read as protection. Locking belongs next to the transaction it protects, not
  in an endpoint several layers above it.
- **Stop failing open silently** wherever a capability is probed with
  `getattr(..., None)`. Absence should say so once, at WARNING, naming the
  consequence. Same argument as the `slot_sort_block` gate in issues/167:
  declining to protect is defensible; being quiet about it is not.

Independently: **`is_create` should not restamp `hasObjectCreationTime` on a
subject that already has one.** Even with atomicity and locking, an upsert that
replaces an existing entity currently rewrites its creation time to now, which
is wrong on its own terms — creation time is not a property of the latest write.
A separate small bug this investigation surfaced.

## Verification

- A test that fires two concurrent upserts of the same entity URI and asserts
  exactly one `hasObjectCreationTime` and one `hasObjectModificationDateTime`
  afterwards. It must fail against today's code — the race is real and
  reproducible, not theoretical, and a test that passes before the fix is
  testing nothing.
- Assert on **quad counts per (subject, predicate)**, not on the API response:
  the response looks fine either way, which is exactly why this survived in
  production from June to August.
- Re-run the listing page that was empty (`offset 200`) and confirm 25 rows.
- Assert the upsert path actually takes the lock — that
  `pg_advisory_xact_lock` is issued inside the same transaction as the delete
  and store, not merely that a helper exists. The failure this issue records is
  a capability that was present in the codebase and absent at runtime, so a test
  that only checks for presence would have passed throughout.

## Scope note

The repair script cleans the 1,233 existing bad rows. It does **not** close this
race — as long as the upsert is two operations and production takes no lock, the
corruption can recur. The last observed occurrence was 2026-08-04, so this is
not currently accumulating fast, but nothing has changed to prevent it.
