# The Edge Table Has No Type Column, So Every Typed Hop Costs a 24 GB Join

## Status: LANDED locally; remaining work is non-local spaces — 2026-08-10

> **MEASURED ON A 1 GB BUFFER POOL — see `issues/081`.** At risk: the 31x figure. `shared_buffers` was 1 GB on a 64 GB machine against queries touching 400,000+ buffers; raising it to 16 GB moved a comparable query 16,411 ms -> 616 ms with no code change. Plan shapes, row counts and buffer counts are unaffected.

Verified on the local cluster:

* **Column present on every `*_edge` table.** No table lacks it.
* **Populated wherever the data has types.** `sp_lead_synth_100k` 4,977,000 /
  4,977,000 and `wordnet_frames` 570,696 / 570,696 — both 100%.
* **Indexes built** — `idx_*_edge_type_dst` and `idx_*_edge_type_src`.
* **Consumed** — `emit_backward._walk_select` and `emit_candidate_ctes` emit
  `e.edge_type_uuid = '...'::uuid` as a column predicate, which is the whole
  point of the column, and `sync_edge_fanout` uses it for per-edge-type
  cardinality.

Four tables read 0% typed and NONE of them is drift. Checked rather than
assumed: `inttest_5afcdedf210d` has **zero `vitaltype` quads** in the space at
all, so NULL is the correct value for all 10,500 of its edge rows — case (2) in
`sync_edge_table.edge_table_untyped_rate`, which already documented exactly this
for `wordnet_exp`. Two more are transient integration-test spaces of 30 rows.

That distinction is the reason `edge_table_untyped_rate` is documented as a
CAPABILITY signal rather than a drift signal. A 0% reading looks alarming and
usually means the data carries no types, not that the derived column is stale.
Establishing drift needs the referential check in `edge_table_orphan_rate`.

**What is left is operational, not code:** spaces outside this cluster need the
migration (`scripts/migrate_edge_type_column.py`) and a backfill
(`scripts/rebuild_edge_tables.py`). That is a deploy step, not a change.

## Original status: OPEN, measured 2026-08-10 — 31x on a real query

    sp_lead_synth_100k_edge:  edge_uuid, source_node_uuid, dest_node_uuid, context_uuid

The edge table collapses `entity -> frame -> slot` traversals into single rows,
which is why it exists. But it does not record **what kind of edge** each row is.
Discriminating `Edge_hasKGSlot` from `Edge_hasEntityKGFrame` therefore requires
joining back to the quad table on `edge_uuid` for a `vitaltype` triple — undoing
part of the join reduction the table was built to provide.

Measured on the backward negation query in `issues/059`, identical except for
type discrimination:

| | time |
|---|---|
| untyped hops | **~700 ms** |
| typed hops, via quad joins | **~22,000 ms** |

**31x, and 21.3 seconds of it is pure type checking.** Three hops, three joins
against a 24 GB quad table whose `vitaltype` predicate alone holds 10,054,000
rows.

## Proposal

Add `edge_type_uuid` to the edge table, populated from the edge node's
`vitaltype`, so a typed hop is a column predicate instead of a join.

**Storage.** The table is 4,977,000 rows / 2,178 MB for this space. One uuid
column is 16 bytes/row, about 80 MB — **under 4%** of the table, against a 24 GB
quad table. An index on `(edge_type_uuid, dest_node_uuid)` would add more; whether
it is needed depends on whether the type or the endpoint is the more selective
filter, which should be measured rather than assumed.

**Population.** It is derived data, and this codebase has a bad record with
derived data that the write path maintains: the production edge table was ~25%
incomplete (`issues/041`), and an in-place reload has no way to signal derived
tables. Options, in order of safety:

1. A **generated column** cannot work — the value comes from another table.
2. **Maintained by `resync_all_auxiliary_tables`**, alongside how the table is
   already built, with the orphan-rate probe extended to cover type drift. This
   is the honest option: same failure mode as today, same detection.
3. **Maintained incrementally on write**, which is how the existing edge rows are
   kept current and how they went 25% stale.

Option 2 with a staleness probe is the recommendation. A wrong `edge_type_uuid`
does not fail loudly — it silently answers frame queries with the wrong rows,
exactly like `issues/041`.

**Migration.** `ALTER TABLE ... ADD COLUMN` plus a backfill; on 5M rows that is
minutes, not hours. Every space needs it, and
`test_fixture_indexes_match_schema` will flag any that lack it once the schema
declares it.

## Why this is worth more than the 31x suggests

Type discrimination is not incidental to the KG model — `entity -> frame -> slot`
traversals are *defined* by edge type, so essentially every KGQuery hop pays this
join today. The measurement above is one query; the tax is on all of them. It is
also a precondition for `issues/059`: the backward negation rewrite is only worth
building if a typed hop is cheap, because with the current join it turns a 700 ms
plan into a 22 s one.

## Related

- `issues/059` — the backward negation rewrite this unblocks
- `issues/041` — derived-table staleness, the risk this proposal has to answer
- `high_cardinality_slot_value_query_plan.md` — the edge table's original
  rationale, "reducing joins via the supporting edge tables was critical"
