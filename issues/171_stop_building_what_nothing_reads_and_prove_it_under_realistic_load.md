# Stop Building What Nothing Reads, And Prove It Under Realistic Load

## Status: OPEN. Two halves that belong together — remove work nothing consumes,
## then demonstrate the result holds while writes and jobs run CONCURRENTLY,
## which is the only condition under which the original timeouts appeared.

---

# PART 1 — FLAGS TO STOP BUILDING REDUNDANT THINGS

A run of performance firefighting added several derived structures in quick
succession. ONE of them provably returns nothing; a second looked redundant and
turned out to be a documented diagnostic, recorded below because the correction
matters more than the original claim.

## `{space}_entity_fanout` — NOT REDUNDANT. This claim was wrong.

Recorded because the correction is the useful part. It is true that no query
path reads this table — but that is DELIBERATE and documented, not an oversight.
`sync_entity_fanout.py` opens with:

    AN OPERATOR DIAGNOSTIC. NOT A QUERY-PATH INPUT. Decided 2026-08-15.
    Nothing in the SQL pipeline reads this table and nothing should start to
    without new evidence.

and goes on to record that the obvious planner use — choosing the emission shape
by the start entity's fan-out — was TESTED AND REJECTED on measured data: dedup
won 5 of the 6 hub cases, and the single loss needed a three-way conjunction on
one data point.

The cost is also small. Measured rebuild:

    sp_lead_synth_100k     276 ms
    wordnet_frames         761 ms
    lead_nurture_100k       24 ms

So there is nothing to reclaim and no flag worth adding. "Nothing reads it" was
the right observation and the wrong conclusion — a grep found the absence of
readers, and the module header already explained it.

## `component_intersect.py` — provably does not fire

Default OFF via `VG_COMPONENT_INTERSECT`, and measured on the shape it was
written for (the Nurture campaign query on a 53M-quad space): with the flag SET
and UNSET the generated SQL is BYTE-IDENTICAL — 5,220 and 6,356 characters for
the page and count forms respectively. It never reaches the SQL.

An apparent 6x improvement from enabling it was cache warming between
consecutive runs, not the flag. Flag-gated code that provably never fires is how
a dead path survives for months (`issues/144`).

## `{space}_edge_fanout` — worth measuring, not yet condemned

It fails with a NOT NULL violation on every import round trip (`issues/170`) and
nobody noticed until the warning cascade around it was fixed. A statistic whose
absence goes unremarked for that long should have to justify its rebuild. It IS
read, unlike `entity_fanout`, so this is a measurement question rather than a
deletion.

## What this part should do

  1. A flag per derived structure that can be skipped, DEFAULTING TO CURRENT
     BEHAVIOUR so the flag itself changes nothing. `VG_BUILD_ENTITY_FANOUT`,
     and the existing `VG_COMPONENT_INTERSECT`.
  2. MEASURE what each costs: resync wall-clock and bytes with and without.
     A flag with no measurement behind it is a preference.
  3. Flip the defaults on the evidence, and DELETE what stays off. A permanently
     disabled feature behind a flag is worse than no feature: it still has to be
     read, understood and maintained by everyone who meets it.
  4. `component_intersect` needs a decision, not a flag: make it fire and show a
     measured win, or remove it.

NOT to be flagged off: `rdf_stats` vs `rdf_value_stats` (equality on a small
value set vs ranges over a large one — complementary, `issues/090`),
`rdf_pred_stats` (rdf_stats is capped, so its rows cannot sum to a predicate
total), and the three structural tables, which are read by 11 / 3 / 7 modules.

---

# PART 2 — PROVE IT UNDER REALISTIC LOAD

The whole point. Every timing conclusion in this repository has been drawn from
a quiet database, and the production problem was never quiet.

## Why this is the missing test

`issues/161` measured ~110s of background analytics inside a three-minute window
while queries were being timed, and every conclusion drawn in that window was
unreliable. During this work an apparent 2x regression and an apparent 6x
improvement BOTH turned out to be contention or cache state rather than code.
A benchmark that only runs alone cannot tell you whether production is fast.

The failure we are trying to prevent is specifically a CONCURRENCY failure:
rebuild work holding locks or CPU while application queries wait. A restore
holding ACCESS EXCLUSIVE across a minutes-long derivation (`issues/168`) is
invisible to a serial benchmark and fatal in production.

## The shape of the test

Three workloads, concurrently, against the 53M-quad dataset:

    READ    a realistic mix of KG query shapes — the paging shapes, the
            criteria filters, the count forms — at production-like concurrency.
            These are the ones with measured targets (~20ms via the fast path,
            >90s via the fallback).
    WRITE   continuous ingest at a realistic rate, so the incremental
            derivations (edge, frame_entity, entity_slot_sort) are running in
            the caller's transactions throughout.
    JOBS    the maintenance probes and the analytics job on their real
            schedules — NOT disabled. `lead_nurture_100k` is currently in
            `VG_MAINTENANCE_EXCLUDE_SPACES` precisely so jobs do not perturb
            benchmarks, and that exclusion is what has to be lifted here: the
            question is what happens WITH them.

Assertions, in order of importance:

  1. ZERO timeouts and zero cancelled statements. Non-negotiable.
  2. p99 read latency under a stated bound, not the mean — the mean hides
     exactly the queue-behind-a-rebuild case this is looking for.
  3. No query exceeding a hard ceiling at any point in the run.
  4. Writes continue to make progress; a read workload that starves ingest is
     not a pass.

## Which jobs are NECESSARY, and this needs deciding first

Running everything is not realistic either. Analytics on the type distribution
is now 14ms (was 6,282ms) because it reads `rdf_stats` instead of the quads, but
`with_frames_count` in the same job is still 13-15s — a four-way join with
`COUNT(DISTINCT src_term.term_text)` — and is unaddressed. Deciding what belongs
in the concurrent set is part of this work, not a precondition to be assumed.

---

# PART 3 — THE RESTORE PROCESS THIS NEEDS

The test writes to the 53M-quad dataset, so it must be removable. Reloading 53M
quads per run is not viable.

## Use a DEDICATED GRAPH, not a URI convention

Write every test entity into its own context (graph), one per run. Removal is
then a single indexed operation on machinery that already exists:

    clear_graph(space_id, graph_uri)                   quads
    delete_entity_slot_sort_for_context(conn, sid, ctx) slot-sort rows

`context_uuid` is indexed on the quad table and is the leading column of
`idx_{space}_quad_ctx_pred`, so removal is bounded by what the run wrote rather
than by the size of the space. A URI-prefix convention would require scanning
53M rows to find what to delete, and would leave derived rows behind.

The entities themselves should still carry a run marker in a slot value, so a
failed cleanup is diagnosable and a stuck run's data is identifiable without
consulting the graph catalog.

## What cleanup must also remove

Not just the quads. A run leaves rows in `edge`, `frame_entity`,
`entity_slot_sort`, moves `rdf_stats`/`rdf_pred_stats`, and may leave a
`slot_sort_block`. Cleanup must return the space to a state where the alarms are
quiet — a leftover block is slow-and-correct but will be reported after 24h, and
an undeclared shortfall means the cleanup itself skipped a derivation.

VERIFY BY MEASUREMENT, not by assumption: after cleanup, quad count and
per-type coverage should match the pre-run values. Record both.

## Why not a snapshot restore

`bulk_export.export_space` / `import_space` round-trips a whole space, but
import TRUNCATEs and re-COPYs 53M quads and then rebuilds the derived tables —
minutes, under an exclusive lock. That is the right tool for a corrupted space
and the wrong one for a per-run cleanup. Graph-scoped removal is proportional to
what was written; a restore is proportional to the whole dataset.

---

# WHAT DONE LOOKS LIKE

  * every derived structure either has a reader or is gone;
  * a concurrent read/write/jobs run against 53M quads with zero timeouts and a
    stated p99, repeatable;
  * test data removable in time proportional to what was written, verified by
    comparing coverage and counts to the pre-run values;
  * the maintenance exclusion on the perf dataset LIFTED, because the test now
    depends on the jobs running rather than on their absence.

## The honest risk

This test will probably find things. The current evidence — 48 unattributed
performance-tier failures, several fixtures that were benchmarking the fallback
rather than the fast path, and a perf tier that has never run with maintenance
enabled — suggests the concurrent picture is worse than the serial one, not
equal to it. That is the reason to build it, and a reason not to schedule the
work as if it were a formality.


---

# FIRST RESULTS, AND WHAT THEY DO NOT YET COVER

Built: `tests/load/concurrent_load.py` (harness),
`tests/load/run_scoped_data.py` (graph-scoped write + verified cleanup),
`tests/load/test_concurrent_query_write_jobs.py` (opt-in via
`VG_RUN_LOAD_TEST=1`).

Against `lead_nurture_100k` — 53,457,500 quads, 4,064,500 slot-sort rows — with
`recompute_stats_tables` and the coverage probe running concurrently and
continuous ingest:

    queries 5932   ok 5932   timeouts 0   failures 0
    p50 81.0ms     p99 226.0ms            max 517.6ms
    writes 676     write_errors 0         seconds 57.5

Zero timeouts, and cleanup verified clean.

## The first version of this test measured the wrong window

It slept `duration_s` and stopped everything. Measured: 45s of readers against
jobs that ran 133.7s, so roughly TWO THIRDS of the job execution had no queries
observing it, and it reported p99 164.5ms for a window that was mostly quiet.

Readers now run until the jobs finish. p99 moved 164.5 -> 226.0ms on the same
workload, which is the size of the error and the reason the fix was worth
making. A contention test that stops before the contention ends measures the
recovery.

## GAP 1 — the worst case is still unmeasured

The two runs differed enormously in job cost: 133.7s and 57.5s. The difference
is cache warmth — the first pulled 53M quads through the stats aggregate cold,
the second found them in shared buffers.

So the EXPENSIVE run is the one whose readers did not cover the jobs, and the
run with full coverage had cheap jobs. "Cold jobs with full reader coverage" —
the actual worst case — HAS NOT BEEN MEASURED. It needs a cache-cold start
(restart PostgreSQL, or a large enough unrelated scan) before the run.

Do not read the 226ms p99 as the ceiling. It is the warm-cache number.

## GAP 2 — the writer does not exercise the derivations

`cleanup removed={'entity_slot_sort': 0, 'edge': 0, 'frame_entity': 0,
'quad': 676}` — the writer inserts raw quads directly, so nothing derived was
created and nothing needed removing.

That is honest for what it writes and it is NOT the production write path.
`add_rdf_quad`, `add_rdf_quads_batch` and `execute_sparql_update` all run
`sync_edge_table_after_insert`, `sync_frame_entity_after_edge_insert` and
`sync_entity_slot_sort_after_edge_insert` IN THE CALLER'S TRANSACTION — which is
exactly the write-side work that can contend with reads, and precisely what this
test was built to expose.

The current writer measures lock and I/O contention from inserts. Routing it
through `add_rdf_quads_batch` would measure the real thing, and the cleanup path
already handles the derived rows it would produce.

## GAP 3 — the job set is a guess

Two jobs run concurrently: the stats recompute and the coverage probe. The
analytics job is NOT in the set, and `with_frames_count` inside it is still
13-15s (a four-way join with `COUNT(DISTINCT src_term.term_text)`). Deciding
what production actually runs concurrently is listed above as part of this work
and has not been done — the current set is what was easy to invoke, not what was
argued for.

## GAP 4 — one space, three shapes, one machine

The shapes are the campaign count, the campaign page and an absent-value count.
That is the family the timeouts came from, not the family production runs. Read
concurrency is 3 per shape on a developer machine, which is not a production
concurrency level and cannot be extrapolated to one.


---

# THE REAL QUERY SHAPE: A PAGE LOAD IS A FAN-OUT, NOT A QUERY

Taken from the consuming portal application's backend — the routers that build
KG queries, and its `case_kgquery_*` diagnostic cases — rather than from shapes
chosen here. This corrects the mix described above.

## What a portal page load actually issues

`kgentity_list_impl.list_entities` has two paths, and the one the portal uses
for a list view is the second:

    include_entity_graph=False   ONE SPARQL query: a pagination subquery joined
                                 with a property fetch, count running
                                 concurrently.
    include_entity_graph=True    Count + URI query run CONCURRENTLY, then the
                                 entity graphs fetched IN PARALLEL via
                                 asyncio.gather — one per row.

The portal's entity router exposes exactly this as
`include_graphs` — "Include each entity's full graph in the response", commented
as avoiding N per-row fetches from the CLIENT. It does not avoid them from the
DATABASE; it moves the fan-out server-side and makes it concurrent.

Page sizes in the diagnostic cases: 5, 20 and 50.

## So one user action is 1 + 1 + N queries, N up to 50, N of them parallel

That is the shape this whole investigation should have been measuring. It is
also where a timeout would come from first: fifty concurrent entity-graph
queries per request, multiplied by concurrent users, against a connection pool
that does not grow.

## What the load test currently does instead, and why that is wrong

It issues independent, sequential reads: three find shapes and one entity-graph
open, each on its own connection, paced. That measures per-query latency under
background load. It does NOT measure:

  * the FAN-OUT — 20-50 graph fetches issued together and awaited together, so
    the user-visible latency is the SLOWEST of them, not the median;
  * POOL EXHAUSTION — the fan-out competes for connections with itself, and a
    pool sized for steady traffic behaves differently under a burst of 50;
  * the COUNT running CONCURRENTLY with the page query, which is what the
    implementation actually does.

A p99 of 226ms per query says nothing about a page load that awaits 50 of them.

## What the test should assert

The unit of measurement is the PAGE LOAD, not the query:

  * time from request to all N graphs returned, at p99;
  * with N drawn from the real page sizes (5, 20, 50);
  * with count and page issued concurrently, as the implementation does;
  * and the per-query numbers kept as a secondary diagnostic, because they are
    what tells you WHICH part of a slow page load was slow.

## NOT YET DONE

The load test has not been restructured for this. The numbers reported above
(zero timeouts, p99 226ms) are true for the shape they measured and do not
support a claim about page-load latency, which is the number the product has.


---

# THE WRITER NOW DERIVES, and it costs what you would expect

GAP 2 above is closed. The writer INSERTed raw quads, so none of the sync hooks
fired and the run measured lock and I/O contention only — proved by its own
cleanup line, `{'entity_slot_sort': 0, 'edge': 0, 'frame_entity': 0}`.

It now runs `sync_edge_table_after_insert`,
`sync_frame_entity_after_edge_insert` and
`sync_entity_slot_sort_after_edge_insert` on the subject just written, inside
one transaction, as every real write path does.

    before (raw quads)     p99 226 ms   676 writes   5,932 queries
    after  (deriving)      p99 543 ms   112 writes  23,859 queries

Zero timeouts either way. The write-side cost is now visible: p99 more than
doubled and write throughput fell six-fold, because each write holds its locks
across three derivations while readers run. That is the contention this test
exists to expose and was previously not measuring.

STILL NOT A REAL INGEST. The derivations run but produce no rows — a synthetic
subject of random uuids forms no shape any of them recognise — so this measures
the COST OF RUNNING them, not of writing derived rows. Closing that needs the
writer to construct a real entity/edge/frame/slot shape, which is more fixture
than test.

# PRODUCTION QUERY SHAPES: NOT AVAILABLE, and worth recording why

`pg_stat_statements` on the reachable production instance covers 2,033 hours
(85 days) and contains NO KG QUERIES AT ALL — the only statement matching the
quad, slot-sort or edge tables is an unrelated INSERT that merely mentions a
column name. Against a 26.8M-quad space.

Either the serving traffic goes to a second, newer instance named in the
deployment config but not reachable from here, or the KG on this instance is
loaded and not served. `issues/161` cites a 45M-quad space where this one holds
26.8M, which favours the first.

So the load test's query mix stays as it is: derived from the consuming portal's
routers and its `case_kgquery_*` diagnostics. That is second-best to production
telemetry and is what is available.

One thing the visit did establish: THE INSTANCE IS SHARED. Its heaviest
statement is an unrelated application's polling query at 35.7 hours cumulative
and a 60s maximum. Whatever the KG does there competes with that — concurrent
contention arriving from a direction this load test does not model, since it
assumes the database is otherwise ours.


---

# GAP 3 CLOSED, AND A FIFTH JOB NOBODY LISTED

The production job set, from where they are registered rather than from memory:

    db_maintenance      every 300 s     (5 minutes)
    space_analytics     every 86,400 s  (once a day)
    metrics_rollup      every 3,600 s   (hourly)
    import/export cleanup
    backfill_server_properties_task     NOT IN THE SCHEDULER AT ALL

The load test ran two PIECES of maintenance and no analytics. Analytics is now
in the set, scoped with `trigger_compute(SPACE)` rather than `run()`, which
would walk every space and measure the fixture set instead of the workload.

    without analytics    p99 543 ms   max 1,083 ms   0 timeouts
    with analytics       p99 627 ms   max 1,734 ms   0 timeouts

So the daily analytics pass costs ~84ms at p99 and pushes the worst query to
1.7s. Visible, and nothing times out.

## THE FIFTH JOB IS THE MOST ACTIVE ONE, and it is not a scheduler job

`backfill_server_properties_task` is a background COROUTINE started directly by
the app, not a registered job. It stamps server-managed properties onto
entities: 200 per batch, event-driven via a nudge from loaders and the import
endpoints, then polling every 0.5 s until a full cycle finds no work.

A 74M-quad bulk load leaves it 100,000 entities of work. Measured: it wrote
~57 quads/second continuously for the whole of a 464-second run and kept going
afterwards, adding ~293,000 quads in total before draining.

So the "production job set" this issue asked for was missing the job that runs
every half-second, while listing the ones that run every five minutes and every
day. Any benchmark taken against a freshly loaded space includes it, and nobody
would know: it logs at INFO under its own module name and writes to the quad
table like any other client.

## AND IT BROKE THE CLEANUP CHECK — correctly

`verify_clean` compared whole-space quad counts and failed a run with
`+26,400 left behind` when the run itself had written 142. The DETECTION was
right and the ASSERTION was wrong: other jobs legitimately write to a shared
space while the load runs, so demanding the space be byte-identical afterwards
fails for a healthy system, and a check that cries wolf gets deleted.

It now verifies what the run OWNS — its own graph, quads and slot-sort rows —
and reports space-wide drift as context rather than as a verdict. It also
resolves its own context instead of relying on `cleanup` having run, because the
cleanup-did-not-happen case is the one that most needs checking.

## What this leaves

Benchmarks taken while a load is draining are not baselines. The fixture is now
quiet (0 batches in two minutes, 74,465,500 quads settled), so figures from here
are comparable and the ones above are not, quite.
