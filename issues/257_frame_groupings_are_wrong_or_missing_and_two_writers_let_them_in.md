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
- an `Edge_hasKGSlot`'s is its source frame.

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

`sp_lead_synth_100k` (the 50M-quad space) was still running when this was
filed; the same loader built it as `sp_lead_synth_10k`. The actions copy also has
one slot edge pointing at a slot that does not exist.

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

## How it got in — two server-side openings, by reading

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

## What to do, in order

1. **Close the openings.** All of the following are on every frame write path,
   both routes, and each needs a test that fails on today's code:
   - the server sets every grouping and ignores any the client sent;
   - grouping is derived from `Edge_hasKGSlot` for every `KGSlot` subclass, not
     a list of six;
   - the dead `set_dual_grouping_uris` is deleted.
2. **Make the loaders set groupings**, or record explicitly that a bulk-loaded
   space does not support frame writes. Decide which.
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
