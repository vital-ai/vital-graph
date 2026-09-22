# Changelog

Notable changes per release. Dates are the release date, not the first commit.

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
