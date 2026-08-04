# `EXISTS` / `NOT EXISTS` lose correlation when the outer variable is referenced only in an inner `FILTER`

## Status: FIXED (2026-08-03) — see "Fix as applied"

## Severity

**Data loss in one direction, missing results in the other.** Both silent.

- `FILTER NOT EXISTS` → the guard is dropped, so a `DELETE` guarded by it takes
  everything, including the rows the guard was written to protect. Same
  fail-open family as issue 023.
- `FILTER EXISTS` → matches nothing, so results silently disappear.

No error and no warning is emitted — see "Even the diagnostic is suppressed".

## Summary

When the pattern inside `EXISTS` / `NOT EXISTS` references an outer variable
**only from a `FILTER`** — rather than from one of its own triple patterns —
the correlation to the outer row is lost. The outer variable is not in the
inner emit context, so it compiles to the SQL literal `NULL`, the inner
comparison becomes `NULL = ...` → NULL, and the inner subquery returns zero
rows for every outer row.

`EXISTS` is then always false and `NOT EXISTS` always true, regardless of data.

## Reproduction

PostgreSQL + Jena sidecar, 4 seeded subjects `doc0..doc3`, each with one
`<probe/name>` triple.

```sparql
# expected {doc1,doc2,doc3} — actual {doc0,doc1,doc2,doc3}  (guard dropped)
SELECT DISTINCT ?s WHERE { GRAPH <g> {
  ?s ?p ?o .
  FILTER NOT EXISTS { ?s2 <probe/name> "doc0" . FILTER(?s = ?s2) }
} }

# expected {doc0} — actual {}  (matches nothing)
SELECT DISTINCT ?s WHERE { GRAPH <g> {
  ?s ?p ?o .
  FILTER EXISTS { ?s2 <probe/name> "doc0" . FILTER(?s = ?s2) }
} }
```

The `EXISTS` case is the clearer proof: the failure is not an inverted
negation, it is the inner subquery genuinely producing no rows.

### Data loss, verified

```sparql
DELETE { GRAPH <g> { ?s ?p ?o } }
WHERE  { GRAPH <g> {
  ?s ?p ?o .
  FILTER NOT EXISTS { ?s2 <probe/name> "doc0" . FILTER(?s = ?s2) }
} }
```

Intent: delete everything *except* `doc0`. Expected 1 survivor.
**Actual: 0 survivors** — the protected subject was deleted too.

## Probe matrix

Same stack, same seed data. The distinguishing factor is *where* the outer
variable appears inside the EXISTS pattern:

| Shape | Result |
|---|---|
| `NOT EXISTS { ?s <name> "doc0" }` — outer var in the inner BGP | **correct** |
| `NOT EXISTS { ?s <name> ?n2 . FILTER(?n2 = "doc0") }` — outer var in inner BGP, filter is local | **correct** |
| `NOT EXISTS { ?s2 <name> ?n2 . FILTER(?n2 = "doc0") }` — no outer var at all | **correct** |
| `?s2 <name> "doc0" . FILTER(?s = ?s2)` — same filter *outside* any EXISTS | **correct** |
| **`NOT EXISTS { ?s2 <name> "doc0" . FILTER(?s = ?s2) }`** | **guard dropped → returns everything** |
| **`NOT EXISTS { ?s2 <name> "doc0" . FILTER(sameTerm(?s, ?s2)) }`** | **guard dropped → returns everything** |
| **`EXISTS { ?s2 <name> "doc0" . FILTER(?s = ?s2) }`** | **matches nothing → returns empty** |

An outer variable used in an inner *triple pattern* correlates correctly. Only
a filter-only reference breaks.

## Root cause

`vitalgraph/db/sparql_sql/emit_expressions.py:_exists_to_sql` (line 937)
establishes correlation solely from **scope intersection**:

```python
outer_vars = set(ctx.types.all_vars())
inner_scope = compute_scope(inner_plan)
inner_vars = inner_scope.all_visible
shared = outer_vars & inner_vars
```

`?s` is referenced only inside the inner FILTER, so it is not in
`inner_scope.all_visible`, so it is not in `shared`, so no correlation
predicate is generated for it.

Worse, the reference still has to be emitted. The inner FILTER is emitted
against `inner_ctx`, where `?s` is unregistered, and `_var_to_sql`
(`emit_expressions.py:110`) returns the string `"NULL"` for any variable not in
the registry:

```python
def _var_to_sql(expr: ExprVar, ctx: EmitContext) -> Optional[str]:
    info = ctx.types.get(expr.var)
    if info and info.text_col:
        return info.text_col
    # Rule 1: NULL = unbound (§10.5). Variable not in registry.
    ...
    return "NULL"
```

So the inner filter compiles to `NULL = <inner col>`, which is NULL for every
row, and the inner subquery yields nothing.

Per SPARQL 1.1 §8.1.1, `EXISTS` is evaluated with the current solution mapping
substituted in — the outer binding of `?s` should be substituted into the inner
FILTER. The current implementation only correlates variables that the inner
pattern independently binds.

### Even the diagnostic is suppressed

`_var_to_sql` has a `logger.warning` for exactly this "variable is out of
scope" situation, but it is gated on `ctx.query_all_vars`, and `_exists_to_sql`
constructs its `inner_ctx` **without** passing `query_all_vars`
(`emit_expressions.py:960-968`). So the warning never fires for this path and
the failure is completely silent.

The warning text is also misleading here — it attributes the condition to "a
BIND inside a UNION branch" and advises restructuring the UNION, which does not
apply to EXISTS.

## Suggested fix

1. **Collect filter-referenced variables, not just scope-visible ones.** Walk
   the inner pattern's filter expressions for variable references (there is
   already a `vars_in_expr` helper used by `var_scope.py`), union those with
   `inner_scope.all_visible` when computing `shared`.
2. **Substitute the outer column rather than emitting NULL.** For an outer
   variable that the inner pattern does not bind, the inner FILTER must
   reference the *outer* alias's column directly — that is what makes the
   subquery genuinely correlated. Registering those outer variables in
   `inner_ctx` (pointing at the outer columns) before emitting `inner_sql` is
   the smaller change; passing them through as correlation predicates is the
   alternative.
3. **Fail loudly meanwhile.** *(Only partially done — see "Known gap" below.)*
   Whatever the shape of the fix, an outer variable
   that reaches `_var_to_sql` unregistered inside an EXISTS should not silently
   become `NULL`. Given issues 023 and 026, the pattern across this codebase is
   that a dropped constraint reads as success and widens a delete. At minimum
   pass `query_all_vars` into `inner_ctx` so the existing warning fires, and
   fix its UNION-specific wording.

---

## Fix as applied

It took **two** changes, not one. The correlation fix alone was not enough —
see "The second half" below, which the original analysis missed.

### 1. Bind filter-only outer variables — `emit_expressions.py::_exists_to_sql`

Outer variables the inner pattern does not bind are now registered in
`inner_ctx` pointing at the outer columns, before `inner_sql` is emitted. The
inner FILTER then references the outer row instead of compiling to `NULL`,
which is what makes the subquery genuinely correlated.

Safe against shadowing: `AliasGenerator.next_var` applies the `ex_` prefix to
inner column names, so a bare outer name like `v0` can never collide with an
inner `ex_v0` and resolves to the enclosing query.

`inner_ctx.query_all_vars` is also now propagated, so the pre-existing
`_var_to_sql` diagnostic can actually fire for a genuinely unresolvable
reference instead of silently emitting NULL.

### 2. Count those variables as text-needed — `var_scope.py::vars_in_expr`

**This is the half the original write-up missed.** With only change 1, a
URI-valued outer variable worked but a **literal**-valued one still failed.

`vars_in_expr` had no `ExprExists` case, so a variable referenced *only* inside
an EXISTS pattern was invisible to `compute_text_needed_vars`. The outer BGP
then skipped that variable's term-table join and emitted `NULL` for its text
column — so the correlation compared a real inner value against a literal NULL
and matched nothing. Same symptom, different cause, one layer up.

`vars_in_expr` now recurses into `ExprExists.graph_pattern` via a new
`_vars_in_algebra` helper, which walks dataclass fields generically rather than
switching on Op type, so a new Op kind cannot silently go uninspected.

Diagnosing this needed the actual rows, not just the SQL: the emitted
correlation clause read `WHERE (v1 = ex_v1)` — which *looks* correct — and only
dumping the outer result showed `v1` was NULL for every row.

## Verification

- `tests/integration/test_minus_and_exists_correlation.py` — 22 tests covering
  both issues: every probe-matrix row, both EXISTS and NOT EXISTS directions,
  URI- and literal-valued outer variables, nesting, and the guarded-DELETE
  shape.
- `tests/unit/sparql_sql/test_exists_var_refs.py` — 11 tests, no DB needed, for
  the `vars_in_expr` half.
- **Confirmed to fail pre-fix**: reverting the source files reproduced 12
  integration + 6 unit failures.
- Full suite after: 1791 passed / 56 skipped / 29 xfailed, plus 500 passed /
  9 skipped in `tests/api` against a rebuilt test stack.

### Correction to the probe matrix above

`FILTER NOT EXISTS` nested inside another `FILTER NOT EXISTS` was **also**
broken — it is not in the matrix because it was not probed at filing time. It
is covered now (`test_nested_not_exists`) and was verified to fail pre-fix.

## Regression test to add (done — see Verification)

- Every row of the probe matrix above as a SELECT — the correct shapes matter
  as much as the broken ones, since the difference is only where the variable
  appears.
- The `EXISTS` direction as well as `NOT EXISTS`; they fail differently and a
  test for only one would miss a partial fix.
- The DELETE case, asserting the surviving count — a guard that silently stops
  guarding is the data-loss shape.

## Known gap — the underlying fail-open is NOT fixed

This issue's specific defect is fixed and regression-tested. The *mechanism*
that made it silent is not.

`_var_to_sql` still returns the literal `NULL` for any variable it cannot
resolve, so the next translation gap of this kind will again widen a constraint
instead of erroring. Suggested-fix item 3 above was only partially applied:

- **Done:** `query_all_vars` is now propagated into the EXISTS inner context,
  so the diagnostic can fire there at all (it previously could not, making this
  class of failure completely silent); and the warning text was rewritten,
  since it wrongly attributed the condition to "a BIND inside a UNION branch"
  and prescribed a UNION-specific remedy.
- **Not done:** failing closed. A log line is not a fix — nothing is surfaced
  to the caller and an UPDATE still returns success.

Tracked as
`issues/028_expression_emitters_fail_open_on_unresolved_vars.md` (**NOT
FIXED**), which explains why fixing the three instances did not fix the
pattern, and why it should not be changed blind.

## Related

- `issues/028_expression_emitters_fail_open_on_unresolved_vars.md` — NOT FIXED.
  The shared root pattern behind this issue, 023 and 026.
- `issues/023_values_clause_ignored_in_sparql_update.md` — fixed. Same failure
  *shape* (a dropped constraint widening a DELETE), different mechanism
  (unhandled syntax element vs. lost correlation). Note that 023's regression
  test `test_not_exists_constrained_delete` uses the plain
  `FILTER NOT EXISTS { ?s <protected> true }` form, which is in the "correct"
  column above — so it passes and does not cover this defect.
- `issues/026_minus_ignored_when_shared_var_has_no_term_uuid.md` — open. Also a
  silently-ignored constraint, and also rooted in how a variable's identity is
  compared across a subquery boundary (`__uuid` columns there, scope
  registration here). Worth fixing with an eye on both.

## Provenance

Found while probing issue 026. Recorded there as "related, observed but not
root-caused" and split out here after root-causing.
