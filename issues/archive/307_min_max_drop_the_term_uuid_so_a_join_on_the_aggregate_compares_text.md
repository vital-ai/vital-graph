# 307 — MIN / MAX drop the term uuid, so a join on the aggregate compares text

## Status: FIXED, 2026-10-25 — verified on the vg test stack (unit, DAWG conformance, full integration green); archived

## Fix as built (differs from the plan below)

**Identity.** No new flag was needed. Every reader of `from_triple` uses it to mean "`__uuid` is a
real term uuid, NULL exactly when unbound":
- joins and MINUS;
- DISTINCT's and GROUP's deferred term resolution;
- COUNT on the uuid column.

That holds for a grouped MIN/MAX of a term-identity input, whose uuid is picked from the winning
row. `from_triple` also already propagates through JOIN, MINUS and UNION, where
`uuid_materialized` does not (`emit_join.py` output registration). So:

- `emit_group.py`: under GROUP BY, with an input that `has_term_identity()`, `<agg>__uuid` is
  the ordered pick of the input's `__uuid` (same key as the value), and the aggregate is
  registered with `uuid_col` and `from_triple`. An ungrouped MIN/MAX, or one over a computed
  value, is unchanged (`NULL::uuid`, no identity).
- `emit_extend.py`: a variable COPY (`(MAX(?v) AS ?m)` is an EXTEND of the aggregate;
  `BIND(?x AS ?y)`) already copied every companion, `__uuid` included, but registered the copy
  as a fresh BIND value with no identity. It now keeps the source's identity and boundness
  claims (`from_triple`, `uuid_materialized`, `partial`, `text_materialized`). This was the
  second half of the defect: the dashboard's `?computedAt` is such a copy. Any join on a
  `BIND(?x AS ?y)` copy was a text compare too.

**Boundness: a defect that already existed, found by this issue's tests.** An unbound MIN/MAX
joined NOTHING where SPARQL joins EVERYTHING (pyoxigraph 0.5.12 agrees), before and after the
identity fix:
- `var_scope.compute_scope` reported every group key and aggregate as DEFINED. Now a key on a
  maybe-bound variable is maybe; so is a MIN/MAX/SAMPLE unless grouped and over an always-bound
  variable.
- An EXTEND copy now inherits its source's status. Other BIND expressions keep the optimistic
  rule: widening it is separate and measured costly in issue 207.
- `emit_join._all_required` saw no gap in an ungrouped MAX over no rows (one row, `?m` unbound).
  A GROUP whose scope has maybe outputs now counts as one.
- COUNT, SUM, AVG and GROUP_CONCAT keep today's rule.

**Tests.**
- `tests/unit/sparql_sql/test_min_max_keeps_term_identity.py`: 7 cases.
- `tests/integration/test_min_max_join_compares_terms.py`: 7 cases on the vg test stack:
  datatype, tie, the max is still the max, ungrouped over nothing, grouped over an OPTIONAL,
  UNION, BIND copy. Against HEAD before the fix: 4 fail (datatype, tie, OPTIONAL, BIND copy;
  the ungrouped case then did not join on ?m). With the fix: 7 pass.
- `latest_per_deal_by_outcome`: the ON clause is now `j2.v4__uuid = j3.v14__uuid`, a plain
  equijoin. Same 4 rows; 185 → 181 ms (5 interleaved runs).

**Related:** `vitalgraph/db/sparql_sql/emit_group.py` (MIN/MAX companions),
`emit_join.py` (the shared-variable ON clause), `qplan._render_subq` (the planner's
render of the same shape, which joins by uuid), issue 029 (MIN/MAX term ordering),
issue 087 (the text fallback's cost).

## Found

On `latest_per_deal_by_outcome` (UW dashboards), the planner's SQL joins the outer
`?computedAt` to the sub-SELECT's `MAX(?at)` by the term's **uuid**. Today's SQL joins them by
**text**:

    ON CAST(j2.v4 AS TEXT) = CAST(j3.v14 AS TEXT) AND j2.v2__uuid = j3.v10__uuid

The cause is in `emit_group.py`. MIN/MAX pick the winning row's `__type`, `__lang` and
`__datatype` with the SPARQL ordering (`_ordered_pick`), but emit its uuid as a constant
`NULL::uuid AS <agg>__uuid` (and `__bool`, `__dt` as NULL). The aggregate then has no term
identity, so `emit_join` falls through every uuid and typed-lane case to
`CAST(a AS TEXT) = CAST(b AS TEXT)`.

## Why it is wrong

SPARQL join compatibility is RDF-term equality. MIN/MAX return one term of the group (§18.5.1),
so the joined value must be that same term. Comparing text instead:

- **joins terms that differ only in datatype or language:** `"2026-01-01T00:00:00"^^xsd:dateTime`
  joins `"2026-01-01T00:00:00"` (a plain string), or the same text `@en`. This happens whenever
  the outer side holds such a term, with no tie needed;
- **on a tie under the ordering** (same kind, same number or no number, same text, different
  datatype), the winner is arbitrary, and the text compare joins every one of the tied terms;
- **is slow:** no index or hash on term identity, and the text must be decoded on both sides
  first (issue 087 measured the same fallback at 21,790 ms vs 0.3 ms on a VALUES join).

The planner path and today's path return the same rows on the UW data (contract,
2026-10-25: 4/4 rows identical in every column) only because the data has neither case.

## Fix

1. In `emit_group.py`, pick `__uuid` with the same ordered pick as the other companions:
   `(array_agg(g.<v>__uuid ORDER BY <key>))[1] AS <agg>__uuid`. The input variable must have term
   identity (`has_term_identity()`); without it (a computed input) keep `NULL::uuid` and today's
   fallback.
2. Register the aggregate's column with uuid identity in that case, so `emit_join` takes its
   first branch (`__uuid = __uuid`).
3. Leave `__num` as it is: the guarded numeric aggregate (issue 029) is about numeric use of the
   value, not identity. Decide whether `__dt` and `__bool` should come from the pick too (today
   NULL), and check what reads them.
4. Check the other consumers of a MIN/MAX column (ORDER BY, FILTER, HAVING, projection decode)
   behave the same once `__uuid` is set. In particular, the decode must not re-join the term
   table on a uuid that was previously NULL and change the output columns.

## Extent (assessed 2026-10-25)

Small in lines, about 40 plus tests; roughly half a day. The real work is keeping term identity
apart from boundness.

### The direct change (about 15 lines)

- `emit_group.py:181-185`: emit `<agg>__uuid` with `_ordered_pick` over `<input>__uuid`, using
  the same `sparql_order_key` as `__type` / `__lang` / `__datatype`. Do this only when the
  input variable `has_term_identity()`; otherwise keep `NULL::uuid`.
- `sql_type_generation.register_aggregate` (`:513`): set `uuid_col` for that case, so
  `has_term_identity()` (`:196`) is true and `emit_join` (`:240-243`) compares
  `__uuid = __uuid`.

The picked uuid is NULL exactly when the picked value is unbound, because it comes from the same
row as the text. So the readers that use `__uuid` as the boundness column stay correct:
`emit_join._boundness_col` (`:89`), the path seed (`:167`), the EXISTS probe (`:186`) and MINUS
(`emit_minus.py:25`).

### The hard part: one flag currently means two things

`has_term_identity()` is `(from_triple or uuid_materialized) and uuid_col`. But
`uuid_materialized` is ALSO read as "bound on every row":

- `emit_join._always_bound` (`:300-335`) returns True for it, which drops the
  `IS NULL OR` compatibility disjuncts and recovers a hashable equijoin. Issue 052 measured
  more than 120 s against 1.3 s without that.
- `emit_union.py:104-126` passes `uuid_materialized=ti` up from its branches, with `partial`
  as the only guard.

A MIN/MAX result is not always bound: an ungrouped `MAX` over no rows is unbound. Marking it
`uuid_materialized` would claim boundness it doesn't have. A UNION with a MIN/MAX branch would
then inherit that claim, and rows from the other branch would die on `NULL = x` (the bug class
the comments at `emit_union.py:105-122` describe). Marking it `from_triple` is worse: that flag
also drives DISTINCT, GROUP, MINUS and lane selection (issue 026).

So:

1. **An identity-only flag** on `ColumnInfo` (e.g. `term_identity`), read by
   `has_term_identity()` and never by `_always_bound`.
2. **A boundness rule for MIN/MAX:** always bound when there is a GROUP BY and the aggregated
   variable is always bound in the group's input (a required triple, no OPTIONAL or UNION gap).
   Without this the join keeps its `IS NULL OR` disjuncts and cannot be hashed, so the fix would
   make `latest_per_deal_by_outcome` slower, not faster. An ungrouped MIN/MAX is never always bound.
3. **`emit_union` passes up identity and boundness separately:** identity when every binding
   branch has it; `uuid_materialized` only when every branch is always bound.
4. **Audit the 16 `has_term_identity` / `uuid_materialized` reads** (`emit_join` 9,
   `emit_union` 5, `emit_minus` 1, `emit_table` 1). Classify each as identity (gains from the
   fix) or boundness (must read the new rule), and add a lint like `test_null_provenance_lint`
   so new readers pick the right one.

### Visible output change

A projected MIN/MAX's `__uuid` column goes from NULL to the winning term's uuid. The planner's
SQL already returns it (its decode reads the term by uuid), so this makes the two paths agree
column for column. Check the executor's binding decode does not prefer `__uuid` over the
text in a way that changes the binding.

### Related, to check while in there (not verified)

Under MAX, `sparql_order_key` orders text `DESC` with PostgreSQL's default NULLS FIRST. A group
mixing an unbound input row with literals that have no numeric value may therefore pick the
UNBOUND row. That would be an older defect independent of this fix. Check it against Jena's
behaviour (unbound and error values are skipped by MIN/MAX).

## Tests

- A unit or DAWG-style case where the outer side has the same text as the MAX in a different
  datatype: today joins (wrong), fixed does not.
- A tie case: two terms with equal text and different datatypes in one group. Fixed joins exactly
  the picked term.
- An ungrouped `MAX` over no rows stays unbound, and joins as unbound (compatible), not as a
  match on a NULL uuid read as a value.
- A UNION with a MIN/MAX branch and a triple branch, joined to a third pattern: no rows lost
  from either branch.
- A grouped MAX joined to a required triple keeps a plain equijoin (no `IS NULL OR` in the ON
  clause).
- `test_null_provenance_lint` and the DAWG aggregates suite (MIN/MAX, COUNT 8b on a numeric lane)
  unchanged.
- The full vg test stack run: this is the path that runs without the plugin in production.
- `latest_per_deal_by_outcome` on the vg test stack: same rows as before, and the SQL's ON clause
  compares `__uuid`; time it before and after (the text join decodes both sides).
- Planner contract on the same query: today's and the planner's SQL agree, now by construction
  rather than by the data.
