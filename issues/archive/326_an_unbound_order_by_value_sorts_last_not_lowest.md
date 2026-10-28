# 326 — An unbound ORDER BY value sorts last, not lowest; the KG list sort relies on it

## Status: RESOLVED 2026-10-28. Verified on the vg test stack rebuilt at 3d99208c: unit, DAWG conformance, integration and API suites, 0 failures.

## The two things

1. **The engine.** SPARQL 15.1 orders an unbound value LOWEST: first ascending, last descending.
   Both paths sort it last ascending and first descending, PostgreSQL's NULL placement
   (`emit_order.variable_order_keys`, the qtree planner's sort keys). Split out of issues/324,
   where it was left open as a product decision.
2. **The KG list sort helper relies on the engine, and breaks its own contract.**
   `kg_sparql_utils.KGSparqlUtils.build_sort_clauses` documents "subjects WITHOUT [the sort
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

- [x] `build_sort_clauses`: the leading `?missing` key for every sort property, so missing sorts
      last in both directions whatever the engine does, as the fast paths do.
- [x] The engine (`emit_order.variable_order_parts` / `variable_order_keys`): unbound lowest, in
      plain columns (the value, date and text keys `NULLS FIRST` ascending, `NULLS LAST`
      descending). An expression key cost 10-59% on every ordered query (issues/324); this does not.
- [x] The qtree planner's keys likewise (it uses `variable_order_parts`).
- [x] Tests: `TestCoalesceInOrderBy` and the 324 tests to SPARQL's placement;
      `tests/integration/test_kg_sort_puts_missing_last.py` (missing last both ways, the page built
      as the frames listing builds it). `test_bind_workaround_sorts_missing_last` joins its COALESCE
      siblings as a strict xfail: its sentinel rows have no numeric value (the known COALESCE
      defect), and only PostgreSQL's NULL placement had put them last.
- [x] Timing: the 27 ordered queries (lead10k portal, ordered corpus shapes), the generator before
      324 against now, 7 runs each: 0.95x-1.06x (u08 1.04x over 15 runs). No regression.
- [x] The vg test stack's full suite.

The differential sweep against Oxigraph now agrees on every unbound placement; its remaining
mismatches are the two left by issues/324 (equal numbers by text) and MIN / MAX over unbound values.

A side effect of the plain-column form: a variable mixing numbers and strings orders the strings
first ascending (today numbers first); SPARQL leaves the relative order of such literals
undefined.
