# The Analytics Job Ignores The Maintenance Exclusion List

## Status: FIXED 2026-09-18. `run()` now reads the exclusion list with the same
## fallback contract the backfill task uses, and the misleading "fast" comment
## on the unguarded query is corrected. Found 2026-09-17 while triaging a dev
## slowdown; minor, and saying so is the point — it runs DAILY, so it could
## never have explained a sustained stall, and it was briefly blamed for one
## before the interval was checked.

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

## The fix

1. `run()` reads `ANALYTICS_EXCLUDE_SPACES`, falling back to
   `VG_MAINTENANCE_EXCLUDE_SPACES` when unset — the contract the backfill task
   states, where an explicit EMPTY value means "compute everything" rather than
   falling back. Without that distinction a deployment could not re-enable
   analytics for a space without also re-enabling maintenance for it, which is
   the whole reason the backfill task spells it out. Four cells test it.

2. The comment, not the query. "Move it below the guard, or correct the
   comment" were the two options and the SECOND is right: the note beside the
   skip return wants a real number there deliberately, so the UI shows one
   honest figure instead of a blank panel. Nulling it to save 4.1 s would have
   traded a feature for a cost that (1) removes anyway — the fixtures that made
   it expensive are exactly the spaces now excluded. The comment claiming
   "fast — index-only scan" is corrected: that is true of the plan and false of
   the cost.
