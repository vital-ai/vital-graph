# Btree Index Limit on term_text — Fix Plan

## 1. Problem

The per-space term table (`{space_id}_term`) stores all RDF terms
(URIs, literals, blank nodes) in a `text` column (`term_text`) with no
length limit.  The schema creates a **btree composite index** on
`(term_text, term_type)` for equality lookups:

```sql
CREATE INDEX idx_{space_id}_term_tt
    ON {space_id}_term (term_text, term_type)
```

PostgreSQL btree indexes cannot handle row values exceeding **~2704
bytes** (one-third of the default 8 KB page size).  Inserting a literal
longer than this causes:

```
asyncpg.exceptions.ProgramLimitExceededError:
  index row size 3056 exceeds btree version 4 maximum 2704
  for index "idx_framenet_kgtypes_test_term_tt"
```

### 1.1 Impact

- **Incremental import** (`INSERT ... ON CONFLICT`) fails immediately
  when a long literal is encountered.
- **Bulk import** (`COPY`) may succeed because index checks are deferred,
  but the index entry is silently missing — subsequent lookups for that
  term will fall back to sequential scan.
- Any property with a long string value triggers this: `kGraphDescription`,
  `textSlotValue`, document content, etc.

### 1.2 Existing Data

| Space | Max literal length | Status |
|-------|-------------------|--------|
| `cardiff_kg` | 3,745 chars | Loaded via COPY; index entry likely missing |
| `framenet_kgtypes_test` | 2,500 chars (truncated) | Workaround applied |

The issue has not surfaced before because most loaded data had shorter
literals.

---

## 2. Root Cause

The index `(term_text, term_type)` is used purely for **equality
lookups** in the SPARQL-to-SQL pipeline:

```sql
SELECT term_uuid FROM {term}
WHERE term_text = $1 AND term_type = 'U' LIMIT 1
```

Btree indexes support equality, range, and prefix operations but have a
hard row-size limit.  For equality-only workloads, a hash index is more
appropriate since it has no value-size restriction.

---

## 3. Proposed Fix

Replace the btree composite index with a **hash index** on `term_text`
plus the existing btree on `term_type`.

### 3.1 Schema Change

File: `vitalgraph/db/sparql_sql/sparql_sql_schema.py`, line 560.

```python
# Before:
f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_tt "
f"ON {t['term']} (term_text, term_type)"

# After:
f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_tt "
f"ON {t['term']} USING hash (term_text)"
```

The existing `idx_{space_id}_term_type` btree on `term_type` remains
unchanged.  For queries like `WHERE term_text = $1 AND term_type = 'U'`,
PostgreSQL will use a BitmapAnd of the hash index and the `term_type`
btree — functionally equivalent with no size limit.

### 3.2 Hash Index Considerations

| Factor | Status |
|--------|--------|
| WAL-safe (crash recovery) | Yes — since PostgreSQL 10 |
| Supports equality (`=`) | Yes |
| Supports range (`<`, `>`, `BETWEEN`) | No — not needed |
| Supports `ORDER BY` | No — not needed |
| Supports `IS NULL` | Yes — since PostgreSQL 10 |
| Arbitrary value length | **Yes** |
| Composite key support | No — use separate indexes |

All term table queries use equality only, so hash is a drop-in
replacement for this use case.

### 3.3 Migration for Existing Spaces

For each existing space, run:

```sql
DROP INDEX IF EXISTS idx_{space_id}_term_tt;
CREATE INDEX idx_{space_id}_term_tt
    ON {space_id}_term USING hash (term_text);
```

This can be done online (`CREATE INDEX CONCURRENTLY` for production) or
during a maintenance window.

### 3.4 Drop Index SQL (already exists)

The `drop_space_indexes_sql` method already drops `idx_{space_id}_term_tt`
by name, so the bulk-load optimization path (drop indexes → COPY →
recreate) will work correctly with the new hash index definition.

---

## 4. Alternative Approaches Considered

### 4.1 Functional Btree on md5(term_text)

```sql
CREATE INDEX ... ON term (md5(term_text), term_type)
```

Requires changing all queries to use `WHERE md5(term_text) = md5($1)
AND term_text = $1` (the second condition handles hash collisions).
Too invasive — touches 30+ query sites.

### 4.2 Truncated Btree

```sql
CREATE INDEX ... ON term (left(term_text, 500), term_type)
```

PostgreSQL won't use this index for `WHERE term_text = $1` because the
indexed expression (`left(...)`) doesn't match the query expression.
Would require rewriting all queries.

### 4.3 GIN Trigram Index Only

The GIN trigram index (`gin_trgm_ops`) already exists on `term_text`
and supports equality.  However, GIN equality lookups are significantly
slower than hash or btree for exact match, and GIN indexes are larger.
Not recommended as the sole index for high-frequency equality lookups.

### 4.4 Application-Level Truncation

Current workaround: truncate long values before storage.  This loses
data and is fragile — every insertion path must enforce the limit.
Acceptable as a temporary measure only.

---

## 5. Current Workaround

The FrameNet generator (`test_scripts/data/generate_framenet_kgtypes.py`)
truncates `kGraphDescription` to 2,500 characters (`_MAX_DESC_LEN`).
This keeps all values under the btree limit.  See
`framenet_testing_plan.md` §2.3 for details.

This workaround should be removed once the hash index fix is deployed.

---

## 6. Related

- `planning_visualization/framenet_testing_plan.md` §2.3 — Documents the
  issue and truncation workaround in the FrameNet context
- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` — Index definitions
- `vitalgraph/endpoint/impl/data_import_impl.py` — Import engine that
  triggers the error
