# The Semi-Join Rewrite Silently Does Not Apply When the Caller Filters by a Specific Entity Type

## Status: FIXED 2026-08-07 — 24.5-32.3s → 2ms, verified against ground truth

> **Buffer-pool review — see `issues/081`. LIKELY UNAFFECTED.** The re-run on a 16 GB pool left these warm timings unchanged; these queries read tens of thousands of buffers and fit in the old 1 GB pool. Original note follows.
>
> _(superseded)_ At risk: semi-join magnitudes (24.5-32.3s -> 2ms). `shared_buffers` was 1 GB on a 64 GB machine against queries touching 400,000+ buffers; raising it to 16 GB moved a comparable query 16,411 ms -> 616 ms with no code change. Plan shapes, row counts and buffer counts are unaffected.

`semijoin._split_bgp` / `_split_anchors` partition a single BGP into
`JOIN(anchor, rest)` around the projected variable, so the rewrite can see a
boundary that the collect stage did not create. Option (1) below; the builder is
untouched.

| | before | after |
|---|---|---|
| specific entity type, page of 50 | 24,465–32,343 ms | **2 ms** warm, 23 ms cold |
| full result set | 34,423 rows | 34,423 rows, 0 duplicates |
| deduplicated set md5 | `dd0b028c…` | `dd0b028c…` — unchanged |

The anchor splits to `q0`, the probe to the seven remaining tables, and the gate
then scores `34,659/35,987 = 0.963`. Result set is byte-identical to the
set-based path and matches the recorded ground truth of 34,423.

**One trap on the way, worth keeping.** The split alone made things *worse* —
81–122 s, a 3–4x regression — because the DISTINCT added for `issues/046` let the
planner satisfy dedup with a blocking `HashAggregate` and sort afterwards, so
every one of 35,987 candidates was probed before LIMIT saw anything. `DISTINCT ON`
has only one implementation, Unique over sorted input, so it forces the
index-ordered scan to survive: 52 probes instead of 35,987. The two fixes are
coupled, and neither is correct alone.

**The split is speculative and gets undone.** A split BGP is equivalent to the
original only *as a semi-join*: the split drops the cross-link constraint tying
the halves together, because the EXISTS correlation replaces it. If the gate then
declines and the node stays an ordinary JOIN, that constraint is simply gone.
Caught by the new test: a criterion at 1.0% selectivity fell below
`MIN_SELECTIVITY`, kept the split as a plain join, and returned **0 rows instead
of 96**. `mark_semijoins` now reverts every split the walk did not go on to mark.

The pass also logs what it did — marked, split, reverted — so a decline is
visible instead of silent.

Two regression tests added to `test_kgquery_growth_curve.py`, both parametrised
over generic and specific entity type: one bounds the specific-type page cost
against the generic one, the other asserts no page repeats an entity.

`issues/040` shipped a semi-join rewrite that made KGQuery paging O(page).
It only fires when the plan contains a two-child `KIND_JOIN`. Whether one exists
turns out to depend on **which entity type the caller asks for**, and in the
common production case it does not exist, so the rewrite is skipped entirely —
no warning, no log line, no fallback notice.

## Measured, same space, same data, same frame/slot criteria

22.4M-quad restored production space, 50-row page, the query from
`planning/planning_performance/high_cardinality_slot_value_query_plan.md`
(slot value matching ~34.6k of ~38.6k candidates).

| `entity_type` | plan the pass receives | rewrite | cold | warm |
|---|---|---|---|---|
| `haley-ai-kg#KGEntity` (generic) | `JOIN(bgp[2], bgp[12])` | ✅ fires | 186 ms | **2–4 ms** |
| a specific entity-type URI | `bgp[13]` — one BGP | ❌ never considered | — | **24,465–32,343 ms** |

Three warm runs each. Nothing differs but the entity type.

The gate itself was never the obstacle. When a JOIN exists it evaluates
`34,659/38,621 = 0.897` against `MIN_SELECTIVITY = 0.05` and probes — one of the
most favourable ratios possible. In the specific-type case `_selective_enough`
is **never called at all**: the tree is

```
slice
  distinct
    project
      order
        bgp  tables=13        <- no KIND_JOIN anywhere
```

and `mark_semijoins._walk` only marks `KIND_JOIN` nodes with exactly two
children, so it walks to the BGP and returns having done nothing.

## Root cause

With `entity_type = KGEntity` the builder emits the anchor
(`?entity vitaltype KGEntity`) as its own group, which collects into a separate
2-table BGP — giving `JOIN(anchor, frame-chain)`, exactly the shape the pass
looks for. With a specific entity type the `hasKGEntityType = X` triple is folded
into the same basic graph pattern as the frame chain, so collect produces a
single BGP and there is no join node to rewrite.

Nesting is *not* the factor — checked directly. Flat (`entity → frame → slot`)
and nested (`entity → frame → frame → slot`) criteria both produce a JOIN when
the anchor is generic, and the lead fixtures use the nested form, so both shapes
were covered by the `issues/040` benchmarks. The entity-type axis was not.

## Why it was missed

Every fixture behind `issues/040` passes `entity_type=KGENTITY`
(`test_kgquery_growth_curve.py:185`), the generic vitaltype. So the benchmarks
exercised only the shape that produces a JOIN. The API benches inherit the same
criteria. Nothing in the suite asks for a specific entity type, which is what
production actually sends — see the wire payload recorded in the plan doc.

## Fix

The rewrite is valid here; the pass just cannot see an opportunity because the
opportunity is inside a BGP rather than between two of them. Options, roughly in
order of appeal:

1. **Split the BGP in the pass.** Where a BGP contains an anchor subset binding
   only the projected variable plus a remainder whose variables are all private,
   partition it into `JOIN(anchor, rest)` and mark that. Keeps the rewrite in one
   place, and the selectivity gate then applies unchanged.
2. **Have the builder emit the specific-type anchor in its own group**, matching
   what it already does for the generic type. Smaller change, but it makes the
   optimisation depend on a builder detail that is easy to regress silently —
   which is exactly how this arose.
3. **Recognise the single-BGP case in `emit_slice`** and drive the two-phase page
   from the anchor tables directly.

Whichever is chosen, the pass should **log when it declines**. A rewrite worth
4 ms vs 24 s should not be able to skip itself without saying so; every failure
mode found so far in this area (`leaf_terms` dropped by
`prune_union._replace_plan_in_place`, range criteria invisible to the gate, and
now this) has been silent.

## Add to the suite

`test_kgquery_growth_curve.py` should parametrise over entity type — generic and
specific — not just over state/threshold. That one axis would have caught this,
and would catch a regression of whichever fix lands.

## Reproduce

```bash
./scripts/probe_semijoin_entity_query.sh                    # specific type: one BGP, no rewrite
PROBE_ENTITY_TYPE="http://vital.ai/ontology/haley-ai-kg#KGEntity" \
  ./scripts/probe_semijoin_entity_query.sh                  # generic: JOIN, rewrite fires
```

The script derives the space, graph and criteria URIs from the restored
production copy on the local cluster, and prints the plan tree
`mark_semijoins` receives, the gate's own decision line, the SQL, and three
timed runs.

## Related

- `issues/040` — the rewrite this narrows
- `planning/planning_performance/high_cardinality_slot_value_query_plan.md` —
  the query this was found with; its recommendation (2) is only half-delivered
  until this is fixed
- `planning/planning_performance/two_phase_kgquery_paging_plan.md` — the shipped
  design, which does not state this precondition
