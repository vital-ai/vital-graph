# 331 — Integrity probes rescan spaces nobody writes (RETRACTED: a pg_stat_statements reading error)

## Status: CLOSED, NOT A DEFECT, 2026-10-29. Filed and retracted the same day. The measurement grouped one probe across every space; PostgreSQL 18 identifies a statement by its table ALIASES. Kept for the two traps, which will catch the next reading of production `pg_stat_statements`.

**Related:** `issues/239` (the tracker this was measured for; its 2026-10-29
section is corrected to match), `issues/150` (the write gate).

## What was claimed

A two-hour diff of production `pg_stat_statements` (`internal_data/pgss_20261029/`)
showed five probe statements, each labelled with one space's tables, on spaces
with no write in the window: 379 s, 25.6% of the window's execution time. The
claim was that those probes rescanned unwritten spaces every cycle.

## Why it is wrong

**Trap 1: PostgreSQL 18 groups a statement by the NAMES its tables carry in
the query, not by their OIDs.** A table with an alias is identified by the
alias. The probes are written `FROM {space}_edge e LEFT JOIN {space}_rdf_quad
rt ...`, with the same aliases for every space, so ONE `pg_stat_statements`
entry sums that probe over EVERY space. Its text is whichever space's statement
created the entry, often from before the 2026-10-22 storage-key rename (the
`lead_data_edge` text names a table that no longer exists). Verified on the vg
test stack's PostgreSQL 18.4 with `compute_query_id = on`:

| statement | space A | space B |
|---|---|---|
| `SELECT 1 FROM vgs_A_edge e LEFT JOIN vgs_A_rdf_quad rt ON ...` | 8053707859074311434 | **8053707859074311434** |
| `SELECT count(*) FROM vgs_A_edge` (no alias) | -4368291152974203613 | 3840608472580826727 |

Confirmed against production's own logs: the entry labelled `lead_data_edge`
(17 calls in the window) is the edge type-agreement refresh, which logged 19
edge refreshes in that window, on three OTHER spaces, and none on `lead_data`,
whose stored verdict was last computed at 14:51, before the window. Likewise
the entry labelled with the main KG space's `frame_slot` sums the orphan-rate
probe over every space, and that space (`vgs_nb6z72zc`, storage keys from the
`space` table) was the one taking an ingest, 174,354 write statements in the
window. Every per-space attribution in the original table was wrong.

**Trap 2: the table is full and evicting.** `pg_stat_statements.max` is 5,000
and the entry count was 4,825-4,885. `pg_stat_statements_info.dealloc` read
8,908 on 2026-10-29: each one drops the least-used 5%. A statement run a few
times an hour is evicted before it accumulates, so a diff UNDERCOUNTS
infrequent statements, and "no entry was evicted" cannot be decided from two
snapshots (an entry evicted and absent from both is invisible). This is why the
drift probes appeared to be missing beside the probes that run after them.

## What still holds

The bucket totals in `issues/239`'s re-measure: an aliased entry is still the
probe it says, just summed over spaces. Probes were ~45% of the window's
execution time, as a floor (trap 2).

The code path the issue described is real: `probe_data_changed` re-runs any
probe whose last result was unconverged before it reads the write watermark, so
a gap the job cannot close would keep its probe running on a quiet space. There
is no evidence it fires on production, so nothing was changed.

## To read production per space next time

* Diff statements without aliases, or name the space in the probe's alias
  (e.g. `e_<key>`), which separates the entries at the cost of one entry per
  space in a full table.
* Or read the maintenance job's own logs per space, which name the space.
* Raise `pg_stat_statements.max` (a parameter-group change and a restart) or
  call `pg_stat_statements_reset()` at the start of a measured window, so the
  window is not competing with 57 days of entries.
