# `MIN`/`MAX` compare RDF terms as text, and `AVG` over a non-numeric term crashes the query

## Status: FIXED (2026-08-04) — and the performance trade MEASURED 2026-08-12

The sort-per-group this fix introduced was carried as an unmeasured risk in
`scaling_implementation_plan.md` for eight days: *"until it runs we do not know
whether that needs fixing at all"*. It has now run. **It does not need fixing.**

    sp_lead_synth_100k, one group            MIN     AVG   MIN/AVG
    Integer      400,000 values              825     365     2.26x
    Double       437,000 values            1,273     417     3.05x
    Currency     155,000 values              384     233     1.65x
    Text       1,050,000 values            2,487       —         —

    4 groups x ~100,000                    2,198   1,293     1.70x
    400,000 groups x 1 row                 2,385   2,569     0.93x

The overhead is bounded at ~2-3x, and it SHRINKS as groups shrink — at one row
per group there is nothing to sort and `MIN` is no slower than `AVG`.

**The specific cliff the plan warned about is not there.** It flagged
`external merge` as "where a constant factor becomes a cliff". Forced by
lowering `work_mem` until the sort spills:

    64MB    quicksort         876 ms
    16MB    quicksort         877 ms
     4MB    external merge    897 ms
     1MB    external merge    800 ms

Spilling to disk is within noise. The concern was reasonable and is not real.

**`AVG`/`SUM` over non-numeric text return UNBOUND and do not crash**, which is
this issue's other half still holding — that failure used to kill the whole
query, not just the aggregate.

Gated by `tests/performance/test_aggregate_growth.py`, which asserts the
MIN/AVG RATIO rather than timings, because the ratio is the sort-per-group cost
and it is what a regression in `sparql_order_key` would move.

All four DAWG tests pass and their `XFAIL_SQL_V2_EXEC` entries are removed, so
`XFAIL_SQL_V2_EXEC` is now empty.

### Fix

**`MIN`/`MAX` select a term by SPARQL ordering, not by text.**
`emit_group.sparql_order_key` builds an ORDER BY reproducing §15.1 — blank
nodes < IRIs < literals, numerics compared numerically via the `__num`
companion, non-numerics after them — and `_ordered_pick` takes the winning row
with `(array_agg(col ORDER BY key))[1]`.

Every companion is picked with the *same* ordering, so the returned term keeps
its own datatype rather than the constant `_agg_datatype` fallback. That
mattered more than the DAWG tests could show: the result comparator normalises
numeric literals through `Decimal.normalize()` and collapses their datatype to
`__NUMERIC__`, so a wrong-but-numeric datatype would have passed. Verified
directly instead — `MAX` over `{1, 2.2, 3.5, 1.0E2, 3.0E4}` now returns
`3.0E4` typed `xsd:double` (previously `3.5`, typed `xsd:integer`), and `MIN`
returns `1` typed `xsd:integer`. Strings still order lexicographically.

**`AVG` no longer aborts the query.** The real shape of `agg-err-01` is
`((MIN(?p) + MAX(?p)) / 2 AS ?c)`, not a bare `AVG` — this issue originally
described it as an AVG cast. `MIN`/`MAX` had no `num_col`, so `_numeric_arg`
fell back to `CAST(<text> AS NUMERIC)`; with a blank node in the group the
lexicographic max was `b2` and Postgres raised
`invalid input syntax for type numeric: "b2"`, killing the whole query rather
than yielding an unbound aggregate.

`MIN`/`MAX` now expose a guarded `__num` lane —
`CASE WHEN COUNT(*) != COUNT(x__num) THEN NULL ELSE MIN/MAX(x__num) END` — so a
numeric use of an aggregate over a group containing a non-numeric is a type
error (unbound), per §18.5.1, and the query completes.

### Performance note

`array_agg(... ORDER BY ...)` sorts each group, where the old `MIN`/`MAX`
streamed. For MIN/MAX over large groups this is a real cost. It is the standard
idiom — Postgres has no `arg_max`, and returning the whole term requires
picking a row — but if aggregate-heavy queries over large groups matter, this
is the place to measure. Nothing in the current suites is large enough to show
it.

Two costs, not one:

- **CPU** — a full sort per group to obtain a single row. `array_agg` has no
  top-N shortcut; it sorts everything and then discards all but `[1]`.
- **Memory** — every input row of every group is materialised in the aggregate
  state before the pick. Peak footprint scales with the *input* size, not the
  group count, so a wide `MIN` over a large space can spill to disk
  (`Sort Method: external merge`) where the streaming version used O(1) state.

And it is currently paid **four times per `MIN`/`MAX`**: `_aggregate_to_sql`
emits one `_ordered_pick` for the value (`emit_group.py:318`) and
`emit_group.py:168` emits three more for `__type`, `__lang`, `__datatype`.
Postgres shares aggregate transition state only across *identical* `Aggref`
nodes; these four differ in their input expression, so they are four
independent sorts over the same rows under the same key.

### Mitigations

Roughly in increasing order of effort. (1) and (2) are strictly mechanical and
should come first; (3) and (4) are the ones that remove the sort rather than
shrink it.

**1. Collapse the four picks into one.** Aggregate the companions together with
the value under a single ordering, then project the fields out. This is a
straight 4× reduction in sort work for zero semantic change — and it also makes
the "all companions come from the winning row" invariant structural rather than
something four separate `ORDER BY` clauses have to agree on.

Two encodings, both awkward in their own way:

- `text[]` — `(array_agg(ARRAY[col::text, col__type::text, col__lang,
  col__datatype] ORDER BY key))[1]`, with fields read back by subscript. No DDL,
  but every lane goes through text and `array_agg` over arrays yields a 2-D
  array, so the subscripting is fiddly.
- A **named composite type** — `array_agg(ROW(...)::sparql_term ORDER BY key)`,
  fields read as `(pick).datatype`. Cleaner and keeps native types, but field
  selection on an anonymous `record` is a hard error in Postgres
  (`could not identify column ... in record data type`), so the type must exist
  in the schema. Per [[schema-created-by-scripts-only]] that means an explicit
  create-space/migration step, not an implicit `CREATE TYPE IF NOT EXISTS`.

Either way the four `agg_select` entries become field extractions over one
aggregate. Repeating the identical aggregate subexpression per field is fine —
identical `Aggref` nodes *are* shared — but confirm with `EXPLAIN` that only one
sort appears rather than assuming it.

**2. Make the sort key cheaper.** `sparql_order_key` sorts on
`(CASE type-rank, __num, text)`. The text tiebreaker is the expensive column:
under a non-C collation it is `strcoll`, not `memcmp`. The docstring already
states that ordering among mutually incomparable literals is
implementation-defined, so pinning that column to `COLLATE "C"` is
spec-legal and materially faster. The local cluster is C-locale already
([[local-postgres-cluster-facts]]) so this shows up only where the deployment
isn't — make it explicit rather than depending on the cluster's default. Also
consider whether the text tiebreaker is needed at all once the type rank and
`__num` have been compared; it exists for determinism, and a cheaper stable
tiebreaker (e.g. the term uuid) may serve.

**3. Feed presorted input.** PostgreSQL 16 added the ability for aggregates
with `ORDER BY` to consume presorted input instead of sorting internally. If
the child subquery is emitted with `ORDER BY <group cols>, <order key>` and the
plan is a `GroupAggregate`, the per-group sorts disappear entirely — and with
(1) applied there is a single ordering for all lanes to match, which is what
makes this reachable. Best case the ordering comes from an index and the sort
is skipped altogether; worst case it is one sort of the input instead of four
per group. **Verify the version floor and that the planner actually takes the
path** before relying on it; and check it does not pessimise `HashAggregate`
plans that are currently fine.

**4. Replace the pick with a streaming aggregate.** The real fix. Two routes:

- **`DISTINCT ON` rewrite.** When a group node's only aggregates are `MIN`/`MAX`
  over a single variable, the whole thing is expressible as
  `SELECT DISTINCT ON (group cols) group cols, val, val__type, ... ORDER BY
  group cols, <key>` — one sort for the entire query, index-usable, no
  per-group state. Narrow but it covers the common
  `SELECT ?g (MIN(?o) AS ?m) ... GROUP BY ?g` shape.
- **A custom aggregate.** A user-defined `sparql_min`/`sparql_max` whose
  transition function keeps only the running best row is O(n) time and O(1)
  memory, with no sort and no materialisation — exactly the streaming behaviour
  the old code had, with correct ordering. Costs a schema object (same
  create-script constraint as the composite type above) and, if written in
  PL/pgSQL, per-row call overhead that may eat the win; C would not, at the cost
  of an extension to deploy.

**5. Skip the pick when the term never escapes.** If the aggregate's result is
consumed only numerically — arithmetic, comparison, `HAVING` — the guarded
`__num` lane already carries the answer via a plain streaming `MIN(__num)`, and
the datatype/lang/text lanes are computed and thrown away. Emitting the ordered
picks only when the whole RDF term can reach the result set would remove the
cost outright for that class of query. Requires knowing at emit time whether the
aggregate variable is projected or only used in expressions; worth doing only if
measurement shows those queries matter.

### Measuring it

Nothing in the suites is large enough to show any of this, so the first step is
a case that does. Build a space with a large `MIN`/`MAX` group — high input
cardinality per group is what matters, not group count — and compare
`EXPLAIN (ANALYZE, BUFFERS)` before and after. What to look for:

- how many `Sort` nodes appear under the aggregate (expect 4 today);
- `Sort Method` — `quicksort` with a memory figure vs `external merge` with a
  disk figure, which is the work_mem spill;
- `GroupAggregate` vs `HashAggregate`, since (3) only helps the former.

Compare against the pre-fix streaming `MIN`/`MAX` to size the regression
honestly — the question is not whether the sort costs something, but whether it
costs enough to justify a schema object.

### Nailing it down: a SQL-level bakeoff test

The mitigations above rest on two claims I could not verify by reading code —
whether Postgres shares the repeated identical `Aggref` in (1), and whether the
PG16 presorted-aggregate path actually triggers for (3). Both are answerable
only by asking Postgres. Rather than reason further, write tests that execute
the candidate SQL directly and let the plans decide.

**Exercise raw SQL, not the SPARQL pipeline.** The question is which SQL
formulation Postgres executes best; routing through parse → plan → emit adds
variance and makes it impossible to vary one formulation at a time. Build the
fixture table directly in the shape `emit_group` sees — a text lane plus
`__num`, `__type`, `__lang`, `__datatype` companions — and hand-write each
candidate. The emitter changes only after a winner exists.

**Home:** `tests/performance/test_minmax_agg_bakeoff.py`, on the existing
harness — `perf_pool` / `skip_no_pg` from `tests/performance/conftest.py`,
`explain_json` / `node_types` / `temp_written_blocks` from
`tests/performance/harness.py`. Mark it `slow`; it is a decision instrument, not
a per-commit gate. `node_types` gives the Sort-node count; extracting
`Sort Method` and `Peak Memory Usage` per node needs a small helper alongside
`temp_written_blocks`.

**Correctness gate before any timing.** A faster formulation that picks a
different row is worthless, and three of the candidates change how the winning
row is chosen. Every candidate must return results identical to the current
implementation — value *and* all three companions — across the fixture matrix,
as a hard assertion that runs first. Include the cases the DAWG tests cover and
the ones they don't: mixed numeric lexical forms (`3.5` vs `3.0E4`), a blank
node in the group, all-IRI groups, all-string groups, single-row groups, groups
where `__num` is entirely NULL, and ties on the full key. Case (2) is the one to
watch — `COLLATE "C"` changes the tiebreak order for incomparable literals, so
assert it stays *deterministic and documented*, not that it matches the default
collation's order.

**Candidates**, each as its own SQL string over the same fixture:

- `current` — four `array_agg(... ORDER BY key)[1]` calls, the baseline.
- `streaming_minmax` — the pre-fix plain `MIN`/`MAX`. Wrong answers; included
  only as the floor, to size what the fix cost.
- `single_pick_textarray` and `single_pick_composite` — mitigation (1), both
  encodings. Their plans answer the `Aggref`-sharing question directly: assert
  exactly one Sort node under the aggregate.
- `collate_c` — mitigation (2), layered on the winner of (1).
- `presorted` — mitigation (3): child wrapped with a matching `ORDER BY`. Assert
  whether the per-group Sort disappears and whether the plan is still
  `GroupAggregate`; if the planner picks `HashAggregate` instead and the sort
  stays, that is the answer and (3) is dead.
- `distinct_on` — mitigation (4a). Only valid for the single-variable shape, so
  it needs its own correctness fixture, but it is the cheap end of "remove the
  sort".
- `custom_agg` — mitigation (4b), PL/pgSQL first. If PL/pgSQL per-row overhead
  eats the win at realistic group sizes, that kills the C-extension option too
  without anyone building it. Create and drop the aggregate inside the test's
  own fixture — this is a benchmark artifact, not schema
  ([[schema-created-by-scripts-only]]).

**Matrix.** Rows *per group* is the driver, since that is what the sort scales
with — sweep it (1, 10, 1K, 100K) at a fixed group count, then vary group count
independently to separate per-group overhead from total work. Cross with type
mix (all-numeric / mixed / all-non-numeric) because the type rank and the NULL
`__num` lane change the key's selectivity. Pin `work_mem` explicitly per session
so the spill threshold is deterministic rather than inherited from whichever
cluster runs the test, and run one configuration at a small `work_mem` on
purpose to confirm the materialisation cost is real.

**Assert plan shape, report wall-clock.** Per the harness philosophy in
`planning/planning_performance/scaling_test_strategy.md` §3: assert on the
size-independent, deterministic facts — Sort node count, `Sort Method`
(`quicksort` vs `external merge`), `Temp Written Blocks`, aggregate strategy —
and *report* timings in the test output as a comparison table without asserting
on them. Timing assertions on a shared local cluster are flake.

**What the test decides.** It should end with an unambiguous answer to: does (1)
collapse four sorts to one; does (3) fire on this PG version; and does the
streaming aggregate in (4) beat the collapsed sort by enough to justify a schema
object. Record the numbers in this issue. Once a winner is chosen, the bakeoff
stays as documentation of *why*, and the emitter gets one narrow regression test
asserting the plan shape of the SQL it now produces — the DAWG tests already
cover the semantics, so the regression risk being guarded is silently falling
back to four sorts.

Also worth capturing: the local cluster is C-locale and PG 18.4
([[local-postgres-cluster-facts]]), so it is the best case for (2) and has (3)
available. If deployment targets differ in version or collation, the bakeoff
result does not transfer — note the cluster version and `lc_collate` in the test
output so a future reader knows what was measured.

### Verification

- The four DAWG tests (`aggregates/MAX`, `MAX with GROUP BY`,
  `MIN with GROUP BY`, `Error in AVG`) pass with their xfails removed.
- Datatype correctness probed directly against the backend, since the
  comparator cannot see it.
- 2102 local tests, 507 `tests/api` against a rebuilt stack.

The two remaining `aggregates` failures are the pre-existing
`XFAIL_TESTS_V2` GROUP_CONCAT entries, where pyoxigraph itself differs from the
manifest — oracle limitations, not our defects.

## Severity

**Wrong results, silently** (`MIN`/`MAX`) and a **hard query failure** (`AVG`).

Read-path only — no data-loss risk. But `MIN`/`MAX` returning a plausible wrong
answer is the more dangerous of the two, because nothing signals it.

## Summary

Four W3C DAWG aggregate tests fail against the SQL backend. In every case
pyoxigraph agrees with the manifest's expected `.srx` and the SQL pipeline does
not, so these are our defects rather than oracle disagreements.

| DAWG test | Symptom |
|---|---|
| `aggregates/MAX` | wrong extremum |
| `aggregates/MAX with GROUP BY` | wrong extremum per group |
| `aggregates/MIN with GROUP BY` | wrong extremum per group |
| `aggregates/Error in AVG` | query aborts with a Postgres cast error |

## How they were found

They were not found by anyone reading the code. `tests/conformance/test_dawg_sql_v2.py`
ran only the pyoxigraph oracle and never executed the SQL pipeline, despite its
name, docstring, `sql_v2` marker and PostgreSQL+sidecar gate. Wiring it to
actually execute (2026-08-04, issue 023's coverage work) surfaced these on the
first real run.

They are currently `xfail`ed with reasons in `XFAIL_SQL_V2_EXEC` — visible and
still collected, not excluded. Removing an entry must make its test pass.

## Root cause — `MIN`/`MAX`

`_qualify_agg_inner` (`vitalgraph/db/sparql_sql/emit_group.py:292`) feeds the
**text** column to `MIN`/`MAX`:

```python
if agg_name in ("MIN", "MAX"):
    # Use text column — __num is NULL for URIs/strings, which would
    # make the error guard evaluate to NULL and destroy sort order.
    # Text comparison is correct for SPARQL MIN/MAX on all RDF types.
    return f"{src_alias}.{info.sql_name}"
```

The last line of that comment is false. Text comparison is lexicographic, so
over the test data

```turtle
:ints    :int    1, 2, 3 .
:decimals :dec   1.0, 2.2, 3.5 .
:doubles :double 1.0E2, 2.0E3, 3.0E4 .
```

`MAX(?o)` compares `"3.5"` against `"3.0E4"` as strings and picks `"3.5"`.
The correct answer is `3E+4` — thirty thousand.

SPARQL 1.1 §18.5.1 defines `MIN`/`MAX` by the `ORDER BY` ordering, which
compares numeric literals **numerically** regardless of their lexical form, and
orders across type groups (unbound < blank node < IRI < literal). Lexicographic
text ordering coincides with that only by accident.

The comment's stated concern is real — `__num` is NULL for non-numeric terms —
so the fix cannot simply switch to `__num` either. It needs a sort key that
orders numerics numerically and falls back to text (or type-group rank) for
everything else, e.g. ordering on `(type_rank, __num, text)` rather than on any
single column.

## Root cause — `AVG`

`Error in AVG` runs `AVG(?o)` over a group containing a blank node:

```turtle
:y :p 1, _:b2, 3, 4 .
```

and fails with:

```
invalid input syntax for type numeric: "b2"
```

so a text value is reaching a numeric cast. `emit_group.py:239-247` builds an
error guard intended for exactly this case —

```python
if agg_name in ("AVG", "SUM", "MIN", "MAX") and isinstance(expr.expr, ExprVar):
    ... CASE WHEN COUNT(*) != COUNT({inner_sql}) THEN NULL ELSE ...
```

— but a guard cannot help here: SQL evaluates the `CASE` arms over the same
rows, so `AVG(...)` still sees the offending value. The likely path is
`_qualify_agg_inner`'s fallback `CAST({sql_name} AS NUMERIC)` when `num_col` is
absent (`emit_group.py:288-290`); confirm before fixing.

Per SPARQL §18.5.1.4 an `AVG` over a non-numeric term yields a **type error**
for that aggregate — the solution is unbound — it does not abort the query.
The fix is to make the cast total (e.g. cast only rows that match a numeric
pattern, or use the `__num` companion which is already NULL for non-numerics)
rather than to guard around a cast that still executes.

## Suggested fix

1. `MIN`/`MAX`: order on a composite key that respects SPARQL term ordering
   instead of raw text. `__num` already exists and is populated for numeric
   literals; the missing piece is the type-group rank and the fallback.
2. `AVG`/`SUM`: never emit a cast that can raise. Prefer `__num`; where a cast
   is unavoidable, make it conditional on a numeric-literal test so a
   non-numeric row contributes NULL rather than an exception.
3. Delete the corresponding entries from `XFAIL_SQL_V2_EXEC` in
   `tests/conformance/test_dawg_sql_v2.py` — the four DAWG tests are the
   regression tests, no new ones needed.

## Related

- `issues/023_values_clause_ignored_in_sparql_update.md` — the coverage work
  that surfaced these. Its point stands: the bugs existed for as long as the
  conformance suite looked green while testing nothing.
