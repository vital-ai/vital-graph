# `shape.node_types` Reports a Regression When Two Siblings Swap Places

## Status: FIXED 2026-08-20 — the counts gate, the order reports

`perf_compare` now compares the node-type MULTISET for the gate and surfaces an
order-only difference as information:

    a pure sibling reorder      ℹ️  same 39 entries, different order
                                    (Index Only Scan, Index Scan) — sibling
                                    order is not meaningful (issues/113)
    an index scan -> seq scan   ❌  gained ['Seq Scan'], lost ['Index Only Scan']

Both verified against the real baseline, and the historical case confirms it: the
run that produced this finding reports 0 failing, and against the 2026-08-18
baseline where the difference first appeared it now reads as informational with
the moved nodes named.

The failure message is also readable now. It used to print both 39-element lists;
it prints the difference.

**Option 1 was taken, with option 3's objection kept visible.** A multiset cannot
see a parent/child swap that preserves it — a `Sort` above a `Gather` versus the
reverse. That is exactly why the order difference is REPORTED rather than
dropped, and it is pinned as a known limit in
`tests/unit/test_shape_comparison_ignores_sibling_order.py::TestWhatThisCannotSee`
so it is a stated trade rather than a surprise. If it ever needs to gate, the fix
is the structural tree comparison, not a return to elementwise.

`traversal.skew2k.dedup.depth3` fails the baseline comparison on
`shape.node_types`. Measured against the run that produced the alert:

    node count            39 -> 39          identical
    node type counts      identical         (no type gained or lost)
    the only difference   one `Index Only Scan` moved position in the list
    shared_buffers        8,163 -> 8,389    +2.8%
    execution_ms          5.344 -> 5.46     +2.2%
    actual_rows           17 -> 17          identical

So: the same 39 nodes, the same multiset of node types, the same rows, and the
same cost to within noise. What changed is the ORDER of two siblings in a
flattened pre-order walk of the plan tree.

## Why the metric is wrong, not the query

`shape.node_types` flattens the plan into a list and compares it elementwise. But
sibling order carries no meaning: PostgreSQL is free to emit a hash join's inputs
in either order, and two index scans under the same parent are unordered with
respect to each other. A comparison that treats that as a shape change reports a
regression for a plan that is, by every other measure recorded, the same plan.

This matters more than one bench. `shape.node_types` is the metric that catches
REAL plan flips — `Gather Merge` becoming a `Sort` above a `Gather` is exactly
what it is for, and that is how `issues/112` was diagnosed. A metric that also
fires on meaningless reorderings trains people to skim past it, and the next
genuine flip is skimmed past with it.

## What to do

The comparison needs to distinguish a reordering from a change. Options, in the
order I would try them:

1. **Compare the multiset, and the tree separately.** A change in node-type
   COUNTS is unambiguous and cheap. Keep the ordered list for display, gate on
   the counts.
2. **Canonicalise sibling order before flattening** — sort each node's children
   by (node type, relation name) so a swap normalises away. Preserves more signal
   than a multiset, costs a stable sort at record time, and changes the recorded
   value for every bench, so it needs a re-promotion.
3. **Compare the tree structurally**, parent/child edges rather than a flat list.
   The most faithful and the most work.

Option 1 would have caught `issues/112`'s `Gather Merge` -> `Sort` + `Gather`
(the counts differ) while ignoring this one (they do not), which is the
discrimination being asked for.

## Provenance

Present before 2026-08-20's work and unrelated to it: the same difference shows
against the 2026-08-18 baseline. Surfaced because the tiered baselines
(`issues/112` follow-up) reduced the query tier's noise to a single finding,
which made it visible instead of one of eighteen.

## Related

- `issues/112` — `shape.node_types` correctly caught a real plan flip there; this
  issue is about it also firing when nothing changed
- `issues/081` — a gate that reports something other than what it names
