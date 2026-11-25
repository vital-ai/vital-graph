# 344 — Type agreement rescans a space that cannot keep a verdict

## Status: FIXED 2026-11-15. Unit-tested and VERIFIED on the vg test stack (rebuilt image, `vgtest_core`); DEPLOYED to production 2026-11-23. Confirmed on production 2026-11-25: the edge-agreement scan left the top 30 statements of an hour (was 13.6 %).

## Found

The same production `pg_stat_statements` hour as `issues/343` (2026-11-15 13:28 → 14:28
UTC): the edge-type agreement scan (`refresh_type_agreement`, edge kind) was **13.6 %** of
the database's time, 3 calls at 66.5 s mean. Production's `type_agreement` table
(read-only) shows where it went:

| space (by role) | kind | agrees | source rows | last compute | last computed |
|---|---|---|---:|---:|---|
| main KG space | edge | **NULL** (born stale) | 6.8 M | **224.5 s** | 64 min ago |
| main KG space | frame | NULL (timed out) | 4.8 M | 300.0 s | 308 min ago |
| underwriting space | edge / frame | TRUE | 2.4 M / 2.0 M | 13.4 s / 10.8 s | 44 min ago |
| business KG space | edge / frame | TRUE | 195 k / 142 k | 4.2 s / 9.3 s | 64 min ago |
| six static spaces | both | TRUE | | | ~17 days ago (token still current) |

## Cause

A stored verdict is usable only while nothing writes the space: its change token carries
the space's write-log count (`change_token(…, space_id)`, `issues/302`). The refresh
already skips a current verdict, and backs off a space whose verdict was born stale
(1 h) or timed out (6 h). But **the back-off expires on a clock, not on the space going
quiet**. The main KG space is written continuously, so every hour it ran a 224 s edge scan,
was born stale again, and has never once held a usable verdict. The spaces that do reach
TRUE are rescanned on the first cycle after any write, and the next write makes that
verdict unusable too.

## Fix

`_refresh_not_needed` (`vitalgraph/db/sparql_sql/edge_type_agreement.py`) gains a third
reason to wait, `_not_quiet_yet`: **a space that already has a stored row rescans only when
its change token equals the one seen at the previous cycle**, i.e. after a whole cycle with
no write. It applies wherever the old code would have scanned a space with a row: a moved
verdict, and an expired born-stale or timeout back-off.

- A busy space never qualifies, so its hopeless scans stop.
- A space that goes quiet gets its verdict one cycle later, when it has a chance to be used.
- A space with **no row** still scans at once, so a new space gets its first verdict without
  waiting.
- An unreadable token does not block (scan, as before). This is a cost gate; the stored
  token is still what keeps a verdict correct, and nothing about reading or trusting
  verdicts changed.
- `force=True` (the manual trigger) ignores it, as it ignores every gate.
- In memory: a restart costs one cycle's delay.

Expected effect on the hour above: the main KG space's 224 s edge scans (and its frame
attempts every 6 h) stop while it is being written. Its verdicts don't change, since none
has ever been usable.

## Tests

- `tests/unit/sparql_sql/test_type_agreement_waits_for_a_quiet_space.py` (new, 10 tests):
  a moved verdict waits one quiet cycle and then rescans; a space written every cycle is
  never rescanned; expired born-stale and timeout back-offs also wait; a current verdict is
  still "current"; no row scans at once; an unreadable token does not block; spaces and
  kinds keep separate sightings; the refresh itself never reaches the scan on a busy space;
  `force` still scans. **6 of 10 fail on the unfixed code** (run in a throwaway worktree at
  HEAD); the other four pin behaviour that is unchanged.
- `test_unprovable_agreement_is_not_rebought.py::test_the_backoff_expires_so_a_quietened_space_recovers`
  is **changed on purpose**: recovery after the back-off now takes one observed quiet cycle
  (the first refresh records the token, the second scans). Its intent, that a quietened space
  recovers with no intervention, still holds and is still asserted.
- Unit suite: 6,388 passed, 9 skipped.

## Verified on the vg test stack (2026-11-15)

`test_scripts/debug/_issue344_quiet_gate_verify.py`, run inside the rebuilt app container, calls the
real `refresh_type_agreement` on two spaces the MaintenanceJob excludes:

| step | `sp_lead_types` | `sp_lead_synth_10k` |
|---|---|---|
| 1 `force` | both kinds SCANNED, TRUE | both kinds SCANNED, TRUE |
| 2 no write | verdict still current | verdict still current |
| 3 after a write | **waiting for a quiet one** (both kinds) | **waiting for a quiet one** (both kinds) |
| 4 a quiet cycle | both SCANNED, TRUE | both SCANNED, TRUE |
| 5 no write | verdict still current | verdict still current |

The write is one dummy row inserted into and deleted from the quad, `edge` and `frame_slot`
tables: a net no-op that moves the tokens. A quad-only write did NOT move them here, and
that is correct, not a miss: without the write log (no space on `vgtest_core` has one;
production's busy space does) a kind's token is the churn of the table it is read from.

## Not done

- **After deploy**: the pgss window again. The edge-agreement statement should leave the
  top of the hour while the main KG space is being written.
- The durable fix, which the module's own docstring names: maintain agreement at write time
  (a `type_agrees` flag where `edge_type_uuid` / `frame_type_uuid` are derived), so a busy
  space can hold a verdict at all.
