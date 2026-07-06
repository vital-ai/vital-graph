# Entity search type_key filter: wrong SQL table alias

## Summary

The `search_topic`, `search_hybrid`, and `search_topic_near` methods in
`EntityRegistrySearch` generate SQL that references `e.type_key`, but
`type_key` is a column on the `entity_type` table (aliased `et`), not on the
`entity` table (aliased `e`). Any search request with a `type_key` filter
returns a 500 Internal Server Error.

## Root Cause

In `vitalgraph/entity_registry/entity_registry_search.py`, three methods
build a filter clause with the wrong alias:

```python
# Line 66 (search_topic)
filters.append(f"e.type_key = ${param_idx}")

# Line 158 (search_hybrid)
filters.append(f"e.type_key = ${param_idx}")

# Line 533 (search_topic_near)
filters.append(f"e.type_key = ${param_idx}")
```

The SQL JOINs `entity_type et ON et.type_id = e.entity_type_id`, so the
column must be referenced as `et.type_key`.

PostgreSQL confirms:
```
asyncpg.exceptions.UndefinedColumnError: column e.type_key does not exist
HINT:  Perhaps you meant to reference the column "et.type_key".
```

## Reproduction

```
GET /api/registry/search/entity?q=consulting&type_key=person&min_certainty=0.3&limit=10
→ 500 Internal Server Error
```

Without `type_key`, the same endpoint works fine:
```
GET /api/registry/search/entity?q=consulting&min_certainty=0.3&limit=10
→ 200 OK
```

## Fix

Change `e.type_key` → `et.type_key` in all three locations (lines 66, 158, 533).

Applied in commit: `entity_registry_search.py` — `replace_all` edit.

## Severity

**Medium** — all type-filtered entity searches (semantic, hybrid, and
semantic+geo) are broken. The `/api/registry/search/entity` endpoint is
unusable when `type_key` is provided.

## Affected Tests

- `tests/api/test_registry_search_api.py::TestEntityRegistrySearch::test_entity_search_type_filter`
  (currently marked `xfail`; remove marker after server redeploy)

## Files

- `vitalgraph/entity_registry/entity_registry_search.py` (lines 66, 158, 533)
