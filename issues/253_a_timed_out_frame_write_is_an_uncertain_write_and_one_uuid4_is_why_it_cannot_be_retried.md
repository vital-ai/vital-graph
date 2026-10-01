# 253 — A timed-out frame write is an uncertain write, and one `uuid4()` is why it cannot be retried

## RETRACTION 2026-10-01 — I READ THE WRONG DATABASE, AND IT INVERTS TWO
## FINDINGS AND VOIDS ONE FIX'S JUSTIFICATION. Read this before anything below.
##
## The production application connects to **`vitalgraph-pg18-prod`** (PostgreSQL
## 18.4), taken from the task definition's `PROD_DB_HOST`. The Secrets Manager
## entry it draws its PASSWORD from (`vitalgraph/prod/database-new`) carries a
## `host` field naming a DIFFERENT, unrelated instance. I used the
## secret's host. Every "measured on production" claim about database SETTINGS or
## database LOGS below was therefore read from an instance the app does not use.
##
## Corrected, read as the app's own role on the right instance:
##
##     lock_timeout                        = 10000  (source: DATABASE)
##     statement_timeout                   = 60000  (configuration file)
##     idle_in_transaction_session_timeout = 60000  (configuration file)
##     running build: v0.0.77 / 0ba7f87f22e5 / deployed 2026-09-29 14:38:54 UTC
##
##   1. **`lock_timeout` IS 10 s, set via `ALTER DATABASE`, and `issues/231` was
##      RIGHT.** My "it is 0, so nothing bounds a lock wait" was the wrong
##      instance. A single-key lock wait has always been bounded at 10 s.
##   2. **PostgreSQL DID close those connections.** My "the client side did it,
##      because the database logged nothing" read the wrong instance's log. The
##      right one logs a FATAL for every one.
##   3. **The 5 lost writes are `idle_in_transaction_session_timeout`** — 60 s,
##      from the configuration file — and the match is exact: `FATAL: terminating
##      connection due to idle-in-transaction timeout` at 18:18:05, and four more
##      inside 21:00-21:59, against 5 app-side failures at 18:19:06, 21:32:03,
##      21:34:28, 21:39:26 and 21:43:38. Each FATAL precedes its app-side error by
##      61-93 s, which is the app discovering the dead connection at rollback.
##      **Not a lock wait (bounded at 10 s) and not asyncpg's `command_timeout`.**
##   4. **Part 5's justification is VOID.** The request-pool `lock_timeout` fence
##      was built because "nothing bounds a lock wait". Something does. The fence
##      now duplicates a database-level setting at the same value; it is harmless
##      and explicit, and it is NOT the fix for the 5 losses. Decide whether to
##      keep it on its own merits, not on the reason it was written.
##   5. **THE REAL DEFECT IS NOW IDENTIFIED and still unfixed** — see "ROOT CAUSE
##      FOUND". `add_rdf_quads_batch_bulk` awaits `maybe_analyze` inside the
##      CALLER's transaction, and production ANALYZEs `rdf_quad` and `term` for
##      60-98 s each. Matched 4 for 4 against the database log, with each app
##      failure landing 1-2 s after an ANALYZE sequence ends.
##
## What is NOT affected by the mix-up: everything measured from the APPLICATION
## logs (the presync/total/BULK breakdowns, `issues/238`'s deployment and its
## effect, the 138 writes to one lead, the five failures and their durations), and
## everything measured locally (the 384x `frame_slot` result, the equivalence
## checks, the 55P03 mechanism). Those came from the app's own log group and a
## local database, neither of which depends on which RDS instance I opened.

## Status: SIX PARTS FIXED 2026-09-29/30, NONE DEPLOYED, and RE-BASED TWICE BY
## MEASUREMENT 2026-09-30. A later report of 5 writes that did not stick is
## explained in "the 5 failed writes" below: they are CONFIRMED LOSSES, caused by
## an unbounded lock wait meeting asyncpg's 60 s `command_timeout`, which kills
## the connection under the open transaction. Part 5 is the fix and is waiting on
## a deploy.
##
## Originally: PARTIALLY FIXED 2026-09-29 (four parts, tests pass, each checked
## against the reverted code), and RE-BASED BY MEASUREMENT 2026-09-30 — see
## "MEASURED 2026-09-30 — step 1". Read that section before acting on anything
## else here: it corrects this file's central number and one of its fixes.
##
## In short: `issues/238` is deployed and already took the median write from
## 1.112 s to 0.273 s and writes over 2 s from 29.72% to 0.47%. The work per
## write was never 7.2 s of scans — it was ~0.9 s of work plus a WAIT, and
## `lock_timeout = 0` on production means nothing bounds that wait. The scans
## are no longer the urgent item; the unbounded wait is, and part 2 below
## deliberately left the single-key case alone on a premise that measurement has
## now falsified.
##
## Production report received 2026-09-29, updated the same day with the
## caller-side breakdown and the lock-timeout census, and again with the
## caller-side investigation. Nothing measured on production from this side.
## Everything under "The mechanism" and "What the code says" is verified by
## reading the code at HEAD, and two of the numbers were already measured on
## production and written into it.
##
## THREE CLAIMS IN EARLIER DRAFTS OF THIS FILE ARE WRONG. They are corrected
## in place below and listed here so nobody acts on the version they read first:
##
##   1. "~128 of the frame timeouts come from the Salesforce -> KG lead sync."
##      NO. Every failed write is forwarded from ANOTHER SERVICE through the
##      API's `/api/kgentities`. See "Where the writes come from".
##   2. "The 09-26 spike probably already has an answer: the 6,810-entity bulk
##      delete of `issues/231`." NO — it was portal lead writes. See "The 09-26
##      spike".
##   3. "The post-write `ANALYZE` is the best-fit stall." NO. Demoted in the
##      second draft; see "A hypothesis this issue got wrong first".
##
## NAMING COLLISION, read this before following a cross-reference: the reporter
## keeps their findings in THEIR tracker's issue 044 §5-§7. This repository's
## `issues/archive/044` is a different, unrelated, FIXED issue (abandoned queries
## outliving their client). Where this file says "the reporter's 044" it means
## theirs.

## What is fixed

**1. The write is idempotent, so a replay is a no-op.** `vitalgraph/kg_impl/edge_uris.py`
is now the one home for a server-minted edge URI, and the three live mint sites
call it: the entity→frame edge (`kgentity_frame_create_impl.py`), the
parent→child entity edge (`kgentity_create_impl.py`) and the frame→slot edge
(`kgslot_create_impl.py`). The form is not new — `_create_parent_child_edges`
already composed `{source_id}_{destination_id}_edge` and now shares the helper,
which a test pins so nobody thinks a scheme was invented. The two dead
`_generate_uuid` helpers are DELETED rather than left unused. The fourth site
(`vitalgraph/kg/kgentity_create_endpoint_impl.py:149`) is NOT fixed: nothing
imports that module, and a change there would be untestable.

**2. Waiting is bounded per REQUEST, not per key.** `lock_entities` spends one
budget (`VITALGRAPH_ENTITY_LOCK_BUDGET_S`, default 10 s to match production's
`lock_timeout`) across a multi-key acquisition, re-deriving the remaining
allowance before each key, so twelve contended entities cost the same ceiling as
one instead of twelve times it. The SINGLE-key case — what a frame write does —
keeps byte-for-byte the statement it had, on the reasoning that one wait is
already bounded by the session's own `lock_timeout`. **THAT PREMISE IS FALSE ON
PRODUCTION: `lock_timeout` is 0 there, so the single-key wait — the reported case
— has no bound at all. Measured 2026-09-30; this is the first thing to fix.** `SET` is saved and restored rather than `SET LOCAL`:
we are inside the caller's transaction, where asyncpg nests ours as a savepoint
and a `SET LOCAL` would outlive its RELEASE (`bounded_lock_wait` already
documents this trap). A spent budget clamps to 1 ms and never to 0, because
PostgreSQL reads `lock_timeout = 0` as WAIT FOREVER — the bound would vanish at
the exact moment it is needed.

**Verified against a real server, because the whole bound rests on it:** a
second session holding `pg_advisory_xact_lock` on the same key, with
`lock_timeout = 250ms` set INSIDE the waiter's open transaction, fails with
`ERROR: 55P03: canceling statement due to lock timeout`. So `lock_timeout` does
apply to an advisory lock, a `SET` inside the transaction does take effect for
its own later statements, and 55P03 is the code to classify on. Note the local
cluster's default `lock_timeout` is 0, so locally this budget is the ONLY bound.

**3. A lock timeout names the lead.** `EntityLockTimeout` carries the URI, the
key and the wait; `_lock_timeout_failed` logs all three from the three locked
write paths (`update_subjects_graph`, `upsert_objects_atomic`,
`update_entity_graph`). The `return False` contract is unchanged, so nothing
downstream had to move. Only SQLSTATE 55P03 is relabelled — calling a syntax
error or a dead connection a lock timeout would send the next investigation to
the wrong place, and a test pins that.

**4. A failed write is reported as a failure — in an HTTP 200 body, as decided.**
The five sites that discarded `update_subjects_graph`'s boolean now raise
`SubjectWriteFailed` (`endpoint/impl/impl_utils.py`): three in
`kgframes_endpoint.py`, including the two LIVE slot paths that were feeding
`SlotCreateResponse(status=CREATED, created_count=N)` for writes that never
happened, and two in `kgrelations_endpoint.py`, which appended the relation URI
to `updated_uris` regardless.

The exception is TYPED for one reason: the two live handlers catch it and return
`STORE_FAILED` — "write failed for a describable data reason", which derives
`success=false` in a 200 — rather than letting it reach `except Exception` and
become a 500. **A first version raised `RuntimeError` and therefore produced a
500, which is the contract this codebase deliberately does not use for this case
(`model/result_status.py` reserves 500 for `ERROR`, a server-level fault). That
was reworked once the 200-vs-503 question below was decided.** Reverting the
handler mapping makes the test fail with `HTTPException: 500`, which is how the
decision is pinned rather than merely written down.

The three sites reachable only through helpers nothing calls keep the raise
unhandled: whoever wires them up has to decide their response, and a silent
`False` would let them repeat the defect.

**5. A request can no longer wait forever for a lock (2026-09-30).** The REQUEST
pool sets `lock_timeout` when it opens a connection —
`sparql_sql_db_impl._init_request_conn`, default 10 s, `VITALGRAPH_REQUEST_LOCK_TIMEOUT_S`
to change it, 0 to disable. Per CONNECTION, so it costs nothing per write, and it
is the thing that makes part 2's single-key reasoning TRUE rather than assumed;
`entity_lock`'s docstring now says so explicitly, because if this comes out the
single-key path silently becomes unbounded again.

**The INTERNAL pool is deliberately NOT fenced.** Background work legitimately
waits for locks — ANALYZE, VACUUM, an index build, a resync holding ACCESS
EXCLUSIVE — and a pool-wide fence would kill maintenance mid-way while the job
reported success, which is `issues/136` (an RDS `statement_timeout` killing 91%
of VACUUMs on the big quad table) in a new costume. Two of the tests exist only
to hold that asymmetry in place, and one holds the `0 means disable, not
"forever"` clamp, since PostgreSQL reads `lock_timeout = 0` the other way.

Why 10 s: at the measured ~0.25 s service time it still lets a queue of ~40
writes to one entity drain, so it fences the pathological case and not a
busy-but-healthy one; and the caller's own read timeout is 30 s, so anything
above that would be a fence only the client ever reaches — which is the situation
it replaces.

**6. The `frame_slot` pre-delete filter is indexable (2026-09-30).**
`sync_frame_slot_before_delete` had the exact shape `issues/238` diagnosed and
fixed in its twin: one arm was `IN (SELECT ... FROM edge WHERE ...)`, which
compiles to a hashed SubPlan, and a BitmapOr can only combine indexable
conditions — so a single unindexable arm forced the whole disjunction to a
SEQUENTIAL SCAN, giving a statement that deletes a handful of rows a cost
proportional to the size of the table. 238 fixed `entity_slot_sort` and left this
one; step 1 then measured it as 96.6% of the four pre-delete scans.

The edge indirection is now resolved eagerly into a second array
(`_edge_source_nodes`, both arms indexable via `idx_{space}_edge_dst_src` and
`idx_{space}_edge_edge`) and run in the caller's transaction immediately before
the DELETE, so it reads exactly the rows the subquery would have.

**MEASURED on a real 401,543-row `frame_slot`** (474,031-row edge table),
realistic 15-subject write, 5 runs, `force_custom_plan` as production uses:

    OLD (subquery arm)   Seq Scan    37.0 / 38.0 / 348.3 ms   11,260 buffers
    eager resolve        Bitmap       0.040 / 0.054 / 0.068 ms    459 buffers
    NEW (two arrays)     Bitmap       0.033 / 0.045 / 4.457 ms    215 buffers

**384x including the resolve.** Equivalence checked through the real function on
five input shapes — frame only, slots only, edges only, a whole write, and
unscoped — all agreeing with the old form on the same 7 rows, plus an unknown
subject deleting nothing. The indirect arms are the whole reason the filter is a
disjunction, so agreeing on those two is the part that matters.

A sweep found no other live instance of the pattern in the sync modules; the two
remaining mentions are the historical comments in these two files.

Tests: `tests/unit/test_server_minted_edge_uris_are_deterministic.py`,
`tests/unit/test_a_failed_subject_write_is_not_reported_as_written.py`,
`tests/unit/test_request_connections_bound_their_lock_wait.py`,
`tests/unit/test_frame_slot_delete_is_indexable.py`, and new classes in
`tests/unit/test_entity_lock.py`. Each was checked by REVERTING the
fix and confirming the failure, which is how the AST-based randomness guard was
found to be trippable by a comment before it was rewritten. Full unit suite:
5,103 tests, 0 failures. `tests/unit/test_update_lock.py`'s fake needed
`fetchval("SHOW lock_timeout")` — a SPARQL update locks many groupings, so it
takes the new bounded path.

### What is NOT fixed, and is the contention itself

~~The unbounded lock wait~~ and ~~the remaining scan time~~ are FIXED — parts 5
and 6 above, both 2026-09-30. Neither is deployed.

**Coalescing at the source**, which is theirs, and now has a named cause: the
apply form's autosave, 40 saves in 4.5 minutes on one lead.

**The LOST UPDATE.** A slower save overwriting a newer one needs a conditional
write or a server-side merge; nothing here addresses it, and the entity lock
cannot.

**No `lock_uris` was added anywhere.** The five sites above still take no entity
lock. That is a grouping decision, not a mechanical one — `update_subjects_graph`
warns that "locking the frame subjects instead would contend with nobody while
looking correct" — and for relations the right key is not obvious from the code.
Left open deliberately rather than guessed at.

**Existing duplicate edges are not repaired.** Every frame re-created before this
change still carries one stale `Edge_hasEntityKGFrame` per write. Counting them
per (entity, frame) pair is both the damage assessment and the repair's input.

**The status a refused write returns: DECIDED, keep the 200.** So the measured
caller still cannot see it — it throws only on a non-2xx, and 42,343 `updateLead`
calls logged 1 error — and that half of the fix belongs to the portal. What the
server now guarantees is that the body tells the truth: `STORE_FAILED`,
`success=false`, `created_count=0`, on every path that previously claimed
success.

## MEASURED 2026-09-30 — step 1: which statement owns the time

Method: production application logs (`/ecs/vitalgraph-prod`), the `presync`,
`update_subjects_graph:` and `BULK insert:` lines this code already emits. Two
6-hour windows, like for like: **09-26 12:00-18:00Z** (the spike day, n=3,842
writes) and **09-30 10:00-16:00Z** (now, n=2,755). No sampling — every write in
each window.

### The four pre-delete scans

    statement (log label)              med     p95     p99     max   share
    -------------------------------------------------------------------------
    09-26  frame_slot (frame_entity)  0.190   0.436   0.561   1.953   40.5%
           edge                       0.001   0.003   0.007   0.054    0.3%
           entity_slot_sort (stats)   0.269   0.739   0.786   5.468   58.8%
           rdf_quad DELETE            0.001   0.004   0.012   0.201    0.4%
           all four                   0.464   1.216   1.339   7.410

    09-30  frame_slot (frame_entity)  0.195   0.453   0.600   1.158   96.6%
           edge                       0.001   0.002   0.003   0.019    0.5%
           entity_slot_sort (stats)   0.002   0.012   0.032   0.736    2.3%
           rdf_quad DELETE            0.001   0.002   0.007   0.061    0.6%
           all four                   0.199   0.486   0.607   1.319

**`issues/238` IS DEPLOYED, and this is what it bought**: `entity_slot_sort` went
from 0.269 s median to 0.002 s — 134x, and from 58.8% of the scan cost to 2.3%.
It was the dominant statement on the spike day.

**`frame_slot` is now the dominant one at 96.6%** — the prediction that named it
was right, but it is dominant because 238 removed the other, not because it grew:
0.190 s then, 0.195 s now. In absolute terms the whole four-scan block is 0.199 s
median today.

**Two log labels are stale and misleading.** `frame_entity=` times
`sync_frame_slot_before_delete` (the table was renamed, `issues/183`) and
`stats=` times `sync_entity_slot_sort_before_delete`, not the stats tables.
Anyone reading this line to attribute cost is reading the wrong names.

### The whole write, and where the seconds actually were

    update_subjects_graph total   med     p95     p99      max    >2s     >10s
    ---------------------------------------------------------------------------
    09-26                        1.112   4.817   7.886   51.724  29.72%   0.21%
    09-30                        0.273   0.710   1.088   11.226   0.47%   0.07%

    BULK insert (the insert half) med    p95     p99      max
    09-26                        0.414   1.385   2.024    5.443
    09-30                        0.046   0.817   1.222    4.684

So the WORK per write on the spike day was ~0.9 s (0.46 scans + 0.41 insert) and
is ~0.25 s now. **The premise that a frame write should be about a second was
correct.** The 7.52 s in `kg_backend_utils.py:1084` is the TOTAL, not the scans —
this issue read it as "~7.2 s of scans under the lock", and that was wrong.

**The tail is waiting, not working, and the logs locate it exactly.** Take the
7.327 s write at 13:13:05.525: its `presync` line is stamped 13:13:05.114 and
reports 0.47 s of scans, so the scans STARTED at ~05:04.64 — while the write
itself began 7.327 s before it finished, at ~12:58.20. **Six point four seconds
elapsed before the first statement of the write ran.** The four scans are the
first thing after `lock_entities`, so that gap is connection acquisition plus the
entity lock, with no work in it. The next write in the window reproduces it:
6.8 s of gap, 0.48 s of scans.

### The load, confirmed server-side

**138 `POST /kgentities/kgframes` in four minutes, every one to the SAME lead**
(13:12-13:16Z). That is the apply-form autosave as reported, measured from this
side: 34.5 writes/minute to one entity, arriving in bursts — five writes landed
within five seconds inside that window, each taking ~10.3 s while doing ~0.9 s of
work.

Serialised at ~0.9 s a write, one lead sustains ~65/minute, so the MEAN rate is
survivable and the BURSTS are not: a burst above 1/s builds a queue, and the
queue is what the caller sees. At today's ~0.25 s it takes a much bigger burst to
build anything, which is visible in the numbers — writes over 2 s went from
29.72% to 0.47%, and over 30 s from one to none.

### ~~`lock_timeout` IS ZERO ON PRODUCTION~~ — WRONG INSTANCE, see the retraction at the top

Read directly from the production instance as the app's own role:

    lock_timeout      = 0       (source: default)   -- i.e. WAIT FOREVER
    statement_timeout = 60000   (configuration file)

No `pg_db_role_setting` override for the app role or database, and the only place
the code sets `lock_timeout` is `bounded_lock_wait`, which saves and restores it
around specific reads. So:

**1. `issues/231`'s "lock_timeout 10s" does not hold for the app's write
sessions.** Every conclusion in this file that used a 10 s cap on a lock wait was
wrong, including "a 9 s wait plus a 22.8 s service time is 31.8 s". The real cap
on ONE wait is `statement_timeout` = 60 s, because the wait happens inside
`SELECT pg_advisory_xact_lock($1)` — which is exactly why a 51.7 s write is
possible and why the multi-key case is `N x 60 s`, not `N x 10 s`.

**2. It falsifies the justification for leaving the single-key path alone** in
part 2 of "What is fixed". That decision rested on "one wait is already bounded by
the session's own `lock_timeout`". It is not bounded at all. A frame write locks
ONE entity, so the reported case is precisely the case with no bound — see "What
step 1 changes".

**And the reported 286 "writes failed on lock timeouts" cannot be
`lock_timeout`**, because there is none. Over the whole of 09-26 this log contains
zero occurrences of `lock timeout`, zero of `update_subjects_graph failed`, and
zero of `deadline exceeded`. Whatever those 286 are, they are not this, and the
claim needs its own evidence before anything is built on it.

### One more consequence, and it is good news

**No write failed on the spike day.** Zero `update_subjects_graph failed` lines in
24 hours, and the 51.7 s write logged its own completion. So those writes LANDED,
late, exactly as "the server does not stop when the caller gives up" predicts.
The uncertain writes in this report are overwhelmingly writes that SUCCEEDED
after the caller stopped listening — which is what the frame comparison should
expect to find.

### What step 1 changes

**The urgent item is no longer the scans.** 238's deployment already took the
median write from 1.112 s to 0.273 s and the >2 s share from 29.72% to 0.47%. The
contention condition has largely dissolved on its own.

**The urgent item was that nothing bounds a lock wait** — `lock_timeout = 0`, so
a single-entity write could wait to the 60 s statement cap, which is what produced
the 30 s caller timeouts. DONE, part 5: set once per connection on the REQUEST
pool, which costs nothing per write.

**And `frame_slot`'s subquery arm** — 96.6% of the scan cost, though only 0.195 s
of it. DONE, part 6: 384x measured, Seq Scan to Bitmap, equivalence checked on
five input shapes.

Neither is deployed. The order to verify them in production is part 5 first (it
changes what a contended write DOES — fails at 10 s instead of hanging), then
part 6 (it changes what a write COSTS, and should show up as the four-scan block
dropping from 0.199 s to near zero in the same `presync` line this was measured
from).

## MEASURED 2026-09-30 (evening) — the 5 failed writes, and they are REAL losses

Reported: 5 writes did not stick, read-back showed them unchanged, "most likely
rejected by the per-entity write lock as busy", and a retry with the same cutoff
expired all 5.

**The server logged all five, and it was not a rejection.** Nothing rejects a
write on the deployed code — `lock_timeout` is 0 there, so a contended write
WAITS. What the log says, five times on 09-30 (18:19:06, 21:32:03, 21:34:28,
21:39:26, 21:43:38 UTC):

    update_subjects_graph failed: cannot call Transaction.__aexit__():
    the underlying connection is closed

with the write's own duration beside it:

    18:19:06   FRAME_CREATE step2   122.039s  (21 subjects, 146 quads)
    21:32:03   FRAME_UPDATE step2   190.847s  (15 subjects, 106 quads)
    21:43:38   FRAME_UPDATE step2   154.025s  (15 subjects, 106 quads)

12 occurrences over 7 days, of which these 5 are one day — so a low-rate failure
that clustered. The 21:32-21:43 group of four inside eleven minutes is the
reported retry batch.

**These are CONFIRMED LOSSES, and that is the difference from everything above.**
The connection died under an open transaction, so it never committed and nothing
was written. The earlier population — the 30 s caller timeouts — were writes that
LANDED late; these did not land at all, which is exactly why the read-back shows
the leads unchanged. They stay lost until the applicant saves that page again.

**None of them reached its first statement.** There is no `presync` line for any
of the three above — that line is emitted after the four scans complete — so the
122-191 s was spent before any work began, in connection acquisition and the
entity lock wait. Neighbouring writes in the same seconds completed in
0.27-0.42 s, so the box was healthy and these specific requests were blocked.

**~~PostgreSQL did not close those connections~~ — IT DID.** This paragraph read
the wrong instance's log (see the retraction). The real instance logs `FATAL:
terminating connection due to idle-in-transaction timeout` once per failure, 5
for 5. The chain below is kept only because it was the reasoning at the time:

    unbounded lock wait  ->  something client-side kills the connection
                         ->  transaction never commits, write is lost
                         ->  the error reports the SYMPTOM, not the cause

**WHICH client-side thing is NOT established, and the durations argue against the
obvious answer.** asyncpg's `command_timeout = 60` on the REQUEST pool is the
leading candidate, but 122 / 154 / 191 s do not divide cleanly by a 60 s fence,
and the pool's `acquire_timeout` is 15 s (read from the production log), so
waiting for a connection cannot account for the remainder either. A dead socket
noticed only at rollback would fit the durations better than a timer that fired
on schedule. Candidates, none confirmed: the 60 s command timeout with its
callback delayed by a starved event loop (GC pauses are logged in the same
windows); a TCP connection dropped in between and discovered late; something
else.

**The logging added for this will answer it on the next occurrence** — the masked
cause names itself (`TimeoutError` for the fence, `ConnectionDoesNotExistError`
or a reset for a dead socket), which is the whole reason it was worth adding
before deploying anything.

**This is what part 5 fixes, and it is the argument for deploying it.** With
`lock_timeout = 10 s` on the request pool the wait ends at 10 s with a clean
55P03 on a LIVE connection: the transaction rolls back cleanly, `EntityLockTimeout`
names the lead, and the caller gets a `STORE_FAILED` it can act on — instead of a
two-to-three-minute hang ending in an InterfaceError that names nothing.

### Two findings worth their own fixes

**1. The cause is masked — FIXED 2026-09-30, and it is why the mechanism above is
still a candidate list rather than a conclusion.** When the body
of `async with conn.transaction()` raises and `__aexit__` also raises, Python
REPLACES the body's exception — so `update_subjects_graph`'s `except Exception as e`
logs the transaction-exit `InterfaceError` and discards the real one, which is
still sitting in `e.__context__`. Logging `__context__` alongside would have said
`asyncio.TimeoutError` (or whatever it really was) immediately. Note the related
trap already recorded in `sparql_sql_db_impl.py`: a `command_timeout` raises
`asyncio.TimeoutError`, **whose `str()` is empty** — so even unmasked it needs
`repr()` or the type name to be legible. `utils/exception_detail.describe_exception`
now handles both — it walks `__cause__`/`__context__`, labels a deliberate `raise
... from` differently from an accident of nesting, honours
`__suppress_context__`, caps the chain, survives a cyclic one, and prints the
TYPE when `str()` is empty. Wired into the five swallowing write paths in
`kg_backend_utils`, with a guard test per path.

**2. `command_timeout` outliving the fence it should follow.** A 60 s client-side
fence on a statement whose server-side wait is unbounded means the CLIENT always
wins, and the client's way of winning destroys the connection and the transaction
with it. The two fences want ordering: a lock wait bounded BELOW the command
timeout, so the failure is a clean server-side error rather than a killed
connection. Part 5 (10 s) establishes that ordering; this is the reason it is not
merely a latency improvement.

## ROOT CAUSE FOUND 2026-10-01 — a write holds its transaction open across an ANALYZE

**`add_rdf_quads_batch_bulk` awaits `maybe_analyze` inside the CALLER's
transaction**, and on production that ANALYZE runs for one to three minutes.

    # sparql_sql_space_impl.py:1686-1693
    # Track row changes for auto-ANALYZE (outside transaction)
    from .auto_analyze import record_changes, maybe_analyze
    record_changes(space_id, count)
    self._invalidate_counts_for_quads(space_id, quads)
    async with self._db._internal_pool.acquire() as conn:
        await maybe_analyze(conn, space_id, pg_config=self.postgresql_config)

**The comment is true only for one of the two branches.** When this function opens
its own transaction, the block really is outside it. When a caller passes
`connection=conn` — which `update_subjects_graph` always does, and six other call
sites in `kg_backend_utils` do — the CALLER's write transaction is still open
around all of it. `maybe_analyze` then does
`await asyncio.to_thread(_sync_analyze, tables, pg_config)`, ANALYZEing every
per-space table on a separate connection while the write's own session sits IDLE
IN TRANSACTION.

**The database log, matched 4 for 4.** Every idle-in-transaction FATAL falls
inside an ANALYZE window, and each application failure lands ONE TO TWO SECONDS
after that ANALYZE sequence finishes — the write resumes the instant the ANALYZE
returns and finds its connection already terminated:

    ANALYZE sequence (a different session)                FATAL      app failure
    rdf_quad 90.4s -> term 98.0s   21:28:52-21:32:01      21:29:53   21:32:03
    rdf_quad 60.2s -> term 83.5s   21:32:02-21:34:27      21:33:03   21:34:28
    rdf_quad 46.5s -> term 86.7s   21:37:10-21:39:24      21:38:11   21:39:26
    rdf_quad 68.1s -> term 81.5s   21:41:04-21:43:37      21:42:05   21:43:38

Sequence durations of 189 s / 145 s / 134 s / 153 s against reported write totals
of 122 s / 154 s / 191 s. The rarity matches too: `maybe_analyze`'s threshold is
**50,000 row changes** and it skips when another holds its advisory lock, so only
an occasional write pays it — about five a day.

**Earlier shape breakdowns of this log MISSED these statements**, because the
regex required `execute` (the extended protocol) and ANALYZE arrives as a simple
statement. That is why an earlier pass concluded "no ANALYZE in the hour"; there
were twenty, the longest 98 s.

**And it partly vindicates this issue's FIRST hypothesis**, which was demoted for
good reason at the time. "The post-write ANALYZE is the stall" was the right
suspect and the wrong mechanism: not *the write waits for an ANALYZE so it is
slow*, but *the write holds a transaction open across the ANALYZE, so PostgreSQL
kills the transaction*. Demoting it on the evidence then available was correct;
the evidence that settles it is the ANALYZE durations in the database log, which
nothing had looked at.

### FIXED 2026-10-01 — scheduled, never awaited

`auto_analyze.schedule_maybe_analyze` replaces the inline acquire-and-await at
**all three sites** — `add_rdf_quads_batch_bulk`, `remove_rdf_quads_batch_bulk`
and `delete_entity_graph_bulk`, two of which take a caller's connection and so
had the hazard inside someone else's transaction. `record_changes` and the count
invalidation are in-memory and stay where they are.

Fire-and-forget rather than merely "skip it when the caller owns the
transaction": a request should not wait one to three minutes for deferrable
maintenance even on the path that owns its transaction, and `maybe_analyze`
already takes a non-blocking advisory lock, so a duplicate schedule is harmless.
The pattern — a per-space in-flight registry holding a strong reference, plus a
done-callback that discards it and logs — is `vectorization.auto_sync`'s, reused
rather than reinvented.

**The threshold is now checked BEFORE anything is acquired.** `maybe_analyze`
tests it only after being handed a connection, so the old shape paid an
internal-pool acquisition on EVERY write to discover there was nothing to do — at
a 50,000-row threshold, nearly every write. A test asserts an ordinary write
acquires nothing at all.

Tests: `tests/unit/test_a_write_never_waits_for_an_analyze.py` — the caller
returns before the ANALYZE begins, the task is strongly referenced until it
finishes, a failing ANALYZE is logged and never raised at the caller, no event
loop is not an error, and an AST guard over the three sites. Reverting one site to
the awaited form fails that guard.

**One pre-existing test had to be retargeted, not weakened.**
`test_the_analyze_sites_in_the_write_path_are_routed` (from `issues/231`) pinned
the three sites as the two-line text `_internal_pool.acquire() … await
maybe_analyze(`. That code is gone, so the test now asserts the same requirement
where it now lives: three `schedule_maybe_analyze` sites, the scheduler choosing
its pool through `internal_pool_for`, and `auto_analyze` never reaching for
`connection_pool` directly.

**What this does NOT need:** the phase timestamps would have shown this as
`insert=` absorbing the whole duration with `commit=-`; they are still worth
having for the next unknown, but the cause is established without them.

## What the database log shows, and what it eliminates (2026-10-01)

Configuration bounds what it CAN show: `log_min_duration_statement = 1000`,
`log_lock_waits = off`, `log_disconnections = off`, `log_statement = none`,
`log_min_messages = warning`. So: statements over 1 s, FATAL/ERROR/WARNING,
checkpoints, autovacuum. Nothing sub-second, no lock waits, no session lifetimes.

Contents of 21:00-21:59 UTC on 2026-09-30 — 354 LOG, 4 FATAL, 1 ERROR:

  * **4 FATAL `terminating connection due to idle-in-transaction timeout`** at
    21:29, 21:33, 21:38 and 21:42, each 75-93 s before an application-side
    failure. With 18:18:05 that is **5 for 5**.
  * **1 ERROR**, `canceling statement due to statement timeout`, on a
    `WITH targets AS (…)` statement — a maintenance query, not a write.
  * 252 slow statements: `INSERT INTO {space}_term` at **5141 / 2427 / 2300 /
    2022 ms** (the slowest write statement in the hour, and nothing in this issue
    touches it); `DELETE FROM {space}_frame_slot` **eight times at 1.0-1.2 s**,
    which is the statement part 6 makes 384x faster, so production is paying it;
    one `DELETE FROM lead_prod_entity_slot_sort` at 1217 ms; 54 slow
    `SELECT count…`.
  * 75 `could not receive data from client: Connection reset by peer`, all on
    this database, spread across the whole hour at 1-6/min — consistent with pool
    recycling rather than a pathology.
  * 12 checkpoints, 2 autovacuums, 1 autoanalyze.

**THE DECISIVE DETAIL: three of the four killed sessions appear in the log ONLY
as a FATAL.** No slow statement at all. So nothing slow was happening in the
database on those connections — every statement they ran was under a second, and
then the application stopped talking to them with a transaction open. **The
database log eliminates the database as the location of the delay.**

### A suspicion raised and withdrawn

One session (pid 2100892) ran a `frame_slot` DELETE and then a generated
`SELECT p0.v0 …`, which looked like a READ executing inside a write transaction —
a real possibility, since `execute_sparql_query` accepts a caller's `conn` by
design (`issues/175` class 2). **Tested and false.** Of 29 sessions with slow
statements, 3 ran both a slow write and a slow read, and the gaps are **26 s, 2
minutes and 24 minutes** — a pooled connection reused across requests, not a
shared transaction.

### What is now eliminated, and what remains

    lock wait            NO -- lock_timeout is 10 s
    sidecar compile      NO -- sidecar=0 ms in every pipeline line in the window
    SQL generation       NO -- peaked at 283 ms
    event-loop starvation NO -- busy task streams gap at most 2 s, not 60 s
    a read inside the write transaction  NO -- see above
    anything in the database  NO -- three of four killed sessions ran nothing slow

What remains is an application-side await inside the transaction that is not a
database statement — a semaphore, the thread pool, or another coroutine. **The
phase timestamps added 2026-10-01 are what will name it**: they are logged on the
FAILURE path as well as the success path, because every one of these losses ends
in an exception, and a phase that never completed prints `-`. A write parked with
its transaction open will read as
`phases acquire=… begin=… lock=… presync=- insert=- commit=-`.

Instrumented: `update_subjects_graph`, where all five losses occurred.
NOT instrumented: `upsert_objects_atomic` and `update_entity_graph`, deliberately,
to keep the change small — if a loss ever appears there it will need the same
treatment.

## The report, as received

`POST /api/graphs/kgentities/kgframes` writes KG frames onto a lead entity in the
`lead_prod` space. Occasionally VitalGraph does not answer within the caller's
30 s read timeout. The calls either side of each failure took 0.46–0.58 s against
a ~0.5 s norm, so single requests stall while the service as a whole is fine. The
client does not retry a timed-out POST, so each failure is an UNCERTAIN WRITE:
the frames were either never written or written without the caller knowing, and
nothing records which.

Two separate failure populations, which should not be conflated:

    237  VitalGraph call failures in 7 days, all from the API service,
         almost all 30 s READ TIMEOUTS
           145  frame writes      \  ~190 uncertain writes
            45  entity creates    /
            24  entity reads
            15  queries
             8  other
         7-38/day except 131 on 09-26. Only 4 near a deploy.

    286  writes reported by the caller as failing on LOCK TIMEOUTS in the same
         week, across ALL callers and not just this API. **This attribution does
         not survive measurement: production's `lock_timeout` is 0, and
         VitalGraph's log contains zero lock timeouts on the spike day.** See
         "MEASURED 2026-09-30".

Entity creates since 09-28 often take **110–160 s**.

**The cause is not general VitalGraph slowness: it is lock contention on busy
lead entities, and the same few leads get dozens of frame writes a minute.**

## Where the writes come from — CORRECTED 2026-09-29

The earlier attribution ("~128 of 149 from the API's own Salesforce -> KG lead
sync") was WRONG, and the way it was wrong is worth keeping, because the same
trap will catch the next investigation.

**Every failed write is forwarded from another service** through the API's
`/api/kgentities`. None originates inside it. What made them look internal was a
change on the CALLER's side: a commit on 09-25 moved their per-request audit log
lines to DEBUG, so from that evening on their logs name no caller at all, and
"no caller recorded" was read as "no external caller".

Before that change, all 31 failures have one:

    22  the portal backend, writing leads in `lead_prod`
     9  the underwriter-role key, writing nurture entities in `prod_kg`

After it, VitalGraph's own access log still gives the SPACE for 37 of them, and
**36 are `lead_prod`** — which is how the spike below was attributed.

**A caller-side logging change made a caller-side cause look like a server-side
one.** Note the same class of defect on this side, fixed the day before this
report: `issues/247`, where every successful request was logged as "client
disconnected" and a search of those logs produced a confident, wrong answer about
21,527 abandoned requests.

## The 09-26 spike was portal lead writes — CORRECTED

An earlier draft said it "probably already has an answer": the 6,810-entity bulk
delete that `issues/231` measured that same day, reading 606 MB of buffers per
delete. That was inference from a date coincidence, and the caller-side evidence
supersedes it — 36 of 37 space-attributed failures are `lead_prod`, i.e. portal
lead writes. The bulk delete may still have contributed IO pressure; nothing
shows it caused these.

Two date coincidences, two wrong causes, in one file. What settled each was
evidence naming the actual request.

## The reporter's three follow-ups, now answered

Their findings, in their tracker's issue 044 §5-§7 (not this repo's 044 — see the
status block).

### 1. Does the caller notice? NO, and it is measured

  * the portal's apply route calls its `updateLead` WITHOUT AWAITING it, and
    `updateLead` sends each frame write and never reads the response;
  * the portal's client library throws only on a non-2xx status;
  * the API reports a failed or timed-out write as **HTTP 200 with
    `success:false`**.

Over 7 days the portal logged **42,343 successful `updateLead` calls and 1
error**. Nothing retries and nothing reconciles. A lost write is repaired only if
the applicant saves that same page again — **so the last save of a page stays
lost.**

Separately: **9,010 updates skipped as "entity not found" against 4,163 lead
creates**, consistent with updates racing ahead of the create because neither
waits for the other. Not investigated further, and not this issue's mechanism —
but the server already has the answer for it: `operation_mode=upsert` exists on
both write endpoints (`kgentities_endpoint.py:251,433`, default `create`), and an
upsert that arrives before the create creates the entity instead of skipping. A
race that cannot be ordered is cheaper to make order-independent than to order.

**This is where VitalGraph's own convention meets a status-only client.** This
codebase deliberately returns HTTP 200 for domain outcomes and puts the result in
the body; the API mirrors that; the portal's library reads only the status. Each
piece is defensible and the composition loses writes silently. See "The decision
this now turns on".

### 2. Why the lock contention: the apply form's autosave

  * one lead took **40 saves in 4.5 minutes**, often a second apart;
  * each save reads the lead's whole graph, merges in the new values, and writes
    the frames back;
  * they overlap on the same frames of the same lead and queue on the per-entity
    lock — some hitting the 10 s `lock_timeout` (the 286), some waiting past the
    caller's 30 s (the timeouts).

**And the finding that is not about failure at all: a slower, older save can
overwrite a newer one even when nothing times out.** That is a LOST UPDATE, and
no amount of locking inside VitalGraph can prevent it — the entity lock makes one
write atomic, while the race spans the caller's read, its merge, and its write,
which are three separate requests. Preventing it needs either a conditional write
or a server-side merge; see "The decision this now turns on".

### 3. Logging the entity ID

A one-line change on the caller's side, in a file of theirs
(`kg/kg_entities_impl.py`, which is not in this repository) — not done yet.
VitalGraph's half IS done: see part 3 of "What is fixed".

## The mechanism, and two of its numbers were already measured

Frame writes for an entity serialise on that entity. `kgentity_frame_create_impl.py:934-936`
passes `lock_uris=[entity_uri]`, and `update_subjects_graph`
(`kg_impl/kg_backend_utils.py:1078-1080`) takes `pg_advisory_xact_lock` on it
inside the transaction that does the work. That is correct and deliberate
(`issues/173`, `issues/174`): entity upsert and entity-graph delete hold the same
key, so a frame write must take it to be excluded from them.

The cost is how long the lock is held, and the code already carries the
production measurement, in the comment at `kg_backend_utils.py:1084-1092`:

    `FRAME_CREATE step2` is 7.52 s MEAN / 22.8 s MAX on production for
    FOURTEEN subjects, of which the insert is ~0.3 s

An earlier reading of this — that ~7.2 s of a 7.5 s write is the four
auxiliary-table scans that run before the delete — was WRONG, and the 09-30
measurement replaces it: the four scans were 0.46 s median on the spike day and
0.199 s now. The paragraph is kept because the scans are still where the
*remaining* work is; the 7.52 s figure is a TOTAL that is mostly wait. What
follows describes the scans — `sync_frame_slot_before_delete`, `sync_edge_table_before_delete`,
`sync_entity_slot_sort_before_delete`, and the two prop-sort recomputes after it.
The entity lock is held across all of it.

That turns the reported arrival rate into a saturated queue by arithmetic:

    service time under the lock   ~0.9 s  (09-26, measured; ~0.25 s now)
    capacity for one lead         ~65 writes/minute
    measured arrival rate         138 writes in 4 minutes to ONE lead,
                                  in bursts above 1/second

    (An earlier draft read the 7.52 s figure as scan time and derived a capacity
    of 8/minute from it. Both were wrong: 7.52 s is the total INCLUDING the wait.)

**SUPERSEDED by the 09-30 measurement**, kept because the shape of the reasoning
was right and its inputs were wrong. The service time is ~0.9 s, not 7.5 s; there
is no 10 s cap on a wait; and what crosses the caller's 30 s is a QUEUE — measured
at 6.4 s of waiting before the first statement of a write, on a lead taking 138
writes in four minutes. Nothing about this
requires VitalGraph to be generally slow, which is what the neighbouring 0.46–0.58 s
calls are telling us.

Note the 7.52 s / 22.8 s figures may predate `issues/238` (the `entity_slot_sort`
delete that scanned the whole table, 1,496x, fixed in the repo 2026-09-27 as
`f5324f29`). Whether that is DEPLOYED is the first thing to check, because it is
one of the four scans being timed. Which of the four owns the time is already
answerable without new instrumentation — `update_subjects_graph` logs
`⏱️ update_subjects_graph presync: frame_entity=… edge=… stats=… delete=…` per
write, individually, and the comment above it says why it was split out.

### Why a request can wait far longer than one statement's worth

`lock_timeout` is per STATEMENT, and `lock_entities` (`entity_lock.py:61-63`)
issues **one statement per key**:

    for key in keys:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", key)

So a write covering N entities can wait N x the per-statement cap before any work
starts, and nothing bounds the request as a whole (`request_bounds.py` bounds
reads only). With `lock_timeout = 0` on production that cap is
`statement_timeout` = 60 s, so the multiplier is 60 s and not the 10 s an earlier
draft assumed. That is a candidate — UNVERIFIED — for
the 110–160 s entity creates, and it is falsifiable by counting how many keys
those requests lock. `issues/044` gap 1 made this general point already: one
request runs several statements, each getting its own independent budget, so a
request can take an arbitrary multiple of any single fence.

### The neighbouring measurement that is NOT the 09-26 spike

Kept because it was this file's second wrong cause and because the numbers are
real and worth having. `issues/231` closed a stall investigation on 2026-09-26 —
the same day as the spike — with a measurement: a bulk entity delete of 6,810
entities, 89.7 minutes at 0.9 entities/s, `issues/238`'s pre-fix shape reading
**606 MB of buffers per single entity delete** (~4 TB over the run) and evicting
`shared_buffers` so unrelated reads went to disk, with irregular stalls at
**26 s, 47 s, 10 s, 34 s** and `pool_wait` at 0 — IO, not connection starvation.

The profile matches the spike's shape, the date matched exactly, and it is still
not the cause: 36 of the 37 space-attributed failures are `lead_prod` portal lead
writes. A matching shape on a matching day is a hypothesis, not an attribution.
The bulk delete does hold the per-entity lock, so on any lead it touched it would
have made the queueing worse — a contributor at most.

## Why the write cannot be retried, and it is one line

`retry.py` classifies `httpx.ReadTimeout` as POST_SEND (line 59), POST is not in
`IDEMPOTENT_METHODS` (line 44), so `vitalgraph_client.py:840` raises
"non-idempotent request may already have been processed; not retrying" and
increments `retry_stats.non_retryable_writes`. The report matches the code,
including that a counter for this already exists.

But the write is *almost* idempotent. Terms are content-addressed
(`_generate_term_uuid` over text/type/lang/datatype), the quad key is
`(subject_uuid, predicate_uuid, object_uuid, context_uuid)`, and every insert on
it is `ON CONFLICT DO NOTHING`; on this path the subjects are also deleted before
being re-inserted. Replaying the identical payload should change nothing. The
exception is the one URI the SERVER mints per call:

    vitalgraph/kg_impl/kgentity_frame_create_impl.py:435
        edge_uri = f"http://edge/entity_frame_edge_{uuid.uuid4()}"

A replay therefore attaches the same frame to the same entity a SECOND time via a
second `Edge_hasEntityKGFrame`, and nothing else differs. Three siblings do the
same on adjacent paths, and the entity-create path is 45 of the failures:

    kg_impl/kgentity_create_impl.py:430          Edge_hasEntityKGFrame
    kg_impl/kgslot_create_impl.py:282            Edge_hasKGSlot
    kg/kgentity_create_endpoint_impl.py:149      Edge_hasKGFrame

The deterministic convention already exists in this codebase, on the
standalone-frame path — `kgframes_endpoint.py:3033-3042`, `f"{frame_uri}_entity_edge"`.
So this is a convention applied inconsistently, not a design.

**One unverified fact gates any retry.** `bulk_load.py:69-71` still asserts that
the quad `ON CONFLICT` is a no-op because `quad_uuid` is in the PK. That WAS
true, which is why `scripts/migrate_quad_pk_dedup.py` exists and found 1,323
duplicate quads across 6 spaces. `sparql_sql_schema.py:997-1007` now declares the
slim 4-column key, so new spaces are fine — but whether `lead_prod` was migrated
is unchecked, and if it was not, a replay duplicates every quad in the payload
rather than nothing. The migration script reports the PK columns under
`--dry-run`. Check this before enabling any retry.

## What the code says about the caller not knowing

**The server does not stop working when the client gives up, deliberately.**
`RequestBoundsMiddleware` bounds reads only, and says why: cancelling a write
mid-transaction would have PostgreSQL roll it back, "turning a network hiccup
into silent data loss that the client cannot detect, because it is by definition
no longer listening." For this POST there is no request deadline
(`VITALGRAPH_REQUEST_DEADLINE_S` is for cancellable reads), no cancellation on
disconnect, and only `_progress_bounded`, which deliberately does not watch the
commit phase. Every server-side fence (60 s statement, 10 s lock, 120 s read
deadline) sits ABOVE the caller's 30 s, so the only timeout that fires is the one
on the side that cannot determine the outcome. **For a 30 s timeout the likely
answer is that the write landed, seconds after nobody was listening** — which is
why "uncertain" is the accurate word and "lost" is not yet earned.

**A lock timeout is swallowed into a boolean, which is why step 2 cannot be done
where it belongs.** `update_subjects_graph` wraps everything in
`except Exception: self.logger.error(...); return False`
(`kg_backend_utils.py:1150-1152`). So `canceling statement due to lock timeout`
becomes `False`, carrying no entity URI, no lock key and no wait duration. On the
reported path the caller does check it — `kgentity_frame_create_impl.py:951-956`
turns `False` into a failure — so the API service does learn the write failed,
but nothing anywhere can say WHICH LEAD it was about. That is precisely the
reporter's step 2, and the fix belongs at this layer, not theirs.

**Five sibling call sites are worse: they take no lock AND discard the result.**
Found while tracing the above, and adjacent to the reported path rather than on
it:

    endpoint/kgframes_endpoint.py:2728    _store_frames_in_backend
    endpoint/kgframes_endpoint.py:3412    _update_frame_slots_in_backend
    endpoint/kgframes_endpoint.py:3527    _store_frame_slots_in_backend
    endpoint/kgrelations_endpoint.py:644  _update_relations_in_space
    endpoint/kgrelations_endpoint.py:702  _upsert_relations_in_space

All five call `update_subjects_graph` positionally with no `lock_uris`, so they
take no entity lock at all, and all five ignore the boolean and return the URIs
they INTENDED to write. `_store_frames_in_backend` is the shared body for the
standalone-frame store, update and upsert paths, so a lock timeout or any other
database failure there is reported to the caller as frames created. That is
`issues/242`'s shape ("a failed frame delete reports success in four fields") and
`issues/245`'s ("logs the URIs it SUBMITTED, not what was stored") for a third
time, and it is a missing-lock instance for `issues/174`.

## A hypothesis this issue got wrong first

The first draft led with the post-write `ANALYZE` of six auxiliary tables that
`store_objects` awaits (`kg_backend_utils.py:290`, at most once per
`ANALYZE_MIN_INTERVAL` = 900 s). It fit the isolated-stall shape and the
write-only concentration, and it is real work on the request path that should
move off it. But it is NOT the reported cause: the caller-side evidence says lock
contention on specific entities, and the lock mechanism above is measured while
the `ANALYZE` one is not. It also cannot explain a per-lead concentration, since
the guard is per space.

`issues/231` made the identical mistake on 2026-09-24 and recorded it on purpose:
"keeps the wrong ANALYZE explanation on the record: it was plausible, it fit the
timing, and it was believed for hours. What killed it was checking the lock modes
rather than the narrative." Same story, so it is kept here the same way.

## The decision this now turns on: what status a refused write returns

Everything above is settled enough to act on except one thing, and it is a
CONTRACT decision rather than a bug, so it is written down rather than changed.

**The facts that make it the pivot.** The write is now idempotent (part 1 of
"What is fixed"), so replaying it is safe. The client's retry policy already
treats **429 and 503 as `DECLINED`** — "safe to retry regardless of method,
honoring `Retry-After`" (`client/retry.py:13,69`) — which is the ONE class that
retries a POST. And the portal throws only on a non-2xx. So a refused write
returning **503 + `Retry-After`** would, with no further code anywhere:

  * be retried automatically by the VitalGraph client, safely;
  * be visible to a status-only caller, which is every caller in this report;
  * and stop being an "uncertain write", because a declined write did not happen.

**Why this is not a convention violation.** This codebase returns HTTP 200 for
DOMAIN outcomes — validation, not-found, conflict — and reserves non-200 for
server-level failures. A write that could not acquire a lock inside its budget is
not a domain outcome; it is the server declining to do the work, which is what
503 means. The five sites fixed in part 4 already raise, and their handlers
already map that to a 500 — so the inconsistency today is that the MAIN frame
path returns 200 with `STORE_FAILED` while its siblings return 500.

**DECIDED 2026-09-29: keep the 200, callers read the body.** The 503 case was
put and declined. It changes the status code every caller of the write endpoints
sees, and a caller that currently ignores `success:false` would start seeing
exceptions; the contract stays as documented, and reading the body is the
caller's job. Consequences, recorded so nobody re-litigates them by accident:

  * the portal's silent loss is fixed on the PORTAL side, by reading
    `success`/`status`, not here;
  * every future status-only client is exposed to the same trap, so this is a
    thing to say out loud in the API docs rather than a thing that cannot happen;
  * the VitalGraph client will NOT retry a refused write on its own — a 200 is
    not a `DECLINED` — so idempotency (part 1) buys safety for a retry that
    someone still has to ask for, via `idempotent=True`;
  * part 4 of the fix was reworked to honour this: `STORE_FAILED` in a 200, not
    the 500 its first version produced.

### The lost update: WRITTEN UP, NOT BUILT (decided 2026-09-29)

**Locking cannot answer it.** A slower save overwriting a newer one is not a
failure of the entity lock — the lock makes one write atomic, while the race
spans a read, a merge and a write issued as three separate requests. It is a
distinct defect from the timeouts: different cause, different fix, and it loses
data while every request reports success, so it needs no contention to hurt.

Two shapes would fix it, both larger than this issue: a CONDITIONAL write, or a
server-side merge so the read-modify-write never leaves the server. The
conditional write is the smaller, and the data it needs already exists —
`hasObjectModificationDateTime` is stamped on every write
(`kg_server_properties.py:26`). Sketch, for whoever takes it:

    client reads lead            -> body carries hasObjectModificationDateTime
    client writes frames back    -> passes it as `if_unmodified_since`
    server compares before write -> equal: proceed, and re-stamp
                                    moved: refuse, nothing written
    client re-reads and re-merges

So the cost is a new parameter on the write endpoints and a caller willing to
handle a refusal. **That last part is load-bearing**: under the decision above, a
refusal is a `CONFLICT` in a 200 body, and an unread 409 is worth exactly as much
as an unread 200. Building the server half alone would add API surface and change
nothing that happens.

## What needs to change in the client

Nothing here is built. Read the replay-safety table FIRST: it is not uniform
across the write paths, and the reason it is not uniform is not obvious from
part 1 of the fix.

### What is already right — do not "fix" it

**The client's verdict on a failed write is correct today.** All 19 write methods
in `client/endpoint/kgentities_endpoint.py` and `client/endpoint/kgframes_endpoint.py`
pass the server's domain `status` through, and `is_success` treats it as
authoritative — "an HTTP 200 with status=already_exists is NOT a success"
(`client/response/client_response.py:55-64`). So a `STORE_FAILED` frame write
gives `is_success == False` and `raise_for_error()` raises. The silent loss in
this report is NOT in this client; it is in a caller that reads the HTTP status
instead of the body.

### 1. Carry the server's message instead of a composed one

`build_success_response` sets `error_code=0` and `error_message=None`
unconditionally, and the call sites pass a message they compose themselves — so a
refused frame write surfaces as

    Error store_failed: Created 0 frames

and the server's actual explanation (which now names the lead and the lock key in
the log, and the subject count in the body) is dropped on the floor.

`build_response_from_server` already exists for exactly this and says so in its
docstring: it reads `status`, `success` and `message` from the body and derives
`error_code`/`error_message` "so is_success / raise_for_error reflect the DOMAIN
outcome rather than the HTTP code (which is 200 for every domain outcome)".
**19 of 19 write methods use `build_success_response`; none uses it.** Switching
the write methods over is the change, and it is mechanical.

### 2. Pass `idempotent=True` on the writes that are now replay-safe

This is the payoff for part 1 of the fix and the thing that turns a 30 s
`ReadTimeout` from an uncertain write into a retry. The plumbing exists —
`_make_request(..., idempotent=None)` forwards it to the retry policy, and
`vitalgraph_client.py:753-754` defaults it from the HTTP method — and it is
already used for read-shaped POSTs (`sparql_endpoint.py:41`,
`kgqueries_endpoint.py:108`, `kgframes_endpoint.py:1285`). Its comment there says
"Read-only POSTs opt into post-send retry", which would need to change: a WRITE
can now be replay-safe, which was not true before.

**It only covers transport failures.** Under the 200 decision a refused write is
not a `DECLINED` status, so the client will not retry it — `idempotent=True` buys
the timeout case and nothing else.

**And a retry lands on the contended resource.** The server does not cancel the
first attempt (`request_bounds.py` bounds reads only), so a retry queues behind a
write that may still be running, on the same entity lock. Retrying is correct and
it is also load: keep the attempt count low and let the existing backoff and
`budget` do their work rather than raising them.

### The replay-safety table, which is what gates §2

    write path                     shape                          replay
    ---------------------------------------------------------------------------
    frame create / update          delete-then-insert of the      SAFE
    (update_subjects_graph)        SAME subject set
    entity upsert                  same, under the entity lock    SAFE
    (upsert_objects_atomic)
    entity create                  pure INSERT, no delete —       SAFE but not
    (store_objects)                but guarded by                 TRANSPARENT
                                   batch_check_uris_exist

**Why "safe" is not free, and why part 1 alone does not establish it.** Server
properties are stamped per request from `datetime.now()`
(`kg_impl/kg_server_properties.py`, applied inside `add_rdf_quads_batch_bulk`),
so a replayed PURE insert writes a SECOND `hasObjectModificationDateTime` that no
key can collapse — a single-valued predicate with two values, which is exactly
`issues/173`'s damage (243 entities carrying two to four values, one of them
blanking a listing page). `upsert_objects_atomic`'s own docstring makes the point:
client-supplied properties dedupe on the quad key, and the timestamps do not.

What saves each path is therefore different, and worth knowing before trusting
either: on the frame and upsert paths the DELETE precedes the insert, so the old
stamp goes with it; on the create path the existence guard refuses the replay
outright.

**This also narrows an earlier claim in this file.** "Verify the `lead_prod` quad
PK before enabling any retry" was too broad. On a delete-then-insert path a
replay cannot leave duplicate quads whatever the key is, because the subjects are
deleted first. The PK matters only for a pure-INSERT replay — and on the one such
path the guard refuses it. So the PK is worth checking for its own sake
(`issues/253` found `bulk_load.py:69` still asserting the old key, and
`scripts/migrate_quad_pk_dedup.py` found 1,323 duplicate quads across 6 spaces),
but it does not gate §2.

### 3. A retried create reports a failure for a write that succeeded

`create_kgentities` on a replay returns `ALREADY_EXISTS` — `is_success == False` —
for a create whose first attempt landed. So switching retries on for creates
converts a success into a reported failure, and a caller that reconciles on
`is_success` would then try to repair a lead that is already correct.

Two ways out, and they are a choice: have the retry path treat `ALREADY_EXISTS`
on a RETRIED create as success (the client knows it retried; the caller does
not), or have callers use `operation_mode=upsert`, which is replay-safe and
transparent. The second also fixes the reported create/update race — 9,010
updates skipped as "entity not found" against 4,163 creates — so it is the
better-value change even though it is the caller's.

### Outside this repository, for completeness

**The API service**: mirror the body verdict rather than the HTTP status when
reporting to its own callers; log the entity id on the failure line (their
one-liner in `kg/kg_entities_impl.py`); and stop returning `success:false` through
a path whose callers only check the status code.

**The portal**: await `updateLead` and read `success`/`status` — that is the
change that makes 42,343 "successful" calls honest. Then coalesce the apply
form's autosave (40 saves in 4.5 minutes on one lead is the load nothing
server-side makes cheap), and consider `operation_mode=upsert` per §3.

## What remains, mapped onto the three follow-ups

**Coalescing the autosave** (their step 3's real answer) is the highest-leverage
fix and is theirs: 40 saves in 4.5 minutes on one lead is the load, and no
server-side change makes that shape cheap.

**Bounding the lock wait** is the server's half and is now the top item:
`lock_timeout = 0` on production, so nothing stops a single-entity write waiting
to the 60 s statement cap. Set it once per connection via `db/pool.py`'s existing
`setup=`/`init=` hooks (zero per-write cost), or extend the per-request budget to
the single-key case. **Cutting the remaining scan time** — `frame_slot`, 96.6% of
0.199 s — is worth doing and is no longer urgent; `issues/238` is deployed and
already did the heavy half.

**Verifying the `lead_prod` quad PK**, for its own sake — `bulk_load.py:69` still
asserts the old key and the migration found 1,323 duplicate quads across 6
spaces. It does NOT gate the client retry: see the replay-safety table above,
which corrects that claim.

## What NOT to do

**Do not add a deadline that cancels writes.** `request_bounds.py` refused this
for a stated reason: a rollback the client cannot observe converts an uncertain
write into silent data loss. A write fence must commit-or-report, not cancel.

**Do not raise the client's 30 s timeout.** It changes which writes become
uncertain, not whether any do, and it hides the contention being reported.

**Do not remove or weaken the entity lock.** It is the fix for `issues/173`,
where 243 entities ended up with two to four values for single-valued timestamps
and one such row blanked a whole listing page. The problem is the time spent
holding it, not the holding.

**Do not assume the 30 s failures lost data.** The server runs writes to
completion; comparing a sample of affected leads' frames against what was sent is
what settles it, and counting `Edge_hasEntityKGFrame` per (entity, frame) pair
while doing so is the cheapest available evidence of whether anything was ever
replayed.

## Evidence that already exists, before instrumenting anything

    GET /api/metrics/slow?space_id=lead_prod    per-request duration_ms over
                                                500 ms, endpoint
                                                `kgentities_kgframes`
                                                (metrics_endpoint.py:47)
    ⏱️ FRAME_CREATE step1/step2/total           per frame write
    ⏱️ update_subjects_graph presync: …         which of the four scans owns it
    ⏱️ BULK insert: … / BACKEND store_objects   the insert's own breakdown
    update_subjects_graph failed: …             the swallowed lock timeouts

A `slow_query_log` row at 31,000–60,000 ms beside a reported failure proves the
handler ran to completion; its absence is equally informative.

## Verify after fixing

    a replayed identical frame POST   ->  0 new quads, exactly one
                                          Edge_hasEntityKGFrame per
                                          (entity, frame) pair
    a lock timeout                    ->  error line names the lead URI, the
                                          lock key and the wait
    a failed update_subjects_graph    ->  no caller reports the URIs as written
    one lead, dozens of writes/min    ->  no 10 s lock timeouts and no 30 s
                                          client timeouts at the coalesced rate
    a save the applicant made LAST    ->  is the one stored (the lost update,
                                          and nothing above tests it yet)
