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

#### Phase 1 — lock the write transaction, keyed on the GROUPING

**Not on the entity URI unconditionally.** An earlier draft said to lock
`entity_uri`. Top-level frames have no enclosing entity — WordNet is the
worked example, a space built entirely of them — so there is nothing to lock
there.

**And do NOT classify by form type.** `hasKGFormType` describes what a frame
MEANS; `kGGraphURI` describes what it BELONGS TO, and only the second determines
the lock. They come apart in practice. Measured on `prod_kg`:

| | count |
|---|---|
| frames | 482,098 |
| explicitly `KGFormType_Aspect` | 206,219 |
| explicitly `KGFormType_Assertion` | **0** |
| carrying `kGGraphURI` (entity-scoped) | **482,098 — all of them** |
| carrying BOTH `kGGraphURI` and `hasFrameGraphURI` | 482,098 |

So ~275,879 frames there have no form type set at all, which DEFAULTS TO
ASSERTION — while still being entity-scoped. A lock keyed on form type would
take the frame's own URI for every one of them and never contend with the entity
writers, which is the failure this phase exists to prevent, delivered while
looking correct.

Key on the grouping the write actually uses: `kGGraphURI` present means the
entity owns these subjects; absent means the frame stands alone.

The concept that generalises is **the unit a write replaces**, and the two paths
define it differently:

| path | processor | lock unit | decided by |
|---|---|---|---|
| entity-scoped | `kgentity_frame_create_impl` | the entity | writes `kGGraphURI = entity` |
| standalone (e.g. WordNet) | `kgframe_create_impl` | **each frame, independently** | writes no `kGGraphURI` at all |

The processor already encodes the distinction, so the caller never has to infer
it: each one knows which grouping it is writing. That is the safest place for
the decision to live — inferring it from the data at write time would mean
reading state the write is about to replace.

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

**The two key spaces are disjoint, and that is correct rather than a gap.** A
standalone frame carries no `kGGraphURI` and no entity edge, so
`delete_entity_graph_bulk` — which finds subjects by `kGGraphURI = entity` —
can never touch one. There is nothing to be mutually excluded from.
Entity-scoped frames DO take the entity key, because entity upsert and
entity-graph delete both hold it, and that cross-path exclusion is the point of
this phase.

Note the disjointness follows from the GROUPING, not the form type: an
entity-scoped frame whose form type is unset (and therefore Assertion) still
belongs to the entity and still takes the entity key.

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

#### Item 5 subsumes 1c and item 4 — do it first

Traced when picking up the next piece of work. **Frame delete and
`touch_entity_modification_time` both write through
`execute_sparql_update`**, so neither is separate work: locking the SPARQL
update path closes all three at once.

| item | writes via | covered by item 5? |
|---|---|---|
| 1c — frame delete (`delete_frame`) | `execute_sparql_update` | **yes** |
| 4 — `touch_entity_modification_time` | `execute_sparql_update`, as an `UpdateModify` that materialises bindings | **yes** |
| 5 — raw SPARQL updates generally | itself | yes |

This reverses the order they were listed in. Item 4 was called the highest-value
remaining item because it is the one still actively corrupting production — 42
subjects on `lead_prod`, most recent 2026-09-06 — and Option B proposed
rewriting it as direct SQL in a locked transaction. That rewrite is now
unnecessary: once the SPARQL update path locks, the touch is serialised where it
stands, with no change to the function at all.

Item 5 is also the most intricate piece in this issue, so the sequencing is not
free — but doing 1c and 4 separately would mean writing two bespoke fixes and
then a general one that made both redundant.

#### Phase 1c — frame DELETE takes the same key

Folded in rather than deferred: once create and update serialize on the
grouping, a concurrent delete is the only remaining way to interleave with them,
and a plan that locked two of the three would leave the path open while reading
as finished.

`_delete_frame_by_uri` already resolves the owning entity — it does the
`kGGraphURI` lookup for cache invalidation (see the fix in `af3c153`, which made
that lookup unconditional). So the key is already in hand at the point the lock
is needed; nothing new has to be read.

Same rule as create/update: the entity when the frame is entity-scoped, the
frame itself when it stands alone.

Note this is a different concern from the one assessed earlier for frame delete.
That assessment was about its own internal read-then-write — a count read that
feeds the reported number rather than the delete's scope, hence "a reporting
inaccuracy, not corruption". Both readings are true: it is low risk in
isolation, and it still needs the key to be exclusive against the writers.

#### Resolved: mixed writes

No KG endpoint mixes entity-scoped and standalone frames in one call, so no
caller assembles a mixed key set. `lock_entities` would handle one safely if
that ever changed, being sorted and deduplicated, but the plan does not need to
provide for it.

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

### 5. Raw SPARQL update must join the same locking, or it defeats the rest

Locking entity and frame writes still leaves `execute_sparql_update` free to
modify the same subjects concurrently. It is not a hypothetical side door: it is
the path the frame and entity endpoints themselves fall back to, and it is
reachable directly.

**The plumbing for this already exists, for a different reason.**
`_concrete_subjects_from_update_ops` extracts the concrete subject URIs an
update touches, so the edge, frame_entity and slot_sort tables can be
resynchronised afterwards. The same set identifies what the update must lock —
the analysis is already being done, and is currently used only after the write.

**But subjects are not keys.** The lock key is the GROUPING — the entity for an
entity-scoped subject, the frame itself for a standalone one — so the update
must resolve each concrete subject to its grouping before locking. That is one
read on the connection it already owns, ahead of the write transaction. Without
that resolution it would lock subject URIs, contend with nobody, and produce the
same false sense of protection this issue keeps finding.

**WHERE-bound subjects need the lock taken later, not skipped.**
`_concrete_subjects_from_update_ops` cannot see them — it is static analysis over
the AST, and it says so. But the emitted SQL materialises the change set into
`_upd_bindings` before it writes anything, so the subjects ARE available at
runtime. See the section below; the lock goes after that step rather than before
the statement.

That residue HAS NO BACKSTOP. It was argued here that issues/175's constraint
would cover it — a constraint holding regardless of whether the writer can name
its subjects. **That constraint is withdrawn**: VitalGraph is a general quad
store, any predicate may be single- or multi-valued at any time, and a unique
index would silently discard legitimate data. So this path needs a real answer
of its own, from the options below.

#### The concrete case: a SPARQL update touching a slot inside an entity graph

Worked through because it is the interleaving that matters most, and it is
already happening.

An entity operation holds `pg_advisory_xact_lock(entity_uri)` and is doing
delete-then-insert over every subject with `kGGraphURI = entity`. A SPARQL
update modifies a slot belonging to that entity graph. **The SPARQL update does
not take the lock**, so the lock does not exclude it, and the outcome depends on
commit order:

- **SPARQL commits first.** The entity operation's full-graph replace then
  deletes and rewrites that subject from the client payload, so the slot change
  is **silently overwritten** — a lost update, with both writers reporting
  success.
- **SPARQL commits second.** Its `DELETE` targets the value the entity operation
  has already replaced, matches nothing, and its `INSERT` then adds a **second
  value** to a slot that may hold one.

Row-level locking does not prevent either: it serialises writes to the same ROW,
while both failures are about the SET of rows changing underneath a decision
already made.

**This is measurable on production, in the space already repaired:**

| predicate | subjects | holding more than one value |
|---|---|---|
| `hasDateTimeSlotValue` | 390,756 | **92** |
| `hasTextSlotValue` | 1,852,047 | **94** |
| `hasKGSlotType` | 2,821,011 | 0 |

The distribution is itself evidence for the mechanism. `hasKGSlotType` is set
once when a slot is created and never modified — zero violations. The two VALUE
predicates are the ones that get updated, and they are the ones corrupted.

Both are `multiple_values=False` in the ontology, so both are invariant
violations, not legitimate multi-valued data.

**Neither existing remedy covers this today.** The repair in
`scripts/repair_duplicate_single_valued.py` handles only the two
entity-level timestamps. The default predicate set in issues/175 is
entity-level too. And the lock does not reach a writer that does not take it.
So this class is currently unrepaired and unprotected, and it is the direct
answer to "what happens if a SPARQL update modifies a slot while an entity graph
operation is underway": today, it corrupts, and 186 subjects show it has.

#### WHERE-bound updates CAN be locked — the change set is already materialised

**Correcting two earlier claims in this issue.** It said WHERE-bound subjects
"cannot be enumerated without executing" and therefore could not be serialised,
and issues/175 leaned on that to argue a constraint was the only backstop. Both
were wrong, and the mistake was reading the AST-level helper
(`_concrete_subjects_from_update_ops`, which is static analysis and genuinely
cannot see them) instead of the SQL the pipeline actually emits.

`emit_update.py` builds a statement SEQUENCE, and the first statement
materialises the whole change set:

```
Step 1: CREATE TEMP TABLE _upd_bindings ON COMMIT DROP AS <where_sql>
Step 2: DELETE ... driven by _upd_bindings
Step 3: term upserts, then INSERT ... driven by _upd_bindings
```

The subjects are known after Step 1 and nothing has been written yet. A lock
step slots between Steps 1 and 2: read the subject column(s) out of
`_upd_bindings`, resolve each to its grouping, and take the locks in sorted
order — the same keys and the same order every other path uses.

This is safe with respect to lock ordering. Everything before the lock is a
read, so no row locks are held when the advisory locks are acquired, and no
inversion is possible against a writer that locked first.

**DECIDED: lock, then re-materialise.** Bindings computed in Step 1 may be
stale by the time the lock is granted, since another writer can commit in
between. Re-running the WHERE under the lock closes that; applying the stale
bindings only narrows the window and should not be described as closing it. The
second evaluation is paid only by updates that are WHERE-bound.

**The lock key is computable in SQL**, so this needs no application round trip
and no restructuring of `execute_sparql_update` — the whole thing stays inside
the emitted statement sequence:

```sql
('x' || substr(encode(sha256(uri::bytea), 'hex'), 1, 16))::bit(64)::bigint
```

Verified to produce byte-identical keys to `entity_lock.entity_lock_key` for the
same URIs, which matters because a SPARQL update and an entity write must land
on the same key or they will not exclude each other.

**The loop is not optional, and this is the part to get right.** Re-materialising
under the lock can reveal subjects the first pass did not see, belonging to
groupings not yet locked — so one lock-then-remat pass is not a fixed point. The
sequence has to iterate until the key set stops growing:

1. materialise `_upd_bindings` from the WHERE
2. derive the grouping keys it implies
3. take any not already held, in sorted order
4. re-materialise
5. if the key set grew, go to 3; otherwise apply

Advisory locks are transaction-scoped and accumulate, so nothing has to be
released between iterations, and each pass blocks more concurrent writers than
the last — which is why it converges rather than spinning. In the uncontended
case, which is almost all of them, iteration 2 simply confirms stability and the
cost is exactly two evaluations of the WHERE.

Expressible as a `DO` block using `EXECUTE` for the WHERE text, keeping it one
statement sequence rather than a client-side loop. Cap the iterations and fail
loudly if the cap is hit: a WHERE whose result keeps changing under an
accumulating lock set is a signal worth surfacing, not something to paper over
by proceeding with whatever the last pass produced.

**Ordering matters.** Whatever locks here must take keys in the same sorted
order `lock_entities` uses, or a SPARQL update and an entity write acquiring the
same pair in opposite orders will deadlock rather than queue.

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
| frame create/update/delete — phase 1 | ~7 lines; the write is already one transaction |
| frame create/update — phase 2 | blocked on the write scope (issues/175 class 2) |
| raw SPARQL update | subject→grouping resolution, plus a lock; WHERE-bound subjects cannot be covered at all |
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
