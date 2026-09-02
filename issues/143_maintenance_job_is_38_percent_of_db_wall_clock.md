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
