# A Grouping URI With No Type Exists, and Nothing Can Have Created It

## Status: CLOSED 2026-08-21. Membership-scope question decided (the delete
## stays scoped, reachability ruled out). ONE guard, not two — the
## edge-based one was withdrawn the same day; see the correction at the end.
## The origin of the 19 is NOT established.

Two things in the original filing were wrong.

**It is not one instance.** Scanned across every current space on 2026-08-20:

    kg_crud_stress_test            10
    space_client_kgentities_test    5
    space_multi_org_crud_test       3
    <one client space>              1

19 typeless grouping targets across 4 live spaces, three of them created by test
suites — so this is reproducible, not archaeological.

**The example this file was written about is gone.** `prod_kg` no longer exists
on any cluster, so `urn:example:campaign:cer:reactivate_merchant_1` cannot be
inspected. The description below is all that survives of it.

### What the 19 look like, and where they came from

EVERY ONE owns exactly one triple: its own self-link. No type, no name, nothing
else. That is `scripts/repair_grouping_self_link.py`, the `issues/091` repair,
which selected every grouping target lacking a self-link and inserted one **with
no type check at all**. Where a URI was used as a group label with nothing behind
it, the repair did not fix anything — it manufactured a subject whose only triple
is `X hasKGGraphURI X`, making a phantom look like an object while the graph
still reads EMPTY.

It did not create the phantoms. It made them harder to see.

### What landed

* **The repair now skips a typeless target and says so**, on the same principle
  it already applied to a misdirected one: a repair that cannot restore the
  invariant should report rather than write something that hides the breakage.
* **And it reports typeless targets it did not create.** The skip alone was not
  enough — after the 2026-08-16 run those 19 are no longer *missing* a self-link,
  because this script gave them one, so they were invisible to their own cause. A
  detector that stops seeing a condition once it has written a row is reporting
  its own effect.

Verified: the three affected spaces now report 10 / 5 / 3, matching the manual
scan, and a freshly planted phantom is reported as `1 TYPELESS, skipped` instead
of being written.

### The origin: reading #1 was right — it is a DELETE, not a write

The file below spent its length looking for a writer, and concluded correctly
that no server-property path can produce this. That is why it stayed
unexplained: there is no writer. It is residue, which the file listed as
untested reading #1.

`delete_entity_graph_bulk` decides membership with ONE query
(`sparql_sql_space_impl.py:1591`):

    SELECT DISTINCT subject_uuid FROM rdf_quad
    WHERE predicate_uuid = <hasKGGraphURI> AND object_uuid = <entity>
      AND context_uuid = <graph>

and deletes exactly those subjects' quads. So membership is a SNAPSHOT of one
predicate at one instant, and anything whose grouping URI is missing, misdirected
or in another context at that moment is not deleted. Nothing points the other
way either: a quad with the entity as its OBJECT is never considered.

The observed residue matches. Taking one of the 19 apart —
`.../server_props/frame_create_mt/7580cd65-…`, the entity a test creates and then
deletes in a `finally`:

    the entity's own triples   GONE (type, name — the name term is still in
                               `term` with no quad attached to it)
    its frame                  SURVIVES
    its entity->frame edge     SURVIVES
    its self-link              present, and written by the issues/091 repair

so the delete removed the root and left the graph. Which of the three ways
membership can be missed applies to these particular rows is NOT established — I
did not reconstruct the sequence, and the context hypothesis is disproved
(members and self-link share one context). What the code shows is that the delete
CAN leave this residue by construction, and the data shows residue of exactly
that shape.

### Still open

* ~~**Which miss produced these 19.**~~ ANSWERED 2026-08-21 — see "Which miss"
  below. It was the never-stamped member, and the guess recorded here (members
  "not yet" stamped, i.e. a race) was the wrong one of the two.
* **Whether the delete should be membership-scoped at all.** A delete that
  defines the graph by a single mutable predicate will always be able to orphan
  the rest of it. The alternative — deleting by reachability, or refusing when
  the member count disagrees with a recount — is a design question, not a patch.

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

## Which miss produced them — settled 2026-08-21

By elimination, against the live stack.

Driving the exact sequence that made one of the 19 — create entity, create
frames, delete with `delete_entity_graph=True`, the shape from
`case_entity_server_properties.py:515` — now leaves NOTHING behind.
`create_entity_frames` sets `kGGraphURI` on the frame before writing it
(`kgentities_endpoint.py:1789`), and the three writers that did not were fixed
in `issues/091`. Kept as `tests/api/test_entity_graph_delete_residue.py`.

Planting the pre-091 shape instead — an entity and a frame joined by an edge,
the frame never stamped — reproduces the recorded residue exactly:

    entity  2 quads -> 0        the root goes
    frame   2 quads -> 2        the member outlives it
    edge    3 quads -> 3

which is what this file describes: "the entity's own triples GONE, its frame
SURVIVES, its entity->frame edge SURVIVES".

So the answer is the second candidate, not the first: the member never carried
the grouping link, rather than being written after the snapshot. The
distinction matters, because the guard added on 2026-08-20 only sees the race.

### The guard was blind to it

That check counts quads still pointing at the entity via `hasKGGraphURI`. An
unstamped member points at nothing, so it is invisible — the check stayed
silent through the entire reproduction above. A detector that cannot see the
mechanism that actually fired is the same failure as the repair script's.

The edge table is where such a member remains reachable: the entity is gone,
but an edge row naming it survives, and `(source_node_uuid, dest_node_uuid)`
and its reverse are both indexed. The delete now counts those and reports
them, guarded both ways — the reproduction must warn, and the same graph fully
stamped must delete clean and say nothing.

This should now be archaeology. If it fires, one of the issues/091 writers is
back or a new one has appeared.

### The membership-scope question — DECIDED 2026-08-21: keep it scoped

`hasKGGraphURI` is the authoritative definition of membership, not a
denormalized index of edge structure. So the delete stays as it is, an orphan
is a WRITE bug, and the two guards above are the mechanism for catching one.
Reachability is ruled out.

The measurements taken while deciding, kept because they are the argument:

* **The two definitions agree exactly on healthy data.** On `kg_load_test`,
  five entity roots, membership by grouping and membership by reachability are
  both 45. Getting that to line up needs the traversed EDGE objects counted as
  members, not just the nodes — nodes alone give 23, because an edge is a
  subject with its own quads.
* **No member belongs to two graphs.** 0 of 900 in the only space here with
  real grouping data, and confirmed as the intent: entity graphs are disjoint.
* **Cost was not the obstacle.** 0.184 ms scoped against 0.401 ms by
  reachability, both negligible beside the delete itself.

**And the hazard that settles it.** Reachability has to decide which edges
mean "contains". In `sp_kg_rel`, `Edge_hasKGRelation` outnumbers every
containment edge — 27,896 against 19,500 — and every one of them points at
another `KGEntity`. A walk that followed them would delete the neighbouring
entities' graphs along with the target. It can be fenced with a whitelist of
containment edge types, but then the delete is only as correct as that list,
and a new edge type added anywhere else in the system makes it silently wrong.
That is a worse failure than the orphan it was meant to fix: an over-delete
cannot be detected after the fact, while the orphan now reports itself.

So the residue guards stay detection-only by design, not by omission.

## Correction 2026-08-21 — the edge-based guard was withdrawn, and the origin
## claim above with it

The section "Which miss produced them — settled" is wrong and is retained
only so the mistake is legible. It concluded that the residue came from a
member which was never stamped with `hasKGGraphURI`, and added a guard that
warned when an edge still named a deleted entity.

Both rest on reading absence of `hasKGGraphURI` as a missing stamp. It is not.
The property asserts membership in a graph — the entity case being every
member, *including the entity itself*, carrying it set to the enclosing
entity. Absence means the object is **not in that entity graph**, and says
nothing about why. An object that was never a member looks exactly like a
member someone forgot to stamp, and the guard called every one of the first a
case of the second.

What that would have cost: in `sp_kg_rel` a typical entity has 0 members by
grouping and 13-16 edges naming it, so every delete there would have warned.
14,625 frames in that space and 285,348 in `wordnet_frames` carry neither
grouping property, while `kg_load_test`'s 120 carry both — the shapes are
ordinary, not damaged. And a dangling edge is not an error, so there was no
defect to report even where the walk was right.

Withdrawn in 37332fd. The reproduction it was built on — an entity, a frame
with no grouping URI, an edge between them — was most likely a frame that was
never in the entity graph, behaving correctly.

**So which miss produced the 19 is open again.** What still holds: the
quad-level check, because something pointing at the entity via
`hasKGGraphURI` after the delete IS claiming membership in a graph whose root
is gone; and `issues/091`'s finding that the entity must carry the property
for its own graph, which the domain confirms — the entity is a member of its
own graph, so the unconditional include in the delete is right.

Also worth recording, since it was the source of the error:
`hasFrameGraphURI` is a *different* scope — the frame, its slots and its
edges, with the frame-within-frame edge belonging to the child frame. Reading
one for the other is what produced this.


## Re-scanned 2026-08-22 — the 19 are stable, and nothing new has appeared

Ran the maintenance job's integrity checks directly across every registered
space on both clusters: 54 on the docker test stack, 99 on the host.

**The typeless targets are exactly the same 19, in the same four spaces:**

    kg_crud_stress_test            10
    space_client_kgentities_test    5
    space_multi_org_crud_test       3
    <one client space>              1

Unchanged since 2026-08-20. That is worth knowing on its own: whatever produced
them is not still producing them, so this is residue rather than an active
writer. It also means the detector is stable — it is not drifting, and it is
not finding new instances to chase.

Nothing is repaired. `scripts/repair_grouping_self_link.py` correctly SKIPS a
typeless target, on the principle this issue established: a repair that cannot
restore the invariant should report rather than write something that hides the
breakage.

**Graph registration is clean on both clusters** — no space holds quads in a
context the catalog does not list (`issues/116`).

**Two spaces do have missing self-links**, both ephemeral API-test leftovers
rather than anything a user has:

    vg-test  apitest_37a59eb5   1   (the KGDocument root from issues/091's scope note)
    host     apitest_46fec680   3

Neither is a fixture or a served space. They are the kind of thing the orphan
sweep is for, not this issue.