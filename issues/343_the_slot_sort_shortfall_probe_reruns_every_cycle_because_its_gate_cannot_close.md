# 343 — The slot-sort shortfall probe reruns every cycle because its gate cannot close

## Status: FIXED 2026-11-15. Unit-tested and VERIFIED on the vg test stack (rebuilt image, `vgtest_core`); DEPLOYED to production 2026-11-23. On production it works for quiet spaces only: the continuously written main KG space still runs the split every cycle (`issues/349`).

## Found

A one-hour `pg_stat_statements` window on production (`vitalgraph-pg18-prod`, 2026-11-15
13:28 → 14:28 UTC, Sunday, +2 evictions in the window; read-only snapshot/diff with
`test_scripts/perf/_pgss_window.py`). Total exec time 1,472 s over 3,608 s wall.

| % of the hour | statement | calls | mean |
|---:|---|---:|---:|
| **51.0** | `entity_slot_sort_gap` (`WITH slots AS (…)`, 5 pgss entries) | 4 each | 15-85 s |
| 13.6 | edge-type agreement scan | 3 | 66.5 s |
| 5.9 | `pg_prewarm` | 2,203 | 39 ms |
| ~1.5 | `entity_slot_sort_row_shortfall` (the "cheap" gate) | 12 | 0.9-3.4 s |
| ~3 | all user reads and writes together | | |

pgss sums aliased statements across spaces, so this is a bucket total, not per space.
Four calls an hour is one per ~15-minute maintenance cycle.

## Cause

`_run_entity_slot_sort_integrity` (`vitalgraph/process/maintenance_job.py`) runs, per space,
every cycle:

1. `entity_slot_sort_row_shortfall`: `count(quads with hasKGSlotType) − count(entity_slot_sort)`;
2. if that is nonzero, `entity_slot_sort_gap`, the exact split (one snapshot, `issues/277`);
3. if the split's `real > 0`, `backfill_entity_slot_sort_missing_slots`, the slot-seeded repair.

Step 1 is the only gate on step 2, and **it cannot close on a real space**: value-less
slots, entity slots and slots no entity reaches are all correctly absent from the table
(927 absent on the main production space, 99 of them value-less, per the comment at the
repair; the per-entity coverage probe reports every type complete there). So the
exact split and the repair ran every cycle on every KG space, changed or not.

Unlike the other space-proportional probes on the loop, this block was never behind
`probe_data_changed` (`issues/150`'s write gate). `tests/unit/test_probe_change_gate.py`'s
call-site test could not see that, because these three functions were not on its list of
expensive probes.

## Fix

- The block is gated on `probe_data_changed(conn, space_id, "entity_slot_sort_row_shortfall")`,
  with `continue` when the quads are unchanged. That is safe here, unlike at the coverage probe
  in the same step: this block maintains nothing the read path consults (`slot_gaps` is never
  populated), so a skipped cycle skips only an answer that cannot have changed.
- **The repair is invisible to the gate**, because it writes `entity_slot_sort`, not the
  quads. A pass whose repair added rows is marked unconverged, so the next cycle checks
  again; a pass that adds nothing is converged.
- **A pass that fails part-way is not converged.** The watermark moved when the gate
  passed, so the block marks itself unconverged before it starts and converged only at the
  end.
- **A timeout backs off** (`probe_backed_off` / `log_probe_failure` / `clear_probe_backoff`,
  `issues/270`), as the sibling probes do.

Behaviour change: the "SUSPECTED SHORTFALL" warning and the "edge table is short" error
are now logged when data changed (or while a repair is converging), not every cycle.

## Tests

- `tests/unit/test_probe_change_gate.py`: the three functions join `_EXPENSIVE_PROBES`,
  so `test_every_call_site_of_an_expensive_probe_is_gated` covers them. It **failed on the
  unfixed code at all three call sites** (lines 2900, 2908, 2959).
- `tests/unit/test_slot_sort_shortfall_gate.py` (new) drives the step through a fake pool:
  unchanged data does not rerun the split; a write reopens it; a repair that added rows is
  checked again, then the gate holds; a failed pass runs again; a timeout backs off. **4 of
  5 fail on the unfixed code** (run in a throwaway worktree at `be5dbf0e`). The fifth, "a
  write reopens it", passes trivially there because the old code always runs.
- Unit suite: 6,355 passed, 17 skipped.

## Verified on the vg test stack (2026-11-15)

`test_scripts/debug/_issue343_gate_verify.py`, run inside the rebuilt app container, calls the
real `_run_entity_slot_sort_integrity` and counts calls to the real functions. It ran on
two spaces the app's MaintenanceJob excludes, so the job could not run the same step meanwhile:

| cycle | `sp_lead_synth_10k` (406 k slot-sort rows) | `sp_lead_types` (81 k) |
|---|---|---|
| 1 cold (gate open) | 3.03 s: shortfall 1, gap 1 | 0.49 s: shortfall 1, gap 1 |
| 2 unchanged | **0.03 s: nothing run** | **0.01 s: nothing run** |
| 3 unchanged | 0.03 s: nothing run | 0.01 s: nothing run |
| 4a right after a quad insert + delete | 0.03 s: nothing run | 0.01 s: nothing run |
| 4b 3 s later | 2.43 s: shortfall 1, gap 1 | 0.41 s: shortfall 1, gap 1 |

(A first run measured cycle 1 at 10.61 s, cold cache.) The repair was not called: the exact
split found no real gap on either space.

**4a is the cumulative-stats flush lag, not a miss.** The writing backend flushes
`n_tup_ins`/`n_tup_del` at most once a second, so a reader can briefly see the old counter.
On the 15-minute cycle this is at most one cycle's delay: the next cycle sees the moved
counter and runs. It is the same for every probe behind `probe_data_changed`.

## Not done

- **After deploy**: the same pgss window on production, where `WITH slots AS` should drop
  from ~750 s/h to (near) zero on a quiet hour.
- The next items from the same window, not part of this issue: the edge-type agreement scan
  (13.6 %; reruns a full 66 s scan on any written space, so an incremental check is the
  candidate) and the `pg_prewarm` rate (2,203 calls/h; check it against `issues/271`'s
  intent).

## On production after deploy (2026-11-25)

The one-hour pgss window above, rerun 2026-11-25 02:38 → 03:41 UTC, about 28 h after the
rollout:
- `WITH slots AS` fell from ~750 s/h (51 %) to **~470 s/h** (26 %), and is still the top
  statement.
- 4 calls × 98 s were on the main KG space, i.e. every 15-minute cycle; 3 × 26 s were on
  other spaces.

The main KG space is written continuously (61,426 quad rows in 10 minutes; every other
space 0). The gate opens on any write, so on that space the fix changes nothing. It works
where data is quiet: the test service's median maintenance cycle went from 102 s to 0.7 s.

The production cycle median went from 756 s to 433 s (24 h before vs after; 17.5 h →
15.2 h of cycle time).

**Expected effect only partly reached.** The busy-space case is `issues/349`.
