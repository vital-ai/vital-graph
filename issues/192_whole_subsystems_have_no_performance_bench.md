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

### What closing it cost, which is worth knowing before closing the next one

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
| concurrency at scale | driver exists | **0 in a baseline** | `load_test_scripts/load_test.py` emits the record format and `thresholds.toml` has `requests_per_sec` / `failures` rules — no load record has ever been promoted, so neither rule has ever fired. Configuration, not construction. |
| entity-graph endpoint | yes | **0** | the path a real client page fans out 25-wide |
| vector / semantic search | yes | **0** | |
| geo | yes | **0** | |
| fuzzy / text search | yes | **0** | |
| bulk export | yes | **0** | |

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
