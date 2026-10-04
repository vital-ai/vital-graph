# Changelog

Notable changes per release. Dates are the release date, not the first commit.

## 0.0.46 — 2026-10-04

4 commits since 0.0.45 (same day), one of them code. Frame `create` and entity-
frame `update` now mean what they say, with no switch (`issues/256`). **Server
only — the client is unchanged from 0.0.45**; upgrading the package changes
nothing for a caller until the server is deployed.

### Changed — behaviour a caller will see (server)

- **Frame `create` refuses anything that already exists**, on both
  `/kgentities/kgframes` and `/kgframes`: if any object sent (frame, slot, slot
  edge) exists, it answers `already_exists` and writes nothing. It was accepted —
  and on the entity route MERGED into the frame, keeping its old slots beside the
  new. **A caller that re-saves a frame through `create` must send `upsert`.**
  `VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING` (0.0.45, default off) is REMOVED.
- **Entity-frame `update` is all or nothing.** It SKIPPED a frame that was
  missing or another entity's and still answered `updated`: a batch of an
  existing frame and a new one wrote the first, dropped the second, and reported
  success. Now the whole request is decided before any of it is written: a
  missing frame → `not_found`; another entity's frame → `invalid_request`;
  slots or edges sent without their frame → `invalid_request` (an update
  replaces the frame graph and would drop the frame). Nothing written. Frames
  that commit before a later one fails answer `partial` (not a success), not
  `updated`.

A caller meaning create-or-replace sends `upsert`, which is unchanged: it
replaces an existing frame's graph and creates a missing one.

## 0.0.45 — 2026-10-04

5 commits since 0.0.44 (same day). Slot writes to an entity's frame move to
their own route, locked on the entity; the entity registry gains get-or-create
by an identifier declared unique (`issues/227`); an unbound `GRAPH ?g` stops
being planned for one row (`issues/258`); and `VitalGraphClient` wraps every
KG entity and frame method — which found eleven wrappers that were broken.

**Deploy the server first, and run the registry migration BEFORE it.** The new
code writes `entity_identifier.entity_type_id`; deployed before
`apps/entity_registry/migrate.py` adds the column, every identifier insert
fails. The new client methods call routes only the new server has.

### Changed — behaviour a caller will see (server)

- **`/kgframes/kgslots` refuses an entity's frame** (write and delete),
  `invalid_request`, pointing to the new `/kgentities/kgframes/kgslots`. A
  caller editing an entity frame's slots through `/kgframes/kgslots` breaks on
  deploy until it moves (`issues/256`).
- **Slot routes:** `update` of a missing slot is `not_found`; a slot of another
  frame refuses the request; deleting a slot already gone is `no_op` (was
  `not_found`), with the URI in `absent_uris`.

### Added — server

- **`POST /kgentities/kgframes/kgslots`, `DELETE /kgentities/kgframes/kgslots`**
  — slot writes and deletes on an entity's frame: one transaction under the
  entity lock, the frame must be the entity's, `if_unmodified_since` is the
  entity's stamp, and `hasKGGraphURI` is set on what is written.
- **`POST /api/registry/entities/resolve`** — get-or-create by an identifier
  DECLARED unique for an entity type: `created` or `found`, and concurrent
  callers converge on one entity. A pair not declared is refused. `create` and
  `add_identifier` answer `already_exists`, naming the holder, when a declared
  value is taken (`issues/227`). Nothing is declared in this release.
- **Frame `create` can refuse an existing frame** —
  `VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING=1`, default OFF: callers that rely
  on `create` overwriting must move to `upsert` first.

### Added — client

- `kgentities.create_entity_frame_slots` / `delete_entity_frame_slots`;
  `kgframes.delete_frame_slots(if_unmodified_since=...)` and `absent_uris`;
  `entity_registry.resolve_or_create_entity`.
- **`VitalGraphClient` wraps every `kgentities` and `kgframes` method** — 28
  added (slot routes, entity-frame writes, child frames, frame graphs, queries,
  counts), and the existing wrappers take every parameter their endpoint does.
  `VitalGraphClientInterface` declares them all.

### Fixed — client (behaviour changes)

- **`list_kgentities(..., search=...)` sent the search term as the entity TYPE
  filter.** It is a search now.
- **`get_kgframes_with_slots`** put `page_size` in `frame_uri`, `offset` in
  `page_size` and `search` in `offset`.
- **The six KGType wrappers** passed `graph_id` after KGTypes became
  space-scoped: five raised `TypeError`, `list_kgtypes` sent the graph id as
  `page_size`. They accept `graph_id` and ignore it; `list_kgtypes` gains
  `type_uri`.
- **`upload_file_content`** sent the file URI as the graph and the graph as the
  data.
- **`search_triples`** called a method that does not exist; it uses
  `list_triples`.
- **`execute_graph_operation` is REMOVED** — it called a method that does not
  exist and never worked. Use `create_graph` / `drop_graph` / `clear_graph`.

A caller that worked around any of these gets different results after
upgrading.

### Fixed — server

- **An unbound `GRAPH ?g` was estimated at ONE row** and planned as nested
  loops — the two `statement_timeout` cancellations on production
  (`issues/258`). The default graph was excluded through a subquery the planner
  cannot estimate; it is now a literal uuid, and the unbound plan is the bound
  plan. Locally 2.0 s → 156 ms median on the reported shape; results unchanged.

### Data

- `apps/entity_registry/migrate.py` adds `entity_identifier.entity_type_id` —
  run BEFORE deploying.
- `apps/entity_registry/backfill_identifier_entity_type.py` fills it for
  existing rows (batched, re-runnable) — run after deploying.
- `apps/entity_registry/declare_unique_identifiers.py --report` (read-only)
  shows, per type and namespace, the duplicates that block a declaration;
  `--apply` builds the declared indexes.

## 0.0.44 — 2026-10-04

31 commits since 0.0.43 (2026-10-01). A frame write now means what it says:
`update` and `upsert` REPLACE the frame graph instead of merging into it, and
every delete and `replace` is one locked, guarded transaction scoped to what the
request names (`issues/256`, `issues/257`). Several of these are **behaviour
changes a caller will see** — read the first section before upgrading.

**Release the client after the server.** An older server ignores
`if_unmodified_since` on deletes, so a guarded delete against it runs
unguarded. Everything else in the client works against either.

### Changed — behaviour a caller will see (server)

- **Frame `update` and `upsert` replace the whole frame graph.** A slot or slot
  edge left out of the request is DELETED; it used to survive, still attached
  (a merge reported as success). Send each frame you update whole: the frame,
  every slot, every `Edge_hasKGSlot`. Other frames, and child frames, are not
  touched.
- **The server decides every `hasFrameGraphURI`**; whatever a client sends is
  discarded. A request with several frames and a slot whose owning frame cannot
  be determined (no `Edge_hasKGSlot` naming it) is refused, `invalid_request`,
  nothing written.
- **Deleting an entity WITHOUT `delete_entity_graph=true` is refused** while
  the entity has frames, slots or edges (`invalid_request`). It used to delete
  the entity alone and leave them pointing at nothing.
- **`replace` is scoped to the frames it names** and their descendants, on both
  routes. It used to delete every root frame of the entity, or every child of
  the parent. It is one transaction now, guarded, and a refused or failed
  replace changes nothing.
- **`/kgframes` refuses an entity's frames** — create, update, upsert, replace
  or delete over one, or `parent_uri` naming one or naming an entity. Entity
  frames go through `/kgentities/kgframes`.
- **Entity-frame upsert** refuses a frame that belongs to another entity, and
  writes nothing onto a missing entity; a frame it creates is now linked from
  the entity. It answers `upserted` (was `created`).
- **`/kgframes` update of a frame that does not exist** answers `not_found`
  (it created it). **An unknown `operation_mode`** answers `invalid_request`
  (it became a create). **`/kgentities?operation_mode=replace`** answers
  `invalid_request` (was a 500).
- **Deleting something already gone answers `no_op`** on every route, with
  `absent_uris` naming it (was `store_failed` or `not_found`).

### Added — client

- **`upsert_kgentities`** — entity upsert, which the client could not send.
- **`if_unmodified_since` on the deletes** — `delete_kgentity`,
  `delete_kgentities_batch`, `delete_entity_frames`, `delete_kgframe`,
  `delete_kgframes_batch` and the methods that delegate to them. Stale ->
  `is_conflict`, nothing deleted. One stamp per request.
- **`delete_kgentities_batch(delete_entity_graph=...)`**, and the
  `VitalGraphClient` delete wrappers pass `delete_entity_graph`, `recursive`
  and `if_unmodified_since`.
- **`DeleteResponse.absent_uris`.**
- **`query_frames(include_frame_graph=True)` returns each frame's graph** —
  `frame_graph` as JSON quads, hydrated into `frame_graph_objects`
  (`issues/210`). It was accepted and never implemented.

### Changed — client

- **A `create` is no longer replayed after a post-send failure** (a timeout).
  The retry marking follows the mode: update, upsert and replace are replayed;
  create is not, because a replayed create that had landed answers
  ALREADY_EXISTS. A caller autosaving through `create` should move to `upsert`.
- **Delete responses report the server's count, list and message**;
  `delete_kgentity` said "Deleted 1 items" for a no-op.

### Fixed — client

- **`VitalGraphClient.delete_kgentities_batch` deleted nothing.** It passed a
  comma-separated string to a method that iterated it, so the URIs went out a
  character at a time and the server answered `no_op` — a success. Takes a
  list or a string now.

### Fixed — server

- **New KGTypes are indexed again** (`issues/260`). Auto-sync had no `kgtype`
  scope, so nothing indexed a new or changed type after 2026-09-21; re-populate
  `kgtype_default` after deploying.
- **Entity-frame writes keep vector, geo, fuzzy and FTS rows in step** — they
  scheduled no auto-sync — and an entity graph delete clears its members' rows.
- **A failed or cancelled query logs its SPARQL, its SQL and its timings**
  (`issues/259`): one WARNING `failed_query` line, the `slow_query` shape.
- Every early error in `/kgframes` create ("space not found", "no KGFrame
  objects") was a 500.
- Refused writes answer in the body with their reason; three latent ways a
  guarded write could go unguarded are closed (`issues/253`).
- Entity registry: the postgresql backend, and band rows are all deleted
  (`issues/251`, `issues/252`).

### Data

- `scripts/repair_frame_groupings.py`: the one-time repair of frame form types
  and groupings (`issues/257`), run on production before this release; re-run
  it after deploying.
- `scripts/census_entity_orphans.py`: read-only count of entity graphs whose
  entity is gone.

## 0.0.43 — 2026-10-01

73 commits since 0.0.42 (2026-09-24). THE CLIENT CHANGES, and that is why this
release exists: a caller can now refuse to lose its own update. Everything here
is **opt-in** — a client that passes nothing behaves exactly as 0.0.42 did, and
an older client against a newer server likewise.

### Added — client

- **`if_unmodified_since` on the ten write methods that reach a guarded route.**
  Pass the `hasObjectModificationDateTime` you read and the write is REFUSED if
  the stored value has moved, instead of overwriting a newer save. This is the
  lost update: no amount of locking prevents it, because the race spans a
  caller's READ, its merge and its write, issued as three separate requests. An
  autosave sending tens of writes a minute for one record is the shape that
  loses them, and every request reports success while it happens.

  On `kgentities`: `create_entity_frames`, `update_entity_frames`. On
  `kgframes`: `create_kgframes`, `update_kgframes`,
  `create_kgframes_with_slots`, `update_kgframes_with_slots`,
  `create_frame_slots`, `update_frame_slots`, `create_child_frames`,
  `update_child_frames`.

  **What it compares depends on which route you use, because the two routes
  address different objects.** A frame inside an entity is versioned by its
  owning ENTITY — that is what those callers hold — and a top-level frame or a
  child of one is versioned by the FRAME, because it has no owning entity. Not
  a strong guard and a weak one: two different units of concurrency.

  `operation_mode=replace` deliberately does NOT accept it on either route. It
  deletes the existing frames before writing, so a refusal would land after the
  deletes and leave neither the old frames nor the new ones.

- **`VitalGraphResponse.is_conflict`**, and `status="conflict"` as a new
  `OperationStatus`. A refusal arrives as **HTTP 200** with that status, per this
  project's convention of putting domain outcomes in the body — so nothing about
  the status code reveals it and a caller reading only the code sees a success.
  `is_conflict` is what distinguishes it from `is_error`, and the two want
  OPPOSITE responses: a conflict means re-read, re-merge and send again, while a
  `store_failed` means retrying will not change the outcome. Treating a conflict
  as the latter turns a lost update into a dropped one.

  Do NOT replay a conflict with the same `if_unmodified_since`: the point is
  that the value is stale, so the replay is refused identically.

- **`modification_stamp`, for reading the value you have to send.** On
  `EntityGraphResponse` and `EntityGraph`, on `FrameGraphResponse` and
  `FrameGraph`, as `modification_stamp_for(uri)` on any flat
  `GraphObjectResponse`, and as `modification_stamps` (URI → stamp) on
  `MultiEntityGraphResponse`.

  **Use these rather than the object's attribute.** The obvious call —
  `str(entity.objectModificationDateTime)` — produces a value the server can
  never match: VitalSigns parses the literal into a `datetime`, so `str()`
  renders it space-separated (`2026-10-01 12:23:37.333100+00:00`) while the
  stored text keeps the ISO `T`. The comparison is on the stored string
  deliberately — a datetime comparison would forgive a formatting difference,
  and a formatting difference means something rewrote the value — so the space
  form is refused every time, and a caller using it would re-read, get the same
  unusable value and loop with nothing it could fix. The accessors return the
  wire form, which round-trips.

  The entity-versus-graph distinction matters: an entity graph holds the entity,
  its frames, its slots and their edges, and every one of them carries its own
  stamp. The accessors pick the subject the guard keys on, not the first stamp
  in the list.

  **Frames did not carry this property before 0.0.43.** A frame written by an
  older release has no stamp until it is next written; reading one returns
  `None`, and a caller then writes unconditionally, which is the previous
  behaviour. Nothing needs backfilling.

- **`idempotent=True` on the 12 replay-safe writes**, so the retry policy may
  replay them after a post-send failure — `httpx.ReadTimeout` being the case
  that mattered. A POST is not idempotent by method, so these were never
  retried, which is how timed-out frame writes became UNCERTAIN WRITES nobody
  could resolve. Claimable now because every server-minted edge URI is derived
  from its endpoints rather than `uuid4()`, and the subject-level write deletes
  what it is about to write.

  `create_kgentities` is deliberately NOT marked: a replay is safe for the DATA
  but answers `already_exists`, a reported failure for a write that succeeded.

### Changed — client

- **The server's `status` survives a failure response.** Six short-circuits
  built their response without it — the "nothing was updated" path and five
  `success is False` paths — so a refused write arrived as `status=None` and
  `is_conflict` False, which is exactly the response that needed to say
  otherwise. The count is identical for a refusal and a failure; only the status
  separates them.

- **`create_entity_frames` and `update_entity_frames` return the SERVER's
  message** rather than composing `"Created 0 frames"` over it. That message is
  the only place a refusal's reason survives, since `raise_for_error` falls back
  to it.

### Fixed — client

- **`updated_uris: null` no longer raises `'NoneType' object is not
  subscriptable`.** Four methods read
  `response_data.get('updated_uris', [None])[0]`, and `get(k, default)` does not
  apply the default when the key is PRESENT AND NULL — which the server sends
  when it has none. The result was reported as a client-side error with the
  server's actual answer discarded. **Latent before this release** for any
  response whose `updated_uri` is falsy; a refused conditional write is simply
  the first response shaped that way. If you have been seeing that error, you
  will now get the real response.

### Added — server

- **The write-side half of all of the above**: `if_unmodified_since` on
  `POST /api/graphs/kgentities/kgframes`, `POST /api/graphs/kgframes` and
  `POST /api/graphs/kgframes/kgslots`, compared inside the write transaction and
  under the entity or frame lock — anywhere else is a race of its own. Sending
  one precondition for a write covering several frames is `INVALID_REQUEST`, not
  `CONFLICT`: a precondition names one version of one thing, and narrowing it
  silently to one frame would report success while leaving the rest unguarded.

- **A write is now bounded as a whole** (`VITALGRAPH_WRITE_DEADLINE_S`, default
  25 s). `statement_timeout` bounds each statement, `lock_timeout` each lock
  wait, and `idle_in_transaction_session_timeout` bounds idleness by destroying
  the connection — nothing bounded the write itself, so a write that parked
  between statements ended as a loss the caller could not see.

### Fixed — server

- **A write no longer waits for an `ANALYZE`.** `add_rdf_quads_batch_bulk`
  awaited `maybe_analyze` inside the CALLER's transaction; against a 60 s
  `idle_in_transaction_session_timeout` and ANALYZEs running 60–98 s, the
  connection was terminated and the write lost. Scheduled on the internal pool
  instead, at all three sites.

- **A refused subject write is no longer reported as written.** Five sites
  discarded `update_subjects_graph`'s False return and answered with the URIs
  they INTENDED to write.

- **`frame_slot`'s pre-delete filter is indexable again** — a subquery arm
  compiled to a hashed SubPlan and forced a sequential scan. 384x locally
  (37–348 ms and 11,260 buffers → 0.045 ms and 215 buffers).

## 0.0.42 — 2026-09-24

21 commits since 0.0.41 (2026-09-22). THE CLIENT CHANGES in this release, which
0.0.41 did not: a paginated response can now say it is SHORT of what was asked
for, and the entity create call can be told to keep the timestamps it was given.
Both are additive — an older client against a newer server, or the reverse,
behaves exactly as before.

### Added — client

- **`incomplete` and `missing_uris` on paginated responses**, forwarded by the
  Python client and typed in the TypeScript one. `missing_uris` names what was
  requested and did not come back; `incomplete` says whether the shortfall was a
  FAILURE and therefore retryable — three-valued, where `None` means the route
  cannot say and is NOT the same as `False`, exactly as `has_more` already
  works. A caller reading `None` as "complete" reintroduces the defect these
  exist to expose.

  Both had to be added in two places to reach anyone:
  `extract_pagination_from_json_quads` WHITELISTS what it forwards, and the
  response models are pydantic with the default `extra='ignore'`, so a field the
  server grows is discarded twice over until each is told about it.

- **`preserve_object_properties` on `create_kgentities`** (and on
  `POST /api/graphs/kgentities`). Default `False`, which is what every existing
  caller wants — a client minting a NEW entity should not be choosing its
  creation date. Set it when COPYING entities between spaces: without it the
  server stamps `objectCreationTime = now` on every entity, so an archive copy
  dates the whole archive to the day it ran, and if the originals are then
  deleted the real dates exist nowhere. A property the request omits is stamped
  as before, so enabling it never leaves a timestamp unset. Omitted from the
  query string entirely when false, so requests to a server that predates it are
  byte-identical.

### Changed

- **A KGQuery that times out returns HTTP 200 with `status: query_failed`**
  instead of HTTP 500, matching the entity and type endpoints. A caller that
  relied on the client raising `VitalGraphClientError` for a timeout now
  receives a response with `success: False` and must check it. A server-level
  fault — an unreachable query engine, a lost connection — is still HTTP 500.

### Added

- **`type_agreement`**, a global admin table holding whether `rdf:type` can be
  answered from the derived frame/edge type columns, decided by the maintenance
  job instead of per query. The question costs about two minutes on a large
  space and the query path could only spare 250 ms, so it was never answered
  and the optimisation it guards — measured at 6.8x of one reference query's
  cost for edges, 1.5x for frames — never fired. A stored verdict is used only
  while a cheap catalog token says its source table has not changed, so a
  verdict that stops describing the data declines rather than misleads. Created
  by the existing admin-table migration (`scripts/migrate_slot_sort_blocks.py`),
  which also grants it to the application role; a database without it keeps the
  previous behaviour exactly.

  **The refresh gates itself**, which it has to: the verdict carries a change
  token taken before its own scan, so on a space written to during that scan it
  is stale before it can be stored. Ungated on a production database that cost
  462 seconds of scanning per hour, of which roughly 420 s bought nothing — the
  row was born unusable, every reader declined it, and the gate rescheduled the
  same scan. A space that proves this is now recorded with a NULL verdict and
  left alone for an hour; one whose verdict still matches its token is skipped
  for a catalog read. The backoff expires, so a space that goes quiet recovers
  without intervention. Making it work on a continuously written space needs
  the invariant maintained at write time rather than inferred by a scan that
  cannot outrun the writes.

### Fixed

- **A saturated connection pool made an entity-graph read return FEWER entities
  with HTTP 200 and no error** (`issues/229`). Four layers each turned a failure
  into an absence: `execute_sparql_query` reports failure in its return value,
  the batched retriever read `bindings` and ignored `success` — the same defect
  `issues/215` fixed in the other reader — so a killed query became an empty
  page; `{}` rather than `None` meant the per-entity fallback never ran; and two
  bare `if objs:` loops dropped the rest without a word. Measured: a 500-entity
  bulk copy reported complete success and 387 arrived, with 113 `pool acquire
  timed out` failures matching the 113 missing exactly. The retriever now
  raises, the skips are recorded, and the response says so. Whether a
  30-connection pool is simply too small for this route is not settled.

- **FTS rows now go with a bulk entity-graph delete** (`issues/217`, bulk path).
  They are keyed on the SUBJECT — an entity's frames and slots — while the
  delete endpoint hands auto-sync the ENTITY uris, which carry no FTS row, so
  every slot row outlived its data and still matched searches. Deleting 1,387
  entities left a space at 0 quads and 5,409 orphaned rows, repairable only by
  dropping the index. Cleanup now runs in the same transaction as the quad
  delete, across every index in the space. The vector, geo and fuzzy
  equivalents remain open.

- **A `type_agreement` probe no longer aborts its caller's transaction.** The
  probe treats a missing table as "not migrated", which is supported — but a
  failed statement aborts the transaction block server-side and catching the
  exception does not undo that. Harmless while every query ran on its own
  autocommit connection; once `execute_sparql_query` accepted a CALLER'S
  connection the swallowed error poisoned everything after it, including the
  caller's own read, which came back empty and read as an answer. Now inside a
  savepoint.

- **A batched entity-graph read stops fetching a predicate it discards.**
  `URIProp` restates the subject URI and the deserialiser drops it unread, so
  every one of those rows was read from disk, term-resolved and transferred for
  nothing. Measured on a 49.7M-quad space, one 25-entity page with graphs:
  14,407 rows and 83,516 buffers becomes 12,356 and 75,308. Responses are
  unchanged — the quads are regenerated from the objects. `rdf:type` is
  deliberately left alone: it is redundant with `vitaltype`, but an object
  carrying only `rdf:type` would lose its type and be dropped from the response.
- **An entity listing that asks for entity graphs no longer gives up its fast
  path.** `include_entity_graph=true` took the page of URIs from SPARQL instead
  of `entity_prop_sort`, even though that path needs exactly the ordered page of
  URIs the fast path returns and hydrates the graphs itself. Measured on a
  25-entity page of one type sorted by creation time: the query looped once per
  entity of that type in the space — 84,941 times — resolving two term rows
  each, to return 25 rows. 27,935 ms and 1,430,060 buffers, against 71 ms for
  the same page through the fast path. Declining still falls back to the old
  query, so searched listings are unaffected.
- **A filtered entity count reads one property lane, not all of them.** The
  count matched every property row of every qualifying entity — five or six
  lanes each — and de-duplicated afterwards, while the page it accompanies read
  only the lane it sorts on. Pinning it to the lane the filter already
  restricts to is equivalent, because that subquery guarantees the row and the
  table's primary key makes it unique: measured, 81,135 rows and 83,800 buffers
  against 16,227 and 16,441, same answer both ways.
- **SQL generation stops re-buying a type-agreement verdict it cannot reach.**
  Whether `rdf:type` agrees with the derived type column is checked under a
  250 ms budget and cached against the table's row count. On a large space the
  check needs *two minutes*, so it always timed out — and because the row count
  of a space taking writes changes constantly, the same failure was recomputed
  for almost every query, behind a `count(*)` over millions of rows that cost
  ~236 ms by itself — 11.4 hours of cumulative database time across all spaces,
  and 111 seconds of generation time in a 43-minute window. (It was cheap on a
  typical query — 1.8 ms median — and occasionally very expensive, up to
  1.9 s.) An unreachable verdict is now remembered for 15 minutes, skipping
  both the check and the count. Unknown means "do not absorb", so this can only
  cost an optimisation, never change a result.
- **One KGQuery measures its full-text leaf once, not twice.** The page and the
  count generate SQL separately and each ran the same bounded count (201 ms
  mean, 3,676 ms max). They generate *concurrently*, so a completed-result cache
  never hit; an in-flight measurement is now awaited rather than duplicated, and
  a completed one is reused for 5 seconds. This halves the database work for
  such a query but does **not** shorten it — the two overlap, so the request
  waits for the slower rather than for the sum. The *inlined id set* is
  deliberately not cached — it is the answer rather than an estimate, and
  reusing a stale one would drop rows indexed in between.
- **A filtered or sorted FTS frame query is served from the derived tables at
  any match-set size.** It used to fall back to the general pipeline whenever
  the match set was small enough for that pipeline to inline, on a measurement
  taken against an unpopulated test space. On a real space the fallback is
  slower at every size measured: for a 72-match term — the size a type-ahead
  search produces — 285 ms against 44 ms, and for a 4,600-match term 18.0 s
  against 0.3 s. Plain (unfiltered, unsorted) searches are unchanged.
- **An unsorted FTS frame page is one row per frame, not per matching slot.**
  It was built without `DISTINCT` and de-duplicated afterwards, so a frame
  matching in two slots would have spent two of the page's rows and returned a
  short page with every later offset shifted. No such frame exists in any
  corpus checked, so no caller saw a wrong page; this closes the hole rather
  than repairing damage. The sorted, entity and fast paths were already
  `DISTINCT`.
- **An FTS criterion the space cannot answer is reported, not answered.** A
  nonexistent index returned HTTP 500 with the raw SQL error; a target slot type
  with no enabled search mapping returned a confident empty page,
  indistinguishable from no matches. Both now return HTTP 200 with
  `status: invalid_request` and a message naming the missing index or the
  uncovered slot types.

## 0.0.41 — 2026-09-22

243 commits since 0.0.40 (2026-09-08). Full-text search becomes an ordinary
KGQuery criterion; `frame_slot` replaces `frame_entity`; and a run of
correctness fixes in the derived-table fast paths, several of which returned
wrong answers rather than slow ones.

### Breaking

- **Entity and `frame_query` KGQueries now honour `include_total_count`, which
  defaults to `NO`.** In 0.0.40 those two paths ran the count unconditionally
  and ignored the field; only the connection-style frame path honoured it. Once
  a server is upgraded, a caller that reads `total_count` without setting
  `include_total_count` receives **0**. Pass `TotalCountMode.YES` (bounded at
  the server cap, with `total_count_capped` set when truncated) or
  `TotalCountMode.EXACT` (full count, full cost).
- **A failed read is reported as a failure.** It returns `success: False` with
  the new status `query_failed`, where it used to return a successful empty
  result indistinguishable from a genuinely empty space. `query_failed` is a
  new `OperationStatus` value, so a 0.0.40 client that receives it fails to
  deserialize the response: **upgrade clients before servers.**
- **`{space}_frame_entity` is dropped and replaced by `{space}_frame_slot`**
  (server). One row per slot with its role as data, rather than two role URIs
  baked into column names. Requires migration before the server upgrade; see
  Upgrading.

### Added

- **Full-text search as KGQuery criteria.** `KGQueryCriteria.fts_criteria =
  FTSCriteria(text, index_name, targets=[FTSTarget(slot_type, frame_type,
  kind)], include_match_text)` composes with entity type, owner-entity property
  filters and ordinary sort criteria, through the existing
  `POST /api/graphs/kgqueries`. Boolean only — no score, threshold or relevance
  order. Several targets form one page. Results carry `FTSMatch` on
  `FrameQueryResult.fts_matches`, or `entity_fts_matches` for entity queries.
  Query text is parsed with `websearch_to_tsquery`: quoted phrases, `or`, and
  `-exclusion`. The client refuses a response whose server did not acknowledge
  the criterion (`fts_applied`), so an older server cannot return an unfiltered
  page.
- **KGQuery projections:** `slot_projection` (served from `entity_slot_sort`)
  and `property_projection` (direct entity properties).
- Export writes literal datatypes (`^^<datatype>`) in every format; import reads
  gzip-compressed files and N-Quads.
- Maintenance detects edges whose endpoint no longer exists and objects nothing
  points at.
- Per-index `rank_normalization` for scored `vg:textSearch` (server, migration
  below).

### Fixed

- **Export dropped every literal datatype** — dates and numbers round-tripped
  as strings, silently disabling date and numeric filters and sorts on any
  space restored from an export. Spaces restored from an older export must be
  re-exported and re-imported, then have their derived tables rebuilt with
  `resync_all_auxiliary_tables`.
- **A negated frame criterion was served as its complement** by the slot-filter
  fast path, returning exactly the entities the caller asked to exclude.
- **An entity matching a criterion through two frames was counted and returned
  twice**, inflating `total_count` and shifting pagination.
- Dated and float-valued slot criteria could never bind against a typed column,
  and date bounds on `entity_prop_sort` were never served; both fell back to
  the slow path. Offset-bearing date bounds now compare in UTC.
- `update_entity_frames` silently discarded a non-frame object in its payload
  (for example a `KGEntity`) and still reported `updated`; the discard is now
  named in the response. Frame updates deliberately do not write the entity
  node.
- Full-text search: selective searches with date filters or sorts no longer
  walk every owner entity (seconds to milliseconds); FTS auto-sync respects the
  index mapping instead of indexing every literal; the `search text` CLI reads
  the FTS table and no longer raises on punctuation.
- Bulk import rebuilds `entity_slot_sort` in bounded batches instead of one
  unbounded statement that could exhaust server memory.
- SPARQL: `MINUS` correlation, path alternation as a multiset union, stacked
  `OPTIONAL` planning, and an untranslatable operator now refused rather than
  answering nothing.
- A fast-served entity page dropped `include_entity_graph`;
  `include_frame_graph` on KGQueries now says that it is not implemented.

### Deprecated

- `AdminResyncResponse.frame_entity_rows` — use `frame_slot_rows`. The old field
  stays populated with the same value.

### Removed

- Nothing a 0.0.40 client could call. The standalone `search_messages` method
  and its response models existed only between releases and never shipped; use
  `fts_criteria`.

### Upgrading

In this order:

1. **Migrations**, against each deployment's database:
   `scripts/migrate_frame_slot_table.py` then
   `scripts/migrate_drop_frame_entity.py` (and
   `scripts/migrate_drop_retired_tables.py` for any remaining retired tables);
   `scripts/migrate_shorten_index_names.py`;
   `python -m vitalgraph.db.migrations.migrate_fts_rank_normalization`.
2. **Clients to 0.0.41**, because of the new `query_failed` status.
3. **Servers.** Then audit callers that read `total_count` and set
   `include_total_count` where they need it.

Before enabling FTS on a space, create and populate its index with a mapping
for every slot type a query will target. An FTS target whose slot type the
mapping does not cover currently returns an empty page rather than an error.

## 0.0.40 — 2026-09-08

608 commits since 0.0.39 (2026-08-12). The theme is derived tables: sorting
and filtering entities and frames from purpose-built indexes instead of
walking quads, and the correctness work that had to come with them.

### Breaking

- **`vitalgraph.agent_registry.agent_models` is now `vitalgraph.model.agent_model`.**
  No re-export shim at the old path. Every model the Python client imports now
  lives in the model package; these 32 request/response contracts were the last
  set reached for outside it. Update imports to
  `from vitalgraph.model.agent_model import ...`.

### Added

- `entity_prop_sort` and `frame_prop_sort` — sorted, filterable indexes of
  direct entity and frame properties, with a block-list read gate and recorded
  coverage. Sorted and filtered listings are served from them, including
  top-level (Assertion) frames, without narrowing the set first.
- Entity listings can filter by property and sort without a prior search.
- Single-valued predicate enforcement: a migration, the survey that motivated
  it, and repair for duplicated slot values and server-stamped timestamps.
- WHERE-bound SPARQL updates serialise against concurrent entity and frame
  writes via an `UpdateLockPlan`.
- The write and query paths accept a caller's connection throughout.
- `FROM` and `FROM NAMED` are honoured rather than parsed and discarded;
  relative IRIs resolve against a request base; the default graph is no longer
  also a named graph.
- Equality slot-value entity queries are served from `entity_slot_sort`.
- A concurrent load test with graph-scoped cleanup.

### Fixed

- The `issues/174` grouping-lock degradation could not degrade: a server-side
  `lock_timeout` aborts the transaction, so "proceeding UNSERIALISED" logged
  reassurance and then failed on `InFailedSQLTransactionError`. Now wrapped in
  a savepoint. See `issues/177`.
- **A write no longer depends on the prop-sort tables existing.** Writes to a
  space that predates them failed outright with a 500. These tables are created
  by an explicit migration, so "not migrated yet" is a normal state — and the
  state every space is in between a deploy and its migration. Writes now
  degrade as reads already did.
- Property sorts use their indexes in both directions; a descending sort no
  longer falls back to a full sort.
- Silent declines in the prop-sort count path now log, so a count that declines
  while the page serves is visible rather than inferred.
- Graph enumeration uses a loose index scan instead of a full quad scan.
- Derived tables are read rather than re-derived from quads on every request.

### Changed

- Benchmark baselines re-promoted from ANALYZEd, representative runs, split by
  whether a benchmark builds data or reads resident data, with one baseline per
  tier.

### Client

- **TypeScript**: the four child-frame methods called
  `/api/graphs/kgframes/kgframes`, a route the server does not expose — every
  call was a 404. They now use the `parent_frame_uri` form of
  `/kgentities/kgframes`. Adds `id_list`, `delete_entity_graph` and `recursive`,
  without which a caller could not delete an entity's graph or a frame subtree.
- **Python**: no changes needed; it was already in sync with the server routes.

## 0.0.39 and earlier

Not tracked in this file. See `git log` and `issues/`.
