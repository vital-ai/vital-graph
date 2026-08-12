# Nothing Chooses Which Criterion Drives the Query

## Status: CLOSED again — the failing case was fixed WITHOUT driver selection

> **MEASURED ON A 1 GB BUFFER POOL — see `issues/081`.** At risk: every timing, including the two reverts' 3-14ms -> 30s. `shared_buffers` was 1 GB on a 64 GB machine against queries touching 400,000+ buffers; raising it to 16 GB moved a comparable query 16,411 ms -> 616 ms with no code change. Plan shapes, row counts and buffer counts are unaffected.

Reopened earlier on 2026-08-11 because `issues/070` looked like the shape step 3
needed. It was not. That case is now fixed — a short `contains` needle is
rejected at the API and kept off the trigram index in the emitter — and driving
the page from the text leaf was measured DIRECTLY and lost:

    contains 'ZZQQXX', driven, 10k     11,690 ms (best fence)
    contains 'ZZQQXX', shipped, 100k        1 ms

Worse on a fixture ten times smaller, with every fence tried
(`join_collapse_limit=1`, `enable_nestloop=off`, `enable_material=off`). The
cross product it produces comes from a 10,000x cardinality underestimate the
planner has no statistics to avoid — `issues/072`, not an ordering defect.

So step 3 is back to having no failing case, and now with evidence that the
specific thing it proposes is the wrong answer for the one shape that looked
like a candidate. Precedence stays text anchor -> range anchor -> cheapest leaf
-> list position. Reopen only with a measured shape where criterion order still
changes cost, gated on `perf_sweep_diff.py`.

**Reopened 2026-08-11, hours after being closed.** It was closed on the grounds
that no measured shape needed it. `issues/070` is that shape:

    contains 'CA'        45 ms      common substring
    contains 'ZZQQXX'    TIMEOUT    absent — walks every entity

`_emit_two_phase` always anchors the page on the entity-type BGP and makes every
criterion a probe. `_try_selective_driven` exists to drive the page from a
criterion instead, but fires only when two-phase DECLINES. For `contains`
two-phase succeeds, so the selective side never gets the chance, and a text leaf
whose match set is empty is discovered one candidate at a time.

This does NOT vindicate the general ranking policy the issue originally proposed,
and the two reverts still stand against it. What it asks for is narrower and
already has precedent: `reorder_bgp` pins an index-backed text leaf first for
JOIN ORDER, with a comment explaining that a trigram-served leaf is cheap to
enter whatever it matches. The same precedence needs to reach DRIVER choice —
gated on selectivity, since driving from `'CA'` (2.6M terms) would be worse than
the probe it replaces.

Re-measured 2026-08-11 on `sp_lead_synth_100k`, every two-criterion permutation
of three comparator cells, 25-row page, warm median of 3:

    contains/Text + eq/Boolean    fwd 174ms   rev 176ms   1.0x
    contains/Text + gte/Double    fwd 242ms   rev 266ms   1.1x
    eq/Boolean    + gte/Double    fwd  55ms   rev  58ms   1.0x

Identical row counts both ways. Criterion order no longer changes cost, which is
what this issue was filed about.

**Step 3 — "rank every criterion and choose deliberately" — is deliberately NOT
being implemented on spec.** It is a generalization with no failing shape to
validate against, and the specific attempt at it has already been reverted twice:
root-by-cardinality shipped once and took seven range cells from 3-14ms to 30s,
because a range leaf binds a predicate and no constant object, so it has no count
and something else won the root. Cheap to ENTER is not the same as selective.

The precedence in place — text anchor -> range anchor -> cheapest leaf -> list
position — encodes that lesson. Widening it needs a measured case it gets wrong;
without one, a ranking rewrite is a change whose only evidence would be that it
sounds more principled. Reopen with a failing permutation and gate it on
`scripts/perf_sweep_diff.py`.

This issue's thesis was that nothing chooses which criterion drives, so the
caller's ordering leaks into the plan. Measured across EVERY permutation of each
criteria set, alternating arms with the first repetition discarded:

    selective + large     2 orderings   142-142 ms    spread 1.0x
    selective + range     2 orderings   191-204 ms    spread 1.1x
    large + range         2 orderings    86- 95 ms    spread 1.1x
    three criteria        6 orderings   165-307 ms    spread 1.9x

Against >20 s vs 5.6 s for the same two criteria before. Order no longer decides
the plan.

Correctness checked alongside, not assumed: all six orderings of the
three-criteria set return **identical 249-row sets**.

### It was fixed by a different mechanism than this issue proposed

The issue asked for criteria-level driver selection — rank the criteria, choose
one to drive. What actually fixed it is one level down: `collect` merges every
criterion into ONE right-hand BGP, so "which criterion drives" is really "which
LEAF roots the scan", and `reorder_joins` was choosing that by LIST POSITION.

Giving it `leaf_cardinality` from `plan.leaf_terms` — the structural record made
at collect time — makes the cheapest leaf root the chain whatever order the
caller wrote. The ranking the issue wanted happens, just inside the BGP rather
than above it.

`emit_slice._try_selective_driven` remains for the separate case where two-phase
declines entirely and the answer is sparse (`WV + LeadStatus`, 961 -> 119 ms).

### What is left, and it is small

* **1.9x spread across the six three-criteria orderings** (165-307 ms). Both ends
  are fast and it is well below the 2x flag, but it is not 1.0x — root choice is
  right and the PLACEMENT after the root is still greedy on connectivity first,
  cardinality second. Worth a look only if a slow case turns up.
* **`_PAIR_COUNT_CAP = 50_000` still saturates**, so two genuinely large criteria
  remain indistinguishable to the ranker. It did not matter here because one leaf
  was always cheaper, and it will matter when neither is.
* Steps 1 and 2 (per-predicate retention, saturation recorded distinctly) are
  done.

### Read this before touching root selection again

It shipped once and broke SEVEN range cells, 3-14 ms to 30 s. A range leaf binds
a predicate and NO constant object, so it has no pair count and something else
won the root — and the plan stopped driving from the `num_val` index the range
push-down rests on. The rule is that an INDEX-BACKED leaf roots the chain
REGARDLESS of how much it matches: cheap to ENTER is not the same as selective.
That is what the text-filter anchor always encoded. Precedence: text anchor ->
range anchor -> cheapest leaf -> list position.

## Superseded status: step 3 PARTLY IMPLEMENTED — 2026-08-10

`emit_slice._try_selective_driven` drives the page from the selective criterion
instead of the entity anchor. Measured with alternating arms, first rep
discarded:

    WV alone                    35 ms ->  32 ms    no change, no harm
    WV + LeadStatus            961 ms -> 119 ms    8.1x
    LeadStatus + WV            >20 s   -> >20 s    NOT fixed

So the ORDER asymmetry this issue is named for is only half addressed: the
selective-criterion-first ordering is now fast, the other ordering is not.

### DIAGNOSED — `reorder_joins` cannot see pair cardinality at all

The path fires for both orderings, the gate inputs are identical, and the
emitted join ORDER is identical — the same 20 aliases in the same sequence. The
only difference is which end the scan starts from, and that is
`reorder_bgp.reorder_joins`:

    # --- Pick chain root ---
    first = quad_tables[0]        # whatever is listed first
    ...
    if ilike_alias: first = ...   # only a text filter overrides it

**The root is list position.** Cardinality is computed for every alias but used
only for the greedy placement AFTER the root, behind connectivity. For a KGQuery
"listed first" is the criterion the CALLER wrote first, which is precisely this
issue's complaint.

Two fixes were tried and BOTH are no-ops, which is the more useful finding:

* root by cheapest leaf instead of list position;
* merging `extra_quad_stats` into what `reorder_joins` receives, since
  `rdf_stats` is pruned and the on-demand loader is the only thing that knows
  these pairs.

Neither helped, separately or together, because **`cardinality` is empty for
this shape**. It is derived by REGEX-PARSING the constraint SQL:

    elif f"{alias}.object_uuid = " in sql and not refs:

which requires the object constant to sit in a constraint that references no
other alias. The KGQuery shape emits combined constraints —
`q7.subject_uuid = mv0.dest_node_uuid AND q7.predicate_uuid = '...' AND
q7.object_uuid = '...'` — so `refs = {mv0}`, the branch is skipped, and no leaf
ever gets a `(predicate, object)` count. Both roots fall through to `mv0`, an
edge table.

So the ordering asymmetry is not a missing policy. It is a parser that cannot
read the shape this pipeline actually emits, and every selectivity decision
downstream of it is made on `_INF`.

### ATTEMPTED AND REVERTED — root-by-cardinality breaks every range comparator

Implemented as described below — `reorder_joins` taking `leaf_cardinality` from
`plan.leaf_terms` — and it worked for the case it targeted:

    LeadStatus + WV     >20 s -> 142 ms, matching WV + LeadStatus exactly

and broke SEVEN other cells, all of them ranges:

    gt/Double, gt/Integer, gt/DateTime      3-13 ms -> 30 s timeout
    gte/Double, gte/Integer, gte/DateTime   3-12 ms -> 30 s timeout
    lt/Double                                 16 ms -> 30 s timeout

Reverted (`62777d7`), and the revert restores all seven to 3-14 ms.

**Why.** A range criterion's leaf binds a predicate and NO constant object, so it
has no `object_uuid` entry in `leaf_terms` and gets no cardinality. Some other
leaf then wins the root and the plan stops driving from the `num_val` index the
whole range push-down depends on (`issues/040` W2, `issues/056`).

This is the same shape as the text-filter anchor, which is special-cased for
exactly this reason: a leaf that is cheap to ENTER but invisible to `quad_stats`
because it has no constant object to key on. Ranges need that same protection and
did not get it. `plan.range_leaves` records `(alias, col) -> (operator, literal)`
precisely so a consumer can see them, and `aliases.range_stats` holds their
counts — neither was fed into the cardinality map.

So the fix is not wrong, it is incomplete: the cardinality map must cover range
leaves before root selection can use it, and the next attempt has to be swept
before it is committed rather than after.

### The fix, and why it is not a one-liner

`plan.leaf_terms` records `(alias, column) -> (text, type)` STRUCTURALLY at
collect time, precisely so consumers do not have to parse SQL back — the
selectivity gate was moved onto it for this reason, and `_replace_plan_in_place`
carries a comment about `leaf_terms` being silently dropped once. `reorder_joins`
predates that and still parses text.

Feeding it `leaf_terms` (and `range_leaves`) instead of regexes would give every
leaf a real count, at which point root-by-cardinality becomes a two-line change
that actually fires. That is the work; the root policy alone is not.

Paging is on the entity uuid, which is decision D1 in
`two_phase_kgquery_paging_plan.md`, accepted and bounded to queries with no
explicit `sort_criteria`. The `shared_var != key` guard is what enforces that
boundary: when a sort IS requested the order key is a sort variable, the guard
declines, and the caller's sort is honoured by normal emission.

Verified the full result sets are identical to the previous plan's — 848 of 848
and 249 of 249 — so this changes the plan, not the answer.

### Two measurement corrections worth keeping

* A first version sorted the page by term text rather than uuid, on the belief
  that uuid order was a bug. It is D1, deliberate. The text sort cost the entire
  win (3,683 ms against a 3,208 ms baseline) because it must materialise the
  whole match set before it can pick a page — and led to reverting the path
  altogether on the false conclusion that it was "only fast because it was
  wrong". See `issues/075`.
* An early figure of 48x was contaminated: the two arms ran back to back, so the
  second read a cache the first had warmed. Alternating and discarding the first
  rep gives 8.1x.

## Superseded status: steps 1 and 2 DONE; step 3 has a demonstrated case

Steps 1 and 2 of the suggested order below are implemented:

* **per-predicate stats retention** — `STATS_PER_PREDICATE_DEFAULT = 2_000` in
  `sync_stats_tables`, so a high-cardinality literal can no longer evict every
  structural predicate;
* **saturation recorded distinctly** — `aliases.saturated_pairs` marks counts
  that hit `_PAIR_COUNT_CAP`, so a ranker can tell a lower bound from a
  measurement instead of treating 50,000 as exact.

**Step 3 now has a failing case, which it did not before.** Measured on
`sp_lead_synth_100k`, 25-row page, each criterion in its own frame chain:

    LeadStatus eq  +  CompanyStateCode eq "WV"     >25 s, needs_ordered_scan=False
    CompanyStateCode eq "WV"  +  LeadStatus eq      5,585 ms, 25 rows

The same two criteria. Conjunction is commutative, so that is one question with
two answers depending on the order the caller wrote them in — which is this
issue's thesis, demonstrated rather than argued.

It is NOT the fan-out gate: it still times out with
`MAX_SAFE_PATH_AMPLIFICATION` raised to 10^9. (That gate WAS the cause of the
other multi-criteria slowness — `LeadStatus eq + MQLRating gte` went >25 s to
39 ms once it stopped compounding p99 across hops.) The remaining decline reason
is undiagnosed.

### DIAGNOSED — 2026-08-10. Neither existing plan shape can answer it.

The decline is silent, before any log line: `mark_semijoins` never marks the
join, so `_emit_two_phase` returns at `_has_semijoin=False`. The gate that
declines is `_selective_enough` — `WV` is 848 of 100,000, i.e. 0.85%, under
`MIN_SELECTIVITY = 0.05`.

**That gate is correct and must not be relaxed.** Measured both ways:

    WV alone            MIN_SELECTIVITY 0.05    73 ms      set-based, right call
    WV alone            MIN_SELECTIVITY 0.00    >10 s      forced probe, catastrophic
    large + selective   MIN_SELECTIVITY 0.05    >10 s
    large + selective   MIN_SELECTIVITY 0.00    >10 s

The first pair is the 889x this codebase already documents: probing a selective
criterion costs O(page / selectivity), so the set-based join wins and the gate
picks it. Relaxing the threshold to fix the third row breaks the first.

The second pair is the finding: **for one selective plus one large criterion,
BOTH available plans are >10 s.** Probing from the entity anchor is wrong
because the answer is sparse; the set-based join is wrong because it materialises
the large criterion. The shape has no good plan in the current repertoire, which
is why no threshold tuning reaches it.

### What is actually missing

`_emit_two_phase` always anchors on the ENTITY-TYPE bgp, because that is what
supplies `subject_uuid` order for O(page) paging. Every criterion is then a
probe. For this shape the right driver is the SELECTIVE CRITERION: find the 848
entities with `WV`, test each against `LeadStatus`, sort 848 and take 25.

That trades away the ordered scan — the sort is over 848 rows, not 100,000 —
which is precisely the trade `issues/059`'s candidate-driven path already makes
for negation, gated on density. This is the same trade for a different reason,
and it is the concrete form of "which criterion drives" that this issue names.

So step 3 is not "rank criteria and reorder them". It is "allow a criterion
other than the entity type to be the driver, when it is selective enough that
sorting its whole match set is cheaper than paging the entity index". The
ranking is the easy half; the emission path is the work.

`WV` alone at 73 ms is the existence proof that reaching those 848 rows is cheap.

See `two_phase_kgquery_paging_plan.md` for the full measurement table.

## Original status: OPEN — the machinery exists, nothing consumes it at criteria level

PostgreSQL will not make this decision for us, and we already accepted that once:
`reorder_bgp.reorder_joins` orders joins **within** a BGP using `quad_stats` /
`pred_stats`, because the planner's estimates on this schema are unreliable —
measured 305x and 4,761x underestimates on multi-hop uuid joins (`issues/059`).

What is missing is the level above. Three decisions, and only the first is made:

| decision | who makes it | status |
|---|---|---|
| join order within a BGP | us, `reorder_joins` | done |
| join method/order across the emitted SQL | PostgreSQL | unreliable here |
| **which criterion drives, and traversal direction** | **nobody** | this issue |

## Why PostgreSQL cannot do the third one

Not merely "does it badly" — it is never asked. `emit_slice._emit_two_phase`
anchors on the entity-type BGP to get `subject_uuid` order for O(page) paging,
and every other criterion becomes a probe. And `emit_bgp_exists` appends
`OFFSET 0` as an explicit optimization fence, specifically to stop PostgreSQL
flattening the correlated subquery into a semi-join, because flattening destroys
the ordered scan.

That fence is right for a dense match set. It is also exactly what prevents a
better plan when the result is sparse — see `issues/059`, where a backward
set-wise form answers in 700 ms what the forward probe cannot finish in 200 s.

## What the statistics can and cannot currently tell us

Two problems, in order of severity.

**1. The bounded count saturates.** `_load_missing_pair_stats` counts pairs the
preload lacks, with `_PAIR_COUNT_CAP = 50_000`, cached per process. In the
query that times out, both candidate drivers are actually 100,000 rows:

    (vitaltype,     KGEntity)    actual 100,000  ->  reported 50,000
    (hasKGSlotType, MQLRating)   actual 100,000  ->  reported 50,000

Identical. There is no signal to order them by. The cap is deliberate and its
reasoning is sound for the **gate** — "the gate only needs to know whether a pair
is large, not how large" — but ordering needs the opposite property.

Note this does not block the case that matters most in production: a genuinely
selective criterion (a state code at ~8,800 rows) is well under the cap and is
distinguishable from a saturated one. Ranking *selective vs unselective* works
today; ranking two large criteria does not.

**2. `rdf_stats` is pruned to the wrong rows.** `prune_stats_tables` keeps the
50,000 **lowest** row_counts (`STATS_KEEP_DEFAULT`), and the loader takes the
lowest 10,000 within `[2, 200_000]`. Sensible for seeding a join from its most
selective leaf. But on a 100k-entity space every surviving row has
`row_count = 2`, and only two predicates are represented at all:

    hasEdgeSource          49,516 pairs kept
    hasDateTimeSlotValue      484 pairs kept

The predicates that actually decide plan shape are absent entirely —
`vitaltype` (10,054,000 quads), `hasKGSlotType` (3,877,000), `hasKGFrameType`
(1,100,000). So the preload contributes nothing to these queries and everything
falls through to the capped count.

This is aggravated by the fixture's unique-per-row datetimes (`issues/050`) —
409,017 distinct values, each appearing about twice, flooding the keep-window.
Any high-cardinality literal in production does the same. The pruning is by
global rank, so one noisy predicate can evict every structural one.

A per-predicate policy — keep the most common objects for each predicate, the
way PostgreSQL's MCV lists work — would survive that, and is what makes the table
usable for ranking rather than only for seeding.

## The missing metric is fan-out, not more predicate/object correlation

Predicate/object correlation is already recorded twice — `rdf_stats` holds
`(predicate, object) -> row_count`, and `stat_{space}_quad_po (mcv, ndistinct)`
teaches PostgreSQL the same thing. More of it would not help, because the errors
are not in single-table selectivity. They are **join** cardinality: 305x and
4,761x underestimates on multi-hop traversal steps (`issues/059`).

What no stored metric expresses is **edge fan-out**: given N nodes, how many rows
does one traversal step produce? Measured on the 100k fixture's edge table:

| direction | fan-out per hop |
|---|---|
| forward (source -> dest) | avg **4.15**, p99 10, max 10 |
| backward (dest -> source) | avg **1.00**, p99 1, max 1 |

Over the three hops those queries walk, that is **~71x amplification forward and
1x backward** — which is the whole of the 700 ms vs >200 s gap in `issues/059`,
and the same order as the observed underestimates.

### It is a property of the model, but only for containment edges

Confirmed with the data owner, 2026-08-10:

* a **slot** has exactly one parent;
* a **frame** has no parent or exactly one (an entity or a frame).

So for the containment hierarchy, backward fan-out is 1 **by construction**, not
by observation. A rewrite that walks containment backward is non-amplifying by
the shape of the model, which is a much stronger guarantee than a measurement on
one fixture.

It does **not** generalise to the other edge kinds:

* **relations** have a source and a destination, and an entity may participate in
  many, in either role — many-to-many in both directions;
* a **slot value** may be an entity or arbitrary URI, and many slots may point at
  the same target, so walking from a target back to its slots fans out. (This
  case is already covered by existing stats: it is an `(predicate, object)` count
  in `rdf_stats`, not an edge-table hop.)

So a blanket "always traverse backward" rule would be wrong. Fan-out has to be
recorded **per edge type**, which makes `issues/060` (the edge type column) a
prerequisite for the metric and not only a performance win — without it the edge
table cannot even distinguish the cases.

### Measured on real data: the direction rule INVERTS between edge kinds

`wordnet_frames` carries 570,696 `hasEntitySlotValue` quads — slot values that
point at entities — so the non-tree case is measurable on real data rather than
hypothesised:

| edge kind | forward | backward |
|---|---|---|
| containment (`Edge_hasKGSlot`) | avg 2.00, max 2 | **avg 1.00, max 1** |
| slot value (`hasEntitySlotValue`) | **avg 1.00, max 1** | avg 5.20, p50 2, p99 40, **max 1,342** |

Two conclusions, both of which constrain the design:

1. **Containment backward = 1 holds on real data**, confirming the model
   guarantee rather than a synthetic artefact.
2. **The safe direction is per edge kind and it inverts.** For a slot-value hop
   the safe direction is *forward*; walking it backward hits 1,342x at worst. A
   blanket "traverse backward" rule — which the 100k fixture alone would have
   justified — is wrong.

**The distribution is skewed, so an average is not enough.** 5.20 average against
a 1,342 maximum: a plan chosen on the mean can hit 250x that. The metric needs a
tail statistic (p99 and max), not a mean, and a direction choice should use the
tail when the cost of being wrong is a timeout.

### Coverage gap this exposes

The fixture contains only `Edge_hasKGSlot` (3,877,000), `Edge_hasKGFrame`
(900,000) and `Edge_hasEntityKGFrame` (200,000). **No relation edges exist in it
at all**, which matches `issues/043`/`048`: `build_relation_query` requires
`Edge_hasKGRelation`, which has zero instances anywhere.

Every fan-out number from that fixture therefore describes the tree-shaped half
of the model. `wordnet_frames` covers the slot-value case above and is the
fixture any direction-choosing rewrite must be validated against — it is the one
that would have caught a blanket backward rule.

**Relations are now covered** — `sp_kg_rel`, built 2026-08-10 by
`scripts/generate_relation_dataset.py` / `load_relation_dataset.sh`. 5,000
entities, 223,965 triples, and the first fixture anywhere with relation edges
(16,043 `Edge_hasKGRelation`; the only other instances in existence are 96 in a
handful of tiny test spaces).

Fan-out measured from the loaded space, per edge type:

| edge type | forward | backward |
|---|---|---|
| `Edge_hasEntityKGFrame` | avg 1.00, max 1 | avg 1.00, max 1 |
| `Edge_hasKGFrame` | avg 1.00, max 1 | avg 1.00, max 1 |
| `Edge_hasKGSlot` | avg 1.00, max 1 | avg 1.00, max 1 |
| **`Edge_hasKGRelation`** | **avg 4.24, max 400** | **avg 4.20, max 387** |

Relations are simple binary relationships — `person1 --friendOf--> person2`,
`person1 --worksFor--> company1` — so the fixture generates them with the
structure such data has: a Watts-Strogatz small world for `friendOf`,
Zipf-skewed company sizes for `worksFor`, and a management tree for `reportsTo`.

**The granularity has to reach `hasKGRelationType`, not stop at the edge type.**
Measured from the loaded space, per relation type:

| relation | forward | backward |
|---|---|---|
| `friendOf` | 3.00 / max 3 | 3.00 / max 6 |
| `mentions` | 1.49 / max 2 | 1.41 / max 5 |
| `reportsTo` | 1.00 / **max 1** | 4.77 / max 5 |
| `worksFor` | 1.00 / **max 1** | 39.00 / **max 886** |

All four are `Edge_hasKGRelation`. Backward fan-out across them ranges from 5 to
886, and `reportsTo` is a *tree living inside the same edge type as the hub* —
every person has exactly one manager. A statistic recorded per edge type averages
those into a number describing none of them.

So there are three levels, and each one loses information the next needs:

    per space       forward 1.80 / backward 1.51   hides everything
    per edge type   relation 4.2 / 4.2             hides reportsTo vs worksFor
    per relation type                              usable

`issues/060`'s type column is therefore a prerequisite for the metric and not
merely a performance win — and it is not sufficient on its own.

The fixture also carries both frame form types, including assertion frames that
leave `hasKGFormType` unset (1,250 of 5,000), since unset defaults to assertion
and a fixture that always states it cannot catch a reader that requires the
explicit triple. The manifest records every degree distribution so a test can
assert them rather than recompute them from the data under test.

Still missing: the fixture is not yet registered anywhere the perf suite reads,
so nothing runs against it automatically.

## Suggested order

1. **Per-predicate stats retention** (problem 2). Self-contained, no query-path
   risk, and makes the other work possible.
2. **Raise or tier the cap** for pairs being *ranked* rather than gated, or
   record "at least CAP" distinctly from an exact count so the two are not
   confused. Cheap.
3. **Criteria-level driver selection.** Choose the driving criterion by
   selectivity instead of always anchoring on entity type. This is the real
   change, and `issues/059` is its most extreme case.

Steps 1 and 2 are prerequisites for 3 having anything to decide with.

### Step 1 has to answer the write path too

Per-predicate retention changes *what is kept*; it does not change *how it is
maintained*, and maintenance has the same hole the edge table just turned out to
have (`issues/064`). `sync_stats_after_delete` is subject-driven exactly like
the edge hooks, so a SPARQL UPDATE whose subjects are WHERE-bound misses it.

Stats are the harder version because they are also pruned: a pruned row that a
later write resurrects comes back holding only its post-prune delta —
demonstrated at 100,000 → 1 (`issues/062`). So a write hook alone is not enough.
Absence has to *mean* something, which is exactly what the MCV shape provides:
"smaller than the smallest listed", rather than ambiguous between small, pruned,
and never-seen. Design the retention and the maintenance together, or the first
will keep being undone by the second.

## Related

- `issues/059` — backward negation; 700 ms vs >200 s, the case this would unlock
- `issues/060` — edge type column, which makes the backward hops cheap
- `issues/050` — unique-per-row datetimes, which flood the stats keep-window
- `two_phase_kgquery_paging_plan.md` — D3, of which this is the concrete form
