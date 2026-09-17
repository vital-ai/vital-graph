# The Analytics Job Ignores The Maintenance Exclusion List

## Status: OPEN, found 2026-09-17 while triaging a dev slowdown. Minor — it runs
## DAILY, so it cannot explain a sustained stall, and saying so is the point:
## it was briefly mistaken for the cause before the interval was checked.

**Related:** `issues/192` (the maintenance incident that created the exclusion
list), `issues/109` (a scoped trigger that silently ran everything — same job,
different defect)

## The defect, in two parts

**It does not honour the exclusion list.** `AnalyticsJob.run()` iterates
`_list_spaces()` and computes for every space. Three other jobs read
`VG_MAINTENANCE_EXCLUDE_SPACES` — `maintenance_job.py:545`, `resync_all.py:238`,
and `backfill_server_properties_task.py:153`, which falls back to it
deliberately. This one does not, so a space declared off-limits for maintenance
is still walked here.

**Its one unguarded query is not as cheap as its comment claims.**
`_compute_and_store` skips the expensive property analytics above 5M quads:

    if quad_estimate > 5_000_000:
        ... "skipping expensive property analytics"

but `distinct_pred_count` is computed ABOVE that guard, with this comment:

    # Distinct predicate count (fast — index-only scan on predicate_uuid)
    SELECT COUNT(DISTINCT predicate_uuid) FROM {t_quad} q WHERE 1=1{gf}

Measured on the 50.5M-quad benchmark fixture: **4.1 s warm, returning 21**. An
index-only scan of 50M rows is still a scan of 50M rows. The guard protects
everything except the query that was assumed free.

## Why it is minor, stated precisely

The default interval is **86400 s** (`vitalgraphapp_impl.py:563`). Daily, at a
few seconds per large space, is noise.

It is recorded because the shape is the one `issues/192` already cost a day to:
a periodic job walking benchmark fixtures nobody intended it to walk. Dev
carries 40+ spaces including several 50M+ quad fixtures; production carries six
real ones and no fixtures, so the exposure is dev's.

**It was briefly blamed for a dev slowdown and that was wrong** — the interval
makes it impossible. The actual cause was memory pressure. Noted so the next
reader does not re-run the same wrong inference.

## What to do

1. Read `VG_MAINTENANCE_EXCLUDE_SPACES` in `AnalyticsJob.run()`, by the same
   fallback rule the backfill task uses.
2. Move `distinct_pred_count` BELOW the size guard, or correct the comment. The
   value is genuinely useful and genuinely not free; one of the two has to give.
