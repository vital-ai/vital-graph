# The Perf Runner Class Is Taken From A Flag, Not The Database

## Status: FIXED 2026-09-12 (`7ddf8312`, `bd1dbe1f`). The class is derived from
## the database, per-space bytes are recorded, the residency property is
## asserted, and an incomparable pair is refused in one line.
##
## CONSEQUENCE: both committed baselines are now refused for comparison, which
## makes `issues/190` blocking rather than merely stale.

**Related:** `issues/055` (fixtures on one cluster, tests on another),
`issues/081` (a baseline promoted with no PG stamp),
`planning/planning_performance/perf_coverage_gaps_plan.md` §2

## The defect

`baselines/query.json` carries both of these, in the same stamp:

    "runner": { "class": "vg-test-docker-clean", "persist": false, "seeded": false }
    "stats":  { "fixture_tables": 260, "fixture_live_tuples": 126128097 }

A clean stack cannot hold 126M live tuples — `docker-compose.test.yml` mounts no
volume, so the DB is empty on every `up`. And 12 of that baseline's cells read
`wordnet_frames` and `space_lead_dataset_test`, which exist only on a seeded
persisted stack.

`runner_stamp()` derives the class from `VG_PERF_PERSIST` / `VG_PERF_SEEDED`
(`tests/performance/perf_record.py:91-97`), which only
`scripts/run-perf-tests.sh:135-136` sets. The committed baseline was promoted
from `/tmp/perf_fresh.json` — a direct `pytest` run, where both variables were
unset and therefore read as "clean".

## Why it matters

`runner.class` is what `compare_env` uses to decide whether two runs are
comparable at all. It is the one field that must not be guessable, and it is
currently the only one taken on trust from a flag rather than from the database.
A genuinely clean run and this seeded one are rated the same class.

## The aggregate stat is also the wrong stat

`fixture_live_tuples = 126,128,097` reads as reassuring — a stack that size
cannot be caching everything. It is the wrong number: **a query touches one
space.** Measured on the live vg-test stack 2026-09-12 (105 GB database,
`shared_buffers = 16GB`):

| fixture | total | vs `shared_buffers` |
|---|---|---|
| `sp_lead_synth_100k` | **35 GB** | 2.2x — exceeds memory |
| `wordnet_frames` | 5.9 GB | fits entirely |
| `sp_lead_synth_10k` | 3.4 GB | fits |
| `sp_graph_skew_2k` | 319 MB | fits |
| `sp_kg_rel` | 177 MB | fits |
| `sp_sql_lead_dataset`, `space_lead_dataset_test`, `sp_lead_dup` | 124-150 MB | fit |

One gated fixture is out-of-memory; every other one is comfortably resident,
including `wordnet_frames`, which carries the fast-path benches. 60 of the
105 GB is not fixture data at all.

Cache state cannot corrupt the GATED metrics, by design — `shared_buffers` is
hit + read, and `shared_read` is `report_only` with the measured evidence for
why. What resident data changes is **which plan wins**, and plan shape is the
primary gate.

## CORRECTIONS FOUND WHILE FIXING IT

**The table above is missing the largest fixture.** Measured with the per-space
recording this issue asked for: `lead_nurture_grouped` is **45.7 GB**, larger
than `sp_lead_synth_100k`'s 35 GB, and it is a gated prefix. So **TWO** gated
fixtures exceed `shared_buffers`, not one, and the "true by accident" framing
below understates it — the suite has more out-of-memory coverage than it knew.
Total seed-space data is 51.7 GB of the 105 GB.

**`fixture_live_tuples` cannot be used to detect a seeded stack, and my first
fix used it anyway.** It reads **0** on that live 105 GB stack: `n_live_tup` is
a statistics estimate, and 286 fixture tables there have never been ANALYZEd. So
the first version of the reconciliation called the seeded stack CLEAN,
reproducing the defect it was written to fix. Detection is by
`pg_total_relation_size` on the SEED-ONLY spaces, which needs no statistics —
and by those spaces specifically, because a clean run creates its own fixtures
as it goes, so the presence of fixture tables proves nothing.

That the aggregate tuple count is both the wrong stat AND unreliable is the
strongest argument for the per-space bytes this issue asked for.

## The fix

* Derive `persist` / `seeded` from observed state — `fixture_tables`,
  `fixture_live_tuples`, registration of the seed spaces — and keep the
  environment variables only as a cross-check, recording the disagreement rather
  than silently preferring either. A run whose flags say clean and whose
  database says seeded must be refused for promotion.
* Record **per-fixture bytes** (heap + indexes), not only the aggregate. A
  bench's comparability depends on the size of the space it read, and that
  number is recorded nowhere today.
* Assert the property instead of inheriting it: **at least one gated fixture
  must exceed `shared_buffers`**, checked, with the fixture named. It is true of
  exactly one space, and true by accident. `issues/167`'s pattern — a coverage
  marker replaced by an invariant — applied to size.
* `compare_env` should refuse a clean-vs-resident comparison in ONE line rather
  than emitting a coverage failure for each of the 103 fixture-dependent cells.
  Decided in the plan §8: one baseline, the resident tier; "clean" is a smoke
  mode, not a gated class.
