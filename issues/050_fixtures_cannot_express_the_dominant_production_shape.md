# The Fixtures Cannot Express Depth-1 Frames — 98% of Production

## Status: OPEN — measured 2026-08-08

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
