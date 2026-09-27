# The Maintenance Job Is 38% of Database Wall-Clock, and It Is What Users Feel

## Status: PARTIALLY FIXED 2026-09-02 in `2209009` — recommendation 2 landed.
## The rest is still open. See "What was done" below.

## How this was found, and why it took so long

I spent most of this investigation in CloudWatch application logs and in
`pg_stat_statements`, and both misled me:

* App logs record what the *application* thinks it ran. They showed `Entity
  query` completions with `total=0` / `total=1` and no `page_size: 25` request
  anywhere in three hours — so the user's reported page looked absent.
* `pg_stat_statements` is cumulative. The queryids I ranked on had **zero calls
  since the v0.0.51 cutover**; I was reading a fossil as a live rate.

`log_min_duration_statement = 1000` has been on all along, so every statement
over one second was already being written to the RDS Postgres log **with its
literals inlined and directly runnable**. That is the ground truth, it covers
every client (app, maintenance job, psql) uniformly, and I should have gone
there first. The finding below fell out in one pass once I did.

## The measurement

`error/postgresql.log.2026-09-02-18`, a 46-minute window (18:00–18:45 UTC),
270 statements over 1s. Classified by origin:

| origin | n | total | max | per 300s cycle |
|---|---:|---:|---:|---:|
| `ANALYZE`/`VACUUM` | 26 | 345.8s | 50.2s | 37.9s |
| grouping self-link check | 27 | 319.2s | **38.6s** | 35.0s |
| stats sync (`rdf_stats`, `rdf_pred_stats`) | 96 | 274.7s | 33.1s | 30.1s |
| `edge_table_drift` | 12 | 106.5s | 17.7s | 11.7s |
| **maintenance total** | **161** | **1046.1s** | | **114.8s** |
| user SPARQL | 28 | 157.0s | 17.2s | |

**Maintenance is 87% of all slow database time and 38% of wall-clock**, on a
4 vCPU box. Roughly 115 seconds of >1s sequential scans inside every 300-second
cycle. Slow maintenance statements appear in 33 of the 46 minutes.

## The two queries nobody had looked at

Both are maintenance, and both outrank every user query on the box.

**1. `maintenance_job.py:799` — the typeless-grouping-target probe, 38.6s max:**

```sql
WITH targets AS (
    SELECT DISTINCT object_uuid AS e FROM {space}_rdf_quad WHERE predicate_uuid = $1)
SELECT count(*) FROM targets t WHERE NOT EXISTS (
    SELECT 1 FROM {space}_rdf_quad q
    JOIN {space}_term p ON p.term_uuid = q.predicate_uuid
    WHERE q.subject_uuid = t.e AND p.term_text IN ('...#type', '...#vitaltype'))
```

This is a **watch**, not a repair — the comment above it says the origin is
"unexplained, which is precisely why it is worth watching". It is a full
`DISTINCT` over every grouping target joined against `term`, it runs for every
space on every cycle, it is ungated, and it costs 35s/cycle to answer a question
that has fired once, ever.

**2. `sync_edge_table.py:420` — `edge_table_drift`, 17.7s max:**

```sql
SELECT count(DISTINCT (subject_uuid, context_uuid)) FROM {space}_rdf_quad
WHERE predicate_uuid = $1
```

A `count(DISTINCT (...))` over a composite on a ~50M-row table. Also every
space, also every cycle, also just to produce a drift ratio.

## This is the user-visible symptom

The Nurture Actions listing page **is** in the log — `ORDER BY s0.v1 DESC,
s0.v0 LIMIT 25`, the frame/slot walk over `rdf_quad`+`term`. It ran four times:

    18:37:56   11,187 ms
    18:36:37    2,501 ms
    18:38:56    1,368 ms
    18:39:08    1,216 ms

**Identical SQL, 9x spread.** That is not a plan problem — a bad plan is
reliably bad. It is contention, and it closes the gap I could not previously
explain: the same bound value that logged at 24,382ms / 3.17M buffers
re-ran at 13ms / 276 buffers. I had guessed "cached plans in worker
processes". It is simpler than that — the maintenance scans evict the buffer
cache and saturate a 4-vCPU box, so the same query re-reads from storage.

This also explains why the `db.r6g.xlarge` resize did not fix the timeouts.
More RAM does not help when a full scan of the quad table walks the cache every
five minutes regardless of how large it is.

## Why the earlier diagnoses were incomplete rather than wrong

`issues/138` (semijoin identity truncation) and `issues/139` (corrupt
`rdf_stats`) were real and are fixed; the 133,783ms → 0.97ms measurement stands.
They removed the *pathological* plans. What remains is a healthy plan run on a
box whose cache and CPU are being consumed by its own housekeeping — a
different failure, which is why fixing the plans did not end the timeouts.

## What was done, 2026-09-02 (`2209009`)

**Recommendation 2 only: the two pure WATCHES came off the 300s loop.**
`_run_grouping_self_link_check` and `_run_graph_registration_check` write
nothing — zero UPDATE/INSERT/DELETE, only `logger.warning` — and were
re-deriving from the whole table every cycle at ~35s/cycle across spaces. They
now run hourly, gated per (watch, space) so the cost spreads across cycles
rather than spiking, on `time.monotonic` so a clock change cannot disable them,
and per-process so a restart still gets a full sweep.

Repairs were deliberately NOT slowed: delaying a repair delays a fix, whereas
delaying a watch delays a log line. A test asserts only the two write-nothing
checks are gated, and a second asserts they still write nothing — so if either
grows a repair, gating it fails loudly instead of silently deferring it.

Expected effect: ~35s/cycle becomes ~3s/cycle amortised. That is roughly a third
of the excess, NOT all of it.

## SUPERSEDED IN PART, 2026-09-03

Recommendations 1-4 below were framed as "run the expensive things less often".
That framing is now rejected: see
`planning/planning_performance/maintenance_incremental_only_plan.md`.

Lengthening an interval trades "expensive constantly" for "expensive
periodically" and leaves the cost proportional to the data. `issues/150` is the
proof — the hourly watch gating from `2209009` helped, and then a DIFFERENT
full walk on the same loop consumed 54% of wall-clock anyway.

The remaining work here is to make these steps INCREMENTAL, after which their
intervals can be deleted rather than tuned. Read the recommendations below as
"what was tried", not "what to do".

## What to do — still open

Recommendations 1, 3 and 4 below are NOT written. Recommendation 2 is done.

1. **Gate the self-link and drift checks on change.** Both recompute from
   scratch every cycle over the whole table. Neither needs to: skip a space
   whose quad count and `n_mod_since_analyze` are unchanged since the last pass.
   This is the single biggest win — ~47s/cycle for two diagnostics.
2. **Decouple the watch cadence from the repair cadence.** A check whose finding
   has occurred once does not belong on a 5-minute loop. Hourly, or daily, is
   the right cadence for a watch; keep 5 minutes for anything that repairs.
3. **Sample instead of scanning.** `edge_table_drift` wants a ratio, and
   `edge_table_orphan_rate` right below it already takes the sampling approach
   (`sample: int = 200`). The drift measure can do the same.
4. **Stagger spaces.** All spaces run in one burst; round-robin one space per
   cycle spreads 115s over N cycles without reducing coverage.

## Verifying a fix

Re-run the classification against a later log file and compare the per-cycle
maintenance total. The listing query's *spread* is the user-facing measure —
it should collapse toward its 1,216ms floor. Do not measure it once and call
it fixed; the whole point is that the same SQL varies 9x by what else is running.

## Reproducing the measurement

    aws rds download-db-log-file-portion --profile <profile> \
      --db-instance-identifier <instance> \
      --log-file-name error/postgresql.log.YYYY-MM-DD-HH \
      --starting-token <marker>   # paginate; one call truncates

Split on the timestamp prefix, regex `duration: ([0-9.]+) ms`, classify by
statement prefix. Statements logged as `statement:` (not `execute`) carry
inlined literals and can be replayed directly.

## Re-measured 2026-09-25 — 23 days on, recommendations 1/3/4 still unwritten

Found while triaging a report of slow production queries that turned out to have
an upstream cause. The box was **idle** throughout — 19 idle connections,
nothing running, no ungranted locks — which makes this a clean read of the
background load rather than of an incident.

`pg_stat_statements`, 57-day window (reset 2026-07-30), on the same 4-vCPU
`db.r6g.xlarge`, now a 114 GB database:

| | calls | hours | share of all exec time |
|---|---:|---:|---:|
| `ANALYZE` / `VACUUM` alone | 194,151 | 129.8 | **21.1%** |
| everything else | 400,680,645 | 485.1 | 78.9% |

**21.1% is a floor, not the figure.** It counts only statements beginning
`ANALYZE`/`VACUUM`; every probe in this issue is a `SELECT` and lands in
"everything else". The named ones are still there and still ungated:

    edge_table_drift (this issue's query 2)
      <space>      5,633 calls  mean 18,134 ms   28.4 h
      lead_prod    5,881 calls  mean  5,116 ms    8.4 h
    frame_slot drift  24,522 calls  mean 1,909 ms   13.0 h
    edge-count probe  32,904 calls  mean 2,324 ms   21.2 h
    stats recompute      735 calls  mean ~45,000 ms  9.1 h

`sync_edge_table.py:435` now carries the conclusion in its own docstring —
*"THIS QUERY SHOULD NOT EXIST ON A SCHEDULE AT ALL. Both sides are counts the
write path already knows, and recomputing them from ~50M rows every cycle is the
defect."* — so recommendation 1 is agreed in the code and simply not built.

The three single largest statements in the entire database are maintenance:

    ANALYZE "<space>_rdf_quad"      7,023 calls  mean 24.8s  max 341s   48.3 h
    VACUUM  "<space>_term"          9,486 calls  mean 10.2s             26.9 h
    ANALYZE "<space>_term"          7,574 calls  mean  8.1s             17.1 h

Two things that were NOT true in the original measurement and should not be
re-diagnosed from it:

  * **`issues/136` is fixed.** Maintenance connections take a 15-minute
    `statement_timeout` (`MAINTENANCE_STATEMENT_TIMEOUT_MS`), which is why an
    ANALYZE can run 341s against the database's 60s default. VACUUM completes;
    dead tuples on the big tables read 0 and 644.
  * **`issues/139` has not returned.** `<space>_rdf_stats` sums to 22,846,358
    with a 3,025,627 max — the post-fix shape, not the corrupt one.

**New, and split out as `issues/236`:** the ANALYZE/VACUUM scheduler's skip
condition is a conjunction (`maintenance_job.py:1018`, `:1052`), so elapsed time
alone schedules work on tables with zero modifications and zero dead tuples.
Three idle fixture spaces have absorbed 32,115 ANALYZEs and 13,696 VACUUMs on
that basis, and `<space>_term` — insert-only, six lifetime deletes — has been
vacuumed 9,543 times. That is this issue's recommendation 1, one layer down.

**Tracked by `issues/239`** as of 2026-09-25. This issue is the parent finding
of that group and its recommendations 1, 3 and 4 are still the largest single
block of remaining work in it.

## Rec 1, 2026-09-25: it was HALF done, and the missing half was invisible

Recorded above as unwritten. It was in fact built for two probes and missing on
two others, and the reason it read as unwritten is worth keeping.

**What was already there.** `probe_data_changed` / `mark_probe_converged`
(`issues/150`) gate a probe on the quad table's write watermark and keep it open
while a repair has outstanding work. `edge_table_drift` and `frame_entity_drift`
have carried it since. **It works**: over 16,691 cycles, `testspace` — write
watermark ZERO, never written — ran `edge_table_drift` **0 times**, while
actively-written spaces ran it ~35% of cycles. A write-existence gate cannot do
better than that on a space that is continuously written, which is the honest
ceiling of rec 1 as specified.

**What was missing, and where the hours actually were.** Two expensive probes
had no gate at all, and both were burning time on `testspace`:

| probe | calls | mean | hours | why ungated |
|---|---:|---:|---:|---|
| `entity_slot_sort_coverage` | 30,833 | 2,852 ms | **24.4** | never gated |
| `frame_slot_drift` (2nd call site) | 34,979 | 2,304 ms | **22.4** | `_run_frame_slot_integrity` is a near-copy of `_run_frame_entity_integrity`, which IS gated — the copy lost the gate |

**46.8 hours, on a space that has never been written to.** Both are now gated.

Two details that made this worth doing carefully rather than quickly:

  * **The coverage step gets the gate on the PROBE, not the iteration.** The same
    loop maintains `slot_sort_coverage` — the marker the READ path's fast gate
    consults — and releases whole-space blocks. A `continue` there does not waste
    time, it leaves the fast path off (`issues/167`: two spaces sat blocked over
    complete tables until someone ran a DELETE by hand). The marker query
    `entity_slot_sort_all_types` measures **220 ms against the probe's 2,852 ms**,
    so gating the expensive half and letting the marker run every cycle costs
    almost nothing and keeps the failure mode at "wasted work" rather than
    "wrong page".
  * **The guard test was hand-kept, which is why this survived.**
    `test_the_remaining_o_graph_probes_are_gated` asks "is this probe NAME gated
    somewhere" — and for `frame_slot_drift` the answer was yes, at the other call
    site. It is now joined by a test DERIVED PER CALL SITE, scoped to the
    enclosing function. A character-window version of that test passes on the
    real code and fails to catch the defect, because the gate and call are ~1,200
    characters apart in comments; the window wide enough to accept that also
    accepts an ungated copy sixty lines below. There is a test asserting the
    detector flags the real pre-fix source, by function name.

**Recs 3 and 4 are untouched** and the framing above still stands: what remains
for the actively-written spaces is to make the counts INCREMENTAL, not to sample
or to lengthen an interval. `sync_edge_table.py:435` still says so.
