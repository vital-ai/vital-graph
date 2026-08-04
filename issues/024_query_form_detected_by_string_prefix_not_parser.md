# SPARQL query form detected by string prefix, not by the parser — any prologue misclassifies the query, and the adapter never returns a boolean at all

## Status: FIXED (2026-08-04)

All four steps of the suggested fix are implemented. The call-site audit turned
up one pre-existing defect in an unrelated, unwired module, left alone and
explained under "Remaining" below.

Changed:

- `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py:1444` — the result dict now
  carries `'query_type'`, and `'boolean'` when the form is `ASK`.
- `vitalgraph/endpoint/sparql_query_endpoint.py:128-170` — dispatches on
  `query_type`; passes the adapter's boolean through instead of recomputing it;
  rejects `CONSTRUCT`/`DESCRIBE` and fails closed on an unrecognised form.
- `vitalgraph/kg_impl/kg_validation_utils.py:672,738` — supplied the missing
  `space_id` argument.
- `tests/api/test_sparql_api.py` — new `TestQueryFormDispatch`, 11 cases.

Verified against the test stack on :8002. Full `tests/api` suite before the
change: 26 failed, 463 passed, 9 skipped. After: 26 failed, 481 passed, 9
skipped — the same 26 pre-existing failures (all in the `TestTextSearchDbVerification`
and `TestVectorDbVerification` classes, unrelated to this issue and confirmed
identical with the change stashed), plus the 18 new tests.

Also done in a follow-up pass:

- **ASK no longer materialises every matching row.**
  `sparql_sql_space_impl.py:1411` wraps the generated SQL as
  `SELECT EXISTS (SELECT 1 FROM (…) _ask_sub)` when the form is `ASK`, and the
  boolean is read from that rather than by counting bindings. SPARQL forbids
  solution modifiers on `ASK`, so there is no inner `LIMIT`/`OFFSET`/`ORDER BY`
  to disturb.
- **Both `ASK` workarounds reverted.**
  `kgframes_endpoint._validate_parent_object` and
  `kgdocuments_endpoint._check_delete_protection` now use `ASK` and read
  `result['boolean']`; the dead `_result_has_rows` helper and the unused
  `sparql_bindings` import went with them.

  Neither guard had *any* test coverage, so the passing suite proved nothing
  about the revert. Two layers of tests were added:

  - `test_sparql_api.py::TestGuardQueryShapes` — locks the backend query shapes
    the guards rely on: `ASK` + `VALUES` distinguishing a managed segment from
    a user document from an absent subject, and `ASK` on `rdf:type` not
    conflating `KGEntity` with `KGFrame`. These do not call the guards.
  - Endpoint-level tests that exercise the guards themselves:
    `test_kgdocuments_api.py::TestManagedSegmentDeleteProtection` (delete a
    managed segment → rejected; user-defined segment type and plain document →
    still deletable) and
    `test_kgframes_api.py::TestParentObjectValidation` (frame parent →
    `Edge_hasKGFrame` created; nonexistent parent → no edge).

  **Writing the endpoint-level tests immediately found a real defect**, filed
  as `issues/031_client_delete_response_reports_rejected_delete_as_success.md`:
  the server correctly refused to delete a managed segment, and the client
  reported `is_success=True` with a fabricated `"Deleted KGDocument: …"`
  message. Fixed there. The shape-level tests would never have caught it —
  which is the argument for both layers.

### Remaining: `vitalgraph_service_impl.py` — pre-existing, unrelated, larger

Deliberately not fixed. It is **not** a two-line defect and it is not caused by
anything in this issue.

`vitalgraph/service/graph/vitalgraph_service_impl.py` is a fully synchronous
class — 50 `def`s, zero `async def`s — that calls the **async**
`VitalGraphClient` at 26 sites without `await`. `.get("boolean")` at `:334` and
`:360` therefore runs against a coroutine object. At `:335` the `except` catches
only `VitalGraphClientError`, so the `AttributeError` escapes to the caller; at
`:361` a broad `except Exception` swallows it into `False`. The two boolean
readers are just where this issue's audit happened to intersect it — the whole
module is affected.

**Why this has not caused problems.** It has been broken for roughly six months
and has never once run in that state:

- Commit `2118686` (2026-02-11) converted `VitalGraphClient` from sync to async,
  updating ~10 client endpoint modules. It did **not** touch
  `vitalgraph_service_impl.py`. Before that commit the client was genuinely
  sync (`def execute_sparql_query` at `a978486:vitalgraph_client.py:587`), so
  these call sites were correct as written and the conversion orphaned them
  wholesale.
- Nothing under `vitalgraph/` imports `VitalGraphServiceImpl`. The only
  references are `test_scripts/vitalgraph_service_tests/`, which CI does not
  run.

So it is dead code that was silently invalidated by a refactor and never
exercised again. Passing a raw query string where a `SPARQLQueryRequest` is
expected is an *older* mismatch still — that signature already took a request
object before the async conversion — which reinforces the same conclusion.

**Tracked as `issues/032_vitalgraph_service_impl_stranded_by_sync_interface.md`.**
The module is the remote, client-backed implementation of the VitalSigns
`VitalGraphService` interface — the abstraction meant to let callers work
against a local graph service or a remote VitalGraph server interchangeably. It
is stranded because that interface is synchronous while its backend is not, so
the preferred fix is upstream in `vital-vitalsigns-python`: convert the
interface to `async`, after which almost nothing here needs to change. See 027
for the full plan and the sequencing caveat.

## Scope note

`BACKEND_TYPE` defaults to `sparql_sql` (`config_loader.py:87`) and the
`fuseki` / `fuseki_postgresql` backends are no longer in use. Everything below
is scoped to `sparql_sql` only; the Fuseki adapters return conformant SPARQL
JSON with a real `boolean` key and are out of scope.

## Severity

**Silent wrong results.** An `ASK` that should answer `true` returns `boolean =
None` and SELECT-shaped bindings instead. A caller reading `response.boolean`
gets a falsy value — so a guard written as "delete only if this ASK says the
object is protected" evaluates as *not protected*.

Affects essentially every real-world query, because real queries have a
`PREFIX` prologue.

**In-repo callers are broken too, by a larger sibling defect.** An earlier
revision of this issue claimed exposure was limited to external REST clients,
on the grounds that the two endpoint guards avoid `ASK`. That was wrong. Around
ten `kg_impl` / `service` call sites issue `ASK` straight through the backend
adapter, bypassing the REST layer, and read a `boolean` the adapter never
returns — see "The adapter has no boolean at all" below. Those are live
failures today, and they are the ones with real consequences.

## Summary

`vitalgraph/endpoint/sparql_query_endpoint.py:128-160` determines the SPARQL
query form by string-matching the start of the raw query text:

```python
query_upper = query.strip().upper()

if query_upper.startswith('ASK'):
    boolean_result = len(bindings) > 0
    return SPARQLQueryResponse(boolean=boolean_result, ...)
elif query_upper.startswith('CONSTRUCT') or query_upper.startswith('DESCRIBE'):
    return SPARQLQueryResponse(triples=bindings, ...)
else:
    # assumed SELECT
```

A SPARQL query does not begin with its form keyword. The grammar is
`Prologue ( SelectQuery | ConstructQuery | DescribeQuery | AskQuery )`, and the
prologue — `BASE`, any number of `PREFIX` declarations — comes first. Comments
may precede it too. In all those cases the check falls through to the `else`
branch and the query is treated as a `SELECT`.

**The Jena sidecar already parses this correctly.** The compile response carries
the parsed form, and it is already mapped through to Python as
`CompileResult.meta.query_type`:

- `vitalgraph-jena-sidecar/.../serializer/ElementSerializer.java:136` —
  `q.put("queryType", query.queryType().toString())`, covered for all four forms
  by `SparqlCompilerTest.java` and `smoke_test.py`
- `vitalgraph/db/jena_sparql/jena_ast_mapper.py:127` — `query_type=pq.get("queryType")`
- `vitalgraph/db/jena_sparql/jena_types.py:435` — `query_type: Optional[str]  # "SELECT", "CONSTRUCT", "ASK", "DESCRIBE"`
  (a field of `ParsedQueryMeta`, reached via `CompileResult.meta`)

The authoritative, parser-derived answer exists and is discarded in favour of
`startswith`. Nothing downstream reads it: `grep query_type` over
`vitalgraph/db/sparql_sql/` returns a single hit, an unrelated hardcoded
`"SELECT"` in `emit_update.py:603`.

## Reproduction

Verified against the test stack (`docker-compose.test.yml`, app on :8002), one
KGDocument seeded in graph `<g>`.

| Query | `boolean` | `results` | Correct? |
|---|---|---|---|
| `ASK { GRAPH <g> { ?s <…hasName> ?o } }` | `True` | — | yes |
| `PREFIX v: <…>`⏎`ASK { GRAPH <g> { ?s v:hasName ?o } }` | `None` | bindings | **no** |
| `# comment`⏎`ASK { GRAPH <g> { ?s <…hasName> ?o } }` | `None` | bindings | **no** |
| `BASE <http://example.org/>`⏎`ASK { … }` | `None` | bindings | **no** |
| `PREFIX v: <…>`⏎`ASK { … v:hasName "nope" }` (false case) | `None` | bindings | **no** |

The CONSTRUCT branch has the same dispatch defect, but see Impact — CONSTRUCT
and DESCRIBE are unimplemented in the backend, so neither routing outcome is
correct and the observed rows below are WHERE-pattern bindings, never triples:

| Query | `triples` | `results` | Correct? |
|---|---|---|---|
| `CONSTRUCT { … } WHERE { … }` | bindings, mislabelled | — | **no** |
| `PREFIX v: <…>`⏎`CONSTRUCT { … } WHERE { … }` | `None` | bindings | **no** |

Note the false-ASK row: a prologued ASK returns bindings whether the answer is
true or false, so a caller cannot even recover the answer by testing
truthiness of `results` — an ASK matching zero rows and an ASK misrouted to
SELECT are indistinguishable at the response level.

## The adapter has no `boolean` at all

The string-matching bug above is the REST layer's. Underneath it is a larger
one: `execute_sparql_query` in `sparql_sql_space_impl.py` returns
`{'results', 'success', 'sql'}` and **never** a `'boolean'` key, for any query
form. `grep "'boolean'"` over that file returns nothing.

That matters because many in-repo callers do not go through the REST endpoint —
they call the adapter directly and read a boolean off the returned dict:

| Call site | Reads | Result under `sparql_sql` |
|---|---|---|
| `kgrelations_delete_impl.py:123` | `result.get('boolean', False)` | always `False` |
| `kgrelations_create_impl.py:212` | `result.get('boolean', False)` | always `False` |
| `kgframe_hierarchical_impl.py:195` | `results.get('boolean', False)` | always `False` |
| `kg_backend_utils.py:688` | `result.get('boolean', False)` | always `False` |
| `vitalgraph_service_impl.py:335,361` | `result.get("boolean", False)` | always `False` |
| `kg_backend_utils.py:280` | `'boolean' in result` → `result['boolean']` | always `False` |
| `kg_validation_utils.py:619,624` | multi-branch probe, else-warn | always `False` + warning |
| `kg_validation_utils.py:678,744` | multi-branch probe, else-default | always `False` |

The prologue question is irrelevant to these. A bare `ASK` fails identically to
a prologued one, because the adapter has no boolean to give either way.

Every one of these degrades **silently to `False`** — none raise. The
subscripting sites are all guarded by an `isinstance(result, dict) and
'boolean' in result` test that simply never passes, so they fall through to a
`False` default. `kg_validation_utils.py:617` additionally probes
`'boolean' in result['results']['bindings']`, an `in` test against a *list* of
bindings, which is likewise always false rather than a `TypeError`.

The defensive multi-branch parsing is what makes this invisible: each site was
written to tolerate several possible result shapes, so encountering none of
them looks like a normal negative answer. `kgrelations_delete_impl`
`_relation_exists` reports "relation does not exist" unconditionally, whatever
is in the graph.

Whether a fixed `False` is fail-open or fail-closed depends on each guard's
polarity — it is not uniform, so each site needs checking individually as part
of the fix, not just a mechanical adapter change.

**Two adjacent bugs found in the same sweep**, both latent behind the silent
`False`: `kg_validation_utils.py:672` and `:738` call
`self.backend.execute_sparql_query(query)` with the `space_id` argument
missing, passing the query text as `space_id`. That is a `TypeError` swallowed
by the enclosing `except Exception`, meaning `validate_frame_ownership` and
`validate_frame_hierarchy` have never executed their queries at all. Fixing the
adapter boolean will not fix these; they need their own correction and are
worth confirming as reachable code before investing in either.

## Impact

- **Any client using `ASK` idiomatically is broken.** Prologues are the norm;
  the bare-keyword form that happens to work is the exception.
- **Guards fail open.** Code shaped as `if resp.boolean: reject()` silently
  stops rejecting. This is the same fail-open class as
  `issues/023_values_clause_ignored_in_sparql_update.md`: an unhandled input
  does not error, it quietly means something weaker.
- **CONSTRUCT/DESCRIBE are not implemented at all** — tracked separately as
  `issues/025_construct_describe_unimplemented.md`. It matters here because it
  inverts the obvious fix: dispatching correctly on `query_type` would move
  WHERE-clause bindings into the `triples` field, labelling bindings as triples
  — worse than today's accident, because it looks right. Until §025 lands,
  these forms must **raise**, not route.
- **It pushed a workaround into unrelated code.** Two call sites avoid `ASK`
  and hand-roll `SELECT … LIMIT 1` because of adjacent layering confusion:
  `kgframes_endpoint._validate_parent_object` (`:2704-2708`) and
  `kgdocuments_endpoint._check_delete_protection`. Those are correct as written
  — the *backend adapter* genuinely returns bindings, not a boolean — and their
  authors evidently hit the adapter defect and routed around it rather than
  fixing it. They can revert to `ASK` once step 1 of the fix lands.

## Suggested fix

**Fix it at the adapter, not the REST layer.** The endpoint synthesising
`boolean` from a string match is the visible symptom; the adapter not returning
one is the cause, and it is what breaks the in-repo callers. Fixing the adapter
makes the REST change a thin pass-through and repairs both populations at once.

1. **Return the parsed form and a real `boolean` from `execute_sparql_query`**
   in `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py`. Smaller than it
   looks: `cr = map_compile_response(raw)` is already a local at `:1383`, in
   scope at the return dict on `:1444`. Add `'query_type': cr.meta.query_type`,
   and when that value is `ASK`, add `'boolean': len(bindings) > 0`. No
   plumbing from the mapper is needed.

   Deriving the boolean by counting is correct *here* — the generator ignores
   `query_type`, so `ASK` compiles to a plain row-returning `SELECT`. That is
   precisely the contract that belongs at this boundary, and it is already
   documented at a call site that had to work around its absence
   (`kgframes_endpoint.py:2707-2708`).

2. **Audit the ~10 boolean call sites listed above.** They stop returning a
   fixed `False` once step 1 lands, which changes behaviour at every one. Check
   each guard's polarity for what it now starts doing, and separately fix the
   missing-`space_id` calls at `kg_validation_utils.py:672,738`.

3. **Dispatch on `query_type` in `sparql_query_endpoint.py`** instead of
   `startswith`, passing through the adapter's `boolean` rather than
   recomputing it.

4. **Fail closed on anything not genuinely supported** — raise rather than
   defaulting to the `SELECT` branch, so a form cannot silently take the wrong
   shape (the §023 lesson). Per Impact, that currently means `CONSTRUCT` and
   `DESCRIBE` too, not just unrecognised forms — an explicit "not supported" is
   the only honest response until §025 lands. Only `SELECT` and `ASK` should
   route.

Worth folding in while touching this: because ASK compiles to an unmodified
SELECT, it has no `LIMIT 1` and materialises every matching row to answer a
yes/no question. Correctness is unaffected; on a broad pattern the cost is not.

## Regression tests to add

- `SELECT` and `ASK`, run **both** bare and with a `PREFIX` prologue, asserting
  the response shape matches the form.
- `ASK` true *and* false cases with a prologue — asserting `boolean is True` /
  `boolean is False`, never `None`.
- A leading-comment and a `BASE`-prologue case.
- `CONSTRUCT` and `DESCRIBE`, bare and prologued, asserting an explicit
  not-supported error — **not** a response shape. These flip to shape
  assertions under §025 and should move there when they do.
- An unrecognised/unparseable query errors rather than silently taking the
  SELECT path.
- **At the adapter, not just the endpoint:** `execute_sparql_query` returns
  `boolean is True` / `boolean is False` for a matching / non-matching `ASK`,
  bare and prologued. This is the test that would have caught the whole
  in-repo family, and its absence is why the defect survived.
- `kgrelations_delete_impl._relation_exists` returns `True` for a relation that
  exists — a direct regression test for the always-`False` behaviour.

## Related

- `issues/023_values_clause_ignored_in_sparql_update.md` — same fail-open
  pattern in the update path: an unhandled construct widens behaviour instead of
  raising.
- `issues/025_construct_describe_unimplemented.md` — split out of this issue's
  Impact section. Blocks the CONSTRUCT/DESCRIBE half of the fix here; until it
  lands, those forms must raise rather than route.
- `issues/021_uri_prefix_string_matching_in_deletes.md` — same root habit:
  deciding semantics by string-matching text that should be parsed. Found while
  fixing 021.
