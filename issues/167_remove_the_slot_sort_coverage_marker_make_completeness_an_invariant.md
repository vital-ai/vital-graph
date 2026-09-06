# Remove The Slot-Sort Coverage Marker — Make Completeness An Invariant

## Status: OPEN, design. The marker is a workaround for a gap that should not
## exist, and every bug it has caused was in its own lifecycle rather than in
## the data it describes.

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
