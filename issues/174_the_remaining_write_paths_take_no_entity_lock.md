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

## The paths, and where each stands — 2026-09-07

### 1. Entity delete — LOCKED. Race demonstrated, then closed.

`delete_entity_graph_bulk` resolves membership and then acts on it:

```python
async def _do_delete(conn):
    subject_rows = await conn.fetch(          # READ: which subjects belong
        "SELECT DISTINCT subject_uuid ... WHERE predicate_uuid = $1 ...")
    ...
    # DELETE those subjects
```

The read is of `hasKGGraphURI`, a mutable predicate — the code comment directly
above it already concedes it is "a snapshot of ONE mutable predicate". An upsert
committing between the read and the delete adds subjects the delete never sees,
leaving orphaned rows under an entity that reports as deleted; `issues/091`
recorded that same end state once already, from a different cause.

`lock_entities(conn, [entity_uri])` is now the first statement of `_do_delete`,
the same lock and ordering the upsert path uses.

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
so serializing it means threading one through those layers first.

That is a refactor, not an addition, and rushing it would be worse than leaving
it recorded. A lock taken on a connection other than the one doing the write
protects nothing while looking as though it does — which is precisely the defect
issues/173 documented, where eight endpoint call sites read as locked and none
were. Half-serializing this path would recreate that, one layer down.

`delete_frame` is separate and lower risk: it reads a count and then issues a
SPARQL DELETE, but the read feeds the count it reports rather than the delete's
scope. The exposure is a count that disagrees with what was removed — a
reporting inaccuracy, not corruption.

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

## Scoping the fix for item 4 — two options, measured

### Option A — give `execute_sparql_update` a caller-supplied connection

The mechanical part is trivial; the semantic part is the entire cost.

The function is **224 lines** and opens **three independent transactions** on
the one connection it acquires:

| line | purpose |
|---|---|
| 2356 | the main write — "whole batch rolls back cleanly" (issues/019) |
| 2382 | cleared-graph auxiliary cleanup (issues/064) |
| 2418 | edge / frame_entity / slot_sort sync |

The 2418 block states its guarantee outright: *"run it in its OWN transaction …
so a sync failure rolls back cleanly (leaving the committed quads intact)
instead of poisoning the pooled connection."*

**asyncpg turns a nested `conn.transaction()` into a `SAVEPOINT`** — confirmed
in its source, not assumed. So a caller passing a connection already inside a
transaction silently converts all three, and that guarantee becomes false: the
quads are no longer committed, they are in the caller's transaction. A sync
failure rolls back to a savepoint while the outer transaction continues, and if
the outer one later rolls back, the quads go with it.

Adding `conn=None` is about five lines and all **48 call sites** keep working,
since it defaults. Making it CORRECT means deciding what each of those three
blocks should mean when nested and re-establishing the guarantee each was
written for — three separate issue-referenced behaviours on a hot write path.
That is a design decision, not a refactor, and the five-line version is the
dangerous one precisely because it looks finished.

### Option B — rewrite `touch_entity_modification_time` as direct SQL

Smaller, and touches nothing else:

- **3 call sites**, all in `kgentities_endpoint.py`, all already wrapped in
  try/except and logged as "non-critical".
- The plumbing exists: `add_rdf_quads_batch_bulk` and
  `remove_rdf_quads_batch_bulk` both already accept `connection=`, so term
  interning and the stats tables stay correct inside a locked transaction.
- It is a single triple with a known subject, predicate and graph, so it needs
  no SPARQL at all — which also drops the Jena sidecar compile round trip and
  makes it faster.
- Roughly 30–40 lines in `kg_server_properties.py`, plus a concurrency test of
  the shape now standard here (must fail without the lock).

### Recommendation: B

Option A is a plausible general capability, but adopting it to fix this race
means changing transaction semantics for 48 call sites to solve a problem that 3
call sites have — and the blast radius lands on exactly the guarantees three
prior issues were written to establish.

Option A is worth doing IF something later genuinely needs a SPARQL update
inside a caller's transaction. That deserves its own issue, with the three
nesting questions answered deliberately rather than as a side effect of an
unrelated fix.

## What to decide

Two questions, and they are different for each remaining path.

**Is it actually concurrent in production?** Entity writes demonstrably are —
issues/173 recorded it, with a client retry at ~31s intervals as the trigger,
and item 4 above shows a second mechanism still producing duplicates as recently
as 2026-09-06. Whether frame writes and duplicate segmentation enqueues see the
same pattern is a question about how the callers behave, not about this code,
and is unanswered.

**How much does locking it cost?** Only where a single connection already spans
the read and the write is this a one-line change — that was true of items 1 and
of the upsert in issues/173, and is NOT true of what remains:

| path | cost |
|---|---|
| entity delete | one line — **done** |
| frame create/update | thread a connection through three processors first |
| segmentation enqueue | a partial unique index, so a migration script |
| `touch_entity_modification_time` | ~30–40 lines, direct SQL (Option B above) |

`lock_entities(conn, uris)` takes keys in sorted order, so wherever a connection
IS available, adding it is one line and paths locking the same entities cannot
deadlock against each other. The constraint is never the lock; it is whether the
read and the write share a transaction to hang it on.

## Superseded in part by issues/175

Items 1 and 4 above are class-1 failures — a single-valued predicate holding two
values. issues/175 argues those belong in a database constraint rather than in
per-path locking, because a lock is opt-in per path and cannot protect a raw
SPARQL update or an endpoint not yet written. A partial unique index would have
prevented item 4 without modifying `touch_entity_modification_time` at all.

Item 1's entity-delete race is NOT covered by that: an orphaned entity graph is
not a uniqueness violation, and needs the read and the write to share a
transaction. The lock added here remains the right fix for it.

That split — invariant vs multi-statement consistency — is the distinction
issues/175 draws, and it is why "add a lock everywhere" is not the whole answer.

## Verification, when a path is locked

Follow issues/173: a test that fires two concurrent writers at the same entity
and **fails without the lock**. The race there reproduced 3 times out of 3 with
the lock line removed and 0 out of 3 with it, which is what made the fix
credible. A concurrency test that passes before the change is testing nothing.

Assert on rows in the database, not on the API response — both writers returned
success in the issues/173 case, which is why it survived two months.
