# Frame/Slot Sort Orders By a Variable It Never Projects

## Status: FIXED 2026-08-16 — correct, and 869 ms → 8 ms end to end via a maintained derived table

Part 1 (the 500) and the duplicate-row defect underneath it are fixed and
tested. Part 2 took 17% via pattern order, then a survey (§"Solutions
investigated") eliminated extended statistics and the semi-join on evidence and
identified a denormalised sort table as the answer. **That table is now built,
maintained and read.**

End to end through the portal's own call path, `cardiff_kg`, 25-row page:

| | before | after |
|---|---:|---:|
| page 1 asc | 869 ms | **10 ms** |
| page 1 desc | 1,707 ms | **8 ms** |
| offset 500 | 869 ms | **8 ms** |
| offset 2000 | O(offset) | **11 ms** |

Same 25 entities in the same order as the SPARQL path, verified against it in
both directions, at two page depths, and at two FRAME depths — a nested
`PersonalGuarantorFrame → PersonalGuarantorContactFrame → GuarantorEmail` sort
is also 8 ms and also identical.

`{space}_entity_slot_sort` is a STRUCTURAL MIRROR under
`planning_sql/derived_table_maintenance.md`: incremental on all eight write
paths, drift-detected in `MaintenanceJob`, repairable by
`repair_derived_tables.py`, rebuilt by `resync_all`, and read by
`fast_slot_sort`, which declines to the general pipeline for any shape it does
not serve.

**Remaining, and why this is not archived:** the direction gate from the survey
(2.9x on the general path, 87x worse pinned) is still unbuilt. It matters for
every traversal, not just this sort, and the shapes `fast_slot_sort` declines —
a slot attached directly to an entity with no frame, and sorts combined with
frame or property criteria — still take the six-way join. This issue's own query
is fixed; the class it belongs to is not.

What landed, all in `vitalgraph/sparql/kg_query_builder.py`:

- `_sort_needs_aggregate` — new; whether a criterion can bind more than one
  value per anchor, decided from the PATH rather than from the loaded data.
- `_build_sort_bindings` — decides aggregation once across all criteria before
  emitting, then projects every ordered variable. Frame/slot sorts become
  `SELECT ?entity (MIN(?_sort_raw_0) AS ?sort_val_0) ... GROUP BY ?entity`.
  Also emits slot constraints first and walks the frame path inward-out (Part 2).
- Tests: `tests/unit/test_kgquery_sort_projection.py` (28 cases, 21 fail
  pre-fix), `tests/integration/test_kgquery_sort_projection.py` (5 cases, all
  fail pre-fix with the production error).

Verified against `cardiff_kg` through the portal's own call path
(`kgqueries.query_entities`): 25 distinct URIs per page, `total_count=2863`,
pages disjoint, ordering correct across page boundaries in both directions.

## Original report — every `entity_frame_slot` / `frame_slot` sort 500s; found 2026-08-16 while timing the Cardiff portal's query shapes

`KGQueryBuilder` emits `ORDER BY ?sort_val_0` over a `SELECT DISTINCT ?entity`
that does not project `?sort_val_0`. The generated SQL then orders the outer
query on a column the `DISTINCT` subquery does not have:

```
Failed to execute entity query: column s0.v5 does not exist
HINT:  Perhaps you meant to reference the column "s0.v0".
```

`v0` is `?entity`; `v5` is `?sort_val_0`. The column index varies with the
request shape (`v5` and `v6` both observed) — same defect.

## Reproduce

Any `query_entities` call carrying a `SortCriteria` with
`sort_type="entity_frame_slot"` or `"frame_slot"`. Measured on `cardiff_kg`
(5.1M quads):

```python
sc = SortCriteria(sort_type="entity_frame_slot",
                  frame_path=["urn:cardiff:kg:frame:KGLeadInfoFrame"],
                  slot_type="urn:cardiff:kg:slot:CompanyName",
                  slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                  sort_order="asc", priority=1)

await client.kgqueries.query_entities(
    space_id="cardiff_kg", graph_id="urn:cardiff_kg",
    entity_type="urn:cardiff:kg:entity:KGLead",
    sort_criteria=[sc], page_size=25, offset=0)
```

| | result |
|---|---|
| identical criteria, `sort_criteria=None` | 25 URIs, `total_count=2863`, **24 ms** |
| with `sort_criteria` above | **HTTP 500**, every time, every offset |

## Cause

`vitalgraph/sparql/kg_query_builder.py:1353`, `_build_sort_patterns`. Three
branches; only one populates `select_vars`.

The `entity_property` branch projects the sort variable (`:1368-1369`):

```python
patterns.append(f"?{anchor_var} <{sc.property_uri}> ?{sort_val_var} .")
select_vars.append(f"?{sort_val_var}")
```

The `frame_slot` branch (`:1379`, no frame path) and the `entity_frame_slot`
branch (`:1393`, with frame path) both end the same way — patterns appended,
`select_vars` untouched:

```python
patterns.append(f"?{slot_var} haley:hasKGSlotType <{sc.slot_type}> .")
patterns.append(f"?{slot_var} {value_property} ?{sort_val_var} .")
```

Both then fall through to the shared `ORDER BY` construction at `:1446`, which
references `?{sort_val_var}` regardless of whether it was projected. The
builder's caller emits `SELECT DISTINCT ?entity` (`:318`, `:958`, `:968`), so:

```sparql
SELECT DISTINCT ?entity WHERE { GRAPH <urn:cardiff_kg> {
    ?entity haley:hasKGEntityType <urn:cardiff:kg:entity:KGLead> .
    ?sort_frame_edge_0_0 vital-core:vitaltype <...Edge_hasEntityKGFrame> .
    ?sort_frame_edge_0_0 vital-core:hasEdgeSource ?entity .
    ?sort_frame_edge_0_0 vital-core:hasEdgeDestination ?sort_frame_0_0 .
    ?sort_frame_0_0 haley:hasKGFrameType <urn:cardiff:kg:frame:KGLeadInfoFrame> .
    ?sort_slot_edge_0 vital-core:vitaltype <...Edge_hasKGSlot> .
    ?sort_slot_edge_0 vital-core:hasEdgeSource ?sort_frame_0_0 .
    ?sort_slot_edge_0 vital-core:hasEdgeDestination ?sort_slot_0 .
    ?sort_slot_0 haley:hasKGSlotType <urn:cardiff:kg:slot:CompanyName> .
    ?sort_slot_0 haley:hasTextSlotValue ?sort_val_0 .
} }
ORDER BY ASC(?sort_val_0) ?entity
LIMIT 25 OFFSET 0
```

(taken verbatim from the server log, not reconstructed)

**This is also invalid SPARQL 1.1.** Under `SELECT DISTINCT`, `ORDER BY` may
only use variables in the projection (§15.1) — precisely because the
deduplication can discard the ordering key. Jena's compiler accepts it, so the
violation surfaces as a Postgres column error rather than a compile error, which
is why it reads as a SQL-generation bug and is really a query-construction bug.

Confirmed by running the logged SPARQL with **only the projection changed**:

| projection | result |
|---|---|
| `SELECT DISTINCT ?entity` | `column s0.v5 does not exist` |
| `SELECT DISTINCT ?entity ?sort_val_0` | 25 rows, first sort value `'129 Tenn Ave Liquor, LLC'` |

## The list path already does this correctly

`KGEntityListProcessor._build_optimized_properties_query`
(`vitalgraph/kg_impl/kgentity_list_impl.py:514`) projects the sort variable:

```python
inner_select = "SELECT DISTINCT ?s ?sort_val WHERE {"
```

and its count query joins the same triple so the total matches (`:855-856`). So
the correct shape exists in the codebase; the KG query builder diverged from it.
Whatever fix lands should look like that one.

## Severity: silent wrong ordering, not a visible error

The HTTP 500 does not reach users. Callers wrap this path in a fallback —
`cardiff-portal-app/backend/.../kg_entity_router.py:129` catches, logs a
warning, clears `sort_slot_type`, and falls through to `list_entities` with
`sort_by=None`. The user clicks a sort header and gets the **default-ordered**
list with no indication anything failed.

That is why this survived: a wrong sort order is indistinguishable from a
working one unless someone checks the values. On the Cardiff portal it is the
"Company" column of the KG Leads table, and it has presumably never worked.

Cost of the fallback is also paid: the failing round trip happens first.

## Fixing it was two things, not one — and the obvious fix was wrong

**Retracted: "add `select_vars.append(f"?{sort_val_var}")` to both branches".**
That was this document's own recommendation, it makes the reported symptom go
away, and it is incorrect. A value reached through a frame or a slot is
**many-per-anchor**: an entity may carry several frames of the sort type and a
frame several slots of it. `SELECT DISTINCT ?entity ?sort_val_0` then yields one
row PER VALUE, so a `LIMIT 25` page holds fewer than 25 entities and repeats
some of them — trading a visible 500 for a silently short page.

Not hypothetical, and not visible on the data the bug was found with. On
`cardiff_kg`:

| | |
|---|---|
| `(entity-graph, slot-type)` pairs holding >1 slot of that type | **9,354** (max 6) |
| naive `DISTINCT` projection, one NurtureAction, `MsgContent` sort | **4 rows for 1 entity** |
| aggregated form, same entity | 1 row |

The first page of KGLeads sorted by CompanyName does *not* expose this — every
lead has exactly one CompanyName slot, so the naive fix passes there. That is
what made it worth checking rather than assuming.

**What was done instead.** Aggregate: `(MIN(?_sort_raw_0) AS ?sort_val_0)` with
`GROUP BY ?anchor`, MIN ascending and MAX descending so each anchor is ordered
by the value that actually determines its position. The `entity_property`
branch already did exactly this for `uri_list` properties; the frame/slot
branches now follow it.

The decision is made **once for the whole query**, not per criterion, because
`GROUP BY ?entity` forbids projecting any other variable bare — so one
aggregated criterion forces the rest. Deciding per-criterion left the mixed case
(a frame/slot sort beside an `entity_property` sort) unrepresentable: it emitted
`(MIN(...) AS ?sort_val_0) ?sort_val_1` under a `GROUP BY`. That case was
already latently broken for `uri_list` + plain entity-property sorts, and is
fixed by the same change.

**Still open: the cost.** See "Part 2" below — partly improved, not solved.

## Part 2 — the cost. Where it goes, what was taken, what is left

### Where the time goes

`EXPLAIN (ANALYZE, BUFFERS)` on the generated SQL, KGLead sorted by CompanyName,
2,863 entities, 25 rows out — **507,492 buffers**:

```
Nested Loop  (rows=68683)          <- frame -> ALL its slots
  q9 hasTextSlotValue  loops=68683   buffers=274,746   <- value fetched for every slot
Nested Loop  (rows=23799)
  q8 hasKGSlotType=CompanyName  loops=23799  buffers=95,201  <- type checked afterwards
```

Each `KGLeadInfoFrame` carries **~24 slots**. The plan walks entity → frame →
*every* slot, fetches the text value for all 68,683 of them, and only then asks
which are CompanyName slots — keeping 2,863. Roughly 73% of the buffers are
spent on rows that are about to be discarded.

The selectivities that should have driven it the other way:

| | rows |
|---|---:|
| KGLead entities | 2,863 |
| KGLeadInfoFrame frames | 2,863 |
| **CompanyName slots** | **5,726** |
| all `hasKGSlotType` quads | 304,858 |
| frame→slot pairs the plan materialises | **68,683** |

### What was taken: pattern order, 17% of the buffers

`_build_sort_bindings` now emits the slot constraints first and walks the frame
path inward-out (deepest frame first, anchor hop last) instead of anchor-first.
Same BGP, same results, different starting point for the planner's search.

| | buffers | interleaved median |
|---|---:|---:|
| anchor-first (before) | 507,492 | 385 ms |
| slot-first (now) | 423,742 | 357 ms |
| same sort pinned to ONE entity | 222 → 222 | unchanged |

**1.08x on time, 1.20x on buffers.** Consistent in direction across three
(entity, frame, slot) combinations and free on the pinned case, which is why it
shipped — but it is a nudge, not a fix. Buffers are the stabler figure; the
timing spread overlaps.

**Retracted before it was written down.** An end-to-end reading appeared to show
869 ms → 364 ms and 1,707 ms → 387 ms. That comparison is invalid: the "before"
numbers were taken seconds after a container restart, against a cold buffer
pool, and the "after" ones warm. The interleaved SQL-level A/B above is the real
number. This is the same cold/warm error `PORTAL_QUERY_PLAN.md` warns about, made
here by the person who wrote the warning.

### What was DELIBERATELY NOT shipped: the remaining 2.9x

This is a decision, not an omission. The change is written, measured, and
correct on the query this issue is about — and it is not in the tree, because it
makes a different and equally common query 87x slower.

Pinning the selective end explicitly — a top-level subquery that resolves the
CompanyName slots and their values first, then walks back to frame and entity —
is worth far more than reordering:

| formulation | buffers | exec |
|---|---:|---:|
| as generated today | 507,492 | 360 ms |
| **subquery pins the slot end** | **279,323** | **125 ms** |
| hand-written CTE, same direction | 114,848 | 138 ms |

Same 25 rows, same order, in all three.

**And it is a severe regression on the opposite shape.** The same sort pinned to
a single entity — the entity-detail page, at least as common as the list:

| | buffers | exec |
|---|---:|---:|
| as generated today | 222 | 0.7 ms |
| subquery pins the slot end | 133,067 | 60.8 ms |

**600x the buffers, 87x slower.**

So the direction cannot be a convention. It has to be chosen per query from
measured selectivity: pin the slot end when the slot type admits fewer rows than
the entity criteria, and the anchor end otherwise. **Both counts are already
available** — `rdf_stats` answers `count by type` in 3 ms, and the numbers this
query needed are the ones tabulated above (2,863 entities against 5,726
CompanyName slots, which is why the slot end wins here and loses when the entity
end is one URI).

### Why this belongs to `048`/`090` rather than to a fix of its own

That per-query choice is exactly what `traversal_decision` exists to make, and
that module is **inert**: its own docstring says "it returns a decision and a
reason, and nothing emits differently yet". Two things would have to change
there, and both are small next to the rest of that work:

1. **A type-constrained end has to count as pinned.** On this query it logs
   `Decision(as-is: neither end pinned, no driving set)`. The slot end *is*
   constrained — `hasKGSlotType = CompanyName`, 5,726 of 304,858 slot-type quads,
   1.9% — but the gate only recognises a URI-pinned end.
2. **Something has to act on the answer.** Today nothing reads the decision.

So the remaining 2.9x is not a separate piece of work from `048`/`090`. It is a
concrete, measured case FOR them, arriving with the gate condition already
established rather than as another shape to characterise: the win, the
regression it must avoid, the statistic that separates the two, and the
formulation that achieves it are all in this document.

One constraint on whoever emits it: the subquery form only avoids `093` (a
subquery inside `GRAPH` returns zero rows) by keeping the subquery at TOP LEVEL
with its own `GRAPH` inside it. Nesting it the other way round returns nothing,
silently.

### Solutions investigated 2026-08-16 — and the one that wins is not the 2.9x

The section above frames the remaining work as "gate the direction choice". That
is still true and still worth doing, but a survey of the alternatives found a
much larger and simpler answer, and eliminated two candidates on evidence.

| option | result | verdict |
|---|---|---|
| Extended statistics on `(predicate_uuid, object_uuid)` | **already in place** | exhausted |
| Semi-join rewrite (`_exists_to_sql`) | **structurally impossible here** | eliminated |
| `frame_entity` collapse | indexes the wrong relation | eliminated |
| Direction gate (pin the selective end) | 2.9x, needs selectivity gate | viable, modest |
| **Denormalised (entity, frame_type, slot_type, value)** | **85x, and flat with page depth** | **recommended** |

#### Extended statistics — already landed, and they do not reach this

`high_cardinality_slot_value_query_plan.md` makes these recommendation (1). They
exist: `stat_cardiff_kg_quad_po` on `(predicate_uuid, object_uuid)`, kinds
`{d,m}`, with `attstattarget` 1000 on subject and predicate.

They are working — the *scan* estimates are good (q4 estimates 2,774 against
2,863 actual; q0 estimates 3,065 against 2,863). The `rows=1` in the plan is
**join** selectivity collapsing across a 6-way join, which is a different
quantity that per-table extended statistics do not describe. Nothing further is
available here.

#### The semi-join cannot apply to a sort — by construction, not by gate

Recommendation (2) of the same document is semi-join generation, and the log
shows it being attempted and abandoned on this query:

```
semijoin: split BGP on ?entity — anchor ['q0'], probe ['mv0','mv1','q1','q4','q5','q8','q9']
semijoin: no join rewritten (1 BGP split(s) reverted)
```

Two independent reasons in `semijoin.py`, and neither is a tunable:

- `:736` — "a semi-join collapses the right side to its join key, so a projected
  value could not be produced from it". **A sort must project the value it sorts
  by.** The traversal that a filter can reduce to EXISTS is the same traversal a
  sort needs an actual value out of.
- `:753` — `KIND_GROUP`: "Aggregates count rows, so collapsing duplicates below
  is never safe". The Part 1 fix put this query under a `GROUP BY`, so the walk
  resets there regardless.

So the general engine fix that rescued the high-cardinality *filter* queries
cannot rescue the *sort*. Worth stating plainly, because the two shapes look
alike and the plan for one has been read as covering the other.

#### The denormalised table — BUILT, and what the prototype got wrong

One row per slot reachable by the entity→frame→slot walk, carrying the value and
the three types the walk discriminates on. SQL-level, `cardiff_kg`:

| | before | after |
|---|---:|---:|
| page 1 | 360 ms / 423,742 buffers | **7.2 ms / 78 buffers** |
| offset 500 / 2000 | 609 ms / O(offset) | **flat** |

An index-only scan with zero heap fetches, so it also answers the O(offset) half
of `078`/`080` for this shape without keyset pagination.

**Two prototype figures were wrong and are corrected here**, because both were
quoted in the "recommended" verdict above:

- **Storage: 38 MB → 170 MB** (304,848 rows), 7.0% of the 2,432 MB quad table
  rather than 1.6%. The prototype covered ONE value predicate at ONE frame depth
  and carried ONE index; the shipped table covers all ten predicates, nested
  frames, and six indexes. Above `edge` at 143 MB, where the prototype figure
  suggested it would be a quarter of it — the conclusion holds, the margin
  quoted did not.
- **Page time: 4.2 ms → 7.2 ms.** Same reason, plus the partial-index fix below.

**A finding that only appeared once there was more than one index.** With the
text, numeric and datetime lanes all indexed on the same four leading columns,
the planner served a TEXT sort from the DATETIME index — identical prefix,
cheaper to scan, and missing `value_text`, so the index-only scan became an
Index Scan with heap fetches: **58 buffers → 2,918, 4 ms → 15 ms.** Making the
num and dt lanes PARTIAL (`WHERE value_num IS NOT NULL`) fixed it, since a
partial index cannot be chosen unless the query implies its predicate. It also
cut the table from 189 MB to 125 MB (both measured on the one-hop table, before
nested frames took it to 170 MB). The single-index prototype could not have
surfaced this.

#### What was built, and what the contract caught

`planning_sql/derived_table_maintenance.md` §"`entity_slot_sort`, added
2026-08-16" has the full account. In this repo:

| | |
|---|---|
| table + 6 indexes | `sparql_sql_schema.py` (space schema, so every new space has it) |
| derivation, incremental + full + drift | `db/sparql_sql/sync_entity_slot_sort.py` |
| read path | `db/sparql_sql/fast_slot_sort.py`, via `kgquery_endpoint._try_fast_slot_sort` |
| write paths | all 8 in `sparql_sql_space_impl.py` |
| recurring repair | `MaintenanceJob._run_entity_slot_sort_integrity`, `scripts/repair_derived_tables.py`, `resync_all` |
| tests | `tests/integration/test_entity_slot_sort_maintenance.py` (6), matrix entry in `test_derived_table_maintenance.py` |

**The generated matrix caught a real gap on the first run.** Adding the table to
`DERIVED` failed on `remove_rdf_quad` — one write path of eight, missed. That is
the failure this repo has already shipped twice, refused in the minute it was
introduced.

**A count-based drift probe cannot see a stale VALUE.** This table stores the
value being ordered by, so repointing a slot leaves the row count identical and
the content wrong; the probe reads zero and `backfill` cannot repair it because
backfill only ADDS. Correctness there rests entirely on the write path deleting
before it re-derives. That is tested directly, and the test was verified to fail
when the delete is removed — after a first version of it did NOT catch that,
because the batch-delete path removes the row by another route and masked it.

#### A coverage hole found after building it, then closed

**The first version walked ONE frame hop** and stored a single
`frame_type_uuid`. That silently excluded every slot under a CHILD frame. On
`cardiff_kg` it removed two of the eight columns the portal's lead list renders:
`GuarantorEmail` and `GuarantorPhone` hang off `PersonalGuarantorContactFrame`,
reached by `Edge_hasKGFrame` 2,863 times and by `Edge_hasEntityKGFrame` zero.

It was found by asking whether the table could also serve the portal's slot
projection (§3/§5) — a question about a different feature — and noticing the
answer was "six of eight columns". Nothing about the table said so; the missing
slots were indistinguishable from slots with no value.

**Fixed by storing the PATH rather than one level.** `frame_type_uuid UUID`
became `frame_type_path UUID[]`, the ordered frame types from the entity down to
the slot's parent, derived by a recursive walk over `Edge_hasKGFrame`. That is
exactly what a `SortCriteria.frame_path` names, so the reader matches the whole
array. Measured on `cardiff_kg` after the change:

| | before | after |
|---|---|---|
| rows / size | 248,549 / 125 MB | 304,848 / 170 MB |
| portal's 8 lead columns covered | 6 | **8** |
| `GuarantorEmail` (depth 2) sort | fell back, ~350 ms | **8 ms**, identical page |

Depth distribution: 248,072 rows at depth 1, 56,770 at 2, 6 at 3. The walk is
bounded at `MAX_FRAME_DEPTH = 6` — nothing in the model forbids a frame cycle,
and an unbounded recursive CTE that meets one does not return.

**A different gap survives, and is now declined explicitly.** Every row is
reached through at least one frame, so a slot attached DIRECTLY to an entity —
`sort_type="frame_slot"` with an empty `frame_path` — is not in the table.
`can_serve` refuses it. Before this pass it did NOT: the reader simply omitted
the frame predicate and would have answered from frame-borne rows, which is a
wrong page rather than a slow one. Found while reworking the same code.

#### Why this was not simply "do the denormalised table"

`high_cardinality_slot_value_query_plan.md` §"Recommendation (3)" declines a
denormalised slot-value table **deliberately**: "general robustness does not need
it; reserve it for known-hot queries needing flat *cold* latency". That judgement
was made about a *filter* query, where the semi-join was the general fix.

For sorts the semi-join is unavailable (above), so the reasoning that justified
declining does not carry over — a sort-by-traversed-value has no general engine
fix waiting behind it. Two things follow, and they should be decided rather than
assumed:

1. Whether "known-hot" covers this. The portal's KG list pages are the shape,
   and they are user-facing; but a per-space derived table for every
   (entity, frame, slot) triple is a schema commitment, not a query fix.
2. **Staleness is the real cost, not storage.** This is a third derived table on
   top of `edge` and `frame_entity`, and both of those have shipped incomplete —
   `041` (empty on every space), `060`, and an edge table once ~25% incomplete in
   production. A stale sort index gives a wrong ORDER, which is exactly the
   silent-wrong-answer class this whole issue is about. It would need
   `resync_all_auxiliary_tables` and the drift audit from day one, not later.

**Recommended order.** Both, in this order, because they are independent and the
first is small: (a) the direction gate, which needs only `traversal_decision` to
count a type-constrained end and something to read its answer, and helps every
traversal shape rather than sorts alone; (b) the denormalised sort table for the
frame/slot sort specifically, entered as a derived-table proposal with its
maintenance obligations, not as a performance patch.

### Not the frame_entity table

Ruled out before measuring anything: `cardiff_kg_frame_entity` is empty, and
`041` says these derived tables are empty on every space, so it looks like the
answer. It is not — `repair_derived_tables.py` states that `frame_entity` indexes
CONNECTOR frames (a frame joining two entities through source and destination
slots), not entity→frame membership. This traversal is membership. Populating it
would change nothing here.

## Tests

Written as an invariant rather than as a test of this query: **every variable a
generated `ORDER BY` names must appear in that query's projection**, enumerated
over every `sort_type` the model declares, so a sixth branch added later is
covered without anyone remembering this document. The branches differing on
exactly this point is what a per-shape test misses.

`tests/unit/test_kgquery_sort_projection.py` — 28 cases, no database.
21 fail pre-fix, covering all four frame/slot sort types × both directions, the
aggregate choice, the mixed-criteria promotion, and the emitted query shape. The
7 that pass pre-fix are deliberate regression guards on behaviour that had to be
*preserved*: `entity_property` must NOT aggregate, an unsorted query must emit
neither `ORDER BY` nor `GROUP BY` (`issues/075` — an invented `ORDER BY ?entity`
sorts on URI text, measured 117x more expensive and selecting a different page),
and the count query must keep the sort join without inheriting the projection.

`tests/integration/test_kgquery_sort_projection.py` — 5 cases, real infra.
All 5 fail pre-fix with the production error verbatim. The fixture gives ONE
entity two slots of the sort type, and its second value is the largest in the
set, so the entity moves from second ascending (MIN) to first descending (MAX).
A 1:1 fixture passes under both the correct fix and the naive one — which is how
this test would have ended up guarding nothing.

*(The first draft of that fixture used `"yankee"` against a `"zulu"`, which is
smaller, so the entity held the same position under MIN and MAX and the test
could not distinguish them. Caught by the test failing on its own expectation.)*

## Related

- **`095` — the same over-acceptance, from the other end.** Filed independently
  on the same day: Jena accepts four forms the SPARQL grammar forbids, one of
  them `SELECT *` with `GROUP BY`, which has no defined answer. This issue is
  what that costs in practice — an invalid projection/ORDER BY combination
  parsed cleanly and failed 500 levels down in Postgres, on a user-facing sort,
  for an unknown length of time. `095` argues post-parse validation in the
  sidecar is "a real option"; this is a data point for it. Validating that every
  `ORDER BY` variable is projected under `DISTINCT`/`GROUP BY` would have caught
  this at compile time with a comprehensible error.
- `test_scripts_internal/kg_portal_queries/PORTAL_QUERY_PLAN.md` §4 — where this
  was found, and what it costs the portal
- `090` / `two_phase_kgquery_paging_plan.md` — the paging cost behind part (2)
- `043` — KGQuery hardcodes entity/frame attachment; same builder, adjacent area
