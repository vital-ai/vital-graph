# CSV Import Drops Literal Datatypes and Computes Non-Canonical Term UUIDs

## Status: FIXED in the converter 2026-08-06 — existing CSV-loaded spaces need reloading

Two defects in `test_scripts/import/test_csv_import_process.py`, the converter
behind the bulk `.nt → CSV → COPY` load path. Both are silent: every load
reported success, row counts were correct, and reads mostly worked.

## Defect 1 — every literal lost its datatype

`datatype_id` was written as `''` (SQL NULL) in **both** term writers — the
two-pass `_generate_terms_csv` and the inline writer used by `uuid_only_quads`.

Root cause was one level deeper than the empty column. Datatype extraction read

```python
object_datatype = str(obj.datatype)     # '<http://www.w3.org/2001/XMLSchema#boolean>'
```

`str()` on a pyoxigraph `NamedNode` returns the **N-Triples serialization**, not
the URI. This is the same trap the file already documents for subjects and
predicates — the comment there explains it at length — reappearing one level
down on the datatype. The bracketed string matched no known datatype, so the
column stayed empty for every typed literal in every CSV-loaded space.

### Why it is not visible

The generator's numeric, boolean, and datetime companion columns are all gated
on the datatype:

```sql
CASE WHEN t.datatype_id IN (4, 11, 10, ...) AND t.term_text ~ '...'
     THEN CAST(t.term_text AS NUMERIC) END AS v__num
```

With `datatype_id` NULL the CASE yields NULL, so `WHERE v__num >= 65.0` is NULL
and the query returns **zero rows instead of failing**. Equality is unaffected —
it binds the object term directly and never consults the datatype.

Measured on the generated lead fixture, where the true counts are known exactly:

| criterion | comparator | expected | before fix | after fix |
|---|---|---|---|---|
| `mql` | eq (boolean) | 5,030 | 5,030 | 5,030 |
| `state_ca` | eq (text) | 908 | 908 | 908 |
| `high_rated` | **gte (numeric)** | 3,559 | **0** | 3,559 |

Only the range comparator exposed it. A fixture validated with equality checks
alone would have been declared good.

## Defect 2 — term uuids disagree with the runtime

`generate_term_uuid` hashed the datatype **URI**; vitalgraph's canonical
`emit_update._generate_term_uuid` hashes the integer **datatype_id**:

```python
parts = [term_text, term_type]
if lang is not None:        parts.append(f"lang:{lang}")
if datatype_id is not None: parts.append(f"datatype:{datatype_id}")
```

Four different uuids for `"true"^^xsd:boolean`:

```
2b7add47-83ba-519a-ad7d-cf3ca8ef53d6   runtime, datatype:2      ← canonical
521791b8-dad5-53a5-acbb-a2fd1fbb4b4c   converter, bracketed URI ← what CSV loads produced
dbd34433-debd-5df5-99e5-cb69a7e1b893   converter, bare URI
1aa5301d-46f8-5f3d-8947-34cb5ca68e90   no datatype component
```

Confirmed against live data: `sp_sql_lead_dataset` (loaded via the API import
path) holds `2b7add47…`; the CSV-loaded space held `521791b8…` for the same term.

### Why it is not visible

Reads resolve query constants by `(term_text, term_type)` lookup — the `_const`
CTE in the generated SQL — not by computing the uuid, so a CSV-loaded space is
internally consistent and answers queries correctly.

The damage is latent and appears on **write**. `emit_update`, `auto_sync` and the
backfill task all compute the canonical uuid, fail to find the CSV-loaded row,
and insert a *second* term row for the same literal. Existing quads point at the
old uuid and do not join to the new one. A space can therefore accumulate
duplicate terms and silently split literal identity, with no error at any point.

## Fix

Both in `test_scripts/import/test_csv_import_process.py`:

1. `object_datatype = obj.datatype.value` — the URI, not the serialization.
2. `generate_term_uuid` maps the datatype URI to its seeded `datatype_id` and
   hashes `datatype:{id}`, matching the runtime exactly. Verified identical:
   `2b7add47-83ba-519a-ad7d-cf3ca8ef53d6` from both.
3. `DATATYPE_IDS` is derived from `SparqlSQLSchema.STANDARD_DATATYPES` rather
   than hardcoded — `{space}_datatype` is a BIGSERIAL seeded from that list in
   order, so the id is its 1-based index, and a change to the seed list cannot
   silently desync the CSVs from the table. Unknown datatypes still fall back to
   NULL.

## Affected spaces

Any space loaded through the CSV path before 2026-08-06. Both known instances
have been reconverted and reloaded:

- `wordnet_frames` — 315,278 literal terms, all previously NULL datatype
- `sp_lead_synth` — 45,370 literal terms, now 45,370 typed

Spaces loaded through `data_import_impl` (the API import path) are unaffected —
that path uses the runtime's own term insertion.

**Worth checking whether the CSV path has ever been used against test or prod.**
If so those spaces carry non-canonical uuids for every typed literal and would
accumulate duplicate terms on write.

## Detection

```sql
-- literals with no datatype, in a space that should have typed values
SELECT count(*) FILTER (WHERE datatype_id IS NULL) AS untyped,
       count(*) AS literals
FROM {space}_term WHERE term_type = 'L';

-- canonical-uuid check for a known typed literal
SELECT term_uuid, datatype_id FROM {space}_term
WHERE term_text = 'true' AND term_type = 'L';
-- expect uuid5(NS, 'true' || chr(0) || 'L' || chr(0) || 'datatype:2')
```

## Related

- `issues/041_in_place_reload_leaves_derived_tables_stale.md` — the other silent
  failure in the bulk load path, found in the same session
- `planning/planning_performance/kgquery_o_page_paging_generator_plan.md` — step
  1, the fixture whose acceptance check surfaced this
