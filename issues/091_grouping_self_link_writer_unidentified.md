# 619 Grouping URIs Lost Their Self-Link, and the Writer Was Never Found

## Status: OPEN — data repaired, cause unidentified, and reads now depend on it

Every object in an entity's graph carries `hasKGGraphURI` pointing at the
entity, the entity included: it is a member of its own graph. On 2026-08-16,
619 grouping URIs across 12 host spaces were not.

Repaired (`scripts/repair_grouping_self_link.py`, both clusters verify clean)
and watched (the maintenance cycle reports violations). **What wrote them that
way is still unknown**, which is the open part.

## Why it is not just historical

The read path used to compensate. `get_entity_graph` was a UNION whose first
branch re-fetched the entity by pinning its URI, so a missing self-link produced
no symptom — the entity's own properties arrived from that branch regardless.
That is why 619 broken URIs went unnoticed.

That compensation is now gone. Entity-graph reads select in ONE branch by
grouping URI, and return EMPTY when the entity is not among its own members.
Better failure behaviour, but it means **a still-live writer would now produce
visibly empty entity graphs** rather than quietly complete-looking ones.

## What is known

* The distribution is a write path, not drift. Several spaces were 100% broken —
  `doc_test` 500 of 500, `graph_viz_a` 30 of 30, `customer_journey_test` 11 of
  11 — while `prod_kg` was 1 of 8,752.
* The predicate is ABSENT on those entities, not pointing elsewhere. Checked,
  because "missing" and "wrong" need different repairs.
* The targets are real objects: `KGEntity` in the graph_viz and
  customer_journey spaces, `KGDocument` in `doc_test`.
* **The create path is not the culprit.**
  `KGValidationUtils.set_dual_grouping_uris_with_frame_separation` assigns
  `kGGraphURI` over every object in the set, entity included
  (`kg_validation_utils.py:301`).

## What to check next

The affected spaces were populated by something other than the KG create path —
the mix of `KGDocument` and `KGEntity` targets suggests more than one. Candidates
in rough order:

1. The document ingestion path (`doc_test` is 100% broken and is documents).
2. Fixture/test loaders that write quads directly rather than through
   `create_kgentities` — `graph_viz_*` and `customer_journey_test` look
   generated.
3. `data_import_impl`, which writes quads with raw SQL.

A quicker route than reading all three: reload one affected fixture through its
own loader on a scratch space and see whether the self-link appears.

## Related

- `issues/041` — derived structures drifting with nothing comparing them
- `issues/092` — a grouping target with no type at all, same repair pass
