# An Interrupted Bulk Import Leaves A Space Silently Unindexed

## Status: OPEN. Found 2026-09-04 on the vg-test stack, by doing it — three
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
