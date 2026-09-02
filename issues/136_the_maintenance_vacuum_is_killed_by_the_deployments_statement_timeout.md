# The Maintenance VACUUM Is Killed By The Deployment's `statement_timeout`, And Reports Success

## Status: FIXED 2026-09-01. Maintenance connections now set their own fences
## at connect time; a partial run logs at ERROR instead of "complete"; and
## staleness takes the later of the manual and autovacuum timestamps.
## Verified against production. The measurements below are the BEFORE state.

Found 2026-09-01 while reading 24h of production logs (`/ecs/vitalgraph-prod`,
image `v0.0.48-prod`, task definition 48) for a reported ~450 client
`ReadTimeout`/day. The timeouts are their own problem — most of what fixes them
is already in HEAD and undeployed, see "What this is NOT" below. This issue is
the thing that reading those logs turned up that nothing in the repository knows
about.

## The measurement

Window: 2026-08-31 16:00 → 2026-09-01 16:00 UTC. Space `prod_kg`, 7 tables, of
which `prod_kg_rdf_quad` is the large one.

    VACUUM  pick → prod_kg                                     244
      of those, "VACUUM complete: space=prod_kg tables=6"      223   <- one table missing
      of those, "VACUUM complete: space=prod_kg tables=7"       21
      VACUUM prod_kg_rdf_quad failed: statement timeout        222
      VACUUM prod_kg_rdf_quad failed: lock timeout               1

    ANALYZE pick → prod_kg                                     108
      ANALYZE prod_kg_rdf_quad failed: statement timeout        42
      ANALYZE prod_kg_rdf_quad failed: lock timeout             10

**VACUUM of the quad table succeeded 21 times out of 244 — 8.6%.** ANALYZE of the
same table succeeded about 70% of the time (the 52 failures above include 20 from
the separate `auto_analyze` path).

Dead tuples for the space, sampled hourly from the job's own
`scored 5 space(s): ...` line, climb without a reclamation event:

    20:00  252,395      02:00  332,365      08:00  351,626      14:00  402,833
    21:00  262,338      03:00  336,441      09:00  356,636      15:00  419,869
    22:00  281,942      04:00  338,348      10:00  371,946
    23:00  299,070      05:00  342,052      11:00  377,119
    00:00  316,438      06:00  352,342      12:00  379,392
    01:00  327,830      07:00  354,278      13:00  388,552

~9k/hour accumulating, monotonic across 19 hours. On a table of this size that is
~1.7% dead — not catastrophic bloat, and this issue does not claim it is. What it
is, is unbounded: nothing in the loop reclaims it.

## The cause

The RDS parameter group sets **`statement_timeout = 60000` at the parameter-group
level**, so every session in the database inherits it. Both maintenance paths open
their own short-lived psycopg connection and neither clears it:

* `maintenance_job._make_sync_connection` (`maintenance_job.py:1351`) —
  `psycopg.connect(..., autocommit=True)`, no `options`, no `SET`.
* `auto_analyze._sync_analyze` (`auto_analyze.py:83`) — the same connection,
  built independently.

The docstring on the first one explains why it is a *separate* connection ("so
ANALYZE / VACUUM never touch the asyncpg pool or the event loop"), which is
correct and was the right call. What it does not do is notice that a fresh
connection is not a fresh *configuration*.

The read path already understands this distinction — `_apply_read_fence` deliberately
sets `SET LOCAL statement_timeout` inside a transaction precisely so the setting
cannot leak onto a pooled connection. The maintenance path needs the mirror image:
an explicit *removal* of a fence it did not ask for.

`VACUUM` is exactly the statement for which a read-shaped timeout is meaningless.
It is not a query with a caller waiting on it, and there is no answer to return
late.

## Three consequences, in order of how hard they are to see

**1. It reports success.** `_sync_run_tables` catches per-table, logs a WARNING,
and returns the count of tables that worked. The caller then logs:

    VACUUM prod_kg_rdf_quad failed: canceling statement due to statement timeout   [WARNING]
    VACUUM complete: space=prod_kg tables=6                                        [INFO]

Any monitor watching for "did maintenance run" sees 244 clean completions a day.
The one table that matters is the one missing from `tables=6`, and nothing says so.
This is `issues/108` and `issues/084` again: a green report measuring something
other than what it names.

**2. One space starves the other four.** Because the VACUUM never lands,
`last_vacuum` for that table never advances, so its staleness score stays highest
and the next cycle picks the same space again:

    VACUUM pick → prod_kg     244        ANALYZE pick → prod_kg     108
                  lead_prod    18                      lead_prod    65
                  testspace     5                      testspace    44
                  lead_data     5                      lead_data    42
                  sp_kg_types   3                      sp_kg_types  36

89% of all VACUUM picks in 24h went to the one space that cannot complete one.
The other four share 31. Compare the ANALYZE column, which mostly succeeds and is
therefore spread roughly evenly — that is what the scorer is supposed to look like.

**3. It burns 2-vCPU database time to throw the work away.** 223 killed VACUUMs
× 60s = **3.7 hours of VACUUM per day, cancelled**. The instance is a
`db.r6g.large` (2 vCPU) whose hourly CPU *maxima* reached 96-99.6% in four hours
of this window. A VACUUM restarted from the beginning every six minutes, on a
schedule, is a contributor to the saturation that causes the query timeouts the
investigation started from.

## The scoring bug underneath it

`_pick_worst_for_vacuum` scores `dead * (1.0 + minutes_since / 60.0)`, and
`_gather_*_stats` builds `minutes_since` from the **oldest** `last_vacuum` across
the space's tables:

    last_v = row["last_vacuum"] or row["last_autovacuum"]      # :488

Two problems in one line, both independent of the timeout:

* `or` prefers the MANUAL vacuum whenever it is non-NULL. A table that autovacuums
  perfectly well but was last VACUUMed by hand weeks ago reads as weeks stale
  forever. `last_analyze` at `:483` has the identical shape.
* Taking the minimum across tables means one stuck table sets the score for the
  whole space, which is what makes the starvation in consequence 2 total rather
  than merely unfair.

The effect on the number is large enough to be misleading on its own. At 16:01
the job logged `prod_kg(mods=6690, dead=561)` and a VACUUM score of
**233,399.3** — 561 dead tuples scoring in the hundreds of thousands, because the
staleness multiplier had reached ~415. **The score is not a dead-tuple count and
must not be read as one.** It is the first thing in the logs that looks like a
severity signal and it is the least trustworthy number there.

## What this is NOT

> **2026-09-01: VERIFIED against the deployed source.** Production is built from
> a separate deploy repository (`issues/137`); once that was known, every claim
> below was checked against the deployed tree rather than inferred from logs.
> All five held: `_checked_query`, `_gather_cancelling`, `_apply_read_fence` and
> `semijoin.py` are all ABSENT at the deployed commit, and the bulk insert is
> `logger.error(...)` then `return 0`. The deployed `maintenance_job.py` contains
> no reference to `statement_timeout` either, so this issue's defect is present
> in the running code and in `main` alike.

The client-visible symptom that started this — ~450 `ReadTimeout`/day, 1,391
`execute_sparql_query ... failed:` lines with an empty message, 713 requests
landing in the 59-61s band — is **mostly already fixed in HEAD and simply not
deployed**. Recorded here so this issue is not mistaken for that one:

* the empty error message is asyncpg's 60s `command_timeout` winning the race
  against the server's 60s `statement_timeout`; HEAD's 55s read fence
  (`sparql_sql_space_impl.py:77`, `issues/044`) makes the server win and produces
  a real message
* returning `200` with `0 results` on a query that died is fixed by
  `_checked_query` / `BackendQueryError` (`kgquery_endpoint.py:85`, `issues/082`,
  `issues/100`)
* `add_rdf_quads_batch_bulk` returning 0 instead of raising is fixed
  (`sparql_sql_space_impl.py:1573`, `issues/105`) — which also makes the
  "likely a PostgreSQL index overflow" message in `kg_backend_utils.py:839`
  unreachable, and it was misattributing a lock timeout anyway
* the slow shape itself (high-cardinality slot-value lookups, worst case 390 of
  758 requests over 30s) is `issues/090` / `issues/119`, and both shipped
  mitigations — the extended `(predicate_uuid, object_uuid)` statistics at
  `sparql_sql_schema.py:1179` and the `semijoin` rewrite — are in HEAD

None of those touch the maintenance path. This issue is the one that is open
everywhere, including HEAD.

## What a fix has to decide

Clearing `statement_timeout` on the maintenance connection is one line, and it is
the wrong place to stop, because an unfenced VACUUM on a growing table is a
different risk rather than no risk. The open questions:

* **`statement_timeout = 0` for VACUUM, or a large explicit value?** Zero is
  correct in principle for a statement with no waiting caller, but it means a
  pathological VACUUM has nothing to stop it. A generous explicit bound (say
  15-30 min) fails loudly instead of silently every six minutes.
* **`lock_timeout` too?** A `lock_timeout` of exactly 10s is in force on prod
  writes — visible as `update_subjects_graph` failing at 10.017s and 10.253s. It
  is **not in this repository and not in the RDS parameter group**, so it is an
  `ALTER ROLE` or `ALTER DATABASE` setting nobody here has recorded. It accounts
  for 1 VACUUM and 10 ANALYZE failures on top of the timeout ones. Its source
  should be established before anything overrides it.
* **Should a partial failure still log "complete"?** Simplest correct behaviour
  is to log at ERROR and report the attempted count alongside the completed one,
  so `tables=6/7` is visible without reading the WARNING above it.
* **`VACUUM (SKIP_LOCKED)`** would convert the lock-timeout failures into a
  clean skip rather than an error.

`scripts/ensure_space_indexes.py` also needs a run against production — the
extended statistics it emits are DB-side artifacts that no deploy carries. That
is independent of this issue but shares the maintenance window.

## Retractions from the first pass over these logs

Both readings were mine, both looked solid from the first cut, and both are the
inference the logs invite. Recorded so the next reader does not repeat them.

* **"The dead-tuple score grew 35x in 23 hours, so the table is badly bloated."**
  It grew 233,399 → 8,174,310, and that is what the log says. But the score is
  `dead * (1 + minutes_since/60)`, and the multiplier does most of the work — the
  actual dead-tuple count over the same window went 252k → 420k. Real, unbounded,
  and about 1.7% of the table. Not 35x.
* **"ANALYZE of the quad table cannot complete, so the extended statistics can
  never activate."** False, and it inverts the fix ordering. ANALYZE succeeds
  roughly 70% of the time (76 of 108 cycles completed all 7 tables). It is VACUUM
  that is at 8.6%. The statistics fix does not depend on this issue and can be
  applied independently.

## Related

- `issues/112` — the maintenance job's other surprise: it re-ANALYZEs benchmark
  fixtures and the exclusion that fixes it removes the only thing keeping them
  fresh. Same job, same shape of problem — the maintenance loop's real behaviour
  differs from what the code reads like.
- `issues/108`, `issues/084` — a report that says "complete" while the thing it
  names did not happen.
- `issues/090`, `issues/119` — the query shape whose timeouts led here.
- `issues/081` — a measurement compared against a configuration nobody recorded.
  The parameter-group `statement_timeout` is that, one layer out: a
  deployment-level setting the application inherits and never states.

---

## Measured against production, 2026-09-01 — three corrections and one answer

Connected to the instance directly as `vitalgraph_user` (the master password is
RDS-managed and rotates; the `.env` copy cannot match it — read
`MasterUserSecret` or use the app role). Everything below is from the live
database, and it moves this issue's severity DOWN while making its waste
argument sharper.

### The `lock_timeout` question is answered

    SELECT * FROM pg_db_role_setting;
    vitalgraphdb | <all roles> | {lock_timeout=10s}

It is `ALTER DATABASE vitalgraphdb SET lock_timeout = '10s'`. Not the parameter
group, not the repository — a database-level setting. That is the 10.017s /
10.253s write failures. `statement_timeout` shows `1min` from `configuration
file`, i.e. the parameter group, as recorded above.

### CORRECTION 1 — the bloat is BOUNDED, not unbounded

    prod_kg_rdf_quad   44,913,629 live   435,213 dead   0.96% dead
    autovacuum threshold (50 + 0.01 * reltuples)          449,154
    last_autovacuum 08-30 17:33     autovacuum_count 8
    last_vacuum     08-31 20:29     vacuum_count 3476

Dead tuples are ~14k below the autovacuum trigger. **Autovacuum does not obey
`statement_timeout`** — when it fires it runs to completion, which is why
`last_autovacuum` exists at all despite 20 straight hours of killed manual
VACUUMs. So the table does not bloat without limit; it oscillates around a ~1%
watermark set by autovacuum instead of the ~0% the maintenance job intends.

The earlier framing in this file — "nothing in the loop reclaims it" — is wrong.
Autovacuum reclaims it, late and at a higher watermark. What the maintenance job
contributes is zero.

### CORRECTION 2 — a completed VACUUM will NOT make the next one fit

The recommendation this investigation was heading toward was: run one VACUUM by
hand with `statement_timeout = 0`, because a completed pass leaves the visibility
map current and the next routine VACUUM would then fit inside 60s. **That
reasoning is wrong, and the numbers say so plainly:**

    heap                5,064 MB       relpages       648,110
    indexes            18,432 MB       relallvisible  628,204  (96.9% all-visible)
    total              23 GB           9 indexes, largest 6,009 MB

The visibility map is *already* 96.9% current, so the heap scan is only ~20k
pages and was never the cost. The cost is **index cleanup across 18 GB in nine
indexes** — and that is proportional to total index size, not to dead tuples. It
does not shrink after a successful VACUUM. Against 3.8 GB of `shared_buffers`
and gp3 at 3,000 IOPS, 18 GB of index scanning cannot finish in 60 seconds and
never will.

**So a manual VACUUM buys one completion and changes nothing structural.** The
fence has to be lifted on the maintenance path, or the routine VACUUM has to stop
doing index cleanup every time (`INDEX_CLEANUP OFF` for the routine pass, with a
periodic full one), or the nine indexes have to be justified.

### CORRECTION 3 — the extended statistics are already deployed, and do not help

    stat_prod_kg_quad_po   (predicate_uuid, object_uuid)   kinds {d,m}   stxstattarget 1000
    attstattarget: subject_uuid 1000, predicate_uuid 1000, object_uuid 500, context_uuid 500

Exactly what `sparql_sql_schema.py:1179` emits, already present on all four
spaces — and the DEPLOYED schema module emits `quad_po` too, so the running code
created them itself at cutover. "Run `ensure_space_indexes.py` against
production" can be struck from the plan; the statistic has been in place since
2026-07-30 and the timeouts happened anyway. It did not fix the timeouts, which is `issues/119` §8's
conclusion holding on real data: a pair-MCV cannot cover this value space.

## What the waste actually costs, measured

`pg_stat_statements`, 33.5-day window (reset 2026-07-30 03:20 UTC):

    queryid                  calls    mean_ms   max_ms   total_s   rows
    -2008816266530851936    24,340    16,549    59,824   402,805   24,340   (COUNT twin)
     5465777133120619217    24,340    16,534    59,812   402,443        0   (SELECT twin)
    -5972074618902859341     4,527    24,191    59,995   109,511        -   ANALYZE "prod_kg_rdf_quad"

The pair is the timing-out shape, run in parallel by `_execute_entity_query`.
**805,249 CPU-seconds against 5,799,440 vCPU-seconds available in the window —
13.9% of the instance's entire CPU budget, spent on two statements.**

**Every one of the 24,340 SELECT calls returned zero rows.** The workload is
paying ~16.5s per call to establish that something is not there.

`ANALYZE` on this table is itself a 24-second statement run 4,527 times — **30.4
hours** in the window, and its `max_exec_time` of 59,995 ms shows it losing to
the same 60s fence.

## The plans, captured

Four `EXPLAIN (GENERIC_PLAN)` captures (no execution) in
`planning/prod_plan_capture_20260901/` — the two twins above plus the two
2-frame shapes. This is the "before" record for an ANALYZE against the CURRENT
deployment: if anyone ANALYZEs this table and a shape flips, this is what to
diff against. It is **not** a baseline for a deploy of `main`, which emits
different SQL for these shapes — see `issues/137`.

All four are nested-loop-dominated — 12-13 `Nested Loop` against 2 `Hash Join`.
The signature is unmistakable:

    Limit  (cost=66.10..66.24 rows=1 width=255)
      ...
      ->  Nested Loop  (cost=25.94..61.18 rows=1 width=16)
            ->  Nested Loop  (cost=25.37..59.65 rows=1 width=32)
                  ->  Nested Loop  (cost=24.81..58.12 rows=1 width=48)
                        ->  Nested Loop  (cost=24.24..56.59 rows=1 width=64)

**`rows=1` at every level and a total cost of 66, for a statement whose mean
execution is 16,540 ms.** The planner believes this is trivial. That is the
`issues/090` / `issues/119` correlation underestimate, surviving a correctly
configured pair-MCV at target 1000, exactly as predicted.

---

## The fix, 2026-09-01

**1. The connections set their own fences.** `maintenance_conn_options()` in
`maintenance_job.py` returns a libpq `options` string, applied at CONNECT time
rather than by a later `SET` so there is no window carrying the inherited value.
Both callers use it — `_make_sync_connection` and `auto_analyze._sync_analyze`,
the latter importing it rather than duplicating so the two cannot drift.

Verified against production, same credentials, with and without:

    without options  statement_timeout='1min'   lock_timeout='10s'    (inherited)
    with    options  statement_timeout='15min'  lock_timeout='1min'   source=client

So a libpq `options` string does override an `ALTER DATABASE SET`, which was the
open question — `lock_timeout=10s` comes from the database, not the parameter
group, and it is overridden too.

**Bounded (15 min), not 0**, and the reasoning is at the call site: zero is
defensible because no caller waits on a VACUUM, but it removes the only thing
that would stop a pathological run. A generous bound fails loudly once instead
of silently every six minutes. `VG_MAINTENANCE_STATEMENT_TIMEOUT_MS` and
`VG_MAINTENANCE_LOCK_TIMEOUT_MS` override per deployment.

**2. A partial run is no longer called complete.** `_log_table_op_outcome`
logs `VACUUM INCOMPLETE: space=… 6/7 tables` at ERROR when the loop lost a
table, and the result dict carries `tables_attempted` beside `tables_vacuumed`.
Consequence 1 above — 244 clean-looking completions a day — cannot recur.

**3. Staleness takes the LATER of the two timestamps.** `_latest(a, b)` replaces
`row["last_vacuum"] or row["last_autovacuum"]` (and the analyze pair). The `or`
returned the manual timestamp whenever it was non-NULL, so a table autovacuumed
perfectly well but last touched by hand weeks ago read as weeks stale forever.

Consequence 2 — one space taking 244 of 275 VACUUM picks — should resolve on its
own once the VACUUM actually completes and `last_vacuum` advances. **Not
separately verified**; worth watching after deploy.

## What is still NOT fixed here

The `lock_timeout = 10s` on the **write path** is untouched. The override above
is scoped to maintenance connections; `ALTER DATABASE vitalgraphdb SET
lock_timeout` still applies to application connections, and the
`update_subjects_graph` failures at 10.017 s are unchanged. That is a database
setting and a separate decision.

The per-space aggregation still takes the OLDEST table's timestamp, so one
genuinely stuck table can still speak for a whole space. With the timeout fixed
there should not be one, which is why this was left rather than changed.

Full `tests/unit` passes, including
`tests/unit/test_maintenance_exclusions.py` and
`tests/unit/test_maintenance_stats_integrity.py`.
