# 174 — The remaining write paths take no entity lock

**Status:** open
**Raised:** 2026-09-07, from the cleanup in issues/173
**Related:** issues/173 (the race that corrupted 243 subjects and the lock that
fixes it), `vitalgraph/db/sparql_sql/entity_lock.py`

## What this is, and what it is not

issues/173 fixed one write path — UPSERT — and removed the endpoint-level lock
ceremony that had been decorative since Fuseki was deprecated. Serialization now
lives next to the transaction it protects, in
`upsert_objects_atomic` and `update_entity_graph`.

**Every other write path still takes no entity lock. None of them ever did on
this backend** — the removed ceremony resolved to `None` on every request — so
nothing was lost. But the gap is now visible instead of papered over, and it
should be closed deliberately rather than left implicit.

**No corruption has been observed on any path below.** issues/173 had 243
corrupted subjects as evidence; this issue has none. It records a class of risk
identified by reading, and the point of writing it down is to decide which paths
are genuinely concurrent before adding locks speculatively. A lock on a path
nothing contends for costs latency and buys nothing.

## Ranked by how closely each resembles the bug that did happen

### 1. Entity delete — same shape as the fixed bug, one-line fix

`delete_entity_graph_bulk` (`sparql_sql_space_impl.py`) is atomic but **not
exclusive** — exactly what `update_entity_graph` was before issues/173:

```python
async def _do_delete(conn):
    subject_rows = await conn.fetch(          # READ: which subjects belong
        "SELECT DISTINCT subject_uuid ... WHERE predicate_uuid = $1 ...")
    ...
    # DELETE those subjects
```

Membership is read, then acted on. An upsert committing between the read and the
delete adds subjects the delete will not see, leaving **orphaned rows under a
deleted entity** — a typed object with a partial graph, which is the failure
`issues/091` already recorded once from a different cause.

The read is of `hasKGGraphURI`, a mutable predicate, and the code comment
directly above already acknowledges it is "a snapshot of ONE mutable predicate".

Fix: `await lock_entities(conn, [entity_uri])` as the first statement of
`_do_delete`, identical to what `update_entity_graph` now does. This is the one
recommendation here that needs no further investigation.

### 2. Frame create / delete / update — read-modify-write on an entity's frames

`delete_frame` reads a count, then issues a SPARQL DELETE. The read feeds the
reported count rather than the delete's scope, so the visible risk is a count
that disagrees with what was removed — a reporting inaccuracy, not corruption.

The frame **create and update** paths are the ones worth checking: they modify
the frame set belonging to an entity, and two concurrent writers to the same
entity are exactly the pattern that produced issues/173. Whether they read
current state before writing has NOT been traced here, and that determination
should come before any lock is added.

### 3. Document segmentation — largely already serialized

Lowest risk, and the reason is worth recording so nobody adds a redundant lock:
`SegmentationJobManager.claim_next` dequeues with `SELECT ... FOR UPDATE SKIP
LOCKED`, so two workers cannot claim the same job. The advisory lock that used
to wrap `_execute_segmentation` was guarding something the queue already
guarantees.

Residual risk is narrow: two *distinct* jobs targeting the same document URI,
concurrently. Whether the queue admits that — whether jobs are unique per
document — was not established here and is the question to answer before acting.

## Progress — 2026-09-07

### 1. Entity delete — LOCKED. Race demonstrated, then closed.

`lock_entities(conn, [entity_uri])` is now the first statement of
`_do_delete` in `delete_entity_graph_bulk`.

**The first test I wrote proved nothing** — it passed with and without the lock,
because the window between the read and the delete is normally microseconds and
the upsert's own lock plus row-level contention hid it. By the standard this
issue sets, that test was worthless as evidence.

Widening the read→delete window to 2s and removing the lock reproduced it
**3 times out of 3**: a concurrent upsert committed in the window, its new
member subject was invisible to the delete's snapshot, and the graph was left
**orphaned — 1 subject of 4 remaining under an entity that reported as deleted**.
Restoring the lock with the SAME widened window gave a consistent result 3 times
out of 3.

So the race is real and the lock closes it. It is also **narrow in production**:
the window is normally tiny, which is why it has not been observed. It widens
under load, a slow plan, or a lock wait.

### 2. Frame create / update — read-then-write CONFIRMED, not a one-line fix

Traced. `update_frames` reads (`validate_frame_ownership`), then assigns
grouping URIs, then writes via `create_entity_frame` — across three processors
with **no shared transaction**. There is no single connection to take a lock on,
so serializing it means threading one through those layers first. That is a
refactor, not an addition, and it is deliberately NOT done here.

### 3. Document segmentation — safer than assumed, one residual gap

`claim_next` uses `FOR UPDATE SKIP LOCKED`, so two workers cannot take the same
job. `enqueue` also cancels any pending/in_progress job for the document before
inserting.

But that cancel-then-insert is itself unserialized, and the
`segmentation_jobs` table has **no unique constraint on `document_uri`** — only
a plain index. Two concurrent enqueues can therefore both cancel, both insert,
and leave two pending jobs for one document, which two workers may then claim
simultaneously. The fix is a partial unique index on `document_uri` where status
is pending or in_progress; that needs a migration script, since schema changes
here are made only by an explicit action.

### 4. NEW — `touch_entity_modification_time` is a SECOND, still-live race

Not in the original scope of this issue, and the more important finding.

It writes `hasObjectModificationDateTime` with an unserialized SPARQL
DELETE/INSERT. Two concurrent touches both match the old value, both delete it,
and both insert their own — the exact corruption issues/173 repaired.

**Evidence, from the backup taken before that repair:**

| pattern | subjects | implies |
|---|---|---|
| both timestamps duplicated | 239 | the upsert race (writes both) |
| **modification time only** | **4** | a different writer |
| creation time only | 2 | — |

The upsert race cannot explain the modification-only cases: it stamps both
properties. Those four are dated 2026-07-27, 2026-08-07, 2026-09-02 and
**2026-09-06** — spread out rather than clustered like the two upsert incidents,
and the most recent is the day before this was written. This mechanism is
active, and issues/173's fix does not cover it.

It is not a one-line fix either: `execute_sparql_update` acquires its own
connection internally, so the update cannot join a locked transaction. Closing
it means either rewriting the touch as direct SQL in a locked transaction
(straightforward — it is a single triple with a known subject, predicate and
graph) or giving the SPARQL update path a way to run on a caller's connection.

## What to decide## What to decide

For each path: **is it actually concurrent in production?** Entity writes are,
demonstrably — that is what issues/173 recorded, with a client retry at ~31s
intervals as the trigger. Whether frame writes and document segmentation see the
same pattern is a question about how the callers behave, not about this code.

`lock_entities(conn, uris)` is available and takes keys in sorted order, so
adding it to a path is a one-line change and multiple paths locking the same
entities cannot deadlock against each other.

## Verification, when a path is locked

Follow issues/173: a test that fires two concurrent writers at the same entity
and **fails without the lock**. The race there reproduced 3 times out of 3 with
the lock line removed and 0 out of 3 with it, which is what made the fix
credible. A concurrency test that passes before the change is testing nothing.

Assert on rows in the database, not on the API response — both writers returned
success in the issues/173 case, which is why it survived two months.
