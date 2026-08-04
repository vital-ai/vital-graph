# SQL `NULL` is overloaded across six distinct meanings, and every consumer re-guesses which one it is

## Status: FIXED (2026-08-04) — vocabulary in place, workarounds removed, lint added

All ten steps done. The taxonomy below still stands as documentation of what
NULL means where; what changed is that the two knowable-at-emit-time
distinctions now live on `ColumnInfo` instead of being re-inferred by each
consumer, and the habit that caused issue 026 is now caught by a lint.

**What shipped**

| Step | Change |
|---|---|
| 1 | Audit — overturned the proposed seven-value enum; see "Step 1 findings" |
| 2r–4r | `ColumnInfo.text_materialized`, `has_term_identity()`, populated in `emit_bgp` and propagated through join/minus/union; byte-identical SQL across all 34 plan-tree fixtures |
| 5r | `emit_minus` asks for identity instead of deriving unconditionally; also propagates `from_triple` through the passthrough |
| 6r | `TypeRegistry.deferred_text_companions` — `emit_distinct` no longer asks for "unbound" companions and patches the UUID back |
| 7r | `emit_join._boundness_col` — the explanatory comment became a check |
| 8r | `ColumnInfo.is_unbound` replaces the undeclared `_is_null_placeholder` |
| 9r | Source lint: no emitter may test a `__uuid` column for NULL |
| 10r | Issue 028 corrected — it is *not* unblocked by this work |

**Both workarounds are gone.** `emit_distinct`'s string-patch and
`emit_join`'s comment-as-documentation were the two live instances; each is now
an explicit call against the vocabulary.

**Verification.** 2098 local tests (unit + integration + fixtures +
conformance), 507 `tests/api` against a rebuilt stack. Steps 2r–4r were checked
byte-for-byte on generated SQL. The lint was verified to fail when the exact
issue-026 expression is reintroduced, rather than assumed to work.

**Not done, deliberately:** kinds A (unbound) and F (type error) remain plain
SQL NULL, which is correct — those genuinely are runtime NULLs and SQL's
propagation semantics are what SPARQL requires. Kind B stays `typed_lane`, and
for BGP variables it is row-dependent so it could not be a static field. Kind E
stays with issue 028's context marking, because an unresolved reference has no
`ColumnInfo` to carry a field.

## Severity

**Latent data loss, recurring.** No single live reproduction — this is the
mechanism that *generates* the bugs. Three data-affecting defects (023, 026,
027) and four separate hand-written workarounds all trace to it. It will keep
producing new ones until the meaning is carried explicitly.

## Summary

The SQL generator encodes at least six semantically different conditions as the
same value: SQL `NULL`. The producing emitter knows which one it meant. The
consuming emitter has to re-infer it from a bare `NULL` — and each consumer
guesses differently.

| | Meaning | Produced by | Example |
|---|---|---|---|
| **A** | Genuinely unbound (SPARQL §10.5) | `TypeRegistry.null_companions` (`sql_type_generation.py:546`) — UNION padding, VALUES UNDEF | OPTIONAL did not match |
| **B** | Bound, but this typed lane does not apply | `TypedExpr.produce_companions` (`sql_type_generation.py:263-265`) | `NULL::numeric` for a string value |
| **C** | Bound, value **synthesized**, no term-table identity | `emit_table.py:51,62,71`; `emit_extend` via `sql_type_generation.py:268` | `NULL::uuid` for BIND / VALUES / aggregates |
| **D** | Bound, but **text not materialized** | `emit_bgp` when `text_needed_vars` skips the term JOIN | text column NULL while `__uuid` is set |
| **E** | Reference **unresolvable** by the translator | `emit_expressions._var_to_sql` | out of scope, or a translation gap |
| **F** | Expression produced a **type error** → unbound | `emit_group.py:239-247` aggregate error guard | `AVG` over a non-numeric term |

A and F genuinely *are* NULL at runtime and should stay that way — SQL's NULL
propagation and `IS NULL` are exactly the right semantics for them. B, C, D and
E are not runtime NULLs at all. They are **metadata about how the value was
produced**, smuggled through the value channel.

## Evidence: four independent workarounds, three shipped bugs

This is not speculative. Every one of these is a consumer compensating for a
meaning it could not read directly.

**1. `emit_minus` read C as A — issue 026 (fixed).**
`NULL::uuid` from VALUES/BIND meant "synthesized, no term identity". MINUS read
"unbound", so its domain-intersection test could never be satisfied and the
whole MINUS silently became a no-op. In a guarded DELETE that widened to the
entire graph. Fixed by deriving the identity from the other companions
(`term_identity_expr`) — i.e. by *reconstructing* the metadata that should have
been carried.

**2. `_var_to_sql` produced E, every consumer read A — issues 023 / 027 (fixed).**
An unresolvable reference compiled to a bare `NULL`, indistinguishable from a
legitimate unbound. Under a `NOT EXISTS` guard that dropped the guard entirely
and deleted rows the query was written to protect.

**3. `emit_join` hand-patches D vs A — `emit_join.py:96-98`.**
Written before either issue was filed, and the comment says it outright:

> *"Use `__uuid` for the IS NULL check — the base (text) column may be NULL
> when text_needed_vars skips term JOINs, even though the variable IS bound."*

**4. `emit_distinct` uses the wrong primitive, then undoes it — `emit_distinct.py:171-177`.**
For variables that are D (bound, text deferred) it calls `null_companions()` —
which *means* A — and then string-patches the `__uuid` column back to a real
value:

```python
null_cols = TypeRegistry.null_companions(sn)
# Replace the NULL::uuid placeholder with actual UUID passthrough
for i, c in enumerate(null_cols):
    if c.endswith(f" AS {sn}__uuid"):
        null_cols[i] = f"{r_alias}.{sn}__uuid AS {sn}__uuid"
```

Four emitters, four different coping strategies, no shared vocabulary.

## The one place it is already done right

`emit_group` marks its case instead of emitting a bare NULL:

```python
info = ColumnInfo(sparql_name=var, sql_name=sn, text_col=sn)
info._is_null_placeholder = True      # emit_group.py:106
ctx.types.register(info)
```

and `_qualify_agg_inner` reads the flag (`emit_group.py:281`) to emit NULL
*deliberately*. That is the correct shape. It is also ad-hoc: an undeclared
attribute set via `getattr(..., False)`, documented nowhere, covering one case
out of six, used by one consumer.

Issue 028 added a second instance of the same idea (`ctx.add_unresolved_var`
for case E). Two ad-hoc mechanisms for two of six cases is the argument for
doing this properly rather than a third time.

## Design

**The distinction belongs in `ColumnInfo`, not in the SQL.** Consumers decide
at *emit* time from the type registry; they do not inspect NULLs at runtime.
Changing the emitted SQL value would break A and F, which must stay NULL for
spec compliance.

```python
class NullKind(Enum):
    NONE          = auto()  # bound and fully materialized
    UNBOUND       = auto()  # A — SPARQL §10.5, genuinely unbound
    LANE_NA       = auto()  # B — typed lane not applicable to this value
    SYNTHESIZED   = auto()  # C — value exists, no term-table identity
    TEXT_DEFERRED = auto()  # D — bound, text JOIN skipped
    UNRESOLVED    = auto()  # E — translator could not resolve the reference
    ERROR         = auto()  # F — SPARQL type error, evaluates to unbound
```

`ColumnInfo` carries `null_kind: NullKind = NullKind.NONE`. Note the kinds are
per-*column-lane* in some cases (a variable can be `NONE` for `__uuid` and
`LANE_NA` for `__num`), so the field may need to be per-companion rather than
per-variable — settle that in step 1 below, on the evidence of what the four
consumers actually need.

The prize: a new consumer is correct by default. Today the only way to write a
correct consumer is to know all four workarounds already exist.

---

## Step 1 findings (2026-08-04) — the `NullKind` enum below is the wrong shape

Step 1 said to audit what the four consumers actually branch on before writing
code, and not to guess. Doing that overturned the design. Recording it here;
the original proposal is left below for context, but **do not implement the
seven-value enum**.

### What is already represented

**C (synthesized / no term identity) → `ColumnInfo.from_triple`. Already
exists, and is already correct.**

I initially misread `emit_bgp.py:194` —

```python
has_term = slot.term_ref_id is not None and any(
    t.ref_id == slot.term_ref_id for t in plan.tables)
```

— as "the term table was joined", which would have meant `from_triple` was
conflating C with D. It is not: `term_ref_id` is assigned at *collect* time
(`collect.py:139,287,351`) and reflects plan structure, not whether the JOIN
was emitted. `from_triple` genuinely means "this value came from a triple and
has a term-table identity" — exactly C.

Verified end-to-end: for a query where a shared join variable's term join *is*
deferred (`text_needed_vars = {age, name}`, `?s` excluded), the emitted join
still correlates on `j0.v0__uuid = j1.v2__uuid`, and OPTIONAL/VALUES/plain
joins over that variable all return correct results. `emit_join` is right.

**So issue 026 was not a missing field — it was a consumer ignoring a field
that existed.** `emit_join` and `emit_group` both consult `from_triple`;
`emit_minus` went straight to the raw `__uuid` column. Had it asked
`from_triple`, it would have known VALUES/BIND variables have no term identity.

**B (lane not applicable) → `ColumnInfo.typed_lane`, plus a runtime CASE.**
For BGP variables `typed_lane` is deliberately `None` because the actual type
is row-dependent — `__num` is a `CASE ... END` evaluated per row. B is
therefore not a static per-variable property at all and cannot live in a
per-variable enum. It is already modelled as well as it can be.

**E (unresolved) is characterised by *absence* from the registry.** There is no
`ColumnInfo` to put an enum value on — that is the defining property. Issue
028's context marking is the right representation and should stay.

**A (unbound) and F (type error) are genuine runtime NULLs.** SQL NULL
propagation is the correct semantics. Leave them alone.

### The one real gap

**D (bound, text not materialized) is ambient, not per-column.** It lives in
`ctx.text_needed_vars` and nothing on `ColumnInfo` expresses it. That is why
`emit_distinct.py:171-177` reaches for `TypeRegistry.null_companions()` — the
primitive that *means* A — for variables that are actually D, and then
string-patches the `__uuid` column back. There is no D primitive to reach for.

### Revised conclusion

Six kinds collapse to **one addition and one correction**:

| Kind | Action |
|---|---|
| A, F | none — genuine runtime NULLs |
| B | none — already `typed_lane`; inherently runtime for BGP vars |
| C | none to the model; make `emit_minus` **use** `from_triple` |
| D | **add** a per-variable "is the text materialized" property |
| E | none — issue 028's context marking is correct |

This is far smaller and safer than the enum, and it removes the two workarounds
that actually exist. The taxonomy in this issue remains valuable as
documentation of what NULL means where; it just should not become a field.

## Implementation steps

*(Revised per the step 1 findings above. The original phasing is preserved —
enrichment first, then consumers, then enforcement — but steps 2–4 are now much
narrower.)*

### Phase 1 — represent what is missing (behaviour-preserving)

**Step 2r. Add `text_materialized` to `ColumnInfo`**, defaulting to `True`, and
set it from `ctx.text_needed_vars` where variables are registered
(`emit_bgp`, and the passthrough registrations in `emit_join` / `emit_distinct`
/ `emit_group`). Nothing reads it yet; the suite must be green with byte-
identical generated SQL.

**Step 3r. Add `ColumnInfo.has_term_identity()`** — an accessor expressing what
`from_triple` means for the question consumers actually ask ("can I compare
this by term UUID?"), so the next consumer does not have to know that
`from_triple` is the right field. Still nothing reads it.

**Step 4r. Assert the vocabulary.** Unit tests that `text_materialized` is
`False` exactly when the term join is deferred, and that `has_term_identity()`
is `False` for VALUES/BIND/aggregate outputs and `True` for BGP variables.

### Phase 2 — migrate the consumers

**Step 5r. `emit_minus`** — replace the unconditional `term_identity_expr`
COALESCE with an explicit `has_term_identity()` check, deriving only when
needed. Issue 026's integration tests are the net.

**Step 6r. `emit_distinct`** — request the correct companions for
`text_materialized=False` variables instead of asking for `null_companions()`
and repairing the `__uuid` entry afterwards.

**Step 7r. `emit_join`** — turn the `emit_join.py:96-98` comment into a
`text_materialized` check, so the reason the `__uuid` column is chosen for the
NULL test is expressed rather than explained.

**Step 8r. `emit_group`** — fold `_is_null_placeholder` into whichever
representation survives, so there is one mechanism rather than an undeclared
attribute read via `getattr`.

### Phase 3 — enforcement

**Step 9r.** A lint/assertion test that a consumer cannot infer term identity
by testing a `__uuid` column for NULL directly — the mistake that caused 026.

**Step 10r.** Revisit issue 028. Unchanged in intent, but note that `NullKind.
UNRESOLVED` will not exist; 028's discrimination still needs scope analysis and
is **not** unblocked by this issue. See the correction in 028.

---

## Original proposal (superseded by the step 1 findings above)

Retained because the taxonomy is still the clearest statement of what NULL
means where, and because the reasoning about *why* the distinction belongs in
`ColumnInfo` rather than in the SQL value still holds.

### Superseded implementation steps

Sequenced so that every step is independently verifiable and no step both adds
a mechanism and changes behaviour. Steps 1–4 are the enrichment phase and are
behaviour-preserving by construction; steps 5–8 migrate consumers and remove
the workarounds.

The suite that makes this tractable did not exist before 2026-08-04: 2062 local
tests, 604 DAWG conformance tests that execute real SQL (updates included), and
502 API tests. Use it at every step.

### Phase 1 — introduce the vocabulary (behaviour-preserving)

**Step 1. Decide the granularity.**
Audit what the four consumers (`emit_minus`, `emit_join`, `emit_distinct`,
`emit_group`) actually branch on. Determine whether `null_kind` is one field on
`ColumnInfo` or a per-companion mapping. Do not guess — B is inherently
per-lane, C is per-variable-but-only-affects-`__uuid`. Write the answer into
this issue before writing code.

**Step 2. Add `NullKind` and the `ColumnInfo` field, defaulting to `NONE`.**
Nothing reads it yet. Pure addition; the suite must be green with zero
behavioural diff.

**Step 3. Populate it at every producer.**
`null_companions` → `UNBOUND`. `produce_companions` non-applicable lanes →
`LANE_NA`. `emit_table` / `emit_extend` `__uuid` → `SYNTHESIZED`. `emit_bgp`
deferred-text vars → `TEXT_DEFERRED`. `_var_to_sql` → `UNRESOLVED` (fold in
`ctx.add_unresolved_var` from issue 028). `emit_group`'s aggregate error guard
→ `ERROR`. Still nothing reads it. Still zero behavioural diff.

**Step 4. Assert the vocabulary is populated, not just present.**
Unit tests that each producer stamps the kind it claims. Without this, steps
5–8 build on an assumption. This is also where `_is_null_placeholder` gets
mapped onto the enum (`UNRESOLVED` in the GROUP BY case) so there is one
vocabulary, not two.

*Checkpoint: full suite green, and `git diff` on generated SQL is empty for the
plan-tree fixture corpus.*

### Phase 2 — migrate consumers and delete the workarounds

Each step is one consumer, one commit, verified independently — so a regression
is attributable to a single emitter rather than to "the refactor".

**Step 5. `emit_minus`.**
Replace the `term_identity_expr` COALESCE with an explicit `SYNTHESIZED` check.
Keep `term_identity_expr` as the *derivation* used when the kind says derive —
the mechanism was right, the trigger was a guess. Issue 026's 22 integration
tests are the regression net.

**Step 6. `emit_join`.**
Replace the `left_has_uuid`/`right_has_uuid` heuristic and the
`text_needed_vars` comment at `emit_join.py:96-98` with a `TEXT_DEFERRED`
check. The comment becomes an assertion.

**Step 7. `emit_distinct`.**
Remove the string-patch at `emit_distinct.py:171-177`: request the right
companions for `TEXT_DEFERRED` variables instead of asking for `UNBOUND`
companions and repairing one of them.

**Step 8. `emit_group`.**
Delete `_is_null_placeholder` in favour of `null_kind`, so there is exactly one
mechanism. Fold in issue 028's `ctx.unresolved_vars` marking, which becomes a
query over `null_kind == UNRESOLVED` rather than a parallel list.

### Phase 3 — make the class of bug unreachable

**Step 9. Forbid bare NULL companions.**
Once every producer stamps a kind, a consumer that infers meaning by testing a
column for NULL is a bug by construction. Add a guard — a lint test over the
emitters, or an assertion in `TypeRegistry` — so a new `NULL AS x__uuid`
without a declared kind fails the suite.

**Step 10. Revisit issue 028 with the vocabulary in hand.**
`UNRESOLVED` distinguishes "translator failed" from `UNBOUND` "legitimately
unbound" — which is precisely the discrimination 028 is blocked on. With
`null_kind` populated, 028's strict mode may become safe to enable in
production for the `UNRESOLVED` case only, and its allowlist should shrink to
the genuinely-out-of-scope entries. That is the step that closes 028.

## Verification strategy

- Steps 2–4 must produce **byte-identical generated SQL**. The plan-tree
  fixtures (`tests/fixtures/plan_trees/`) are the check.
- Steps 5–8 each land alone, with the full suite plus a rebuilt test stack
  (`tests/api` — `emit_minus` and `emit_join` are on every query path).
- The DAWG update conformance suite is the one that catches data-affecting
  regressions; it is also the one that did not exist until 2026-08-04, which is
  why this refactor is feasible now and was not before.

## Related

- `issues/023_values_clause_ignored_in_sparql_update.md` — FIXED. Case E.
- `issues/026_minus_ignored_when_shared_var_has_no_term_uuid.md` — FIXED. Case
  C read as A; the fix reconstructs metadata that should have been carried.
- `issues/027_exists_loses_correlation_for_filter_only_outer_vars.md` — FIXED.
  Case E read as A.
- `issues/028_expression_emitters_fail_open_on_unresolved_vars.md` — NOT FIXED,
  and **blocked on this issue**: it needs `UNRESOLVED` separable from
  `UNBOUND`, which is exactly what `NullKind` provides. See step 10.
