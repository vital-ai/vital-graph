# 250 — A nested frame graph returns the child frame and none of its slots

## Status: RESOLVED. The fix shipped 2026-09-29 (both connection arms typed to
## `Edge_hasKGSlot`), and the question this issue left open was DECIDED AGAINST
## four days later. Nothing is outstanding.
##
## NOT introduced by `issues/240` — the batched query preserved the singular
## contract exactly, which is what the equivalence test pins.

## The open question was settled on 2026-10-03, and the answer is "shallow"

This issue shipped option 3 and left options 1 and 2 — traverse
`Edge_hasKGFrame` transitively, or one extra level — as a live choice, calling
the shallow result "honest but not complete".

**That framing is withdrawn.** `issues/256` decided, and `issues/257` states, the
rule that settles it:

> `hasFrameGraphURI` IS the definition of a frame graph. [...] an
> `Edge_hasKGFrame` (parent -> child) and an `Edge_hasEntityKGFrame` have NONE:
> structural links are in no frame's graph (decided 2026-10-03).
>
> Nothing a frame does not own carries its grouping. That is what keeps
> `update` shallow and makes `replace` the only subtree operation.

So a frame graph is shallow BY DEFINITION, and a child frame's slots are not
missing from the parent's graph — they were never in it. The typed arms are not
an approximation of a traversal still owed; **they are the rule**, arrived at
independently and four days early. A transitive read would now CONTRADICT the
data model. Options 1 and 2 are withdrawn, not deferred.

What survives from the original report is the half-applied part, and that is
exactly what was fixed: the untyped arms grouped a structural `Edge_hasKGFrame`
and its destination into the parent's graph, which the rule says belongs to no
frame's graph at all.

**If a consumer needs to render a hierarchy**, that is a subtree READ operation
and there is none — `replace` and recursive delete are the only subtree
operations today. That is a feature request against the rule, not this defect,
and it should be filed on its own evidence of a caller that needs it.

## One dead implementation still does the wrong thing

`delete_frame_graph` / `_build_frame_graph_delete_query`
(`kgframe_graph_impl.py:161` and `:395`) deletes `?childFrame`'s triples and the
parent -> child edge while binding NOTHING for the child's own slots — a
half-cascade that would leave them pointing at a deleted frame, and a grouping
the 2026-10-03 rule forbids outright.

**It is dead.** Its only caller is `kgframes_endpoint._delete_frame_graph`
(`:2855`), which has no callers itself; the live `DELETE /kgframes` route goes
through `frame_delete.delete_frames` -> `delete_frame_subtrees`, which takes an
explicit `recursive` flag and refuses a frame with children when it is false.
`issues/212` covers the orphaning on the live path and records it cannot recur.

Left as-is rather than removed, because deletion of a delete path deserves its
own change and its own issue — this is the `issues/240` dead-helper pattern
(a wrong implementation sitting beside the right one), noted here so whoever
removes it has the reason to hand.

## What was done

Both builders in `vitalgraph/kg_impl/kgframe_graph_impl.py`, changed together
because the equivalence test fails if only one moves:

    { ?subject vital:hasEdgeSource ?frame .
      ?subject vital:vitaltype haley:Edge_hasKGSlot . }

**Nothing legitimate is lost, and that is measured rather than assumed.** Edges
whose source resolves to a `KGFrame`, whole corpus:

    Edge_hasKGSlot     1,437,778
    Edge_hasKGFrame        5,443

Two types, no third. So the filter drops exactly the child-frame edges. On the
sampled parent (`...frame:contacts:0`) that is 1 slot edge kept and 1 child-frame
edge dropped, along with the stub it pointed at.

**The filter is on `vital:vitaltype`, not `rdf:type`** — a convention, and
pinned as one. `vitaltype` is the single-valued type URI the codebase counts on
and the one `kg_query_builder.py:976` already uses to type a slot edge.

> **Corrected 2026-10-11.** This said the two were not interchangeable and that
> the wrong predicate "matches nothing and returns every connection frame
> slotless". **False, and measured:** every edge carries both, in identical
> numbers — `rdf:type Edge_hasKGSlot` 1,356,591 against `vitaltype` 1,356,591,
> and 5,741 each for `Edge_hasKGFrame`. `rdf:type` would have worked;
> `delete_frame_graph` in this same module types its edges that way and is
> correct. The choice stands on consistency alone, which is reason enough, and
> the invented silent-failure risk is withdrawn — left standing it would have
> had the next reader "fixing" working queries.

**The client was deliberately NOT typed to match.** `group_objects_by_frame_graph`
stays tolerant: the server is the only producer, so a child-frame edge no longer
reaches it, and filtering by class name on a deserialised object risks dropping
every slot if the name is wrong. Recorded in its docstring.

**Tests:** 4 added to `test_frame_graphs_batched_equivalence.py` — both arms
typed, in BOTH builders (parametrised, since the equivalence test only proves
they agree, not that either is right); `vitaltype` not `rdf:type`; and the edge
object itself still returned, because the client identifies a slot BY its edge
and dropping that arm would render nothing.

## Original report follows.

## The shape

A frame reaches its own slots two ways, and `_build_frame_graph_query` covers
both (`issues/240`):

    attribute    the slot carries `hasFrameGraphURI` naming its frame
    connection   an edge runs FROM the frame (source) TO the slot (destination)

**A child frame carries its OWN frame graph URI.** So the attribute arm, which
matches `?subject haley:hasFrameGraphURI ?frame`, collects the slots of THIS
frame and stops. A child's slots name the CHILD, and are invisible to a query
anchored on the parent.

Child frames are linked by `Edge_hasKGFrame`, source = parent, destination =
child — confirmed by `graph_validation.py:_find_child_frames`, the one place in
the tree that traverses them at all.

**And the connection arms are not typed.** They match ANY edge out of the frame,
not just `Edge_hasKGSlot`. So `Edge_hasKGFrame` matches too, and the child frame
object IS pulled into the parent's graph — as a bare edge destination, with none
of its slots behind it.

That is the failure that matters. The contract says "does NOT include child
frames"; the query half-includes them. A child frame arrives with zero slots,
and **a frame with zero slots is indistinguishable from a frame whose slots were
not fetched** — the exact ambiguity `issues/240` was written about, where the UI
reported "No slots found for this frame" for a frame that had two.

## Measured, local `the_kg_space` 2026-09-29

    Edge_hasKGFrame total                                  5,741
      ... whose source resolves to a KGFrame                5,443
    grandchild links (a child that is itself a parent)         13

So nesting is not an edge case: 5,443 frame-to-frame links. Depth beyond two is
real but rare, which is why a fixed two-hop join would cover almost everything
and still be wrong — and why the singular docstring's "arbitrary depth" warning
is not hypothetical.

Objects naming each frame in `hasFrameGraphURI`, three sampled parent/child
pairs:

    parent ...frame:contacts:0          3      child ...:person:0        17
    parent ...frame:pg:0                1      child ...:personal_info    5
    parent ...frame:pg:0                1      child ...:financial        3

The child holds most of the content. Fetching the first parent's frame graph
returns 3 attribute-linked objects plus a child frame stub, and omits 17.

## Where it is, and where it is not

**Both the singular and the batched server queries**, identically —
`_build_frame_graph_query` and `_build_frame_graphs_query` in
`vitalgraph/kg_impl/kgframe_graph_impl.py`. The singular one SAYS so, in
`get_frame_graph`'s own docstring:

    Note: Does NOT include child frames (which can have arbitrary depth).

So this is deliberate, documented, pre-existing scope — not a regression. The
`issues/240` batching reproduced it arm-for-arm on purpose, and
`test_frame_graphs_batched_equivalence.py` would fail if it had not.

**The client grouping too**, and it could not be otherwise:
`group_objects_by_frame_graph` mirrors the same four linkages, so it can only
partition what the server sent. Adding recursion there alone would group objects
that are not in the response.

**Not the entity side.** `group_objects_by_entity_graph` keys on `kGGraphURI`,
which names the entity graph a member belongs to, so nesting does not arise the
same way. This asymmetry was stated backwards in the `issues/240` write-up — see
the correction below.

## Correcting a claim in `issues/240`

That issue's dead-helper section says frames have "no such uniform
back-pointer, which is the whole reason that side reconstructs linkage from
edges." **Wrong.** Frames DO have `hasFrameGraphURI`; it is the second of the
four arms. The reason the frame side also needs edges is that a space may use
EITHER the attribute or the connection form and this cannot pick a side — the
reason the singular docstring gives. The back-pointer exists; it just does not
span a parent/child boundary, which is this issue.

## The fix, and it is a choice

1. **Traverse `Edge_hasKGFrame` transitively** — a SPARQL property path
   (`vital:hasEdgeSource`/`hasEdgeDestination` chained, or a recursive CTE) that
   collects descendant frames first, then applies the existing four arms to the
   whole set. Correct at any depth. Needs a **cycle guard**: nothing in the data
   model forbids a frame graph cycle and a property path would not terminate
   politely without one. Cost is unmeasured and must be, on a 25-URI page.
2. **One extra level**, covering 5,443 of 5,456 observed links, and still wrong
   for the 13. Cheap and bounded, but it makes the contract "two levels", which
   is a strange thing to document and an easy thing to forget.
3. **Honour the stated contract and drop the child frame stub** — if child
   frames are excluded, exclude them, rather than returning one with no slots.
   This is the smallest change, removes the misleading half-result, and does NOT
   require deciding the traversal question. It makes the current behaviour
   honest instead of making it complete.

3 is not an alternative to 1; it is what to do if 1 is not done now. The stub is
the part actively misleading a caller today.

## Not established

  * **Whether any live caller requests a frame that HAS children.** The counts
    prove nested frames exist, not that the `uris=` or single-URI frame-graph
    endpoints are being called on parents. Not traced.
  * **What the UI does with a zero-slot child frame today.** The "No slots
    found" string is cited from `issues/240`'s account of the connection-linkage
    bug, not re-observed for this case.
  * **Whether `hasFrameGraphURI` ever names a ROOT** rather than the immediate
    frame. If some writer populated it with the root, those graphs would already
    be whole and the picture would be mixed. The three pairs sampled all name
    the immediate frame; this was not checked across the corpus.
  * **Cost of the transitive form.** Not measured, and `issues/238` is a
    standing reminder that a plausible-looking traversal can be an IO disaster.

## Reproduce

    psql -d the_kg_space_local -At -c "..."   # the three counts above

Or by inspection: `_build_frame_graphs_query` binds `?frame` from a VALUES
clause and every arm anchors on `?frame`. No arm mentions `Edge_hasKGFrame` or
any path expression, so nothing can reach a second level.

**Related:** `issues/240` (the batching that preserved this scope, and the
misstatement corrected above), `issues/210`/`issues/226` (consumers that will
inherit the traversal, whichever is chosen)
