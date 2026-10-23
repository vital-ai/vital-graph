# 297 — The cardinality model guesses where characteristic sets and pairs would count

## Status: OPEN — step 0 (census) run 2026-10-23 and passed; step 1 (offline estimate) is next and not started. K must be data-derived (UW has 1,010 slot types). See "Step 0 census".

**Related:** `issues/293` (the generator's cardinality model; its "Known
limits" name this gap: "Choosing per step needs co-occurrence statistics
(characteristic sets); not built"), `issues/296` (`pg_hint_plan`, which would
carry whatever this model says), `issues/119` §9 (do not hand estimates to
Postgres' statistics), `issues/142` (stats are recomputed, never accumulated),
`issues/153` and `199` (what absence from a stats table means), `issues/163`
(stats are graph-scoped), `planning/planning_performance/query_planner/postgres_planner_c_interface.md`.

## What the model guesses today

`bgp_cardinality.py` prices a flat quad BGP join by join from `rdf_stats`
(pair counts) and `rdf_pred_stats` (rows and distinct objects per predicate).
Measured error (293, `model_vs_pg.py`): geometric-mean q-error **1.42** on the
UW dashboard (the corpus it was tuned on) and **3.73** on leads (held out),
against Postgres' 189.85 and 40.97. The remaining error comes from three
assumptions, each standing in for a statistic we do not collect:

| step | assumption | where it fails (measured in 293) |
|---|---|---|
| subject bound, constant object (`?s hasKGSlotType <S>` after `?s` is bound) | **containment**: min(rows so far, the pair's count) (`step_factor`, `_CONTAIN`) | exact when the pins are correlated (UW: NAICS is 10% of its frame type's slots, 0.1% of all slots); **6x high on uniform data** (leads, a second slot type pinned on probed members: 100,000 estimated, 16,486 actual) |
| object bound, subject free (`?s hasKGGraphURI ?d` after `?d` is bound) | **mean fan-out**: `row_count / object_count` over the whole predicate | blind to which objects are linked at all: on leads, child frames are never the object of `hasFrameGraphURI`, so a frame-type pin probed by object returns **0**; the model said **6.8M** (Postgres 123,701) |
| subject bound, no constant | one value per subject | measured ~1 for nearly every predicate; untested for multi-valued slots |

The cost of this error is direct. `ENFORCE_MIN_GAIN = 10` (`bgp_cardinality.py:259`)
exists because the model's error band reaches ~6x, so a predicted gain below 10x
is not acted on. `category_page`, predicted 4.5x, went from 3.1 s to 9.1 s when
its order was enforced. A tighter model allows a lower gate, so the model's
order is enforced on more queries.

## Definitions

**Characteristic set (CS)** (RDF-3X, Neumann & Moerkotte 2011): the set of
predicates a subject has. Subjects are grouped by their CS. Each CS stores its
subject count and, for each member predicate, its triple count, from which the
mean multiplicity follows. A star `?s p1 ?a ; p2 ?b` is then estimated exactly
as the sum, over every CS containing {p1, p2}, of
`subjects × mult(p1) × mult(p2)`.

**Typed characteristic set**: a CS whose members can also be (predicate,
constant object) pairs, so `hasKGSlotType <S>` is a member and not just
`hasKGSlotType`. That pair is what makes our stars selective. A plain CS can't
distinguish one slot type from another, because every slot is expected to have
about the same predicate set (unverified; step 0 checks it).

**Characteristic pair (CP)** (Gubichev & Neumann 2014): for a link predicate
`?s L ?o` where `?o` is itself a subject, count the links by (CS of `?s`,
CS of `?o`). That is the fan-out of a star-to-star join, split by what is on
each end. A combination that never occurs has no row, which gives the 0 that
the mean fan-out cannot.

## Fit to this data

- **The kind of a subject is free.** Every graph object has exactly one
  `vitaltype`, and every graph object has one. So `vitaltype <T>` is always a
  typed member and partitions every CS by kind. Type-specific predicates
  (`hasKGEntityType`, `hasKGFrameType`) cover only ~12% of objects and cannot
  do this.
- **Choose typed members from the data, not a list.** 183's lesson: slot types
  are values, not schema. Rule: a predicate's object is typed when the predicate
  has few distinct objects (`rdf_pred_stats.object_count` ≤ K, K to be set
  from step 0, e.g. 1,000) and those objects are IRIs. This should select
  `vitaltype`, `hasKGSlotType`, `hasKGFrameType`, `hasKGEntityType`,
  `hasKGFormType`, and not values or graph URIs.
- **Link predicates from the data too**: predicates whose objects are
  subjects in the same graph (`hasKGGraphURI`, `hasFrameGraphURI`,
  `hasEdgeSource`, `hasEdgeDestination`, entity-valued slots). 293's whole
  class is links of this kind.

## What to collect

Both tables are per space and graph-scoped (`context_uuid`, per 163). Both are
written only by `recompute_stats_tables`, as a rebuild (per 142).

**`{space}_char_set`**: one row per (graph, CS, member).

| column | |
|---|---|
| `context_uuid` | graph |
| `cs_id` | a stable hash of the sorted member list |
| `predicate_uuid` | member predicate |
| `object_uuid` | the constant for a typed member; the all-zero uuid for an untyped one (`edge_fanout`'s sentinel convention, so it can sit in the key) |
| `cs_subjects` | subjects with this CS, repeated on each member row |
| `member_triples` | triples of this member over those subjects (multiplicity = `member_triples / cs_subjects`) |

**`{space}_char_pair`**: one row per (graph, link predicate, subject CS, object CS).

| column | |
|---|---|
| `context_uuid`, `link_predicate_uuid`, `subject_cs_id`, `object_cs_id` | key |
| `links` | link triples between the two |
| `distinct_subjects`, `distinct_objects` | so the fan-out is available in both directions |

**Bounding.** The number of distinct CSs is the open risk: RDF-3X merges rare
CSs into supersets for this reason. Keep the top N by `cs_subjects`, as
`rdf_stats` keeps its largest pairs, and define absence explicitly before
anything reads it. An absent CS has at most as many subjects as the smallest
CS stored; that is 153's bound, by the same argument. The tables must never let
an empty table read as "small" (199). A space without these tables, or with
them empty, falls back to today's assumptions.

## How to compute it

- **CS**: the quad PK is `(subject_uuid, predicate_uuid, object_uuid,
  context_uuid)`, so one ordered pass groups by subject without a sort. For
  each subject, build its sorted member list (typed members include their
  object), hash it, then aggregate by (graph, hash). This is a full pass over
  the quads. 293 measured a comparable distinct-subjects pass at **29.7 s on
  74.2M quads** and deferred it on cost, so the cost must be measured first.
- **CP**: needs each subject's `cs_id` at both ends of every link, which means
  a temporary subject → `cs_id` map (10M rows on `sp_lead_synth_100k`) joined
  to the link quads. This is the expensive half: measure it separately, and
  build it only if the CS half proves its worth.
- Maintenance already uses 38% of production database time (143, 239). The
  planning doc's policy applies: **a planning statistic must earn its
  maintenance.** The recompute cost goes into the decision, not a footnote.

## How the model uses it (`bgp_cardinality.py`)

1. **Stars.** Group the BGP's leaves by subject variable, which `_positions`
   already provides. For a star whose members are all tracked (untyped
   predicates, or typed with a constant), the star estimate is the CS sum
   above. This replaces the chain of `_CONTAIN` steps for that star.
   Constants that are not typed members (a value literal, say) apply as a
   selectivity within the CS, using today's pair count.
2. **Links.** A leaf probed by object, where the object variable is the
   subject of another star, takes its fan-out from `char_pair` restricted to
   the CSs compatible with each star. If no row matches, the estimate is **0**,
   which fixes the child-frame case.
3. **Anything else** keeps today's step: containment, mean fan-out, or `None`
   for unpriced. The existing rule still holds: an unpriced factor is reported
   as unknown, never guessed.
4. **Order search is unchanged** (`choose_order`). Only the prices change.

## Plan, each step a gate

0. **Census (no code in the server).** A script on `uw_prodshape` and
   `sp_lead_synth_100k`, per `vitaltype`: count the distinct untyped CSs,
   distinct typed CSs, and subjects in the top 10 / top 100 CSs. Also count the
   distinct (subject CS, object CS) combinations per link predicate.
   **Stop here if** typed CSs per kind are either ~1 (so containment is
   already exact) or tens of thousands (so they can't be stored).
1. **Offline estimate.** Feed the census output to `model_vs_pg.py` as an
   alternative model, with no schema change. It must:
   - improve leads' 3.73 without making UW's 1.42 worse;
   - fix the two named cases (16,486 and the child-frame 0);
   - be checked on a larger held-out set than 9 + 6 queries: the
     161/118/045/138/218 shapes and wordnet.
2. **Collect.** Migration script (opt-in per space, like `object_count`,
   created by the script and never as a side effect, run as the app role,
   idempotent for every install) plus the recompute. Measure the recompute cost
   on the 74.2M-quad space and the table sizes.
3. **Use.** Steps 1–3 of "How the model uses it" above, behind the same
   `plan_decisions` recording as `model_join_order`.
4. **Revisit `ENFORCE_MIN_GAIN`** against the new error band. Re-measure
   `category_page` and every shape whose order changes, with identical result
   multisets and loops on the busiest node as the measure.
5. **Decide.** Keep only if a plan decision changes for the better on a
   workload. Otherwise remove the code, the tables and the migration, as 293
   decided for `object_count`.

## Not in scope

- **Feeding this to Postgres' statistics.** 119 §9: a corrected estimate there
  flipped a good nested loop to a 93x hash join. If anything carries these
  numbers to Postgres, it is 296's per-statement hints, with method and order
  pinned.
- **Edge and `frame_slot` tables.** Still unmodelled (293). Characteristic
  pairs on `hasEdgeSource`/`hasEdgeDestination` could price edge-table hops
  later; that is a follow-on, not part of this issue.
- **Freshness between recomputes.** Same behaviour as `rdf_stats`: stale
  after a bulk load until the next recompute, never silently wrong.

## Dependency on model coverage (recorded 2026-10-22)

This issue is stage 6 work (`issues/293`: the model replaces `reorder_joins`'
single-pattern root, the semi-join anchor and the `selective-driven` gate,
retiring the class's route-arounds). Its reach depends on the model covering
**edge and `frame_slot` tables**, which it does not yet: KGQuery's paths, where
the semi-join and `selective-driven` decisions actually run, go through those
tables, so without that coverage there are no model prices to sharpen. Order:
(1) model coverage of edge/`frame_slot` tables; (2) 297's census and pairs,
then 296's arms, each where coverage exists, each judged by the statistics
policy (a decision changes, measured). The UW dashboard's two remaining slow
queries are NOT addressed by this issue: `only_cause` is a correlated
`NOT EXISTS` SubPlan and `category_page` an unhashable `IS NULL OR` join
condition, both structural, pursued separately under 293. Production's quiet
slow log is not evidence against stage 6: it is quiet partly because the
route-arounds fixed each shape after it reached production.

## Step 0 census, run 2026-10-23: proceed

`test_scripts_internal/kg_uw_decision_reasons/cs_census.py` (read-only; per
vitaltype: plain and typed CSs, top-10/100 coverage; per link predicate: links
and distinct (subject CS, object CS) pairs). Outputs in `cs_census/`.

**K must come from the data.** At K = 1,000 `hasKGSlotType` was not typed on
`uw_prodshape2`, which has **1,010** slot types (341 with 100+ slots). Every
slot kind then collapsed to one CS. At K = 2,000 it is typed. A fixed K
silently drops the member that makes stars selective.

| space | kind | subjects | typed CS | in top 100 |
|---|---|---|---|---|
| `uw_prodshape2` (K=2000) | KGTextSlot | 433,272 | 357 | 96.8% |
| | KGFrame | 161,974 | 181 | 99.1% |
| | KGURISlot | 40,099 | 1,326 (hasUriSlotValue typed too) | 96.9% |
| | other slot kinds | 20k-100k each | 8-172 | 98-100% |
| `sp_lead_synth_100k` (K=1000) | KGFrame | 1.2M | 12 | 100% |
| | slot kinds | 100k-1.15M each | 1-16 | 100% |

Link predicates, distinct (subject CS, object CS) pairs: UW at most 2,845
(`hasFrameGraphURI`), leads at most 138 (`hasKGGraphURI`), `hasFrameGraphURI`
70.

Against the stop rule: typed CSs per kind are neither ~1 nor tens of
thousands, and the pair tables are small (thousands). **Step 1 (offline
estimate) is justified.** Expectation: on UW a slot's typed CS is essentially
its slot type, which containment already prices exactly (the model's UW
q-error is 1.34 on the corrected fixture), so the gain is on lead-like data,
where the two named misses live (16,486 vs 100,000; the child-frame 0).
