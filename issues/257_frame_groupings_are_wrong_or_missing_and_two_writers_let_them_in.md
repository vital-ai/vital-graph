# 257 — Frame groupings are wrong or missing in real data, and two writers let them in

## Status: OPEN, filed 2026-10-03. The writers are CLOSED and the real data is
## REPAIRED: dev's six real-data spaces and production's (2026-10-03), census 0,
## no frame reclassified. No longer blocks `issues/256`. What remains belongs to
## the deploy and is listed under "STILL TO DO": (1) deploy `main`; (2) straight
## after, re-run `scripts/repair_frame_groupings.py --apply` on production for
## anything the old code wrote in between, and confirm the census reads 0;
## (3) DEFERRED: reload the generated test datasets in both test databases from
## the fixed generators, and repair the real `sp_sql_lead_dataset` fixture there.

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

**The "slot other" rows: child frames' SLOTS grouped under the parent.**
CORRECTED 2026-10-03. The first version of this paragraph said the child FRAMES
carry the parent's grouping, from a misread sample. The repair's dry run (step 2:
0 frames not self-grouped on every space) and a direct look at one of the 925
show otherwise: the child frame IS grouped with itself; only its slots are
grouped under the parent. E.g. the slot
`…:frame:generated_message:4:frame:schedule:0:slot:days` is linked by
`…:generated_message:4:frame:schedule:0` (self-grouped) and grouped under
`…:frame:generated_message:4`. That is the FIRST `:frame:<name>:<n>` segment of
the slot's own URI, the URI-prefix derivation the old lead generator used, so
the writer of these campaign entities very likely groups slots by URI text.
232 child frames under 226 parents, campaign entities written by the API
service.

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
2. **Fix the generators. DONE 2026-10-03 (uncommitted).** The bulk-loaded
   spaces lack groupings because the generators that built them were WRONG.
   Every generator now emits both groupings by the rule, AND an explicit
   `hasKGFormType` on every frame (the decision recorded under "Form type"
   below):
   - `generate_lead_dataset.py`: a new `entity_groupings` derives groupings
     from the frame/slot/edge STRUCTURE the triples describe, replacing the
     URI-text pass that took the FIRST `:frame:<name>:<n>` segment. That pass
     grouped every nested child frame and its slots under the ROOT, and every
     parent -> child edge under the parent. Frames get `KGFormType_Aspect`
     (entity-scoped, as the server's entity-frame write sets it);
   - `generate_graph_dataset.py`: every frame is grouped with itself and is an
     explicit Assertion (standalone); slots and slot edges are grouped with
     their frame. The arbitrary `:framegraph:N` grouping for `issues/088`'s
     anti-join is gone; `--form-type-fraction` now only makes a share of
     frames explicit Aspects;
   - `generate_relation_dataset.py`: explicit form type on every frame (the
     "unset Assertion" share is gone, because under the rule it would read as
     an Aspect), groupings on every frame graph, `hasKGGraphURI` across the
     entity-attached frame, and the person's self-link (`issues/091`);
   - `generate_depth_mix_dataset.py` inherits the lead fix. Its census found an
     OLDER bug: the flattener's parent-edge regex also matched a root frame's
     SLOT edges (`…:edge:to_slot_…`), so flattening re-sourced them FROM THE
     ENTITY. Fixed with `(?!slot_)`;
   - `generate_duplicate_quad_dataset.py` and `load_wordnet_csv.py` build no
     frames. `wordnet_frames` comes from an export, so it is repaired, not
     regenerated.

   Verified by a census of each generator's output against the rule, computed
   from the structure that output describes. At HEAD: lead 814/1,074 frames
   wrong and nearly every slot; graph and relation, every frame. Fixed: zero in
   every column. `tests/unit/test_generators_follow_the_grouping_rule.py`, 4
   cases: all FAIL on HEAD's generators, all pass fixed. The lead end-to-end
   case needs the gitignored templates and skips without them.

   Existing spaces are regenerated from the fixed generators, or repaired.
   Regenerating reloads spaces, so it is done only when asked.
3. ~~**Add the census to the maintenance audit.**~~ **DROPPED 2026-10-03: this
   is a ONE-TIME data update, not something maintenance watches for.** The
   writers are closed (step 1) and the generators fixed (step 2), so nothing
   should produce bad groupings again; the census runs before and after the
   repair (step 4) instead. A sampled watch was built and removed unmerged.

**Form type (DECIDED 2026-10-03, option 2).** The server classifies a frame
WITHOUT `hasKGFormType` by grouping: no `hasFrameGraphURI` -> Assertion, has
one -> Aspect (`kgframes_endpoint.py`, copied into `sync_frame_prop_sort.py`).
Under "every frame is grouped with itself" that unset default could only fire on
defective data, and adding groupings would FLIP every unset-and-ungrouped frame
from Assertion to Aspect: every frame in `wordnet_frames` and the bulk-loaded
spaces, and an uncounted share of production's ~275,000 unset frames. So the
repair FIRST sets an explicit `hasKGFormType` on every frame lacking one, by
today's rule (no grouping -> Assertion, grouped -> Aspect), and only then
touches groupings. Nothing reclassifies. Generators emit it explicitly too.

**Method (decided 2026-10-03): SPARQL UPDATE** for setting these properties in
bulk, not the per-subject API write path. The update path takes the grouping
locks in the write's transaction (`acquire_update_locks`) and re-derives the
edge, frame_slot, slot-sort and both prop-sort tables for the subjects it
touches. Two cautions from its own code: an edge-table sync failure after an
update is logged as non-critical rather than raised, and under heavy
concurrent writes the update lock can give up and proceed unlocked
(`issues/174`'s residual). So production runs in a quiet window, with the
census before and after.

**Step 4 tooling, written 2026-10-03 (not yet run on dev):
`scripts/repair_frame_groupings.py`.** Through the server only, by SPARQL
UPDATE, in bounded batches (SELECT up to `--batch` violators, fix exactly those
with one `VALUES` UPDATE, repeat). In order: 1a/1b explicit form type by today's
default (grouped -> Aspect, ungrouped -> Assertion), 2 frames self-grouped,
3 slot edges -> source frame, 4 slots -> linking frame (a slot linked from two
frames is skipped and reported), 5 parent -> child edges ungrouped. Dry run by
default; its per-step counts ARE the census, before and after. **Trial on the
vg test stack**, on a throwaway space seeded with each defect the census found:
the dry run counted exactly the seeded defects; `--apply` (batch 2, so the loop
ran) brought every step to 0; the child, its slot and slot edge regrouped under
the child, the parent -> child edge lost its grouping, the control frame was
untouched, and **every frame kept its classification** (Aspect/Assertion by
the server's own rule, compared before and after).

**Which spaces are repaired (DECIDED 2026-10-03).** Only REAL-DATA spaces are
repaired: the three production copies, plus the actions, underwriting and lead
test copies. Every generated or throwaway TEST dataset is RELOADED from the
fixed generators instead (`sp_lead_*`, `sp_graph_synth_*`, `sp_kg_rel`,
`sp_lead_types`, `kgquery_perf`, `sp_sql_lead_dataset`, and the API test
spaces). **Open: `wordnet_frames`.** It is a test dataset but no generator
builds it; it is loaded from the canonical export (`kgframe-wordnet-0.0.1.vital`
-> `-vt.nt`), which carries no groupings, so reloading it "with fixed data" first
needs a conversion step that adds them by the rule.

**Dev dry run, 2026-10-03** (`scripts/repair_frame_groupings.py`, counts only,
through the dev server), on the real-data spaces:

| space | 1a form type -> Aspect | 1b -> Assertion | 2 frames | 3 slot edges | 4 slots | 5 parent->child edges |
|---|---:|---:|---:|---:|---:|---:|
| main KG copy | 52,700 | 0 | 0 | 1 | 925 | 232 |
| main KG copy, newer | 52,691 | 0 | 0 | 1 | 913 | 232 |
| main KG archive | 22 | 0 | 0 | 0 | 925 | 232 |
| actions copy | 11,399 | 0 | 0 | 0 | 1 | 0 |
| underwriting copy | 0 | 0 | 0 | 0 | 0 | 899 |
| lead test copy | 0 | 0 | 0 | 0 | 0 | 0 |

No slot is linked from two frames anywhere. Step 1b is 0 everywhere: no frame
is unset AND ungrouped, so the form-type step reclassifies nothing.

**`wordnet_frames`, the conversion step, DONE 2026-10-03:
`scripts/add_frame_groupings.py`** (.nt -> .nt), between the `.vital`
conversion and the CSV. On `kgframe-wordnet-0.0.1-vt.nt` in 18s: all 8,582,356
lines kept, and 1,712,088 triples added (285,348 frames self-grouped and made
explicitly Assertion, as they read today; 570,696 slot edges and 570,696 slots
grouped with their frame). The census of the output reports none of the rule's
violations. Output: `test_data/kgframe-wordnet-0.0.1-vt-grouped.nt`. Not yet
converted to CSV or loaded.

**DEV REPAIR DONE, 2026-10-03.** All six real-data dev spaces read 0 in every
step after the repair: archive (22 form types, 925 slots, 232 edges), actions
(11,399 form types, 1 slot), underwriting (899 edges), main KG (52,700 form
types, 1 slot edge, 925 slots, 232 edges), main KG newer (52,691, 1, 913, 232),
lead test (already clean). Recounted after each.

What the dev runs taught, now in the script:
- whole-space SPARQL counts time out on production-sized spaces; discovery is
  READ-ONLY SQL (`--discover-sql PREFIX`), set-based, term uuids inlined as
  literals: a full census of the main copy in 5-7s, of the production actions
  space in 90s cold. The first SQL version probed per row (~180k buffers per
  18.7k frames) and ran >10 min on production before it was cancelled. A
  version reading uuids from a one-row CTE could not use the (predicate,
  object) index and scanned the table;
- a 500-row regrouping UPDATE ran past the server's 60s statement timeout, and
  once proceeded UNSERIALISED after failing to acquire its grouping locks
  (`issues/174`); it rolled back. Regrouping now runs at `--batch 50` (~30s per
  batch on dev), form-type inserts at `--form-batch 500`;
- the client's 30s timeout cut off an update the server then committed;
  `--timeout` (600s default).

**Production dry run, 2026-10-03** (read-only SQL on the live cluster):

| space | 1a -> Aspect | 4 slots | 5 parent->child edges |
|---|---:|---:|---:|
| main KG | 275,577 | 1,740 | 435 |
| actions | 251,790 | 1,740 | 435 |
| lead data | 289,920 | 0 | 0 |
| lead prod | 3 | 0 | 0 |
| main KG archive | 0 | 0 | 0 |
| underwriting | 0 | 0 | 0 |

Steps 1b, 2 and 3 are 0 everywhere, so nothing reclassifies.

**PRODUCTION REPAIR DONE, 2026-10-03.** Read-only SQL discovery, writes by
ground `DELETE DATA` / `INSERT DATA` through the production server: lead prod
(3 form types), actions (251,790 form types, 1,740 slots, 435 edges), lead data
(289,920 form types, 27 min), main KG (275,577 form types, 1,740 slots, 435
edges, 89 min). A final independent census of all six real-data spaces, the
archive and underwriting included, reads 0 in every step. On the way, a
`DELETE/INSERT ... WHERE { VALUES ... OPTIONAL }` regrouping batch of 50 hit the
60s statement timeout on production after running unserialised (lock plan
resolved no groupings); it rolled back. Ground updates run ~1.25s per batch.

**STILL TO DO.** (1) Deploy `main` (the grouping writers closed, `issues/256`
frame-graph replace), done separately. (2) Then run the repair again, to catch
anything the old writers wrote in between (`scripts/repair_frame_groupings.py
--discover-sql ... --apply`). (3) Reload the generated test datasets in both
test databases from the fixed generators, and repair the real `sp_sql_lead_dataset`
fixture there; deferred.

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
