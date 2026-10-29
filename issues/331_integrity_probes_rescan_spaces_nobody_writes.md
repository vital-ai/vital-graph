# 331 — Integrity probes rescan spaces nobody writes: a quarter of production database time

## Status: OPEN, filed 2026-10-29 from a two-hour `pg_stat_statements` diff on production (read-only). Mechanisms partly from code reading; each needs a local reproduction before a fix.

**Related:** `issues/239` (the tracker this was measured for), `issues/150`
(the write gate and its "unconverged work overrides the gate" rule), `issues/143`
(rec 1: gate probes on writes), `issues/270` (probe back-off on timeouts).

## Measured

Two snapshots of production `pg_stat_statements` (database `vitalgraphdb`,
`internal_data/pgss_20261029/snap{1,2}.json`), 2026-10-29 18:11 and 20:09 UTC,
diffed per (queryid, role), my own `postgres`-role EXPLAIN runs excluded. No
entry was evicted in between. The window's total execution time was 1,479 s.

Probe scans on spaces with **no write of any kind to their quad table in the
window** (every statement naming `<space>_rdf_quad` with INSERT, DELETE, UPDATE
or COPY was searched; none):

| space | probe | calls | mean | total |
|---|---|---:|---:|---:|
| `prod_kg` | frame_slot orphan rate (`fs WHERE NOT EXISTS (... edge ...)`) | 50 | 2,977 ms | 148.8 s |
| `lead_data` | edge type agreement (`... IS DISTINCT FROM e.edge_type_uuid LIMIT`) | 17 | 6,235 ms | 106.0 s |
| `vgs_aclndx37` | entity_slot_sort coverage (`WITH of_type AS ...`) | 22 | 2,778 ms | 61.1 s |
| `testspace` | edge dangling endpoints | 14 | 3,170 ms | 44.4 s |
| `testspace` | entity_slot_sort coverage | 99 | 190 ms | 18.8 s |
| **total** | | | | **379.1 s = 25.6% of all execution time** |

Each repeats a multi-second full scan whose answer cannot have changed: nothing
it reads was written. For comparison, all user reads in the same window were
110 s.

## Four mechanisms, not one

The probes are gated in four different ways, so this is not one missing `if`:

1. **frame_slot orphan rate** (`maintenance_job._run_frame_slot_integrity` and
   `_run_frame_slot_backfill`, gate `probe_data_changed`). `probe_data_changed`
   returns True whenever the probe last reported outstanding work, BEFORE
   reading the write watermark. `issues/150` added that override for a gap the
   backfill fills in passes. But an orphan is not something the backfill
   repairs (it only adds rows), so a space with a persistent orphan never
   converges and its full scan runs every cycle forever. 50 calls in 1.97 h is
   about one per call site per cycle. UNEXPLAINED: both call sites run
   `frame_slot_drift` first, and no drift statement for `prod_kg` is in
   either snapshot. Reproduce locally before trusting the reading.
2. **edge type agreement** (`edge_type_agreement.refresh_type_agreement`, its own
   change token and back-off). It should skip a space whose verdict matches its
   token. 17 scans on an unwritten space means the verdict is not stored, or its
   token keeps moving without quad writes.
3. **entity_slot_sort coverage**: ungated by design. `issues/150` measured it at
   **130 ms** and kept it every cycle as the cheap probe. On `vgs_aclndx37` it
   is now 2.8 s per call, 21x that; the premise no longer holds there.
4. **edge dangling endpoints** (`_run_edge_integrity`): reports, never repairs
   (`issues/212`). If it is gated on convergence like (1), a persistent
   dangling row keeps it unconverged forever.

## Direction (not decided)

A probe whose finding nothing AUTOMATIC repairs should run on writes, not on
"unconverged". The override belongs only to findings the job itself works off
(the backfillable gap), and those move a watermark of their own: the derived
table the backfill writes. Gate on the watermarks of every table the probe
reads, and keep re-warning about a standing finding on a timer, not a scan.

Acceptance: on a local space with a persistent orphan, a persistent dangling
row and no writes, each probe runs once and then not again until a write; a
backfillable gap still converges over passes on a quiet space (`issues/150`'s
verification step 2); production's next diff shows these rows at ~0 calls on
unwritten spaces.
