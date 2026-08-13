# The Fixtures Cannot Express Depth-1 Frames — 98% of Production

## Status: FIXTURE BUILT 2026-08-08 — depth does not change the conclusions

`scripts/generate_depth_mix_dataset.py` builds a uniformly depth-1 fixture by
promoting every child frame to attach directly to its entity. Slot count is
identical before and after (96,925); only depth moves. Loaded as
`sp_lead_depth1`, registered as `lead_fixtures.DEPTH1`.

**The shape matrix run against it says depth changes nothing.** 46 cells are
non-vacuous on both the depth-1 and depth-2 fixtures, and **0 differ in plan
class**; correctness mismatches are 0 on both. So the issues/040/045/046/047
conclusions, all derived on depth-2 data, do hold on the shape that is 98% of
production.

That is a null result, and worth having as one: the gap was real and had to be
closed before anything could be said about it, but having closed it, no finding
needs revising. What remains open is *cost* rather than plan class — depth-1
queries carry 6 quad joins against depth-2's 8, so absolute timings recorded on
depth-2 fixtures remain pessimistic relative to production.

Two things this exercise cost, both worth remembering. The first flatten dropped
everything under the parent's URI prefix, deleting its three sibling frames —
46,300 triples per 500 entities, silently. The second flattened only the Company
chain, leaving every other chain at depth 2, which made every non-Company cell
vacuous. Both were caught by the matrix's VACUOUS verdict rather than by
inspection.

## Original finding

Slot URIs encode their frame containment, so nesting depth is directly
countable. Production against the 10k fixture:

| frame depth | production | 10k fixture |
|---|---|---|
| 1 — `entity → frame → slot` | **1,364,214 (98.0%)** | **0** |
| 2 — `entity → frame → frame → slot` | 26,134 (1.9%) | 387,700 (all) |
| 3 | 1,141 (0.08%) | 0 |

The fixture is **uniformly depth 2**. It contains no depth-1 chain at all, so it
cannot exercise the shape that is 98% of production.

This is not a scale problem — `sp_lead_synth_100k` has the same distribution,
because `generate_lead_dataset.py` clones template graphs that happen to be
uniformly depth 2. Generating more entities produces more depth-2 chains.

## How it surfaced

`scripts/perf_shape_matrix.py` sweeps nesting depth. Its depth-1 cell returned
zero rows on both sides of the differential check, and the sweep reported it as
`VACUOUS` rather than `OK` — a verdict added precisely because an earlier
revision reported "0 mismatches" while comparing empty sets.

Without that distinction this would have read as a passing cell.

## Why it matters

Depth determines join count, and join reduction is the mechanism the edge table,
`frame_entity` and the covering indexes all rely on. Measured on the fixture:

| depth | quad joins, edge rewrite ON | OFF |
|---|---|---|
| 1 | 6 | 10 |
| 2 | 8 | 14 |

So the shape carrying 98% of production traffic is the one where the edge
table's benefit is measured — 4 of 10 joins removed — and it is the one no
benchmark runs. Every KGQuery performance number recorded to date describes the
1.9% case.

The direction is at least conservative: depth 2 is more expensive than depth 1,
so existing benchmarks are pessimistic rather than flattering. That is a better
failure mode than the entity-type (`issues/045`) and page-size (`issues/047`)
gaps, where the fixture tested the easier case and hid real defects. But it
means the numbers do not describe the workload.

## Fix

Give `generate_lead_dataset.py` a depth distribution rather than inheriting
whatever the templates have — ideally matched to the production mix above
(98/2/0.08), or at minimum a `--depth-mix` knob so both shapes are covered.
The manifest should record it, so a bench can assert against the intended mix
rather than assume it.

## Related

- `issues/046` — the other fixture-expressiveness gap, and the duplicate-quad
  dataset built to close it
- `scripts/perf_shape_matrix.py`, `scripts/generate_lead_dataset.py`
