# Entity Registry URL Refactor — Remove Path IDs

## Goal

Move **all** IDs and keys out of URL path segments and into query parameters. No identifiers of any kind appear in the URL path — only fixed route segments.

## Rationale

- Consistent URL structure across all endpoints
- Easier to extend filters without new routes
- Avoids URL-encoding edge cases with identifier values
- Cleaner reverse proxy / gateway configuration

---

## Current → Proposed Routes

### Entity CRUD

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `POST /entities` | `POST /entities` | *(no change)* |
| `GET /entities` | `GET /entities` | *(no change — already uses query params)* |
| `GET /entities/{entity_id}` | `GET /entities/get?entity_id=X` | `entity_id` → query |
| `PUT /entities/{entity_id}` | `PUT /entities/update?entity_id=X` | `entity_id` → query |
| `DELETE /entities/{entity_id}` | `DELETE /entities/delete?entity_id=X` | `entity_id` → query |

### Identifiers

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `POST /entities/{entity_id}/identifiers` | `POST /identifiers/add?entity_id=X` | `entity_id` → query |
| `GET /entities/{entity_id}/identifiers` | `GET /identifiers/list?entity_id=X` | `entity_id` → query |
| `DELETE /identifiers/{identifier_id}` | `DELETE /identifiers/remove?identifier_id=X` | `identifier_id` → query |
| `GET /lookup` | `GET /identifiers/lookup` | *(rename only — already uses query params)* |

### Aliases

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `POST /entities/{entity_id}/aliases` | `POST /aliases/add?entity_id=X` | `entity_id` → query |
| `GET /entities/{entity_id}/aliases` | `GET /aliases/list?entity_id=X` | `entity_id` → query |
| `DELETE /aliases/{alias_id}` | `DELETE /aliases/remove?alias_id=X` | `alias_id` → query |

### Categories

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `GET /categories` | `GET /categories` | *(no change)* |
| `POST /categories` | `POST /categories` | *(no change)* |
| `GET /entities/{entity_id}/categories` | `GET /categories/entity?entity_id=X` | `entity_id` → query |
| `POST /entities/{entity_id}/categories` | `POST /categories/assign?entity_id=X` | `entity_id` → query |
| `DELETE /entities/{entity_id}/categories/{category_key}` | `DELETE /categories/remove?entity_id=X&category_key=Y` | both → query |
| `GET /categories/{category_key}/entities` | `GET /categories/entities?category_key=X` | `category_key` → query |

### Same-As

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `POST /same-as` | `POST /same-as` | *(no change)* |
| `GET /entities/{entity_id}/same-as` | `GET /same-as/list?entity_id=X` | `entity_id` → query |
| `PUT /same-as/{same_as_id}/retract` | `PUT /same-as/retract?same_as_id=X` | `same_as_id` → query |
| `GET /entities/{entity_id}/resolve` | `GET /same-as/resolve?entity_id=X` | `entity_id` → query |

### Entity Types

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `GET /entity-types` | `GET /entity-types` | *(no change)* |
| `POST /entity-types` | `POST /entity-types` | *(no change)* |

### Change Log

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `GET /entities/{entity_id}/changelog` | `GET /changelog/entity?entity_id=X` | `entity_id` → query |
| `GET /changelog` | `GET /changelog` | *(no change)* |

### Search

| Current | Proposed | Changed Params |
|---------|----------|----------------|
| `GET /similar` | `GET /search/similar` | *(rename for consistency)* |
| `GET /search/topic` | `GET /search/topic` | *(no change)* |

---

## Summary of Changes

- **20 endpoints affected** (out of 28 total)
- **8 endpoints unchanged** (already use only query params or have no path IDs)
- **0 path parameters remain** after refactor

## Files to Modify

### Server-side
1. `vitalgraph/endpoint/entity_registry_endpoint.py` — all route decorators + handler signatures
2. `vitalgraph/model/entity_registry_model.py` — no changes expected (models are body/response only)

### Client-side
3. `vitalgraph/client/endpoint/entity_registry_endpoint.py` — all `_url()` calls + `params` dicts

### Tests
4. `vitalgraph_client_test/test_entity_registry_endpoint.py` — should need no changes (uses client methods, not raw URLs)
5. `vitalgraph_client_test/load_test_data.py` — should need no changes (uses client methods)
6. `vitalgraph_client_test/cleanup_test_data.py` — uses direct SQL, no changes

### Documentation
7. `docs/entity_registry.md` — update all endpoint tables
8. `planning_fuseki/entity_registry_plan.md` — update endpoint reference

---

## Implementation Steps

1. Update server route decorators — replace `{param}` paths with flat paths + `Query()` params
2. Update client endpoint — change `_url(f"/entities/{entity_id}")` to `_url("/entities/get")` with `params={"entity_id": entity_id}`
3. Run full test suite — verify 88/88 still pass
4. Update docs

## Migration / Backward Compatibility

Options:
- **Hard cut**: Change all routes at once. Client and server deploy together.
- **Soft migration**: Add new routes alongside old ones, deprecate old with warning header, remove after N releases.

Recommended: **Hard cut** — this is an internal API with a single client. No external consumers to coordinate with.
