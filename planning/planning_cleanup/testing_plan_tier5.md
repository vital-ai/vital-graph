# Testing Plan — Tier 5: Performance Tests (benchmarks)

> Split from [testing_plan.md](testing_plan.md). See main doc for overall
> architecture, CI pipeline, fixtures, and migration strategy.

## Purpose

Detect performance regressions. Not gating — run nightly or on demand.

## Approach

- Use `pytest-benchmark` for microbenchmarks.
- Maintain a baseline JSON file with known-good p50/p95/p99 values.
- Alert (but don't fail) on >20% regression.

## Key benchmarks

- SPARQL→SQL generation latency (no DB): p50 < 5ms
- Simple SELECT execution (10 results): p50 < 50ms
- Complex multi-join query (WordNet): p50 < 200ms
- Bulk insert throughput: > 10k quads/sec
- Entity list with graph retrieval: p50 < 200ms

---

## Implementation Status

**Not started.** This is the lowest priority tier — planned for Phase 4 of the
migration strategy (Week 7–8).
