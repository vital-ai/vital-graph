# 352 — ANALYZE of a term table costs 84-98 s, and the 10000 statistics target is why

## Status: OPEN 2026-11-25. Not started. Measured on production, read-only.

## Found

From `349`'s `pg_stat_activity` sample of production cycles (2026-11-25, 04:15 → 04:42 UTC,
read-only):

| statement | wall | share of maintenance | longest |
|---|---:|---:|---:|
| `ANALYZE` (term 98 s, quad 24 s, others) | 129 s | 12 % | 84 s |

The 2026-11-25 status note saw the same thing live: an `ANALYZE` on the UW space ~47 s in,
IO-bound, no lock waits.

## Cause (from the code)

`sparql_sql_schema.py` ~1893-1908 sets `SET STATISTICS 10000` on the term table's numeric
and datetime columns (`issues/056`). PostgreSQL samples `300 × max(target)` rows for the
**whole** table, so one high-target column makes every `ANALYZE` of the table read a
3,000,000-row sample:
- across all columns;
- with page reads spread over the whole heap.

The comment records the cost as "ANALYZE on 10.4M rows took 8.3s". The production main KG
term table is 10 GB, and at that size the sample touches a large share of its pages.

When it runs: `_tables_needing` → `analyze_floor` is
`max(10,000, VG_ANALYZE_SCALE_FACTOR × live rows)` per table, with a default of 2 %
(`issues/270`). A term table on a continuously written space crosses that regularly. How
often on production is not measured yet.

## First step (read-only)

- **How often, and how long.**
  - `pg_stat_user_tables.analyze_count` (and `last_analyze`) for each space's term table,
    read twice a day apart: this job's analyses per day.
  - The `ANALYZE` process rows the job tracks, or the "ANALYZE … tables have work" log
    lines, give durations.
- **Whether the high target still matters at production scale.** `pg_stats.histogram_bounds`
  length and `null_frac` for the two columns.

## Options

1. **Analyze the two columns separately.**
   - A frequent `ANALYZE term (<other columns>)` at the default target.
   - An infrequent `ANALYZE term (num_val, dt_val)` at 10000.
   - PostgreSQL sizes the sample by the columns named. Each of these is an ordinary
     `ANALYZE`, so `_run_analyze`'s per-table call would need to know about the split.
2. **Raise this table's scale factor:** a per-table floor, as `issues/270` did for the
   quad table. Simplest. It delays the planner seeing new numeric/date values on that
   space.
3. **Lower the target** to the smallest value that still keeps `issues/056`'s two
   timeouts fixed. Measure that on the vg stack at production scale; don't guess it.

Whichever is chosen, `issues/056`'s regression must stay pinned: `num_val <= 65.0` on a
sparse column has to estimate within an order of magnitude.
