# emit_update.py: Lang-tagged literal UUID mismatch

## Status: FIXED

## Summary

Language-tagged literals inserted via `SPARQL INSERT DATA` produce a quad
whose `object_uuid` does NOT match the term inserted into the term dictionary.
This makes the data un-queryable via SELECT.

## Root Cause

In `vitalgraph/db/sparql_sql/emit_update.py`:

- **Term insertion** (`_emit_term_insert`, line ~189) uses
  `_generate_term_uuid(text, ttype, lang=lang, datatype_id=datatype_id)` which
  **includes** the lang tag in the UUID v5 hash.

- **Quad object_uuid** (`_term_uuid_subquery`, line ~210) falls into the
  fallback branch when `ttype == 'L'` and `datatype_id is None` (the case for
  plain lang-tagged literals). This branch does a text+type lookup:
  ```sql
  (SELECT term_uuid FROM {term_table}
   WHERE term_text = '...' AND term_type = 'L' LIMIT 1)
  ```
  This subquery does **not** filter by `lang`, and since the UUID was generated
  with lang in the hash, no row with a matching UUID exists in the quad.

## Reproduction

```sparql
INSERT DATA { <http://example.org/x> <http://example.org/label> "Hello"@en . }
SELECT ?label WHERE { <http://example.org/x> <http://example.org/label> ?label . }
-- Returns 0 rows
```

## Proposed Fix

In `_term_uuid_subquery`, when `ttype == 'L'` and the literal has a `lang`
parameter, compute the deterministic UUID using `_generate_term_uuid(text,
ttype, lang=lang)` and emit it as a literal `'<uuid>'::uuid` — same as the
typed datatype path. The fallback subquery should only be used when both `lang`
and `datatype_id` are None.

Alternatively, pass `lang` through to `_term_uuid_subquery` wherever it's
called from the INSERT DATA code path.

## Affected Tests

- `tests/integration/test_datatype_fidelity.py::TestLangTags` (4 tests, marked xfail)

## Severity

**High** — any lang-tagged literal inserted via SPARQL UPDATE is silently lost
(data is stored but never retrievable).

## Files

- `vitalgraph/db/sparql_sql/emit_update.py` (lines 201-218)
