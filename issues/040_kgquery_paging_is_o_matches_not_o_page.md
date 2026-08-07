# KGQuery Paging Costs O(total matches), Not O(page)

## Status: RANGE HALF FIXED 2026-08-06 · PAGING HALF CLOSED AS NOT ACHIEVABLE AS FRAMED

**Read this section before implementing anything below it.** The range-comparator
half of this issue is fixed and shipped. The paging half — the title of the
issue — was pursued through three separate approaches, all measured, all dead.
The framing "O(matches) is the pathology, O(page) is the fix" **does not survive
measurement**, and the sections further down still assert it.

### Fixed: range comparators (W2 + W4)

`FILTER(?val >= t)` is now pushed into the BGP as a term-table semi-join
(`filter_pushdown._try_numeric_filter`) and served by a partial expression index
(`idx_{space}_term_num`, 48 kB). On `sp_lead_synth` (10,000 entities, 25-row
page):

| t | matches | before | after | time before → after |
|---|---|---|---|---|
| 99.9 | 16 | 458,924 | **4,391** | 746 ms → **13 ms** |
| 99 | 110 | 458,928 | 8,640 | 695 ms → 19 ms |
| 90 | 1,031 | 458,949 | 49,798 | 999 ms → 54 ms |
| 0 | 10,000 | 458,923 | 449,942 | 754 ms → 1,098 ms |

Range cost per matched row went 28,683 → 274 buffers, and at large match counts
reaches 45.0 — the equality baseline to one decimal place. Caveat recorded
honestly: at `t=0`, where the filter excludes nothing, the push-down is **1.34x
slower** in wall time (725 ms → 975 ms) because the semi-join is pure overhead.
Buffers *improved* slightly there, so a buffer-only gate does not catch it.

### Closed: O(page) paging — three approaches, all measured, all dead

| approach | result |
|---|---|
| **M1** — order by `subject_uuid` instead of URI text | **no effect.** 36,466 buffers before and after, measured twice: with and without a `(context, predicate, object, subject)` index that lets the scan emit in subject order |
| **W1** — anchored semi-join rewrite (`JOIN` → `WHERE EXISTS`) | **no effect, 9% worse.** Implemented as a live-variable pass + `emit_join` support; mark fired, `WHERE EXISTS` reached the SQL, acceptance and DAWG conformance clean. CA 36,466 → 39,715 buffers. Reverted. |
| **W1 + M1 + subject-ordered index together** | **no effect.** Plan still `Sort → Nested Loop rows=908`: the full match set is computed before the sort |
| **Forced driver** — `OFFSET 0` fence to stop the `EXISTS` being pulled up, forcing per-entity probing | **catastrophic.** 31 ms → **>200 s**, cancelled by statement timeout |

**Why O(page) is not reachable here.** There are only two ways to return page 1
of the entities matching criteria C:

- **(a)** compute all matches, sort, take 25 — O(matches), ~40 buffers per match
- **(b)** scan entities in order, probe each, stop at 25 — O(25 / selectivity × probe cost)

(a) is cheap *per match* precisely because it is set-based: `reorder_bgp` picks a
good order and the ten-table frame/slot chain is processed in bulk. (b) cannot
amortize any of that — it re-walks the chain once per candidate, and a single
walk costs far more than the ~40 buffers the bulk plan spends per match. The
measured 4-orders-of-magnitude gap is that difference, not a tuning failure.

So **O(matches) is close to optimal for this query shape**, and the premise of
this issue's title is wrong. PostgreSQL's `rows=1` estimate against 908 actual
is a contributing factor — a planner that believes there is one row never
prefers an early-termination plan — but fixing the estimate would only let it
choose (b), which is measurably worse.

### What is actually left

The extrapolation below (100,000 matches ≈ 3M buffers) still holds. The lever is
**reducing the match set or precomputing the path**, not restructuring paging:

- W2/W4 did exactly this for ranges — 104x by making the predicate selective at
  the leaf.
- `{space}_frame_entity` already exists as a precomputed frame→entity mapping.
  It holds 285,348 rows on `wordnet_frames` and **0 on both lead spaces**, which
  is why it never appears in these plans. Why it is empty for lead-shaped data,
  and whether it can serve the KGQuery frame path, is the most promising open
  direction — and it is a materialization question, not a planner one.

Everything below this section predates these measurements. `M1`, `M2` and the
`W1`/`W3` workstreams in
`planning/planning_performance/kgquery_o_page_paging_generator_plan.md` are kept
for the reasoning, not as a plan of record.

## Original status: OPEN — scaling characteristic, not yet a live failure

A KGQuery frame query with `page_size=25` computes **every matching entity**
before returning the page. `SELECT DISTINCT` + `ORDER BY ?entity` sit above the
join chain, so neither can be satisfied without materialising the full match
set, and the `LIMIT` cannot be pushed past them.

Cost therefore scales with how many entities match the criteria, not with the
size of the page requested. The entity-listing fast path guarantees the
opposite, and is asserted to.

## Measured — `sp_sql_lead_dataset` (270,110 quads, 100 entities)

```
Limit                rows=25
  Unique             rows=25
    Incremental Sort rows=25
      Subquery Scan  rows=33
        Sort         rows=33
          Nested Loop rows=99      ← all 99 matches computed for a 25-row page
```

| Case | comparator | matches | rows through the join | buffers |
|---|---|---|---|---|
| `state_ca` | eq | 13 | — | 440 |
| `mql` | eq | 99 | 99 | 3,022 |
| `high_rated` | **gte** | 73 | **100** | 3,321 |

For the equality cases, 7.6x the matches → 6.9x the buffers: near-linear in
match count. `high_rated` is the exception and is covered below — a range
comparator carries the whole candidate set through the join, so it costs *more*
than `mql` while returning *fewer* rows.

Compare the same logical operation on the entity fast path, which is O(page):

| Path | buffers for a 25-row page | behind it |
|---|---|---|
| `query.fastpath.typed_subject_page` | **481** | 109,745 entities |
| `query.kgquery.generated_sql.plan[mql]` | **3,022** | 99 matches |

The fast path holds 481 buffers *regardless* of how many entities exist. The
KGQuery path is already 6x that for a match set of 99.

## Why it does not look broken today

The plan itself is healthy — this is not an `issues/039`-style pathology:

- every leaf is an Index Only Scan or Index Scan
- `Heap Fetches: 0` throughout
- no node discards rows via a filter
- 10 nested-loop levels × 99 rows × ~3 buffers ≈ the 3,022 observed

Nothing is being wasted. The work is simply proportional to the wrong quantity.

## Why it matters

The lead fixture has 100 entities, so the full match set is trivially small and
the behaviour is invisible. Extrapolating the measured ~30 buffers per matching
entity:

| Matching entities | Projected buffers for page 1 |
|---|---|
| 99 | 3,022 (measured) |
| 10,000 | ~300,000 |
| 100,000 | ~3,000,000 |

At that point a first page of 25 rows reads more of the database than the
entity listing reads for the whole space. The failure mode is a customer-visible
timeout on a *common* query against a large space, not a gradual slowdown — and
it arrives suddenly, when one tenant's data crosses the threshold.

Deep pages are worse again: every page repeats the full computation, so paging
through N matches is O(N²).

## Where it comes from

`vitalgraph/sparql/kg_query_builder.py:310` and the sibling templates emit

```sparql
SELECT DISTINCT ?entity WHERE { ... }
ORDER BY ?entity
LIMIT 25 OFFSET 0
```

`DISTINCT` is needed because the join chain can produce an entity more than once
(multiple frames/slots satisfying the criteria). `ORDER BY` is needed for stable
paging. Both are correct requirements; the problem is that satisfying them the
current way forces full materialisation.

## ⚠️ Mitigations below were measured on probe SQL, not on generated SQL

**Read this before implementing M1 or M2.** Both were measured against
hand-written queries that reproduce the *logical* operation. Neither matches the
shape the generator actually emits, and applying either as written is a no-op.
Verified 2026-08-06 against the real generated SQL for `high_rated` and `mql`:

**M2 does nothing.** The index was built with the generator's exact expression —
not the simplified one in the M2 section, but
`CASE WHEN datatype_id IN (4,11,10,12,3,6,5,19,18,20,21,15,14,16,17,13) AND
term_text ~ '^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$' THEN CAST(term_text AS
NUMERIC) END`, 960 kB. The plan did not change and the buffer count was
identical to the digit: **3,341 before, 3,341 after**, index never referenced.

The reason is structural. The generated plan never scans the term table by
value. `t_v8` is reached by a **primary-key lookup on `term_uuid` inside a
nested loop**, once per candidate row, and `WHERE (v8__num >= 65.0)` is applied
at the *top* of the join chain. There is no range scan for a range index to
serve. The probe query scanned the term table by numeric range — a shape the
generator does not produce.

**M1's ceiling is ~0.7%.** Splitting the plan by buffers:

| Query | join chain | everything above it (Sort + DISTINCT + Unique + Limit) | total |
|---|---|---|---|
| `mql` | 3,002 | **20** | 3,022 |
| `high_rated` | 3,321 | **20** | 3,341 |

Changing the ordering key only touches that 20. The other 99.4% is the join
carrying every candidate through ten nested-loop levels, and reordering does not
make a `LIMIT` terminate it early.

The probe got O(page) because it was a *single* join whose driving index was
already ordered by `subject_uuid`. In the generated plan the driving scan is
`idx_*_quad_ctx_pred` with all three key columns bound to constants — the
residual row order is heap order, not `subject_uuid` order, because
`subject_uuid` sits in `INCLUDE` and `INCLUDE` columns are not sort keys.

### What would actually work

O(page) needs the join to terminate early, which needs two things together:

1. **An ordered driving scan.** Drive from an index whose leading key is
   `subject_uuid` (`idx_*_quad_sp`, or the PK) so rows arrive in the paging
   order and `LIMIT` can stop.
2. **Criteria as semi-joins.** Each frame/slot criterion becomes an `EXISTS`
   rather than a join, so the driver is filtered instead of fanned out — that is
   also what makes `DISTINCT` unnecessary rather than merely cheaper.

For range comparators, additionally push the predicate to the leaf so the slot
value is an index condition rather than a post-join filter — the value is
already available as `v0__num` in the projection. Only *then* does an M2-style
expression index have a scan to serve; on its own it has nothing to attach to.

All three are generator changes (`emit_bgp` / `emit_join` / `filter_pushdown`),
not schema or builder changes. That is a materially larger piece of work than
the mitigation sections below imply.

## Mitigations — measured on probe SQL (see the warning above)

Both were tested on `sp_sql_lead_dataset`. Neither is applied, and neither
transfers to the generated query as written.

### M1. Two-phase paging: order by `subject_uuid`, not by entity URI text

Page the matching subject UUIDs from an index first, then resolve the page's
text in a second step. Because `subject_uuid` is index-ordered, `DISTINCT` and
`ORDER BY` are satisfied by the index and the `LIMIT` stops the scan early —
the join never fans out over the full match set.

Measured against a 4,170-match slot filter, both returning the same 25 rows:

| | Buffers | What the plan does |
|---|---|---|
| **A — current shape** (`DISTINCT` + `ORDER BY term_text`) | **918** | HashAggregate over all 4,170 matches, then Sort, then Limit. Also **Seq Scan on the term table** (42,801 rows) to hash for the join |
| **B — two-phase** (`ORDER BY subject_uuid`, then resolve) | **117** | `Unique` over an Index Scan stopping at **25 rows**, then 25 PK lookups |

**7.8x fewer buffers, and the shape changes from O(matches) to O(page)** — plan B
reads 25 index rows regardless of whether 4,170 or 4,000,000 match. That is the
property `query.fastpath.typed_subject_page` already guarantees for entity
listings.

Cost: ordering becomes UUID order rather than alphabetical by URI. If
alphabetical ordering is a product requirement the sort cannot be avoided this
way, and the fix has to be an index supporting the required order instead.
Worth checking what callers actually rely on — the entity fast path pages by
`subject_uuid` for exactly this reason.

### M2. Partial expression index for range comparators

The `gte` problem above is that `CAST(term_text AS numeric)` is not indexable,
so the filter can only run after the join. A **partial expression index** makes
it indexable:

```sql
CREATE INDEX idx_{space}_term_numval
  ON {space}_term ((CAST(term_text AS numeric)))
  WHERE term_text ~ '^[0-9]+(\.[0-9]+)?$';
```

The partial predicate is not optional — the term table holds URIs and free text,
and an unqualified expression index fails to build:

```
ERROR: invalid input syntax for type numeric:
  "urn:acme:lead:00QUg...:frame:leadstatusframe:0:..."
```

which is the same reason the generator wraps its cast in a regex guard.

Measured on the `hasDoubleSlotValue >= 65` lookup:

| | Buffers (hit / read) | Notes |
|---|---|---|
| **Before** | 916 (40 / **876**) | Bitmap Heap Scan with `Rows Removed by Index Recheck: 40,862` |
| **After** | 389 (385 / **4**) | Bitmap Index Scan on the expression index |

**2.4x fewer buffers and 219x fewer disk reads**, for a **40 kB** index. The
40,862-row index recheck disappears entirely.

Caveats: this indexes numeric literals only — datetime and other typed
comparators would each need their own partial expression index, and the regex
must match the generator's own guard exactly or the planner will not use it.
It also does not by itself make the *generator* emit a range-constrained join;
it makes the underlying lookup cheap, which helps whether or not the SPARQL
FILTER is pushed down.

### M3. Keyset pagination — RULED OUT under current requirements

Replacing `OFFSET` with a keyset cursor would fix the O(N²) deep-paging
behaviour that M1 does not address — M1 makes each page O(page) to *find*, but
`OFFSET n` still walks n rows.

**Not viable as things stand.** It is incompatible with paging and sorting
features the API already offers and the UI already uses:

1. **`offset` is a public parameter.** `KGQueryRequest.offset: int = Field(0, ge=0)`.
   A cursor replaces it, so every caller computing offsets breaks —
   `frontend/src/components/entity-graph/LevelPagination.tsx` does exactly that:
   `pageNumber(offset, pageSize)`, `onOffsetChange(offset - pageSize)`,
   `onOffsetChange(offset + pageSize)`.
2. **No random access to page N.** Offset can jump to page 50; a cursor only
   moves next/previous from where it is. The UI's page number and its
   `rangeLabel(offset, shown, totalCount)` both need an absolute position that a
   cursor does not provide.
3. **`total_count` conflicts with the point of the change.** The response
   returns it and the UI renders it — `EntityGraphHeader` documents that the
   frame total comes from the server's `total_count`. Keyset pagination does not
   produce a total; computing one still requires the full count query, which is
   the O(matches) scan this issue is about. Either the cost stays or the UI
   loses "of 4,170".
4. **Arbitrary sorting becomes impossible.** A cursor requires a unique, totally
   ordered, indexed key. `sort_criteria` currently allows ordering by arbitrary
   fields; under keyset each supported ordering needs its own index and its own
   cursor encoding, and any field without one simply cannot be sorted on.

Point 4 is the blocking one: sorting on arbitrary fields and keyset pagination
are close to mutually exclusive, and sorting is an existing feature rather than
a nice-to-have.

Revisit only if deep paging into large result sets becomes a real workload *and*
the product is willing to trade away arbitrary sort fields, jump-to-page, or the
total count. Note that M1 (ordering by `subject_uuid`) happens to establish
exactly the unique indexed key a cursor would need, so doing M1 first makes M3
cheaper should that ever change — but M1 does not depend on it.


### M1 and M2 are additive

Measured on the same range-filtered page (`hasDoubleSlotValue >= 65`, 25 rows),
all four combinations:

| | expression index | paging | buffers | saving vs A |
|---|---|---|---|---|
| **A** neither | — | current | **1,390** | — |
| **C** M1 only | — | two-phase | **991** | 399 |
| **B** M2 only | ✓ | current | **863** | 527 |
| **D** both | ✓ | two-phase | **464** | **926** |

399 + 527 = 926, and the observed combined saving is exactly 926 — the savings
sum with no overlap. Combined effect on this query is **3.0x fewer buffers**.

They are additive because they remove disjoint costs: M2 removes the
40,862-row index recheck at the *leaf* (making the range lookup indexable), M1
removes full-match-set materialisation at the *top* (DISTINCT + Sort). Neither
subsumes the other and applying one does not reduce the other's benefit, so
they can be sequenced independently without re-measuring the second.

Note the buffer counts here differ from the individual M1/M2 sections above
because this query joins the term table twice (subject text and object value)
to keep all four variants comparable.

**This additivity result is about the probe queries, not about the generated
SQL.** It says the two *effects* are independent where both are reachable; it
does not say either is reachable today. See the warning at the top of the
mitigations section — on the generated plan M2 is inert and M1 is capped at 20
of 3,341 buffers.

### Suggested order

**M2 first** — small, cheap, independent, and does not touch the API.

**M1 is the substantive fix.** It changes the complexity class and the codebase
already has a working precedent in the entity fast path. It also keeps the
current API intact: same `offset`, same `total_count`, same UI. The open
question is ordering — M1 as measured pages by `subject_uuid`, so if a caller
requires alphabetical-by-URI order the sort cannot be skipped that way and the
fix becomes "an index supporting the required order" instead. Worth establishing
what `sort_criteria` orderings are actually used before building it.

**M3 is ruled out** (above), so deep pages remain linear in offset. That is an
accepted limitation rather than an oversight: M1 makes pages 1-N cheap to find,
which is the common case, and the deep-page cost only bites on workloads that do
not currently exist.

## Related

The planner also estimates `rows=1` at every one of the 10 join levels against
99 actual — a systematic ~99x underestimate, the same correlation-blindness
family as issues/039 and the nurture slot-value blowup. It happens to pick
nested loops, which is correct at this size; at larger match counts that same
estimate is what would drive a bad join choice. Worth watching if the paging
work above changes the plan shape.

### The `gte` comparator carries the whole candidate set through the join

`high_rated` breaks the otherwise-linear relationship: **73 matches but 3,321
buffers**, more than `mql`'s 99 matches at 3,022. Fewer results, more work.

The plan says why. In `mql` (equality on a boolean slot) the join chain carries
99 rows from the bottom. In `high_rated` it carries **100** — every entity in
the space — through nine of the ten nested-loop levels, and only narrows to 73
at the very top:

```
Nested Loop  rows=73     ← the >= 65.0 filter applies here, last
  Nested Loop  rows=100  ← every entity in the space
    Nested Loop  rows=100
      Nested Loop  rows=100
        ... six more levels, all rows=100
```

The range predicate becomes a SPARQL `FILTER(?val_0_0_0 >= 65.0)`, which is
evaluated *after* the pattern joins rather than constraining the slot-value
lookup. An equality comparator binds the object directly and narrows the scan at
the leaf; `gte` cannot, so the join fans out over the full candidate set first.

This compounds the main issue rather than being separate from it. Where equality
paging is O(matches), range paging is O(*candidates*) — every entity carrying
that slot type, whatever the threshold. On a large space the two diverge sharply:
a highly selective threshold (say the top 1% by rating) still pays the full
candidate cost, and the more selective the filter the worse the ratio of work to
results.

Worth checking whether the generator can push a range predicate into the SQL as
a bound on the slot-value column — the numeric value is available as `v0__num`
in the emitted projection, so an index-supported range scan may be reachable
rather than a post-join filter.

## Reproduce

```bash
pytest tests/performance/test_kgquery_generated_sql_plans.py -m performance -q
```

Compare `query.kgquery.generated_sql.plan[state_ca]` (13 matches) against
`[mql]` (99 matches) in the recorded run — buffers scale with the match count.
The bench gates plan *shape*; it does not currently gate this ratio, because on
a 100-entity fixture there is no headroom to set a bound from. A larger fixture
would let the growth class be asserted the way `test_growth_curve.py` does.
