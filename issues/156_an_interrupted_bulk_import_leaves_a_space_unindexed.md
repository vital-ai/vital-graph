# An Interrupted Bulk Import Leaves A Space Silently Unindexed

## Status: FIXED 2026-10-11 (uncommitted), all three options.
##
## Found 2026-09-04 on the vg-test stack, by doing it — three
## imports were killed mid-flight while choosing a dataset, and the space was
## left with primary keys only.

## What happens

`ImportEngine.import_ntriples_bulk` drops the space's secondary indexes before
COPY and recreates them afterwards
(`data_import_impl.py:353` and `:468`):

    saved_indexes = await conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes ... AND indexname NOT LIKE '%_pkey'",
        [term_tbl, quad_tbl])
    for row in saved_indexes:
        await conn.execute(f"DROP INDEX IF EXISTS {row['indexname']}")
    ...                                   # parse, COPY terms, COPY quads
    for row in saved_indexes:
        await conn.execute(row['indexdef'])

`saved_indexes` lives only in the importing process's memory. If that process
dies between the drop and the recreate -- kill, crash, timeout, container
restart, connection loss -- the definitions go with it and the indexes are gone.

THE NORMAL PATH IS FINE and was verified: a fresh space has 9 quad + 6 term
indexes, and after a completed `--mode bulk` import it still has 9 and 6.

## Why it matters more than "do not kill imports"

The result is a space that answers every query CORRECTLY and scans for all of
them. Measured on a 50.3M-quad / 10.5M-term space in this state:

    resolve one term by exact text     2,110 ms   (parallel seq scan, 10.5M rows)
    bounded runtime count (cap 50k)    5,812 ms
    a KG entity query                  timed out at the 60 s request budget

Nothing reports it. There is no "this space has no indexes" check anywhere, and
the symptom -- slow queries, right answers -- is the failure mode this codebase
has been bitten by repeatedly (`issues/139`, `issues/145`): correct output, ruined
plans, no signal.

It also fooled ME for three messages: I measured the Nurture query shape against
a space I had broken, reported that the production failure reproduced, and then
blamed the import for dropping indexes. Both claims were wrong and both were
withdrawn. A check would have said so immediately.

## Options

1. **RECREATE FROM THE CATALOG, NOT FROM MEMORY.** The index definitions are
   already derivable: `create_space_indexes_sql` emits exactly this set for any
   space. Recreating from that rather than from a saved fetch makes the recovery
   independent of the process that dropped them, and makes a rerun of the import
   self-healing.

2. **DETECT IT.** `scripts/ensure_space_indexes.py` already exists and already
   knows the full set. Nothing calls it as a CHECK. The maintenance job is the
   natural home: a space missing indexes that `create_space_indexes_sql` names is
   a one-query comparison against `pg_indexes`, and it should be loud.

3. **NARROW THE WINDOW.** Recreate in a `finally`, so an exception inside the
   import restores them. Does not survive a kill -9 or a container stop, so it
   is a complement to 1 and 2 rather than a fix.

Preference: 2 first, because it turns a silent state into a reported one for
every cause including the ones nobody has thought of, and it is a few lines
against a script that already exists. Then 1.

## Not a regression

This behaviour predates the rdf_stats recompute work and is untouched by it.
Recorded here because it was found while testing that work, and because the
diagnosis cost real time.

## Fix, 2026-10-11 — all three options

Found while fixing it: **a CANCEL also left the space unindexed**, not only a
kill. The three `cancel_event` checks returned straight past the recreate.

1. **Restore from the schema, not from memory**
   (`vitalgraph/db/sparql_sql/space_indexes.py`: `schema_indexes`,
   `missing_space_indexes`, `restore_space_indexes`). The import replays its
   saved definitions first, so an index the schema does not name is kept, then
   every schema index still missing on term/quad. A rerun is self-healing.
2. **Detect it.** The maintenance job's `_run_space_index_check` compares each
   space with `create_space_indexes_sql` every 15 min
   (`VITALGRAPH_SPACE_INDEX_CHECK_S`), one catalog query per space, and logs a
   WARNING naming the indexes and `scripts/ensure_space_indexes.py --space X`.
   Detection only: a non-concurrent `CREATE INDEX` on a large table blocks
   writes, so repair is an operator's call. The message says an import in
   progress is a legitimate cause.
3. **Narrow the window.** Everything between the DROP and the recreate is in a
   `try`, and the recreate is its `finally`: exceptions and cancels restore
   every index. A failed restore logs an ERROR with the repair command.

Tests: `tests/integration/test_interrupted_bulk_import_keeps_indexes.py` (4):
a cancelled import and a failed import each restore every index (both fail
against the old code: indexes left dropped); the schema restore needs no memory
of what was dropped; the maintenance check reports a space missing one. Each
test first asserts the fixture space is complete: the first version compared an
empty set with an empty set after an earlier test had stripped the shared space,
and passed vacuously against the unfixed code.
