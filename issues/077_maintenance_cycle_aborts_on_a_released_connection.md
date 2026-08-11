# The Maintenance Cycle Aborted Every Run, and Reported Itself Complete

## Status: FIXED 2026-08-11

Seen in the app log, every cycle:

    MaintenanceJob cycle error: cannot call Connection.fetchval():
    connection has been released back to the pool
      File "vitalgraph/process/maintenance_job.py", line 524, in _run_edge_integrity
        has_vitaltype = await conn.fetchval(f"""

## The bug

`_run_edge_integrity` computes drift, orphan rate and untyped rate inside
`async with self._pool.acquire() as conn:`. The `has_vitaltype` probe added by
`c11e3b1` sits AFTER that block, so it used a connection the pool had already
taken back.

`EDGE_UNTYPED_WARN_PCT` is 0.01, so any space with 1% untyped edge rows reaches
the probe — which is the normal state of a table whose `edge_type_uuid` column
was added by a migration and not yet backfilled. It therefore fired on essentially
every cycle rather than in some rare corner.

## Why it mattered more than one failed check

A single `except` wraps the whole cycle body, so the raise skipped **every
remaining step**:

    edge integrity          never ran
    frame-entity integrity  never ran
    stats prune             never ran   <- bounds rdf_stats to the reorder window
    vector reindex          never ran
    cleanup                 never ran

`stats prune` is the one to care about: `issues/062` relies on it to keep
`rdf_stats` bounded, and the reorder path reads those statistics.

## Why it went unnoticed, which is the more useful part

The cycle logged, immediately after the traceback:

    MaintenanceJob cycle complete in 1081ms — analyze={...} vacuum={...}
    vector_reindex=None cleanup=False

Steps that never ran report as `None`/`False`, which is indistinguishable from
steps that ran and found nothing to do. So the line reads as a healthy cycle. The
error above it is a single line in a busy log, and the summary underneath
contradicts it.

Fixed in two places:

1. The probe takes a FRESH connection. Deliberately not moved inside the `try`
   above — that one means "this space has no edge table" and would swallow a
   real failure here.
2. `run()` records `summary["aborted"]` and logs `cycle ABORTED ... every later
   step was SKIPPED, not clean` instead of the completion line. A cycle that
   dies partway can no longer look like a quiet one.

## Coverage

`tests/unit/test_maintenance_edge_integrity_conn.py`. There were no tests for
this job at all. Both fail against the previous code — the second one printing
the misleading `cycle complete` line after a raise, which is the defect it
exists to pin.

## Related

- `issues/041` — the orphan-rate probe this sits beside, and why counts alone
  cannot see a stale edge table.
- `issues/062` — the `rdf_stats` bound that `stats prune` maintains.
