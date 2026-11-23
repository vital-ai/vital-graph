# 348 — A space created on one instance is unusable on another

## Status: FIXED 2026-11-23 (`482e9d5a` … `869f9cd6`; CI fix `1708ba57`); verified end to end with two containers behind a load balancer; not deployed

### What changed
- **Request resolver** (`vitalgraph/space/space_resolution.py`).
  - An async dependency, mounted by `VitalGraphAppImpl._include_space_router` on the 26
    routers with `space_id` routes (125 routes).
  - It depends on auth, so it runs after authentication.
  - If this process cannot name the request's space, it calls `ensure_space_loaded`
    before the handler runs.
- **"Resolved" now means the key map, not the registry.**
  - `space_names` remembers spaces read and found unkeyed (`_UNKEYED`, `mark_unkeyed`,
    `is_resolved`). `load_storage_keys` marks them, including on an unmigrated database.
  - `ensure_space_loaded` takes its fast path only when the space is registered AND
    resolved.
  - A registered space whose read fails stays available, as before.
- **Create.**
  - `create_space_with_tables` reads the row (loading its key) before the table check.
  - `create_space_metadata`'s upsert replaces an existing row only when that row names no
    objects (`... WHERE` on both quad tables, `RETURNING`).
  - The key is held from allocation until the row is written or abandon
    (`space_names.begin_create` / `end_create`). `load_storage_keys` skips a space being
    created here, so another instance's same-id "created" notice cannot swap the key in
    mid-create. The row write uses the key this create allocated.
  - One create per id at a time in a process (`create_space_with_tables` takes a per-id
    `asyncio.Lock`). The hold is per id, not per create, so two same-id creates on ONE
    instance (a client retrying after a timeout) used to run together. The second replaced
    the first's key mid-create, and the first's release ended the hold for both. On a real
    database both then FAILED (400): one create's failure path forgot the shared key, so the
    other built its next tables under the bare id (`relation "probe348_…_datatype" does not
    exist`), and each left its keyed tables behind as orphans. Now the second waits, finds
    the space, and is refused.
  - A create that fails partway (a DDL error, a dropped connection) drops the tables it
    already built, while its key is still held, before releasing it
    (`_drop_partial_create`). It used to forget the key and keep them: orphans with no
    row, under a key nothing remembers, found only by
    `scripts/cleanup_orphan_space_tables.py`. Nothing is dropped when no key was
    allocated, or when the map no longer holds this create's key.
  - On a lost row, `_abandon_lost_create` drops only this create's own tables, still
    under its own key, then releases the hold and loads the winner's key. A failure of
    that reload is caught: the key is forgotten (re-read on next use) and the create still
    reports `SpaceAlreadyExistsError`. Escaping as a plain error, it made
    `create_space_metadata` return False, and `SpaceImpl.create`'s rollback
    (`delete_space_storage`) then deleted the winner's `space` and `graph` rows by id.
    `SpaceAlreadyExistsError` propagates
    through `SpaceImpl.create` and `create_space_with_tables`. Both previously turned it
    into `False`, and the old metadata-failure rollback (`delete_space_storage`) would
    have deleted the OTHER space's `space` and `graph` rows.
- **Delete.**
  - The "deleted" signal re-reads the row first.
    - If the row is gone, it calls `SpaceManager._forget_space`: registry record, storage
      key, and `invalidate_space_caches`.
    - If the space has already been re-created (a late notice), it drops only the caches
      and keeps the new space's record and key.
  - `_forget_space` never drops the key of a create in progress here.
  - The refresh forgets spaces whose row is gone. That covers spaces cached before its
    read, and also keys held without a registry record (the import/export path loads
    one), except creates that were in progress when it started.
  - `delete_space_with_tables` resolves the space first.
- **Body-named spaces.**
  - `ImportExportJobManager._resolve_job_space` runs at job start.
  - The process trigger calls `ensure_space_loaded`.

### Verified
- `test_scripts/debug/_issue348_cross_instance_race.py`: 500 before the fix, 200 from the
  keyed table after it.
- `tests/unit/test_a_space_created_elsewhere_is_usable_at_once.py`: 17 tests at
  `482e9d5a`, 21 at `87acf917`, 23 at `8e7a9436`, 25 now. Against the code before `482e9d5a` (extracted to
  a temp dir), 13 of the first 17 failed.
  - Of the 4 that passed there, the two request tests exercise the new resolver module
    itself, and the other two check behaviour that is unchanged.
  - The partial-create cleanup's "fails partway" test fails on `8e7a9436`.
  - The same-id test fails with the lock bypassed: both creates report success there.
    That is the fake backend; on a real database both failed (see "What changed").
  - Each test starts with an EMPTY key map. At `87acf917` it only forgot the test's own
    space, so running this file in one pytest session with the integration file failed
    the four refresh tests in `TestDeleteElsewhere`: they saw, and forgot, keys the
    integration tests had loaded. Each file passed on its own.
  - Includes `test_space_routes_resolve_their_space`, which builds the real app and fails
    for any `space_id` route without the resolver.
- Full unit suite: passes. The only failure before this commit was
  `test_every_indexed_issue_is_COMMITTED`, about this issue's own file being uncommitted.
  - A leak from the new route-coverage test was found and FIXED before the commit. It
    built the app with the repo's `.env` loaded, and that broke two later tests
    (`test_entity_registry_vector_config`, `test_archive_tooling_reports_outcomes`)
    through module-level values read while it was loaded. It now patches out
    `load_dotenv_files` and uses placeholder DB settings, and both tests pass after it.
- Reported by the reviewer, run on the local kind cluster against `87acf917`:
  - `tests/integration/test_a_duplicate_create_cannot_rekey_a_space.py`: 4 passed. These
    are the manager refusing; the row write refusing and dropping only its own tables,
    with A's notice arriving mid-create; an orphan row still being taken over; and a delete
    on an instance that had not heard of the space dropping the keyed tables. They exercise
    the row write's `to_regclass` guard against a real database.
  - Two processes over one database, create on A then read on B: B answered 200 in 20 of
    20 tries. The pre-fix commit `4b5eeb8c` running as B failed 14 of 20 with
    `relation "probe348_…_vector_index" does not exist`.
- Reported by the reviewer, run on the local kind cluster against `8e7a9436`:
  - The unit and integration files in one pytest session: 27 passed. The cross-file
    pollution is fixed.
  - Two processes, create on A then read on B at once, x20: 20 of 20 answered 200. B's
    resolver re-read the space all 20 times.
  - Two simultaneous creates of one id on one instance, x10: exactly one won every time.
    The other got "already exists in manager", and nothing was left behind.
  - The same check on `87acf917` (no lock): both creates failed with 400 every time, and
    each left a full table set orphaned (20 sets of 27 tables).
- Reported by the reviewer, run on the local kind cluster against `f0b09be7`:
  - A create forced to fail after building its core tables (27) returned False and left
    none of its tables or functions behind. Its key and its hold were both released.
  - The unit and integration files in one pytest session: 29 passed.
  - A client that gives up on a create (50 ms timeout), then retries the same id: the
    server did not cancel the abandoned create. It finished, and the retry was refused
    as "already exists". `create_space_storage`'s `except Exception` (which a
    `CancelledError` would skip) therefore only matters at shutdown, when the process is
    exiting anyway.
- After `f0b09be7`: the branch where a failed create finds the key map no longer holding its
  key now logs a warning naming the orphaned prefix. It is not reachable with the per-id
  lock, so it is not tested.
- Reported by the reviewer, end to end on the local k8s setup (kind), 2026-11-23:
  - Setup:
    - Two vitalgraph containers per round, built from this repo's Dockerfile, behind an
      nginx round-robin load balancer, as in production.
    - One database (`sparql_sql_graph` on vital-pg), reached through the pooler in
      session mode, as `dev_stack.py --k8s` runs it.
    - The deployment's own provisioning script (the step that failed on 2026-11-21) ran
      5 times per round with no retries, each run creating new spaces and their indexes.
  - HEAD `869f9cd6`: 5 of 5 runs provisioned on the first try, with no 500s. Each container
    resolved a space it had not yet heard of 5 times.
  - Pre-fix `4b5eeb8c`: 0 of 5. Every run failed at `GET /api/vector-indexes?space_id=…`
    with 500 "does not exist", the production error. The failures were always on the same
    container: round-robin sent each create to one container and the next call to the
    other.
  - One difference from production: there the planned AWS setup connects to the primary
    directly, not through a pooler. Session mode keeps NOTIFY working either way, and the
    fix does not depend on NOTIFY.
  - Conclusion: the deployment can drop its provisioning retries once a release with
    these commits is deployed there.
- CI: "Tests (Tier 1 + 2)" failed from `482e9d5a` to `869f9cd6`. The app-building
  route-coverage test needs `itsdangerous` and `uvicorn`, server-only packages the unit tier
  does not install. Fixed in `1708ba57`: that test skips without them, and a source-level
  check runs instead, resolving each router mounted with plain `include_router` to its
  module and requiring that none declares a `space_id` parameter. Tier 1 + 2 passes:
  6,427 passed, 21 skipped.

Found from outside, by a deployment that runs two vitalgraph instances behind one load
balancer over one PostgreSQL database. On 2026-11-21 its provisioning (create a space, then
its indexes) failed with a 500 the first time it touched each new space. Its workaround is
to run provisioning up to 3 times; the second run succeeds. That workaround goes once a fix
ships here.

The cause was found by reading the code at `4b5eeb8c`. The deployment's own logs then
confirmed the timing (§3).

**Reproduced in-process, 2026-11-23**
(`test_scripts/debug/_issue348_cross_instance_race.py`, no database).
- Setup: instance B is a real `SpaceManager` with the real "created" signal handler. Its
  backend read is delayed 180 ms. The request goes through the real vector-index router,
  mounted as the app mounts it.
- While the handler runs, `GET /api/vector-indexes?space_id=app_memory` answers 500
  after querying `app_memory_vector_index`.
- After the handler finishes, the same call answers 200 from `vgs_abcdefgh_vector_index`.
- This matches the production log.

The duplicate create (§4) is exercised against a real database by
`tests/integration/test_a_duplicate_create_cannot_rekey_a_space.py`, including A's notice
arriving mid-create (passed on the local kind cluster; see "Verified").

## Symptom

1. A client creates a space. The request lands on instance A.
2. The client at once calls a space-scoped endpoint, such as creating or reading the
   space's vector index. That request lands on instance B.
3. B answers 500, "relation does not exist".
4. The same call a moment later works.

## Cause

Each process keeps two caches of spaces. Both are filled at startup, by the process's own
creates and deletes, by NOTIFY from other instances (`SpaceManager._handle_space_signal`,
`space_manager.py:864`) and by a refresh every 60 s (`_refresh_cache_from_db`, `:960`;
started at `vitalgraphapp_impl.py:683`).

### 1. The space registry: not what failed

`SpaceManager._spaces` (`space_manager.py:84`).
- `get_space()` (:594) and `has_space()` (:662) read only the cache.
- `ensure_space_loaded()` (:676) and `get_space_or_load()` (:747) re-read the `space` row
  on a miss. The re-read goes through `get_space_metadata()`
  (`sparql_sql_space_impl.py:951`), which also loads the storage key (:964).
- The kg, sparql, triples, kgdocuments and kgquery endpoints use these.
  `VitalGraphAPI.get_space_by_id` (`vitalgraph_api.py:400`) does too, so fetching one
  space by id works on B.

### 2. The storage-key map: the failure

`space_names._KEYS` (`vitalgraph/db/sparql_sql/space_names.py:59`).
- `space_prefix()` (:63) builds every per-space object name from this map. It is
  synchronous, so it cannot read the database.
- When the space is not in the map, `space_prefix()` silently falls back to the bare
  space id. This fallback is temporary until Stage 4 of the storage-key plan.
- New spaces are keyed. On B, a new space not yet in the map is named `{space_id}_…`
  instead of `vgs_<key>_…`, and those tables do not exist.
- `vector_indexes_endpoint.py` calls `space_prefix()` 12 times (:120, :200, :279, …).
  `geo_points_endpoint.py` calls it 3 times. Neither asks the space manager first.
- The full-text index, search/vector/fuzzy mapping, geo config, files, objects and
  metrics endpoints reach `space_prefix()` through helpers, also without the space
  manager.

### 3. Why B had not caught up: a race with B's NOTIFY handler (confirmed from production logs)

B is meant to learn a new space's key from the "created" NOTIFY. `_handle_space_signal`
calls `get_space_metadata()` for "created" and "updated" (`space_manager.py:877`), and that
loads the key. A sends the NOTIFY just before it answers the create. B's handler does an
async database read before it registers the key. A client that sends its next request as
soon as the create returns can reach B inside that window.

The deployment's logs from 2026-11-21 show exactly this. A is the instance ending `e57dd6`,
B the one ending `0929a5`, all times 16:58:56:

| time | instance | event |
|---|---|---|
| .507 | A | `POST /api/spaces`: creating `app_memory` starts |
| .818 | A | sends the "created" NOTIFY |
| .819 | B | receives it; the handler starts its database read |
| .820 | A | answers the create with 200 |
| (between) | B | `GET /api/vector-indexes?space_id=app_memory` arrives and runs before the key is loaded |
| .995 | B | event loop reports a 138 ms stall, which held up the handler |
| .997 | B | `Space 'app_memory' added to local registry via signal` |
| .999 | B | the vector-index request answers 500, having looked for `app_memory_vector_index` (the bare-id name) |

- B received the NOTIFY about 1 ms after A sent it, so B's listener works. This is **not** a
  broken listener, and the other cross-instance signals (token versions, entity caches,
  fuzzy mappings) are not affected.
- Loading the key took about 180 ms. Most of that was the event-loop stall, not the read.
- Stalls widen the window, and both instances had them: B 138 ms here, A 236 ms just
  before the create. With ~180 ms to aim at, a client issuing its next call at once hits
  the window on every new space, which matches what production saw. Without stalls the
  window shrinks to a few milliseconds, but it never closes.
- The 60 s refresh only matters when a NOTIFY is never received. That did not happen here.

The fix (resolve an unknown space before the request runs) closes this case. B no longer
depends on having handled the NOTIFY before the next request arrives.

Unrelated errors in the same logs: `relation "space" does not exist` and similar at 16:03
came from the first boot, before the database was initialized (auto-init). They are not
part of this issue.

### 4. Related and worse: a duplicate create re-keys the space and splits the instances

The same create call, landing on B before B knows the space:
1. `create_space_with_tables` checks `self._spaces` (`space_manager.py:269`), which is
   cache-only, so B sees nothing.
2. It then calls `space_backend.space_exists()` (:275). That calls
   `SparqlSQLSchema.space_tables_exist()` (`sparql_sql_schema.py:2504`), which builds the
   table names with `space_prefix()`. That gives the bare id, so it finds no tables.
3. `create_space_storage()` (`sparql_sql_space_impl.py:868`) allocates a NEW key and
   creates a full set of tables under it.
4. `create_space_metadata()` (:1035) upserts the row with
   `ON CONFLICT (space_id) DO UPDATE SET … storage_key = EXCLUDED.storage_key` (:1047).
   The comment there assumes "a row that already exists here had no objects (creation
   checks)", and step 2 is where that assumption breaks.

Result:
- A still holds the old key and reads and writes the old tables. B holds the new key and
  uses the new, empty tables. The two instances serve different data for one space id.
- At A's next refresh, `list_spaces()` → `load_storage_keys()` registers the new key on A
  too. From then on the space's real data is cut off, orphaned under the old `vgs_` prefix.
  Writes A made between the duplicate create and that refresh are cut off with it.
- The caller is told the create succeeded, not `SpaceAlreadyExistsError`.

Not seen in production; the retrying provisioning would reach it only if its creates are
not idempotent client-side. Severity is data loss, so it is fixed with the rest.

The same split can happen on ONE instance: two same-id creates running together there
(a client retrying after a timeout) both pass the checks. Fixed with a per-id create
lock. See "What changed".

### 5. Deletes from another instance leave state behind

- The "deleted" NOTIFY branch (`space_manager.py:899`) pops the registry entry but never
  calls `forget_storage_key()`. It also leaves the per-space caches (term, stats, count,
  entity-graph, …) in place.
- The refresh never drops keys either. `load_storage_keys()` touches only the rows it
  reads (`space_storage_key.py:55`), so a deleted space's key is never removed.
- `space_cache_invalidation.invalidate_space_caches()` already drops every per-space
  cache, and the registry record when given the manager. Its docstring states that it is
  process-local and that no other instance acts on it (`issues/232`). Neither the delete
  handler nor the refresh calls it.
- If the space is re-created under the same id, the "created" signal re-registers the new
  key, but the per-space caches can still answer from the old space.
- A late "deleted" notice can arrive after the same id was re-created. Each instance also
  receives its own notices, so a quick delete-then-create on one instance is enough.
  - Before the fix this dropped the new space's registry entry.
  - The first version of the fix (`482e9d5a`) also dropped its key and caches. Requests
    recovered through the resolver, but background work listing the registry missed the
    space until the next refresh.
  - Fixed after review: the handler re-reads the row and keeps a space that exists again.

### 6. The refresh evicts a space created during its read

`_refresh_cache_from_db` takes a snapshot with `list_spaces()`. It then removes every
cached id not in that snapshot (`space_manager.py:1007`). A space this process creates
between the read and the removal is evicted. Its key survives, since
`load_storage_keys()` does not forget unread rows, so later requests reload the registry
entry through `ensure_space_loaded`. Only background work that lists spaces from the
registry misses it until the next refresh.

## Fix

**Resolve unknown spaces before a request runs.**
- If the process does not know a request's space, re-read the space's row with
  `get_space_metadata()` before the handler runs. That call loads the key, and the space
  is registered as well.
- An id that does not exist stays unknown and is reported as now (HTTP 200 not-found).

Where it hooks in (investigated 2026-11-23):
- Space-scoped routes take `space_id` as a query parameter (`Query(...)`), not a path
  parameter. Every handler then calls `require_space_read` / `require_space_write`
  (`auth/role_dependencies.py:82`, `:131`). Those are synchronous, so the fix can't live
  there.
- Every router gets the same auth dependency, `self.get_current_user`, and is mounted
  with `app.include_router` (`vitalgraphapp_impl.py:1225-1487`).
- So: one async dependency, `resolve_space(request, user=Depends(get_current_user))`, which
  reads `request.query_params.get("space_id")` and is passed as
  `include_router(..., dependencies=[Depends(resolve_space)])` for the space-scoped
  routers.
- Because it depends on auth itself, it runs after authentication. Requests that fail
  authentication never reach the database read. FastAPI caches dependencies per request, so
  auth still runs once.
- A `resolve_space` call and the signal handler may both load the same key at the same
  moment. Both paths are idempotent (`register_storage_key` replaces), so that is harmless.
- **"Known" must mean the key map, not the registry.** The signal path adds a registry
  entry even when loading the key failed (`space_manager.py:880-895`), so registry
  membership does not prove the key is loaded.
- **Unkeyed spaces must not re-read on every request.** A space created before the key
  cutover correctly has no key in the map. Remember "checked, unkeyed" per id, cleared on
  signals and refresh, so the hit path stays a dict lookup.
What a query-parameter hook does not cover:
- **Import and export jobs.** The job is created by one request (`space_id` in the body,
  `import_model.py:47`, `export_model.py:22`) and started by another that carries only a
  `job_id` (`import_endpoint.py:324`, `export_endpoint.py:295`).
  `ImportExportJobManager.start_job` runs the job as a task on whichever instance received
  the start (`jobs/import_export_manager.py:283`). The job then names tables through
  `space_prefix()` / `get_table_names()` (`data_import_impl.py:88`, `:464`;
  `data_export_impl.py:129`). So `start_job` (or `_run_job`) must resolve the job's
  `space_id` itself. It only holds the pool, so it should call
  `load_storage_keys(conn, space_id)` directly. That works without a space manager.
- **Process triggers.** `process_endpoint.py:120` passes `body.space_id` to
  `scheduler.trigger_now`. A manual trigger right after a create is unlikely, but the
  handler should resolve the same way.
- **Already covered:** the one kgentities route with `space_id` in its body
  (`kgentities_endpoint.py:718`) and the segmentation and index-sync workers already call
  `get_space_or_load`.

**Create checks the row, not the tables.** The duplicate create is reachable today:
`POST /api/spaces` → `VitalGraphAPI.add_space` (`vitalgraph_api.py:213`) →
`create_space_with_tables`, with no database read in between.

How it would happen: the client checks whether the space exists through the listing,
which is registry-only, so a just-created space can be missing on B. It then creates on
B inside the same ~180 ms window.

The deployment's retried provisioning is safe in practice: its second run comes long after
B has the space registered, and `create_space_with_tables` refuses at `:269`.
- `space_exists()` must report the `space` row (and its key), not tables named by
  `space_prefix()`. Or `create_space_with_tables` can call `ensure_space_loaded()` before
  its cache check.
- `create_space_metadata()` must not overwrite an existing row's `storage_key`. Insert, and
  treat a conflict as `SpaceAlreadyExistsError` with the new tables dropped. This also
  covers two instances creating the same id at once: the `space` primary key decides it.

**Deletes elsewhere clear everything.**
- The "deleted" signal branch calls `forget_storage_key()` and
  `invalidate_space_caches(space_id)`. (`_forget_space` removes the registry record
  itself, so the `space_manager` argument is not passed.)
- The refresh does the same for each id it drops. That includes keys held without a
  registry record (an import/export job loads one directly), except a create in progress.
- A late "deleted" notice for a space already re-created keeps the new space (the row
  decides) and drops only the caches.

**A same-id create on two instances at once** (found in review of `482e9d5a`). The row
write took its key from the shared map at write time.
- If A's "created" notice reached B mid-create, B's map held A's key. B's write then
  passed as "already holds this key": B reported success over its own orphaned tables, and
  B's setup after the write landed in A's tables.
- Passing the allocated key alone would not have been enough. Once the write refused, the
  abandon dropped tables by `space_prefix`, which by then gave A's key: it would have
  dropped A's tables.
- So the create holds its key (`begin_create`) until the row is written or abandoned, and
  `load_storage_keys` leaves a space being created here alone.

**The refresh keeps what it did not see.**
- Record the set of cached ids before `list_spaces()`. Evict only ids that were in that
  set and are absent from the result.

A periodic age check (re-read each cached space every ~10 s) was considered for lost
delete notifications, and not proposed. The main loss case, a LISTEN reconnect, already
clears the caches (`vitalgraphapp_impl.py:857`), and the age check costs a read per
cached space per interval.

## Tests

No test covers the "created" or "deleted" branches of `_handle_space_signal` today. The
storage-key tests (`test_storage_key_rules.py`, `test_space_rekey.py`,
`test_migrate_space_storage_key.py`) all run within a single process.

Unit level, simulating two instances: two space managers, each with its own key map (the
map is module-level, so swap or patch it per instance), over one fake or real database.
- A space created on A is usable on B at once, through an endpoint that never calls the
  space manager (vector indexes).
- An import or export job created on A and started on B for a space B does not yet know
  runs against the keyed tables.
- An unknown id stays unknown and is re-read on every request. Caching the miss would
  bring the race back for a space created elsewhere a moment later. The cost is one
  indexed read per request for a made-up id, after authentication.
- An unkeyed (pre-cutover) space is resolved once, not once per request.
- A duplicate create on B raises `SpaceAlreadyExistsError`. A's key and row are unchanged,
  and no `vgs_` tables are left behind.
- A delete on A clears B's registry entry, key and per-space caches, both through the
  signal and through the refresh.
- The refresh keeps a space created during its `list_spaces()`.

Integration, on the vg test stack: run two server containers against the same database,
alternate requests between them, and run the create → create-vector-index sequence that
failed. Also run the existing new-space and re-key integration tests.

To make the race repeatable, delay B's signal handler (patch `get_space_metadata` in the
handler to sleep, say 500 ms) rather than relying on timing. Without the fix the
vector-index call fails every time; with it, the call succeeds.

## Out of scope

- The listing (`list_spaces`) reads the registry, so on B a brand-new space can be missing
  from the list until the NOTIFY or the refresh arrives. Fetching that one space by id
  already works.
- Space rename across instances is `issues/232` (a signal carrying both ids).
