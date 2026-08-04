# `MINUS` is silently ignored when its shared variable comes from `BIND` or `VALUES`

## Status: FIXED (2026-08-03) — see "Fix as applied"

## Severity

**Wrong results, silently.** The `MINUS` contributes nothing and the query
returns the unfiltered left side. No error, no warning.

Affects SELECT *and* UPDATE. In a `DELETE ... WHERE { ?s ?p ?o . MINUS {...} }`
the dropped exclusion widens the delete — same fail-open family as issue 023,
so this is a data-loss risk, not only a correctness one.

## Summary

`emit_minus` decides whether a left row is excluded by comparing `__uuid`
columns. Any variable whose value does not come from the term table — `BIND`,
`VALUES`, aggregates — has a literal `NULL::uuid` in that column. `emit_minus`
reads NULL as "unbound", the domain-intersection test can never be satisfied,
and the `NOT EXISTS` is vacuously true for every row.

So the value is *bound*, but the emitter cannot see it.

## Reproduction

Verified against PostgreSQL + Jena sidecar, 4 seeded subjects `doc0..doc3`,
each with one `<probe/name>` triple. Every query below is a plain SELECT — the
update path is not required to reproduce.

```sparql
# expected {doc1,doc2,doc3} — actual {doc0,doc1,doc2,doc3}
SELECT DISTINCT ?s WHERE { GRAPH <g> {
  ?s ?p ?o .
  MINUS { ?x ?y ?z . BIND(<probe/doc0> AS ?s) }
} }

# expected {doc1,doc2,doc3} — actual {doc0,doc1,doc2,doc3}
SELECT DISTINCT ?s WHERE { GRAPH <g> {
  ?s ?p ?o .
  MINUS { VALUES ?s { <probe/doc0> } }
} }
```

## Probe matrix

Same stack, same seed data. The pattern is exactly "does the shared variable
have a real term UUID":

| Shape | Result |
|---|---|
| `MINUS { ?s <name> "doc0" }` — shared var from a BGP | **correct** |
| `MINUS { ?s <name> "doc0" . BIND(1 AS ?n) }` — BIND present but shared var still from a BGP | **correct** |
| `MINUS { VALUES ?s {...} ?s ?p9 ?o9 }` — VALUES joined to a BGP that rebinds `?s` | **correct** |
| **`MINUS { ?x ?y ?z . BIND(<doc0> AS ?s) }`** — shared var from BIND | **ignored** |
| **`MINUS { VALUES ?s {...} }`** — shared var from VALUES alone | **ignored** |
| `BIND(<doc0> AS ?b) FILTER(?s = ?b)` — BIND compared in a FILTER | correct |
| `BIND(<doc0> AS ?s) ?s ?p ?o` — BIND joined to a BGP | correct |

BIND and VALUES are fine in joins and filters. Only the `MINUS` comparison path
is affected.

## Root cause

`vitalgraph/db/sparql_sql/emit_minus.py:56-73` builds both halves of the SPARQL
§18.5 test purely from `__uuid` columns:

```python
compat_parts.append(
    f"({l_uuid} IS NULL OR {r_uuid} IS NULL OR {l_uuid} = {r_uuid})")
nonempty_parts.append(f"({l_uuid} IS NOT NULL AND {r_uuid} IS NOT NULL)")
```

`emit_extend` (BIND) and `emit_table` (VALUES) both emit a literal NULL for
that companion column — `sql_type_generation.py:233` and `:518`,
`emit_table.py:51,62,71` — while carrying the real value in the text/type
columns (`v5`, `v5__type`).

Generated SQL for the BIND repro, trimmed to the relevant lines:

```sql
SELECT *, 'http://example.org/probe/doc0' AS v5, 'U' AS v5__type,
       NULL::uuid AS v5__uuid, ...
...
WHERE (ml0.v0__uuid IS NULL OR mr0.v5__uuid IS NULL OR ml0.v0__uuid = mr0.v5__uuid)
  AND ((ml0.v0__uuid IS NOT NULL AND mr0.v5__uuid IS NOT NULL))
```

`mr0.v5__uuid` is the constant `NULL::uuid`, so the domain-intersection
conjunct is always FALSE, `NOT EXISTS` is always TRUE, and no left row is ever
removed. The `MINUS` is a no-op by construction.

The NULL-means-unbound reading is correct for a genuinely unbound variable
(an OPTIONAL that did not match). The bug is conflating that with "bound, but
not to a term-table row".

## Suggested fix

Do not compare on `__uuid` alone. `emit_update._binding_uuid_col` already
solves exactly this problem for the update write path — COALESCE the `__uuid`
column with a deterministic UUID computed in SQL from the text/type/lang/
datatype companions:

```python
COALESCE(CAST(b."col__uuid" AS uuid),
         vitalgraph_term_uuid(text, type, lang, datatype_id))
```

Applying the same COALESCE to `l_uuid`/`r_uuid` in `emit_minus` makes
BIND/VALUES/aggregate values comparable and leaves genuinely-unbound variables
NULL, so the §18.5 semantics stay correct. `vitalgraph_term_uuid` mirrors
`_generate_term_uuid` exactly, so the computed UUID equals the term-table UUID
for any term that exists.

Audit the other emitters that compare on `__uuid` for the same assumption —
`emit_join.py:75,100-101` at minimum. The probe matrix says joins are currently
fine, so this is confirmation rather than a suspected second bug.

**Audit done — `emit_join` is not affected, structurally.** It gates the
`__uuid` comparison on `from_triple` for *both* sides
(`left_has_uuid = left_info.uuid_col and left_info.from_triple`,
`emit_join.py:72-73`) and falls back to a typed-lane or text comparison
otherwise. BIND/VALUES-produced variables are not `from_triple`, so they never
reach the UUID path — which is why the join shapes in the probe matrix pass.
No change needed there.

Corroborating: the comment at `emit_join.py:96-98` already notes that "the base
(text) column may be NULL when text_needed_vars skips term JOINs, even though
the variable IS bound" — the same hazard that turned out to be the second half
of issue 027.

---

## Fix as applied

**`sql_type_generation.py`** — new `term_identity_expr(alias, sql_name, space_id)`,
the shared "what is this variable's term identity" expression:

```sql
COALESCE(alias.v0__uuid,
         CASE WHEN alias.v0 IS NOT NULL THEN vitalgraph_term_uuid(...) END)
```

The `CASE` guard is load-bearing. Without it a genuinely unbound variable (an
OPTIONAL that did not match) would get a non-NULL derived identity and read as
*bound*, breaking the §10.5 compatibility rules in the opposite direction. The
guard keeps NULL meaning unbound while making synthesized values comparable.

**`emit_minus.py`** — both halves of the §18.5 test now use
`term_identity_expr` instead of the raw `__uuid` column. Nothing else about the
compatibility / domain-intersection structure changed.

## Verification

- `tests/integration/test_minus_and_exists_correlation.py` — 22 tests, covering
  every row of the probe matrix plus the guarded-DELETE shape.
- `tests/unit/sparql_sql/test_term_identity_expr.py` — 10 tests, no DB needed,
  asserting on generated SQL: that the MINUS correlation is no longer a bare
  `__uuid` comparison, that lang/datatype participate in the derived UUID, and
  that the unbound guard is present.
- **Confirmed to fail pre-fix**: reverting the source files reproduced 12
  integration failures across issues 026 and 027, including both guarded-DELETE
  cases. These are genuine regression tests.
- Full suite after: 1791 passed / 56 skipped / 29 xfailed
  (unit + integration + fixtures + conformance), plus 500 passed / 9 skipped in
  `tests/api` against a rebuilt test stack — `emit_minus` is on every query
  path, so the API sweep was the point.

### Also fixed, found while verifying

`MINUS` with a **literal-valued** shared variable (`MINUS { VALUES ?nm { "a" } }`)
works too. That path exercises lang/datatype folding in the derived UUID, which
a URI-only fix would have missed.

## Regression test to add (done — see Verification)

- Each row of the probe matrix above, as a SELECT — the correct shapes are as
  important as the broken ones, since the distinguishing factor is subtle.
- The same `MINUS { VALUES ?s {...} }` shape as a DELETE, asserting the
  surviving count, so the fail-open cannot come back through this route after
  issue 023 closed the other one.
- A translation-level assertion on the emitted SQL: the MINUS correlation must
  not reduce to a constant-NULL comparison.

## Related

`issues/027_exists_loses_correlation_for_filter_only_outer_vars.md` — split out
of this issue and root-caused. `FILTER NOT EXISTS { ?s2 <name> "doc0" .
FILTER(?s = ?s2) }` also fails to constrain, but with no `BIND` or `VALUES`
involved: `_exists_to_sql` correlates only on scope-visible variables, so an
outer variable referenced solely from an inner FILTER compiles to `NULL`.
Different mechanism, same failure shape.

Both issues are about how a variable's identity survives a subquery boundary —
`__uuid` columns here, scope registration there. Worth fixing with an eye on
both.

## Provenance

Found while writing the regression tests for
`issues/023_values_clause_ignored_in_sparql_update.md`. A `MINUS`-constrained
DELETE test failed, and the first question was whether issue 023's fix was
incomplete. Running the identical pattern as a SELECT showed it failing there
too, which ruled the update path out. The 023 test was rewritten to plain
shared-variable `MINUS` and now asserts the query path first, so any future
failure there is unambiguously update-specific
(`tests/integration/test_update_where_constraints.py`,
`test_minus_constrained_delete`).
