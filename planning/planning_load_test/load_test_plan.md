# VitalGraph Service Load Testing

**Status:** Implemented (`load_test_scripts/`).
**Goal:** exercise the running VitalGraph HTTP service under concurrent load — end-to-end through the API + client + SPARQL→SQL pipeline + Postgres — to measure latency percentiles and throughput, and to validate the P1–P3 performance work *as a user experiences it* (not just at the SQL layer).

## Why a service-level load test

The `tests/performance/` gates prove complexity class and buffer counts at the SQL layer. This complements them by hitting the **whole stack** the way a client does:

```
Locust user → HTTP (/api/…) → FastAPI endpoint → SparqlSQLSpaceImpl → SPARQL→SQL → Postgres 18
```

It surfaces things the SQL gates can't: auth/serialization overhead, connection-pool behavior under concurrency, JSON (de)serialization of VitalSigns objects, and real p50/p95/p99 latency under mixed read/write load.

## Driver: asyncio + the official client (not Locust)

The cardiff test this was adapted from uses **Locust**, whose users are gevent greenlets and which monkey-patches the process with gevent. `VitalGraphClient` is **asyncio-native** (aiohttp) — calling it from a gevent greenlet needs a per-greenlet asyncio bridge, which adds event-loop/thread-pool contention and distorts the latencies you're trying to measure. (That's why the cardiff test hand-rolled a *sync* HTTP client instead of using the async client.)

So this harness uses **the VitalGraph client only**, driven by a small **asyncio concurrency driver** (`load_test.py`): N concurrent `VitalGraphClient` "users" via `asyncio.gather`, each looping weighted random operations, with per-operation latency percentiles + throughput. Native async, no bridging — the numbers reflect the real client→service path. Trade-off vs Locust: no live web dashboard (metrics are printed at the end), which is acceptable for a latency-focused test.

## Target & auth

- **Service:** the VitalGraph app (dev on `http://localhost:8001`, vg-test docker on `:8002`).
- **Auth:** `POST /api/login` (form-encoded `username`/`password`, OAuth2 form) → JWT; sent as `Authorization: Bearer <token>`. (This is the difference from the cardiff wrapper, which uses `/authenticate` + api-key.)
- **Backing store:** local Postgres **18** (the RDS-matching version).

## Operations exercised

Weighted `VitalGraphClient` calls (the client picks the right routes/params — e.g. `list_kgentities`, not a hand-written `/api/graphs/kgentities?graph_id=…`):

| Operation | Client call | Weight |
|---|---|---|
| List entities (random page size) | `kgentities.list_kgentities` | 30 |
| Get entity | `kgentities.get_kgentity(uri=…)` | 25 |
| Get entity + graph | `kgentities.get_kgentity(…, include_entity_graph=True)` | 15 |
| List entity frames | `kgframes.list_kgframes(parent_uri=…)` | 10 |
| List spaces | `spaces.list_spaces` | 5 |
| List graphs | `graphs.list_graphs` | 5 |
| **Update a frame slot** | `kgframes.update_kgframes` | 5 (write) |

`--read-only` drops the write op for a safe read-only profile.

## Load profiles

- **smoke** — 1–2 users, 30 s (sanity).
- **read** — 20 users, read-only tags, 2 min (read-scaling behavior).
- **mixed** — 20 users, read+write, 2 min (concurrent-write correctness via the verify step + p95 under contention).
- **soak** — 5 users, 15 min (leak/steady-state check).

Driven by Locust (`-u`/`-r`/`-t`), headless with CSV output, or the interactive dashboard.

## Test data

- Space `kg_load_test`, graph `urn:kg_load_test_graph`, **20 organization entities**, each with a `CompanyInfoFrame` (`IndustrySlot`, address, founded, employees) — the same shape the cardiff test uses, so the write task can flip an `IndustrySlot` text value and verify it.
- The **entity/frame generator** (`kg_test_data.py`, `organizations.py`) is **copied from the cardiff repo into `load_test_scripts/data_gen/`, which is gitignored** (it's borrowed test data, not ours to vendor).
- `setup.py` creates the space + entities **via `VitalGraphClient`** (this repo's own client — the sanctioned space-manager path), and writes the resulting entity URIs into `load_test_data.py` for Locust to consume. `--cleanup` deletes them.

## Metrics / what "good" looks like

Locust reports p50/p95/p99 and req/s per named request. Rough local expectations on PG18 (single machine, not RDS): list/get entity p95 well under a few hundred ms; the write path (multi-step read→update→verify) higher but bounded; **zero verify-mismatch failures** under concurrent writes (the write task distinguishes "another user overwrote" from "write lost"). Absolute numbers are machine-dependent; the value is the **percentile shape under concurrency** and regression tracking across changes.

## How to run

See `load_test_scripts/README.md`. In brief:
```
python load_test_scripts/setup.py                      # seed space + 20 entities
python load_test_scripts/load_test.py -u 5  -t 30 --read-only   # read-only smoke
python load_test_scripts/load_test.py -u 20 -t 120             # mixed read/write
LOAD_TEST_ENV=test python load_test_scripts/load_test.py -u 10 -t 30   # target :8002
```
`load_test.py` prints per-operation p50/p95/p99 + req/s at the end.

## Follow-ups

- Add a **query-endpoint** task (the high-cardinality slot-value KG query) to load-test the exact pattern P1's extended-statistics fix targets.
- Point at the **partitioned** schema variant once a space is migrated, to compare graph-scoped read latency partitioned vs not under load.
- Wire into the P4 read-topology work (replica routing) to measure read-scaling with real concurrency.
