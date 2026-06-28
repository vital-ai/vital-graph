# Entity Registry Bulk Upload Plan

## Overview

A CLI script (`entity_admin.py bulk-load`) for ingesting large volumes of entity data
directly into PostgreSQL, bypassing the REST API. Designed for initial population,
migrations from external systems, and periodic batch imports of thousands to millions
of entities.

---

## 1. Input Format

### 1.1 Entity File (JSONL — required)

One JSON object per line. Each line is a self-contained entity record with all related
data (aliases, identifiers, categories, locations) nested inline.

```jsonl
{"type_key":"business","primary_name":"Acme Corporation","country":"US","region":"California","locality":"San Francisco","description":"Manufacturing company","website":"https://acme.com","aliases":[{"alias_name":"Acme Corp","alias_type":"abbreviation"},{"alias_name":"ACME","alias_type":"abbreviation"}],"identifiers":[{"namespace":"DUNS","value":"123456789","is_primary":true}],"categories":["customer","vendor"],"locations":[{"location_type":"headquarters","location_name":"SF Office","address_line_1":"123 Market St","locality":"San Francisco","admin_area_1":"CA","country":"US","country_code":"US","postal_code":"94105","latitude":37.7937,"longitude":-122.3965}],"metadata":{},"created_by":"bulk_import_2026"}
```

**Required fields:**
- `type_key` — must match an existing `entity_type.type_key` (person, business, etc.)
- `primary_name`

**Optional entity fields:**
- `entity_id` — if provided, used as-is (for migrations preserving IDs); if omitted, auto-generated
- `country`, `region`, `locality`, `description`, `website`, `notes`, `metadata`
- `created_by` — defaults to `"bulk_load"`
- `latitude`, `longitude` — entity-level coordinates

**Nested arrays (all optional):**
- `aliases[]` — `{alias_name, alias_type?, is_primary?, notes?}`
- `identifiers[]` — `{namespace, value, is_primary?, notes?}`
- `categories[]` — list of `category_key` strings (must match existing `category.category_key`)
- `locations[]` — `{location_type, location_name?, address_line_1?, address_line_2?, locality?, admin_area_1?, admin_area_2?, country?, country_code?, postal_code?, formatted_address?, latitude?, longitude?, timezone?, google_place_id?, effective_from?, effective_to?, is_primary?, notes?}`

### 1.2 Relationship File (JSONL — optional)

Separate file because relationships span entities and require both endpoints to exist.

```jsonl
{"source":"e_a7b3x9k2m1","destination":"e_x2y4z6w8m0","type_key":"employer_of","description":"Since 2020","start_datetime":"2020-01-15T00:00:00Z"}
```

**Source/destination resolution:** Values can be:
- An `entity_id` directly (e.g. `e_a7b3x9k2m1`)
- A lookup key `ref:<namespace>:<value>` (e.g. `ref:DUNS:123456789`) — resolved via `entity_identifier`
- A lookup key `name:<primary_name>` (e.g. `name:Acme Corporation`) — resolved via exact `primary_name` match

**Fields:**
- `source`, `destination` — required (entity reference)
- `type_key` — required (must match `relationship_type.type_key`)
- `description`, `start_datetime`, `end_datetime`, `created_by`, `notes` — optional

---

## 2. Script Architecture

### 2.1 Location

`entity_registry/entity_admin.py` — add a new `bulk-load` subcommand.

Alternatively, a standalone script `entity_registry/entity_bulk_load.py` that can also
be invoked from `entity_admin.py`. The standalone approach is better for operational
clarity and allows independent testing.

### 2.2 CLI Interface

```bash
# Full load: entities + relationships + rebuild indexes
python entity_registry/entity_admin.py bulk-load \
    --entities entities.jsonl \
    --relationships relationships.jsonl \
    --batch-size 1000 \
    --created-by "migration_2026" \
    --rebuild-weaviate \
    --rebuild-dedup \
    --skip-changelog \
    --dry-run

# Entities only, no index rebuild (manual rebuild later)
python entity_registry/entity_admin.py bulk-load \
    --entities entities.jsonl \
    --batch-size 5000

# Relationships only (entities already loaded)
python entity_registry/entity_admin.py bulk-load \
    --relationships relationships.jsonl
```

**Flags:**
| Flag | Default | Description |
|------|---------|-------------|
| `--entities` | — | Path to entity JSONL file |
| `--relationships` | — | Path to relationship JSONL file |
| `--batch-size` | 1000 | Rows per INSERT batch (tune for performance) |
| `--created-by` | `"bulk_load"` | Value for `created_by` columns |
| `--rebuild-weaviate` | false | Run full Weaviate sync after load |
| `--rebuild-dedup` | false | Run full dedup index rebuild after load |
| `--skip-changelog` | false | Omit changelog entries (faster) |
| `--on-conflict` | `skip` | `skip` (ignore dupes), `update` (upsert), `error` (abort) |
| `--validate-only` | false | Parse and validate input without writing |
| `--dry-run` | false | Show counts and sample records, no writes |
| `--max-errors` | 100 | Abort after N validation/insert errors |
| `--log-file` | — | Write detailed log to file |

---

## 3. Processing Pipeline

### 3.1 Phase 0: Pre-flight Validation

1. **Connect** to PostgreSQL pool.
2. **Load lookup tables** into memory:
   - `entity_type` → `{type_key: type_id}` map
   - `category` → `{category_key: category_id}` map
   - `entity_location_type` → `{type_key: location_type_id}` map
   - `relationship_type` → `{type_key: relationship_type_id}` map
3. **Validate input file** (first pass or streaming):
   - Every `type_key` must exist in entity_type
   - Every `categories[]` key must exist in category
   - Every `locations[].location_type` must exist in entity_location_type
   - Report unknown types/categories and offer to auto-create them
4. **Count lines** for progress reporting.
5. **Check for entity_id collisions** if `entity_id` values are provided in the input.

### 3.2 Phase 1: Entity Insert (PostgreSQL)

Process the entity JSONL file in streaming batches:

```
for each batch of N lines:
    1. Parse N JSON lines
    2. Generate entity_ids for records that don't have one
    3. Build batch INSERT for entity table
    4. Build batch INSERTs for entity_alias, entity_identifier,
       entity_category_map, entity_location tables
    5. Execute all INSERTs in a single transaction
    6. Optionally write entity_change_log entries
    7. Report progress (entities/sec, errors, elapsed)
```

**SQL strategy — use `COPY FROM` or multi-row INSERT:**

For maximum throughput, use PostgreSQL `COPY FROM STDIN` via `asyncpg.copy_to_table()`
for the entity table, then multi-row INSERTs with `ON CONFLICT` handling for child
tables. If `COPY` is too rigid for conflict handling, use multi-row `INSERT ... VALUES`
with parameterized queries.

**Recommended approach — multi-row INSERT with asyncpg `executemany`:**

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        # Batch insert entities
        await conn.executemany(
            "INSERT INTO entity (entity_id, entity_type_id, primary_name, ...) "
            "VALUES ($1, $2, $3, ...) ON CONFLICT (entity_id) DO NOTHING",
            entity_rows
        )
        # Batch insert aliases
        await conn.executemany(
            "INSERT INTO entity_alias (entity_id, alias_name, alias_type, ...) "
            "VALUES ($1, $2, $3, ...)",
            alias_rows
        )
        # ... identifiers, categories, locations
```

**Transaction scope:** One transaction per batch (not per entity, not per entire file).
This gives a good balance of atomicity and memory usage. If a batch fails, log the
failing records and continue with the next batch.

**Index management for very large loads (100K+):**

For loads exceeding ~100K entities, consider temporarily disabling non-essential indexes
before the load and rebuilding them afterward. The existing Tier 3 loader pattern
(`_disable_non_essential_indexes` / `_rebuild_indexes` in `sql/store.py`) can be
adapted for entity registry tables.

```
Essential (keep during load):
  - entity.entity_id PRIMARY KEY
  - entity_type.type_key UNIQUE
  - category.category_key UNIQUE

Non-essential (disable/rebuild):
  - idx_entity_name, idx_entity_status, idx_entity_country, idx_entity_created
  - idx_alias_name, idx_alias_entity, idx_alias_type
  - idx_identifier_ns_value, idx_identifier_entity, etc.
  - All entity_location indexes
  - All entity_category_map indexes
```

### 3.3 Phase 2: Relationship Insert (PostgreSQL)

If a relationship file is provided, process it after all entities are loaded:

1. **Resolve references** — For `ref:` and `name:` lookups, build an in-memory map
   during Phase 1 (entity_id ↔ identifiers/names) or query the database.
2. **Batch insert** relationships using `executemany` with `ON CONFLICT` handling.
3. **Validate** both source and destination entity_ids exist before inserting.

### 3.4 Phase 3: Index Rebuild

After PostgreSQL load is complete, rebuild secondary indexes:

#### 3.4.1 Weaviate Rebuild (if `--rebuild-weaviate`)

Use the existing `EntityWeaviateIndex.full_sync(pool)` and `location_sync(pool)` methods,
which already handle bulk upserts efficiently via Weaviate's batch API.

```python
weaviate_index = EntityWeaviateIndex.from_env()
weaviate_index.ensure_collection()
entity_count, _ = await weaviate_index.full_sync(pool, batch_size=200)
location_count, _ = await weaviate_index.location_sync(pool, batch_size=200)
```

This is equivalent to `entity_admin.py weaviate sync --full` and does NOT drop/recreate
collections (use `weaviate rebuild` separately if schema changes are needed).

#### 3.4.2 Dedup Index Rebuild (if `--rebuild-dedup`)

Use the existing `EntityDedupIndex.initialize(pool)` method, which already does a
streaming bulk load from PostgreSQL using a cursor.

```python
dedup_index = EntityDedupIndex.from_env()
count = await dedup_index.initialize(pool)
```

This is equivalent to `entity_admin.py dedup sync --full`.

---

## 4. Impact on Running Service

### 4.1 What Is NOT Cached (safe — changes visible immediately)

| Component | Storage | Read Pattern | Bulk Load Impact |
|-----------|---------|--------------|------------------|
| Entity CRUD | PostgreSQL | Direct SQL query per request | ✅ New entities visible immediately |
| Aliases | PostgreSQL | Direct SQL query | ✅ Visible immediately |
| Identifiers | PostgreSQL | Direct SQL query | ✅ Visible immediately |
| Categories | PostgreSQL | Direct SQL query | ✅ Visible immediately |
| Locations | PostgreSQL | Direct SQL query | ✅ Visible immediately |
| Relationships | PostgreSQL | Direct SQL query | ✅ Visible immediately |
| Change Log | PostgreSQL | Direct SQL query | ✅ Visible immediately |
| Entity types | PostgreSQL | Direct SQL query | ✅ Visible immediately |
| Weaviate search | Weaviate | Direct Weaviate query | ⚠️ Stale until sync |
| Location search | Weaviate | Direct Weaviate query | ⚠️ Stale until sync |

**Confirmation needed:** Verify that `list_entity_types()`, `list_categories()`,
`list_location_types()`, and `list_relationship_types()` all query PostgreSQL directly
on each call (no in-process cache). A quick grep confirms these are all direct
`conn.fetch()` calls — no caching.

### 4.2 What IS Cached (requires reload)

| Component | Cache Type | Staleness Effect | Reload Mechanism |
|-----------|-----------|------------------|------------------|
| **Dedup index (in-memory)** | In-process MinHash LSH | `find_similar` won't find new entities | `initialize(pool)` full reload |
| **Dedup index (Redis/MemoryDB)** | Redis keys | Same as above but shared across workers | `initialize(pool)` or per-entity `add_entity()` |

### 4.3 Dedup Index Reload Strategy — IMPLEMENTED

The in-memory dedup index runs inside each web worker process. After a bulk load:

**Admin Rebuild Endpoint (implemented):**

```
POST /api/registry/admin/rebuild?rebuild_dedup=true&rebuild_weaviate=false&notify_workers=true
```

This endpoint (in `entity_registry_endpoint.py`):
1. Rebuilds the local worker's dedup index via `dedup_index.initialize(pool)`
2. Optionally runs a full Weaviate sync (`rebuild_weaviate=true`)
3. Sends a `reload_full` pg NOTIFY so all other workers also rebuild

**PostgreSQL NOTIFY `reload_full` action (implemented):**

The `_handle_dedup_notification` callback in `entity_dedup_ops.py` now handles
three actions: `add`, `remove`, and `reload_full`. On `reload_full`, each worker
calls `dedup_index.initialize(pool)` to do a complete rebuild from PostgreSQL.

```python
# Sending (via _notify_dedup_reload):
payload = json.dumps({'action': 'reload_full'})
await signal_manager._send_notification(CHANNEL_ENTITY_DEDUP, payload)

# Receiving (in _handle_dedup_notification):
if action == 'reload_full':
    count = await self.dedup_index.initialize(self.pool)
```

**Per-entity NOTIFY (existing, for small changes):**

The existing `_notify_dedup_change('add', entity_id)` mechanism remains for
single-entity changes during normal REST API operations.

**Worker restart (fallback):**

Since the dedup index is rebuilt from PostgreSQL on each worker startup
(`ensure_tables` → `initialize(pool)`), restarting the service after a bulk
load also works:

```bash
docker compose restart vitalgraph-app
```

### 4.4 Weaviate Staleness

After a bulk load, Weaviate will not contain the new entities until a sync is run.
This means:
- `search_entity` (semantic/topic search) won't find new entities
- `search_location` (geo search) won't find new locations
- All PostgreSQL-backed endpoints (entity CRUD, list, identifiers, etc.) work fine

The bulk load script's `--rebuild-weaviate` flag triggers the sync automatically.
Otherwise, run manually:

```bash
python entity_registry/entity_admin.py weaviate sync --full
```

---

## 5. Error Handling

### 5.1 Validation Errors

- **Unknown type_key** — report line number, skip or abort based on `--on-conflict`
- **Unknown category_key** — report and skip the category assignment
- **Malformed JSON** — report line number, skip the line
- **Missing required fields** — report and skip
- **Duplicate entity_id** — behavior depends on `--on-conflict`:
  - `skip` — `ON CONFLICT DO NOTHING`, log as skipped
  - `update` — `ON CONFLICT DO UPDATE SET ...`, log as updated
  - `error` — abort the batch

### 5.2 Error Tracking

Maintain an error log with:
- Line number in source file
- Error type (validation, insert, constraint violation)
- Record summary (entity_id or primary_name)
- Error message

Write error log to `--log-file` or stderr. Abort after `--max-errors` threshold.

### 5.3 Transaction Rollback

Each batch is a single transaction. If a batch fails:
1. Roll back the entire batch
2. Log all records in the batch as failed
3. Continue with the next batch (unless `--max-errors` exceeded)

---

## 6. Progress Reporting

```
Entity Bulk Load: entities.jsonl
──────────────────────────────────────────────────
Phase 1: Loading entities...
  [████████████████████░░░░░░░░░░]  68%  68,000/100,000  (3,400/sec)  ETA: 9s
  Entities inserted:   68,000
  Aliases inserted:    142,000
  Identifiers:         51,000
  Categories assigned: 89,000
  Locations:           34,000
  Errors:              12 (see errors.log)

Phase 2: Loading relationships...
  [████████████████████████████░░]  93%  9,300/10,000  (2,100/sec)
  Relationships:       9,300
  Skipped (not found): 42

Phase 3: Rebuilding indexes...
  Weaviate sync:       100,000 entities, 34,000 locations (45.2s)
  Dedup index:         100,000 entities (8.3s)
  NOTIFY reload_full sent to running workers

──────────────────────────────────────────────────
Complete: 100,000 entities, 10,000 relationships in 2m 15s
  Errors: 54 (see errors.log)
```

---

## 7. Performance Targets

| Scale | Entity File | Expected Time | Notes |
|-------|-------------|---------------|-------|
| Small | 1K entities | < 5s | Single batch, no index optimization |
| Medium | 10K entities | < 30s | Multiple batches |
| Large | 100K entities | < 5 min | Disable/rebuild indexes |
| Very Large | 1M entities | < 30 min | COPY FROM + index rebuild |

Bottlenecks in order:
1. PostgreSQL INSERT throughput (~5K-20K rows/sec with executemany)
2. Weaviate batch upsert (~2K-5K objects/sec)
3. Dedup index build (~10K entities/sec for in-memory)

---

## 8. Implementation Order

### Phase 1: Core bulk load (MVP)
1. JSONL entity parser with validation
2. Batch INSERT into entity + child tables via `executemany`
3. Entity ID generation (or pass-through if provided)
4. Progress reporting and error logging
5. `--dry-run` and `--validate-only` modes
6. Integration into `entity_admin.py` as `bulk-load` subcommand

### Phase 2: Relationships + index rebuild
1. JSONL relationship parser with reference resolution
2. Batch INSERT into `entity_relationship`
3. `--rebuild-weaviate` flag (calls existing `full_sync`)
4. `--rebuild-dedup` flag (calls existing `initialize`)

### Phase 3: Live service reload
1. Add `reload_full` action to `_handle_dedup_notification`
2. Send `reload_full` NOTIFY after bulk load
3. Optionally add admin REST endpoint for manual reload trigger
4. Document worker restart as fallback

### Phase 4: Performance optimization (large scale)
1. Index disable/rebuild for loads > 100K
2. `COPY FROM STDIN` path for entity table
3. Parallel batch processing (multiple connections)
4. Memory-mapped file reading for very large inputs

---

## 9. Testing Strategy

1. **Unit tests** — JSONL parser, validation, entity_id generation
2. **Integration tests** — small JSONL files (100 entities) loaded via the script,
   verify PostgreSQL contents match input
3. **Client-side tests** — extend existing `load_test_data.py` / `test_entity_registry_endpoint.py`
   to verify bulk-loaded entities appear in search and dedup results
4. **Scale tests** — generate 10K/100K synthetic JSONL files, measure throughput
5. **Live service tests** — load data while service is running, verify:
   - PostgreSQL queries return new entities immediately
   - Weaviate search finds new entities after sync
   - Dedup finds new entities after reload
   - No errors or crashes in running workers

---

## 10. Open Questions

1. **Should the bulk load support incremental/append mode?**
   If yes, `ON CONFLICT DO UPDATE` for entities that already exist, merging aliases
   and identifiers. If no, simpler `ON CONFLICT DO NOTHING` or `error`.

2. **Should we support CSV as an alternative input format?**
   JSONL is natural for nested data (aliases, locations). CSV would require a flattened
   schema or separate files per table. Recommend JSONL-only for v1.

3. **Should the export command produce JSONL compatible with bulk-load?**
   Yes — round-trip capability (`export → edit → bulk-load`) would be very useful.
   The existing `entity_admin.py export` already produces JSON; extending it to JSONL
   with nested aliases/identifiers/categories/locations would make it the inverse of
   bulk-load.

4. **Auto-creation of missing entity types, categories, location types?**
   If the input references a `type_key` that doesn't exist, should the loader create
   it automatically (with a `--auto-create-types` flag) or require pre-registration?
   Recommend: require pre-registration by default, `--auto-create-types` as opt-in.
