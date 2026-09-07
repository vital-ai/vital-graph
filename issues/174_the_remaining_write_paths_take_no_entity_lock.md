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

### 2. Frame create / update — PLANNED. Smaller than first assessed.

**Correcting the earlier entry.** It said the read and the write "span three
processors with no shared transaction, so there is no connection to take a lock
on". That is wrong about the write. The mutation is already ONE transaction:
`SparqlSQLBackendAdapter.update_subjects_graph` does subject-level delete +
insert inside `async with conn.transaction()`, the same shape as
`update_entity_graph`, and the production adapter has it. It is atomic but not
exclusive — exactly the gap the other two paths had.

Two other things that entry got wrong or missed:

- `handle_frame_update_deletion` — the find-subjects-then-SPARQL-DELETE block
  cited as the risky read-then-write — **has no callers.** It is dead code.
- The SPARQL quad-diff fallback in `execute_atomic_frame_update` is dead for the
  production adapter too, since it is guarded on
  `hasattr(backend_adapter, 'update_subjects_graph')`, which is true.

So the live write path is one transaction, and the work splits cleanly.

#### Phase 1 — lock the write transaction, keyed on the GRAPH ROOT

**Not on the entity URI.** An earlier draft of this plan said to lock
`entity_uri`, which is wrong for half the frames in the system: frames are
either top-level **Assertions**, which have no enclosing entity at all, or
**Aspects**, which are entity-enclosed *or* children of an Assertion. There is
no entity URI to lock in the Assertion case.

The concept that generalises is **the unit a write replaces**, and the two paths
define it differently:

| path | processor | lock unit | carried as |
|---|---|---|---|
| entity-enclosed (Aspect) | `kgentity_frame_create_impl` | the entity | `kGGraphURI` |
| standalone (Assertion) | `kgframe_create_impl` | **each frame, independently** | `hasFrameGraphURI` |

**THERE IS NO FRAME-GRAPH.** This is the part to get right, because the
entity-graph analogy does not carry over and inventing one would send an
implementer looking for an ancestor walk that has nothing to find. A frame is
grouped with its OWN members and nothing else: each frame carries
`hasFrameGraphURI` pointing at itself, and its slots and edges point at that
frame. Deeply nested frames are not chained to an ancestor — each is an
independent object.

Confirmed on production: **482,096** subjects whose `hasFrameGraphURI` points at
themselves (the frames), against **5,641,635** member rows pointing at
**479,616** distinct targets. Distinct targets tracking the frame count is what
"every frame groups only its own members" looks like; a chained hierarchy would
show far fewer targets than frames.

Two consequences for the lock:

- **Each frame is its own lock unit.** Concurrent writes to two different frames
  do not exclude each other, including when one is nested inside the other's
  structure. That is correct, not a gap — they are independent objects with no
  shared graph to corrupt.
- **There is no root to fragment.** An earlier revision of this plan worried
  that a deep hierarchy would split the key, so two writers "under one root"
  would miss each other. That concern is void: there is no root.

`kgframe_create_impl` says as much in its own header — *"Does NOT use entity_uri
or kGGraphURI. Uses only frameGraphURI for grouping individual frame
members."*

**The two key spaces are disjoint, and that is correct rather than a gap.** An
Assertion frame carries no `kGGraphURI` and no entity edge, so
`delete_entity_graph_bulk` — which finds subjects by `kGGraphURI = entity` —
can never touch one. There is nothing to be mutually excluded from. Aspect
frames DO take the entity key, because entity upsert and entity-graph delete
both hold it, and that cross-path exclusion is the point of this phase.

A standalone create may write **several independent frames in one call**.
`lock_entities` sorts and deduplicates its keys, so passing the whole set is
safe: the total order is what stops two multi-frame writes deadlocking against
each other.

| file | change |
|---|---|
| `kg_backend_utils.py:1430` `update_subjects_graph` | accept `lock_uris=None`; `await lock_entities(conn, lock_uris)` first inside the transaction |
| `kgentity_frame_create_impl.py:443` `execute_atomic_frame_update` | accept the root, pass `lock_uris=[entity_uri]` |
| `kgentity_frame_create_impl.py:203` | pass `entity_uri` — `create_entity_frame` already has it (line 115) |
| `kgframe_create_impl.py:303` `execute_atomic_frame_update` | same, with the frame URIs |
| `kgframe_create_impl.py:285` `create_frame` | pass the distinct frame URIs (the `hasFrameGraphURI` values assigned in its step 2 — one per frame, each pointing at itself) |

Roughly seven lines across three files. Note there are **two** separate
`execute_atomic_frame_update` implementations, one per processor — both write
through `update_subjects_graph` and both need the argument, or the standalone
path is left unserialized while looking done.

`lock_entities` is named for its first caller but locks graph roots generally;
worth a docstring line saying so rather than a rename, since entity upsert and
delete already use it under the old name.

#### Phase 2 — validation-to-write atomicity. Genuinely blocked.

`validate_frame_ownership` (`kgentity_frame_update_impl.py:110`) reads on its
own connection, and the write happens much later in a different transaction.
Phase 1 does not make the validation current: a frame reparented between the
check and the write is still acted on from a stale read.

Closing that means holding one lock from before the validation through to the
commit, which needs a connection spanning both — the write-scope work in
issues/175 class 2. **This is the part that is genuinely blocked**, and it was
the whole of what the earlier entry described.

Its risk is also narrower than the corruption class: the failure is acting on
stale ownership, not a single-valued predicate gaining a second value. Worth
doing after class 2 exists; not worth a bespoke mechanism before then.

#### Verification

Same standard as the rest: two concurrent frame writes to one entity, asserting
on rows rather than the API response, and it **must fail without the lock**. The
entity-delete lock in item 1 needed its window widened to 2s before the race
appeared at all — expect the same here, and treat a test that passes
immediately as untrustworthy rather than as good news.

Also assert the cross-path exclusion Phase 1 exists for: an ASPECT frame write
concurrent with an entity-graph delete on the same entity must serialize. That
is what the entity key buys, and nothing else tests it.

And cover both frame kinds, because they take different keys and a test using
only one would leave the other path unverified: two concurrent writes to one
ASSERTION frame must serialize on that frame's own URI, with no entity involved
anywhere. Add the negative case too: concurrent writes to two DIFFERENT frames
must NOT block each other, since they are independent units — a lock that
serialized them would be over-broad and would show up as latency under load.

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

**How much does locking it cost?** It depends on whether a single connection
already spans the WRITE — which is more often true than first assessed, since
both `update_entity_graph` and `update_subjects_graph` already run their
mutation in one transaction. Making the READ atomic with the write is the
expensive part, and only phase 2 of the frame work needs it:

| path | cost |
|---|---|
| entity delete | one line — **done** |
| frame create/update — phase 1 | ~4 lines; the write is already one transaction |
| frame create/update — phase 2 | blocked on the write scope (issues/175 class 2) |
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
