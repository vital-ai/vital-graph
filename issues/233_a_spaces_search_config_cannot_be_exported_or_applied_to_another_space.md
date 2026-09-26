# 233 — A space's search config cannot be exported, or applied to another space

## Status: OPEN — capability request, raised 2026-09-24. NOTHING BUILT.
## `bulk_export` exports three tables and none of them are config.

**Related:** `issues/232` (rename a space — the other half of the workflow),
`vitalgraph/db/sparql_sql/bulk_export.py` (the existing export, and the gap),
`issues/219` (auto-sync ignoring the mapping — why mapping fidelity is not
cosmetic), `issues/217` (FTS rows orphaned by a bulk delete)

## The request

> Export the config of a space — mainly the mapping data for its indexes — and
> import or apply that config to a given space.

With `issues/232` the workflow is: rename `data` to `data_orig`, create a new
`data`, and apply `data_orig`'s config to it, so the replacement has the same
FTS and vector mappings as the original without anyone re-entering them.

## Why this is not just convenience

The config IS the search behaviour. A space with the same data and different
mappings answers differently, and the difference is silent — there is no error,
just fewer or different hits. Three things in the recent record make that
concrete:

  * `issues/219`: auto-sync ignored the mapping entirely and embedded the wrong
    text. Nothing failed; the vectors were simply wrong.
  * `source_type` on a search mapping flips from `default` to `properties` as a
    SIDE EFFECT of adding a property. Rebuilding a config by replaying API
    calls in the obvious order therefore does not reproduce it — this was hit
    while cloning search config between spaces earlier in this work and had to
    be corrected with an explicit `PUT` afterwards.
  * Dev and prod both have at most ONE FTS-indexed slot per frame, so mapping
    shape is not yet stressed by production data — meaning a fidelity bug here
    would not show up until it does.

Re-entering a config by hand is therefore not a workaround; it is a source of
differences nobody can see.

## What "the config" actually is

Nine per-space tables. All are named `{space_id}_{suffix}` and all are keyed by
the space id IN THE TABLE NAME — there is no numeric space key anywhere, and
`space.space_id` is itself the primary key (`sparql_sql_schema.py:351-359`).

| table | what it holds | DDL |
|---|---|---|
| `{s}_vector_index` | index registry: `index_name`, `dimensions`, `distance_metric`, `provider`, `model_name`, `provider_config JSONB` | `:1397-1409` |
| `{s}_fts_index` | `index_name`, `languages`, `rank_normalization` | `:1529-1546` |
| `{s}_search_mapping` | `mapping_type`, `type_uri`, `index_name`, `enabled`, **`source_type`**, `separator`, `include_pred_name` | `:1488-1500` |
| `{s}_search_mapping_property` | `property_uri`, `property_role`, `ordinal`, FK → `search_mapping` | `:1503-1513` |
| `{s}_search_mapping_index` | mapping ↔ index junction, `index_type IN ('vector','fts')` | `:1516-1526` |
| `{s}_fuzzy_mapping` | `shingle_k`, `num_perm`, `lsh_threshold`, `phonetic_bonus` | `:1459-1472` |
| `{s}_fuzzy_mapping_property` | FK → `fuzzy_mapping` | `:1475-1485` |
| `{s}_geo_config` | `enabled`, `auto_sync`, `geo_datatype_uris`, lat/lon predicates | `:1413-1438` |
| `{s}_document_segmentation_config` | `document_type_uri`, `segment_method_uri`, token limits, `auto_vectorize` | `:1600-1613` |

**The good news is that the rows are almost portable.** Because the space id
lives in the table NAME rather than in the rows, dumping these tables and
loading them into another space needs no space-id rewriting inside the data —
with one exception, `{s}_segmentation_jobs.space_id` (`:1586`), which stores
the id as a value. That is job state rather than config and should not be
exported at all.

## The three things that make this harder than a table dump

### 1. `mapping_id` is a local SERIAL, and two tables reference it

`search_mapping_property` and `search_mapping_index` both carry
`mapping_id` FKs. Those ids are only unique within the source space's own
table, so an import must REMAP them — allocate new ids in the target and
rewrite the children — rather than preserving them. The same applies to
`fuzzy_mapping` / `fuzzy_mapping_property`.

Preserving source ids happens to work when the target is empty and breaks the
moment it is not, which is the worst possible failure schedule: it passes every
test written against a fresh space and corrupts the first real one.

### 2. The target is never empty

Creating a space already bootstraps config. `bootstrap_space_extras`
(`:2120-2169`) calls `setup_document_segments_vectorization`
(`document/vector_index_setup.py:32-212`), which creates
`{s}_vec_document_segments`, its `{s}_vector_index` row, AND its
`{s}_search_mapping` + `{s}_search_mapping_property` rows. Then for every row
in `{s}_vector_index` it calls `ensure_fts_index`
(`vectorization/fts_index_lifecycle.py:26-81`), creating `{s}_fts_{name}`, its
three indexes, a trigger function, a trigger, and an `{s}_fts_index` row.

So "apply `data_orig`'s config to the new `data`" always means RECONCILING
against config that already exists, not inserting into a vacuum. The import
needs a stated semantics — merge, or replace — and `replace` has to drop the
physical `_vec_`/`_fts_` tables and their triggers for indexes it removes, or
it leaves tables nothing references.

### 3. Config implies physical objects, not just rows

An imported `{s}_vector_index` row without its `{s}_vec_{name}` table is a
registry entry pointing at nothing. A faithful import must create the physical
index tables, their indexes, the FTS trigger function and trigger — i.e. call
the same lifecycle code paths the endpoints call, rather than writing rows
directly. Writing rows directly is the obvious implementation and produces a
config that looks right in every listing and does not work.

And the imported indexes start EMPTY. Applying a config does not vectorize or
populate anything; the target needs a backfill afterwards, and the export
should probably record enough for the caller to know that (source row counts,
the model each index was built with).

## What exists today, and why it does not cover this

`bulk_export.export_space` / `import_space` (`bulk_export.py:43,120`) is the
nearest thing. It binary-`COPY`s exactly three tables —

    _EXPORT_TABLES = ("datatype", "term", "rdf_quad")        # :32

— writes a `manifest.json` with the space id and a snapshot watermark, and on
import TRUNCATEs those tables, fixes the `datatype_id` sequence, re-registers
graphs, then resyncs `edge` and `frame_slot`. **It touches no config table at
all.** So a `bulk_export` round trip today moves the data and silently drops
every index mapping — which is the gap this issue names, and is worth fixing in
`bulk_export` itself rather than only in a new tool.

There is no `clone_space`, `copy_space` or config export anywhere in the repo;
the only `get_import_export_config()` hits are unrelated
(`config/config_loader.py:371`).

## Sketch

A versioned, human-readable document — JSON or YAML, not a pg dump — because
the point is that it can be reviewed, diffed, checked into a repo, and applied
to a space that already exists:

    version, exported_at, source_space_id
    vector_indexes[]   name, dimensions, metric, provider, model, provider_config
    fts_indexes[]      name, languages, rank_normalization
    mappings[]         mapping_type, type_uri, index_name, enabled, source_type,
                       separator, include_pred_name,
                       properties[] (uri, role, ordinal),
                       indexes[]    (index_type, index_name)
    fuzzy_mappings[]   …, properties[]
    geo_config         …
    segmentation_config[]

`mapping_id` never appears — the nesting carries the relationship, which is
what makes the remapping problem disappear rather than needing to be solved.
`source_space_id` is recorded for provenance only and must NOT be required to
match on import, or the document cannot be applied to a differently-named
space, which is the entire use case.

Apply should be idempotent and should go through the existing lifecycle
managers (`search_mapping_manager.py`, `vector_index_lifecycle.py`,
`fts_index_lifecycle.py`, `fuzzy_mapping_manager.py`, `geo_config_manager.py`),
not write rows itself.

## Order of work

1. **Export first, and alone.** It is independently useful — a config nobody
   can read is also a config nobody can review, and this makes the current
   state of prod and dev diffable. It also cannot break anything.
2. **A diff/verify mode**: given a document and a space, report what differs.
   This is what makes the eventual apply trustworthy, and it is the thing that
   would have caught the `source_type` flip without anyone suspecting it.
3. **Apply, merge semantics**, going through the lifecycle managers, creating
   the physical tables and triggers.
4. **Then replace semantics**, which needs a considered answer on dropping
   physical tables for removed indexes.
5. **Fold config into `bulk_export`** so a round trip stops dropping it.

## Not established

  * Whether an exported config should carry the `document_segments` bootstrap
    rows at all. They exist in every space by construction, so exporting and
    re-applying them is at best a no-op and at worst a conflict — but omitting
    them makes the document an incomplete description of the space.
  * Whether `provider_config JSONB` can contain credentials. If it can, export
    has to redact, and that changes what "apply" can reconstruct.
  * What apply should do when the target space's data does not contain the
    `type_uri` a mapping names. Probably accept it — config can legitimately
    precede data — but it should be said, not defaulted.
  * Whether two spaces can share an index NAME without interference. They are
    different physical tables (`{s}_vec_{name}`), so presumably yes, but the
    provider cache is keyed `f"{space_id}:{index_name}"`
    (`vectorization/registry.py:23`) and that was not traced further.
  * Whether the portal or Resource API hold any config of their own that would
    need to move alongside this.
