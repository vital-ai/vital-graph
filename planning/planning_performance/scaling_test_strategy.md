# Scaling Test Strategy: Proving Scale Locally, Validating It in the Cloud

**Status**: Strategy / planning
**Date**: 2026-07-18
**Companions**: `billion_scale_strategy.md` (the deployment tiers & levers), `100x_scalability_analysis.md`, `mitigation_details.md`, `kgentity_listing_render_plan.md` (worked examples of the verification style below).

---

## 0. The problem this solves

We want to build and prove scaling improvements **mostly on a laptop**, in small/medium "micro scenarios" that demonstrate a change scales — *without* standing up billion-row databases or expensive AWS infrastructure for every change. But some things (absolute latency at 1B rows, replica/shard topology, storage/IO ceilings, cost) can only be validated on real infrastructure with real data volumes.

So the strategy has two halves:

1. **Prove the *scaling behavior* (complexity class, plan shape, work-proportionality) locally** on small/medium data — this catches ~90% of regressions and validates most improvements cheaply.
2. **Validate the *constants* (absolute latency, throughput, cost, topology) on ephemeral cloud infra with large data** — rarely, at milestones, torn down after.

The guiding idea: **you don't need a billion rows to prove a query is O(page) instead of O(N).** You prove the *class* with plans and work-counters on medium data; you only need scale to measure the *constant*.

---

## 1. Principles

1. **Test the lever, not the machine.** Most improvements in `billion_scale_strategy.md` are about *complexity* (index-only scans, partition pruning, covering indexes, LIMIT push-down, COPY vs executemany). Complexity is provable on medium data.
2. **Prove behavior with plans + counters, not just wall-clock.** Wall-clock on a laptop is noisy and doesn't extrapolate. `EXPLAIN (ANALYZE, BUFFERS)` buffer counts, rows-examined-vs-returned, index-vs-seq scan, sort/hash spill — these *do* extrapolate and are deterministic.
   - *Worked example (this repo):* the KG-entity listing fix was proven by EXPLAIN showing **452,746 buffer touches → 464** (O(N)→O(page)) on the real 109K-entity `wordnet_frames` space — no billion rows required. See `kgentity_listing_render_plan.md` §2.2/§4.
3. **Scale the test as the work progresses.** Match test rigor to the deployment tier being implemented (§9). Don't build a sharding test harness before sharding exists.
4. **Ephemeral and cheap by default.** Cloud tests spin up, run, snapshot results, tear down. No always-on big infra.
5. **Reproducible datasets.** Deterministic generators + versioned reshaped open datasets, so a result is comparable across runs and machines.
6. **Every scaling fix ships with a scaling test** that would fail if the fix regressed (a plan-shape assertion, a work-counter bound, or a growth-curve check) — not just a correctness test.

---

## 2. The testing ladder

Five levels, from laptop-seconds to cloud-milestones. Each has a data-size band, an environment, a cost, and a purpose. Most work lives at **L0–L2**.

| Level | Data size | Where | Cost | Runs | Purpose |
|-------|-----------|-------|------|------|---------|
| **L0 — Plan/logic** | 0–10K | Laptop, unit tests | free | every commit / CI | Correctness + **plan-shape assertions**; SQL-generation and query-builder logic; no DB or tiny DB. |
| **L1 — Local integration** | 100K–2M | **Ephemeral `vg-test` Docker** (own PG) — or host PG | free | pre-merge / nightly | End-to-end through the real backend; EXPLAIN + index-usage assertions; correctness on realistic shapes. **This is where we are today** (`tests/integration/`, `wordnet_frames` 109K, `doc_test` 500 docs/4.5K segments). |
| **L2 — Scaled micro** | 10M–100M | **`vg-test` Docker** (tuned PG) on a beefy dev box | free–low | weekly / per-tier | Confirm the improvement *holds its complexity class* as data grows 10–100×; growth-curve fits; cold-cache behavior; ingest throughput. Still local. |
| **L3 — Cloud single-instance** | 100M–1B | Ephemeral AWS RDS (io2/gp3) | $$ (hours) | per-milestone | Validate **absolute** latency/throughput & PG config on real network-attached storage; verify the vertical-scaling tier; restore from snapshot to avoid re-loading. |
| **L4 — Cloud topology** | 1B–10B+ | Ephemeral RDS replicas / Aurora / sharded fleet | $$$ (hours–days) | rare, gated | Validate read-replica routing, sharding, Aurora Limitless, failover, and **cost** at true scale. |

**Rule of thumb:** a change is "proven to scale" once it passes **L0 + L1 plan/counter assertions and an L2 growth-curve check**. L3/L4 are for validating constants, config, topology, and cost — not for deciding whether an algorithmic change is correct.

### 2.1 The ephemeral local stack (`vg-test` Docker) — L1/L2 standard

L1/L2 run against the **self-contained `vg-test` Docker stack** (`docker-compose.test.yml`), **not** the developer's host PostgreSQL. It brings its own PostgreSQL container (`docker/test-pg`, **no volumes → clean DB every run**), the app, the Jena sidecar, and MinIO, on distinct ports (5433 / 8002 / 7071) so it runs alongside the dev stack. This gives **reproducible, version-pinned, clean-slate** runs — the same *spin-up → load → validate → tear-down* discipline we apply to cloud infra at L3, but free and local.

- **Cycle:** `docker compose -f docker-compose.test.yml up -d --build --wait` (the `--build` picks up the change under test) → load/seed the dataset into the container DB → run the suite → `docker compose ... down`. `e2e/run-tests.sh` already does this for Playwright; a parallel `scripts/run-perf-tests.sh` does it for `pytest -m "integration or performance"` (pointing at the container DB via `VG_TEST_PG_PORT=5433 VG_TEST_PG_PASSWORD=testpass VG_TEST_SIDECAR_URL=http://localhost:7071`).
- **Keep the image on the scaling-target PG version:** bump `docker/test-pg` to **PostgreSQL 18** so plan-shape assertions reflect the features we rely on (async I/O, skip-scan, UUIDv7, partition-pruning cost model). Host-PG runs remain a convenience fallback but are not the gate.
- **Why this matters for scaling tests:** clean-DB-per-run makes growth-curves and buffer-count assertions deterministic (no leftover bloat/cache state from prior runs), and building the image means every run tests the *actual updated code*, not a stale local server.

---

## 3. Proving scaling behavior *without* scale (the core techniques)

These let a laptop-sized test prove a billion-row property.

### 3.1 Plan-shape assertions (L0/L1)
Assert the *structure* of the query plan, which is size-independent:
- Uses an **Index Scan / Index-Only Scan**, not a Seq Scan, on the hot table.
- **No full sort** of the base relation before LIMIT (top-N or index-ordered only).
- **Partition pruning** selects one partition (post-Tier-3).
- Join type is the intended one (nested-loop-on-index vs hash), and no unintended `Materialize`.
- `Heap Fetches: 0` for index-only scans.

Implementation: run `EXPLAIN (FORMAT JSON)` and assert on node types / flags. A regression that turns an index scan into a seq scan fails the test at 100K rows just as it would at 1B.

### 3.2 Work-proportionality counters (L1/L2)
Assert that **work grows with the result, not the table**:
- `EXPLAIN (ANALYZE, BUFFERS)` **shared-hit/read** counts bounded by ~`O(page_size · depth)`, not `O(rows)`.
- **Rows Removed by Filter** and **actual rows** at each node ≈ the page, not the table.
- Temp-file (sort/hash spill) bytes = 0 for bounded operations.

*Example bound:* "a 25-row page must touch < 2,000 buffers regardless of entity count." This single assertion would have caught the entity-listing regression and is true at any scale.

### 3.3 Growth-curve / complexity-class check (L2)
Run the same operation at **3–4 data sizes** (e.g. 100K, 1M, 10M, 50M) and fit the cost metric (buffers, rows-examined, or warm latency):
- **Flat / log** → O(page)/O(log N): the improvement scales. ✅
- **Linear** → O(N): acceptable only for genuinely full-scan operations (aggregates, resync).
- **Super-linear** → a scaling bug; block it.

You extrapolate the class from small points; you do **not** need the endpoint size to know the shape.

### 3.4 Cold-cache simulation (L1/L2)
Cold buffer pool is where billion-scale pain shows (random heap I/O). Simulate locally:
- `DISCARD ALL` + evict via `pg_prewarm`-of-other-tables, or restart PG / drop OS cache, then run — compare `shared read` (disk) vs `hit`.
- This reproduced the exact "7s cold render" class we fixed, on 109K rows.

### 3.5 Cost extrapolation (no infra)
From per-operation counters (buffers read, rows, IOPS implied) + the AWS unit costs in `billion_scale_strategy.md` §10, **estimate** the infra cost/latency at target scale analytically before spending on L3/L4. Turns "how much will 10B cost" into a spreadsheet, validated occasionally against real L3 runs.

### 3.6 Micro-partition / micro-shard scenarios (L1)
Test partitioning/sharding *logic* with tiny numbers: create a table with **4 partitions of 10K rows** and assert pruning + partition-wise joins; create a **2-shard registry** and assert routing. The logic is identical at 256 partitions / 10 shards; only the constant differs.

---

## 4. What to test, per dimension

Mapping the four workload dimensions from `billion_scale_strategy.md` to concrete methods and levels.

| Dimension | What to prove | Method | Level |
|-----------|---------------|--------|-------|
| **Query performance** | Complexity class holds; index/plan shape; work ∝ result | Plan-shape + buffer-count assertions; growth curve; cold-cache | L0–L2 (class), L3 (latency) |
| **Write / incremental** | Per-write cost stays bounded as indexes grow; no O(N) sync | Insert latency vs table size curve; aux-sync buffer counts | L1–L2 |
| **Batch import/export** | Throughput (quads/s) and that it's COPY-bound not index-bound; index drop/rebuild wins | Load N at sizes; measure quads/s; compare executemany vs COPY; export streaming | L2 (throughput), L3 (billion-load wall-clock) |
| **Background jobs / maintenance** | Jobs are chunked, resumable, non-blocking; VACUUM/ANALYZE/resync cost scales sub-linearly per chunk | Run job on medium data; assert per-chunk bounded work + no long locks; measure lag | L1–L2 |
| **Topology (readers/writers/shards)** | Routing correctness; replica read-after-write handling; shard fan-out | Micro-shard/replica logic (L1); real replica lag + failover (L4) | L1 (logic), L4 (real) |

---

## 5. Datasets: sourcing realistic scale

We need datasets that (a) are large/expandable, (b) exercise **graph** query patterns (multi-hop, frames/slots, filters), and (c) map to the **KGEntity / KGFrame / KGSlot / KGDocument** model. Two families: **synthetic-with-scale-factor** (controllable) and **reshaped open datasets** (realistic).

### 5.1 Reshape open datasets into the KG model

A reusable **"reshaper"** maps an external dataset's schema onto our model:
- **Entities** → `KGEntity` (one `vitaltype`, name, type, properties).
- **Binary relations** → `KGFrame` (assertion) with source/dest **`KGSlot`** fillers, or a materialized `edge`.
- **N-ary / event / role structures** → `KGFrame` with multiple typed slots (the natural fit).
- **Text** → `KGDocument` (+ segments), as already built for Wikipedia.

Candidate open datasets (roughly small→large):

| Dataset | Nature | KG mapping | Scale | Why |
|---------|--------|-----------|-------|-----|
| **WordNet** (in use) | Synsets + lexical relations | synsets→entities, relations→frames | ~120K entities / ~285K frames | Already loaded; good L1 graph traversal. |
| **FrameNet** (in use) | Frames, roles, lexical units | direct: frames→KGFrame, roles→slots | 10s of K | Natural frame/slot fit; already have `framenet_kgtypes`. |
| **Wikipedia** (in use) | Articles | docs→KGDocument + segments | expandable | Document/segment scaling (built §ref kgdocument doc). |
| **DBpedia / Wikidata subsets** | Entities + relations (RDF) | entities→KGEntity, statements→frames/edges | 1M–1B+ (subsettable by domain) | Realistic, huge, domain-sliceable; Wikidata Truthy for edges. |
| **OpenAlex / MAG** | Papers, authors, citations, venues | papers/authors→entities; authorship & citation→frames w/ slots | 10M–250M+ nodes | Deep multi-hop (citation chains, co-authorship) — great for property-path/recursive-CTE tests. |
| **LDBC SNB** (recommended) | Social network: persons, forums, posts, comments, likes | persons/posts→entities; knows/likes/replyOf→frames+slots | **scale factors SF1…SF10000** (1GB→10TB) | Purpose-built graph benchmark with a **data generator** and defined query workloads at controllable scale — the closest thing to a graph TPC. |
| **SNAP graphs** | Social/web/road graphs | nodes→entities, edges→frames/edges | up to billions of edges | Cheap huge edge lists for pure traversal/join scaling. |
| **OpenStreetMap** | Geo features | features→KGEntity w/ PostGIS geog | region→planet | Geo + vector index scaling (we use PostGIS/pgvector). |

**Recommendation:** standardize on **LDBC SNB** as the primary *scalable* benchmark (scale-factor knob + realistic graph queries), plus **Wikidata/OpenAlex subsets** for realistic heterogeneity, keeping WordNet/FrameNet/Wikipedia for L1. Build one reshaper per source into a common intermediate (entities/frames/slots/docs), then reuse the existing bulk-load path.

### 5.2 Synthetic generators with a scale-factor knob

For controllable growth curves (§3.3) and stressing specific bottlenecks, extend the existing `test_scripts/data/` generators into a **parameterized** generator with knobs:
- `--entities N`, `--frames-per-entity`, `--slots-per-frame`, `--predicate-cardinality` (few hot predicates vs many), `--graphs` (contexts), `--fanout` (edge degree distribution — power-law vs uniform), `--seed` (deterministic).
- Emits directly to the bulk-load path (COPY). A single `--scale-factor` maps to a preset of these.
- Deterministic + seeded so the *same* dataset regenerates identically for comparable runs and for cross-machine reproducibility.

This gives TPC-style "SF1/SF10/SF100" datasets tuned to *our* schema and query shapes, which reshaped open data can't target precisely.

### 5.3 Dataset management
- **Small/medium** (L0–L2): generate on demand (fast) or keep a cached copy; keep out of git (large), track a manifest + generator seed.
- **Large** (L3–L4): build once, snapshot the RDS volume; **restore from snapshot** for each test run instead of re-loading (hours saved). Store reshaped datasets in S3 as COPY-ready files.

---

## 6. Metrics, gates, and CI

**Metrics captured per test** (size-independent first, wall-clock last):
- Plan node types / flags (index-only, pruning, sort, spill).
- `BUFFERS` shared hit/read; temp bytes; rows examined vs returned.
- `pg_stat_user_indexes.idx_scan` vs `seq_scan`; index-only heap-fetch ratio.
- Ingest quads/s; job per-chunk time + max lock duration.
- Warm and cold wall-clock (context only, not the gate at L0–L2).

**Regression gates (CI):**
- **L0/L1 (every PR):** plan-shape assertions and buffer-count bounds must hold. A change that flips index→seq or blows the buffer bound **fails the build**. These are cheap and deterministic.
- **L2 (nightly/weekly):** growth-curve slope within the expected class; ingest throughput within X% of baseline.
- **L3/L4 (milestone, manual/gated):** absolute SLOs (per-band targets from `billion_scale_strategy.md` §2) and cost budget.

**Anti-pattern to avoid:** gating CI on absolute laptop wall-clock (noisy, non-portable). Gate on plans/counters; treat wall-clock as informational until L3.

---

## 7. Cloud testing & cost control (L3/L4)

- **Ephemeral, IaC-defined** (Terraform/CDK): a `test-rds` module that spins the target instance/storage/replicas, runs the load, captures metrics, and **tears down**.
- **Snapshot-restore, don't re-load:** build the billion-row dataset once → snapshot → each run restores (minutes) instead of re-ingesting (hours). Keep a snapshot per (scale, schema-version).
- **Right-size for the test:** load on a temporarily large instance (parallel index build), then downsize for the query test if measuring steady-state.
- **Spot / short-lived:** L3/L4 runs are hours; use on-demand and destroy. Track spend against the `billion_scale_strategy.md` §10 model — and use L3 numbers to *calibrate* the analytical cost extrapolation (§3.5) so future estimates need no infra.
- **Guardrails:** hard `statement_timeout`, `temp_file_limit`, and a budget alarm so a runaway test can't rack up cost.

---

## 8. Progression roadmap (today → incremental)

Test capability is built **just-in-time** alongside the `billion_scale_strategy.md` tiers — not up front.

| Phase | Deployment work (billion doc) | Testing capability to add | Level focus |
|-------|-------------------------------|---------------------------|-------------|
| **Now** | Tier 0–1 (config, indexes) partly done; per-feature fast-path work | Formalize **plan-shape + buffer-bound assertions** as reusable pytest helpers; wrap the EXPLAIN checks we've been doing by hand. Add growth-curve harness. | L0–L1, seed L2 |
| **Next** | Tier 2 (COPY ingest, PK slim, UUIDv7) | Ingest-throughput benchmark (executemany vs COPY) at 1M/10M; deterministic scale-factor generator | L2 |
| **Then** | Tier 3 (partitioning, stats redesign) | Micro-partition pruning tests (L1) + 50M partitioned growth-curve (L2); background-job chunking tests | L1–L2 |
| **Milestone A** | Validate 100M–1B single instance | Stand up the ephemeral RDS harness; snapshot a 100M–1B reshaped LDBC/Wikidata dataset; absolute-latency + cold-cache runs | **L3** |
| **Later** | Tier 4–5 (replicas, sharding, Aurora Limitless) | Replica-routing + read-after-write tests; micro-shard logic (L1) then real fleet (L4); failover & cost | L1 logic → **L4** |

**Immediate next steps (small, high-leverage):**
1. Add `tests/performance/` helpers: `assert_plan(sql, must_use_index=..., no_seq_scan=..., max_shared_buffers=...)` and `growth_curve(op, sizes=[1e5,1e6,1e7])`. (Codifies §3.1–3.3.)
2. Add a **scale-factor synthetic generator** (§5.2) emitting via COPY.
3. Write one reshaper (start with **LDBC SNB** or a **Wikidata subset**) into the KG model.
4. Convert the ad-hoc EXPLAIN checks used in `kgentity_listing_render_plan.md` into standing L1 regression tests.

---

## 9. Tooling summary

| Need | Tool |
|------|------|
| Unit + plan-shape | pytest markers (`unit`, `integration`, `performance`); `EXPLAIN (FORMAT JSON)` assertions |
| Local backend | **ephemeral `vg-test` Docker** (`docker-compose.test.yml` — own PG:5433 + sidecar:7071 + app:8002, clean per run); `e2e/run-tests.sh` (Playwright) + `scripts/run-perf-tests.sh` (pytest integration/perf); host PG optional fallback |
| Data generation | extend `test_scripts/data/` generators; add scale-factor + reshapers |
| Query-rate / concurrency | `pgbench` (SQL) and/or k6/Locust (HTTP API) for L3 read-rate tests |
| Bulk load | the product COPY path; time it as the benchmark |
| Cloud infra | Terraform/CDK ephemeral RDS module; RDS snapshots; S3 for COPY files |
| Metrics | `pg_stat_statements`, `pg_stat_user_tables/indexes`, `EXPLAIN BUFFERS`, `pg_buffercache`; the verification queries in `mitigation_details.md` |

---

## 10. Appendix — example assertions

**Plan-shape + buffer bound (L1), the codified version of what we did by hand:**
```python
plan = await explain_json(conn, page_sql)          # EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
assert uses_index(plan, "idx_{space}_quad_ps")      # not a Seq Scan
assert not has_node(plan, "Seq Scan", on="rdf_quad")
assert shared_buffers(plan) < 2_000                 # O(page), not O(N) — held at 109K, holds at 1B
assert temp_bytes(plan) == 0                        # no sort/hash spill
```

**Growth-curve (L2):**
```python
pts = {n: shared_buffers(await explain_json(conn, page_sql))
       for n in load_at_sizes([100_000, 1_000_000, 10_000_000])}
assert is_flat_or_log(pts)   # buffers must not grow ~linearly with n → proves O(page)
```

**Reshape sketch (open dataset → KG model):**
```
person(id, name)                 → KGEntity(uri, vitaltype=Person, hasName)
knows(personA, personB, since)   → KGFrame(vitaltype=KnowsFrame)
                                     + KGSlot(source=personA), KGSlot(dest=personB),
                                       hasSinceDate=since
post(id, author, content)        → KGDocument(content) + KGFrame(authoredBy → author slot)
```
Reshapers emit into the common entity/frame/slot/document intermediate, then the existing bulk-load path (COPY) ingests — so every dataset reuses one loader and one set of scaling tests.
</content>
