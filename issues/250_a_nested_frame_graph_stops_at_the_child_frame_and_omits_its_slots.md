# 250 — A nested frame graph returns the child frame and none of its slots

## Status: OPEN. Verified live in local data 2026-09-29. NOT introduced by
## `issues/240` — the batched query preserved the singular contract exactly,
## which is what the equivalence test pins. The scope was always this narrow.

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

## Measured, local `cardiff_kg` 2026-09-29

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

    psql -d cardiff_kg_local -At -c "..."   # the three counts above

Or by inspection: `_build_frame_graphs_query` binds `?frame` from a VALUES
clause and every arm anchors on `?frame`. No arm mentions `Edge_hasKGFrame` or
any path expression, so nothing can reach a second level.

**Related:** `issues/240` (the batching that preserved this scope, and the
misstatement corrected above), `issues/210`/`issues/226` (consumers that will
inherit the traversal, whichever is chosen)
