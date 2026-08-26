# Migration Plan — v0.0.39 → next release

**Surveyed 2026-08-26** against the live PG 18.4 cluster (`NEW_PROD_DB_*`).
466 commits since `v0.0.39` (2026-08-12). All ten migration scripts were added
or changed in that window, plus 14 commits to `sparql_sql_schema.py`.

Nothing in the most recent work needs a migration: the term-typing fix changes
LOOKUPS, not stored identity, and `named_graph_semantics` §4.2 deliberately
leaves existing `urn:default` catalog rows in place. Everything below predates
that.

## The live cluster

| space | quads | terms | term table |
|---|---|---|---|
| (largest) | 42,508,064 | 7,586,500 | 3,020 MB |
| `lead_data` | 21,510,588 | 3,412,852 | 1,102 MB |
| `lead_prod` | 8,996,876 | 1,546,787 | 526 MB |
| `sp_kg_types` | 0 | 0 | 72 kB |
| `testspace` | 0 | 0 | 48 kB |

## What is needed

| # | migration | scope | why | cost |
|---|---|---|---|---|
| 1 | `migrate_space_schema` | all 5 | every space lacks `rdf_value_stats`; `testspace` also lacks `vector_index`, `fuzzy_band`, `geo`, `geo_config` | seconds — `CREATE TABLE IF NOT EXISTS` |
| 2 | `migrate_term_num_index` | all 5 | **REQUIRED.** The push-down emits `num_val >= t`; without the column the query fails with `column "num_val" does not exist` | table rewrite under ACCESS EXCLUSIVE |
| 3 | `migrate_term_datetime_column` | all 5 | `dt_val`, same shape as 2 | same |
| 4 | `migrate_edge_type_column` | all 5 | `edge_type_uuid` + backfill | add is fast; backfill scales with edges |
| 5 | `migrate_frame_entity_type_column` | all 5 | `frame_type_uuid` + backfill | same |
| 6 | `migrate_quad_pk_dedup` | 3 populated | PK is still the old 5-column `(s,p,o,c,quad_uuid)`. **Duplicate quads confirmed present in all three.** | the expensive one — see below |
| 7 | `migrate_value_stats_pred_rows` | after 1 | `pred_rows`; moot until `rdf_value_stats` exists | seconds |

## Not needed — verified, do not run

- **`migrate_quad_ctx_pred_index`** — the four real spaces already have
  `object_uuid` as a key column. Only empty `testspace` lacks the index, and
  step 1 creates it.
- **`migrate_vector_index_columns`** — `distance_metric` and `description` are
  present on all four spaces that have the table.
- **`migrate_geo_config_defaults`** — `geo_config` exists everywhere except
  `testspace`, which step 1 handles.

## Sizing, and the honest gaps

`migrate_term_num_index` was measured at **3m16s for 10.4M terms**. Scaled:
~2-3 min for the largest, ~1 min, ~30 s, instant, instant. `ADD COLUMN ...
STORED` rewrites the table under **ACCESS EXCLUSIVE** — writes to that space
block for the duration. It is not an online migration.

**`migrate_quad_pk_dedup` is unsized.** Duplicates are confirmed present in all
three populated spaces — a `LIMIT 1` probe finds them immediately — but the
exact count is unknown: `SELECT count(DISTINCT ...)` over 42.5M rows exceeded a
600 s statement timeout. **Size this before scheduling the window**, on a
restored snapshot rather than live. The proportion decides whether this is a
minutes job or an hours job, and there is no way to know from here.

Why it matters beyond tidiness: `quad_uuid` defaults to `gen_random_uuid()`, so
an identical quad got a fresh key and never conflicted — every
`ON CONFLICT DO NOTHING` on this table has been a no-op. Re-inserting an
existing quad returns `INSERT 0 1`. That is why the duplicates are there.

## Order

1. **`migrate_space_schema`** on all 5 — cheap, creates missing tables, and
   step 7 depends on it.
2. **`migrate_quad_pk_dedup`** on the three populated spaces — do this BEFORE
   the column adds. It removes rows, so every later rewrite has less to copy,
   and the dedup itself gets no cheaper by waiting.
3. **`migrate_term_num_index`**, then **`migrate_term_datetime_column`** — the
   two ACCESS EXCLUSIVE rewrites, back to back inside one window per space.
4. **`migrate_edge_type_column`**, **`migrate_frame_entity_type_column`** —
   add + backfill.
5. **`migrate_value_stats_pred_rows`**.
6. `ANALYZE` each space afterwards. Steps 2-4 change table shape and row
   counts; stale statistics after a rewrite is how a plan flips silently
   (`issues/112`, `issues/119`).

## Deployment coupling — the sharpest risk

**The app and the Jena sidecar must ship together.** The Python side now sends
`baseURI` in the compile request, and an older sidecar has
`@JsonIgnoreProperties(ignoreUnknown = true)` — it will ignore the field
silently. Relative IRIs would stop resolving, with no error, no log and no
failed health check: the service would simply return wrong answers.

There is no version negotiation between them. If they can skew, add one.

## Verification after each step

    tests/api, tests/conformance, tests/unit, tests/integration   0 failures
    tests/performance                                             0 failures

CI runs only `tests/unit` plus a corpus-presence check, so a green build does
not cover any of this.
