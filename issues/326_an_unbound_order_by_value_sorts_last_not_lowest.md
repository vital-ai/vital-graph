# 326 — An unbound ORDER BY value sorts last, not lowest; the KG list sort relies on it

## Status: OPEN 2026-10-27. Tracking; implementing.

## The two things

1. **The engine.** SPARQL 15.1 orders an unbound value LOWEST: first ascending, last descending.
   Both paths sort it last ascending and first descending, PostgreSQL's NULL placement
   (`emit_order.variable_order_keys`, the qtree planner's sort keys). Split out of issues/324,
   where it was left open as a product decision.
2. **The KG list sort helper relies on the engine, and breaks its own contract.**
   `kg_sparql_utils.KGSparqlUtils.build_sort_bindings` documents "subjects WITHOUT [the sort
   property] sort last — in BOTH directions". For sequence properties it says so explicitly
   (a leading `IF(BOUND(?v), 0, 1)` key). For every other property it emits
   `OPTIONAL { ?anchor <prop> ?val } … ORDER BY ?val ?anchor` and leaves it to the engine, so a
   DESCENDING sort puts the subjects missing the property FIRST. The SQL fast paths
   (`fast_prop_sort`, `fast_frame_prop_sort`) sort `NULLS LAST` in both directions, so the same
   listing changes order with the path that serves it.

## What depends on it (audit 2026-10-27)

| | depends on the engine's placement? |
|---|---|
| KG list sort, sequence properties (frame / slot sequence) | no: the explicit `?missing` key |
| KG list sort, any other property | **yes** (item 2) |
| SQL fast paths (entity / frame prop sort) | no: explicit `NULLS LAST` |
| KGQuery sorts (`kg_query_builder._build_sort_bindings`) | no: the sort triples are required |
| The frontend | no: its own client-side fallback |
| `tests/integration/test_sequence_ordering.py` `TestCoalesceInOrderBy` | **yes**: pins today's placement |
| `tests/integration/test_order_by_follows_sparql_ordering.py` (issues/324) | **yes**: pins today's placement |
| Raw SPARQL from outside this repository (the portal through the Resource API) | unknown: cannot be audited from here; its ORDER BY over an OPTIONAL variable will see the change |

## Plan

- [ ] `build_sort_bindings`: the leading `?missing` key for every sort property, so missing sorts
      last in both directions whatever the engine does, as the fast paths do.
- [ ] The engine: unbound lowest, in plain columns (the value, date and text keys `NULLS FIRST`
      ascending, `NULLS LAST` descending). An expression key cost 10-59% on every ordered query
      (issues/324); this must not.
- [ ] The qtree planner's keys likewise.
- [ ] Tests: `TestCoalesceInOrderBy` and the 324 tests to SPARQL's placement; a test of the KG
      list sort missing-last both ways.
- [ ] Timing: the default path's ordered queries before / after, as for 324.
- [ ] The vg test stack's full suite.

A side effect of the plain-column form: a variable mixing numbers and strings orders the strings
first ascending (today numbers first); SPARQL leaves the relative order of such literals
undefined.
