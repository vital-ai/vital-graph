# 240 — `_get_frames_by_uris` accepts `include_frame_graph` and drops it

## Status: FIXED 2026-09-29 — implemented AND batched. The `uris=` form returns
## frame graphs in ONE query, and that query is reusable by `issues/210`/`226`.
## Two dead, wrong grouping helpers found in the same module were removed with it.

## What was done, in three steps and two corrections

**The defect.** `include_frame_graph` was in the signature of
`_get_frames_by_uris` and NOWHERE in the body, so the multi-URI form returned
frames without their graphs — HTTP 200, `status=FOUND`, nothing to say a
parameter had been ignored. The single-URI sibling implemented it all along.

**First attempt: option 3** — make it SAY it is unimplemented, on this issue's
own recommendation that the batched form should be written once with
`issues/210`/`226`. Wrong as a response to "fix this": it documented the gap
instead of closing it, and `issues/226` is a consumer waiting on the capability.

**Second: option 1**, per-URI, mirroring the sibling. Correct, and 25 round
trips for a 25-URI request.

**Shipped: option 2**, batched. `KGFrameGraphProcessor.get_frame_graphs` binds
`?frame` from a `VALUES` clause instead of interpolating a literal, projects
`?frame` alongside `?subject`, and fetches objects ONCE over the union of
subjects — a subject reachable from two frames is one fetch, not two. One SELECT
per request, matching `_fetch_entity_graphs` on the entity side.

**Added ALONGSIDE `get_frame_graph`, not replacing it.** The single-URI path is
in production with its own tests; it keeps working unchanged.

## The risk this carried, and the test that covers it

The four UNION arms are the whole risk. The singular query's docstring records
why: only the ATTRIBUTE linkage was implemented once, so a CONNECTION frame
returned the frame alone, `get_frame_graph` read one object as "frame only" and
returned None, and the UI reported "No slots found for this frame" for a frame
with two. **A pattern anchored on an absent predicate matches nothing rather
than failing** — a dropped arm is silent.

`tests/unit/test_frame_graphs_batched_equivalence.py` uses the SINGULAR builder
as the oracle: arm-for-arm counts of `hasFrameGraphURI`, `hasEdgeSource` and
`hasEdgeDestination` must match, and no frame URI may be interpolated into a
pattern (which would make the VALUES clause decorative). Mutation-checked —
removing one arm fails it with that message.

**Tests:** 10 cases across two files. `tests/unit/test_frames_by_uris_does_not_drop_the_flag.py`
carries the control pair — flag FALSE must cause no graph query at all, since a
function that always fetched them would pass the positive assertion while
ignoring the flag just as completely. 85 frame integration tests pass unchanged.

## Two dead helpers found alongside it, both wrong the same way — REMOVED

Splitting the merged response turned up `group_objects_by_frame` and
`group_objects_by_entity` in `vitalgraph/client/response/response_builder.py`.
Both did this:

    for obj in objects:
        if hasattr(obj, 'URI'):
            groups.setdefault(obj.URI, []).append(obj)

**That is not grouping by frame or by entity.** Keying on the object's OWN URI
produces one group per object — N groups of one, for any input. A caller asking
for "the objects of frame X" would have got back the single object whose URI is
X, silently, and `group_objects_by_entity` also carried an unused `VITAL_Node`
import.

**Neither has ever had a caller.** `git log -S` puts both in `d5d3d636`
(2026-01-26, "sync") as part of one 288-line insertion into the module; nothing
in the tree has ever called them, and they are exported from no `__init__.py`.
They were added dead and stayed dead, which is exactly why being wrong cost
nothing and why nothing surfaced it. Had either been wired up during this issue
— and `group_objects_by_frame` is one autocomplete away from the
`group_objects_by_frame_graph` written for it — it would have produced N
single-object graphs and looked plausible doing it.

### The fix, and it differs per helper because their replacements differ

**`group_objects_by_frame` — deleted.** `group_objects_by_frame_graph` is the
correct implementation of that name's intent, and frames need the four UNION
linkages above, not an attribute lookup. Keeping a broken near-homonym beside it
is a trap.

**`group_objects_by_entity` — replaced by `group_objects_by_entity_graph`**,
which is NOT newly invented: it is the rule `kgentities_endpoint` had already
open-coded, correctly, in both of its `include_entity_graph` branches (formerly
`:203-208` and `:505-510`, verbatim identical):

    graph_uri = str(obj.kGGraphURI) if obj.kGGraphURI else None
    if graph_uri:
        groups.setdefault(graph_uri, []).append(obj)

So the entity side never had this bug in live code — it had the right rule twice
and a wrong helper nobody called. Both call sites now go through the helper, so
the duplicate cannot drift.

**Entities do not need the requested URIs; frames do.** Every object in an
entity graph carries `kGGraphURI` naming its graph, so the key is on the data.
The frame side must also reconstruct linkage from edges, because a space may use
EITHER the attribute or the connection form and the query cannot pick a side.

> **Corrected 2026-09-29.** This paragraph originally said frames have "no such
> uniform back-pointer". That is wrong — frames DO carry `hasFrameGraphURI`, and
> it is the second of the four arms. What it does not do is span a parent/child
> frame boundary: a child frame carries its OWN frame graph URI, so none of this
> reaches a nested frame's slots. Filed as `issues/250`, which also records that
> the untyped connection arms pull the child frame in WITHOUT its slots.

**An object with no `kGGraphURI` is dropped, not collected under `None`** — a
`None` key becomes `build_entity_graph(None, objs)`, a graph that does not exist
sitting in the response list beside real ones. And the value is `str()`-ed:
`kGGraphURI` is a property object, so grouping on the raw value would key by
identity and split one graph into many. Both are pinned.

This follows `issues/241`'s precedent — dead enum members for a retired backend
were removed rather than repaired — for the same reason: code with no caller has
no behaviour to preserve, so "fix it" and "delete it" differ only in what the
next reader has to trust.

**Tests:** `tests/unit/test_client_partitions_entity_graphs.py`, 6 cases. Two
are textual — both branches route through the helper, and neither old name may
return — because the rest needs a live server and the property is "there is one
copy of this rule".

## Still open

`issues/210`/`issues/226` can now call `get_frame_graphs` rather than writing
their own; that is the reuse this was factored for, and it has not been done.

**Related:** `issues/210` (`include_frame_graph` on `/kgqueries` — which states
this surface is clean, and is wrong for the `uris=` form), `issues/209` (the same
silent-null shape: implemented, then bypassed), `issues/226` (the consumer that
wants this capability and repeats 210's claim)

## The defect

    kgframes_endpoint.py:577    include_frame_graph: bool = Query(False,
                                  "If True, include complete frame graph with slots")
    kgframes_endpoint.py:641    return await self._get_frames_by_uris(
                                  space_id, graph_id, uris, include_frame_graph, current_user)
    kgframes_endpoint.py:1349   async def _get_frames_by_uris(self, ..., 
                                  include_frame_graph: bool = False, ...)

Line 1349 is the ONLY occurrence of `include_frame_graph` in that function. The
body fetches `backend_adapter.get_object(...)` per URI under `bounded_gather` and
returns; nothing consults the flag and `_get_frame_graph` is never called.

The single-URI sibling does implement it, which is what makes this a drop rather
than an unbuilt feature:

    kgframes_endpoint.py:1097   sparql_query = self._build_get_frame_query(
                                  graph_id, uri, include_frame_graph)
    kgframes_endpoint.py:1113   if include_frame_graph and frames:
                                    frame_graph = await self._get_frame_graph(...)

So one endpoint, two lookup forms, and the flag works on exactly one of them.
`?uri=` returns the frame plus its graph; `?uris=` returns the frames alone, with
`status=FOUND` and nothing to say a parameter was ignored.

**Three surfaces take this flag and this is the only one that drops it**, which is
what makes "unbuilt" the wrong reading:

| surface | takes it | honours it |
|---|---|---|
| `kgframes_endpoint._get_frame_by_uri` (`:1078`) | yes | **yes** — `:1097`, `:1113` |
| `kgframes_endpoint._get_frames_by_uris` (`:1349`) | yes | **NO** |
| `kgentities_endpoint._get_individual_frame` (`:1520`) | yes | yes — forwards to `sparql_processor.get_individual_frame` |

The third is listed because it shows the flag is plumbed through a DIFFERENT
endpoint as well, so the capability is not missing from the codebase; one
function of three simply does not read its own parameter. (Whether the processor
behind the third honours it downstream was not followed further — it is not this
defect.)

## It is untested, which is why it survived

`grep -rn include_frame_graph tests/` finds three files.
`tests/api/test_kgframes_api.py:503` is the only `/kgframes` cell and its
docstring names the form it covers:

    """GET /kgframes?uri=...&include_frame_graph=true — full frame graph."""

The `uris=` form has no cell with the flag set. A control pair of the kind
`issues/210` used — flag true gets a graph, flag false does not — would have
caught this on either form.

## This corrects a claim in `issues/210` and `issues/226`

`210` has a section headed "`/kgframes` does NOT have the `issues/209` hole —
this is what that question found", which concludes:

> So: two routes, two different states. `/kgframes` implements it where it
> offers it. `/kgqueries` offers it and implements it nowhere.

The first sentence is false for the `uris=` form. `210` reached it by reading the
two call sites at `:634`/`:639` and observing both are URI lookups rather than
paged listings — which is true, and is a statement about which code path runs,
not about whether the flag is honoured once there. Only one of the two was read
through to its body.

**The practical consequence is larger than the wrong sentence.** Both `210`
(option 1) and `226` recommend implementing the capability by reusing this
function:

> `_get_frames_by_uris` already produces frame graphs for a list of frame URIs,
> and the frame_query path has exactly that list at `:1281`.  — `issues/210`

> **KGQuery already holds the input.** `_get_frames_by_uris` takes a list of
> frame URIs  — `issues/226`

It does not produce frame graphs. Wiring `frame_query` into it as written ships
a second no-op, and the symptom — `frame_graph` null on every result — is
identical to the one `210` option 2 exists to explain, so it would read as the
fix not having deployed.

## What it would cost to implement, measured

See the measurement appended to `issues/226` (2026-09-25). For a 25-frame page
the whole frame graph is **2,567 quads / 11,924 buffers / 53.6-341.8 ms** on a
509,203-frame space, term-resolved. Two things follow for this function:

  * That figure is for ONE batched query. This function is per-URI — one
    `get_object` per frame under `bounded_gather` — so a naive repair inherits 25
    round trips rather than the one query the entity side already uses
    (`_fetch_entity_graphs`, `kgquery_endpoint.py:1834`, batched over a `VALUES`
    clause and cache-fronted). Repairing the flag and batching the fetch are
    separate changes and only the first is this defect.
  * The whole-graph fan-out is 385x a named-column projection over the same page.
    A caller who wants two slots should not reach for this at all; that is
    `issues/208`'s argument and `issues/226`'s open request.

## The fix, and it is a choice like `210`'s

1. **Honour it.** Call `_get_frame_graph` per frame after the lookup, mirroring
   `:1113`. Cheapest to write, inherits the per-URI shape, and carries the
   de-duplication trap `:1113` already documents — the frame appears in BOTH the
   lookup result and its own graph, so its quads emit twice unless removed.
2. **Honour it batched.** One query over the page's frames, the way
   `_fetch_entity_graphs` does it. More work, and the right end state, but it is
   the same change `210` option 1 needs — so do it once, there, rather than
   twice.
3. **Say it is unsupported on this form**, HTTP 200 with the outcome in the body,
   exactly as `210` option 2 did for `/kgqueries`. One line, immediately
   actionable, and it stops the flag lying while option 2 is decided.

Option 3 now and option 2 with `issues/210`/`issues/226` is the same sequencing
`210` chose for the neighbouring surface, and for the same reason: a documented
parameter that silently does nothing is worse than one that says so.

## Not established

  * **Whether any caller sets it on the `uris=` form.** No live caller in this
    tree does. `issues/210` records the official client's `query_frames` sending
    the flag, but that is the `/kgqueries` path and the client package is not in
    this tree, so that citation was not re-verified here; the portal is not in
    this tree either. The only in-tree code that sets the flag true is under
    `test_scripts/kg_endpoint_fuseki/`, which targets a backend NO LONGER IN USE
    — so it is not evidence about live callers in either direction and is not
    cited as such.
  * **How long it has been this way.** Not traced through history. The single-URI
    path's implementation and this signature may never have been written
    together.
  * **Whether `_get_frame_graph`'s "1 object means None" rule is right here.**
    `:3580` returns None when the graph holds only the frame itself, so a frame
    with no slots is indistinguishable from an ignored flag even once this is
    fixed. That is a second, smaller instance of the same ambiguity and is not
    addressed by honouring the flag.

## Reproduce

    grep -n "include_frame_graph" vitalgraph/endpoint/kgframes_endpoint.py

Ten hits, and the distribution is the defect. The query parameter at `:577`
dispatches to BOTH lookups — `:636` single, `:641` multi. The single-URI branch
then uses it four more times (`:1078` signature, `:1081` log, `:1097` query
build, `:1113` the graph fetch) and `_build_get_frame_query` acts on it
(`:2174`/`:2176`). The multi-URI branch uses it ONCE, at the signature (`:1349`),
and `_get_frames_by_uris` runs to `:1386` — so there is not one occurrence in the
36 lines of its body.
