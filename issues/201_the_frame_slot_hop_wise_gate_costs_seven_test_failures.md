# The frame-slot Hop-Wise Gate Costs Seven Test Failures, and Removing It Costs 3x

## Status: OPEN — measured both ways, neither setting is right

`emit_bgp._try_hop_wise` declines hop-wise for any BGP containing a `frame_slot`
table (`bc6ff22a`, `issues/195`). That decline is the direct cause of **7 of the
query tier's failures**, and removing it is not simply correct either.

Measured on the same four files, same stack, one change between runs:

    file                            gate (committed)   pin-only   no gate
    test_traversal_bench              4 FAILURES        1 FAIL     0
    test_traversal_direction_gate     3 FAILURES        0          0
    test_nested_frame_traversal       7 s               23 s       20 s
    test_graph_traversal_fixture      5 s               7 s        7 s

So: the gate buys roughly 3x on nested-frame traversal and costs 7 failures.
Neither column is a good answer.

## Why the obvious narrowing does not work

The gate's own reasoning is about THE PIN — it lands as a late Filter because
`reorder_joins` never runs on the hop-wise path — and every measurement in its
comment table is a PINNED chain. A chain driven from a CONSTRAINED end has no
pin to misplace, so the argument does not reach it, and declining there is
costing exactly what `issues/090` exists for.

Narrowing the decline to pinned chains fixes `test_traversal_direction_gate`
outright and takes `test_traversal_bench` from 4 failures to 1 — but
`test_nested_frame_traversal` stays slow (23 s against 7 s). So the expensive
nested case is NOT pinned, and the pin is not the discriminator the comment
believes it is.

## What this needs, and what it must not be

A per-SHAPE measurement, not test runtime as a proxy. The numbers above are
whole-file wall clock, which mixes query cost with fixture setup and cannot say
WHICH shape regressed. The question to answer is narrow:

  * which frame-slot shapes are slower under hop-wise, and by how much
  * what distinguishes them from the constrained-end shapes that need it

`issues/090` records three plausible traversal fixes that measured worse, and
`issues/195` records three attempts to discriminate this by criterion shape that
were each measured worse. This is the fourth and fifth. The failure mode is
consistent: a rule fitted to whole-file timings rather than to per-shape ones.

## Do not treat the 7 failures as independent

They are one cause. Anyone fixing `test_traversal_bench` or
`test_traversal_direction_gate` in isolation will find the tests correct and the
emission gated, and may "fix" them by weakening the assertion — which would
remove the only thing currently reporting this. The tests are right. The gate is
too broad and its replacement is not yet known.

Recorded against the committed state: the experiment was reverted rather than
left half-tuned.
