# 619 Grouping URIs Lost Their Self-Link, and the Writer Was Never Found

## Status: WRITERS IDENTIFIED AND FIXED 2026-08-19 — three of them, found from
## the data's URI prefixes

Not one writer but three, and the affected spaces name them:

    urn:vitalgraph:graphviz:entity:*   generate_graph_viz_test_data._entity
    urn:vitalgraph:journey:event:*     generate_customer_journey_events._event_entity
    .../app/KGDocument/<hex>           kgdocuments_endpoint._create

All three had the identical shape: every MEMBER object took
`kGGraphURI = <root URI>` and the root itself took none. In the two generators it
is visible in a single function — `_entity` builds the KGEntity and returns it,
while the twelve lines that follow set `kGGraphURI` on every frame, edge and slot.

**The document one is shipped code, and it is the one that mattered.** The
segmentation path ALREADY elects the document as the grouping root:

    kg_graph_uri = original_properties.get("kGGraphURI", original_uri)
    # kgdocument_segmentation_processor.py:164, auto_segmentation.py:132

So a document created with no grouping URI still gets segments and edges grouped
under it — it is simply absent from the group it roots. That is why `doc_test`
was 500 of 500 while `prod_kg`, populated through the entity create path, was 1
of 8,752. `_create` now calls `_set_document_grouping_uris`, which fills the value
ONLY when absent and only with the object's own URI: a caller may legitimately
group a document elsewhere, and a segment is `KGDocument`-typed too but arrives
carrying its parent's URI. That is the same rule line 164 uses, so the two agree
by construction rather than by coincidence.

Verified end to end against the rebuilt image: `POST /api/graphs/kgdocuments`
with three quads and no grouping URI now stores
`hasKGGraphURI = <the document's own URI>`.

`_upload_document` routes through `_create`, so both entry points are covered.

### How they were found

By looking at the data rather than reading the candidate list. The grouping-URI
values in each affected space carry a distinctive prefix, and each prefix is
built by exactly one function — `_BASE = "urn:vitalgraph:graphviz"` at
`generate_graph_viz_test_data.py:61`, `URI_PREFIX` at
`generate_kgdocuments_test_data.py:55`. The candidate list below had the document
path at #1 and the fixture loaders at #2; both were right, and neither needed the
reload experiment it proposed.

Every object in a grouping graph carries `hasKGGraphURI` pointing at the root,
the root included: it is a member of its own graph. On 2026-08-16, 619 grouping
URIs across 12 host spaces were not.

> **Scope note added 2026-08-21.** The root is not always an entity — the
> entity graph is the main case, not the only one. A `KGDocument` roots its own
> graph the same way (`kgdocuments_endpoint._set_document_grouping_uris` exists
> because that path once wrote documents with no grouping URI at all), and
> `apitest_37a59eb5` holds such a root with 8 members and no self-link, which
> the repair script handles correctly. Reading "groups objects" as "is an
> entity" is a live source of error: it produced a residue guard that was
> shipped and withdrawn the same day (`37332fd`, `issues/092`). `hasFrameGraphURI`
> is a separate, narrower scope — the frame, its slots and its edges.

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
