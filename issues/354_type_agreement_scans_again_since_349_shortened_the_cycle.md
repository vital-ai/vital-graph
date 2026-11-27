# 354 — Type agreement scans again on production, likely because `349` shortened the cycle that `344`'s quiet test counts in

## Status: OPEN 2026-11-26. Cause CONFIRMED for the main KG space from production's own log lines (read-only CloudWatch, before vs after `349`). FIXED 2026-11-26: quiet is measured in time. Unit-tested (3 of the new tests fail on the unfixed code; unit suite 6,477, 0 failed). VERIFIED on the vg test stack (`vgtest_core`, scratch EC2, with a control against the old gate). Not deployed.

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

## Measured (2026-11-26, read-only CloudWatch, production streams only)

Every `type agreement:` outcome line, grouped by space and outcome. The BORN STALE line is
paired with its "differs" line and counted once.

| space (role) | kind | outcome | before: runs / s | after: runs / s |
|---|---|---|---:|---:|
| main KG | frame | born stale | 0 / 0 | **5 / 1,045** |
| main KG | frame | timed out (300 s) | 1 / 300 | **2 / 600** |
| main KG | frame | absorbable | 1 / 194 | 0 / 0 |
| main KG | edge | timed out (300 s) | 1 / 300 | **2 / 600** |
| UW | edge | absorbable | 12 / 2,596 | 15 / 1,818 |
| UW | edge | born stale | 4 / 990 | 0 / 0 |
| UW | frame | absorbable | 17 / 242 | 15 / 476 |
| business KG | edge + frame | absorbable | 28 / 229 | 32 / 252 |
| **total** | | | **4,852 s** | **4,791 s** |

The two windows:
- **before:** `v0.0.104`, 2026-11-24 00:00 → 2026-11-25 21:20 UTC, **45.3 h**;
- **after:** `v0.0.106`, 2026-11-26 03:46 → 2026-11-27 ~02:00 UTC, **~22 h**.

What it shows:

- **The scan rate doubled, ~107 → ~216 s/h,** with about the same total in half the time.
- **On the main KG space every scan is wasted, and there are 6x as many.**
  - Before: 3 attempts in 45 h. 344's quiet test almost never passed, because a cycle took
    ~12 min and the space is never quiet that long.
  - After: 9 attempts in ~22 h, all of them born stale or timed out, 2,245 s for no usable
    verdict.
  - The frame attempts come 1.5-2.7 h apart: the 1 h born-stale backoff expires, then
    the first ~5-minute pause in writes passes the quiet test.
  - This is the hypothesis above, confirmed.
- **The UW and business KG spaces are another matter.** Their scans end ABSORBABLE: a
  usable verdict, until the next write. They now rescan about twice as often, for the
  same reason, but each scan does buy something. How long each verdict stays current, and
  so whether the doubling is worth paying, is not measured.
- **Only one task logs these lines** (one log stream). The maintenance job runs on one
  of the two tasks.

## Recommendation

**Option 1, quiet by time.**
- Require the token to be unchanged for at least `VG_TYPE_AGREEMENT_QUIET_S`, default
  1800 s, instead of for one cycle.
  - For a space whose last attempt was born stale or timed out, also require more than
    its own last `compute_ms`. A scan that took 274 s cannot succeed on a space that
    pauses for 5 minutes.
- **Expected effect:**
  - restores the before-349 behaviour on the main KG space (about 3 attempts in 45 h,
    or none);
  - halves the UW / business KG rescans.
- **Cost:** a quiet space gets its verdict back up to 30 min later.
- **Code:** `_not_quiet_yet` keeps the time it first saw the current token rather than only
  the token. In memory, as now.
- **Also:** wrap `_run_type_agreement_refresh`'s loop in `timed_spaces`, so `spaces=`
  shows this step per space.

## Fix (2026-11-26)

`_not_quiet_yet` (`edge_type_agreement.py`) now keeps, per `(space, kind)`, the token
and **when this process first saw it**. A space that already has a stored row rescans
only once that token has held for `VG_TYPE_AGREEMENT_QUIET_S` (default **1800 s**).
- A write restarts the clock.
- `0` gives the old one-cycle test.
- The clock is `_quiet_clock` (`time.monotonic`), in memory as before, so a restart
  restarts it.

**Unchanged:**
- a space with no stored row scans at once;
- a current verdict is skipped;
- the born-stale (1 h) and timeout (6 h) backoffs come first;
- `force` bypasses everything.

The extra condition on the last attempt's `compute_ms` is dropped. The refresh's scan
budget is 300 s (`REFRESH_TIMEOUT_MS`), so 30 min of quiet already exceeds any scan that
can finish.

`_run_type_agreement_refresh`'s loop now goes through `timed_spaces("type_agreement", …)`,
so the cycle line's `spaces=` carries `type_agreement[<space>]`.

Tests (`tests/unit/sparql_sql/test_type_agreement_waits_for_a_quiet_space.py`, with a fake
clock):
- a 5-minute pause is not quiet;
- a write during the wait restarts the clock;
- a space paused every 5 minutes for a simulated day is never scanned through the real
  `refresh_type_agreement`;
- `QUIET_S=0` is the old test;
- the default is 30 min.

The `344` tests now advance the clock by `QUIET_S` where they used to call twice. So does
`test_unprovable_agreement_is_not_rebought`'s recovery test.

**Control:** against the unfixed module, the three behaviour tests fail, including "a
5-minute pause passed as quiet".

## Verified on the vg test stack (2026-11-26)

`test_scripts/debug/_issue354_quiet_by_time_verify.py`, run in the rebuilt app container
on a scratch EC2 instance. It drives the real `refresh_type_agreement` on
`sp_lead_synth_10k` (excluded from the app's own maintenance job) with:
- real tokens, scans and stored rows;
- a fake clock, with cycles 5 minutes apart as on production.

A "write" inserts and deletes one row in the quad, edge and frame_slot tables, then
forces the statistics flush (`pg_stat_force_next_flush()`; an idle backend can otherwise
hold its counters ~10 s). That space has no write log, so its token is the derived
tables' own churn, and a quad-only write does not move it.

| cycle | fixed | old gate (control) |
|---|---|---|
| 0, written | wait (first sighting) | wait |
| 1, +5 min, no write | wait (300 of 1800 s) | **scans both** |
| 2, +5 min, written | wait | wait |
| 3, +5 min, no write | wait (300 of 1800 s) | **scans both** |
| 4, +30 min, no write | **scans both** (frame 35.6 s, edge 7.4 s, both agree) | current |
| 5, +5 min, no write | current | current |
| verdict | **PASS** | FAIL |

- **The fix:** the old gate scans at every 5-minute pause, which is production's pattern.
  The fixed gate waits out the 30 minutes, scans once, and then holds a current verdict.
- **The control** rebinds the old module's functions in the running process (the old
  source from `HEAD` before this change), and runs the same script.
