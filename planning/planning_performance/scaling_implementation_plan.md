# Scaling Implementation Plan: Phased Progression to 1B (with Validation)

**Status**: Implementation plan (executable)
**Date**: 2026-07-18
**Branch**: `performance` (off `refactor`)
**Scope**: Take a single space from ~10M to **~1B quads** on **AWS RDS PostgreSQL**, incrementally. (Beyond 1B — sharding / Aurora Limitless — is out of scope here; see `billion_scale_strategy.md` Tier 5.)

**Synthesizes:**
- `100x_scalability_analysis.md` + `mitigation_details.md` — *what* to change (the P0/P1 bottlenecks and concrete SQL/code).
- `billion_scale_strategy.md` — the tiered levers (Tier 0–4 reach 1B) and PG-18/RDS config.
- `scaling_test_strategy.md` — *how to validate* each change (the L0–L4 ladder; prove complexity locally, validate constants in the cloud).

**Operating rule (from the test strategy):** every phase pairs *implementation* with a *validation gate*. A change is "done" only when it (a) works and (b) passes its scaling assertion — a plan-shape / buffer-bound / growth-curve check that would fail if the change regressed. We prove **complexity class** on medium local data (L0–L2) and validate **constants** (absolute latency, cost) on ephemeral cloud infra (L3) only at the milestone.

**Test environment (confirmed & standard for this plan):** L0–L2 validation runs against the **ephemeral `vg-test` Docker stack** (`docker-compose.test.yml`, project `vg-test`) — a self-contained stack with **its own PostgreSQL** container (`docker/test-pg`, no volumes → clean DB every run, port 5433), the app (8002), the Jena sidecar (7071), and MinIO. It does **not** use the host-local PG, so runs are reproducible and version-pinned. Every validation cycle **spins up the updated stack (`--build`), loads/seeds, runs the checks, and tears down** — the same ephemeral pattern we apply to cloud infra at L3, just free and local. `e2e/run-tests.sh` already implements up → seed → Playwright → down; this plan extends that flow to the **integration + performance** suites (point them at the container DB) and keeps the image on the **target PG version**.

---

## 0. Progression at a glance

| Phase | Objective (band) | Tier work (billion doc) | Primary validation level | Gate |
|-------|------------------|-------------------------|--------------------------|------|
| **P0** | Build the validation harness | — (tooling) | L0–L2 harness | `assert_plan` / `growth_curve` / ingest-bench exist + green in CI |
| **P1** | Safe & fast reads (10M→100M) | Tier 0 config/safety + Tier 1 indexes | L1 plan-shape + buffer bounds | Graph-scoped reads index-only; OOM/DoS risks closed |
| **P2** | Viable writes & ingest (→ COPY) | Tier 2 (COPY, PK slim, UUIDv7, chunked sync) | L2 ingest throughput curve | COPY ≥5× executemany; per-write cost flat vs size |
| **P3** | Architecture for 100M→1B | Tier 3 (partition, stats redesign) + Tier 6 jobs | L1 pruning logic + L2 growth curve | Partition pruning proven; per-partition maintenance; index fits cache |
| **P4** | Read topology | Tier 4 (replicas, dual pools, RDS Proxy, cache coherence) | L1 routing logic + L4 real replica | Reads route to replicas; read-after-write handled |
| **P5** | Validate 1B in the cloud | — (validation milestone) | **L3/L4** absolute SLOs + cost | Per-band SLOs met; cost within model |

Phases are **independently shippable** and ordered easy→hard. Stop at any phase and the system is coherent and better.

---

## Phase 0 — Validation harness first

**Why first:** we've been doing EXPLAIN/buffer checks by hand (e.g. `kgentity_listing_render_plan.md`). Codify them so every later phase has a cheap, deterministic gate. This is the enabler for "prove scaling without scale."

**Build (`tests/performance/` + helpers):**
1. `assert_plan(conn, sql, *, must_use_index=None, no_seq_scan=(), max_shared_buffers=None, no_spill=True)` — runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, asserts node types/flags and buffer/temp bounds. (Codifies test-strategy §3.1–3.2.)
2. `growth_curve(op, sizes=[1e5, 1e6, 1e7], metric="shared_buffers")` — loads at each size, fits class (flat/log/linear/superlinear), asserts expected class. (§3.3.)
3. `cold_cache(conn)` — `DISCARD ALL` + evict, to measure `shared read` vs `hit`. (§3.4.)
4. **Scale-factor synthetic generator** (`test_scripts/data/generate_scale_data.py`): knobs `--entities --frames-per-entity --slots-per-frame --predicate-cardinality --graphs --fanout --seed`, emits via **COPY**; deterministic. (§5.2.)
5. Wire markers: `pytest -m "performance"` (L2), keep `integration` (L1), `unit` (L0).
6. **Ephemeral Docker test runner + version bump:**
   - **Bump `docker/test-pg/Dockerfile` from PostgreSQL 17 → 18** (with PostGIS + pgvector), pinning to the **PG major/minor currently available on RDS** (18.x — RDS latest minor 18.4 as of 2026-07) so tests run on the same version as production (async I/O, skip-scan, UUIDv7, partition-pruning cost model). Policy: keep the test image tracking the current RDS-supported version; re-pin when RDS advances (e.g. PG 19 when GA). Verify PostGIS + pgvector build on PG 18.
   - Add a one-shot **`scripts/run-perf-tests.sh`** (mirroring `e2e/run-tests.sh`): `docker compose -f docker-compose.test.yml up -d --build --wait` → load the generated dataset into the container DB → run `pytest -m "integration or performance"` against it → `docker compose ... down` (with `--no-down`/`--skip-build` for iteration). This makes "spin up the updated docker → validate → tear down" the standard cycle for L1/L2, not just Playwright e2e.
   - Point the integration/perf suites at the **container DB** by default in this runner: `VG_TEST_PG_PORT=5433`, `VG_TEST_PG_PASSWORD=testpass`, `VG_TEST_SIDECAR_URL=http://localhost:7071` (the `vg-test` ports). The suites already read these via `tests/integration/conftest.py`, so no test code changes — just the runner's env.

**Validation of P0 itself:** convert the ad-hoc EXPLAIN checks from `kgentity_listing_render_plan.md` (the 464-buffer entity page; the frames/types fast paths) into standing L1 regression tests using `assert_plan`. They must pass **inside the freshly-built `vg-test` container** on the seeded/synthetic spaces (proving reproducibility on a clean, PG-18 DB — not the developer's host PG).

**Exit gate:** the `vg-test` stack builds on PG 18 and `run-perf-tests.sh` runs the full up→load→validate→down cycle green; the entity/frame/type/document fast-path assertions pass in-container; a growth-curve on the current entity page shows **flat** buffers across 100K→1M→10M (synthetic).

---

## Phase 1 — Safe & fast reads (Tier 0 + Tier 1)

**Objective:** close the OOM/DoS risks and make graph-scoped reads index-only. Band 10M→100M. Low risk, no table rewrite.

**Changes** (from `100x` Phase 1 + `billion` Tier 0/1; SQL in `mitigation_details.md`):
- **Tier 0 (config/safety):** RDS parameter group (shared_buffers, work_mem, hash_mem_multiplier, effective_io_concurrency, huge_pages; PG 18 `io_method=worker`); **mandatory `statement_timeout` + `idle_in_transaction_session_timeout`**; **LRU-cap `_term_cache`/`_stats_cache`** + `LIMIT 10000` stats load; **`MAX_PATH_DEPTH` → 5**; `default_statistics_target=500` + per-column targets; autovacuum tuning.
- **Tier 1 (indexes/query):** `(context_uuid, predicate_uuid)` and `(context_uuid, subject_uuid)` **covering** indexes (build `CONCURRENTLY`); **partial GIN** on `term(term_text) WHERE term_type='L'`; **LIMIT push-through** past term JOINs; `DELETE … RETURNING` fuse; `rdf_stats(row_count)` index; the `_require_literal` trigram fix (already implemented — add a standing test).

**Validation (L0/L1, plus one L2 curve):**
- `assert_plan` on graph-scoped predicate/subject queries → **Index-Only Scan** on the new composites, **no Seq Scan** on `rdf_quad`, `Heap Fetches: 0`, `shared_buffers < bound`.
- Cache-cap tests (L0): term/stats caches evict at the cap; stats load capped at 10K rows.
- Path-depth test (L0): property path rejects depth > configured.
- **Growth curve (L2):** graph-scoped point-lookup buffers stay **flat** across 1M→10M→50M synthetic; a `rdf:type`-heavy predicate scan grows **≤ linear** and uses the index.
- Cold-cache (L1): confirm the covering index turns cold random-heap reads into index-only (compare `shared read`).

**Exit gate:** graph-scoped reads are index-only with flat buffer growth; caches provably bounded; property-path fenced; all Phase-1 assertions green in CI.

---

## Phase 2 — Viable writes & ingest (Tier 2)

**Objective:** make billion-quad ingest feasible (days → hours) and keep per-write cost bounded as indexes grow.

**Changes** (from `100x` Phase 2 + `billion` Tier 2):
- **COPY-based bulk load** via staging temp tables + `INSERT … SELECT ON CONFLICT` (`sparql_sql_space_impl.add_rdf_quads_batch_bulk`).
- Extend `drop_space_indexes_sql` to drop **edge/frame_entity/geo** indexes for bulk load; rebuild `CONCURRENTLY` / with `max_parallel_maintenance_workers`.
- **Chunk aux-table sync** `ANY($3)` into 10K-subject batches (`sync_edge_table`, `sync_frame_entity_table`).
- **UUIDv7** default for `quad_uuid` (PG 18); **remove `quad_uuid` from PK** (4-col UNIQUE) — schedule this rewrite to coincide with P3 partitioning to rewrite once.
- Streaming COPY **export** (`COPY (SELECT …) TO STDOUT`) for backup/migration.

**Validation (L2 throughput + L1 correctness):**
- **Ingest-throughput benchmark:** load 1M/10M synthetic quads via **executemany vs COPY**; assert COPY ≥ **5×** and quads/s roughly flat (not collapsing as indexes grow). (Test-strategy §4 batch dimension.)
- **Per-write curve:** single-quad insert latency vs table size (1M→10M→50M) stays **sub-linear** (no O(N) aux sync). `assert_plan` on the aux-sync query shows chunked, bounded work.
- Correctness (L1): COPY path produces identical quads/counts to executemany; ON CONFLICT dedup holds; export round-trips (export → re-import → identical counts).
- UUIDv7/PK-change: uniqueness preserved; insert-locality improvement visible as reduced index buffer churn (L2).

**Exit gate:** COPY path is the default bulk loader with a ≥5× benchmark; export/import round-trips; per-write cost flat; a 10M synthetic load completes within target quads/s.

---

## Phase 3 — Architecture for 100M→1B (Tier 3 + background jobs)

**Objective:** keep each index cache-resident and each maintenance op bounded, so 100M→1B is survivable on one instance.

**Changes** (from `100x` Phase 3 + `billion` Tier 3 + §6 jobs):
- **Partition `rdf_quad` by HASH(context_uuid)** (16–64 partitions; LIST-by-graph where few graphs). Co-partition `edge`/`frame_entity`. Fold in the PK slim + UUIDv7 (one rewrite). Migration is per-space, online (build alongside → backfill via COPY → swap).
- **Covering indexes with `INCLUDE`** per partition; drop subsumed single-column indexes.
- **Bounded stats redesign** (top-N `rdf_stats`); optional predicate-partitioned hot-predicate tables; optional materialized transitive closures for key predicates.
- **Background maintenance service** (§6 of billion doc): ANALYZE driven by `n_mod_since_analyze` (DB-side, threshold ~5M for large spaces), tuned autovacuum, chunked aux/stats resync, orphan-term cleanup, index reindex-CONCURRENTLY, partition lifecycle — all idempotent, chunked, resumable, non-blocking.

**Validation (L1 logic + L2 scale):**
- **Micro-partition tests (L1):** a table with 4 partitions × 10K rows — `assert_plan` shows **partition pruning** to one partition for `WHERE context_uuid=$1`; partition-wise joins; per-partition index used.
- **Growth curve (L2):** partitioned vs unpartitioned at 10M/50M — partitioned query buffers stay **flat / smaller**, index size per partition small; confirm working set fits `shared_buffers`.
- **Background-job tests (L1/L2):** each job runs on medium data with **bounded per-chunk work** (`assert_plan`), **no long `ACCESS EXCLUSIVE` locks** (assert lock duration), and is **resumable** (kill mid-run → re-run → correct). Orphan cleanup reclaims only unreferenced terms. Stats redesign: top-N `rdf_stats` matches the reorder heuristic's needs.
- Migration test (L1): per-space partition migration preserves counts and query results (dual-read parity before/after swap).

**Exit gate:** partitioned schema with pruning proven at micro + 50M; background-jobs service runs the full maintenance set online with bounded work; migration is count/parity-safe.

---

## Phase 4 — Read topology (Tier 4)

**Objective:** scale reads out and isolate workloads; correctness under horizontal app scale-out. Still stock RDS (one writer + N readers).

**Changes** (from `billion` Tier 4):
- **Dual-pool routing** in `db_provider.py`: SPARQL `SELECT` → replica pool (round-robin), writes/updates → primary.
- **OLTP vs analytics pools** (different `command_timeout`).
- **RDS Proxy** (managed) in front of PG.
- **Multi-instance-safe caches:** move ANALYZE-trigger accounting DB-side; accept per-instance read caches (or externalize hot caches).

**Validation (L1 logic + L4 real):**
- **Routing logic (L1, local):** with a mocked/second local PG as "replica," assert SELECTs use the read pool and writes the write pool; analytics queries use the analytics pool.
- **Read-after-write (L1):** flows that must see their own write route to primary (or a read-primary window); assert no stale read in those flows.
- **Cache-coherence (L1):** two app instances don't double-trigger ANALYZE; DB-side counter is authoritative.
- **Real replica (L4, ephemeral):** one primary + 1–2 real RDS replicas — measure replication lag under write load, verify read throughput scales ~linearly, and failover behaves.

**Exit gate:** routing + read-after-write + cache-coherence proven locally; a real 2-replica RDS run shows sub-second lag and near-linear read scaling.

---

## Phase 5 — Cloud validation at 1B (L3/L4 milestone)

**Objective:** validate the *constants* — absolute latency, ingest wall-clock, maintenance windows, and cost — at true 1B scale. This is the only phase that requires large infra + data.

**Setup (from test-strategy §5, §7):**
- **Dataset:** a reshaped **LDBC SNB (≈SF1000)** or **Wikidata subset** at ~1B quads in the KG entity/frame/slot model, built once and **snapshotted** (restore per run, don't re-load).
- **Infra:** ephemeral RDS (io2/gp3 per `billion` §9 sizing), IaC-defined, budget-guarded, torn down after.

**Validation (L3/L4):**
- **Per-band SLOs** (`billion` §2): graph-scoped point p95 < 250 ms; analytics p95 < 30 s; ingest ≥ 200K quads/s; online maintenance (no blocking window).
- **Cold-cache** first-query behavior on network-attached storage (validates the async-I/O + covering-index work).
- **Bulk load** of ~1B: confirm hours-not-days via COPY + deferred indexes + parallel build.
- **Cost:** measure actual $/mo vs the `billion` §10 model; **calibrate** the analytical cost extrapolation so future estimates need no infra.
- **Replicas/topology** (L4) if Phase 4 shipped: real read-scaling + lag at 1B.

**Exit gate:** the 1B space meets its per-band SLOs, loads in hours, maintains online, and lands within the cost model — with the plan/counter assertions from P1–P3 still holding at 1B (proving the local proofs extrapolated correctly).

---

## Cross-phase: definition of done & CI gating

- **Every scaling PR** carries a scaling assertion (plan-shape / buffer-bound / growth-class), not just a correctness test. CI gates on these (deterministic, portable) — **not** on laptop wall-clock.
- **Nightly (L2):** growth curves + ingest throughput within X% of baseline; regressions block.
- **Milestone (L3/L4):** absolute SLOs + cost, run manually/gated, results recorded and used to calibrate the cost model.
- **Datasets:** small/medium generated on demand (seeded); large built once → snapshot in S3/RDS.

## Sequencing notes & risks

- **P0 before everything** — without the harness, later phases can't be cheaply validated; it's small and high-leverage.
- **P2's PK/UUIDv7 rewrite is folded into P3's partition rewrite** to rewrite the table once.
- **Partition key risk (P3):** validate that production queries are graph-scoped before committing to HASH(context_uuid) (see `billion` §11); the micro-partition tests must reflect real query shapes.
- **Covering-index storage (P1/P3):** net-neutral only if subsumed indexes are dropped — assert plans still hold after dropping.
- **`io_method` on RDS (P1):** confirm the parameter group exposes it; fall back to `worker`.
- Phases 1–3 deliver most of the win on a single instance; Phase 4 is only needed when one instance's read/connection capacity is the limit; Phase 5 is validation, not new capability.

---

## Immediate next actions (this branch)

1. **P0:** bump `docker/test-pg` to **PG 18**; add `scripts/run-perf-tests.sh` (spin up `vg-test` docker `--build` → load → `pytest -m "integration or performance"` against the container DB on :5433 → tear down); scaffold `tests/performance/` with `assert_plan` + `growth_curve` + `cold_cache`; add `generate_scale_data.py`; convert the existing entity/frame/type/document fast-path EXPLAIN checks into standing L1 tests that run **in-container**.
2. **P1:** add the two context-leading covering indexes + partial GIN to `sparql_sql_schema.py` (CONCURRENTLY); the Tier-0 config/cache-cap/timeout/path-depth changes; write their `assert_plan` gates.
3. Land P0+P1 on `performance`, then proceed phase-by-phase, each behind its validation gate.
</content>
