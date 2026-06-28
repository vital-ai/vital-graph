# VitalGraph — Future Ideas & Exploration

**Date:** 2026-06-28
**Status:** Tracking document for ideas to potentially incorporate

---

## 1. UUID Strategy Improvements

**Current state:** UUIDv4 and UUIDv5 are in use.

**Ideas:**

- **UUIDv7 for quad_uuid** — Time-ordered UUIDs would enable scanning by insert order, making exports and incremental processing more efficient (related quads are physically adjacent).
- **Keep deterministic UUIDs for terms** — Same content must map to the same UUID (UUIDv5 is correct here).
- **Consider ULIDs / KSUIDs** — Sortable time component in the prefix, potentially better index locality.

**Reference:** https://medium.com/@optimzationking2/we-used-uuids-as-primary-keys-and-broke-our-indexes-e01ceabc658e

**Key principle:** Don't use random UUIDs as primary keys for high-volume tables due to index fragmentation. Time-ordered identifiers (UUIDv7, ULID) solve this.

---

## 2. Kubernetes Deployment

- Deploy VitalGraph in Kubernetes
- Provide SPARQL endpoint as a K8s service
- Provide additional REST endpoints for status, graph management
- Horizontal scaling considerations (read replicas, connection pooling)

---

## 3. Distributed / Alternative Storage Backends

### TiKV + Oxigraph (exploratory, lower priority)

**Concept:** Use TiKV as a distributed key/value store, potentially with Oxigraph as the SPARQL layer.

**Findings (from earlier research):**
- TiKV has no stable Python client (main client is Go, Rust recently updated)
- Oxigraph is Rust-based — could potentially use Rust TiKV client
- Concept: Create a TiKV store backend for Oxigraph (replacing RocksDB)
- **Risk:** Oxigraph's optimizer may be tightly coupled to local RocksDB performance characteristics; network round-trips to TiKV could negate optimization benefits
- TiKV co-processor/optimizer is accessed via TiDB and may be hard to use directly

### TiDB with Skinny Quad Tables (alternative)

**Concept:** Use TiDB (distributed SQL) with the same term/quad table architecture as the current PostgreSQL backend, leveraging TiDB's built-in SQL optimizer.

**Advantages:**
- Horizontal scalability via TiDB's distributed architecture
- Built-in optimization at SQL level (no need to replicate Oxigraph heuristics)
- Compatible with existing SPARQL-to-SQL pipeline (SQL is SQL)

**Status:** Empty stub exists at `vitalgraph/db/tidb/` — never implemented.

---

## 4. SPARQL Query Optimization

- Continue leveraging ARQ-style heuristic reordering (already implemented via Jena sidecar)
- Explore cost-based optimization using PostgreSQL statistics (quad_stats table already exists)
- Consider adaptive query execution (re-plan after first few results)

---

## 5. Additional Ideas to Track

*(Add future ideas here as they come up)*

- Multi-region replication
- GraphQL endpoint (alternative to REST)
- SPARQL federation (query across multiple VitalGraph instances)
- Streaming/CDC (change data capture for real-time consumers)
- Plugin architecture for custom vg: functions
- Embedding model hot-swap (re-vectorize on model upgrade)
- Fine-grained access control (graph-level or entity-level permissions)

---

## Evaluation Criteria

When considering whether to pursue a future idea:

1. **User demand** — Is this blocking adoption or requested by users?
2. **Effort vs. impact** — How much work vs. how much value?
3. **Architecture fit** — Does it compose cleanly with the current system?
4. **Maintenance burden** — Will it create ongoing maintenance cost?
5. **Alternatives** — Can the need be met with existing features?
