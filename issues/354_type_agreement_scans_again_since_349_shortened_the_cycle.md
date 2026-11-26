# 354 — Type agreement scans again on production, likely because `349` shortened the cycle that `344`'s quiet test counts in

## Status: OPEN 2026-11-26. Cause is a hypothesis, unconfirmed; the first step is one read-only log query.

## Found

From the `353` fields on production, over 13.3 h (2026-11-26 03:46 → 17:00 UTC, after the
`v0.0.106` restart), read from CloudWatch by the deploy session:

| step | runs | per run | total | share of maintenance busy time |
|---|---:|---:|---:|---:|
| `type_agreement_refresh` | ~10 | 60-320 s | ~2,000 s | ~10 % |

`344` (deployed 2026-11-23) was meant to stop exactly this on the main KG space. On
2026-11-25 the edge-agreement scan had left the top 30 statements of an hour (it had been
13.6 %).

## Hypothesis: "quiet for a cycle" now means "quiet for ~5 minutes"

`344`'s gate is `_not_quiet_yet` (`edge_type_agreement.py:618`): a space that already
has a stored row is rescanned only when its change token equals the one seen **at the
previous cycle**. A space qualifies when nothing was written for a whole cycle.

That unit changed under it:
- **Before `349`:** a cycle was a median 433 s of work, plus the scheduler's 300 s sleep.
  "Quiet for a cycle" meant quiet for ~12 min or more.
- **After `349`:** the median cycle is 0.6 s, so cycles start ~5 min apart. A space that
  pauses its writes for 5 minutes now passes the quiet test, and gets a scan of up to
  320 s that the next write makes stale again (born stale, then a 1 h backoff, then the
  quiet test again).

So the gate holds as coded, but its threshold shrank by about 2.5x without anyone changing
it. This would also explain why it fires ~10 times in 13 h rather than every hour.

Other explanations, not yet ruled out:
- a space that really did go quiet and scanned usefully (`ABSORBABLE`);
- a space with no row yet, which scans at once by design;
- the 6 h timeout backoff expiring.

## First step (read-only, CloudWatch)

The refresh already logs every outcome per space and kind:
- `type agreement: <space> <kind> BORN STALE -- … <ms> ms scan …`;
- `type agreement: <space> <kind> rdf:type vs <col> -> ABSORBABLE | differs… (<rows> rows, <ms> ms)`;
- `type agreement: <space> <kind> refresh failed` / the timeout warning.

Query on the production streams only (`ecs/vitalgraph/*`; the group also carries
`ecs-test/*`), from 03:46 UTC:

    fields @timestamp, @message
    | filter @logStream like /^ecs\/vitalgraph\// and @message like /type agreement: /
    | sort @timestamp asc

- **Mostly `BORN STALE` on the busy spaces, minutes after a short write pause:** the
  hypothesis holds.
- **Mostly `ABSORBABLE`:** the scans are buying usable verdicts, and the cost may be
  acceptable.

The step's loop is not wrapped in `timed_spaces` yet, so `spaces=` cannot attribute it.
Wrapping it is a one-line change, worth making with any fix.

## Options, if the hypothesis holds

1. **Quiet by time, not by cycle.** Require the token to be unchanged for at least
   `VG_TYPE_AGREEMENT_QUIET_S` (say 30 min), or for longer than the space's own last
   `compute_ms` times a factor, so that a scan can finish before the next write. That
   restores and states the threshold `344` assumed, so it no longer follows the
   scheduler's cadence. Small.
2. **Lengthen the born-stale backoff** from 1 h to 6 h (`VG_TYPE_AGREEMENT_BORN_STALE_BACKOFF_S`,
   a setting, no code). It cuts the rate but does not fix the threshold.
3. **The durable fix**, as in `344` and the docstring: maintain a `type_agrees` flag at
   write time. Larger.

Whichever is chosen, `344`'s tests must still hold: a quiet space recovers its verdict,
and a new space scans at once.
