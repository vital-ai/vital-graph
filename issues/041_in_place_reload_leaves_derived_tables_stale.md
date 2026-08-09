# Reloading a Space In Place Leaves Derived Tables Stale, Undetectably

## Status: DETECTION ADDED 2026-08-08 — repair still manual

`sync_edge_table.edge_table_orphan_rate` samples edge rows and asks whether each
still corresponds to a `hasEdgeSource` quad. The maintenance job calls it
alongside the existing drift check and logs an error naming the space when the
rate exceeds 50%.

Why a second check was needed: `edge_table_drift` compares **counts**, and this
failure mode has identical counts. Reproduced against a fixture by replacing
every `edge_uuid` with a fresh value — same 24,885 rows either side:

```
count_drift = 0        -> "healthy" — MISSED IT
orphan_rate = 100%     -> "stale"   — caught
```

0% on every healthy space (wordnet_frames, both lead fixtures, the depth-1 and
duplicate-quad fixtures), so it does not false-positive. Bounded to a 200-row
sample, one index probe each, so cost is independent of table size.

**Repair is deliberately not automatic.** Backfill only adds rows, so it cannot
fix a table whose existing rows are all wrong; that needs `resync_edge_table`,
which TRUNCATEs and holds ACCESS EXCLUSIVE, blocking every edge-rewrite query
while it runs. Doing that unattended on a maintenance tick is a worse failure
than the one being repaired, so the job logs loudly and leaves the decision to
an operator.

What remains open is the underlying cause — that an in-place reload has no way
to signal its derived tables — and the fact that the same argument applies to
`{space}_frame_entity`, which has no equivalent probe.

Replacing a space's quads without going through the API import path leaves
`{space}_edge` holding rows built from the *previous* contents. Nothing detects
this. `ensure_edge_table` reports the table usable, `generate_sql` rewrites edge
patterns onto it, and every KGQuery frame traversal returns **zero rows** with no
error, no warning, and no log line.

Zero rows is the worst possible failure mode for a query path that is also
benchmarked: an empty result satisfies every upper-bound assertion a performance
test makes.

## Observed

`wordnet_frames` on the vg-test stack, after the space was reloaded in place with
a different export of the same dataset:

```
real Edge_hasKGSlot nodes in rdf_quad   570,696
rows in wordnet_frames_edge             570,696
edge_uuid values common to both               0     ← same size, disjoint sets
source_node_uuid resolving in term      570,696     (100%)
dest_node_uuid   resolving in term            0     (0%)
```

The table is not corrupt. It is a faithful materialisation of the previous
contents. Confirmed by reversing the UUIDs — for frame
`1716488390958_692023857` the two `edge_uuid` values are exactly `uuid5` of the
two edge URIs from the old export, and neither of those URIs exists in the
currently loaded data.

`wordnet_frames_frame_entity` was **unaffected** (285,348 rows, all uuid columns
100% resolvable). It references only frames and entities, whose URIs were
identical across the two loads. Only the table referencing the changed nodes went
stale — which is why the problem is invisible unless you query through edges.

## Why `ensure_edge_table` cannot detect it

`vitalgraph/db/sparql_sql/ensure_edge_table.py` has three independent reasons
it will never notice:

1. **It checks existence, then emptiness — never correspondence.**
   ```python
   if not table_rows:            # create if missing
   if row_count == 0:            # populate if empty
   _edge_table_ready[space_id] = True
   ```
   A table that exists and is non-empty is declared usable. Its contents are
   never compared to `rdf_quad`.

2. **A row-count check would not have helped.** The counts matched exactly —
   570,696 both sides — because the two loads held the same logical content.
   Size is not identity.

3. **A module-level process cache short-circuits even the weak check.**
   `_edge_table_ready: dict` is consulted first and never invalidated:
   ```python
   if _edge_table_ready.get(space_id):
       return True
   ```
   Once true in a process, the table is never re-examined for the process
   lifetime — so a truncate-and-reload against a live server is invisible even in
   principle.

## Which write paths are exposed

| Path | Edge table maintained? |
|---|---|
| `sparql_sql_space_impl` quad insert/delete | Yes — `sync_edge_table_after_insert` / `_before_delete` |
| `data_import_impl` (API import, 3 call sites) | Yes — `resync_edge_table` |
| **Direct COPY / bulk-load scripts** | **No** |

The third row is the gap. `scripts/load_wordnet_csv.py` and similar load
straight into the tables and call neither sync nor resync. That is consistent
with what was observed: had the incremental sync run, the table would hold the
union of both loads (1,141,392 rows). It holds exactly the old 570,696 — the
sync never ran at all.

Note also that the incremental path is insert-only for inserts; it relies on
`sync_edge_table_before_delete` to remove rows. A load that replaces data
without issuing deletes through that path accumulates rather than replaces.

## Impact

- Any KGQuery frame traversal on an affected space silently returns nothing.
- Performance benches over such a space pass while measuring nothing — this is
  how the fixture survey in
  `planning/planning_performance/kgquery_o_page_paging_generator_plan.md` nearly
  produced meaningless numbers.
- Not currently believed to affect prod, where imports go through
  `data_import_impl`. It affects local and test workflows that bulk-load, and
  anything that reloads a space in place.

## Possible fixes

Not ordered — they address different parts of it.

1. **Identity-based staleness check in `ensure_edge_table`.** Sample K rows and
   verify their `edge_uuid` still appears as a `hasEdgeSource` subject in
   `rdf_quad`. Cheap, bounded, and catches exactly this. Would need to run before
   the `_edge_table_ready` cache is consulted, or the cache made
   invalidatable.

2. **Invalidate derived tables on bulk load.** Have the COPY/bulk-load path
   truncate `{space}_edge` (and siblings) so the existing empty-table populate
   branch rebuilds them, or call `resync_all_auxiliary_tables` on completion.
   `resync_all.py` already exists for this and covers edge, frame_entity, and
   stats.

3. **Make the process cache invalidatable.** `_edge_table_ready` should be
   clearable when a space is reloaded, and arguably should not be a module global
   at all.

4. **Fail loudly instead of returning zero rows.** If a rewrite targets an edge
   table whose sampled rows do not correspond to the quads, that is a bug, not a
   legitimately empty result. It should log at warning level at minimum.

(1) or (2) alone fixes the reported case; (3) is needed for reload-against-a-
live-server; (4) is defence in depth for whatever is missed.

## Reproduce

```bash
# load a space via a bulk COPY script, query it through KGQuery — works
# reload the same space in place from data with different edge/slot URIs
# query again — zero rows, no error
```

Then:

```sql
SELECT count(*) FROM {space}_edge e
WHERE NOT EXISTS (SELECT 1 FROM {space}_term t WHERE t.term_uuid = e.dest_node_uuid);
```

Non-zero means stale. Repair with `resync_all_auxiliary_tables(conn, space_id)`.

## Related

- `issues/035_test_stack_data_accumulates_across_rebuilds.md` — same family:
  state surviving an operation that was assumed to reset it
- `planning/planning_performance/edge_table_integrity_bug.md` — prod
  `acme_kg_edge` ~25% incomplete. Distinct: that one under-counts against correct
  data; this one is complete and entirely wrong, which no count check can see
- `planning/planning_performance/kgquery_o_page_paging_generator_plan.md` — where
  this was found, and blocked on it as step 0
