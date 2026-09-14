# The frame-slot Hop-Wise Gate Costs Seven Test Failures, and Removing It Costs 3x

## Status: FIXED 2026-09-14 — the discriminator is the EDGE table

Both goals at once: all 7 failures gone AND the nested protection kept.

    file                             old gate      narrowed
    test_traversal_bench             4 FAILURES    0
    test_traversal_direction_gate    3 FAILURES    0
    test_nested_frame_traversal      0  (7 s)      0  (6 s)   <- 12 s with no gate
    test_graph_traversal_fixture     0             0
    test_general_traversal           0             0

The gate now declines hop-wise for a `frame_slot` shape when an `edge` table is
present OR the plan is TEXT-FILTERED, rather than for any `frame_slot` at all.
Two conditions, each tied to a measured catastrophe.

### The text condition was found by integration, not by the matrix

The 32-shape matrix had no text-anchored, UNION or BIND shapes, and with only
the `edge` condition `test_the_traversal_is_driven_by_the_text_anchor` failed:
**400 loops to return 2 rows**, a ratio of 200 against a limit of 50. Hop-wise
was driving from a text anchor.

`issues/181` had already measured that — 126,592,971 buffers against 5,151,498
for the text push alone, ~25x worse — so the hazard was known and the matrix
simply did not reach it. Worth stating plainly: a per-shape harness is better
evidence than whole-file timings, and it is still only as broad as the shapes
put into it.

The condition is whole-PLAN rather than per-end, deliberately: matching a filter
to a specific chain end needs the `col_var` mapping `_try_hop_wise` does not
have, and the conservative form costs only that text-anchored traversals keep
the behaviour they already had.

## How it was found, because the method is the point

The numbers in this file and in the gate's own comment were whole-FILE wall
clock. A per-SHAPE harness — 32 shapes across pinned / constrained-head /
constrained-tail x 7 criteria x depths 1-3, warm, median of 3, recording the
emission actually chosen and the row count — said something different.

**The gate is INERT on the shapes it was justified by.** Every measurement in
its comment is a PINNED chain, and pinned chains at depth >= 2 reach
`emit_dedup_chain`, which is tried FIRST and is not subject to it. With the gate
forced off those shapes still do not choose hop-wise: all 14 are `F->F`.

**Its real effect is where dedup CANNOT fire**, which is the constrained ends
(no pinned head) and depth 1 (too shallow). And there it splits cleanly:

    edge  shapes                  hop-wise vs flat
       1  pinned/nested_*/d1 (2)  112.83x and 28.44x WORSE
       0  everything else   (21)  13 better (to 0.05x), 8 worse (<= 1.85x)

An `edge` table appears when a NESTED criterion adds an `Edge_hasKGFrame` link,
which the edge rewrite collapses. Hop-wise has to nest that join inside every
hop's lateral and it fans out — which is the "1,665 ms / KILLED" the gate was
built for. Without it the gate was pure cost: those 21 shapes total 26,708 ms
gated against 16,817 ms ungated, **37% faster**, concentrated in the
constrained ends where flat is all that is left.

## Three hypotheses tested and rejected first

Recorded so the next person does not re-run them.

* **The PIN.** The gate's comment reasons about the pin landing as a late
  Filter. Narrowing to pinned chains fixed the direction gate and took
  traversal_bench 4 failures to 1, but left the nested cases slow. The pin is
  not the discriminator.
* **`frame_slot` table COUNT.** Plausible — a nested criterion "must" add
  tables. It does not: the count is exactly 2 per hop whether the criterion is
  nested or not, measured identical at depths 1 and 2.
* **Criterion SHAPE**, which `issues/195` records three failed attempts at. The
  `category_in_alpha_beta` shapes are the ones that get moderately worse
  (1.24-1.85x) and it is tempting to gate on them. Not done: that band overlaps
  the measured noise floor (0.92-1.33 on slow shapes), and it is the same rule
  fitted to the same kind of numbers that failed three times before.

## One correction to this file's own numbers

It recorded `test_nested_frame_traversal` at 7 s gated and 20-23 s ungated. Three
consecutive runs put it at **6-7 s gated and 12 s ungated**. The 20-23 s figures
were taken while background jobs were running and were contention-inflated — so
the pin-only narrowing was judged against a bad baseline.

## Original filing

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
