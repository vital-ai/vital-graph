# 232 — Renaming a space is already the documented remedy for an over-long id, and does not exist

## Status: ALL FOUR STEPS DONE 2026-09-26/27 — enumerator, rename, registry and
## permissions, quiesce and cache invalidation. Renaming a space now exists.
## Found `issues/246` on the way. One limitation stands: the caches cleared are
## PROCESS-LOCAL, and the "signal carrying both ids" is not built.

## Step 4 — quiesce and invalidate, as built

`vitalgraph/db/sparql_sql/space_cache_invalidation.py`, wired into
`rename_space`: `quiesce_space` before the transaction, `invalidate_space_caches`
for BOTH ids after it commits.

**Both ids, which is the half that is easy to miss.** The old id's entries
describe a space that no longer exists; the new id's were cached before the space
existed under that name, and answer just as confidently.

**Quiesce REPORTS rather than waits.** `process_lock_key` is a sha256 over
`{type}:{space_id}`, so a job holding the OLD id's lock does not exclude one that
starts under the NEW name — two passes over the same physical tables, neither
aware of the other. `rename_space(require_quiet=True)` (the default) refuses
before the transaction when any per-space lock is held.

**The missing entry point this issue predicted now exists.**
`vectorization/registry._provider_cache` is keyed `f"{space_id}:{index_name}"`
and the only way to clear it was the global `clear_cache()`, which discards every
OTHER space's providers — each costing a tokenizer and an ONNX InferenceSession
to rebuild. `registry.invalidate_space(space_id)` drops only the space's own.
`_instance_by_signature` is deliberately untouched: keyed by (provider, config),
it stays valid across a rename and holds exactly the expensive instances.

### The issue's own cache list was incomplete, and a derived test found it

This issue named seven caches. A test that scans for module-level dicts the code
INDEXES BY `space_id` found **twelve**, and six were not on the list:

    _change_counts, _last_analyze_time          auto_analyze
    _recompute_slot                             maintenance_job
    _frame_slot_ready, _frame_slot_present      ensure/sync_frame_slot_table
    _prop_sort_present, _frame_prop_sort_present  fast_prop_sort / fast_frame_prop_sort

**Four of those are readiness flags, which is the dangerous shape**: a cached
"this table is present" for a space whose tables have moved is a false positive
that selects a fast path over objects that are not there. All thirteen
invalidators are now declared in `CACHE_INVALIDATORS`.

**The first version of that test was VACUOUS** and worth recording as such: it
looked for `space` on the declaration line and matched nothing — 19 dict
declarations, zero hits — so it would have passed forever. The type says
`Dict[str, bool]`; only the INDEXING says the key is a space. It now asserts it
finds at least ten, so a future change that breaks the scan fails instead of
silently approving everything.

Three caches are excluded with stated reasons: `compile_cache` (keyed by SPARQL
hash), `_instance_by_signature` (keyed by provider+config), and `_IN_FLIGHT`
(quiesce CANCELS those tasks — dropping the dict would leak running work).

**Tests:** `tests/unit/test_space_cache_invalidation.py`, 10 cases.

### What step 4 does NOT do

Every cache here is process-local, so this clears THIS process. In a
multi-process deployment the others keep their entries until restarted. The
issue's "a NEW signal carrying BOTH ids" is the fix for that and is not built —
so a rename is still safest against a space nothing else is serving.

## Step 2 — the rename, as built

`vitalgraph/db/sparql_sql/space_rename.py` — `rename_space(conn, old, new, *,
dry_run=False)` and `plan_rename` for the statement list. Catalogue only, in ONE
transaction: ~281 `ALTER` statements for a real space, all or nothing.

**Verified on a real 1.49M-quad space** (`rt_verify2`, 313 objects):

    before   313 objects, 1,489,310 quads, mismatched=0
    plan     281 statements {constraint 166, index 71, table 28, sequence 12,
                             trigger 1, function 1, registry 1, process 1}
    after    old id = 0 objects, new id = 313 objects, mismatched = 0
             quads 1,489,310 unchanged, registry row and graph row followed

Graded by the step-1 enumerator, which is the point of having built it first: the
OLD id owning zero objects and `mismatched` being empty is what proves all four
object classes moved TOGETHER. An object count alone would not — a partial rename
leaves everything working under its old name, because the catalogue links by oid.

### Two ordering facts, both discovered by failing tests

**Constraints before indexes.** Renaming a PK or UNIQUE constraint ALSO renames its
backing index, so the index pass must skip any name that is also a constraint name.
34 of a space's 105 indexes move this way (26 PK + 8 UNIQUE), which is why the plan
has 71 `ALTER INDEX` rather than 105.

**Inherited constraints must be skipped.** A partition child inherits its parent's
NOT-NULL constraints under the SAME name, and renaming one on the CHILD is
rejected — `constraint … for table … does not exist`. Renaming it on the parent
carries the children. Measured:

    pc_a     pc_a_ctx_not_null  coninhcount=0  conislocal=t
    pc_a_p0  pc_a_ctx_not_null  coninhcount=1  conislocal=f

so the constraint query filters `coninhcount = 0`. The partitioned-space test
found this; reading did not.

### The substring trap in name mapping

`name.replace(old, new, 1)` is the obvious implementation and it is wrong: for a
space called `x`, the first `x` in `idx_x_edge_ctx` is inside `idx_`. `_map_name`
matches `{decorator}{space_id}` as a whole leading token and returns **None** for
anything it cannot map — and None is a HARD REFUSAL, never a skip, because a
skipped object is an orphan under the old id, which is this issue's whole subject.
28 unit tests cover it, including that trap.

### It refuses a rename that would truncate a name — which found `issues/246`

A mapped name over PostgreSQL's 63-byte identifier limit is TRUNCATED SILENTLY, so
the rename refuses rather than producing names no rename-back can undo. That guard
immediately failed on ordinary spaces, which is how **`issues/246`** was found:
five auto-named UNIQUE constraints are ALREADY truncated on every space, because
`{space}_document_segmentation_config_document_type_uri_segment_method_uri_key` is
70 bytes of suffix before any space id. `max_space_id_bytes()` reports 34 and the
real ceiling is lower and id-dependent.

**The consequence for the rename is a real limitation, not a test artefact:** it
can only be reversible across a SAME-LENGTH rename. Lengthening an id is refused
where names are already at the limit; shortening one works, which is the actual
use case, since rename exists to fix an over-long id.

**Tests:** `tests/integration/test_space_rename.py` (16) and
`tests/unit/test_space_rename_name_mapping.py` (28). The refusals are all asserted
to leave the space untouched, and `dry_run` to change nothing while returning the
plan.

## Step 3 schema work — DECIDED: add `ON UPDATE CASCADE` to all of them

The open question was whether the eleven FK children should gain
`ON UPDATE CASCADE` (one migration, simpler rename, touches shared schema) or
whether the rename should repoint them by hand (no schema change, more to get
wrong). **Decided 2026-09-26: add the cascade.** So `UPDATE space SET space_id`
now carries its children, and the rename can be a catalogue operation rather than
an eleven-table repoint in the right order.

**`user_space_access` gained the foreign key it never had**, `ON DELETE CASCADE
ON UPDATE CASCADE`. It had none, so unlike the eleven it would not have REJECTED
a rename that forgot it — it would have silently kept rows pointing at an id
nobody uses. Measured before doing it: the table is **EMPTY on both the vg test
stack and production**, so the silent revocation was latent rather than active,
and the FK went on without a cleanup pass. Adding it is what stops it becoming
active later.

Both in `sparql_sql_schema.py` for new databases, and in
`scripts/migrate_space_fk_on_update_cascade.py` for existing ones — dry-run by
default, `--apply` to write. It **refuses rather than deletes** if
`user_space_access` holds grants for spaces that do not exist: those rows are
access records, and discarding them to make a migration pass is not the script's
decision. Applied to the vg stack: 11 fixed, 1 added, 12 of 12 cascading.

### The test `issues/232` asked for, before the rename rather than after

`tests/integration/test_space_id_update_cascades.py`, 8 cases. The one that
matters is `test_a_grant_follows_the_space_to_its_new_id` — the failure that does
not announce itself. Alongside it:

  * **`ON DELETE CASCADE` must survive being re-added.** The migration drops and
    re-adds each constraint, so losing the delete action while gaining the update
    action is a live way to get this wrong, and it would leak grants for dropped
    spaces forever.
  * **Every FK to `space` is checked from the CATALOGUE**, not a list, so a table
    added later with the old `ON DELETE CASCADE`-only pattern fails this test
    instead of failing a rename.
  * **A grant for an unknown space is now rejected** — the other half of having a
    foreign key is that the rows cannot become orphaned in the first place.

**A bug worth recording, because it made a migration lie.**
`pg_constraint.confupdtype` is PostgreSQL's `"char"` type and asyncpg returns it
as **bytes** — `b'c'`, not `'c'`. Comparing it to a str is always False, so the
first version reported all twelve constraints as still needing the change
*immediately after successfully changing them*, and its documented idempotence was
untrue: a second run would have dropped and re-added every already-correct
constraint. The test asserts against the decoded value for the same reason.

## Step 1 — the enumerator, and what it measured

`vitalgraph/db/sparql_sql/space_rename_enumerate.py` —
`enumerate_space_objects(conn, space_id)` plus `format_enumeration`, surfaced
read-only at **`GET /api/spaces/objects`**. Derived from the catalogue
(`pg_tables`, `pg_indexes`, `pg_constraint`, `pg_depend`, `pg_trigger`,
`pg_proc`), never from a list — a list is how the three retired suffixes get
orphaned and it cannot know the dynamic `_vec_`/`_fts_` names at all.

Attribution REUSES `SparqlSQLSchema.orphan_tables_for_space` rather than
reimplementing the longest-prefix rule, because two rules that are supposed to
agree will not.

### ANSWERED: does renaming a partitioned parent rename its children?

**No.** Measured on PostgreSQL 18 — `ALTER TABLE ren_old RENAME TO ren_new`
leaves `ren_old_p0` behind, along with `idx_ren_old_val`, `ren_old_pkey`,
`ren_old_p0_pkey`, `ren_old_ctx_val_key` and `ren_old_id_seq`. So the enumerator
reports partition children as their own class: they need their own `ALTER`.

### ANSWERED, and the inventory above UNDERSTATES the scale by 2x

This issue estimated ~26 tables, ~90 indexes, ~12 sequences and ~26 constraints —
about 154 objects. The real figure is **278-329 per space**, and the gap is almost
entirely constraints: **166, of which 126 are PG18's NAMED NOT-NULL
constraints** (`contype = 'n'`), against 26 primary keys, 8 unique, 3 check and 3
foreign keys. PostgreSQL 18 names not-null constraints and they appear in
`pg_constraint`, so a rename has ~126 more objects to handle per space than the
inventory above assumed.

### The production audit this step existed to produce

The issue's reason for building the enumerator first was that it is "the audit
that would show whether any existing space is already carrying mismatched index
or constraint names". Run against production, read-only:

    prod_kg          323 objects  (29 tables, 109 idx, 169 con)  shadowed_by=['prod_kg_archive']
    prod_kg_archive  317 objects  (28 tables, 107 idx, 166 con)
    lead_data           313 objects
    lead_prod           313 objects
    sp_kg_types         329 objects
    testspace           297 objects
    wordnet_frames      313 objects

    spaces with mismatched objects: NONE

**No space has been half-renamed** — so the rename can be built without a repair
pass first. And the prefix hazard is NOT hypothetical: **`prod_kg` is a prefix
of `prod_kg_archive` in production today.** Renaming `prod_kg` without the
longest-prefix rule would claim all 317 of the archive's objects. That pair is the
`data` / `data_orig` shape this issue warned about, already live.

**Tests:** `tests/integration/test_space_rename_enumerate.py`, 12 cases. The
shadowing case is tested from BOTH directions, because claiming another space's
objects is the failure that renames or drops someone else's tables. One test
reproduces the damage directly — rename a table by hand, as `ALTER TABLE` does,
and assert the leftovers are reported.

A bug worth recording: the first `mismatched` rule was a prefix test, which
flagged all 105 indexes of every healthy space, because an index is
`idx_{space}_…` — the space id sits behind a decorator. An audit that fires on
everything is an audit nobody runs. It is a containment test now, and
`test_a_healthy_space_reports_no_mismatch` is the baseline that keeps it honest.

**Related:** `issues/233` (export a space's config and apply it elsewhere — the
other half of the workflow this exists to serve), `scripts/migrate_shorten_index_names.py`
(the `ALTER INDEX … RENAME TO` precedent, and the reason the byte ceiling is 34
rather than 21), `vitalgraph/db/sparql_sql/partition_migrate.py:123-126`
(`ALTER TABLE … RENAME TO` including partition children)

## The request

> Rename space `data` to `data_orig`, covering the underlying tables, indexes,
> the space row, and anything else that names it.

Together with `issues/233` the intended workflow is: rename `data` to
`data_orig`, create a fresh `data`, and apply `data_orig`'s config to it so the
new space has the same FTS and vector index mappings. The rename is the half
that moves the existing data out of the way; `233` is the half that makes the
replacement equivalent.

## This is already the sanctioned answer to a different problem

Two places in the schema tell the operator to rename, and neither can be
obeyed:

`sparql_sql_schema.py:2084-2091`, refusing an over-long space id —

> Shorten the space id — renaming is free now and is not once data is loaded.

`sparql_sql_schema.py:1983-1992`, when index DDL is dropped because the
generated name would exceed 63 bytes —

> rename the space to recover these.

The second is the worse one: the space is CREATED, it works, and some of its
indexes silently do not exist. The documented recovery is a rename, and a
rename cannot be performed, so the real recovery today is "export, drop,
recreate under a shorter name, reload" — which for a large space is hours and
is exactly what `2084-2091` claims renaming avoids.

## What names a space, in full

Taken from `SparqlSQLSchema.get_table_names` (`sparql_sql_schema.py:868-898`)
and `drop_space` (`:2171-2262`), which between them are the only complete
enumerations in the codebase. **The naming rule is raw concatenation —
`{space_id}_{suffix}`, no hashing, no truncation, no escaping.**

**26 static tables.** `term`, `rdf_quad`, `datatype`, `rdf_pred_stats`,
`rdf_stats`, `rdf_value_stats`, `edge`, `edge_fanout`, `entity_fanout`,
`frame_slot`, `entity_slot_sort`, `entity_prop_sort`, `frame_prop_sort`,
`vector_index`, `geo`, `geo_config`, `fuzzy_mapping`, `fuzzy_mapping_property`,
`fuzzy_band`, `fuzzy_phonetic_band`, `search_mapping`, `search_mapping_index`,
`search_mapping_property`, `fts_index`, `segmentation_jobs`,
`document_segmentation_config`.

**Partition children** — `{table}_p0 … _pN` for `rdf_quad`,
`entity_slot_sort`, `entity_prop_sort`, `frame_prop_sort` when
`partition_quads > 0` (`:904-912`).

**Dynamic, one pair per user-named index** — `{s}_vec_{name}` (`:2307-2310`)
and `{s}_fts_{name}` (`:2363-2366`). Every space has at least
`{s}_vec_document_segments`, created at bootstrap.

**Three retired suffixes that still exist on older spaces** — `frame_entity`,
`vector_mapping`, `vector_mapping_property` (`:806-813`). A rename that skips
these orphans them under the old name.

**~90 explicitly named indexes**, all `idx_{space_id}_{suffix}`
(`:1629-1978`), plus three per vector index and three per FTS index.

**Trigger functions and triggers, per FTS index** —
`{space_id}_fts_{name}_tsv_trigger()` and `trg_{space_id}_fts_{name}_tsv`
(`:2377-2378`, `:2403-2417`).

## The four traps

### 1. `ALTER TABLE … RENAME TO` does not rename what the table owns

Sequences, constraints and indexes keep their old names. Nothing in the schema
names a constraint explicitly — `grep "CONSTRAINT "` finds none — so every PK,
UNIQUE and FK is auto-named by PostgreSQL from the table it was created on:

    {old}_term_pkey, {old}_datatype_datatype_uri_key,
    {old}_search_mapping_property_mapping_id_fkey, …          ~26 names
    {old}_datatype_datatype_id_seq, {old}_fts_index_index_id_seq, …  ~12 sequences

They keep WORKING — the catalogue links by oid, not by name — which is what
makes this dangerous. The damage is that every name-based routine now disagrees
with reality: `classify_space_table` (`:825-866`), `orphan_tables_for_space`
(`:2264-2290`), the schema-completeness check, and
`scripts/cleanup_orphan_space_tables.py`. Worse, the next
`CREATE INDEX IF NOT EXISTS idx_{new}_…` sees no index by that name and builds
a SECOND one alongside the old — a silent duplicate on a large table.

So a rename must cover four object classes, not one: tables, indexes,
sequences, constraints. `ALTER INDEX`, `ALTER SEQUENCE` and
`ALTER TABLE … RENAME CONSTRAINT` all exist and are catalogue-only.

### 2. The registry FKs cascade on DELETE, not on UPDATE

`space.space_id VARCHAR(255) PRIMARY KEY` (`:351-359`) — the id string IS the
primary key; there is no numeric surrogate anywhere. Eleven admin tables carry
`FOREIGN KEY → space(space_id) ON DELETE CASCADE`: `graph`, `backfill_state`,
`type_agreement`, `slot_sort_coverage`, `slot_sort_block`, `prop_sort_block`,
`prop_sort_coverage`, `space_analytics`, `query_metrics`, `slow_query_log`,
`import_export_job`.

None declares `ON UPDATE CASCADE`. `UPDATE space SET space_id = …` therefore
does not carry the children along — it is REJECTED. The rename must either add
`ON UPDATE CASCADE` to all eleven, or insert the new parent row, repoint the
children, and delete the old parent, in one transaction.

### 3. `user_space_access` has no foreign key at all

`:388-397` — `space_id VARCHAR(255) NOT NULL`, `PRIMARY KEY (user_id, space_id)`,
and no FK to `space`. So unlike the eleven above it will NOT reject a rename
that forgets it; it will silently keep rows pointing at an id nobody uses.

**That is a silent revocation of every user's access to the renamed space**,
and it is the one failure here that is both invisible and security-relevant.
`process.process_subtype` (`:402`) holds the space id the same way.

### 4. Prefix shadowing

`orphan_tables_for_space` (`:2264-2290`) attributes a table to a space by
LONGEST MATCHING PREFIX in Python — deliberately not SQL `LIKE`, because `_` is
a `LIKE` wildcard — so that `prod_kg` does not claim `prod_kg_test`'s tables.

A rename can break that invariant in a way creation cannot, because creation
checks against the ids that exist and a rename introduces a new id while the
old one is still half-present. **Renaming `data` to `data_orig` is precisely
the dangerous shape**: `data` is a prefix of `data_orig`, so mid-rename every
`data_orig_*` table is also a candidate `data` table. If the intended workflow
then recreates `data`, the two spaces coexist permanently in that relationship
— which is legal today, but only because both were created whole.

## Decide explicitly: graph URIs are NOT rewritten

The default graph URI is `urn:{space_id}` (`vitalgraph_import_cmd.py:111,245`;
`warm_pipeline.py:158`; `import_export_manager.py:418`), and it is stored as a
term whose uuid is derived from its text — `auto_sync.py:39-45`:

    term_uuid = uuid5(_VITALGRAPH_NS, f"{term_text}\x00{term_type}")

So rewriting `urn:data` to `urn:data_orig` changes that term's uuid, and
therefore EVERY `context_uuid` in `rdf_quad`, `edge`, `frame_slot`, the three
sort tables, `geo`, and every `_vec_`/`_fts_` table. That is a full data
rewrite of the largest tables in the space — not a catalogue operation, and
not something that can share a transaction with the rest.

**The recommendation is that a rename does not touch graph URIs**, and that the
resulting cosmetic mismatch (`data_orig` holding a graph named `urn:data`) is
documented as intended. Rewriting them is a separate, much larger feature, and
conflating the two is how this lands as an hours-long operation that claims to
be free.

This matters for the stated workflow: after renaming `data` to `data_orig` and
creating a new `data`, the new space's default graph `urn:data` is the SAME URI
the old space still uses internally. They are in different tables so nothing
collides, but any consumer keying on graph URI alone cannot tell them apart.

## Sketch

One transaction for everything catalogue-shaped — PostgreSQL DDL is
transactional, which is what makes this feasible at all:

    quiesce           cancel_space_syncs(old)              space_manager.py:371
                      release per-space advisory locks     process_lock_manager.py:31-43
                      (lock keys are sha256 over the space id, so a job under
                       the old id does NOT exclude one under the new)
    validate          new id fits max_space_id_bytes()     schema.py:299-322
                      new id not a prefix of / prefixed by any other space id
                      new id not in PROTECTED_SPACES       constants.py:8,13
    BEGIN
      ALTER TABLE     26 static + partitions + retired + every _vec_/_fts_
      ALTER INDEX     ~90 + 3 per vector index + 3 per FTS index
      ALTER SEQUENCE  ~12
      ALTER TABLE … RENAME CONSTRAINT   ~26
      ALTER FUNCTION  {old}_fts_*_tsv_trigger  → {new}_…
      ALTER TRIGGER   trg_{old}_fts_*_tsv      → trg_{new}_…
      registry        insert new space row, repoint 11 FK children,
                      user_space_access, process.process_subtype, delete old
    COMMIT
    invalidate        every in-process cache keyed by space id (below)
    signal            a NEW signal carrying BOTH ids

The enumeration should be DERIVED from the catalogue
(`pg_tables`/`pg_indexes`/`pg_class`) filtered by the same longest-prefix rule
`orphan_tables_for_space` uses — not from a hardcoded list. A hardcoded list is
how the three retired suffixes get left behind, and it cannot know the dynamic
`_vec_`/`_fts_` names.

### Caches a rename must invalidate

All process-local, all keyed by space id, none of which any existing code path
invalidates as a set: `generator._term_cache` / `_datatype_cache` /
`_stats_cache` / `_value_stats_cache` (`generator.py:234,251,273,789`),
`count_cache` and `entity_graph_cache` (both have `invalidate_space`),
`SpaceManager._spaces` (`space_manager.py:84`), `auto_sync._IN_FLIGHT` (`:36`),
`maintenance_job._edge_fanout_slot` (`:359`),
`kgentity_frame_update_impl._ownership_cache` (`:53`).

**`vectorization/registry._provider_cache` (`:23`) is keyed
`f"{space_id}:{index_name}"` and has only a global `clear_cache()` — no
per-space invalidation exists.** That one needs a new entry point.

`compile_cache` is keyed by SPARQL hash, not space id (`:58`), so it is safe.
Redis metric keys (`query_metrics.py:57-64`) are TTL'd and self-heal.

## Order of work

1. **A dry-run enumerator first** — given a space id, list every catalogue
   object that names it, by class. Useful immediately and independently: it is
   also the audit that would show whether any existing space is already
   carrying mismatched index or constraint names.
2. **The rename itself**, transactional, catalogue objects only, refusing any
   space whose new id fails the length or prefix checks.
3. **Registry and permissions**, with `user_space_access` covered by a test
   that asserts access SURVIVES a rename — it is the failure that does not
   announce itself.
4. **Quiesce and invalidate**, including the missing per-space
   `_provider_cache` invalidation and a both-ids signal shape.

## Not established

  * Whether `ALTER TABLE … RENAME` on a partitioned parent renames its children
    or leaves them as `{old}_rdf_quad_p0`. `partition_migrate.py:123-126`
    renames children explicitly, which suggests it does not, but that was a
    different operation and it was not read closely enough to claim here.
  * Whether the eleven FK children should gain `ON UPDATE CASCADE` (one
    migration, simpler rename, changes shared schema) or whether the rename
    should repoint them by hand (no schema change, more to get wrong). Leaning
    to the first, but it touches every space.
  * How a rename interacts with a MultiAZ/replica or an in-flight
    `import_export_job` row that names the space.
  * Whether any consumer outside this repo — the portal, the Resource API —
    caches space ids in a way a rename would strand. Nothing in this repo can
    answer that.
  * Whether the sanctioned recovery at `:1983-1992` actually works after a
    rename: the dropped index DDL would need re-running, and nothing currently
    re-attempts it.

## Reproduce — what the enumerator must find

    SELECT tablename FROM pg_tables WHERE tablename LIKE 'data\_%';
    SELECT indexname FROM pg_indexes WHERE indexname LIKE 'idx\_data\_%';
    SELECT c.relname, c.relkind FROM pg_class c WHERE c.relname LIKE 'data\_%'
      AND c.relkind IN ('S','r','p','i');
    SELECT conname FROM pg_constraint WHERE conname LIKE 'data\_%';
    SELECT routine_name FROM information_schema.routines
      WHERE routine_name LIKE 'data\_fts\_%\_tsv_trigger';

(The `\_` escapes matter — `_` is a `LIKE` wildcard, which is the same trap
`orphan_tables_for_space` avoids by matching in Python.)
