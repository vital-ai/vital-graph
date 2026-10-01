# 251 — `entity_admin.py` reports a successful fuzzy sync that writes nothing

## Status: FIXED 2026-09-29 — option 1 implemented and exercised on both backends.
## **The rewritten `fuzzy check` found a real defect on its first run**, filed as
## `issues/252`: the PG index leaks stale name variants because its delete is
## gated on a per-process cache. That is the argument for the rewrite, stated
## better than the reasoning below does. Production audited for `252` and CLEAN
## (three-way exact agreement) — the fix here was not papering over live drift.
##
## The check shipped with `= 'active'` predicates after this file argued they were
## wrong; corrected to the writer's `<> DELETED` / `<> RETRACTED`.
##
## Original report follows.

## Status when filed: OPEN, verified against source and production 2026-09-29.
## NOT a data-loss bug and NOT currently biting the production index —
## `entity_admin.py` never writes, and production's PostgreSQL fuzzy index is
## complete and current (measured below). What is broken is the reporting: three
## of the four `fuzzy` subcommands answer about an index that is not the one
## production uses, and two of them do it in the confident direction.

**Related:** `issues/249` names `entity_admin.py:764` as one of three consumers
of `find_similar` output that matter — this is the tool being used to look at
that problem. `issues/136` (prod `statement_timeout` vs VACUUM) for the
visibility-map note at the end.

## The shape

`entity_admin.py` builds its fuzzy index unconditionally:

    # apps/entity_registry/entity_admin.py:77
    from vitalgraph.entity_registry.entity_fuzzy import EntityFuzzyIndex
    self.fuzzy = EntityFuzzyIndex.from_env()

`EntityFuzzyIndex` knows two backends, `memory` and `redis`. It has no branch for
`postgresql` — that selection lives in the caller, and both other callers make
it (`vitalgraphapp_impl.py:461`, `vitalgraph_entity_registry_cmd.py:148`). So
with `ENTITY_FUZZY_BACKEND=postgresql`, which is what production sets,
`from_env` falls through to `else: logger.info("Entity fuzzy using in-memory
backend")` and the admin tool gets an in-process index.

It then loads every active entity from PostgreSQL on each invocation and discards
the result on exit.

## What each command actually does on the `postgresql` backend

`_do_initialize` in `entity_fuzzy.py` is `SELECT`-only — there is no write path
and nothing can be corrupted. The problem is that the commands answer about the
throwaway index while appearing to answer about the real one:

| Command | Behaviour |
|---|---|
| `fuzzy sync` | Builds the in-memory index, prints `Full fuzzy sync complete: N entities in Xs`. **The band tables are untouched.** A success message for a no-op. |
| `fuzzy check` | Compares `SELECT COUNT(*) FROM entity` against the count of the index it just built from that same query. It always agrees. It cannot detect the drift it exists to detect. |
| `fuzzy status` | Prints `Backend: memory` and the throwaway index's size. Nothing about the PostgreSQL index. |
| `search similar` | Correct results — but pays a full 1.27M-entity index build first. |

`fuzzy check` is the sharpest of these. A consistency check that is structurally
incapable of returning "inconsistent" is worse than no check, because its output
is used as evidence that the index is fine.

## The documentation pointed at commands that do not exist

Found while confirming the above, fixed in the same pass:

* `apps/entity_registry/README.md` documented `dedup status` / `dedup sync`
* `apps/entity_registry/IMPORT_FORMAT.md:580` documented `dedup-sync` and
  `weaviate-rebuild`

The subcommand is `fuzzy`, and the Weaviate one takes a space. All four fell
through to the usage print and did nothing at all.

The `IMPORT_FORMAT` one is the load-bearing case: it is the documented
"rebuild indexes separately" step after a bulk JSONL import. Corrected to
`migrate_fuzzy_redis_to_pg.py --rebuild`, because `entity_admin.py fuzzy sync`
would not have rebuilt anything even with the right command name. **And the
server does not cover for it** — `EntityFuzzyIndexPG.initialize` is called with
`skip_if_populated=True`, so a restart will not pick up imported entities either
once the band tables are non-empty. A bulk import followed by the documented
step left entities out of the fuzzy index indefinitely, silently.

`entity_admin.py` also prints `Set ENTITY_FUZZY_ENABLED=true` on four paths and
never reads that variable. It is read only by `vitalgraph_entity_registry_cmd.py:157`.

## Why this was not caught

Nothing about it is visible from the tool's own output. `fuzzy status` says
`Backend: memory`, which is *true of what the tool built* and reads as a
configuration report. The one place it would surface — `fuzzy check` disagreeing
with reality — is the command that cannot disagree.

## Production is fine, which is the reason this stayed hidden

Measured on the production instance 2026-09-29, so that a fix is not confused
with a repair:

    entity (active)                1,271,388
    entity_fuzzy_hash                1,271,388     exact 1:1
    entity_alias                         7,782
    entity_fuzzy_band   band_id=0     1,279,170  = 1,271,388 + 7,782, exact
    entity_fuzzy_phonetic_band  b=0   1,278,955    215 short (names yielding no
                                                   phonetic code — see 249)
    bands 0..20 (21), live rows      26,862,754 ≈ 21 × 1,279,170

All three tables are owned by the application role rather than the RDS master,
so they are readable by the service. Coverage is exact against *current* counts, with entity writes
landing continuously (max `updated_time` was the same day). The PostgreSQL
index is complete and current. Nothing needs rebuilding.

## What was done

`apps/entity_registry/entity_admin.py`:

* The fuzzy index is no longer built in `connect()`. It is built on first use by
  `_ensure_fuzzy`, selecting `EntityFuzzyIndexPG` when the backend says so.
  Backend resolution goes through `get_scoped_env`, so `LOCAL_*` / `PROD_*`
  prefixes work as they do for the server.
* `search similar`, `fuzzy status`, `fuzzy check` and `fuzzy sync` branch on the
  index class for the sync/async difference.
* `fuzzy status` on PG reports entities hashed, entities banded, name variants
  and phonetic variants, and flags a hashed-vs-banded disagreement as a partial
  rebuild. On memory it says the index is discarded on exit.
* `fuzzy check` on PG compares against entities **and** active aliases —
  see the grain trap below. On memory it now says outright that it is not a
  consistency check and why.
* `fuzzy sync` gained `--since-hours N` (incremental, no truncate) and refuses a
  full rebuild on PG, pointing at `migrate_fuzzy_redis_to_pg.py`. `--entity-id`
  works on both backends.
* The four stale `Set ENTITY_FUZZY_ENABLED=true` messages are gone.

Two side effects worth naming because neither is cosmetic:

**`stats`, `export` and `types list` no longer build a fuzzy index.** `connect()`
built it for every command, so every invocation of the tool paid a full-corpus
load whether or not it touched fuzzy anything.

**`project_root` was wrong and would have made this fix inert.** It was
`Path(__file__).parent.parent`, which is `apps/` — not the repo root — so
`sys.path` got `apps/`, the module-level `.env` load pointed at a file that does
not exist, and `import vitalgraph` was free to resolve to an installed copy
instead of the checkout. The tool worked only because `VitalGraphConfig()`
independently walks up from the cwd to find `.env`. Fixed to three levels.
`apps/fuzzy_index/migrate_fuzzy_redis_to_pg.py` has the same two-level bug.

`vitalgraph/entity_registry/entity_fuzzy_storage.py`: added
`get_indexed_counts(table)`, returning `(variants, entities)` from a single band.

`vitalgraph/entity_registry/entity_fuzzy_pg.py`: `get_entity_count_db()` counted
`COUNT(DISTINCT entity_key)` on the band table — variants, not entities, under a
name that says otherwise. It had no callers, so it was a trap rather than a live
bug. Now delegates to `storage.get_entity_count()` (the hash table, one row per
entity).

**Exercised on both backends** against local `sparql_sql_graph`: `fuzzy status`,
`fuzzy check`, `fuzzy sync` bare / `--since-hours --dry-run` / `--entity-id`,
`search similar`, and `stats` confirmed to build no index. The memory backend was
re-run under `LOCAL_ENTITY_FUZZY_BACKEND=memory` and behaves as before.

## The fix — and why `initialize` is not part of it

The first draft of this issue treated `EntityFuzzyIndexPG.initialize()`'s opening
`await self.storage.truncate_all()` as a hazard that made wiring the tool a
judgement call. **That was wrong, and it was wrong because it carried the memory
backend's assumption across.** For an in-process index, "sync" must mean "build
it", because nothing is persisted. For the PG backend the bands *are* the
persisted index, and the class is explicit that nothing needs warming
(`entity_fuzzy_pg.py:578`):

    # Bands persist across restarts; scoring metadata is lazy-loaded per
    # query, so there is nothing to warm here.

Two facts settle it. `_initialized` is **set** in four places and **read in
none** — there is no guard, nothing refuses to serve an un-initialized PG index.
And `find_similar` calls `get_candidate_ids` (straight to the band tables) then
`_load_candidate_data` (lazy, per query). It never touches a prebuilt in-memory
structure.

The truncate is gated on `since is None`, so it only fires for an explicit full
rebuild. The docstring says as much: *"Rebuild tools leave this False so an
explicit rebuild still truncates and reloads."* `fuzzy sync` is not a rebuild
tool.

So the correct wiring calls `initialize` rarely or never:

| Command | PG call |
|---|---|
| `search similar` | `await find_similar(...)` — no init; instant, instead of loading 1.27M entities first |
| `fuzzy status` | `await get_entity_count_db()` (the `entity_count` property is `len(self._entity_cache)`, which is 0 until queries populate it) |
| `fuzzy check` | `get_entity_count_db()` against the expected count — and it can now actually disagree |
| `fuzzy sync` | `initialize(since=...)`, incremental and non-truncating, or `skip_if_populated=True` |

A full rebuild stays where it already is, behind
`migrate_fuzzy_redis_to_pg.py --rebuild`.

### The trap in the obvious wiring of `fuzzy check`

`get_entity_count_db()` is `SELECT COUNT(DISTINCT entity_key) FROM
entity_fuzzy_band`, and `entity_key` is `entity_id::variant_index`. **It counts
name variants, not entities.** On production that is 1,279,170 against 1,271,388
entities, and the 7,782 difference is exactly `entity_alias`.

Comparing it to `COUNT(*) FROM entity` — the obvious thing, and what the memory
path does — would report 7,782 phantom missing rows on a healthy index. Fixing a
check that cannot fail by shipping one that cries wolf is the same defect with
the sign flipped. Compare against entities + active aliases, or
`COUNT(DISTINCT split_part(entity_key, '::', 1))`.

### Remaining shape differences

`add_entity`, `find_similar`, `find_similar_by_name` and `clear_index` are sync
on `EntityFuzzyIndex` and async on `EntityFuzzyIndexPG`, and the PG class has no
`storage_config` attribute, which `cmd_fuzzy_status` reads to print the backend
name. Roughly five call sites need the `isinstance` branch that
`entity_fuzzy_ops.py` and `entity_registry_impl.py` already use.

## Separate, found in the same production check — worth its own issue

The visibility map is empty on two of the three tables:

    entity_fuzzy_band            230,606 pages,       0 all-visible (0.0%)
    entity_fuzzy_hash             14,195 pages,       0 all-visible (0.0%)
    entity_fuzzy_phonetic_band   252,521 pages, 236,209 all-visible (93.5%)

So index-only scans on the two hot tables are not index-only. A representative
band lookup, on production:

    Index Only Scan using idx_fuzzy_band_lookup  (actual time=2.033..3.941 rows=152)
      Heap Fetches: 152          <-- every row
      Buffers: shared hit=158 read=9

`entity_fuzzy_hash` takes 7,067,663 index scans — the hottest index in the
registry — and every one of them fetches from the heap. This is not the killed-
VACUUM mechanism of `issues/136`: `autovacuum_vacuum_insert_scale_factor` is
0.2, so the band table needs ~5.4M inserts to trigger an insert-vacuum and is at
2.86M. It will not self-heal for a long time. Last autovacuum on
`entity_fuzzy_band` was 2026-07-29; the phonetic table was done 2026-08-20 and is
the one that is healthy, which is the whole difference.

A manual `VACUUM` on the two tables is the fix, and needs `SET statement_timeout
= 0` in the session or the instance's 1-minute cap kills it (`issues/136`).
