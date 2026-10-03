# 257 — Frame groupings are wrong or missing in real data, and two writers let them in

## Status: OPEN, filed 2026-10-03. Nothing is repaired. BLOCKS `issues/256`'s
## frame-graph fix, which deletes by `hasFrameGraphURI` and would lose or
## miss data on every space listed below until this is done.

## The rule (decided 2026-10-03, `issues/256`)

`hasFrameGraphURI` IS the definition of a frame graph. It is not an index to be
second-guessed: a structure-based alternative was proposed and rejected. And
**every frame is grouped with itself**:

- a `KGFrame`'s `hasFrameGraphURI` is its own URI;
- a slot's is the frame that links it by `Edge_hasKGSlot`;
- an `Edge_hasKGSlot`'s is its source frame;
- an `Edge_hasKGFrame` (parent -> child) and an `Edge_hasEntityKGFrame` have
  NONE: structural links are in no frame's graph (decided 2026-10-03).

Nothing a frame does not own carries its grouping. That is what keeps `update`
shallow and makes `replace` the only subtree operation
(`planning_sql/kg_query/frame_hierarchy_consistency_plan.md` §3, pinned by
`test_update_preserves_children`).

## What the data holds

A census of every `Edge_hasKGSlot` (frame F → slot S) on the dev cluster, all 44
spaces, read from the raw quad table. The `_edge` projection is known to be
incomplete, so it is not used. Columns:
- **slot missing**: S has no grouping;
- **slot other**: S is grouped under a frame other than F;
- **edge missing**: the edge lacks `hasFrameGraphURI = F`;
- **shared**: S is linked from more than one frame.

| spaces | slot edges | slot missing | slot other | edge missing | shared |
|---|---:|---:|---:|---:|---:|
| API-written test spaces (≈20) | 12–320 | 0 | 0 | 0 | 0 |
| production copies: underwriting, lead test, actions | 122k–401k | 0 | 0 | 0 | 0 |
| **production copy: main KG space** | 309,414 | 0 | **925** | 1 | 0 |
| **production copy: main KG space, newer copy** | 312,302 | 0 | **913** | 1 | 0 |
| **production copy: main KG archive** | 61,395 | 0 | **925** | 0 | 0 |
| **bulk-loaded / generated**: `sp_lead_synth_10k`, `sp_graph_synth_10k`, `sp_graph_synth_100k`, `sp_lead_types`, `sp_lead_depth1`, `sp_lead_dup`, `sp_kg_rel`, `sp_sql_lead_dataset`, `kgquery_perf`, `wordnet_frames` | 220–947k | **all** | 0 | **all** | 0 |
| `space_client_kgentities_test` | 14 | 9 | 0 | 9 | 0 |

`sp_lead_synth_100k` (the 50M-quad space), finished after filing: 3,877,000 slot
edges, every slot and edge ungrouped, as the loader's other spaces. The actions
copy also has one slot edge pointing at a slot that does not exist.

**The "slot other" rows are subtrees grouped under their ROOT.** Classified on
the main KG copy: in all 925, the frame the slot names exists and is the PARENT
of the linking frame (232 child frames under 226 parents), and the child frame
itself carries the parent's grouping too. They are campaign entities written by
the API service. The census counts slots only, so **the number of FRAMES grouped
under another frame is not yet counted**. It is at least the 232 children above.
Extend the census to frames before repairing.

**The bulk-loaded spaces have no grouping at all**: no `hasFrameGraphURI` term
exists in them. `sp_lead_depth1` has no `hasKGGraphURI` either, so its entity
graphs are invisible to entity-graph reads and deletes, not only to frame
operations.

## How it got in — the server-side openings

**STEP 1 DONE 2026-10-03 (uncommitted; see "Step 1, as built" below).** The two
openings first listed here were found by reading. Testing found the list was
both short and partly wrong: five live openings in all, one of them in the
server's OWN slot edges, and one listed opening sat on a path nothing calls.

As first written:

1. **`_update_entity_frames` trusts a client's grouping.** Its pass 2
   (`kgentities_endpoint.py`, the `KGSlot` branch) does
   `if graph_obj.frameGraphURI: target_frame_uri = str(graph_obj.frameGraphURI)`
   and only infers from `Edge_hasKGSlot` otherwise. The documented rule is that
   clients NEVER set grouping URIs (`frame_hierarchy_consistency_plan.md` §5).
   This path takes whatever was sent, so a client that re-sends what it read, or
   builds its own, writes it.
2. **The update processor's grouping knows six slot classes.**
   `KGEntityFrameUpdateProcessor.assign_grouping_uris` →
   `graph_operations.set_dual_grouping_uris` →
   `validation_utils.analyze_frame_structure_for_grouping`, which recognises
   text, integer, boolean, double, datetime and entity slots only. Choice, URI,
   geo, currency and every other slot keep whatever grouping they arrived with.
   `graph_operations.py` also defines `set_dual_grouping_uris` TWICE (`:63` and
   `:401`); the second silently replaces the first, so the first is dead and
   misleading.

Which writer produced the 925 is NOT established. Neither opening alone
explains a child FRAME carrying its parent's grouping: every current frame path
sets a frame's grouping to itself. The likeliest source is a client sending a
grouping the server kept, or an older server version. Find it before declaring
the openings closed: the API service's frame-write code, and its request logs
for the affected entities' frame writes.

The bulk loaders are a third source. The synthetic generators and whatever
loaded `wordnet_frames` write no groupings at all.

## Step 1, as built (2026-10-03)

**One function decides every grouping:** `kg_impl/frame_grouping.py`,
`assign_frame_groupings`. It applies the rule, discards what the client sent,
and raises `UngroupableSlot` for a slot whose frame it cannot determine. Each
route answers that with INVALID_REQUEST in a 200 and writes nothing. Every live
grouping site delegates to it:

| site | route | what leaked before |
|---|---|---|
| `KGEntityFrameCreateProcessor.assign_grouping_uris` | entity-frame create / update / upsert | a slot with no edge in a multi-frame request; an edge whose frame was not in the request |
| `_update_entity_frames` pass 2 | entity-frame update | TOOK the client's slot grouping first; with several frames, fell back to whichever came first |
| `KGFrameCreateProcessor.assign_frame_grouping_uris` | `/kgframes` create / update / upsert / replace | as the first row |
| `KGGroupingURIManager.set_dual_grouping_uris_with_frame_separation` | entity create / update / upsert | a slot not linked by an edge from a frame in the payload |
| `KGEntityCreateProcessor`, multi-entity batch | entity create | the batch's frames and slots were never grouped at all |
| `_create_frame_slots` | `/kgframes/kgslots` create | the Edge_hasKGSlot the SERVER creates had NO grouping; a client's edge kept the client's value |
| `KGEntityFrameUpdateProcessor.assign_grouping_uris` | (pre-step, regrouped later) | the six-class helper; its errors were swallowed |
| both `replace` routes | | now decide groupings BEFORE their non-atomic deletes, so a refusal cannot leave neither old nor new frames |

**Corrections to the first version of this issue, from the tests:**
- the slot route DID group its slots (`_set_slot_frame_relationships`); its
  leak is the EDGES, above. The slot processor first suspected,
  `KGSlotCreateProcessor` via `_create_slots`, has NO caller;
- the six-class helper was not where groupings were lost on update, because the
  create processor regrouped after it. The losses were pass 2 and the
  processor's own gaps.

**Deleted:** `vitalgraph/utils/graph_operations.py` (nothing imported it; it
defined `set_dual_grouping_uris` and `set_entity_grouping_uris` twice each) and
`validation_utils.analyze_frame_structure_for_grouping`, its only caller's
helper.

**Tests:**
- `tests/unit/test_frame_grouping.py`: 15 cases, pass.
- `tests/api/test_frame_grouping_contract.py`: 7 cases, on the vg test stack
  driven by the `vital-graph` conda env. With HEAD's server code in the tree
  (the API conftest rebuilds the app image from the working tree), 6 FAIL, each
  on its opening, and 1 guard passes. With the change, 7 PASS.

**Found on the way, NOT changed here:**
- `KGSlotCreateProcessor` / `KGFramesEndpoint._create_slots` and
  `KGFrameHierarchicalProcessor.create_child_frames` /
  `KGFramesEndpoint._create_child_frames` have no callers: dead. The client's
  `create_child_frames` posts to `/kgframes` with `parent_uri`, the standalone
  path. The dead `KGSlotCreateProcessor` also set a slot's `hasKGGraphURI` to
  its FRAME;
- `vitalgraph/kg/` has no importers: a dead package;
- in a multi-entity batch, frames and slots get no `hasKGGraphURI`: an
  entity-grouping gap, outside this issue;
- **`Edge_hasKGFrame` (parent → child): DECIDED 2026-10-03, NO grouping**, like
  `Edge_hasEntityKGFrame`. A structural link between frames is in no frame's
  graph: a shallow `update` of either frame leaves it alone, and only a subtree
  operation (`replace`, recursive delete) removes it, explicitly. It had been
  inconsistent: `/kgframes` with `parent_uri` grouped the server-made edge with
  the CHILD, the entity route's server-made edge had none, a client-sent one kept
  the client's value, and the dead hierarchical processor used the PARENT. A
  first build that grouped it with the parent broke two guarded child-write tests
  (two groupings in one write), which is how the question surfaced. Now built and
  tested: `test_a_standalone_parent_child_edge_has_no_grouping` and
  `test_a_client_sent_parent_child_edge_loses_its_grouping` FAIL on HEAD and
  pass with the change. **Existing data:** parent -> child edges that carry a
  grouping are cleared in the step 4 repair, and the extended census counts them.

**Regression runs, final (vg test stack, `vital-graph` conda env):**
`test_frame_grouping_contract.py` 9 cases: 8 FAIL on HEAD's server code and 1
guard passes; all 9 pass with the change. Full `tests/api` 565 tests, 0
failures, 9 skipped; `tests/unit` 5,182 tests, 6
failures, all `test_document_converter` (the env lacks `mammoth` and
`pdfplumber`).

## What to do, in order

1. **Close the openings. DONE (uncommitted), above.** All of the following are on every frame write path,
   both routes, and each needs a test that fails on today's code:
   - the server sets every grouping and ignores any the client sent;
   - grouping is derived from `Edge_hasKGSlot` for every `KGSlot` subclass, not
     a list of six;
   - the dead `set_dual_grouping_uris` is deleted.
2. **Fix the generators. DECIDED 2026-10-03: the bulk-loaded spaces lack
   groupings because the generators that built them are WRONG**, not because
   such spaces are a different kind of space. Every generator must emit both
   groupings by the rule: `hasKGGraphURI` = the entity on every object of an
   entity graph, and `hasFrameGraphURI` = the frame itself / the frame that links
   the slot / the edge's source frame. What each does today, by reading:
   - `scripts/generate_lead_dataset.py`: groupings were added to the NURTURE
     path only (`2ee163ba`, 2026-09-06, `issues/171`); the base lead path that
     built `sp_lead_synth_*`, `sp_lead_types`, `sp_lead_depth1` and
     `sp_lead_dup` emits none. The nurture path derives the frame by PARSING the
     URI, taking the first `:frame:<name>:<ordinal>` segment, so a nested child
     frame's slots would be grouped under the ROOT. That is the production
     defect's shape, written into a fixture. Unverified against its output.
     Derive from the frame/slot/edge structure the generator itself builds,
     not from URI text;
   - `scripts/generate_graph_dataset.py`: none by default; with
     `--form-type-fraction` it deliberately sets some frames' `hasFrameGraphURI`
     to an arbitrary `:framegraph:N` URI, not the frame, for `issues/088`'s
     anti-join case. The rule forbids that shape, so that case needs another way
     to arise;
   - `generate_relation_dataset.py`, `generate_depth_mix_dataset.py`,
     `generate_duplicate_quad_dataset.py`, `load_wordnet_csv.py`: none.

   Each fix is checked by running the census on a freshly generated space:
   every column 0. Then the existing spaces are regenerated from the fixed
   generators, or backfilled. Regenerating reloads spaces, so it is done only
   when asked.
3. **Add the census to the maintenance audit**, as `issues/091`'s self-link
   check was, so drift is reported rather than found by accident. It must
   cover frames as well as slots and edges.
4. **Repair the data, dev first.** Apply the rule above. For the production
   copies, regroup each child frame and its slots under the child. For the
   bulk-loaded spaces, backfill. The rewrite must keep the derived tables in
   step (frame_slot, edge, slot-sort, prop-sort, FTS), so it goes through the
   same subject-level write path the API uses, not raw `UPDATE`s on the quad
   table. Re-run the census after: every column 0.
5. **Production** through its own change: the census on production first, then
   the repair, then the census again.
6. **Only then** land `issues/256` item 1 (the frame-graph replace).

## The census query

Run per space with `psql -v sp=<space> -v t=<space>_rdf_quad -f census.sql`.
`statement_timeout = 0`. It takes about 30 minutes on a 50M-quad space.

```sql
WITH k AS (
  SELECT vitalgraph_term_uuid('http://vital.ai/ontology/vital-core#vitaltype','U')          AS vt,
         vitalgraph_term_uuid('http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot','U')    AS cls,
         vitalgraph_term_uuid('http://vital.ai/ontology/vital-core#hasEdgeSource','U')      AS src,
         vitalgraph_term_uuid('http://vital.ai/ontology/vital-core#hasEdgeDestination','U') AS dst,
         vitalgraph_term_uuid('http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI','U')  AS fgu
),
e AS (SELECT q.subject_uuid AS e, q.context_uuid AS g
      FROM :"t" q, k WHERE q.predicate_uuid = k.vt AND q.object_uuid = k.cls),
es AS (SELECT e.e, e.g, s1.object_uuid AS f, d1.object_uuid AS s
       FROM e, k, :"t" s1, :"t" d1
       WHERE s1.subject_uuid = e.e AND s1.context_uuid = e.g AND s1.predicate_uuid = k.src
         AND d1.subject_uuid = e.e AND d1.context_uuid = e.g AND d1.predicate_uuid = k.dst),
c AS (SELECT es.*,
  EXISTS (SELECT 1 FROM :"t" x, k WHERE x.subject_uuid = es.s AND x.context_uuid = es.g
          AND x.predicate_uuid = k.fgu AND x.object_uuid = es.f) AS slot_ok,
  EXISTS (SELECT 1 FROM :"t" x, k WHERE x.subject_uuid = es.s AND x.context_uuid = es.g
          AND x.predicate_uuid = k.fgu) AS slot_has_any,
  EXISTS (SELECT 1 FROM :"t" x WHERE x.subject_uuid = es.s AND x.context_uuid = es.g) AS slot_exists,
  EXISTS (SELECT 1 FROM :"t" x, k WHERE x.subject_uuid = es.e AND x.context_uuid = es.g
          AND x.predicate_uuid = k.fgu AND x.object_uuid = es.f) AS edge_ok
  FROM es)
SELECT :'sp' AS space, count(*) AS slot_edges,
  count(*) FILTER (WHERE NOT slot_exists)                  AS slot_absent,
  count(*) FILTER (WHERE slot_exists AND NOT slot_has_any) AS slot_missing,
  count(*) FILTER (WHERE slot_has_any AND NOT slot_ok)     AS slot_other,
  count(*) FILTER (WHERE NOT edge_ok)                      AS edge_missing,
  (SELECT count(*) FROM (SELECT s, g FROM es GROUP BY s, g
                         HAVING count(DISTINCT f) > 1) m)  AS shared
FROM c;
```
