# 308 — `entity_slot_sort` does not serve entity slots or multi-choice slots

## Status: OPEN, record — no caller measured slow yet, 2026-10-25

**Related:** `vitalgraph/db/sparql_sql/sync_entity_slot_sort.py` (`SLOT_VALUE_URIS`, the
table's population), `fast_slot_sort._LANE` (which slot classes the sort, filter and
projection paths serve), `fast_slot_filter.can_serve_filter`, `sync_frame_slot_table.py`
(`frame_slot`), issue 096 (the table), 208 (projection), 277 (entity slots are correctly
absent), and `tests/unit/sparql_sql/test_slot_class_maps_match_ontology.py`.

## What the table covers

`entity_slot_sort` stores one row per slot (`PRIMARY KEY (slot_uuid, context_uuid)`) for
the ten value predicates in `SLOT_VALUE_URIS`. So the fast sort, filter and projection
paths serve exactly the ten slot classes whose value predicate is one of those: Text,
Choice, JSON, URI, Boolean, Integer, Long, Double, Currency and DateTime. The unit test
above now asserts that `_LANE` equals that set. The other 17 `KGSlot` subclasses decline
the fast paths and run the general query. That is correct, but slower.

Two of the 17 come up in real data, for different reasons.

## 1. `KGEntitySlot`: answer from `frame_slot`, do not copy into `entity_slot_sort`

Counted on the local dev database, 2026-10-25 (read-only):

| space | `KGEntitySlot` |
|---|---|
| cardiff_kg, cardiff_kg_new, cardiff_uw, cardiff_kg_actions | **0** |
| wordnet_frames | 570,696 |
| sp_graph_synth_100k / 10k | 946,548 / 91,286 |
| graph_viz_a/b/c/f, space_kgquery_test, space_multi_org_crud_test, kgquery_perf | 10-93 |

Entity slots are the ends of connector frames in relation-shaped spaces. The callers that
use `KGEntitySlot` criteria are frame queries (`query_type="frame"`, e.g.
`test_scripts/vitalgraph_client_test/kgqueries/case_frame_queries.py`). Those are served by
the `frame_slot` rewrite, not by this table.

The values are already derived. `frame_slot` holds `(frame_uuid, slot_uuid, role_uuid =
slot type, entity_uuid = the slot's value)`, indexed `(role_uuid, entity_uuid)` and
`(entity_uuid, role_uuid)`. "Slot S = entity X" is one index probe there. 277 records why
entity slots are correctly absent from `entity_slot_sort`.

Copying them in would not pay:

- **Sorting** on an entity slot orders by the URI's text. "Sort by linked company" means
  sorting by the company's name, which needs a join to the target entity (possibly in
  another graph or space), and neither table provides that.
- **Cost**: about a million more rows on the relation spaces, maintained on every write,
  and 277's shortfall accounting would need reworking.

**The gap that remains.** An *entity* list (not a frame query) that filters on an entity
slot. `fast_slot_filter` declines the whole query when any slot criterion has no lane, so
one entity-slot criterion sends the query, including its served text criteria, to the
general path. No business space has entity slots today, so this is latent.

**If it ever matters, the fix is to let the fast filter path answer that one filter from
`frame_slot`, not to copy the values into `entity_slot_sort`.** The shape: for an
entity-slot `eq` criterion, a semi-join from the candidate entities' frames to
`frame_slot` on `(frame_uuid, role_uuid = slot type, entity_uuid = the value's uuid)`,
alongside the existing `entity_slot_sort` probes for the other criteria. Things to check
before building it:

- `frame_slot` keys on the slot's **direct parent frame**. `entity_slot_sort` carries the
  whole `frame_type_path` from the entity. A nested-frame criterion needs the path matched
  through the frame edges, or it returns the wrong rows (the `component_intersect.py:39`
  failure).
- **Completeness**: the filter path already requires a maintained coverage marker before
  it trusts `entity_slot_sort` (`slot_sort_coverage_is_complete`). `frame_slot` needs the
  same guarantee (memory: the edge table was once ~25% incomplete).
- A value that names no stored term is provably empty, by the existing rule.

## 2. `KGMultiChoiceSlot`: the likelier candidate, handled as `hasKGActionTypeList` is

`cardiff_uw`, same date:

- **3,267** `KGMultiChoiceSlot` instances (cardiff_kg: 21; cardiff_kg_new: 10).
- `hasMultiChoiceSlotValues` is declared `vital-core:hasMultipleValues true` (range
  `xsd:string`). Values per slot: 1 → 658, 2 → 83, **3 → 1,179**, 4 → 130, **5 → 1,169**,
  6 → 28, 8 → 8, 10 → 2, 11 → 10.
- Slot types: `UwGlUnevaluatedGates` 1,175, `UwScoreImputedFields` 1,168,
  `UwRuleInputSlots` 390, `UwSnapshotSourceSet` 269, `ProvenanceAppliesTo` 245, then
  12 / 5 / 3.
- The API already filters on them. Slot comparators `has`, `has_any`, `has_all` and
  `not_has` are exercised by
  `test_scripts/vitalgraph_client_test/kgqueries/case_multi_value_filters.py` (a
  `TagsSlot` holding `["Boston", "NYC"]`). All of them run on the general path today:
  `fast_slot_filter` serves `eq` only, and `_LANE` has no entry for the class.

Why it does not drop into the table as it stands:

- **One row per slot** (the primary key) cannot hold a set. Adding the predicate to
  `SLOT_VALUE_URIS` keeps one value per slot (`ON CONFLICT (slot_uuid, context_uuid) DO
  NOTHING`), and a filter answered from that returns a **subset** that looks complete. That
  is the failure the filter path is written to refuse.

### The design already exists: `entity_prop_sort`'s `value_all`

Marc, 2026-10-25: the entity property `hasKGActionTypeList` is the same multi-valued case,
and the multi-choice slot can be handled the same way. It is already solved there.
`entity_prop_sort` (and `frame_prop_sort`) keep **one row per (entity, context, property)**
carrying two things:

- the **MIN** in the typed lanes (`value_text` / `value_num` / `value_dt` / `value_key`),
  because a sort needs exactly one key per entity, or an entity with three values is emitted
  three times;
- **`value_all TEXT[]`**: every value, each bounded to the key length (issues/283), under a
  `GIN (value_all)` index. Membership operators read it (`value_all @> ARRAY[x]`): the
  `uri_list` datatype's `has` / `has_any` / `has_all` / `not_has` / `not_has_any` (the
  model's operator table, `kgentities_model.py:189`), and also `eq`, "because any predicate
  may become multi-valued at any time", so serving `eq` from the MIN would return a subset.
- A delete is a **recompute** of the row (the MIN moves, `value_all` shrinks, the row
  survives), not a row drop. `sync_entity_prop_sort.py:271`, and the write paths in
  `sparql_sql_space_impl.py` carry it.
- The fast path serves `action_type` as `has` (`fast_prop_sort.py:177-186`, `:230-235`).

Applied to `entity_slot_sort`:

| change | detail |
|---|---|
| `value_all TEXT[] NOT NULL DEFAULT '{}'` + `GIN (value_all)` | populated for **every** slot, not only multi-choice: the same "any predicate may become multi-valued" argument |
| population | `array_agg(DISTINCT bounded value)` per (slot, context), MIN into the lanes. This replaces `ON CONFLICT … DO NOTHING`, whose "keeping the first" depends on insert order, not on the data |
| `hasMultiChoiceSlotValues` into `SLOT_VALUE_URIS`; `KGMultiChoiceSlot` (and `KGMultiChoiceOptionSlot`, same predicate) into `_LANE` as text | the classes become served; the ontology test then requires both |
| `fast_slot_filter` | membership comparators read `value_all`. `eq` moves to `value_all` too, or stays on the `value_key` btree only where the slot is proven single-valued |
| sort | from the MIN, as `entity_prop_sort` does. Whether "sort by a tag set's smallest member" is wanted is a product question; declining sort for multi-choice classes is the other option |
| projection (208) | returns `value_all` for the slot: the whole set, which is what a display wants |
| incremental maintenance | a value insert or delete on a slot re-derives that slot's row. Check every write path the table already maintains (096) |

**Checked 2026-10-25 (read-only):** no slot of the ten classes the table stores today has more
than one value, on cardiff_uw, cardiff_kg, cardiff_kg_new or sp_lead_synth_100k. So today's
one-value-per-slot rows are complete in this data, and the subset risk above is latent. A
SPARQL write that adds a second `hasTextSlotValue` would make it real, so `value_all` fixes a
latent fast-filter subset for every slot class, not only multi-choice.

**Costs to measure:**

- Table size: sp_lead_synth_100k's table is 3.9 M rows. One element per row is typical, plus
  the GIN index.
- Write cost: GIN maintenance on every derived-row write. The fast-update pending list
  helps inserts and costs reads.
- GIN alone has no leading `(context, entity type, frame path, slot type)` prefix. 096 measured
  that prefix as the difference between 5.36 s and 271 ms for the btree probe. A membership
  probe may need `btree_gin` (a composite GIN with the prefix), or the GIN result intersected
  with the prefix btree. Measure before choosing.

**Before building anything:** find out whether any caller filters UW entities on these slot
types, and how slow it is on the general path. They read like diagnostic lists (gates not
evaluated, fields imputed, rule inputs), which suggests display rather than selection. If
they are only displayed, the need is **projection**: return the set for a page of entities.
That can be answered from the quads per page (issue 208 measured the quad side at ~58 ms
for eight values × 25 entities on 74.5 M quads) without touching this table.

## What to do

Nothing yet, on either. This records why neither slot class is in the table, what each would
take, and what to measure first: (1) an entity list filtering on an entity slot, (2) a UW
list filtering or projecting a multi-choice slot. Both on the vg test stack at production
scale.
