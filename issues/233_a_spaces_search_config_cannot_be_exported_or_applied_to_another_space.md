# 233 — A space's search config cannot be exported, or applied to another space

## Status: ALL FIVE STEPS DONE 2026-09-26 — export, diff, apply-merge,
## apply-replace, and config folded into `bulk_export`. The original defect —
## "`bulk_export` exports three tables and none of them are config" — is closed.

## Step 5 — config travels with a `bulk_export` round trip

`export_space` now writes a `config.json` sidecar and `import_space` applies it.
Manifest version bumped **1 → 2** (`config`, `config_includes_secrets`), so a
reader that only understands v1 can tell.

Three decisions, each with a reason that is not "it seemed tidy":

  * **The config is exported INSIDE the same `REPEATABLE READ` snapshot** as the
    three COPYs. A mapping added mid-export would otherwise appear in a backup of
    quads taken before it existed.
  * **Import uses REPLACE**, matching the `TRUNCATE` this function already does to
    the data. Config the backup does not contain has no more claim to survive
    than data the backup does not contain — and a mapping left over from whatever
    the space used to be, pointing at an index the restore did not bring, is the
    "faithfully wrong" state `issues/041` and `issues/168` are both about. Pinned
    by `test_a_restore_does_not_leave_stale_config_behind`.
  * **`include_secrets` defaults to TRUE here**, unlike the read-only export
    endpoint, because a backup that cannot be restored is not a backup. The
    export directory already holds every quad in the space, so it was always
    sensitive; the change is that it can now hold a provider credential, and the
    export logs a WARNING saying so once.

**A config failure does NOT discard the data restore.** Raising would abort the
caller's transaction and throw away a restore that may have taken hours, over a
document that can be re-applied in a second through
`POST /api/spaces/config/apply`. So it is recorded in the returned counts and
logged at ERROR — visible, fixable, and not a reason to lose the data. Pinned by
`test_a_config_failure_does_not_discard_the_data_restore`.

**An export with no `config.json` still imports**, leaving the config untouched
and saying so. That is the state every backup taken before today is in, and a
restore from one must not fail.

The round-trip test is graded by step 2: export the source, import into a target,
then DIFF the target against the source's document and require no difference — so
a field the restore failed to set cannot pass.

**Tests:** 4 more in `tests/integration/test_config_export.py` (34 total). The
existing `test_bulk_export.py` manifest assertion caught the version bump, which
is what it is for; it now asserts v2 and the sidecar's presence.

## Step 4 — replace semantics. DECIDED: yes, drop the physical tables

The open question was whether replace should drop the `_vec_`/`_fts_` tables of
removed indexes. **Answered yes, 2026-09-26.** So `apply_space_config(...,
replace=True)` removes config the document omits and tears the physical objects
down with it, through `teardown_index` / `teardown_fts_index` — which also take
the trigger function, the trigger and the three FTS indexes. A `DELETE` from the
registry would have left all of those behind.

**Merge remains the default.** The destructive behaviour is not what you get by
not thinking, and a test asserts that.

### What it destroys, and how that is made visible

A `_vec_` table holds computed EMBEDDINGS. Re-applying the document recreates the
index EMPTY — it cannot bring the vectors back, and regenerating them costs money
and wall-clock. FTS tsvectors are cheaper but still a rebuild over the corpus.

So every removal is reported as `{what, table, rows_destroyed}` with an EXACT
count (not `reltuples`, which is stale or -1 on a freshly built index), and
`dry_run=True` reports the counts a real run WOULD destroy without writing. That
is what makes the dry run a safety tool rather than a formality, and both halves
are pinned by test. Each removal also logs at WARNING naming the rows.

### The ordering that is not optional

`teardown_index` deletes every `search_mapping` row naming the index it drops. So
removals run BEFORE creations — otherwise a mapping this apply had just created,
naming an index being torn down, would be collateral damage.
`test_removals_run_before_creations` constructs exactly that scenario: the target
has an index the document omits, the document has a mapping of its own, and both
must survive correctly.

### No special case for `document_segments`, deliberately

Every space gets it from `bootstrap_space_extras` AT CREATION ONLY, so dropping it
is permanent for that space. But replace means replace, and a document that omits
it is a document someone edited. The row count and the WARNING are the guard;
refusing would be guessing at intent. Recorded here because it is the one removal
that cannot be undone even by recreating the space's config.

**Tests:** 7 more in `tests/integration/test_config_export.py` (30 total) and 3
more on the endpoint (18 total). Two of them initially failed for a reason worth
keeping: the fixture asked for a 3-dimensional openai index and `ensure_index`
REFUSED it, because it validates width against the provider registry. That is the
validation this issue wanted from going through the lifecycle rather than writing
rows, catching a bad index at apply time instead of at the first reindex.
## `bulk_export` still exports three tables and none of them are config.

## Step 3 — apply, merge semantics, as built

`vitalgraph/db/sparql_sql/config_apply.py` —
`apply_space_config(conn, space_id, document, *, dry_run=False)`, surfaced at
**`POST /api/spaces/config/apply`** (requires WRITE, unlike the diff route beside
it; a dry run also requires write, because otherwise the permission would depend
on a query parameter the caller chooses).

**Through the lifecycle managers, never by writing rows** — `ensure_index`,
`ensure_fts_index`, `SearchMappingManager`, `FuzzyMappingManager`,
`GeoConfigManager`, `SegmentationConfigManager`. A test asserts the consequence
directly: applying a document containing a vector index creates
`{target}_vec_extra_idx`, so the registry row cannot arrive without its data
table.

**Merge, never remove.** A mapping the document omits survives, and the DIFF is
what reports it as `only_in_space`. Removal is step 4 and still needs an answer
on dropping physical tables.

### The ordering trap, which is what makes this more than a loop

`SearchMappingManager.add_property` AUTO-UPGRADES `source_type` from `default` to
`properties` as a side effect (`search_mapping_manager.py`, "Auto-upgrade
source_type when include properties are added"). So the obvious sequence —
create the mapping with the document's `source_type`, then add its properties —
silently produces a mapping whose `source_type` is not what the document said.
This issue already recorded that being hit for real and corrected with an
explicit `PUT`; now the reason is in the code.

Apply therefore RE-ASSERTS every mapping's scalar fields after its properties are
added. `test_the_source_type_trap` is the test that would fail if that ordering
were ever "simplified": it applies a document saying `default` WITH properties and
asserts the result is still `default`.

### Step 2 grades step 3

The headline test is `test_applying_a_document_makes_the_diff_clean` — apply, then
DIFF, and assert no difference. The check is performed by different code from the
code that wrote the config, so a field apply quietly failed to set cannot pass.
This is the concrete payoff from doing diff before apply, as the issue's order
required.

**Idempotent:** a second apply reports `created: []`, `updated: []`,
`changed: False`. `dry_run` reports the plan and writes nothing, asserted by
diffing after.

### Refusals happen before anything is written

  * **A redacted document is refused**, naming the paths and pointing at
    `include_secrets=True`. Writing `__REDACTED__` into a `provider_config` yields
    an index that exists, lists correctly and embeds wrongly — `issues/219`'s
    shape. A test asserts the target's `vector_index` count is unchanged after the
    refusal.
  * **A version mismatch is refused** rather than guessed at.

Both surface as `INVALID_REQUEST` at HTTP 200, so a caller keeps the reason; a
500 would lose it and invite a retry. A successful apply returns `UPDATED` when
it changed something and `NO_OP` when the document already matched, because a
caller polling toward a desired state needs to tell those apart.

### Verified on real data

The production `prod_kg` document (1 vector index, 2 FTS indexes, 3 mappings,
exported with secrets) dry-run against local `wordnet_frames`:

    diff  -> differs: True   fts_indexes +1 to add, mappings +2 to add
    plan  -> would create: fts_index/message_content,
                           mapping/kgslot/urn:example:kg:slot:GenMsgContent/message_content,
                           mapping/kgslot/urn:example:kg:slot:MsgContent/message_content
    dry run wrote nothing: True

**The plan matches the diff exactly**, and the shared `document_segments`
bootstrap config correctly produces no work.

### One gap this found and closed

There was NO way to change an FTS index's `rank_normalization` after creation:
`ensure_fts_index` takes it only when creating and `update_fts_languages` does not
touch it. So a document could describe a rank normalization apply was unable to
produce, and the mismatch would show up only as every score being computed the
other way. `fts_index_lifecycle.update_rank_normalization` now exists — a
registry update, because the bitmask is read at QUERY time by `ts_rank_cd`, so
unlike a language change nothing needs recomputing.

**Tests:** 8 more in `tests/integration/test_config_export.py` (23 total there)
and 5 more on the endpoint (15 total).

## Step 2 — diff/verify, as built

`vitalgraph/db/sparql_sql/config_diff.py` — `diff_documents(document,
space_config)` is PURE, and `diff_space_config(conn, space_id, document)` is the
four-line wrapper that exports the live config and compares. Surfaced at
**`POST /api/spaces/config/diff`** — read-only despite the verb, because the
document has to travel in a body, and requiring READ rather than write so the
people auditing a config can actually run it.

It works because step 1 normalises: no surrogate keys, no timestamps, stable
order, JSONB parsed. Both sides therefore arrive comparable and the interesting
logic needs no SQL, which is why it is unit-tested rather than
integration-tested.

The report states direction in its own key names, so it cannot be read
backwards: `only_in_document` would be ADDED, `only_in_space` is EXTRA,
`changed` carries `{field, document, space}` per field, `unknown` lists values
the document cannot see, and `differs` is the verdict.

**Verified against PRODUCTION, read-only:**

    prod_kg vs its own export  ->  differs: False   unknown: 0
    prod_kg doc vs lead_prod   ->  differs: True
        fts_indexes  would add: message_content
        mappings     would add: kgslot/urn:example:kg:slot:GenMsgContent/message_content
                     would add: kgslot/urn:example:kg:slot:MsgContent/message_content

The second line is the real use case answered on real data, and the absence of a
`vector_indexes` section is the important part: both spaces carry identical
`document_segments` bootstrap config, and it produces NO false positive.

### Three false positives it must not have, each pinned by a test

Each would make the tool stop being run, which is the only failure mode that
matters for a verify step:

  * **Provenance differing.** `source_space_id`, `exported_at`, `absent_tables`
    and `redacted` are ignored by construction. Counting them would make every
    CROSS-SPACE diff dirty — and cross-space is the entire use case. A test sets
    every provenance key to junk on both sides and asserts the verdict does not
    move, so the `_PROVENANCE` constant has teeth rather than being a comment.
  * **A redacted secret reading as changed.** A document exported with the
    default redaction carries `__REDACTED__`. That is UNKNOWN, not different: as
    a change it would make every committed document dirty against its own space,
    and as equal it would hide a rotation. It gets its own `unknown` bucket and
    deliberately does NOT set `differs` — a verify that fails on every committed
    document simply stops being used. A non-secret sitting beside a redacted one
    is still compared.
  * **Absent vs explicit null.** Compared by value over the union of keys, so an
    omitted optional column and a `None` read the same. Both genuinely occur.

A version mismatch is NOTED, not raised: a caller comparing an archived document
needs to see it, and an apply needs to refuse on it — raising denies the first.

**Tests:** `tests/unit/test_config_diff.py` (19, the pure comparison, including
one that derives "every section is actually compared" from `_IDENTITY` rather
than listing sections by hand), 5 more in
`tests/integration/test_config_export.py` where the two halves meet against a
real database — a space does not differ from its own export, a redacted export
still verifies clean, a `source_type` flip performed for real is found, and one
space diffed against another reports only what was added — and 4 more on the
endpoint contract.

## Step 1 — export, as built

`vitalgraph/db/sparql_sql/config_export.py` — `export_space_config(conn,
space_id, *, include_secrets=False)` returns a plain dict; `config_to_json`
renders it with sorted keys. Surfaced read-only at **`GET /api/spaces/config`**
(`spaces_endpoint.py`), with `include_secrets` defaulting to false.

Verified against PRODUCTION, read-only — `prod_kg` exports 1 vector index,
2 FTS indexes and 3 mappings, and the document captures the `source_type:
"properties"` value this issue flagged as flipping invisibly. Also run against
`wordnet_frames` on the vg stack, which returns exactly the bootstrap config.

Three properties it is built for, each with a test:

  * **Portable.** `source_space_id` is provenance only and the space id appears
    NOWHERE else — the load-bearing test plants the space id inside a `type_uri`
    and asserts exactly one occurrence, so the check is structural rather than
    lucky. Without this the document only applies to the space it came from,
    which is the space that least needs it.
  * **Diffable.** No surrogate key (`mapping_id`, `index_id`, `property_id`,
    `config_id`) and no timestamp survives; every list is ordered by a stable
    natural key; `provider_config` is parsed so PostgreSQL's stored whitespace
    and key order do not leak. Two exports of the same config are byte-identical.
  * **Safe to commit.** Key-shaped entries in `provider_config` are redacted and
    the redaction is RECORDED under `redacted`, so a later apply can refuse a
    placeholder rather than write one. Redaction is surgical — `endpoint` beside
    an `api_key` survives.

An older space missing a config table is reported in `absent_tables` rather than
failing the export, because failing would break the tool exactly on the space
that most needs reading.

**Two bugs this found in itself, both caught by tests rather than review:**

  * asyncpg returns JSONB as a **string**, so the first version's redaction
    walked a `str`, matched nothing, and passed the secret through intact — the
    only visible symptom being that `provider_config` was a string rather than an
    object. `_as_object` now parses it, and the redaction test is the regression
    guard.
  * the handler used a non-existent `OperationStatus.SUCCESS`, and its broad
    `except Exception` turned that AttributeError into a plausible
    `store_failed` domain outcome. It is `FOUND` now (a read, in the family's
    read vocabulary) with `QUERY_FAILED` on failure, and the log carries
    `exc_info` so the next such bug is distinguishable from a real one.

**Tests:** `tests/integration/test_config_export.py` (10, against a real
database) and `tests/unit/test_config_export_endpoint.py` (6, the endpoint
contract — domain outcomes at HTTP 200, and the `include_secrets` default
actually threaded through).

**Not done, deliberately:** this describes, it does not decide. The
`document_segments` bootstrap rows ARE exported, because omitting them would
make the document an incomplete description of the space; whether apply should
skip them is step 3's decision, and the document is faithful so that step 3 can
make it.

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
