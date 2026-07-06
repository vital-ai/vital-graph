# Issue #013: KGTypeDescriptionLookup uses wrong column names

## Status: FIXED

## Symptoms

`GET /api/graphs/kgtypes/description` returns 500 Internal Server Error with:
```
asyncpg.exceptions.UndefinedColumnError: column st.id does not exist
```

## Root Cause

`vitalgraph/vectorization/kgtype_description_lookup.py` uses legacy column names
that don't match the actual `SparqlSQLSchema` table definitions:

| Wrong (in file)   | Correct (schema)   |
|-------------------|-------------------|
| `st.id`           | `st.term_uuid`    |
| `q.subject_id`    | `q.subject_uuid`  |
| `q.predicate_id`  | `q.predicate_uuid`|
| `q.object_id`     | `q.object_uuid`   |
| `q.context_id`    | `q.context_uuid`  |
| `st.text`         | `st.term_text`    |
| `ot.type`         | `ot.term_type`    |
| `'literal'`       | `'L'`             |
| `'uri'` / `'iri'` | `'U'`            |

All four methods were affected:
- `get_subject_type_uri`
- `get_subject_type_uris_batch`
- `_fetch_description`
- `_fetch_descriptions_batch`

## Secondary Issue

`kgtypes_endpoint.py:_get_type_description_text` looked for the connection pool
at `getattr(backend, 'connection_pool', None)` or `getattr(backend, '_pool', None)`,
but the pool actually lives at `backend.db_impl.connection_pool`. Fixed to traverse
`backend.db_impl.connection_pool` correctly.

## Fix

- Updated all SQL in `kgtype_description_lookup.py` to use correct column names.
- Fixed pool lookup path in `kgtypes_endpoint.py`.
