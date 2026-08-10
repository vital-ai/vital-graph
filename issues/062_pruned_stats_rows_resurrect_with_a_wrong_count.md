# A Pruned `rdf_stats` Row Reappears Carrying Only Its Post-Prune Delta

## Status: FIXED 2026-08-10 — option (1), the tombstone, at predicate granularity

`rdf_pred_stats` gains a `pruned` boolean. It makes ABSENCE from rdf_stats mean
something, which is the whole defect: absence was ambiguous between "this pair
has no quads" and "this pair was pruned", and the incremental sync resolved it
the wrong way.

* `prune_stats_tables` collects the predicates it removed rows from, with
  `RETURNING` on all three DELETE steps rather than inferring them afterwards —
  inferring means comparing stats against the quad table, the expensive thing
  pruning exists to avoid.
* `sync_stats_after_insert` degrades to UPDATE-only for a pruned predicate.
  Existing rows stay accurate (their base is right, the delta is right); absent
  ones stay absent, which sends the reader to the bounded count that answers
  honestly. A wrong-but-present row is worse than an absent one, because the
  reader trusts what it finds and only counts what it does not.
* `resync_stats_tables` and `resync_stats_for_predicates` clear the flag, since
  a recompute makes the table complete again. Without that the degradation
  would be permanent and nothing would ever have lifted it.

Per PREDICATE, not per pair: one boolean on a table holding one row per distinct
predicate — about 21 in a real space — rather than tombstones for the pairs
pruning exists to delete.

Migrated across all 41 spaces on this host.

**Test:** `test_pruned_pair_is_not_resurrected_with_a_wrong_count`, verified to
fail with the fix disabled rather than merely to pass with it.

## Original report — OPEN, demonstrated 2026-08-10

    before prune:              100,000
    after prune + ONE write:         1

Reproduced in a transaction and rolled back, on
`(vitaltype, KGEntity)` in `sp_lead_synth_100k`:

```sql
BEGIN;
DELETE FROM sp_lead_synth_100k_rdf_stats            -- what prune_stats_tables does
 WHERE predicate_uuid='3f488126-...' AND object_uuid='2d50120b-...';
INSERT INTO sp_lead_synth_100k_rdf_stats (predicate_uuid, object_uuid, row_count)
VALUES ('3f488126-...','2d50120b-...',1)             -- what sync_stats_after_insert does
ON CONFLICT (predicate_uuid, object_uuid)
DO UPDATE SET row_count = sp_lead_synth_100k_rdf_stats.row_count + EXCLUDED.row_count;
ROLLBACK;
```

## Why it happens

Two mechanisms that are individually reasonable and jointly wrong:

* `prune_stats_tables` DELETEs rows — pairs outside `[STATS_MIN_ROW_COUNT,
  STATS_MAX_ROW_COUNT]`, and anything beyond the retention caps.
* `sync_stats_after_insert` upserts with
  `row_count = row_count + EXCLUDED.row_count`, which on a missing row inserts
  the delta as the whole count.

So a pruned pair does not stay absent. It comes back understated by however much
it held when it was deleted, and nothing marks it as untrustworthy.

## Why it is worst where it matters most

Step 1 of pruning deletes pairs with `row_count > STATS_MAX_ROW_COUNT` — the
**least selective pairs in the space**. Those are exactly the ones a resurrection
turns into apparent singletons, and exactly the ones a selectivity gate must not
mistake for selective. A pair at 250,000 rows that receives one write afterwards
reports as 1, and `_selective_enough` will happily seed a plan from it.

A full `resync_stats_tables` recomputes from the quad table and repairs it, so
the window is "between resyncs" — which for an incrementally-written space is
indefinite.

## This is the issues/041 pattern again

Derived data that silently stops describing the data. The edge table was ~25%
incomplete in production; `ensure_edge_table` could not tell because it only
checked existence and non-emptiness. Here nothing checks at all: a wrong
`row_count` produces a wrong plan, not an error.

## Fixes, in increasing order of ambition

1. **Do not prune what writes can resurrect.** Replace the DELETE with a tombstone
   or a `trusted` flag, so a pair that was pruned is read as "unknown" rather than
   as its delta. Cheapest, and it removes the silent-wrong-answer property.
2. **Make the upsert refuse to create rows.** `UPDATE ... WHERE` rather than
   `INSERT ... ON CONFLICT`, so a pruned pair stays absent and falls through to
   the bounded count path, which is honest about being a bound. Small change,
   but it means new pairs are never learned incrementally.
3. **Per-predicate MCV summaries instead of per-pair rows** (`issues/061`).
   Absence becomes meaningful — "smaller than the smallest listed" — instead of
   ambiguous between "small", "pruned" and "never seen". This also removes the
   `> STATS_MAX_ROW_COUNT` deletion that makes the bug worst, and bounds the
   table by `predicates x K` rather than by distinct objects.

(1) is the immediate mitigation; (3) is the design that stops the class.

## A staleness probe should exist either way

`sync_edge_table.edge_table_orphan_rate` samples the edge table and reports drift.
`rdf_stats` has no equivalent: nothing compares a sample of stored counts against
the quad table. A cheap version — sample N pairs, recount them bounded, report the
fraction off by more than one order of magnitude — would have found this without
anyone looking for it.

## Related

- `issues/061` — the retention policy this interacts with
- `issues/041` — derived-table staleness, same failure shape
- `issues/059` — where wrong counts change the plan
