# Stop Building What Nothing Reads, And Prove It Under Realistic Load

## Status: OPEN. Two halves that belong together — remove work nothing consumes,
## then demonstrate the result holds while writes and jobs run CONCURRENTLY,
## which is the only condition under which the original timeouts appeared.

---

# PART 1 — FLAGS TO STOP BUILDING REDUNDANT THINGS

A run of performance firefighting added several derived structures in quick
succession. At least two of them cost work and return nothing.

## `{space}_entity_fanout` — built, indexed, never read

Every reference outside its own module: `resync_all` rebuilds it and reports its
row count, `sparql_sql_schema` creates it and an `idx_*_entity_fanout_top` index
for it, `drop_space` drops it. NO QUERY PATH READS IT. It is rebuilt in full on
every resync — "a periodic full rebuild, never incremental", by its own comment
— and consumed by nothing.

Either its reader was superseded by `edge_fanout` and the traversal-direction
work, or it was never written.

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
