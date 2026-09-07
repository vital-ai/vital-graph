# Remove The Slot-Sort Coverage Marker — Make Completeness An Invariant

## Status: IMPLEMENTED. The gate is inverted, the alarms are in, and the
## upgrade path is written. What remains is running the alarms in production
## long enough to trust the invariant they check.

## THE TARGET, REVISED: INVERT THE REGISTER

The gate does not disappear. It INVERTS. Today `slot_sort_coverage` is an
ALLOW-LIST — a row saying "this type is proven complete", absence meaning
decline. It becomes a BLOCK-LIST — a row saying "this space is known to be at
risk right now", absence meaning SERVE.

A block exists only while one of two things is true:

  1. AN OPERATION IS IN FLIGHT that can make the table disagree with the quads —
     a bulk load, a space import/export, a partition migration. The block is
     taken when the operation starts and released when its derivation finishes.
  2. A PROBLEM IS KNOWN AND A JOB IS FIXING IT — the coverage probe found a
     short type, so a block is recorded and the repair job clears it on
     convergence.

Nothing else blocks. A space nobody is touching and nothing has flagged is
served from the table, because normal writes derive it inline and it is correct.

## Why this is better than either alternative

Against TODAY'S allow-list: absence is the common case, and today absence means
DECLINE. That is the entire defect — nine spaces measured with complete, correct
tables served by the slow path because no row existed. Under a block-list those
nine need no row at all and are served correctly by default.

Against OUTRIGHT REMOVAL: a mechanism still exists for the case that genuinely
needs one. The `issues/149` shape — a type at 1.05% coverage while its drift
probe reported converged — is DETECTED and BLOCKED rather than either ignored
(no gate) or permanently penalised (today).

## THE FAILURE MODE INVERTS TOO, and this is the whole risk

    today       forget to mark COMPLETE   ->  slow, correct
    proposed    forget to mark AT RISK    ->  fast, WRONG

That is not an argument against it; it is the specification for how blocks must
be taken. Three rules follow, and none is optional:

  * A BLOCK IS TAKEN BY THE OPERATION ITSELF, in the same transaction that
    begins the risky work — never by a caller remembering to. If taking the
    block and starting the load can come apart, they will: that is exactly how
    `resync_all` cleared a marker and left it cleared, and how
    `bulk_export.import_space` copied a space in and registered no graphs.
  * A BLOCK SURVIVES A CRASH. It is a row, so a process dying mid-import leaves
    it set. That fails in the correct direction — a stuck block is slow and
    right, and is visible.
  * A BLOCK IS CLEARED ONLY BY A VERIFIED COMPLETION. The job that clears it
    must have just measured coverage, not merely finished running.

## The case that is neither in-flight nor known-broken

A space whose table was created but never populated — a fresh migration, a
space predating the table — is incomplete, is not being worked on, and has
nobody to flag it. Under a block-list it would be SERVED, and wrongly.

So the block is also taken AT TABLE CREATION, and cleared by the first verified
backfill. "No row" then means "nothing has ever put this space at risk", which
is only reachable through a path that verified it — rather than meaning "no one
has looked", which is what absence means today and why this is safe to invert.

## Staging, revised

The inverted gate is SAFER to ship than outright removal and should come first:
it keeps a mechanism for the known-bad case while fixing the common case. The
audit below is still its precondition — a bulk path that takes no block is
exactly the "forget to mark at risk" failure.

  1. Audit the three bypassing modules and their callers (below).
  2. Make each take a block at the start of the operation and release it on
     verified completion. This is where the work is.
  3. Have the coverage probe RECORD A BLOCK on a short type instead of
     withholding an allow-row.
  4. Take a block at table creation.
  5. Flip the read path from allow-list to block-list.
  6. Keep the coverage computation permanently, as the alarm — a block that
     persists past its job, or a shortfall on a space with no block, is the
     signal that this design has a hole.

Step 6 is what makes the inversion self-checking rather than merely optimistic:
a shortfall found on a space with NO block is a bug in step 2, and it is
detectable without waiting for a wrong answer to be noticed.

## The original target, kept for reference

## The target

`{space}_entity_slot_sort` is COMPLETE BY CONSTRUCTION:

  * NORMAL WRITES derive it inline, in the caller's transaction, as they already
    do;
  * EXCEPTION PATHS — bulk load, space copy, migration, a space predating the
    table — are brought to completeness by a JOB, as part of the operation
    rather than eventually;
  * the READ PATH consults nothing. `fast_slot_filter` serves the filter because
    the table is correct, not because a marker says it is.

The marker then disappears from the read path. What remains of it, if anything,
is an ASSERTION maintenance can alarm on — "this should never be short, and it
is" — rather than a gate a query has to pass.

## Why the marker exists today, stated fairly

Not superstition. Three real constraints produced it:

  1. A short table makes a FILTER return a SUBSET that looks like a complete
     answer — plausible count, no error. (A short table only mis-orders a page
     for the SORT path, which is why that path needs no marker.)
  2. Coverage cannot be checked inline: 5,677ms for the table side against 31ms
     for the quad side. Verifying per query costs more than the query.
  3. The table could not be trusted. `issues/149` measured a production type at
     1.05% coverage while its own drift probe reported converged.

The marker is a cached verification standing in for an invariant the system did
not have. The right answer is to have the invariant.

## What is ALREADY true, and it is most of it

Every normal write path derives the table, in the caller's transaction:

    add_rdf_quad                 sync_entity_slot_sort_after_edge_insert
    add_rdf_quads_batch          sync_entity_slot_sort_after_edge_insert
    add_rdf_quads_batch_bulk     sync_entity_slot_sort_after_edge_insert
    execute_sparql_update        sync_entity_slot_sort_after_edge_insert
    (deletes)                    sync_entity_slot_sort_before_delete
    (context drop)               delete_entity_slot_sort_for_context

and the import endpoint already ends in `resync_all_auxiliary_tables`
(`data_import_impl.py:688`, `admin_endpoint.py:74`), which since `af1c717`
rebuilds the table AND records coverage as one operation.

## What is missing

THREE MODULES WRITE QUADS AND NEVER MENTION THE TABLE — zero references each:

    bulk_load.py            COPY-based loader
    bulk_export.py          import_space, copies a whole space in
    partition_migrate.py    partition migration

Whether each is a real hole depends on its CALLERS: a loader whose only caller
finishes with `resync_all_auxiliary_tables` is covered, and one that can be
driven directly is not. `bulk_export.import_space` is the known-bad precedent
here — `graph_registry` records that it copied a whole space in and registered
no graphs, the identical shape of defect one layer over.

## THE AUDIT — DONE

    module                 production callers            derivation runs?
    bulk_load.py           add_rdf_quads_batch_bulk      YES
    bulk_export.py         none (operator/test tool)     NO  -> issues/168
    partition_migrate.py   none (operator/test tool)     n/a, data preserved

BULK_LOAD IS COVERED. Its three entry points are reachable in production only
through `add_rdf_quads_batch_bulk`, and BOTH branches there --
`bulk_load_with_index_rebuild` and `insert_terms_quads_executemany` -- fall
through to the same unconditional `sync_entity_slot_sort_after_edge_insert`,
seeded from the subjects just written. `insert_terms_quads_copy` is internal to
`bulk_load_with_index_rebuild`. Nothing to do.

BULK_EXPORT IS A HOLE, and a live one: `import_space` rebuilds the edge,
frame_entity and stats tables and NOT `entity_slot_sort`, and does not clear the
coverage marker. Restoring over a space that had a complete marker leaves the
fast path serving from rows derived from the PREVIOUS contents. That is a wrong
answer today, independently of this issue -- `issues/168`.

PARTITION_MIGRATE LOOKS FINE, unverified by test. It copies `rdf_quad`, `edge`
and `frame_entity` into new partitioned tables and swaps; it does not touch
`entity_slot_sort`, and it PRESERVES the quads rather than replacing them, so
the existing rows still describe the data. The only change is deduplication
against a slimmer PK, which removes duplicate quads and cannot change which
entities exist. Worth a test before relying on it.

WHAT THE AUDIT CHANGES ABOUT THIS ISSUE: the exception-path work is smaller than
assumed -- one real hole, in a tool with no production caller -- and the block
must be taken by `import_space` specifically. It also raises the priority of
`issues/168`, which must be fixed BEFORE the inversion: under an allow-list that
path is wrong only when a marker happens to be set, and under a block-list it
would be wrong always.

## The job

`scripts/backfill_slot_sort_coverage.py` (from `af1c717`) already drives
`backfill_entity_slot_sort_batch` to completion for a space or all spaces. It is
the deploy-time counterpart to the maintenance job's one-bounded-batch-per-cycle
repair, and reuses the same derivation so the two cannot disagree.

What it needs to become the invariant's guarantor:

  * to be CALLED by the exception paths rather than run by hand;
  * to be idempotent and safe to run concurrently with serving (it is bounded
    per batch, so it already is);
  * to fail LOUDLY when it cannot converge, because after the gate is removed a
    non-converging backfill is a correctness problem rather than a slow one.

## THE RISK, and it is the whole difficulty

Removing the gate changes the failure mode of a short table from SLOW to
SILENTLY WRONG. Today an incomplete table produces a correct answer down the
general path; afterwards it produces a confident subset. `issues/149` is proof
that "the table is complete" has been believed and been false.

So the gate must not be removed on the strength of the invariant being
*designed*. It has to be removed on evidence that the invariant HOLDS:

  1. Close the exception paths (audit above).
  2. Keep the gate, and add an ASSERTION: maintenance already computes coverage
     per type — alarm when any type is short on a space whose writes should have
     kept it complete. Run that in production for a meaningful period.
  3. Remove the read-path gate only once that alarm has been quiet across bulk
     loads, imports, migrations and ordinary traffic. The alarm stays.

Step 2 is what makes step 3 an evidence-based decision rather than a hopeful
one. It also has independent value: it detects the `issues/149` shape, which the
current design merely tolerates by being slow.

## What this buys

The marker has produced four distinct silent-failure modes, all fixed in
`af1c717` and none of them data problems:

    cleared by resync and not restored          fast path off until some job runs
    never set for a maintenance-exempt space    fast path off permanently
    declined with no log                        cliff visible only as latency
    converges one batch per cycle               deploy runs for unknown cycles

Measured on the test database while fixing them: `--record-only` turned the fast
path ON for NINE spaces with `rows_added: 0`. Nine spaces had complete, correct
tables and were being served by the slow path for want of a row in a marker
table. That ratio — nine lifecycle failures to zero data failures — is the
argument for removing it.

## Exit criteria

  * every quad-writing path either derives inline or TAKES A BLOCK and releases
    it on verified completion, listed explicitly with its callers;
  * a block is taken at table creation and cleared by the first verified
    backfill, so "no row" can only mean "verified, or never at risk";
  * the coverage probe records a BLOCK on a short type rather than withholding
    an allow-row;
  * `fast_slot_filter` consults the block-list, and serves when there is no row;
  * the coverage computation KEPT permanently as the alarm, reporting two
    distinct bugs: a block outliving its job, and a shortfall on a space with no
    block.

## What "done" is NOT

Not "the marker was deleted". The read path must still be able to refuse, and
the difference is only which way absence reads. Deleting the mechanism outright
would leave the `issues/149` shape — a genuinely short table with no one
watching — served silently and wrongly, which is worse than the cliff this
replaces.


---

# WHAT LANDED

  * `slot_sort_block` — a row means KNOWN AT RISK, absence means SERVE.
    `entity_type_uuid IS NULL` blocks the whole space, which is what a restore
    or full resync needs since it does not know the type uuids when it starts.
    `NULLS NOT DISTINCT` makes that a real unique key.
  * `take_slot_sort_block` / `release_slot_sort_block` / `slot_sort_is_blocked`.
    The read gate DEFAULTS TO BLOCKED on any uncertainty — unreadable table,
    missing table, error — so a deployment whose schema predates this declines
    everything until it is created. Slow and correct.
  * BOTH read paths gated on it. The sort path was previously ungated at all,
    which was a live hole of its own (`issues/168`).
  * `record_slot_sort_coverage` takes or releases the per-type block FROM THE
    MEASUREMENT IT JUST MADE. One function owns measurement and gate together,
    because splitting them is what produced every marker-lifecycle bug in
    `issues/161`.
  * `resync_all` and `import_space` take a whole-space block at the start of the
    risky work, in the transaction that begins it.
  * TWO ALARMS in the maintenance probe, computed BEFORE recording because
    recording takes a block and would erase the evidence:
      - UNDECLARED SHORTFALL — a type short with no block held. A bug in the
        CODE: some write path made the table incomplete without declaring it,
        so queries were served from it. Logged at ERROR.
      - STALE BLOCK — a block older than 24h. Slow-and-correct but indefinite,
        and nothing else would report it. WARNING.
  * `scripts/migrate_slot_sort_blocks.py` — the upgrade path.

# THE UPGRADE GAP, which the tests could not have caught

An existing deployment holds `complete = false` coverage rows and an EMPTY block
table, because blocks did not exist when those rows were written. The moment the
inverted read path ships, every one of those types goes from DECLINED AND SLOW
to SERVED AND WRONG. That is the inverted failure mode arriving live, on
upgrade, with no code change required to trigger it.

Measured on the test database: 27 short types across 7 spaces, plus one space
(`sp_kg_types`) never measured at all — the "created but never populated" case
this issue predicted. The migration seeds a block for every short type and a
whole-space block for every space with no coverage rows.

RUN IT BEFORE DEPLOYING THE INVERTED READ PATH, not after.

# VERIFIED

    lead_nurture_100k / Lead        complete   -> served, no row needed, ~21ms
    wordnet_frames / NounSynsetNode short      -> blocked
    wordnet_frames / unknown type   unmeasured -> served
    16 spaces swept                            -> 0 undeclared, 0 stale

The sweep is the first time the design reports on itself, and a clean result is
meaningful: the alarm would have fired had the migration missed anything.

# STILL TRUE, AND THE REASON THE ALARMS EXIST

No audit can prove a FUTURE write path will take a block. The third row above is
the shape of the residual risk: a type nobody has measured is served. It is
bounded by the coverage probe measuring every type on every cycle, so an
undeclared shortfall is detected within one cycle rather than never — but
"detected within a cycle" is not "cannot happen", and the honest statement of
this design is that it trades a permanent slow failure for a bounded wrong one,
with an alarm on the window.


---

# THE ORDERING HAZARD IS CREATING THE TABLE, NOT MISSING IT

Two states look similar and behave oppositely:

    slot_sort_block ABSENT      -> is_blocked() defaults to True -> everything
                                   declines -> SLOW AND CORRECT
    slot_sort_block EMPTY       -> no row matches -> everything serves ->
                                   WRONG for any type already short

So an UNMIGRATED deployment is safe. The dangerous state is created by SCHEMA
INIT, which now includes `slot_sort_block` in the table list and would create it
EMPTY on an existing deployment that still holds `complete = false` coverage
rows. That is the window in which the inverted read path serves short tables.

`migrate_slot_sort_blocks.py` closes it by doing both in one run — CREATE, then
seed from the coverage rows. On an EXISTING deployment it must therefore run
BEFORE any schema-init step that would create the table, or immediately after
one that already did. On a NEW deployment an empty block table is correct:
there are no spaces and no coverage rows, so there is nothing to be wrong about.

This repository creates schema only by explicit action, never as a startup side
effect, which means these are two deliberate steps an operator sequences rather
than a race. Sequence them the right way round.

# WHERE IT HAS BEEN RUN

    vg-test (docker, :5433 sparql_sql_graph)      DONE — 28 blocks
    local dev (homebrew, :5432 sparql_sql_graph)  DONE — 130 blocks
                                                  (63 whole-space, 67 per-type)

Local dev is what the dev app container uses
(`LOCAL_DB_HOST=host.docker.internal`, `LOCAL_DB_NAME=sparql_sql_graph`) and is
where integration with the consuming applications is exercised — a peer of the
test stack rather than a lesser copy of it. It had NO block table at all — 100 slot-sort tables and 79 coverage rows, 67 of
them short across 30 spaces. It was in the safe state (absent table -> decline
everything) and is now correctly seeded.

NOT RUN, and deliberately not: the remote environments named in the dev app's
configuration — `PROD_DB`, `NEW_PROD_DB` and `TEST_DB`, all `vitalgraphdb` on
RDS. Those are deployments, not local state, and the migration against them is
an operator action.

Two vg-test tables are unaccounted for by design: `dawg_test` and
`perf_covbench` have `entity_slot_sort` tables but no row in `space`, so the
block table's foreign key cannot reference them. Both hold ZERO slot-sort rows
and no KG entity types, so there is nothing to serve wrongly. Worth knowing
rather than fixing: an unregistered space cannot be blocked, so if one ever did
hold KG data it would be served unguarded.

---

## 2026-09-06 — the production timeouts, root-caused

The 60s timeouts on the NurtureAction dedup shape were caused by this issue's
own gate, not by the query planner.

**The chain, verified in the PostgreSQL log.** This migration runs as the RDS
MASTER user, so the admin tables it created are owned by `postgres` with no
grants — while every space table is owned by `vitalgraph_user`, which created
them. The application could not read `slot_sort_block`, and
`slot_sort_is_blocked` treats an unreadable table exactly as it treats a missing
one:

> DEFAULTS TO BLOCKED ON ANY UNCERTAINTY — an unreadable table, a missing one,
> an error.

So the FILTER fast path went off for **every query in every space**. The
two-criterion shape has no workable plan in the general pipeline at 46M quads
(issues/161) and timed out at 60s; the one-criterion shapes stayed selective
enough to answer in ~0.3s. That asymmetry is what made it look like a planner
problem specific to conjunctions. It was a `GRANT`.

The log is unambiguous: **316 `ERROR: permission denied for table
slot_sort_block` from `vitalgraph_user` between 02:12:09 and 02:45:57Z** — and
nothing whatsoever in the application log, because the read path catches the
error and declines at DEBUG. Declining is supposed to be the safe outcome. It is
safe; here it was also permanent.

**Why this took so long to find.** Every reproduction connected as the master
user, which has rights on everything. The same query against the same rows
measured 128 ms for me and timed out for production, and I read that gap as
evidence that the deployed build must differ. A permissions fault is invisible
to any test that authenticates as an administrator — which is every diagnostic
script in `test_scripts/`, and this migration's own rehearsal.

**Fixed at 02:46Z** by granting SELECT/INSERT/UPDATE/DELETE on both admin tables
to `vitalgraph_user`. Last permission error 02:47:10Z, last query cancellation
02:46:26Z, none since; the app is now issuing `entity_slot_sort` queries.

**Measured as the master user** (before the grant was found), through
`_execute_entity_query` against live prod, 46.6M quads:

| shape | result |
|---|---|
| campaign + lead | **128 ms**, total=0 |
| lead only | 223 ms, total=0 |
| campaign only | 78 ms, total=77,831 |

`total=0` is correct: that lead has no term rows in the space, against 78,251
other `CtRefSFLeadId` values.

**Three fixes, from a deploy rehearsal against a clean instance.**

0. `_ensure_admin_tables` now GRANTS the admin tables to the application role,
   discovering it from the space tables' owner rather than naming it — the app
   role differs across deployments and a wrong literal would fail just as
   silently. `--grant-to` overrides when there are no space tables to infer
   from. This is the fix for the timeouts.

1. `migrate_slot_sort_blocks.py` now creates every admin table from
   `SparqlSQLSchema.ADMIN_TABLE_DDL` before any read. Both local stacks already
   had the coverage table, so every test run exercised the case where the
   precondition already held — the rehearsal found what the tests could not.

2. **The whole-space block had no releaser.** `record_slot_sort_coverage`
   releases per type; the read gate matches
   `entity_type_uuid IS NULL OR = $2`, so one whole-space row switches the fast
   path off for EVERY type and nothing took it back. A space seeded with one at
   upgrade stayed off permanently, with correct answers and no error, until an
   operator ran the DELETE by hand. Per-type release cannot fix this: the type
   that would clear the block does not know it is the last one. Added
   `release_whole_space_block_if_complete`, called from the maintenance sweep —
   the only caller that measures every type in a space — so the space now
   self-heals within one 300s cycle. It holds the block on an empty sweep,
   because "no types measured" is not evidence of completeness.

3. `migrate_rdf_stats_context_column.py` deadlocks against the running app's
   maintenance recompute, which takes the stats and quad tables in the opposite
   order. The deadlock is the safe outcome — the transaction aborts whole, so
   the table is never half-migrated — but the script reported it as a failure
   rather than as something to retry. Added a bounded retry with `lock_timeout`.

**Still open.** `sp_kg_types` and `testspace` carry seeded whole-space blocks on
prod. They will clear on the next maintenance cycle with fix 2 deployed; until
then those two spaces have the fast path off. `cardiff_kg` has only a per-type
block (`KGEntityType_KGEntity`, coverage 0/1) which does not affect
NurtureAction.
