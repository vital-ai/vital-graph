# The Probe Cap Declined On Size Alone — REVERTED, With The Measurements

## Status: REVERTED in the tree. Shipped in `429aebc`, regressed five measured
## shapes, and the data says the idea needs redesigning rather than retuning.

## What it did

`MAX_PROBE_CANDIDATES` was added to stop a 55s production timeout: an anchor of
100,000 candidates with an undiscriminating probe, `EXISTS` running ~49,000
times for a query returning 78,871 rows. It declined the probe whenever the
anchor exceeded 10,000 rows:

    if candidates > MAX_PROBE_CANDIDATES:
        return False

It fixed that shape and regressed four others in
`test_paging_fence_covers_every_shape` on `sp_lead_synth_100k`: the fenced plan
is 9.0-17.9x cheaper in buffers (13,098 against 117,743; 6,131 against 109,621)
while `needs_ordered_scan` is not set, so the cheap plan is never chosen.
Declining the probe changes the plan shape `emit_slice` derives that flag from.

## The comment predicted it, and that did not help

    10,000 is a STARTING POINT, not a measured optimum ... Establish the real
    number by measuring the shapes `issues/045` fixed before trusting it — a
    threshold set too low gives those back.

Correct, written down, and ineffective: the measurement it asked for was the
performance tier, and the change shipped before the performance tier had run.
A warning in a comment is not a control.

## THE MEASUREMENTS, which are the durable result

All four shapes have the SAME candidate count. Only selectivity differs, and the
required decision is NOT MONOTONIC in it:

    production Nurture    100,000 candidates   sel 0.79     must DECLINE
    fence `range-loose`   100,000 candidates   sel 0.354    must ALLOW
    fence `contains`      100,000 candidates   sel 0.10     must ALLOW
    fence `range-tight`   100,000 candidates   sel 0.0010   must DECLINE

Decline at BOTH extremes, allow in the middle. So:

  * no threshold on `candidates` can work — the count is identical across all
    four;
  * no threshold on `sel` can work either — any cut admitting 0.10 and 0.354
    while excluding 0.79 also admits 0.0010, and any cut excluding 0.0010
    excludes the two that must be allowed.

Both were measured by instrumenting the gate, not inferred. This is the finding
worth keeping: the gate needs a signal it does not currently read, and two
successive thresholds (0.25, then 0.5) each fixed a subset and broke another —
which is what retuning a wrong model looks like.

`range-tight` also fails DIFFERENTLY, which is the clue. Its unfenced plan does
not finish in 20s while the flag is unset, so the slow plan is the one served —
where the other three fail by the flag disagreeing with a cost comparison that
did complete.

## Why it is reverted rather than retuned

The 55s timeout it targeted is a real problem, but it is `issues/161`'s problem
and it predates this change. Trading one 55s shape for five regressed ones is
not an improvement, and the shape of the data says the next threshold would move
the failures around again rather than remove them.

The test that caught it points at where the fix belongs:

    This is issues/111's shape: the flag disagreeing with which plan is
    actually better. Fix it in `emit_slice`, not here.

That is the direction: `needs_ordered_scan` should agree with which plan is
actually cheaper, rather than the semi-join gate being bent until the flag
happens to come out right. Reverting restores the baseline, which passes all 49
fence shapes.

## For whoever picks this up

The four points above are the specification. A candidate rule must decline 0.79
and 0.0010 while allowing 0.10 and 0.354 at a constant candidate count of
100,000 — and if that seems impossible on selectivity alone, that is the
finding, not an obstacle to it.
