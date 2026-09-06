# Remove The Slot-Sort Coverage Marker — Make Completeness An Invariant

## Status: OPEN, design. The marker is a workaround for a gap that should not
## exist, and every bug it has caused was in its own lifecycle rather than in
## the data it describes.

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

STEP 1 IS THEREFORE AN AUDIT, not a code change: for each of the three, list the
callers and state for each whether the derivation runs. That audit is the work;
the fix afterwards is small.

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

  * every quad-writing path either derives inline or ends in the job, listed
    explicitly with its callers;
  * a maintenance alarm on any short type, quiet in production across the write
    paths above;
  * `slot_sort_coverage_is_complete` gone from the read path, and
    `fast_slot_filter` serving unconditionally;
  * the coverage computation KEPT, as the alarm.
