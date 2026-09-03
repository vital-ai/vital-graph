# Removing A Timeout Turned A Failing Probe Into A 54%-Duty-Cycle Scan

## Status: FIXED in code, UNDEPLOYED. Caused by `478fa06`, which was itself a fix.

## The symptom, as reported

A two-frame NurtureAction existence check (campaign + lead, `page_size=1`) stalls
at ~60s in **58% of production runs**. The same question asked with one frame
criterion answers in ~0.3s. A benchmark was written to attribute the difference
to the campaign criterion, which matches ~76k rows.

**The query is not the problem.** Timed directly against production:

    HIT   58,105 ms      <- inside a probe window
    MISS   1,923 ms
    HIT    1,455 ms
    MISS   1,141 ms
    ... six further runs, alternating: 1,271-2,077 ms

Matching versus non-matching makes no difference. The 58s run coincided with
something else.

## What it coincided with

    18:41:52   256,063 ms   SELECT count(*) FROM (... DISTINCT slot_uuid ... WITH RECURSIVE ...)
    18:43:20    58,066 ms   WITH _const AS (...)      <- the user query, inside that window

`entity_slot_sort_drift` over a 44-minute window:

    durations: 216s, 216s, 122s, 303s, 252s, 59s, 256s
    total 1,424s of 2,658s  ->  DUTY CYCLE 54%

More than half of wall-clock inside ONE probe, doing a full unseeded
`WITH RECURSIVE frame_walk` that sequential-scans the quad table. It evicts the
read path's buffer cache and competes for I/O. The user query is 1.5s when the
probe is idle and 58s when it is not; at a 54% duty cycle roughly half of runs
stall. The benchmark measured 58%.

## Cause: a fix that removed an accidental bound

`issues/149` found the probe dying at asyncpg's `command_timeout=60` — a
CLIENT-side fence no server-side `SET` can raise — so it never completed and the
backfill it gates never ran. `478fa06` gave it `PROBE_CLIENT_TIMEOUT_S = 900s`.

That was correct and incomplete. The 60s fence was a bug AND it was bounding the
damage. Raising it without gating the cadence converted "fails fast every cycle"
into "runs for four minutes every cycle".

The general shape, worth naming: **a broken thing can be load-bearing.** Fixing
it exposes the cost it was hiding, and the fix is not finished until that cost is
accounted for.

## The fix: gate on CHANGED DATA, not a clock

If no quads were written, drift cannot have changed and re-deriving it is pure
waste. `probe_data_changed` compares
`n_tup_ins + n_tup_upd + n_tup_del` on `{space}_rdf_quad` against the value at
the probe's last run.

Deliberately NOT `n_mod_since_analyze`: that resets on ANALYZE, which the same
job runs, so it would report change constantly.

`pg_stat_reset()` moves the counter DOWN; the test is `!=`, not `>`, so a reset
re-runs the probe rather than disabling it forever.

### Unconverged work overrides the gate

The backfill only ADDs, so a 2.7M-row gap takes many passes. Gating on writes
alone would skip those passes on a quiet space and strand the table half-filled
— the same "diagnoses correctly, repairs nothing" outcome as `issues/149`, from
the opposite direction. `mark_probe_converged` records outstanding work and the
gate honours it.

### The cheap probe stays ungated

`entity_slot_sort_coverage` measured **130 ms** against the drift walk's
216-303s — 2,000x cheaper, and it answers the question that actually matters
(is a type served by the table at all). It runs every cycle.

### The two sibling probes are gated too

`edge_table_drift` (a `count(DISTINCT (subject, context))` over ~50M rows,
measured 17.7s) and `frame_entity_drift`. This is `issues/143`'s recommendation
#1, which was left unwritten when 143 was partially fixed.

## What this does NOT explain

Both leaves of the reported query are statistically invisible to the join
reorder:

    (hasUriSlotValue, nurture_lead)   76,189 actual rows, ABSENT from rdf_stats,
                                      predicate pruned=TRUE
    hasTextSlotValue                  ZERO pairs recorded at all, pruned=TRUE

So the plan is chosen blind. That is not why it took 58s — it is 1.5s when the
box is quiet — but it is why this shape is fragile, and it is `issues/147`'s
prune interacting with `issues/142`'s flag. Left open.

## Verifying after deploy

    1. The `DISTINCT slot_uuid ... WITH RECURSIVE` statement should disappear
       from the slow log on cycles with no writes to that space.
    2. It must STILL appear while entity_slot_sort is converging (~40k -> ~2.83M),
       because unconverged work overrides the gate. If it vanishes while the
       table is short, the override is broken and the table will strand.
    3. The reported query's 58% stall rate should fall toward its ~1.5s floor.
