# The Fan-Out Tables Were Never Maintained, and Empty Read as Safe

## Status: FIXED 2026-09-13 — differently for each table, because they differ

Two tables that look like siblings and are not. Both were rebuilt only by a full
resync, neither had an incremental write path, and neither had a drift probe.
The difference is that one is READ on every query and the other is read by
nothing, so the same gap meant opposite things.

    table            write-path syncs   maintenance probes   readers
    edge                    11                 75            query path
    frame_slot              10                 43            query path
    entity_slot_sort        11                 45            query path
    entity_prop_sort        12                  8            query path
    frame_prop_sort         11                  6            query path
    entity_fanout            0                  0            NONE
    edge_fanout              0                  0            query path

## `entity_fanout`: stopped populating it

Nothing read it — not the query path, not an admin endpoint, not a report, not
operator tooling. Two writers, zero readers. Both uses it was kept for were
measured and rejected: choosing the emission shape from a start's fan-out (dedup
won 5 of 6 hub cases, 2026-08-15), and choosing traversal direction (measured
2026-09-13; the ends are kind-constrained SETS, and per-entity hubs aggregate to
near-uniform across kinds — 49.1 to 62.3 — so the rule reduces to "which set is
smaller", which is what the pair counts already measure).

So the rebuild was pure cost, scaling with `frame_slot` as a self-join with a
count(DISTINCT): 1.21 s at 91k rows, 2.51 s at 571k, 4.09 s at 947k. Removed
from `resync_all` and from `repair_derived_tables` — including the PROBE that
decided whether to repair, which was the same self-join and so carried most of
the cost for no result.

The table is still created, still dropped on teardown, and
`resync_entity_fanout` still exists for an operator who wants the hub list.

## `edge_fanout`: it earns its keep, so it is now refreshed

Not the same case, and an earlier note of mine calling the two "identical in
shape" was wrong. `generator.py` loads it on every query and `emit_slice` asks
`assess_traversal` whether a two-phase probe's traversal amplifies.

**It changes plans.** Instrumented across the whole query tier:

    consulted : 61
    safe      : 59
    UNSAFE    :  2   ("hop tail 468 exceeds 16 — this direction fans out")

Load cost is 0.27-0.32 ms per query.

### EMPTY DID NOT MEAN SAFE, IT MEANT SILENT

`emit_slice` guards its use with `if fanout:`, so a space with zero rows skips
the amplification check for EVERY query and gets no protection and no warning.
Absence read as "nothing amplifies" when it meant "nobody measured".

Found on `sp_lead_synth_100k`: **4,977,000 typed edges and zero fan-out rows**,
while every graph fixture had 8-10. That space had been running unguarded.

### What was added

`MaintenanceJob._run_edge_fanout_refresh`, in the cycle and in the per-space
trigger (forced there, like `stats_recompute`, so an explicit request is not
declined by a schedule). Two gates, in cost order:

1. **Empty but carrying typed edges — repaired whenever seen**, regardless of
   schedule, and logged at WARNING, because that space was running unguarded. A
   space with no typed edges is left alone: zero rows is the right answer there
   and flagging it would queue a rebuild that never converges.
2. **Otherwise schedule-gated**, per space and phase-offset, on its own slot and
   its own interval (`VITALGRAPH_EDGE_FANOUT_INTERVAL_S`, default 6h). Its own
   slot so it cannot starve, or be starved by, the stats recompute.

### Why NOT incremental write paths

`compute_edge_fanout` records avg, p99 and max per (edge type, relation type,
direction), so keeping it current under every write means maintaining a
DISTRIBUTION on the write path. Its own docstring rejects that and says a
periodic recompute is enough — the gap was that no periodic anything existed.

It is also deliberately NOT change-gated on row counts, unlike the stats
recompute. Fan-out can shift without the row count moving: rewiring the same
number of edges onto one hub changes the distribution and nothing else, so a
row-count gate would miss exactly the change that matters.

### Verified

    BEFORE  sp_lead_synth_100k  fanout_rows=0   typed_edges=4,977,000
    AFTER   sp_lead_synth_100k  fanout_rows=6   (repaired_empty)
    second call -> None          (schedule gate holds)
    force=True  -> all refreshed (explicit trigger overrides)
