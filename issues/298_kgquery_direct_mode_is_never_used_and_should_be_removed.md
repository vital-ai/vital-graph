# 298 — KGQuery direct mode is never used and should be removed

## Status: OPEN, filed 2026-10-22 for a future cleanup. No performance effect: removal is for clarity and a smaller API surface, not speed.

**Related:** `issues/293` (found while building a KGQuery corpus for its
stage 6), the frame/slot traversal tables (`{space}_edge`, the `frame_slot`
collapse, `issues/048`, `183`).

## What it is

KGQuery has two ways to reach an entity's frames and slots:

- **edge mode** (`query_mode="edge"`, the default; `use_edge_pattern=True` in
  `kg_query_builder`): the `Edge_hasEntityKGFrame` / `Edge_hasKGSlot` edge
  objects, served by the edge table and the `frame_slot` collapse;
- **direct mode** (`query_mode="direct"`; `use_edge_pattern=False`): the
  materialized shortcut predicates `vg-direct:hasEntityFrame`,
  `vg-direct:hasFrame`, `vg-direct:hasSlot`.

Direct mode existed to skip graph traversals. The traversal tables now give
the generator that shortcut directly, so the materialized predicates are not
needed.

## Why remove it

- **It is never used** (confirmed 2026-10-22).
- **It cannot work.** No space has the `vg-direct:` predicates: not the vg test
  stack, not the dev database, not production (its main 75M-quad KG space has
  none). Nothing in the current code writes them. A direct-mode query compiles
  to a join on a term that does not exist and returns nothing, silently. On
  `sp_lead_synth_100k` every direct-mode count returned 0 and every page 0 rows.
- **It misleads.** The KGQuery builder declares `PREFIX vg-direct:` in every
  query, and entity-graph fetches carry
  `FILTER(?p != vg-direct:hasEntityFrame && …)`. Both were counted as
  direct-mode use when classifying production's slow-query log, a wrong
  conclusion that had to be retracted.

## No performance effect

The exclusion FILTER in entity-graph fetches costs nothing: its three terms do
not exist in any space, so the generator emits no predicate filter at all.
Measured on `uw_prodshape` (one 3,076-quad decision graph, 5 interleaved
runs): 23.7 ms median with the FILTER, 22.8 ms without, identical rows, the
same SQL apart from the FILTER's constants. Production's entity-graph fetches
(1.2 s median) are I/O on cold pages, not this FILTER.

## Scope of the removal

- **API:** `query_mode` on `KGQueryCriteria` (`vitalgraph/model/kgqueries_model.py`)
  and its handling in `vitalgraph/endpoint/kgquery_endpoint.py`; the client's
  `vitalgraph/client/endpoint/kgqueries_endpoint.py`. Removing the field is
  an API change: decide whether to reject `"direct"` with a clear error for a
  release first, or drop it.
- **Query builder:** the `use_edge_pattern=False` branches and the
  `vg-direct:` clauses in `vitalgraph/sparql/kg_query_builder.py` (~lines 981,
  996, 1474-1522 and the frame-path builder near 1828), and the
  `PREFIX vg-direct:` declaration.
- **Materialized-predicate filtering:** `_MATERIALIZED_PREDICATES` and
  `_materialized_filter` in `vitalgraph/db/sparql_sql/sparql_sql_db_objects.py`;
  `MaterializedEdgePredicates` / `include_materialized_edges` in
  `vitalgraph/kg_impl/kg_graph_retrieval_utils.py`; the FILTERs in
  `kg_validation_utils.py`, `kg_sparql_query.py`, `kg_backend_utils.py`,
  `kgentity_list_impl.py`, `kgdocuments_read_impl.py`,
  `kgrelations_read_impl.py`, `kgtypes_read_impl.py`, `kgframes_endpoint.py`.
- **Tests that set `use_edge_pattern` / `query_mode`** (about 17 files across
  `tests/unit`, `tests/integration`, `tests/performance`, `tests/load`): keep
  the edge-mode cases, drop the direct-mode ones.
- `vitalgraph-client-ts` and the frontend: check for `query_mode` or
  `vg-direct`.

## Verify

Edge-mode results unchanged (the KGQuery integration and API suites, the
perf-suite KGQuery benches), and no `vg-direct` string left outside this
issue and the changelog.
