# A Grouping URI With No Type Exists, and Nothing Can Have Created It

## Status: OPEN — one instance, origin unexplained, detection added

`urn:example:campaign:cer:reactivate_merchant_1` on the host space `prod_kg`
groups 26 objects under `hasKGGraphURI` but has only three triples of its own,
all server-managed:

    vital#hasObjectModificationDateTime   2026-04-30T08:20:12
    vital-aimp#hasObjectCreationTime      1970-01-01T00:00:00+00:00
    vital-aimp#hasObjectStatusType        ObjectStatusType_ACTIVE

No `rdf:type`, no `vitaltype`, no name. It is not a `KGEntity` — confirmed by
query, 0 rows.

## Why it matters now

A typeless subject builds no GraphObject (`_bindings_to_objects` skips entries
with no `type_uri`), so the entity is absent from its own graph, and the
retrieval guard added alongside `issues/091` returns EMPTY rather than a graph
with no entity. Verified through the client: `is_success: True`,
`objects returned: 0`.

So its 26 members are unreachable through the entity-graph read. That is the
correct behaviour for broken data — but it is silent, which is why the
maintenance cycle now reports grouping targets carrying no type.

## Why the origin is a real question

**No server-property path can create this.** All three gate on the subject being
a KGEntity:

* `server_property_quads_for_import` stamps only subjects the incoming batch
  types as `KGEntity` (`kg_server_properties.py`, the `entities` dict).
* `_backfill_one_batch_sql` selects `WHERE predicate = rdf:type AND object =
  KGEntity`.
* `count_entities_needing_backfill_sql` uses the same predicate.

So a phantom subject carrying exactly the server properties and nothing else
should be unreachable. It exists anyway.

An earlier reading of this file claimed the stamping paths would hit "any URI
used as a grouping target without an object behind it". That was asserted
without tracing them and is wrong; it is recorded because it is the obvious
wrong inference and someone will make it again.

The epoch creation time (`1970-01-01T00:00:00+00:00`) is the useful clue: a
default, not a copied value, so whatever wrote it had no real object to read a
timestamp from.

## Scope

One subject, across 85 spaces on two clusters. Surveyed by looking for subjects
carrying any server-managed predicate and no `rdf:type`/`vitaltype`.

Two readings, both untested:

1. **Residue from an incomplete delete** — an entity was removed and its
   server-managed quads survived. A single instance argues against a systematic
   delete leak, but not against one bad delete.
2. **A write path outside `kg_server_properties`** that stamps these predicates.
   Not searched for exhaustively.

## Fix

Decide what the object is. Either the URI should be a typed object, or its 26
members are grouped under the wrong URI — a data question needing someone who
knows what that campaign URI means. Deleting the three triples would orphan the
26 members instead of fixing them.

## Related

- `issues/091` — the self-link repair pass that surfaced this
