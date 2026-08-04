# Expression emitters fail *open*: an unresolved variable becomes `NULL` and silently drops the constraint

## Status: MITIGATED (2026-08-04), not fixed — production behaviour unchanged

This is the shared root pattern behind issues 023, 026 and 027. Each of those
fixed one instance; none changed the underlying behaviour.

What changed on 2026-08-04:

- **A ratchet is in place.** The test suite now *raises* on an unresolvable
  variable, with the handful of legitimate corpus occurrences allowlisted by
  name and reason. A new translation gap can no longer be introduced silently
  — it fails the suite. See "The fix as applied".
- **Production still returns `NULL`**, deliberately. The measurement below
  showed that every known occurrence is a *legitimately* unbound variable for
  which `NULL` is the SPARQL-specified result, so failing closed in production
  would break correct queries.

It stays open because the underlying ambiguity is unresolved: the emitter still
cannot distinguish "legitimately unbound" from "the translator failed to
resolve this". The ratchet stops the bleeding without curing it.

## Severity

**Latent data loss.** Not a live bug with a known reproduction — every
*currently known* instance has been fixed. The defect is that the failure mode
is silent and widening, so the next translation gap becomes a whole-graph
delete rather than an error.

Two of the three known instances were exactly that, and both were caught by a
single test that happened to assert a bystander survived.

## The pattern

`_var_to_sql` (`vitalgraph/db/sparql_sql/emit_expressions.py:110`) returns the
string `"NULL"` for any variable it cannot resolve in the current context:

```python
def _var_to_sql(expr: ExprVar, ctx: EmitContext) -> Optional[str]:
    info = ctx.types.get(expr.var)
    if info and info.text_col:
        return info.text_col
    # Rule 1: NULL = unbound (§10.5). Variable not in registry.
    ...
    return "NULL"
```

The comment cites the right rule for the wrong situation. SPARQL §10.5's
"NULL = unbound" is about a variable that is *legitimately unbound at runtime*
— an OPTIONAL that did not match. It is not about a variable the **translator
failed to resolve**. Those are different conditions with the same encoding, and
collapsing them means a translator bug is indistinguishable from ordinary data.

The consequence compounds in one direction only. `NULL = <anything>` is NULL,
NULL is not true, so:

- a `FILTER` that should restrict → restricts nothing
- an `EXISTS` correlation that should match → matches nothing
- a `NOT EXISTS` guard that should protect rows → protects nothing
- in an update's WHERE, the surviving pattern is broader than written → the
  `DELETE` takes more than intended

There is no shape in which losing a variable makes the result *narrower*. Every
failure of this class is a widening, and widening in a DELETE is unrecoverable.

## Why this is not "already fixed by 023/026/027"

Each of those was one route to the same destination, fixed at its own layer:

| Issue | Route | Fixed by |
|---|---|---|
| 023 | Unhandled syntax element → empty BGP (join identity) | fail-closed fall-through in `map_element_to_op` |
| 026 | Synthesized value has `NULL::uuid` → reads as unbound | `term_identity_expr` COALESCE in `emit_minus` |
| 027 | Filter-only outer var unregistered → compiles to `NULL` | bind outer vars in `_exists_to_sql`; teach `vars_in_expr` about `ExprExists` |

023's fix *did* adopt fail-closed, but only for the syntax-element mapper. The
expression emitter — the layer where 027 actually manifested — still fails
open. So the general defect stands: the codebase now rejects an untranslatable
*element*, and still silently widens on an unresolvable *variable*.

Note that 027 needed **two** fixes, not one, and the second was only found
because a literal-valued variable behaved differently from a URI-valued one.
That is the argument for fixing the pattern rather than the instances: the
instances are not obviously enumerable, and the symptom is identical to correct
behaviour.

## What was done instead (interim)

Only diagnostics — no behaviour change:

1. `_exists_to_sql` now propagates `ctx.query_all_vars` into its inner context
   (`emit_expressions.py`), so the warning below can actually fire inside an
   EXISTS. Previously the inner context was constructed without it and the
   condition was **completely silent**.
2. The warning text has been rewritten. It used to read:

   > This typically means a BIND inside a UNION branch references a variable
   > from a sibling pattern. […] move the source pattern into the UNION branch
   > or use a different query structure.

   which is misleading — it names one cause as though it were the only one, and
   prescribes a UNION-specific remedy for a condition that arises from at least
   two other causes (a filter-only reference inside EXISTS; a variable the
   reference-collector never marked text-needed, so its term join was skipped).
   The new text states the actual consequence — the variable compiles to NULL
   and the enclosing constraint is silently weakened — lists the known causes
   without asserting one, and tells the reader not to trust the results.
3. A docstring warning on `_var_to_sql` pointing here.

A log line is not a fix. It is not surfaced to the caller, an UPDATE still
returns success, and nothing fails.

## Suggested fix

The hard part is not the mechanism, it is deciding when "unresolvable" is an
error rather than a legitimate unbound. Some options, roughly in order of
increasing disruption:

1. **Distinguish the two conditions at the type level.** A variable that is
   in-scope-but-may-be-NULL (OPTIONAL/UNION) is a different state from one that
   is not in the registry at all. Give `_var_to_sql` an explicit
   "legitimately unbound" path and make the not-in-registry path raise.
2. **Fail closed only for updates.** The asymmetry is real: a widened SELECT
   returns wrong rows, a widened DELETE destroys data. Threading an
   "is-update" flag through `EmitContext` and raising only in that case fixes
   the data-loss half without risking working read queries. Weaker, but far
   lower blast radius, and it targets exactly the failure that has actually
   hurt.
3. **Fail closed everywhere**, with an escape hatch for the genuinely-unbound
   cases identified in (1).

Option 2 is probably the right first move.

**Blast-radius warning:** this cannot be applied blind. `_var_to_sql` returning
NULL is currently load-bearing for legitimately-unbound variables, and the
warning is gated on `ctx.query_all_vars`, which is not always populated — so
the true frequency of this condition in passing queries is **unknown**. Before
changing behaviour, instrument first: make the condition always detectable
(populate `query_all_vars` everywhere), run the full suite plus the DAWG
conformance corpus, and count real hits. If the count is zero, failing closed
is nearly free. If it is not, each hit needs classifying before anything raises.

## Measurement — DONE (2026-08-04). The blast radius is known now.

Steps 1–3 of the sequencing plan below have been carried out. Results:

**Instrumentation (step 2).** `ctx.query_all_vars` was populated from
`compute_scope(plan).all_visible` — only what is *visible at the root*, which
excluded exactly the variables most likely to fail to resolve. It now uses a
new `var_scope.all_named_vars(plan)`: every variable named anywhere in the
plan, including BGP slots, VALUES vars, and expression references (which now
reach inside EXISTS patterns). Diagnostics only — nothing branches on it.

**The count (step 3).** Across the full local suite plus DAWG conformance —
**2045 tests** — the diagnostic fires **6 times, in 4 tests**:

| Hits | Variable | Test |
|---|---|---|
| 2 | `?o` | `bind/bind07 - BIND` |
| 2 | `?z` | `functions/COALESCE()` |
| 1 | `?z` | `bind/bind10 - BIND scoping - Variable in filter not in scope` |
| 1 | `?nova` | `bind/bind04 - BIND` |

**All four tests pass, and all six hits are legitimately unbound** — not one is
a translation gap. The W3C corpus documents this in the test material itself:

- `bind10.rq` carries the comment `# ?z is not in-scope at the time of filter
  execution`, and the test's own *name* is "Variable in filter not in scope".
- `bind04.rq` is `BIND(?nova AS ?z)` where `?nova` is bound nowhere; per spec
  BIND of an unbound expression leaves the target unbound.
- `coalesce01.rq` annotates its own cases: `(COALESCE(?z, -3) AS ?def)
  # always unbound -> -3`. NULL is the mechanism that makes COALESCE work.

### What this settles

1. **Option 3 (fail closed everywhere) is wrong.** It would break four
   currently-passing W3C conformance tests, every one of them correct. The
   `NULL` return is not a wart to be removed; for these cases it is the
   specified behaviour.
2. **Option 1 (distinguish the two conditions) is mandatory, not optional.**
   Since every measured hit is a legitimate unbound, any fix must separate
   "in-scope but unbound at runtime" from "the translator could not resolve
   this" before it can raise on either.
3. **Option 2 (fail closed for updates only) has a measured blast radius of
   zero.** None of the 6 hits occur in an update — the 95 DAWG update
   conformance tests produce no hits at all. This is now the recommended first
   move, on evidence rather than on the earlier guess.

### Caveat on the measurement

Six hits means the *known corpus* contains no translation gaps — not that none
exist. The corpus does not cover every construct (SERVICE and CONSTRUCT/DESCRIBE
are absent or unimplemented; see issue 025), and the two translation gaps we do
know about (issues 023, 027) were both found by hand-written tests, not by DAWG.
Treat 6 as "the safe cases are rare and enumerable", which is what makes option
1 tractable — not as proof that the failure mode is theoretical.

## Sequencing — do issue 023's DAWG wiring first

*(Steps 1–3 below are now DONE — see "Measurement" above. Retained for the
reasoning, and because step 4 remains.)*

Do not start with the behaviour change. The first step is instrumentation, and
that step **overlaps almost entirely with an item already open on issue 023**,
so doing 023 first gives this issue its evidence base for free.

The dependency: deciding whether to fail closed requires knowing how often the
unresolved-variable condition fires in queries that currently pass. Measuring
that requires two things —

1. `ctx.query_all_vars` populated everywhere, so the condition is always
   *detectable* rather than silently skipped (today it is only sometimes set,
   which is why the true frequency is unknown); and
2. a corpus broad enough for the count to mean anything.

The existing pytest suites are not that corpus. The DAWG conformance suite is —
and wiring it up is exactly item 1 of
`issues/023_values_clause_ignored_in_sparql_update.md`'s "Still open: the
structural coverage gap": teach `dawg_manifest_parser.py` the
`mf:UpdateEvaluationTest` type and add a pytest module driving the existing
`dawg_update_test.py` runner over `UPDATE_CATEGORIES`. Adding `bindings` to
`P0_CATEGORIES` (023's item 2) widens it further on the query side.

Recommended order:

1. **023's DAWG wiring** — closes 023's coverage gap on its own merits, and
   incidentally produces the corpus this issue needs.
2. **Populate `query_all_vars` everywhere** — pure instrumentation, no
   behaviour change, no risk.
3. **Count hits** across the full suite + DAWG. This is the decision point:
   zero hits means failing closed is nearly free; non-zero means each hit gets
   classified as "legitimately unbound" or "translation gap" before anything
   raises.
4. **Then** pick among the options above, informed by (3) rather than by
   guesswork.

Steps 1–3 are all safe and independently valuable. Only step 4 can break a
working query, and by then it is an informed change rather than a blind one.

## The fix as applied (step 4)

### What the evidence ruled out

Before implementing, one more thing was checked against the running backend:
whether a legitimately-unbound variable is *safe* in every context, or only in
positive ones. It looked like negation might be the discriminator — `NULL`
narrows under a plain FILTER but widens under `NOT EXISTS`/`MINUS`, and
widening is what destroys data.

It is not the discriminator. Measured, with `?nova` bound nowhere:

| Query | Result | Spec |
|---|---|---|
| `?s ?p ?o . FILTER(?nova = ?o)` | `{}` | correct — filter errors, excludes all |
| `?s ?p ?o . FILTER NOT EXISTS { … FILTER(?nova = ?o2) }` | all 4 | correct — inner genuinely has no solutions |
| `?s ?p ?o . MINUS { … FILTER(?nova = ?o3) }` | all 4 | correct — same |

So widening under negation is *right* when the variable is genuinely unbound.
Every simple rule — fail closed everywhere, fail closed in updates, fail closed
under negation — would reject or corrupt spec-correct queries. The only sound
discriminator remains scope analysis (option 1), which needs scope threaded
into the emit context and is not a small change.

### What was implemented instead: mark, then decide

The root problem is stated most precisely as a *missing distinction*, not a
missing check: `_var_to_sql` returned a bare `"NULL"`, indistinguishable from
every other NULL in the generated SQL. **That is why issues 023 and 027 left no
trace.** The codebase already had conventions for exactly this and none were
being used:

| Existing convention | What it does |
|---|---|
| `collect._const_subquery` → `__CONST_c_0__` | constant embedded as a token, resolved later; `prune_union` treats a *surviving* token as "matches 0 rows" |
| `EmitContext.add_deferred_uuid` / `pop_deferred_uuids` | variable not yet in the TypeRegistry — emit a placeholder, resolve after child emission |
| `emit_group._is_null_placeholder` | **the closest analogue**: the same out-of-scope-variable situation, but it marks the `ColumnInfo` so `_qualify_agg_inner` can emit NULL *deliberately* rather than by accident |

So the emitter now **marks** and the generator **decides**:

- `EmitContext.add_unresolved_var(var)` / `.unresolved_vars` — same shape as
  the existing `_deferred_uuids` / `_vector_requests` / `_fuzzy_requests`
  lists, and shared into child contexts by `child()` so marks from EXISTS
  bodies and UNION branches reach the parent. Without that sharing the check
  would see nothing — which is precisely how 027 stayed invisible.
- `emit_expressions.unresolved_var_sql(var)` — the emitted SQL. The **value**
  is still `NULL`, because that is the specified result for a legitimately
  unbound variable and the emitter cannot tell the cases apart. What is new is
  that the NULL is self-identifying:

  ```sql
  NULL /* vg:unresolved-var ?s */
  ```

  This matters because generated SQL **is logged**
  (`sparql_sql_space_impl.py`, `"Generated SQL [%s]"`), so it outlives the
  EmitContext. Someone debugging a wrong-result report from a log has the SQL
  and nothing else, and a bare `NULL` there is indistinguishable from the many
  legitimate NULL companion columns — a large part of why 023 and 027 went
  unnoticed. The comment is inert to Postgres (verified: annotated SQL executes
  cleanly) and the `vg:` prefix keeps it greppable without colliding with
  ordinary SQL text.
- `ctx.log("expr", ...)` — also recorded in the ProcessingTrace, where every
  other emitter logs its decisions, so a trace dump shows *where in the plan*
  it happened. The flat context list cannot convey that.
- Marking is unconditional, so all of the above exists in production too, not
  only under test.
- `generator._check_unresolved_vars` + `set_strict_unresolved_vars(bool)` —
  policy applied after emission, where the whole query has been seen. Default
  `False`; the docstring carries the full reasoning, including why the cheap
  discriminators fail, so the next reader does not rediscover it.
- `tests/conftest.py` enables strict mode per test via `pytest_runtest_setup`,
  except `_STRICT_UNRESOLVED_ALLOWLIST` — the four DAWG tests where the
  variable is legitimately unbound, each entry carrying its reason (in every
  case the W3C material documents it in its own comment or name).
- The error message names both possibilities and says what to do: allowlist
  *with a reason* if genuinely unbound, otherwise fix the wiring. Without that
  the allowlist becomes a dumping ground. It now also lists every unresolved
  variable in the query at once, rather than failing at the first.

Deciding after emission rather than at the point of use is what makes a real
fix possible later: the scope analysis that would finally separate the two
cases plugs into `_check_unresolved_vars` without touching the emitters.

### Verification

- `tests/unit/sparql_sql/test_strict_unresolved_vars.py` — 15 tests split
  along the same seam as the design: `TestMarking` (the emitter records,
  unconditionally, including from child contexts) and `TestPolicy` (the
  generator decides). Plus: the emitted SQL is still `NULL`, resolvable
  variables are not recorded, and the module default is asserted to be `False`
  so production cannot inherit the suite's strictness by accident.
- **The allowlist is load-bearing, not decorative**: removing the `COALESCE()`
  entry was confirmed to fail that test with `UnresolvedVariableError`.
- One defect found by these tests during the rework: `_check_unresolved_vars`
  raised on an empty list. The caller guards, so it was unreachable — but a
  policy function that raises when nothing is wrong is a trap for the next
  caller. Fixed.
- The in-SQL marker was verified end-to-end, not just in unit tests: a query
  with a genuinely unbound variable was compiled and the resulting SQL executed
  against PostgreSQL. The marker is present, names the variable, and the
  statement runs cleanly.
- No generated-SQL cache exists anywhere in the codebase (`compile_cache`
  caches sidecar *algebra*, not SQL), so `generate_sql` runs on every query and
  the marks cannot be bypassed by a cache hit. Checked explicitly — a cache
  there would have been a silent hole in the ratchet.
- Full suite: 2062 passed / 61 skipped / 36 xfailed; `tests/api` 502 passed
  against a rebuilt stack. Production behaviour is unchanged by construction —
  the value is still NULL, the annotation is a comment, and the policy default
  is off.

*Unrelated flake seen once during this work:* five
`tests/api/test_kgtypes_api.py::TestKGTypeSearch` vector/hybrid-search tests
failed on one full-suite run and passed both in isolation (21/21) and on an
immediate re-run (502/502). Order- or timing-dependent, not caused by this
change. Recorded here so it is not mistaken for a regression if it recurs.

### What would close this issue

**Blocked on `issues/030_sql_null_overloaded_across_distinct_meanings.md`.**

This issue is one instance of a larger defect: SQL `NULL` carries at least six
distinct meanings in the generator, and every consumer re-infers which one it
is. The specific discrimination this issue is stuck on — "legitimately unbound"
vs "the translator could not resolve it" — is exactly `NullKind.UNBOUND` vs
`NullKind.UNRESOLVED` in 030's vocabulary. Once producers stamp the kind, the
question is answerable by lookup instead of by scope analysis.

Concretely, 030 step 10 is what closes this: with `null_kind` populated, strict
mode may become safe to enable in production for the `UNRESOLVED` case only,
and the allowlist should shrink to the genuinely-out-of-scope entries.

The marking layer added here is the right seam and survives — `ctx.unresolved_vars`
becomes a query over `null_kind == UNRESOLVED` rather than a parallel list
(030 step 8).

The ratchet buys time; it does not remove the need. Until then, every entry
added to the allowlist is a claim that deserves scrutiny.

## Regression test to add

- A translation-level test that an unresolvable variable in an update's WHERE
  raises rather than emitting `NULL` (once the behaviour is decided).
- A test that a *legitimately* unbound variable — OPTIONAL that did not match —
  still compares as unbound and does not raise. This is the one that makes the
  fix safe, and the one most likely to be forgotten.
- Instrumentation counting how often the warning fires across the existing
  suites, as the evidence base for choosing among the options above.

## Related

- `issues/023_values_clause_ignored_in_sparql_update.md` — NOT FIXED (its
  translation defect is fixed; its coverage gap is not). Two connections:
  it adopted fail-closed for syntax elements and the same reasoning was never
  carried over to the expression layer; and its open DAWG-wiring item is a
  prerequisite for this one — see "Sequencing" above.
- `issues/026_minus_ignored_when_shared_var_has_no_term_uuid.md` — FIXED.
- `issues/027_exists_loses_correlation_for_filter_only_outer_vars.md` — FIXED.
  The interim diagnostics described above were made while fixing it.
