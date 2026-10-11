# 267 — A dead frame-graph delete half-cascades into child frames

## Status: OPEN, filed 2026-10-11. **Not reachable today** — the whole chain is
## dead, and that is established below rather than assumed. This is a removal,
## not a repair: the behaviour it implements was forbidden by the 2026-10-03
## frame-graph rule, and the live path already does the right thing.

## What it does

`_build_frame_graph_delete_query` (`vitalgraph/kg_impl/kgframe_graph_impl.py:395`)
builds a SPARQL DELETE whose template removes five things:

    <frame> ?framePred ?frameObj          the frame
    ?slot ?slotPred ?slotObj              its slots
    ?edge ?edgePred ?edgeObj              its slot edges
    ?childFrame ?childFramePred ?childFrameObj      THE CHILD FRAME
    ?childEdge ?childEdgePred ?childEdgeObj         the parent -> child edge

The WHERE binds `?childFrame` through an `OPTIONAL` on
`?childEdge rdf:type Edge_hasKGFrame`. **Nothing in it binds the child's own
slots or slot edges.**

So deleting a parent would delete the child frame's triples and leave the
child's slots behind — each still carrying `hasFrameGraphURI` naming a frame
that no longer exists, and each still the destination of an `Edge_hasKGSlot`
whose source no longer exists. Orphans, silently, with the operation reporting
success (`delete_frame_graph` returns `True` on any non-exception).

**It is wrong twice over.** Beyond the orphaning, touching the child at all is
forbidden: `hasFrameGraphURI` IS a frame graph and a parent -> child
`Edge_hasKGFrame` is grouped with nothing, because structural links are in no
frame's graph (decided 2026-10-03, `issues/256`, stated in `issues/257`). A
frame-graph delete should stop at the frame's own members. This one reaches one
level past them and then stops halfway through that level — the worst of both
scopes.

## Why it cannot fire

Traced, not assumed:

    _build_frame_graph_delete_query   <- delete_frame_graph (`:161`)
    delete_frame_graph                <- kgframes_endpoint._delete_frame_graph (`:2855`)
    kgframes_endpoint._delete_frame_graph   <- NOTHING

`grep -rn "_delete_frame_graph\b"` over `vitalgraph/` returns the definition and
no caller. The live `DELETE /kgframes` route (`kgframes_endpoint.py:478`) goes a
different way entirely:

    route -> _delete_frames_by_uris(recursive=...)
          -> kg_impl.frame_delete.delete_frames
          -> backend_adapter.delete_frame_subtrees   (`kg_backend_utils.py:2250`)

That path takes an explicit `recursive` flag, defaults it to FALSE, and refuses a
frame that has children unless the caller opts in — the `recursive` parameter is
threaded through rather than accepted and dropped, which was checked because
`issues/240` was exactly that defect. `issues/212` covers orphaned children on
the live path and records that it cannot recur.

## Why file it rather than just delete it

Same reasoning as `issues/240`'s dead helpers, which were removed once the
record existed: a wrong implementation sitting beside the right one is a trap,
and this one is worse than a dead grouping helper because the name
`delete_frame_graph` is the obvious thing to reach for. The difference is that
this is a DELETE path, so removing it deserves its own change with its own
diff to read, rather than riding along in a documentation commit.

## The fix

**Remove all three — the query builder, `delete_frame_graph`, and
`kgframes_endpoint._delete_frame_graph`.** Nothing calls them, the live path is
better in every respect, and there is no behaviour to preserve.

Check while removing, since they live in the same module and may share it:

  * `_convert_results_to_vitalsigns` (`:453`) is used by the READ path too —
    leave it.
  * `test_scripts/vitalgraph_client_test/kgframes/case_frame_graphs.py:104`
    defines `test_delete_frame_graph`, which exercises the client's delete
    against the live route, NOT this code. It should keep passing untouched; if
    it breaks, the dead-chain conclusion above is wrong and this issue needs
    reopening rather than the test adjusting.

## It was never live — added dead in the same commit as `issues/240`'s helpers

`git log -S "_delete_frame_graph(" --all` returns exactly ONE commit:
**`d5d3d636`** (2026-01-26, "sync"). That is the same 288-line bulk insertion
that added `group_objects_by_frame` and `group_objects_by_entity` — the dead,
wrong grouping helpers removed under `issues/240`. No commit since has touched
it, and no caller has ever existed.

So the orphaning has never run, and **no production data carries its damage.**
That closes the only question that would have made this urgent, and it makes the
`issues/240` parallel exact rather than merely similar: one import dropped in
several wrong implementations of things the codebase already did correctly, and
they have been surfacing one at a time ever since.

## Not established

  * **Whether orphaned slots exist from some OTHER cause.** Not checked, and
    worth a look independently of this issue: a slot whose `hasFrameGraphURI`
    names a non-existent subject is a useful integrity check whatever produced
    it. `issues/212` is the known live-path source and is recorded as closed.

## Reproduce

    grep -rn "_delete_frame_graph\b" --include=*.py vitalgraph/

One definition, no callers. And in `_build_frame_graph_delete_query`, the DELETE
template names `?childFrame` while the WHERE clause has no block binding that
child's slots.

**Related:** `issues/257` (the rule that makes the child-frame reach wrong),
`issues/256` (where it was decided), `issues/250` (the READ path's version of
the same one-level confusion, resolved), `issues/212` (orphaned children on the
live delete path), `issues/240` (the dead-code precedent)
