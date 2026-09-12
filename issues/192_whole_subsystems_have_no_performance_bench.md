# Whole Subsystems Have No Performance Bench

## Status: OPEN. Ranked, not enumerated — deletes first.

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
