# Whole Subsystems Have No Performance Bench

## Status: OPEN — the top row is CLOSED 2026-09-14, three remain

**SPARQL UPDATE / DELETE is benched** (`15d53122`,
`tests/performance/test_delete_throughput.py`,
`write.delete.concrete_vs_deferred`, baselined in `ingest.json`).

A delete is THREE costs and only the first is visible to the caller, so the
bench takes all three — a change that speeds up the caller's path by deferring
more work to the sweep is not an improvement, and measuring either half alone
would report it as one. `deferred_share` is the metric that moves when that
happens.

    concrete_quads_per_sec      2,048     DELETE DATA, subjects enumerable, syncs inline
    where_bound_quads_per_sec   6,251     DELETE WHERE, marks the space and DEFERS
    orphans_before_sweep        1,000     what the deferral leaves behind
    sweep_s                     0.019     O(edge table) — 181s at 4.98M rows (issues/079)
    deferred_share              0.039

The caller's path is 3x faster precisely because it defers. That is the
relationship worth watching, and neither number alone shows it.

It asserts what it measures — zero orphans after the concrete path, the space
MARKED after the WHERE-bound one, zero after the sweep — so a bench that
silently stops deleting fails rather than reporting a fast number for doing
nothing.

### The tier split was wrong, and fixing it made write benches cheap

Closing one row cost a 46-minute promotion, which was the wrong shape. Measured
per file, 35 of those 46 minutes were ONE file:

    test_paging_fence_covers_every_shape   >=1800s (capped)
    test_covering_benchmark                  291s
    test_ingest_throughput                   124s
    test_per_write_curve                     102s
    test_growth_curve                        101s
    test_partition_pruning                    25s
    test_delete_throughput                    15s
    test_frame_nesting_hops                    8s

And the sweep is NOT A WRITE BENCH. The file has no INSERT, CREATE, DELETE or
TRUNCATE at all — it reads pre-seeded fixtures and runs EXPLAIN probes, and its
runtime is deliberate TIMEOUTS (20 s probe, 120 s retry, per parametrisation).
It carried `ingest_bench` under a "builds its own data" reading that is not true
of it, and parked there it set the price of every write bench.

The split is now on two axes rather than one (`a429435f`):

    query      read-only AND fast     266 tests   105 benches
    ingest     writes                  15 tests     7 benches
    coverage   read-only but SLOW      49 tests    48 benches

    write-tier promotion   46 min  ->  11 min

Zero overlap between all three baselines. A write bench now costs the write
tier, not the sweep — which is what makes the remaining rows worth writing.

### vector and geo are CLOSED 2026-09-14

`835ad340` (geo), `2590b8d1` (vector), baselined in `ingest.json`.

    geo.populate_and_search    1,164 points/s populated   17.9 ms search, 25 rows
    vector.index_and_search      317 vectors/s upserted     6.4 ms search, 10 rows

**The driver this file predicted was not needed.** `EntityQueryCriteria` carries
`geo_criteria` and `vector_criteria`, and `build_entity_query_sparql` -> sidecar
-> `generate_sql` works with NO app — verified before either bench was written.
The fixture was the whole cost, and there was none: zero `*_vec_*` tables and
162 `*_geo` tables all holding zero rows.

Both benches ASSERT BEFORE THEY TIME. An empty geo table or vector index answers
instantly, so a search-only bench against an unpopulated one reports a plausible
latency for matching nothing. Each checks the row count, that the generated SQL
touches `{space}_geo` / `{space}_vec_{index}`, and that rows came back.

Embedding is deliberately outside the vector measurement: `VectorCriteria` takes
a pre-computed `vector` literal rather than `search_text`, which would vectorise
server-side and drag an OpenAI call or a local MiniLM load into a perf run. The
number describes the INDEX, not a model.

**And the tier fix paid for itself immediately.** These two benches cost ONE
8m14s promotion. The delete bench alone cost 46 minutes before the coverage
sweep was moved out of the write tier.

### bulk export is CLOSED 2026-09-14

`1fdf7289`, `write.export.copy_round_trip`, baselined in `ingest.json`.

    export    1.014 s   587,979 quads/sec
    import   23.807 s    25,054 quads/sec
    import_over_export  23.5x   (28.2x on a separate run — 23-28x, stable in magnitude)

The RESTORE is 23-28x the export, and that ratio is the point: `export_space`
COPYs in one REPEATABLE READ snapshot, `import_space` COPYs back and then
RESYNCS the derived tables. Measuring export alone reports 588k quads/sec and
calls it the cost of a restore.

The source space is chosen, not defaulted: `sp_graph_rel_10k` (2.9M quads)
exceeded asyncpg's pool `command_timeout=60`, which fires in the DRIVER as a
bare `CancelledError` — the same cancellation that made the inline orphan
cleanup clean nothing in `issues/079`.

### fuzzy / text is BLOCKED on `issues/202`

Not deferred. Two of its three regimes do not finish in 15 seconds: a
SERVABLE six-character needle matching nothing is 3,290 ms warm on 10k and times
out on 100k, which is 5x slower than the two-character needle the index cannot
serve. A read-only query taking that long is a defect, not a tier-placement
question, so the bench waits rather than being written around a timeout.

### "entity-graph endpoint" is NOT an endpoint — corrected 2026-09-14

It is a FLAG on the KGQuery endpoint, and the distinction matters for whoever
benches it:

    route    POST /kgqueries                       (kgquery_endpoint.py)
    flag     KGQueryRequest.include_entity_graph   (kgqueries_model.py:92, default FALSE)
    path     _fetch_entity_graphs(...)             (kgquery_endpoint.py:848)
    sparql   build_entity_graph_collection_query() (kg_query_builder.py:479)

"Fans out 25-wide" means a page of 25 entities triggers a graph-collection query
each when the flag is set.

**It is CACHE-FRONTED** — `_entity_graph_cache`, invalidated through signals in
`vitalgraphapp_impl.py`. A bench that measures it warm measures the CACHE, not
the fan-out, and would look excellent while the path underneath rotted. That is
the same "fast number for doing nothing" trap the geo and vector benches guard
against with explicit assertions, and it has to be designed for here rather than
discovered.

Reachable from the perf tier without the app: the query comes from the same
builder the vector and geo benches already drive.

### What the remaining rows need

**Not all four are the same job.** All four surfaces have correctness tests, but
where they live decides the cost:

    fuzzy / text   integration  test_search_trigram_index, test_short_needle_probe_is_bounded
    bulk export    integration  test_bulk_export
    vector         API ONLY     13 api files, 1 integration (a text-search file that mentions it)
    geo            API ONLY      4 api files, 1 the same

Text and export are the "a `@pytest.mark.bench` and a `perf_record` call away"
case this file describes. Vector and geo are not: their correctness lives in the
API tier, so benching them in the perf tier needs a driver against
`vitalgraph/vectorization/` rather than an existing test to hang a mark on.

One bench required a full ingest-tier promotion (46 minutes) to baseline,
because `test_every_declared_bench_is_in_a_baseline` cannot distinguish a NEW
bench from a VANISHED one — both are declared-but-absent — and an unbaselined
bench detects nothing. That is correct discipline, not a flaw, but it means the
two remaining justified rows (**concurrency at scale**, **entity-graph
endpoint**) should be written TOGETHER and share one promotion rather than
taking one each.

The bottom four (vector, geo, fuzzy/text, bulk export) are still deliberately
not written: per the rule below, the case has to be "a regression here would
ship silently", and no incident has made it.

## Original filing: Ranked, not enumerated — deletes first.

**Related:** `performance_regression_tracking_plan.md` R6 (write/update parity,
this is that item re-counted), `unexplored_performance_surface.md` §1,
`planning/planning_performance/perf_coverage_gaps_plan.md` §5

## The gap

| surface | correctness tests | bench cells | |
|---|---|---|---|
| writes / ingest | yes | **3** | `copy_speedup`, `e2e_speedup`, `quads_per_sec` |
| SPARQL UPDATE / DELETE | yes | **0** | deletes touch the derived tables; that rebuild is exactly the cost that has surprised us before. **Highest value.** |
| concurrency at scale | driver exists | **11, BASELINED 2026-09-14** | `baselines/load.json` @ `cd516f89` — 10 users/60s read-only, 28.2 req/s, 0 failures, 10 per-operation cells plus throughput |
| entity-graph flag | yes | **8, BENCHED 2026-09-14** | `query.entity_graph.fanout` on `lead_nurture_grouped` — the ONLY fixture with `hasKGGraphURI` at scale. Steady state: base 667ms, cold 861ms, warm 874ms, fan-out delta **193ms** for 18,653 quads. The fan-out is NOT the expensive part |
| vector / semantic search | yes | **1, DONE** | `vector.index_and_search` in `ingest.json` — HNSW over a populated index (it builds the index, so ingest tier) |
| geo | yes | **1, DONE** | `geo.populate_and_search` in `ingest.json` — both halves, because an empty geo table answers instantly and benches nothing |
| fuzzy / text search | yes | **1, UNBLOCKED 2026-09-15** | `issues/202` is fixed, so two of the three regimes now finish quickly. `query.kgquery.text_needle_regimes` records all three (empty 0 buffers, matching 7,516, unservable 1,445,968) — the values, not just the ordering |
| bulk export | yes | **1, DONE** | `write.export.copy_round_trip` in `ingest.json` |

### The entity-graph fan-out, once actually measured — 2026-09-14

Benched in `tests/performance/test_entity_graph_fanout_bench.py`. Three
corrections to what this row said before, all of them found by measuring:

**1. It is not 25 queries.** `_fetch_entity_graphs` does not call
`build_entity_graph_collection_query` at all. It filters the page against the
cache and issues ONE SPARQL query for the misses, with a 25-element `VALUES`
clause and a two-branch UNION. Branch 2 (`?s hasKGGraphURI ?entity_uri`) is the
half that collects frames and slots, and is the product value of the flag.

**2. The obvious fixture measures nothing.** `sp_lead_synth_100k` (50.5M quads)
has ZERO `hasKGGraphURI` quads, so branch 2 matches nothing there and the flag
returns 8 quads per entity instead of ~745. A bench written against it would
have reported the fan-out at ~100ms — fast, green, and measuring a query that
did no work. Only `lead_nurture_grouped` (74.5M quads, 10.65M `hasKGGraphURI`)
carries the shape.

**3. The 3.5-second figure was FIRST TOUCH, not the fan-out.** Two regimes,
and conflating them was wrong by a factor of twenty:

    first touch (PostgreSQL buffers cold)  base 0.7-1.2s  cold 3.2-4.3s  warm ~1.0s
    steady state (buffers warm)            base ~0.8s     cold 0.86-1.14s  warm ~1.0s

In steady state the fan-out adds **193ms** for 18,653 quads. That is not the
problem this row was filed to catch.

**The baseline records 2,144ms, not 193ms**, and both are correct. The tier
run follows a container restart, so the 74M-quad working set is not resident
and the bench lands nearer first touch. The base query barely moves across
the two regimes (667 -> 692ms) while the fan-out moves elevenfold, so the
ratio swings 1.3x -> 4.1x too. `fanout_cold_ms` is therefore a
regime-dependent absolute: a large swing between runs is buffer state, not a
regression, and the gate is a 6x bound on the shape rather than a threshold
on the milliseconds.

**What the numbers actually indict is the BASE query**: 667ms to return a
25-entity page from a 74.5M-quad space with no graph attached at all. That is
the same finding as `issues/203` from the other direction — the expensive thing
is the entity paging query, not the decoration on top of it.

**The cache DOES pay for itself, and my earlier reading here was wrong.**
Measured 2026-09-15 against `/health/cache`, on offsets no run had touched:

    offset 31337   cold 15,924ms -> repeat 1,041ms    25 misses then 25 hits
    offset 44444   cold  4,510ms -> repeat 1,042ms    25 misses then 25 hits
    offset 58888   cold  2,996ms -> repeat   865ms    25 misses then 25 hits

Clean 25-miss/25-hit pairs every time, so there is NO key mismatch — the
`_effective_graph = graph_id or "default"` suspicion recorded here earlier is
disproved. Cumulative hit rate on the instance was 45.5% (125 hits / 150
misses), and the entry count matched the fan-out bench exactly (150 = 6 pages
x 25), which is what identifies those hits as the bench's own.

The earlier conclusion — "warm is slower than cold, so the cache saves
nothing" — was an artefact of WHICH PAGES were measured. Offsets 1000-3000 had
already been pulled into PostgreSQL's buffers by previous probes, so "cold"
there was only app-cache-cold and cost about the same as warm. On a page that
is genuinely untouched the cache is worth 2 to 15 SECONDS.

**Which makes the real finding the cold fan-out, not the cache.** A read-only
entity-graph page over this 74.5M-quad space costs 3.0-15.9s on first touch,
returning ~18,600 quads — roughly 1,200 quads/second at the worst offset, which
is the signature of scattered random reads rather than an index walk. The cache
hides it completely on re-access, which is why nothing has ever flagged it, but
every FIRST access to an entity pays it and production does that constantly.
That is the standing rule's territory: no read-only query should take that
long, and if it does the method is wrong.

### 2026-09-15 — what closing 202 and 203 changed here

**The text row is no longer blocked.** `issues/202` is fixed: a servable needle
matching nothing is now provably empty and costs 0 buffers against 1,681,156.
The ordering test that had been failing records all three regimes' VALUES, which
is what this issue asked for — it drifted by orders of magnitude while the test
stayed green, because an assertion between three regimes holds until they cross.

**The load baseline moved, and not by a little.** `issues/203` closed, so the
numbers recorded above for the concurrency row are stale by design:

    kgquery_sorted     p50  338 ms -> 8.2 ms
    kgquery_page1      p50   37 ms -> 5.6 ms
    kgquery_deep_page  p50   45 ms -> 5.7 ms

Re-promoted at `23348a64`. The caveat recorded above — that the driver's
criteria omit `slot_class_uri`, so both kgquery cells measure the general
pipeline — NO LONGER APPLIES: the driver now sends it, which is why the
*unsorted* case improved 6.5x as well. The cells measure the fast paths now, and
the earlier numbers should not be compared against these.

**A dependency the baseline now carries.** `kg_load_test` needs an
`{space}_entity_prop_sort` table for the sorted path to serve. Rebuild that
space without it and `kgquery_sorted` silently returns to ~338 ms — a baseline
regression with a DATA cause and no code change, which is the hardest kind to
read from a comparison alone.

### What the load baseline may be gated on — measured, not assumed

Two runs of the SAME command against the same data, back to back, compared
against each other:

    p50_ms            within ~20%   (37.4->42.6, 23.7->28.7, 9.9->10.9, 4->4.4)
    requests_per_sec  within ~3%    (27.5 vs 28.2)
    p95_ms / p99_ms   up to +400%   (list_spaces p95 8.7->43.7, sparql_select 21.2->102.7)

The tails are not signal at this scale: several operations draw only 43-85
samples in a 60s run, so one scheduling hiccup moves p95 by a factor of five.
Gate on `requests_per_sec` and on `p50_ms` for the high-count operations, with
a wide band; leave p95/p99 informational until the sample count justifies
otherwise. This is the same trap `issues/188` describes for the 91 numeric
threshold rules — a threshold set from a single observation flaps, and a
flapping gate gets ignored, which is worse than no gate.

The other 48 cells in `ingest.json` are the status-only fence-coverage cells
(`76a9e1d8`), which are deliberate coverage detection rather than measurements.
So the ingest tier's measured surface is three numbers.

## Rules for closing it

Each row is a `@pytest.mark.bench` and a `perf_record` call away from an
existing correctness test — two lines, per the suite README. The real cost is
the fixture and the promotion.

**Do not add a bench per subsystem for completeness.** The argument for each row
has to be "a regression here would ship silently". For the bottom four that case
has not been made with an incident yet. Write them when one of them costs a day.

Per the convention in `issues/README.md`, each surface closed gets its own
entry rather than being struck off this table silently.
