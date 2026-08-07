# Performance suite — running it, recording it, comparing it

The process that answers *"did this change make anything slower?"*
Design and rationale: `planning/planning_performance/performance_regression_tracking_plan.md`
(what to measure) and `scaling_test_strategy.md` (why plans/counters rather than wall-clock).

## The one command

```bash
# run against a clean, ephemeral PG 18 and compare to the promoted baseline
./scripts/run-perf-tests.sh --baseline main -- tests/performance -m performance

# record only (no comparison) — e.g. to capture a "before" point
./scripts/run-perf-tests.sh --record -- tests/performance -m performance

# make a reviewed run the new reference
./scripts/run-perf-tests.sh --promote main -- tests/performance -m performance
```

The runner brings up `docker-compose.test.yml` (PostgreSQL 18 on :5433, Jena sidecar
on :7071, **no volumes → clean DB every run**), initializes the admin schema,
runs pytest, then compares and tears down. `--skip-build` reuses the image;
`--persist` keeps the PG data volume so a large loaded dataset survives runs.

Useful flags: `--no-down` (leave the stack up to poke at it), `--reset-data`
(wipe the persisted volume), `-- <pytest args>` (anything after `--` goes to pytest).

## Before/after comparison — the "has the last month regressed anything?" workflow

```bash
git stash                                    # or: git checkout <pre-change-commit>
./scripts/run-perf-tests.sh --record=/tmp/before.json -- tests/performance -m performance
git stash pop
./scripts/run-perf-tests.sh --skip-build --record=/tmp/after.json -- tests/performance -m performance
python scripts/perf_compare.py /tmp/after.json --baseline /tmp/before.json
```

`perf_compare.py` also does trends over the recorded history:

```bash
python scripts/perf_compare.py --trend query.fastpath.typed_subject_page --metric shared_buffers
```

## What gets recorded

Runs land in `tests/performance/results/` (git-ignored — machine-local
measurements) plus a `history.jsonl` index. Baselines land in
`tests/performance/baselines/` and **are** committed.

Each run carries the environment it was measured in — git commit + dirty flag,
PG version and the settings that move plans (`shared_buffers`, `work_mem`,
`effective_cache_size`, `random_page_cost`, …), machine, and runner class
(`vg-test-docker` vs `host-pg`). `perf_compare.py` warns when any of these
differ, because a comparison across environments is not meaningful.

Each bench records structural metrics first (shared buffers, rows examined,
temp spill, heap fetches, plan node types, indexes used) and wall-clock last.
**Structural metrics gate; wall-clock is report-only** — laptop timings are noisy
and don't extrapolate, so gating on them produces flaky builds, not signal.

## Bench kinds

| kind | Measures | Gated on | Fixture |
|---|---|---|---|
| `query` / `write` (default) | EXPLAIN plan shape, buffers, rows, spill | shape exactly, counters ±15% | `perf_conn` / `perf_pool` |
| `api` | REST wall-clock per query, plus result counts | result counts; `wall_ms` report-only | `perf_client` |
| `load` | p50/p95/p99, throughput, failures | throughput −20%, failures > 0; percentiles report-only | — (load driver) |

**API benches** need the app running and are configured from the same
`VG_TEST_*` family as everything else — `VG_TEST_API_URL` (default
`http://localhost:8002`), `VG_TEST_API_USER`, `VG_TEST_API_PASSWORD`. They
auto-skip when the server is unreachable, the same way the SQL benches skip
without PostgreSQL. Deliberately *not* the client's own `LOCAL_CLIENT_*` vars,
so a suite can't silently measure the dev server on :8001.

**Every API bench asserts a result count.** A query that stops matching rows has
regressed no matter how fast it got — the lead suite once reported ten queries
as passing-and-fast while they matched nothing.

**Load runs** come from the standalone driver, which emits the same record
format:

```bash
LOAD_TEST_ENV=test python load_test_scripts/load_test.py \
    -u 20 -t 120 --read-only --record tests/performance/results/load.json
python scripts/perf_compare.py tests/performance/results/load.json --baseline main
```

Load records carry their run parameters (users, duration, ramp, think time) and
`perf_compare.py` refuses to compare runs whose parameters differ — a p99 from
20 users is not comparable with a p99 from 5. Their `runner.class` is the API
target (`api-localhost:8002`), not the PostgreSQL stamp, since that is what a
load run actually measured.

Latency stays **report-only** until we know the noise floor. Two consecutive
identical 15s runs moved a p99 from 311ms to 27ms — gating on that today would
produce flakes, not signal.

## Adding a bench to an existing test

Two lines: mark the test, then record.

```python
@pytest.mark.bench("query.fastpath.typed_subject_page")
async def test_fast_page_is_o_page(perf_conn, perf_record, ...):
    plan = await assert_plan(perf_conn, sql, ..., max_shared_buffers=8_000)
    perf_record(plan=plan, dataset="wordnet_frames")
```

`perf_record` derives the metric set from the plan via the harness extractors.
For non-plan measurements pass metrics directly:

```python
perf_record(kind="write", metrics={"copy_speedup": 6.1}, dataset="synthetic:400k")
```

Recording is inert unless `VG_PERF_RECORD` is set, so tests behave normally in a
plain pytest run.

## Two kinds of threshold — and why both exist

- **Inline assertions** in the test (`max_shared_buffers=8_000`, `MIN_COPY_SPEEDUP=5.0`)
  are *absolute floors*: catastrophic-regression detectors that hold at any scale.
  They fail the build on their own.
- **The baseline** (`tests/performance/baselines/main.json` + `thresholds.toml`)
  is the *drift detector*: it compares against what was actually measured, so a
  40% degradation that still clears the floor is caught.

Gating rules live in `thresholds.toml`: plan shape must match exactly, work
counters allow +15% before failing, throughput −20%, wall-clock is report-only.

## Coverage is a tracked metric, not a footnote

`conftest.py` skips the whole suite when PostgreSQL is unreachable, and several
benches skip when their dataset isn't loaded. **A run can report green having
measured almost nothing.** So skips are recorded, and `perf_compare.py` *fails*
when a bench present in the baseline is skipped or missing in the run.

On a clean `vg-test` stack only the self-seeding benches run. To load the
realistic datasets and close the hole:

```bash
./scripts/run-perf-tests.sh --seed-data --baseline main -- tests/performance -m performance
```

`--seed-data` layers `docker-compose.test.data.yml` and implies `--persist`.
**The load happens entirely inside the stack:** the datasets are bind-mounted
into the containers at `/data/test_data` and `/data/internal_data`, the loader
runs in the app container (which already has the vitalgraph package), and it
writes to the stack's own PostgreSQL at `postgres:5432` over the compose
network. No host Python environment is involved and nothing streams from the
host. The mount is also present on the `postgres` container so a future loader
can use server-side `COPY ... FROM '/data/...'`.

The seeder is idempotent — a space that is registered and already holds quads is
skipped — so only the first run pays the load cost. By hand:

```bash
docker compose -f docker-compose.test.yml \
               -f docker-compose.test.persist.yml \
               -f docker-compose.test.data.yml \
  exec -e VG_TEST_PG_HOST=postgres -e VG_TEST_PG_PORT=5432 \
       -e VG_TEST_PG_PASSWORD=testpass \
  vitalgraph python /app/scripts/perf_seed_data.py --dataset wordnet
      # ... --max-triples 2000000   fast subset (see the warning below)
      # ... --force                 reload
```

`scripts/` is mounted into the app container, so the seeder can be edited and
re-run without rebuilding the image.

| Dataset | Source | Feeds |
|---|---|---|
| `wordnet` → `wordnet_frames` | `test_data/kgframe-wordnet-0.0.1.nt` (1.3 GB, ~7.0M quads) | `query.fastpath.*` |
| `lead` → `space_lead_dataset_test` | `internal_data/lead_test_data/*.nt` (100 files, 45 MB, ~265K quads) | `query.covering.graph_scoped_scan_index_only`, `query.stats.correlated_leaf_estimate` |

The source files are gitignored and machine-local, so these benches still cannot
run in CI — `--seed-data` closes the hole locally, not on a fresh clone. A
dataset whose sources are missing is reported and skipped rather than failing
the run.

The lead dataset is imported straight from the `.nt` files. The usual loader
(`test_scripts/vitalgraph_client_test/test_sparql_sql_lead_dataset.py`) drives
the REST API and derives extra structure, so it produces a slightly larger space
(~265K quads vs ~193K here). Both carry the predicates the benches query
(`hasKGEntityType`, `hasBooleanSlotValue`); absolute counts differ, which is why
the baseline must be re-promoted if you switch loaders.

**Orphaned tables.** A persisted volume accumulates per-space tables from
deleted spaces — tables present, no `space` registry row. The import then fails
on `graph_space_id_fkey`, and `SpaceManager` refuses to fix it (its existence
check is table-based). The seeder detects this and restores the registry row.

**The backfill task must not touch benchmark spaces.**
`backfill_server_properties_task` stamps four server properties onto every
KGEntity — legitimate work, but on `wordnet_frames` that is ~439K quads added
over tens of minutes (~3,600 quads/minute observed with the app otherwise idle).
It is a long job, not a runaway one, but it changes the dataset *while a run is
measuring it*, so buffer counts drift and baselines stop comparing.

`docker-compose.test.data.yml` sets a per-space exclusion so the task skips the
benchmark spaces and keeps running normally everywhere else:

```yaml
- BACKFILL_EXCLUDE_SPACES=${BACKFILL_EXCLUDE_SPACES:-wordnet_frames,space_lead_dataset_test}
```

Confirm it took effect in the app log:

```
Backfill: skipping excluded space(s): space_lead_dataset_test, wordnet_frames
```

Related knobs: `BACKFILL_ENABLED=false` disables the task entirely,
`BACKFILL_BATCH_SIZE` (default 200), `BACKFILL_IDLE_TIMEOUT` (default 1800s).
The runner also stops the app container before pytest, so the exclusion is a
second line of defence for hand-run seeding.

### Two things the seeder does that are worth knowing

- **`vitaltype` is derived, not imported.** The `kgframe-wordnet` N-Triples
  files contain only `rdf:type` — no `vitaltype` predicate anywhere. But the KG
  fast paths filter on `vitaltype`, so a raw import yields a space where those
  queries match nothing. The seeder adds one `vitaltype` quad per `rdf:type`
  quad, reproducing the 1:1 shape the dev `wordnet_frames` space exhibits
  (1,536,485 of each). Absolute counts are therefore comparable to dev, but the
  derivation is ours.
- **Subsets are dangerous.** `--max-triples` takes a *prefix* of the file, and
  the entity records live late in it: a 400K-line prefix contains KGFrame and
  KGEntitySlot but **zero KGEntity**, so the KGEntity fast-page bench matched 0
  rows and passed every bound vacuously. `assert_plan(min_actual_rows=...)` now
  makes that fail instead — but prefer a full load for anything you intend to
  trust.

### Don't let the loaders point at the dev database

`vitalgraphimport` / `vitalgraphadmin` resolve `LOCAL_DB_*` from the project
`.env`, which pins `host.docker.internal:5432` — the **dev** server. Running
them without an override loads into dev, not the test stack.
`scripts/perf_seed_data.py` deliberately bypasses that config layer and connects
from `VG_TEST_PG_*` explicitly.

`query.covering.advantage_growth` is skipped for a different reason: it cannot
demonstrate its claim on the synthetic generator's data shape (the probe
predicate matches ~50% of the table, so the covering index is never chosen and
WITH/WITHOUT measure identically). It needs a predicate-cardinality knob on
`generate_scale_data` before it means anything — the skip reason in the test
carries the measured evidence.

## Known environment gotchas

- **`bs4` / `markdownify` must be installed** in the test env, or four
  `tests/unit` modules fail to import and abort the *entire* pytest session
  before any perf test runs. `pip install -e '.[dev]'` covers it.
- **The vg-test PostgreSQL runs stock config** (`shared_buffers=128MB`,
  `work_mem=4MB`). Plan shapes are measured against defaults, not the tuned
  parameter group from `rds_parameter_group_deploy.md` — fine for detecting
  drift, but don't read absolute numbers as production-representative.
- **Don't run the suite against the dev/host PG** expecting comparable numbers;
  it's a different environment class and `perf_compare.py` will say so.
