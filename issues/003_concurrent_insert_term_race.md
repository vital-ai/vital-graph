# Concurrent INSERT DATA: term table UniqueViolationError

## Summary

When multiple SPARQL INSERT DATA operations run concurrently and reference
the same subject URI, the term insertion hits a `UniqueViolationError` on
`term_pkey`. The `WHERE NOT EXISTS` guard in the emitted SQL is not
atomic under concurrent execution.

## Root Cause

In `vitalgraph/db/sparql_sql/emit_update.py`, term insertion uses:

```sql
INSERT INTO {space}_term (term_uuid, term_text, term_type, lang, datatype_id)
SELECT '<uuid>', '<text>', '<type>', NULL, NULL
WHERE NOT EXISTS (
    SELECT 1 FROM {space}_term WHERE term_uuid = '<uuid>'
)
```

Under concurrent transactions, two sessions can both execute the `NOT EXISTS`
check before either commits, causing both to attempt the INSERT.

## Reproduction

```python
# 5 concurrent INSERT DATA operations referencing the same subject URI
tasks = [
    sparql_update(f'INSERT DATA {{ <same_uri> <prop{i}> "val{i}" . }}', space)
    for i in range(5)
]
await asyncio.gather(*tasks)  # UniqueViolationError
```

## Proposed Fix: ON CONFLICT DO NOTHING

Replace `INSERT ... WHERE NOT EXISTS` with `INSERT ... ON CONFLICT DO NOTHING`.

### Historical Note

ON CONFLICT DO NOTHING was previously attempted and broke things. The
upstream code historically relied on the guarantee that after emitting a
term INSERT, the term row IS present for subsequent quad references within
the same multi-statement batch.

### Investigation (2026-07-02)

The upstream dependency **no longer exists** in the current codebase:

1. **Main write path already uses ON CONFLICT DO NOTHING** —
   `sparql_sql_space_impl.py:_ensure_term()` (line ~1574) has been using
   `ON CONFLICT DO NOTHING` successfully all along. It computes the
   deterministic UUID before the INSERT and returns it regardless of
   whether the row was actually inserted.

2. **No RETURNING or row-count checks** — nothing in `emit_update.py` or
   its callers inspects whether a term INSERT actually inserted a row.
   The `execute_sparql_update()` call (line ~1438) simply does
   `await conn.execute(sql)` on the full batch with no per-statement
   result inspection.

3. **Deterministic UUIDs for most terms** — after the issue #001 fix,
   `_term_uuid_subquery` emits pre-computed UUID literals for all URIs,
   typed literals, and lang-tagged literals. These quad INSERTs have
   **zero dependency** on the term table lookup.

4. **Plain untyped literals (common case) use a subquery fallback** —
   `_term_uuid_subquery` still emits
   `(SELECT term_uuid FROM term WHERE term_text=... LIMIT 1)` for plain
   literals with no lang/datatype. This IS the common case (string values
   like names, descriptions, etc.). However, this is safe with ON CONFLICT
   because:
   - If our INSERT succeeded → term visible within same tx
   - If ON CONFLICT fired (term already committed by another tx) → term
     visible to our next statement's snapshot (READ COMMITTED gives each
     statement a fresh snapshot after lock resolution)

5. **PostgreSQL concurrency semantics** — when two transactions try to
   INSERT the same `term_uuid` with ON CONFLICT DO NOTHING:
   - One wins and acquires the row lock
   - The other blocks on that lock
   - When the winner commits, the blocked tx re-evaluates → DO NOTHING
   - The blocked tx's subsequent statements see the committed term
   - No UniqueViolationError possible

6. **Why the subquery fallback exists for plain literals** — per
   `planning/planning_sql/kg_query/sparql_sql_datatype_loss_plan.md`,
   the OLD `_term_upsert()` used `gen_random_uuid()` (not deterministic).
   Any term written before the deterministic UUID fix may have a random
   UUID in the database. The subquery fallback
   `SELECT term_uuid FROM term WHERE term_text=... AND term_type='L'`
   was intentionally kept as a backward-compatibility safeguard — it finds
   legacy terms by text+type regardless of their UUID. Computing the
   deterministic UUID in Python would produce a different UUID than what's
   actually stored for those legacy rows.

   This fallback does NOT affect the ON CONFLICT fix — whether the term
   INSERT succeeds or is a no-op, the subquery will find the term either
   way. The fallback is about **reading** legacy terms, not about insert
   side-effects.

7. **Eliminating the subquery fallback (optional further hardening)** —
   if all existing spaces have been migrated to deterministic UUIDs (or
   no pre-fix plain-literal data remains), the fallback could be removed
   entirely by always computing `_generate_term_uuid(text, "L")` in
   Python. This would remove the last term-table dependency from quad
   INSERTs.

   **Migration path:** A one-time DB migration script could re-key all
   legacy plain-literal terms to deterministic UUIDs:
   ```sql
   -- For each space:
   -- 1. Compute new deterministic UUID for each plain literal term
   -- 2. Update term_uuid in the term table
   -- 3. Update all rdf_quad references (object_uuid, subject_uuid, etc.)
   --    that pointed to the old random UUID
   --
   -- Pseudocode:
   UPDATE {space}_term SET term_uuid = vitalgraph_term_uuid(term_text, term_type, lang, datatype_id)
   WHERE term_type = 'L' AND lang IS NULL AND datatype_id IS NULL
     AND term_uuid != vitalgraph_term_uuid(term_text, term_type, lang, datatype_id);
   --
   -- Then cascade to rdf_quad:
   UPDATE {space}_rdf_quad q SET object_uuid = t.new_uuid
   FROM (
     SELECT old.term_uuid AS old_uuid,
            vitalgraph_term_uuid(old.term_text, old.term_type, old.lang, old.datatype_id) AS new_uuid
     FROM {space}_term old
     WHERE old.term_type = 'L' AND old.lang IS NULL AND old.datatype_id IS NULL
       AND old.term_uuid != vitalgraph_term_uuid(old.term_text, old.term_type, old.lang, old.datatype_id)
   ) t
   WHERE q.object_uuid = t.old_uuid;
   ```
   After migration, the subquery fallback can be removed and all UUID
   lookups become deterministic Python computations. The script operates
   directly against the database while the service is down (no app server
   required) and is located at `apps/term_uuid_migration/migrate_term_uuids.py`.

### Related Planning Documents

- `planning/planning_sql/kg_query/sparql_sql_datatype_loss_plan.md` —
  documents the full chain of causation for UUID mismatches, the fix to
  `_term_upsert` (deterministic UUID v5), and explicitly notes the
  subquery fallback for plain untyped literals (line 171).
- `planning/planning_import_export/import_export_plan.md` — import engine
  incremental path uses `INSERT ON CONFLICT` successfully (line 182).
- `planning/planning_sql/sparql_sql_v2_update_plan.md` — module structure
  showing `_term_upsert` and `_term_uuid_subquery` as V2-native helpers.

### Alternative Approaches (if ON CONFLICT proves problematic)

1. **Application-level retry** — catch `UniqueViolationError` on the term
   INSERT and retry the entire batch (simple but adds latency).
2. **Advisory lock per term UUID** — `pg_advisory_xact_lock(term_uuid)`
   before each conditional INSERT (heavy for high-cardinality batches).
3. **Serializable isolation** — run term+quad batch at SERIALIZABLE level
   (PostgreSQL handles conflicts via serialization failures + retry).

## Severity

**Medium** — affects concurrent write workloads. Single-threaded writes
(which is the typical KG entity lifecycle pattern) are not affected.

## Affected Tests

- `tests/integration/test_concurrency.py::TestConcurrentWrites::test_parallel_inserts_different_predicates`
  (marked xfail)

## Files

- `vitalgraph/db/sparql_sql/emit_update.py` (term INSERT generation)
