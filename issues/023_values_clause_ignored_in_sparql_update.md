# Unhandled WHERE elements in a SPARQL UPDATE are silently dropped — DELETE wipes the whole graph

*(originally filed as "`VALUES` in a SPARQL UPDATE's WHERE is ignored"; root-caused
and rescoped 2026-08-03 — `VALUES` is one instance of a general fail-open defect)*

## Status: FIXED (2026-08-04) — defect *and* coverage gap both closed

- **The reported defect** is fixed and regression-tested (2026-08-03). A
  `VALUES`-constrained DELETE no longer wipes the graph. See "Fix as applied".
- **The coverage gap** that let it hide is closed (2026-08-04). See "Coverage
  gap — closed" below. Conformance went from 350 tests to 604, and for the
  first time any of them execute the SQL pipeline at all.

The gap was never incidental to this bug — it is why a whole-graph delete
shipped and was caught only by one test that happened to assert a bystander
survived. Both halves had to be done.

See also `issues/028_expression_emitters_fail_open_on_unresolved_vars.md`
(FIXED 2026-08-04) — the fail-closed principle adopted here covered only the
syntax-element mapper; 028 extended it to the expression emitter, which now
raises on a variable that was in scope and still could not be resolved. The
conformance corpus built here is what let 028 measure its blast radius first.

And `issues/029_aggregates_over_mixed_typed_literals.md` (FIXED 2026-08-04) —
four pre-existing aggregate bugs that surfaced the moment conformance began
executing SQL.

## Issues that descend from this one

Four issues cite this one and it cited none of them, which understated how much
followed from it:

- `issues/026_minus_ignored_when_shared_var_has_no_term_uuid.md` and
  `issues/027_exists_loses_correlation_for_filter_only_outer_vars.md` — the same
  failure shape (a silently dropped constraint widening a DELETE) at two other
  layers. Both found while writing this issue's regression tests.
- `issues/028_expression_emitters_fail_open_on_unresolved_vars.md` — the shared
  fail-open beneath all three. Its measurement needed the conformance corpus
  this issue built.
- `issues/025_construct_describe_unimplemented.md` — unblocked by the same
  work: `test_dawg_sql_v2` only began executing SQL here, so before that there
  was no way to validate a CONSTRUCT implementation. 025 added the `construct`
  category to the file this issue fixed.
- `issues/029_aggregates_over_mixed_typed_literals.md` — four pre-existing
  aggregate bugs, surfaced the moment that suite started executing.

## Severity

**Data loss.** A `DELETE` intended to remove a handful of named subjects
removes *every triple in the graph*, silently and with a success response.

## Summary

On the SQL backend, a `VALUES` clause inside the WHERE of a SPARQL **update**
is dropped. The remaining pattern `?s ?p ?o` is then unconstrained, so the
delete matches everything.

`VALUES` in a **SELECT** works correctly. Only the update path is affected,
which is what makes this dangerous: the clause reads as correct, tests against
a SELECT confirm the semantics, and the update quietly means something else
entirely.

**`VALUES` is not the only affected construct.** See "Root cause" — the defect
is a fall-through in the syntax-Element mapper, and at least five element types
hit it.

## Reproduction

Verified against the test stack (`docker-compose.test.yml`, app on :8002).
Seed a graph with 4 KGDocuments, then:

```sparql
DELETE { GRAPH <g> { ?s ?p ?o . } }
WHERE  { GRAPH <g> { VALUES ?s { <urn:probe:doc0> } ?s ?p ?o . } }
```

Expected 3 documents remaining. **Actual: 0.**

The same `VALUES` constraint in a SELECT returns only `urn:probe:doc0`, as it
should:

```sparql
SELECT ?s WHERE { GRAPH <g> { VALUES ?s { <urn:probe:doc0> } ?s ?p ?o . } }
-- → {urn:probe:doc0}   (correct)
```

## Shapes that behave correctly

Probed on the same stack, same seed data:

| Shape | Result |
|---|---|
| `VALUES` in SELECT | correct |
| `DELETE { <uri> ?p ?o } WHERE { <uri> ?p ?o }` (bound subject) | correct |
| Multiple bound-subject DELETEs joined with `;` | correct |
| `DELETE { ?s ?p ?o } WHERE { ?s ?p ?o . FILTER(?s IN (<uri>)) }` | correct |
| **`DELETE { ?s ?p ?o } WHERE { VALUES ?s {...} ?s ?p ?o }`** | **deletes everything** |

---

## Root cause

Not a translation-layer drop. `VALUES` is **never parsed** for updates, because
queries and updates take different paths out of the Jena sidecar:

- **SELECT** → compiled algebra → `map_op()`, which has an `OpTable` handler
  (`vitalgraph/db/jena_sparql/jena_ast_mapper.py:401`). Works correctly.
- **UPDATE WHERE** → *syntax* Elements → `map_element_to_op()`
  (`jena_ast_mapper.py:785`), because `UpdateModify.wherePattern` is serialized
  at syntax level, not algebra level (`jena_ast_mapper.py:661`).

The sidecar serializes Jena's `ElementData` (VALUES) under the type name
**`"ElementValues"`** (`vitalgraph-jena-sidecar/.../serializer/ElementSerializer.java:95`).
`map_element_to_op` has no case for it, so it reaches the fall-through:

```python
logger.warning("Unknown element type: %s — returning empty BGP", etype)
return OpBGP(triples=[])
```
`jena_ast_mapper.py:963`

Inside an `ElementGroup` that becomes `OpJoin(empty_BGP, real_BGP)`. An empty
BGP collects to a plan with no tables and no var_slots
(`vitalgraph/db/sparql_sql/collect.py:107`) — a unit table, i.e. **join
identity**. So the constraint does not fail closed or match zero rows; it
evaporates, leaving `?s ?p ?o` unconstrained. Whole graph deleted, success
returned.

### Blast radius: every element type the mapper doesn't handle

`map_element_to_op` handles `ElementPathBlock`, `ElementGroup`, `ElementFilter`,
`ElementBind`, `ElementOptional`, `ElementUnion`, `ElementNamedGraph`,
`ElementSubQuery`. The sidecar can emit these too, and each silently widens an
update the same way:

| Element emitted by sidecar | Handled? | Consequence in an update WHERE |
|---|---|---|
| `ElementValues` (VALUES) | **no** | the reported bug |
| `ElementTriplesBlock` | **no** | **entire WHERE body vanishes** |
| `ElementMinus` | **no** | MINUS exclusion dropped → delete widens |
| `ElementNotExists` / `ElementExists` | **no** | guard dropped → delete widens |
| `ElementService` | **no** | remote pattern dropped → delete widens |

`ElementTriplesBlock` is the most alarming: Jena normally emits
`ElementPathBlock`, but any shape that yields a plain triples block loses its
whole WHERE and deletes the graph.

### Second, independent fail-open

`_delete_from_bindings` (`vitalgraph/db/sparql_sql/emit_update.py:754-812`)
drops the condition entirely when a delete-template variable is not bound by
the WHERE:

```python
if _var_is_bound(dq.subject.name):
    conditions.append(...)
# else: unbound variable → omit condition (wildcard match)
```

Even with the mapper fixed, any future path that drops a variable from
`var_map` turns a delete-template position into a wildcard. This is a distinct
layer from the parse bug and should be fixed independently.

---

## Why the test suite did not catch this

There *are* SPARQL tests covering `VALUES`, and there *are* SPARQL tests
covering updates. **They never intersect**, and every one of them passes.
Four separate layers of false confidence:

**1. The `VALUES` emitter unit test bypasses the broken code.**
`tests/unit/sparql_sql/test_emit_table.py` hand-constructs `PlanV2(kind=KIND_TABLE,
values_vars=..., values_rows=...)` and asserts on the emitted SQL. It never runs
the mapper or the collector. It passes, and would pass with the mapper deleted
entirely — the emitter is not the broken part.

**2. The `VALUES` plan-tree fixture is SELECT-only with a recorded response.**
`tests/fixtures/plan_trees/json/values_inline.json` (from
`sparql_corpus.py:113`) is a `SELECT ?s ?name WHERE { VALUES ?type {...} ... }`
with a **recorded** sidecar response — i.e. the algebra path with `OpTable`.
`map_element_to_op` is never invoked.

**3. The DAWG `bindings` category is 11 `VALUES` tests, all of them SELECT.**
Names include "Inline VALUES graph pattern", "VALUES inside GRAPH binding the
same variable as the graph name" — all `mf:QueryEvaluationTest`, zero updates.
It is in `QUERY_CATEGORIES` for the pyoxigraph runner but not in
`P0_CATEGORIES`, so `tests/conformance/test_dawg_sql_v2.py` does not even run it
against the SQL backend.

**4. The DAWG update suite is not wired into pytest — and has no VALUES test anyway.**
- A complete update runner exists (`vitalgraph_sparql_sql_dev/dawg_test_impl/dawg_update_test.py`,
  driven by `dawg_test_runner.py:494` over 11 `UPDATE_CATEGORIES`), but it lives
  outside `testpaths = ["tests"]` (`pyproject.toml:231`) and is never collected.
- `tests/conformance/test_dawg_sql_v2.py:119` filters to
  `tc.test_type == "QueryEvaluation"`, and `dawg_manifest_parser.py:77` has no
  `UpdateEvaluationTest` mapping at all — so the pytest conformance suite
  *cannot* express an update test. `delete-insert` alone has 9
  `mf:UpdateEvaluationTest` entries that are parsed and discarded.
- Even fully wired, it would still miss this: **no `.ru` file in the entire
  DAWG tree uses `VALUES`.** The SPARQL 1.1 update suite does not cover
  VALUES-in-update-WHERE.

`test_scripts/sparql/test_update_queries.py` (658 lines of update coverage)
contains no `VALUES` case and is also outside `testpaths`.

**Takeaway:** the gap is structural, not an oversight on one test. Update WHERE
patterns have no conformance coverage in pytest at all, and the constructs that
*are* covered are covered only on the query path — the path that works.

---

## Why it matters beyond the one caller

`VALUES` + unbound triple pattern is the *idiomatic* way to express "delete
these N subjects" in SPARQL. Any future caller reaching for it gets whole-graph
deletion. The failure is silent — the update returns success and the caller has
no signal short of counting rows afterwards.

Found while implementing
`issues/021_uri_prefix_string_matching_in_deletes.md`: the replacement
delete used exactly this shape and destroyed an unrelated document that the
regression test was asserting had survived. The test caught it; nothing else
would have.

## Current mitigation

`vitalgraph/document/segment_deletion.py` uses bound-subject DELETEs joined
with `;`, with a comment explaining why it must not be "simplified" back to a
`VALUES` form (see `segment_deletion.py:204`). That is a workaround at one call
site, not a fix.

## Suggested fix

The bug is in `vitalgraph/db/jena_sparql/jena_ast_mapper.py`, **not** in
`vitalgraph/db/sparql_sql/`. The SQL layer already has full `VALUES` support —
`OpTable` exists (`jena_types.py:284`) and `emit_table.py` emits it correctly.
This is a wiring gap, not a missing capability.

1. **Fail closed on the fall-through.** Make `map_element_to_op` *raise* on an
   unknown `etype` instead of returning `OpBGP(triples=[])`. This single change
   converts every current and future gap in the table above from silent data
   loss into a rejected update. A rejected update is recoverable; a whole-graph
   delete is not. Do this first — it is the fix that matters.
2. **Add the missing element handlers**: `ElementValues` → `OpTable`,
   `ElementMinus` → `OpMinus`, `ElementTriplesBlock` → `OpBGP`,
   `ElementNotExists` / `ElementExists`.
   - *Gotcha:* the two serializations disagree on row format. The algebra path
     (`_map_table`, `jena_ast_mapper.py:402`) expects `rows` as **dicts keyed by
     var name**; `ElementSerializer.java:100-108` emits ElementValues `rows` as
     **positional lists aligned to `vars`**, with `null` for UNDEF. The new
     handler must zip against `vars` — it cannot reuse `_map_table` directly.
3. **Fix the second fail-open** in `_delete_from_bindings`
   (`emit_update.py:754-812`): an unbound delete-template variable must raise,
   not become a wildcard.

---

## Fix as applied

### `vitalgraph/db/jena_sparql/jena_ast_mapper.py`

- **Fail closed.** The `map_element_to_op` fall-through now raises
  `UnsupportedSparqlElement` instead of returning `OpBGP(triples=[])`. This is
  the change that generalizes — it covers constructs nobody has enumerated yet.
  No plumbing was needed: `execute_sparql_update` already catches and returns
  `False` (`sparql_sql_space_impl.py:1619`), so an untranslatable update is
  rejected with the data intact.
- **Added handlers**: `ElementValues` → `OpTable` (zipping the sidecar's
  positional rows against `vars`), `ElementTriplesBlock` → `OpBGP` (folded into
  the existing `ElementPathBlock` branch), `ElementMinus` → `OpMinus`,
  `ElementExists` / `ElementNotExists` → `OpFilter(ExprExists)`.
- **Group assembly**: `OPTIONAL` / `MINUS` / `EXISTS` / `NOT EXISTS` carry only
  their right-hand side, so they now wrap the accumulated result instead of
  joining with it. Dispatch is on the raw element type rather than
  `isinstance` of the mapped op.
- `ElementService` deliberately has no handler — SERVICE has no SQL
  translation, so it now rejects rather than silently dropping the pattern.

### `vitalgraph/db/sparql_sql/emit_update.py`

- `_delete_from_bindings` raises `UnboundDeleteTemplateVar` for an unbound
  delete-template variable in any position (subject/predicate/object/graph)
  instead of omitting the condition. SPARQL 1.1 §3.1.3 says an unbound template
  variable yields no triple, so this costs nothing a correct query relied on.

### Bonus defect found by the new tests

`ElementOptional` read the nested element from key `"element"`, but the
serializer emits `"sub"` (`ElementSerializer.java:55`) — so **every `OPTIONAL`
in an update WHERE was also silently dropped to an empty BGP**, the same
fail-open by a different route. Now reads `"sub"` and wraps correctly. This was
pre-existing and unreported; `emit_update.py:579` shows OPTIONAL-bearing update
templates are actively used, so this was live.

## Verification

- `tests/unit/sparql_sql/test_update_where_mapping.py` (28 tests) and
  `tests/unit/sparql_sql/test_delete_template_binding.py` (14) — no DB or
  sidecar needed, so these run in CI.
- `tests/integration/test_update_where_constraints.py` (10) — end-to-end
  against PostgreSQL + sidecar.
- **The integration tests were confirmed to fail against the pre-fix code**:
  reverting both source files reproduced 6 failures, including the exact
  reported shape. They are genuine regression tests, not tests written to pass.
- Full suite after the fix: 1396 passed, 35 skipped, 6 xfailed
  (unit + fixtures + integration); conformance 350 passed, 21 skipped,
  23 xfailed. No regressions.

### Mitigation unwound

`vitalgraph/document/segment_deletion.py` now uses the `VALUES` form again —
one batched DELETE per 200 URIs instead of one bound-subject DELETE per URI.
The comment that warned against this shape has been replaced with a pointer to
this issue.

Verified against the rebuilt test stack (`docker-compose.test.yml`, app on
:8002), not just unit tests:
`tests/api/test_kgdocuments_api.py::TestSegmentDeleteScoping` — the suite whose
decoy-survival assertion originally exposed this bug — passes, along with the
rest of the document/segmentation API suites (28 tests).

Unit coverage was inverted rather than deleted: `test_segment_deletion.py` used
to assert `"VALUES" not in upd`; it now asserts the pairing invariant, that an
unbound `?s ?p ?o` is always accompanied by a `VALUES` list naming every
subject, and that no batch can emit an unconstrained delete.

### Not changed

- `MINUS { ... BIND(...) }` does not constrain correctly — but this reproduces
  on the **SELECT** path too, so it is a pre-existing `emit_minus` limitation
  with BIND-introduced shared variables, unrelated to this issue. Worth its own
  issue. Plain shared-variable MINUS works on both paths.

## Regression tests — added

All of the following are in place:

- Seed a graph with N subjects, issue a `VALUES`-constrained DELETE for one,
  assert N-1 remain. Also multi-subject `VALUES`, and a `VALUES` matching
  nothing (must be a no-op, not a wildcard).
- `FILTER(?s IN (...))` and bound-subject forms, so the correct shapes stay
  correct.
- `MINUS` and `NOT EXISTS` inside an update WHERE. The MINUS test asserts the
  same pattern on the *query* path first, so a failure is unambiguously
  update-specific.
- **Translation-level:** `map_element_to_op` raises on an unknown `etype`
  rather than returning an empty BGP — the assertion that generalizes.
- **Translation-level:** `_delete_from_bindings` raises on an unbound
  delete-template variable, in each of the four positions.
- **Fail-closed end-to-end:** a rejected update leaves the data intact.

## Coverage gap — CLOSED (2026-08-04)

Everything in this section was open until 2026-08-04; see "How it was closed"
below for what changed. The original description follows.

### The gap, as filed

- Teach `dawg_manifest_parser.py` the `mf:UpdateEvaluationTest` type (its
  `type_map` at line 77 has only query/syntax types) and add a pytest
  conformance module that drives the existing `dawg_update_test.py` runner over
  `UPDATE_CATEGORIES`. The runner is complete; it just lives outside
  `testpaths` and is never collected.
- Add `bindings` (the DAWG `VALUES` category, 11 tests) to `P0_CATEGORIES` in
  `test_dawg_sql_v2.py` so `VALUES` is exercised against the SQL backend, not
  only pyoxigraph.

Neither would have caught *this* bug — no DAWG `.ru` file uses `VALUES` — but
both close the hole that let it stay invisible.

### Definition of done — all met

1. ✅ A pytest module drives the update runner over `UPDATE_CATEGORIES`.
2. ✅ `bindings` is in `P0_CATEGORIES`.
3. ✅ Both green; the genuine failures they surfaced are fixed (one) or filed
   and xfailed with reasons (four).

### How it was closed

**`tests/conformance/test_dawg_update_sql_v2.py` (new) — 95 tests.**
Drives the existing `dawg_update_test.py` runner over all 11
`UPDATE_CATEGORIES`. Each case loads the pre-state, runs the update through the
real SPARQL→SQL translation, and compares the resulting graph to the manifest's
expected post-state.

*Correction to the plan:* item 1 above said to teach `dawg_manifest_parser.py`
the `mf:UpdateEvaluationTest` type. That turned out to be unnecessary — a
separate, complete `parse_update_manifest` already existed in
`dawg_update_test.py`. The only thing missing was the pytest module. The
`type_map` gap in `dawg_manifest_parser.py` only ever affected the query-side
collector, which does not handle update tests anyway.

**`tests/conformance/test_dawg_sql_v2.py` — now actually executes SQL.**
The bigger finding, and it made item 2 meaningful. Despite its name, docstring,
`sql_v2` marker and PostgreSQL+sidecar gate, this module ran **only the
pyoxigraph oracle** and never touched the SQL pipeline — its own comment said
"full sql_v2 execution ... is handled by run_single_test_sql_v2 in the runner",
and nothing in `tests/` ever called that runner. So the 350 conformance tests
that had been passing all along were pyoxigraph validating itself against the
W3C expected results; **the SQL backend had no conformance coverage on the
query side either**. Adding `bindings` to `P0_CATEGORIES` without fixing this
would have added 11 more tests that never touch our code.

It now runs both: `test_oracle_baseline` (pyoxigraph, for attribution) and
`test_sql_v2` (the real pipeline).

**Bugs this surfaced immediately**

- **A defect in this issue's own fix.** Four W3C update tests failed because
  `_delete_from_bindings` *raised* on an unbound DELETE-template variable. The
  spec says such a template yields no triple — a no-op. `delete-07.ru`
  ("Simple DELETE 7") exists precisely to check it, its stated purpose being
  "to test that unbound variables in the DELETE clause do not act as
  wildcards". Fixed: it now emits a no-op, which keeps the safety property (an
  unbound position must never become a wildcard) while being spec-legal. The
  earlier behaviour was safe but wrong, and only conformance caught it.
- **Four aggregate bugs**, pre-existing and unrelated: `MIN`/`MAX` compare RDF
  terms as text so numerics order lexicographically, and `AVG` over a
  non-numeric term aborts the query with a Postgres cast error. Filed as
  `issues/029_aggregates_over_mixed_typed_literals.md` and xfailed with
  reasons in `XFAIL_SQL_V2_EXEC`.

**Result:** conformance 350 → **604 passed**, 26 skipped, 30 xfailed. Full
local suite 2045 passed; `tests/api` 502 passed against a rebuilt stack.

### This work also unblocked issue 028

As predicted, the corpus this created is what
`issues/028_expression_emitters_fail_open_on_unresolved_vars.md` needed to
measure its blast radius. That measurement is done — 6 hits in 2045 tests, all
legitimately unbound — and it settled 028's design question. See its
"Measurement" section.

Until then the bespoke tests in
`tests/integration/test_update_where_constraints.py` are the only thing
standing between an update-translation regression and production.

