# `include_frame_graph` Is Accepted On `/kgqueries` And Implemented Nowhere

## Status: FIXED 2026-10-04 (`2807ad3d`, released in 0.0.44) — OPTION 1. A
## `/kgqueries` frame query with `include_frame_graph=true` returns each frame's
## graph in `frame_graph`, and the client hydrates it. The option-2 message is
## gone. See "As built" at the end. The history below is kept as it was.

**Related:** `issues/209` (the same silent-null symptom from the opposite
cause — implemented, then bypassed), `issues/182` (why a frame query on a large
space is slow enough that this was awkward to reproduce)

## The defect

    kgqueries_model.py:91    include_frame_graph: bool = Field(False,
                               "When True, include structured frame graph data
                                in frame_query results")
    kgqueries_model.py:131   frame_graph: Optional[Any] = Field(None,
                               "Structured frame graph data (when
                                include_frame_graph=True)")
    kgquery_endpoint.py:1287         frame_graph=None  # TODO: implement
                                                       # include_frame_graph

That `TODO` is the only mention of the flag in `kgquery_endpoint.py`. The
request field is never read.

It is not an internal-only field, either. `client/endpoint/kgqueries_endpoint.py:245`
puts `include_frame_graph: bool = False` in `query_frames`'s signature and sends
it, so a caller reaches this through the supported client with both models'
docstrings telling them it works.

## Reproduced

`sp_lead_dup`, `frame_type=urn:acme:kg:frame:CompanyAddressFrame`, five frames:

    include_frame_graph=True    frames=5   frame_graph set on 0 of 5   FOUND
    include_frame_graph=False   frames=5   frame_graph set on 0 of 5   FOUND

Identical. No error, no message, `status=FOUND`.

`lead_nurture_grouped` was the first attempt and the request exceeded the
client's 60 s budget — a frame query by type on a 74.5M-quad space is its own
problem (`issues/182`), and not this one.

## `/kgframes` does NOT have the `issues/209` hole — this is what that question found

`issues/209` asked whether the frame listing loses `include_frame_graph` the way
the entity query lost `include_entity_graph`. It does not, and the reason is
worth recording so nobody re-checks it:

  * On `/kgframes` the flag is implemented, at `_get_frame_by_uri`
    (`kgframes_endpoint.py:634`) and `_get_frames_by_uris` (`:639`), with the
    SPARQL built at `:2170`.
  * Both are URI LOOKUPS. The flag is not a parameter of the paged LISTING at
    all, so the listing's two fast paths — `fast_typed_subject_page` and
    `fast_frame_prop_page` (`:900`, `:940`) — cannot bypass a flag that never
    reaches them.

So: two routes, two different states. `/kgframes` implements it where it offers
it. `/kgqueries` offers it and implements it nowhere.

## The fix, and it is a choice rather than a bug fix

1. **Implement it.** `_get_frames_by_uris` already produces frame graphs for a
   list of frame URIs, and the frame_query path has exactly that list at
   `:1281`. This mirrors what `issues/209` just did on the entity side, where
   hydration after the page cost 3.5-5.1 s for 25 entities — so it should be
   built knowing that number, and probably alongside `issues/208`, which is the
   argument that a caller naming what it wants should not pay a whole-graph
   fan-out for it.
2. **Say it is unsupported.** Return the `frame_query` with a `message` naming
   the flag as not implemented, HTTP 200, per the house rule that domain
   outcomes are 200 with the outcome in the body. Honest in one line, and
   immediately actionable by a caller who is currently reading nulls.
3. **Remove it** from the request model and the client. An API break for a field
   that has never done anything, and the only option that cannot mislead anyone
   later.

Option 2 now and option 1 with `issues/208` is what I would do. Doing nothing is
the current state, and the current state is a documented parameter that lies.

**Option 2 SHIPPED 2026-09-18.** A request that sets the flag comes back with a
`message` naming it, pointing at `/kgframes` (where it IS implemented, on the
URI lookups) and at `slot_projection` / `property_projection` for naming the
columns wanted. `status` is unchanged and `success` stays true, because the
query succeeded — only the flag was ignored.

Three API cells pin it, and the pairing is the point: a cell asserting only
that the message APPEARS would pass against an endpoint that returns it
unconditionally, which is noise on every response that never asked. The control
— a request with the flag FALSE gets no message — is what makes the first cell
mean anything, and it earned its place immediately: it caught a 500. `message`
is a non-Optional `str` on `ResultStatus`, so the `None` this first shipped
with failed validation, and the cell written to stop an unconditional message
found an unconditional crash instead.

## Not yet established

- Whether anything actually sets it. `grep` finds no caller in this repo outside
  the client's own signature; the portal is not in this tree.
- What a `frame_graph` should CONTAIN if implemented — the frame plus its slots,
  or the frame's whole subtree including child frames. `/kgframes` answers this
  one way (`_build_get_frame_query` at `:2170`); nothing says the query surface
  should answer it the same way.

## Reproduce

    grep -n "include_frame_graph" vitalgraph/endpoint/kgquery_endpoint.py

One hit: the `TODO` at line 1287.

## RETRACTION 2026-09-25 — "`/kgframes` implements it where it offers it" is FALSE for the `uris=` form

The section above headed "`/kgframes` does NOT have the `issues/209` hole" ends:

> So: two routes, two different states. `/kgframes` implements it where it
> offers it. `/kgqueries` offers it and implements it nowhere.

The first of those sentences is wrong. `_get_frames_by_uris`
(`kgframes_endpoint.py:1349`) takes `include_frame_graph` in its signature and
the flag appears NOWHERE in the body — so `GET /kgframes?uris=a,b,c&include_frame_graph=true`
returns the frames without their graphs, HTTP 200, `status=FOUND`, no message.
The single-URI form at `:1097`/`:1113` does implement it. Filed as `issues/240`.

**How this file got it wrong is the reusable part.** The check that produced that
section read the two call sites at `:634`/`:639` and established that both are
URI LOOKUPS rather than paged listings — which is true, and is the right answer
to the question `issues/209` had asked (can a fast path bypass the flag?). It is
not the same question as "is the flag honoured once the lookup runs", and only
one of the two functions was read through to its body. A dispatch table is
evidence about which code runs, not about what that code does.

The same gap is in the test suite: `tests/api/test_kgframes_api.py:503` is the
only `/kgframes` cell for this flag and its docstring names the form — `?uri=`.
The `uris=` form has no cell with the flag set. The control-pair discipline this
file used for option 2 on `/kgqueries` would have caught it on either form.

## This changes OPTION 1, which recommended building on that function

Option 1 above says:

> `_get_frames_by_uris` already produces frame graphs for a list of frame URIs,
> and the frame_query path has exactly that list at `:1281`.

It does not produce frame graphs. Wiring `frame_query` into it as written ships a
SECOND no-op whose symptom — `frame_graph` null on every result — is identical to
the one option 2 exists to explain, so it would read as the fix not having
deployed. `issues/226` repeats this claim from here and is corrected there too.

Option 1 is still the right end state; its first step is now `issues/240`.

## And option 1 is CHEAPER than this file assumed — measured 2026-09-25

This file says option 1 "should be built knowing that number", the number being
`issues/209`'s 3.5-5.1 s for 25 entities. Measured on `nurture_typed` (2,995,193
slot-sort rows, 509,203 frames), for a scattered 25-frame page:

| for one 25-frame page | buffers | warm exec ms (min/med/max, 5 reps) |
|---|---:|---|
| 2 named columns from `entity_slot_sort`, frame-keyed | **31** | 0.33 / 1.03 / 1.61 |
| the same 2 values walked from the quads | 2,295 | 8.96 / 13.16 / 22.55 |
| whole frame graph, term-resolved — THIS FILE'S OPTION 1 | 11,924 | 53.6 / 85.7 / 341.8 |

**2,567 quads, not ~18,000.** The frame graph is ~7x less data than the entity
graph, and the timings track that ratio — so option 1 is roughly 12k buffers, not
a multi-second hydration. Buffers were byte-identical across three repetitions;
the ms spread is contention (`nurture_typed` is not maintenance-excluded).

Two corrections to how `issues/209`'s figure should be read, both from the code
rather than from the number:

  * **`_fetch_entity_graphs` is batched and cache-fronted**
    (`kgquery_endpoint.py:1834`). 3.5-5.1 s is ONE query resolving ~18,000 quads,
    not N round trips. Term resolution is where it goes — adding the three term
    joins to the frame-graph query took 2,122 buffers to 11,924, 5.6x, for the
    same quads.
  * **`_get_frames_by_uris` is per-URI** (`get_object` per frame under
    `bounded_gather`), so implementing option 1 through it would inherit 25 round
    trips instead of the one batched query the entity side already uses. Fixing
    `issues/240` by honouring the flag per frame is correct but is NOT option 1;
    batching is the separate half.

So the decision this file deferred is now priceable. Option 1 costs ~385x a
named-column projection over the same page, which is why it should be offered
rather than defaulted — the same conclusion `issues/226` reached, on a number an
order of magnitude smaller than the one it feared. What it does NOT settle is
this file's own open question of what a `frame_graph` should CONTAIN; the 2,567
quads above are `?s haley:hasFrameGraphURI <frame>` plus the frame, i.e. the
shape `_build_get_frame_query` already answers, not a decision that the query
surface should answer it the same way.

## As built, 2026-10-04 (`2807ad3d`, 0.0.44) — option 1

- **Server** (`kgquery_endpoint._execute_frame_query_case`): when the flag is
  set, ONE batched fetch for the page through
  `KGFrameGraphProcessor.get_frame_graphs` — the query `issues/240` built for
  `/kgframes?uris=` so this could reuse it — not one per frame. Offered, never
  defaulted, on 210's price of ~12k buffers for a 25-frame page.
- **What a `frame_graph` contains** (this file's open question): the frame and
  every subject grouped with it by `hasFrameGraphURI` — its slots and slot
  edges. Not child frames: since `issues/257` a child frame is its own frame
  graph, and a link to it carries no grouping, so this is the same shallow
  answer `/kgframes` gives and the frame update/upsert replace.
- **Shape:** JSON quads (`{s,p,o,g}`), the shape `entity_graphs` uses, so the
  client hydrates both the same way. `FrameQueryResult.frame_graph` is typed
  `List[Dict]` (was `Any`), with a client-only `frame_graph_objects` holding the
  hydrated GraphObjects.
- **A failed fetch is SAID:** the frames are correct, so the query still
  succeeds, `frame_graph` is null, and `message` names the failure — never the
  silent null this issue is about.
- The option-2 message is removed; a request that did not ask still gets no
  message and no graph.

**Tests.** `tests/api/test_kgqueries_api.py::TestIncludeFrameGraph` replaces the
three option-2 cells, keeping their pairing: each frame carries its OWN graph
(frame and slot, not the other frame's slot); not asking returns no graph and no
message; the flag does not change which frames come back. Against the previous
handler the first FAILS (the not-implemented message) and the two guards pass.

