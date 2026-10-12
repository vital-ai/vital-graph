# 268 — The frame_slot warning sends a surplus to a backfill that only inserts, and the surplus was not real

## Status: FIXED 2026-10-12 (not yet released). Found in production on v0.0.85.

**Related:** `issues/263` (made the warning's remedy depend on the finding; this is
the case it missed), `issues/149` (client-side probe timeouts), `issues/150` (the
drift probe's cost).

## What production showed

After the 0.0.47 deploy, `263`'s warnings for the lead prod space stopped. Five new
ones appeared in eight hours, all for the main KG space and all in the other
direction:

    04:02  expected 3043004, has 3043006   (+2)
    04:37  expected 3043654, has 3043683   (+29)
    06:41  expected 3044768, has 3044798   (+30)

Each said "Missing rows only: the frame_slot backfill repairs this". The table had
MORE rows than expected, and the backfill only inserts, so it never fired: there
was nothing missing to insert. A warning whose text sends you to the wrong fix is
the class of problem `263` was filed about.

## Two defects

**1. The remedy branched on orphans only.** `263` chose between "backfill" and
"rebuild" by `orphan_rate == 0.0`, so a surplus with no orphans got the
missing-rows text.

**2. The surplus was a measurement artefact.** `frame_slot_drift` took its two
counts in TWO statements. Under READ COMMITTED each statement has its own
snapshot, and the expected count is a multi-second scan over the edge and quad
tables. Rows written while it ran were seen by the `count(*)` that followed and
not by the scan, so under write load the probe reported a small positive drift
that did not exist. The evidence fits: always positive, 2-30 rows on 3.05M, both
counts climbing together, and `+0` on two counts taken eight seconds apart when
writes were quiet.

**Found on the way:** `frame_slot_drift(conn, space, timeout=...)` accepted the
client-side timeout the maintenance job passes (`issues/149`) and never gave it to
the driver.

## Fix

- `frame_slot_drift` computes both counts in ONE statement (two scalar subqueries),
  so they share one snapshot, and passes `timeout` to the driver.
- The remedy text is `frame_slot_repair_text`, chosen by what is wrong: orphans →
  the rebuild; fewer rows than expected → the backfill; more rows than expected →
  the sweep (`cleanup_stale_frame_slot`), with the note that the backfill cannot
  remove rows.

## Tests

- `tests/unit/test_frame_slot_warning_matches_the_drift.py` (4): each finding gets
  its own remedy; the production surplus is not sent to the backfill; the drift
  probe issues ONE statement with the client timeout. On the previous code the
  probe issued two statements with `timeout=None`.
- `tests/unit/test_frame_slot_residue_backfill.py`: `263`'s warning test now
  checks behaviour instead of the method's source text.
- Live on the vg test stack: `wordnet_frames` 570,696 = 570,696 and
  `sp_graph_synth_100k` 946,548 = 946,548, twice each. The frame_slot integration
  tests pass, as does the full unit suite.

## Not done

Production confirmation after the next deploy: the main KG space's surplus
warnings should stop entirely, since the counts now come from one snapshot.
