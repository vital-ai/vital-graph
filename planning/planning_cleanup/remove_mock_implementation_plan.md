# Plan: Remove Mock Implementation

**Date:** 2026-06-28
**Status:** ✅ Complete

---

## Goal

Remove the pyoxigraph-backed mock client implementation and its associated test
scripts. Replace with real-backend testing (PG + FastAPI) which provides higher
fidelity and eliminates the maintenance burden of keeping two implementations in sync.

---

## What Gets Removed

### Mock client implementation (`vitalgraph/mock/`)

| File | Size | Description |
|------|------|-------------|
| `mock/client/mock_vitalgraph_client.py` | 23K | Main mock client class |
| `mock/client/endpoint/` (16 files) | ~150K total | Mock endpoint implementations (entities, frames, types, objects, files, relations, documents, query, etc.) |
| `mock/client/space/` (5 files) | ~30K | Mock space/graph management |
| `mock/__init__.py` | — | Package file |

**Total:** ~24 files, ~200K of code that must be kept in sync with the real implementation.

### Mock client tests (`vitalgraph_mock_client_test/`)

| Item | Count | Description |
|------|-------|-------------|
| Test scripts | ~33 files | End-to-end tests against the mock |

### Backend config references

| File | Change |
|------|--------|
| `vitalgraph/db/backend_config.py` | Remove `BackendType.MOCK` enum value and factory branch |
| `vitalgraph/db/mock/` | Delete (empty `__init__.py` only) |

---

## Why Remove

1. **Maintenance burden** — Every new feature requires dual implementation (real + mock). History shows repeated debugging sessions to fix mock inconsistencies (entity_type_uri filtering, VitalSigns CombinedProperty issues, frameGraphURI assignment, JSON-LD context handling, etc.).

2. **False confidence** — Tests passing against pyoxigraph don't prove the real SPARQL-to-SQL pipeline works. The mock uses a completely different code path (pyoxigraph SPARQL vs. PostgreSQL SQL).

3. **Always out of sync** — The mock lacks features the real backend has: vector search, FTS, geo queries, auxiliary table rewrites, term caching, bulk operations, concurrency handling.

4. **PG is cheap to run** — `docker run postgres:17` or a CI service container. The testing plan already requires PG for Tier 2–4.

5. **No unique value** — Tier 1 unit tests need no backend. Tier 2–4 tests need the real backend. There's no testing tier where the mock is the right tool.

---

## Replacement Strategy

### For integration tests (currently using mock)

Use the real FastAPI app with a test PostgreSQL database:

```python
# tests/conftest.py
import httpx
from vitalgraph.impl.vitalgraphapp_impl import create_app

@pytest.fixture(scope="session")
async def app():
    """Create real VitalGraph app against test PG database."""
    app = create_app(config_path="tests/vitalgraphdb-test-config.yaml")
    async with app.lifespan():
        yield app

@pytest.fixture
async def client(app):
    """HTTP client against the real app (no network, ASGI transport)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client
```

This gives:
- **Full fidelity** — Tests exercise the real SPARQL-to-SQL pipeline
- **No network** — ASGI transport is in-process, fast
- **Isolated** — Each test gets a temp space, cleaned up after
- **No maintenance** — No second implementation to keep in sync

### For client-side unit tests

If any tests need to verify client serialization/deserialization without a backend:
- Use `respx` or `httpx` mock transport to return canned JSON responses
- These are simple HTTP-level mocks, not a full backend reimplementation

---

## Execution Steps

### Phase 1: Audit mock test coverage

1. List all test scenarios in `vitalgraph_mock_client_test/`
2. Identify which scenarios already have coverage in `vitalgraph_client_test/` (real backend)
3. Identify unique scenarios that need porting to real-backend tests

### Phase 2: Port unique test scenarios

4. Create equivalent tests using `httpx.ASGITransport` + real PG
5. Verify they pass against the real backend

### Phase 3: Remove mock code

6. Delete `vitalgraph/mock/` directory
7. Delete `vitalgraph_mock_client_test/` directory
8. Delete `vitalgraph/db/mock/` (empty `__init__.py`)
9. Remove `BackendType.MOCK` from `backend_config.py`
10. Remove any imports referencing the mock in other files
11. Update `planning/planning_cleanup/codebase_cleanup_plan.md` references

### Phase 4: Verify

12. Run full test suite — confirm no imports break
13. Confirm CI passes
14. Update documentation

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Losing test scenarios | Phase 1 audit before deletion |
| Breaking imports | grep for `from vitalgraph.mock` and `from vitalgraph.db.mock` |
| Developer workflow disruption | Document the `httpx.ASGITransport` pattern as the replacement |

---

## Effort Estimate

| Phase | Effort |
|-------|--------|
| Audit | 1 hour |
| Port unique scenarios | 2–4 hours (depending on count) |
| Remove code | 30 min |
| Verify + document | 30 min |
| **Total** | **4–6 hours** |

---

## Dependencies

- PostgreSQL available for tests (already required by testing plan)
- `httpx` with ASGI transport (already a dependency)
- Testing plan Phase 1 (test foundation) should be in place first, or this can be done concurrently
