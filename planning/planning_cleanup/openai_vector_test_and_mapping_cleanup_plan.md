# OpenAI End-to-End Vector Test & Mapping/Index Endpoint Cleanup

> **Created**: Jul 2026
> **Status**: Planned
> **Related**: `integration_workflow_tests_plan.md` §3.1, `search_ui_plan.md`, `vector_geo_plan.md` §7.1

---

## 1. Problem Statement

Two issues exist with the current vector integration tests:

1. **OpenAI test never validated**: `tests/api/test_openai_vector_integration.py` exists
   but has never been run end-to-end. It skips without `OPENAI_API_KEY`, and the Docker
   container doesn't receive the key even when set on the host.

2. **Wrong endpoint pattern**: Multiple tests use the legacy `vector_mappings` endpoint
   (`vg_client.vector_mappings.create_mapping(index_name=...)`) which relies on the old
   `{space}_vector_mapping` table with a direct FK to `vector_index`. The correct
   architecture uses `search_mappings` + the `search_mapping_index` junction table,
   where mappings are created first and indexes are attached to them.

---

## 2. Correct Architecture (from `search_ui_plan.md`)

### 2.1 Workflow Order

1. **Create mapping** — defines WHAT to vectorize (mapping_type, source_type, properties)
2. **Create index** — defines the embedding target (provider, dimensions, model)
3. **Attach index to mapping** — links them via `search_mapping_index` junction table

### 2.2 Tables

| Table | Role |
|-------|------|
| `{space}_search_mapping` | Primary entity: what to vectorize |
| `{space}_search_mapping_property` | Child properties feeding the mapping |
| `{space}_search_mapping_index` | Junction: links mapping → concrete index |
| `{space}_vector_index` | Index registry: provider, dimensions, model |

### 2.3 Endpoints (Correct)

```
POST /api/search-mappings?space_id=X              — create mapping
POST /api/search-mappings/{id}/indexes?space_id=X — attach index to mapping
POST /api/vector-indexes?space_id=X               — create vector index
```

### 2.4 Client Methods (Correct)

```python
mapping = await vg_client.search_mappings.create_mapping(
    space_id=..., index_name=..., mapping_type="kgentity",
    source_type="properties", enabled=True,
)
index = await vg_client.vector_indexes.create_index(
    space_id=..., index_name=..., dimensions=1536,
    provider="openai", model_name="text-embedding-3-small",
    provider_config={"api_key_env": "OPENAI_API_KEY"},
)
await vg_client.search_mappings.add_index(
    space_id=..., mapping_id=mapping.mapping_id,
    index_type="vector", index_name=index.index_name,
)
```

---

## 3. Legacy Endpoint to Remove

### 3.1 Files

| File | Purpose | Action |
|------|---------|--------|
| `vitalgraph/endpoint/vector_mappings_endpoint.py` | Legacy server endpoint | Remove |
| `vitalgraph/client/endpoint/vector_mappings_endpoint.py` | Legacy client endpoint | Remove |
| `vitalgraph/model/vector_mappings_model.py` | Legacy Pydantic models | Remove (if separate) |

### 3.2 Legacy Table

```sql
{space}_vector_mapping (
    mapping_id SERIAL PRIMARY KEY,
    mapping_type VARCHAR(50),
    type_uri VARCHAR(500),
    index_name VARCHAR(255) REFERENCES {space}_vector_index(index_name),  -- direct FK
    ...
)
```

This table has a direct FK from mapping → index, requiring the index to exist first.
The new `search_mapping_index` junction table inverts this: mappings exist independently
and indexes are attached afterward.

### 3.3 Dependents to Migrate

Files that import or reference `vector_mappings`:

- `tests/api/test_openai_vector_integration.py`
- `tests/api/test_kgtypes_entity_integration.py`
- `tests/api/test_integration_workflows.py`
- `vitalgraph/client/vitalgraph_client.py` (registers `vector_mappings` endpoint)
- `vitalgraph/api/vitalgraph_api.py` (registers the router)
- Any other test or script calling `vg_client.vector_mappings.*`

---

## 4. OpenAI End-to-End Test Fix

### 4.1 Docker Container Must Receive API Key

Add to `docker-compose.yml`:
```yaml
services:
  vitalgraph:
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```

Or via `.env` file already referenced by `docker-compose.yml`.

### 4.2 Rewrite Test to Use Correct Endpoints

Replace:
```python
# WRONG (legacy)
await vg_client.vector_indexes.create_index(...)
await vg_client.vector_mappings.create_mapping(index_name=...)
```

With:
```python
# CORRECT
mapping = await vg_client.search_mappings.create_mapping(
    space_id=..., index_name="openai_test",
    mapping_type="kgentity", source_type="properties", enabled=True,
)
await vg_client.vector_indexes.create_index(
    space_id=..., index_name="openai_test", dimensions=1536,
    provider="openai", model_name="text-embedding-3-small",
    provider_config={"api_key_env": "OPENAI_API_KEY"},
)
await vg_client.search_mappings.add_index(
    space_id=..., mapping_id=mapping.mapping_id,
    index_type="vector", index_name="openai_test",
)
```

### 4.3 Validate End-to-End

1. Set `OPENAI_API_KEY` on host and in Docker container
2. Rebuild container: `docker compose up --build -d`
3. Run test: `pytest tests/api/test_openai_vector_integration.py -v`
4. Confirm:
   - Reindex calls OpenAI API (check server logs for `OpenAIProvider initialized`)
   - Vectors stored with 1536 dimensions
   - Semantic search returns correct rankings

---

## 5. Migrate All Tests to `search_mappings`

### 5.1 `test_kgtypes_entity_integration.py`

Currently:
```python
await vg_client.vector_indexes.create_index(space_id=..., index_name=INDEX_NAME, ...)
mapping = await vg_client.vector_mappings.create_mapping(
    space_id=..., index_name=INDEX_NAME, mapping_type="kgentity",
    source_type="type_description", enabled=True,
)
```

Migrate to:
```python
mapping = await vg_client.search_mappings.create_mapping(
    space_id=..., index_name=INDEX_NAME, mapping_type="kgentity",
    source_type="type_description", enabled=True,
)
await vg_client.vector_indexes.create_index(space_id=..., index_name=INDEX_NAME, ...)
await vg_client.search_mappings.add_index(
    space_id=..., mapping_id=mapping.mapping_id,
    index_type="vector", index_name=INDEX_NAME,
)
```

### 5.2 `test_integration_workflows.py`

Same pattern — find any `vg_client.vector_mappings.*` calls and replace.

### 5.3 `test_openai_vector_integration.py`

Full rewrite per §4.2 above.

---

## 6. Implementation Order

| # | Task | Priority |
|---|------|----------|
| 1 | Migrate `test_kgtypes_entity_integration.py` to `search_mappings` | High |
| 2 | Migrate `test_integration_workflows.py` to `search_mappings` | High |
| 3 | Rewrite `test_openai_vector_integration.py` with correct order | High |
| 4 | Pass `OPENAI_API_KEY` through Docker container | High |
| 5 | Run OpenAI test end-to-end and validate | High |
| 6 | Search codebase for remaining `vector_mappings` references | Medium |
| 7 | Remove legacy `vector_mappings_endpoint.py` (server + client) | Medium |
| 8 | Remove or deprecate `{space}_vector_mapping` table creation from schema | Low |
| 9 | Verify no frontend code references the old endpoint | Medium |

---

## 7. Verification

After all changes:

```bash
# Run all integration tests
pytest tests/api/ -v --tb=short

# Specifically validate OpenAI (requires key)
OPENAI_API_KEY=sk-... pytest tests/api/test_openai_vector_integration.py -v

# Confirm no references to old endpoint remain
grep -r "vector_mappings" vitalgraph/ tests/ --include="*.py" | grep -v "__pycache__"
```

---

## 8. Architectural Clarification

**The vector mapping functionality is fully preserved** — it is not removed, only unified
under the general `search_mappings` endpoint. The old `vector_mappings` endpoint was a
single-purpose CRUD that created mappings with a direct FK to a vector index. The new
`search_mappings` endpoint provides the same mapping lifecycle (create, update, delete,
add/remove properties) but uses a junction table (`search_mapping_index`) to associate
one or more indexes (vector or FTS) with a mapping.

| Operation | Old (`vector_mappings`) | New (`search_mappings`) |
|-----------|------------------------|------------------------|
| Create mapping | `POST /api/vector-mappings` | `POST /api/search-mappings` |
| CRUD (get/update/delete) | `/api/vector-mappings/{id}` | `/api/search-mappings/{id}` |
| Add/remove property | `/api/vector-mappings/{id}/properties` | `/api/search-mappings/{id}/properties` |
| Link to vector index | Implicit (FK on mapping row) | Explicit: `POST /api/search-mappings/{id}/indexes` |
| Link to FTS index | Not supported | Same `add_index` with `index_type="fts"` |

The only behavioral difference: index attachment is now **explicit** via `add_index()`
rather than implicit via a foreign key on the mapping row. This enables a single mapping
to be backed by multiple index types (e.g., both vector and FTS for hybrid search).

---

## 9. Known Issue: `resp.get()` on Pydantic Models

Some client endpoints were migrated from returning raw `Dict` to typed Pydantic response
models (e.g., `DeleteResponse`). Tests that use `resp.get("field")` on these typed responses
get `AttributeError` because Pydantic models don't support `.get()`.

**Fix:** Replace `resp.get("field")` with `resp.field` attribute access.

### Verified status:

| File | Status | Notes |
|------|--------|-------|
| `tests/api/test_mappings_api.py` (search_mappings) | ✅ Fixed | `delete_mapping` / `remove_property` return `DeleteResponse` model |
| `tests/api/test_mappings_api.py` (fuzzy_mappings) | ✅ OK | `fuzzy_mappings` client still returns raw `Dict` — `.get()` is valid |
| `tests/api/test_agent_registry_api.py` | ✅ OK | Client returns raw `Dict[str, Any]` — `.get()` is valid |
| `tests/api/test_kgdocuments_api.py` | ✅ OK | Client returns raw `Dict` — `.get()` is valid |
| `tests/api/test_users_api.py` | ✅ OK | `get_user_spaces` returns raw `Dict[str, Any]` — `.get()` is valid |

### Resolved: Agent Registry schema mismatch + JSONB parsing

`test_agent_registry_api.py` was failing due to two issues:

1. **Missing DB columns** — `protocol_config`, `transport_config`, `output_schema`, `notes`
   had been added to the schema definition but not to existing databases.
   - **Fix:** Reordered `apps/agent_registry/migrate_agents.py` to run `ALTER TABLE ... ADD
     COLUMN IF NOT EXISTS` **before** index creation (indexes reference those columns).
     Added `DROP VIEW IF EXISTS` before view recreation to handle column changes.

2. **asyncpg JSONB returned as strings** — asyncpg does not auto-decode JSONB without a
   registered codec. The endpoint layer was passing raw string values (e.g., `'{}'`) into
   Pydantic models expecting `Dict`.
   - **Fix:** Added `_parse_jsonb()`, `_endpoint_to_response()`, and
     `_function_to_response()` helpers in `vitalgraph/agent_registry/agent_endpoint.py`.
     All response construction now parses JSONB strings via `json.loads()`. Also applied
     to `change_detail` in the changelog route and to `_agent_to_response()` for
     `auth_service_config`, `capabilities`, `metadata`, `protocol_config`.

**Status:** ✅ All 12 agent registry tests pass.

---

## 10. Notes

- The `search_mappings.create_mapping()` endpoint also takes an `index_name` parameter,
  but this is the mapping's **logical name** (used in SPARQL `vg:vectorSimilarity(?e, text, "name", k)`),
  NOT a reference to a vector_index row. The actual vector index linkage happens via `add_index()`.
- The `vector_populator.py` already resolves provider from `vector_index` table — no change
  needed there. It just needs the junction table to find which index backs a mapping.
- The `auto_sync` path also uses `search_mapping` resolution — confirm it works with the
  junction table after removing the legacy path.
