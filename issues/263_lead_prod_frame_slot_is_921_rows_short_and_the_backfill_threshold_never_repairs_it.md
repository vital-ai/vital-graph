# 263 — `lead_prod`'s frame_slot is 921 rows short, and the backfill threshold never repairs it

## FIXED IN CODE 2026-10-10, not yet deployed (see "Fix" at the end). On
## deploy, `lead_prod`'s 921 rows are backfilled automatically on the third
## maintenance cycle; no manual production write is needed.
##
## Status: OPEN — found 2026-10-10 reading the production logs. CAUSE FOUND
## the same day (see "Investigation"): the 921 rows are 211 whole frames written
## by the OLD release during the 2026-09-10 frame_slot migration window. No
## write path is dropping rows. Still to do: the one-off repair, plus the
## threshold mismatch and the misleading message, which are what kept this
## alive for a month.

## Investigation, 2026-10-10

Read-only probe against production (`test_scripts/debug/_issue263_missing_frame_slot.py`):

- **921 missing keys = 211 frames x all of their slots.** None of the 211 has
  ANY `frame_slot` row. All are `Edge_hasKGSlot` → `KGFrame` in `urn:lead_prod`.
  Their slots are value slots (email, name, stage, ...), so 0
  `hasEntitySlotValue`, which is normal for them.
- **Every one was created 2026-09-10 between 15:53 and 16:48 UTC.** Frames
  created that day, by hour, against how many have frame_slot rows:
  14:00 235/235, **15:00 251/227, 16:00 233/46**, 17:00 228/228. Every frame in
  the window is missing; every frame either side of it is fine.
- **That window is a release overlap.** `b94484a9` (2026-09-10 00:31) retired
  `frame_entity` for `frame_slot`. The tasks serving production until 16:54 were
  release 0.0.40 (started 09-09 02:22), and their writes log
  `presync: frame_entity=...`: they maintained the OLD table and never touched
  `frame_slot`. The new tasks started at 16:47:17 and 16:47:56; the first
  integrity warning came at 16:49:05 from one of them. `lead_prod_frame_slot`
  was built from a snapshot at about 15:53. That build is not in the app logs,
  so it was most likely `scripts/migrate_frame_slot_table.py` run by hand. Every
  frame the old tasks wrote between the snapshot and the cut-over has no rows.
- It persists because none of the 211 leads has been written since. Any write
  to one re-derives its rows (`sync_frame_slot_after_edge_insert` matches
  touched frames).

So the earlier "a write path is still missing rows" was wrong twice: the gap is
not growing (see below), and it is not a write path. It is a deploy-ordering
residue that the self-heal was configured to ignore.

**What would have healed it the same day:** the backfill this issue already
names. It ran every cycle and declined, because 921 < `max(1000, 1%)`. A
migration that builds a derived table while the previous release is still
writing will always leave a tail like this, and the backfill is exactly the tool
for it, if the threshold lets it act.

**Separate defect found on the way: `265`.** The referential sweep
(`cleanup_stale_frame_slot`) judges every value-slot row stale and deletes up to
50k valid rows per pass. Production did this to `prod_kg_actions` five
times on 2026-09-28, and the backfill restored each batch only because 50k
clears the threshold this issue is about.

## What the logs show

`maintenance_job._run_frame_slot_integrity` on production, log group
`/ecs/vitalgraph-prod`:

```
frame_slot integrity: lead_prod expected 1121682 rows, has 1120761, orphan rate
0.00% — the frame-slot collapse is serving from a table that does not match the
data. Repair with `scripts/migrate_frame_slot_table.py --space lead_prod --apply`.
```

- **3,402 warnings since the 2026-10-01 deploy**, 200-440 a day. No other space
  is reported.
- **The gap is constant, not growing.** The first warning is 2026-09-10 16:49
  UTC. The daily maximum deficit was 941 and 932 on the first two days, then
  exactly **921 on every day from 2026-09-11 to 2026-10-10**, while `expected`
  grew from 786,334 to 1,121,714. Daily minimums wander between 897 and 920;
  those dips are a check landing between an edge write and its frame_slot
  write, not further loss.
- **Orphan rate is 0.00%.** No row is wrong; rows are only missing.

So this is a fixed residue from before 2026-09-10 (or from the first day of the
check), not an active leak. Whatever wrote it, current writes keep pace.

An earlier reading of the same logs (in conversation, 2026-10-10) called the gap
"slowly growing" by comparing one day's minimum, 903, with the latest value,
921. That was wrong; the per-day maxima above are the right series.

## Why it never self-heals

`_run_frame_slot_backfill` runs directly after the integrity step and would
add exactly these rows — `backfill_frame_slot_table` is `INSERT ... ON CONFLICT
DO NOTHING` over the same edge/slot-type join `frame_slot_drift` counts. But it
only picks a space when

```python
drift > max(EDGE_DRIFT_MIN_ABS, int(EDGE_DRIFT_MIN_PCT * expected))
#        max(1_000,             1% of 1,121,682 = 11,216)
```

921 is below both. The integrity step, meanwhile, warns on ANY difference
(`expected == actual and orphan_rate == 0.0` or report). And because `lead_prod`
is written continuously, `probe_data_changed` never lets the integrity probe
converge-and-skip. Result: a warning every cycle, forever, about a gap that is
by configuration never repaired.

The rows are insertable: `frame_slot`'s primary key is
`(frame_uuid, slot_uuid, context_uuid)` (`sparql_sql_schema.py:1221`), the
same triple `frame_slot_drift` counts `DISTINCT`, so `expected - actual` is a
true count of missing keys, not a key mismatch.

## The log message names the wrong tool

It recommends `scripts/migrate_frame_slot_table.py --space X --apply`, a full
rebuild that TRUNCATEs under ACCESS EXCLUSIVE — on a 1.12M-row production table,
an outage for every frame-slot query while it runs. With orphan rate 0, the
non-blocking `backfill_frame_slot_table` (ROW EXCLUSIVE) is the right repair;
the rebuild is for orphans, which backfill cannot remove. The message should
name the tool that fits what was found.

## What to do

1. **DONE 2026-10-10 — see "Investigation".** ~~Identify the 921 rows before
   repairing them~~ — the repair erases the evidence of which writer dropped them.
   Run against `lead_prod` (read-only):

   ```sql
   SELECT DISTINCT e.source_node_uuid AS frame_uuid,
          e.dest_node_uuid AS slot_uuid, e.context_uuid
   FROM lead_prod_edge e
   JOIN lead_prod_rdf_quad st
     ON st.subject_uuid = e.dest_node_uuid
    AND st.predicate_uuid = <hasKGSlotType uuid>
   WHERE NOT EXISTS (
     SELECT 1 FROM lead_prod_frame_slot fs
     WHERE fs.frame_uuid = e.source_node_uuid
       AND fs.slot_uuid  = e.dest_node_uuid
       AND fs.context_uuid = e.context_uuid);
   ```

   Then resolve the frame URIs and group by frame type, slot type, URI prefix,
   and creation/modification time. The questions: are they all one frame type,
   one time window (before 2026-09-10?), one writer? `91` found its writers
   from URI prefixes the same way.
2. **Repair with the backfill, not the rebuild** — run
   `backfill_frame_slot_table` for `lead_prod` once, then confirm the next
   integrity check reports `expected == actual`.
3. **Make the two steps agree.** Recommended: when orphan rate is 0 and the
   space has any missing rows, backfill it — the threshold exists to bound the
   cost of the scan, and the integrity step has already paid for an equivalent
   one this cycle. The alternative, warning only above the backfill threshold,
   would hide exactly this kind of residue, which is what `041` warns against.
4. **Fix the message** to recommend the backfill when orphan rate is 0 and the
   rebuild only when it is not.

## Not established

- ~~Which write path dropped the 921 rows, or when.~~ Answered above: no write
  path; the 2026-09-10 release overlap.
- Whether other spaces were written during the 15:53-16:48 window. Only
  `lead_prod` warns, and the integrity step reports any nonzero drift, so
  probably not, but no other space was examined directly.
- Who ran the 15:53 build, and whether a runbook says to build before
  cut-over. A release note to build derived tables only AFTER the new code is
  serving (or to backfill straight after) would prevent the next one, but no
  release procedure was examined.

## Fix, 2026-10-10

- **Persistent residue is backfilled** (`maintenance_job._run_frame_slot_backfill`).
  Drift below `max(EDGE_DRIFT_MIN_ABS, 1%)` is backfilled once it has lasted
  `FRAME_SLOT_RESIDUE_CYCLES = 3` consecutive cycles. Rows a write is still
  deriving clear within a cycle; a residue does not. A drift above the floor
  still goes first. If a backfill inserts nothing, the space is not retried
  until its drift changes, so an unrepairable gap costs one scan, not one per
  cycle.
- **The probe no longer declares a residue converged.** Convergence was
  `drift <= 1000`, which would have stopped probing a quiet space carrying a
  residue for good. It is now `drift <= 0`, or "already tried at exactly this
  drift".
- **The warning names the right repair.** No orphans: the backfill, which runs
  automatically. Orphans: the blocking rebuild, named as blocking.
- Both residue dicts are registered in `CACHE_INVALIDATORS`, so a space rename
  does not carry them to the new id.

Tests: `tests/unit/test_frame_slot_residue_backfill.py` (7). They cover the
`lead_prod` case (921 of 1M, repaired on cycle 3 and not before), a transient
gap never triggering, an unrepairable gap scanned once, a changed drift tried
again, above-floor priority, the probe staying open, and the message's branch
order. Unit suite otherwise unchanged: the only failures are the 6
document-converter tests (`mammoth`/PDF library not installed in this env) and
the issue-index "committed" check, until these files are committed.
