# Nothing Reads A Slot Value Out Of `entity_slot_sort`

## Status: BUILT 2026-09-16. `slot_projection` on `POST /kgqueries` returns
## `entity_slot_values` — entity URI -> alias -> LIST of values — served from
## `entity_slot_sort` on ALL THREE entity paths and gated on the same
## block-list the filter uses. Verified end to end on a 74.5M-quad space: 25
## entities x 8 columns across 7 frame paths, **200 of 200 values filled, 3.3-6.3
## ms server-side**, against the 18,000-quad `include_entity_graph` fan-out it
## replaces. Design decisions and what is NOT covered are below.
##
## The measurement that preceded it, kept because it is what justified building: A 25-entity, 8-column projection costs **0.76 ms
## and 1,163 buffers** against **57.65 ms and 62,953 buffers** for the same
## eight values from the quads, identical values, on a 74.5M-quad fixture. The
## projection adds a FLAT ~390 buffers over the page selection it rides on, at
## every offset from 0 to 90,000. Two claims written below before measuring
## were wrong and are struck through where they appear.

**Related:** `issues/096` (why the table exists), `issues/161` (the filter),
`issues/172` (how the last gap of this shape was closed), `issues/207` (why
projecting slot values through SPARQL is expensive), `issues/209` (the hydration
route that exists and is silently dropped)

## The ask

A third consumer of `{space}_entity_slot_sort` that PROJECTS — reads
`value_text` / `value_num` / `value_dt` out and hands them back — plus a route
to reach it from the kgentities/query surface.

## What is already there

`sparql_sql_schema.py:1201`. One row per `(slot_uuid, context_uuid)` carrying
`entity_uuid, frame_uuid, entity_type_uuid, frame_type_path, slot_type_uuid`
and the value in three lanes. Maintained incrementally on every write path since
`issues/187` closed 2026-09-12.

FOUR readers today, and the claim holds for all four: every one of them uses the
value as a SEARCH KEY, and none reads it out.

| reader | what it asks | what it projects |
|---|---|---|
| `fast_slot_sort.py` | order a population (and, since `172`, filter it too) | entity URI |
| `fast_slot_filter.py` | select a population | entity URI |
| `slot_sort_range.py` | narrow a SPARQL range criterion (`issues/111`) | `slot_uuid` |
| `component_intersect.py` | one uncorrelated `IN` constraint per component | `entity_uuid` |

`sync_entity_slot_sort.py:57` says it outright: *"STILL NOT A GENERAL SLOT
PROJECTION."* It says it about a different hole — slots hanging directly off an
entity are not in the table — but the sentence covers this one too.

## The index points the other way

All three lane indexes (`sparql_sql_schema.py:1724-1748`) are

    (context_uuid, entity_type_uuid, frame_type_path, slot_type_uuid,
     <value lane>, entity_uuid)

The value sits BEFORE `entity_uuid`. That is built for the filter's question —
seek on a value, read out entities, index-only, no heap access — which is where
`issues/161`'s 13.9 s -> 46.9 ms comes from.

A projection asks the inverse. It already HAS the 25 entities of a page and
wants their values. Two ways to get them from what exists:

  * `idx_{space}_ess_entity (entity_uuid)` — 25 probes plus heap fetches. The
    value columns are not in that index, so it is not index-only. Probably
    cheap; nothing has measured it.
  * A prefix scan of `(context, entity_type, frame_type_path, slot_type)` with
    `entity_uuid` as a filter — index-only, and it reads the whole population
    of that type to find 25 rows. The schema comment already prices that
    neighbourhood: `count(DISTINCT entity_uuid)` over this table measured
    **5,677 ms** on the 53.4M-quad space.

So "the data is already indexed for exactly this probe" is true of the filter
and not of the projection. It is a different access path with no number behind
it, and the first thing to do is measure it.

## The cost case that is actually there

What a projection replaces is `include_entity_graph`, and that IS measured —
`tests/performance/test_entity_graph_fanout_bench.py`, on `lead_nurture_grouped`
(74.5M quads, the only fixture carrying `hasKGGraphURI` at scale):

    steady state, 25-entity page    +80-290 ms      ~18,600 quads
    first touch (cold buffers)      3.2-4.3 s

`_fetch_entity_graphs` issues ONE SPARQL with `VALUES` and a two-branch UNION;
branch 2 — everything pointing back at the entity — is the expensive half and
the whole product value of the flag.

A list view rendering 8 slot columns over 25 rows wants ~200 values. It is
currently served ~18,600 quads and throws nearly all of them away.

`issues/207` is the other side of the same coin: projecting slot values through
SPARQL is exactly the shape that got expensive, because each datatype has its
own value predicate. A projection from this table sidesteps that entirely — the
three lanes are already split by datatype and already denormalised.

## MEASURED 2026-09-16

`lead_nurture_grouped` on the vg-test stack — 74.5M quads, 4,064,529 slot-sort
rows, 100,000 entities of one type at ~40.6 slots each. The same fixture
`test_entity_graph_fanout_bench` uses, so the comparison is like for like.

One 25-entity page at offset 1,000, EIGHT columns — CompanyName, LeadStatus,
MQLRating, CompanyCity, CompanyState, StartDate, MonthlyGrossSales, LeadAge —
spanning **seven distinct frame paths** and all three value lanes. Warm, median
of 4-5 `EXPLAIN (ANALYZE, BUFFERS)` runs, root-node buffers.

    variant                                            ms    buffers   rows
    page alone (the sort fast path, for reference)   0.42        766     25
    A  entity-led probe, 8 columns at once           0.35        276    200
    B  prefix-led, 8 arms (one per frame path)       1.82      2,208    200
    C  A + the term join that yields entity URIs     0.81      1,076    200
    E  page + projection, ONE statement              0.76      1,163    200
    D  the same 8 values from the QUADS             57.65     62,953    200

**76x on time, 54x on buffers, and the values are identical** — all 200
`(entity, slot)` pairs from the table match the quad walk, checked in the same
script.

D is a CHARITABLE baseline, not a strawman: it is hand-written as one required-
pattern arm per column, the form `issues/207` concludes is the good one. The
general pipeline does not get to be better than this; it can only be worse.

### The projection is flat in the offset; the PAGE is not

Variant E minus the page CTE alone, same page size, by offset:

    offset      page ms   page buf    +proj ms   +proj buf   projection adds
         0         0.04         21        0.57         413      392 buffers
     1,000         0.42        766        0.78       1,163      397
     5,000         1.27      3,733        1.84       4,122      389
    15,000         3.88     11,072        4.47      11,466      394
    90,000        24.32     65,846       27.92      66,247      401

The projection costs **~390 buffers and ~0.5 ms whatever the offset**, because
it is bounded by the page. What grows is the page SELECTION — the ordered index
scan skipping N tuples before it returns 25 — which is the existing sort fast
path and not this. Worth knowing separately: `issues/096` recorded that path as
flat to offset 2,000, and it is, in per-row terms; the skip is still linear and
reaches 24 ms / 65,846 buffers at offset 90,000.

Page size, variant E: 25 -> 0.83 ms / 1,163 buf; 100 -> 2.71 / 2,417;
500 -> 15.45 / 9,035. Linear in rows returned, as it should be.

### Why the index direction turned out not to matter

The plan for A:

    Bitmap Heap Scan   276 buffers (54 index + 222 heap), 0.71 ms
      Rows Removed by Filter: 825
      ->  Bitmap Index Scan on idx_*_ess_entity   1,025 rows

Not index-only — the value columns are not in `idx_*_ess_entity`, exactly as
predicted — and it does not matter, because 25 entities is 222 heap blocks. The
heap is 80% of a 0.35 ms probe. A covering index (`INCLUDE` the three lanes)
would remove it and is not worth a second index on a 2.3 GB table; recorded so
the next reader does not re-derive it.

Two consequences worth keeping:

  * **The probe reads every slot of each entity — 1,025 rows to return 200.**
    Cost tracks SLOTS PER ENTITY, not columns requested. Asking for one column
    costs what asking for forty costs. Good news for a wide list view.
  * ~~Eight columns spread across different frame paths cannot share one
    probe.~~ **WRONG, and measured wrong.** That is true only of the
    prefix-led shape (variant B), which is the one the measurement says not to
    use. The entity-led probe does not touch `frame_type_path` at all, so seven
    frame paths cost one probe — and B, which does need an arm per path, is 5x
    slower and 8x the buffers.

### Two of the four correctness questions, counted 2026-09-16

**A slot carrying two value predicates does not happen here.** Of the 4,064,500
slots with a value on `lead_nurture_grouped`, **zero** carry more than one value
predicate and zero carry more than one value (max 1 of each). So the arbitrary
row `ON CONFLICT ... DO NOTHING` keeps is latent on this data — a documented
edge rather than a live wrong value. Not proof for production, which this
fixture only imitates.

**Several slots of one type on one entity DOES happen.** Across the seeded
spaces, `(entity, slot_type)` pairs with more than one slot:

    sp_lead_synth_100k      4,064,500 rows        0 pairs
    sp_lead_types              81,290             0
    sp_lead_dup                20,323             0
    space_lead_dataset_test    13,934             0
    sp_sql_lead_dataset        13,934             0
    sp_kg_rel                   4,875             0
    kg_load_test                6,400         1,200 pairs, up to 3

and `sparql_sql_schema.py:1191` records 9,354 such pairs on `prod_kg`, up to 6.
So the projection rule for a multi-valued slot is a real decision and not a
hypothetical: on `kg_load_test` a naive projection emits an entity three times,
or picks one of three values with nothing saying which.

### Cold

Not established, and the honest reason is that it cannot be from here.
PostgreSQL's cache needs a restart to empty, this fixture is largely resident in
a 16 GB `shared_buffers`, and first-touch samples at untouched offsets read only
45-210 buffers with wall times (57-292 ms) too noisy and non-monotonic to report
as a curve — one sample each, on a machine running other containers. The one
comparison worth keeping from that pass: at the same fresh, deep offsets the
quad side ran 2.2-3.5 s against the table's 0.33-0.56 s, which is the regime
`test_entity_graph_fanout_bench` records for its cold fan-out.

### Conditions

vg-test stack, PostgreSQL 18.4, `shared_buffers` 16 GB, `random_page_cost` 4 —
which is NOT production's 1.1 (`issues/191`), so plan choice here is
conservative relative to prod. `pg_stat_user_tables` shows no analyze for any of
the three tables, so the estimates are poor (7,160 against 90,025 actual on the
page scan) while the plans chosen are the natural ones; nothing was ANALYZEd for
this, because doing so would perturb the perf baselines.

    test_scripts/perf/_issue208_projection_probe.py     A-E, agreement check
    test_scripts/perf/_issue208_attribute_offset.py     page vs projection
    test_scripts/perf/_issue208_cold_vs_offset.py       cold vs deep offset

### One mistake, recorded because it generalises

The first pass summed EVERY `Buffers:` line in the plan. A node's line includes
its children's, so that counts each buffer once per level of nesting and
inflated everything 4-6x — it read the one-statement form at 264,318 buffers
where the root node says 66,247. The root's line is the total, and it is the
first one `EXPLAIN` prints. The ratios happened to survive; the absolute numbers
did not.

## BUILT — what shipped, 2026-09-16

**The surface.** `slot_projection: List[SlotProjection]` on `KGQueryRequest`,
each column naming `alias`, `frame_path`, `slot_type` and `slot_class_uri`.
Response: `entity_slot_values: Dict[str, Dict[str, List[Any]]]` — entity URI,
then alias, then the values. Client: `query_entities(..., slot_projection=[...])`.

**The three decisions, as taken:**

  * **The caller names `slot_class_uri`**, exactly as `SortCriteria` and
    `SlotCriteria` already require, and that is what picks the lane. The table
    does not record which value predicate produced a row, so nothing else can
    decide it. A wrong class reads the wrong lane and yields nulls rather than a
    wrong value, because a text slot has no `value_num`.
  * **Values come back as a LIST**, always, one element in the common case. An
    entity carrying several slots of one type is real — 1,200 pairs on
    `kg_load_test` at up to 3, 9,354 on `prod_kg` at up to 6 — and returning one
    of them would be a choice the caller never made. Sorted, so two identical
    requests render them identically.
  * **`entity_slot_sort` only.** Frame-borne slots, which is what the
    measurement covers. `entity_prop_sort` and direct entity properties are not
    in this and are the obvious next increment.

**It reaches all three entity paths** — the slot-sort SORT path, the slot-sort
FILTER path, and the general SPARQL pipeline — as a shared step after the page
is chosen, not a fourth gate. That is `issues/209`'s lesson applied before
rather than after: a field populated on one path and absent on the others is
indistinguishable, from the caller's side, from a field that does not work.

**Gated on `slot_sort_is_blocked`**, including on the general path. The page
there is authoritative (it came from the quads) and the columns still come from
the derived table, so a short table renders a BLANK COLUMN that reads as "no
value set" — the filter's asymmetry, not the sort's. Blocked means the field is
absent and the log says so, never empty columns.

### Verified end to end

`lead_nurture_grouped`, 25 entities, the same eight columns across seven frame
paths, through `POST /kgqueries`:

    case                          uris   ents   values    quads      ms
    general  + projection           25     25      200        0   3,981
    fast sort + projection          25     25      200        0     194
    fast filter + projection        25     25      200        0     138
    fast sort, include_entity_graph 25      -        -   18,000     533
    fast sort, neither              25      -        -        0     126

200 of 200 filled, and a row reads as it should:

    company  ['M&M Insulation Co']      city     ['Dyer']
    status   ['...enum:LeadStatus:Working']  state    ['Tennessee']
    mql      ['15.3']                   started  ['2020-07-03T00:00:00']
    age      ['14.3']                   sales    ['17564.78']

The wall-clock column is single samples over HTTP on a busy machine — indicative
only. The repeatable number is the server's own, logged per request:

    Slot projection: 25 entities x 8 columns, 3.3-6.3 ms   (warm)

against 533 ms for the fan-out that returns 18,000 quads to render the same
eight columns, on the same page, in the same state.

### The gap between 0.35 ms and 3.3 ms, since both are in this file

The SQL is 0.35 ms by `EXPLAIN ANALYZE` and 1.41 ms through asyncpg from the
host; the endpoint logs 3.3-6.3 ms. The difference is the round trip plus
assembling the dict in Python, and it is not worth chasing.

What IS worth recording: the FIRST execution on a fresh pooled connection cost
**33-92 ms** — prepare and plan, per connection, because asyncpg's statement
cache is per-connection. A low-traffic deployment with a large pool pays that
repeatedly rather than once. Measured, not modelled: 91.9 ms first, 1.41 ms
median of the next eleven, same connection.

### Not covered, deliberately

  * Direct entity properties (`entity_prop_sort`). A real list view mixes them
    with slot values; this is slots only.
  * Slots hanging directly off an entity. Not in the table at all
    (`sync_entity_slot_sort.py:57`), which is why `frame_path` is required
    rather than optional — an empty path would project as absent rather than as
    an error.
  * `count_only`, which has no page to project.
  * Numeric and datetime values cross the wire as STRINGS, as every other value
    on this API does. Lossless, and consistent with SPARQL JSON results.

## Four things that decide wrong answer vs slow answer

**1. Term type is not stored.** `value_text` holds the lexical form for URIs AND
strings (`slot_sort_range.py:185`), and the row does not retain WHICH value
predicate produced it — `sync_entity_slot_sort.py:246` matches
`predicate_uuid = ANY($6)` over the ten `SLOT_VALUE_URIS` and drops the
predicate. A sort or filter does not care, because the caller supplies
`slot_class_uri` and that picks the lane. A projection has to render a term.
The available escape hatch is to require `slot_class_uri` per projected column,
exactly as the sort and filter surfaces already require it. No language tag
survives, and booleans live in the text lane.

**2. Multi-valued slots have no projection rule.** One row per SLOT, and an
entity may carry several slots of one type — `sparql_sql_schema.py:1191`
measured 9,354 such pairs on `prod_kg`, up to 6. A sort collapses them with
MIN/MAX; `entity_prop_sort` solves the same problem by storing `value_all`
alongside the MIN. A projection must state its rule rather than inherit one.

**3. A slot with two value predicates keeps an arbitrary row.**
`_ON_CONFLICT` is `ON CONFLICT (slot_uuid, context_uuid) DO NOTHING`, and its
comment says "keeping the first is deterministic". The PK dedupe is
deterministic; WHICH row wins is whatever the scan emitted first. That is noise
inside an ORDER BY and it is the value a user reads in a column.

**4. The failure mode ranks with the filter's, not the sort's.** A short table
makes a projected column BLANK, which reads as "no value set" — plausible, no
error, no way to tell. That is the asymmetry `fast_slot_filter`'s docstring is
built around and why `issues/149` matters (a production type at 1.05% coverage
while its own drift probe reported converged). Any projection goes behind
`slot_sort_is_blocked`, same gate as the filter. And frame-borne slots only: a
slot attached directly to an entity is not in this table, so those columns are
holes the surface must decline rather than render empty.

`frame_type_path` must still be matched WHOLE where it is matched at all —
`component_intersect.py:39` records that a loose match admits entities reached
by a different path, and `fast_slot_sort.sort_keys` requires every key to share
ONE path for that reason. An entity-led projection sidesteps it: the probe is on
`entity_uuid`, the path is returned rather than matched, and the caller maps
`(frame_type_path, slot_type_uuid)` back to its column. Measured at seven
distinct paths in one probe. That is also the ONLY sound way to do it — matching
a path loosely to save a probe is the wrong-rows failure `component_intersect`
names.

## The shape to build, and the precedent against a third module (AS BUILT)

`issues/172` was the same class of gap — two gates each declining the other's
input — and it was NOT fixed with a third module. `fast_slot_sort` was widened
to take frame criteria as EXISTS clauses, and it now serves sort, frame filter
and entity-property filter together.

Projection is orthogonal to selection: it applies to whatever chose the page.
Built as a fourth gate it would have to re-implement selection to have a page to
project. Built as a shared step invoked AFTER the page is fixed, it is reachable
from both fast paths and from the general pipeline — which is also the only way
it does not reproduce `issues/209`, where a response field is populated on one
path and silently absent on two others.

Surface: a `slot_projection` list on `KGQueryRequest` (frame path, slot type,
slot class, alias) and a new response field. Not `entity_graphs` — that is
`{s,p,o,g}` quads and the wrong shape to overload.

Worth deciding at the same time whether `entity_prop_sort` participates. A real
list view mixes slot values with direct entity properties, that table is the
sibling for the second kind, and it already stores `entity_uri` inline where
`entity_slot_sort` needs a term join to produce one.

## Not yet established

- ~~What the projection probe costs.~~ MEASURED above: 0.76 ms / 1,163
  buffers for page-plus-projection, 76x cheaper than the same values from the
  quads. What is NOT measured is the END-TO-END request — this is SQL through
  one asyncpg connection, and the fan-out figures it is compared against are
  HTTP round trips including response serialisation.
- Whether the same shape holds on a space whose entities carry FEWER slots. The
  probe reads every slot of each entity, so its cost is set by slots-per-entity
  (~40.6 here) and this fixture is on the heavy side.
- Whether the portal's list view is the only caller, and which of its columns
  are frame-borne slots versus direct properties. `issues/096` records eight
  columns on the lead list; two of them (`GuarantorEmail`, `GuarantorPhone`)
  are reachable only through a child frame, which is why `frame_type_path` is a
  path.
- Whether a caller wants ALL values of a multi-valued slot or one, and whether
  `value_all`'s approach on `entity_prop_sort` is the answer here too.

## Reproduce

The gap: `grep -n "value_text" vitalgraph/db/sparql_sql/*.py` — every hit is a
WHERE or an ORDER BY.

The cost of the thing it replaces:
`tests/performance/test_entity_graph_fanout_bench.py`, which needs
`lead_nurture_grouped` and skips without it.
