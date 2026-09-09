# Changelog

Notable changes per release. Dates are the release date, not the first commit.

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
