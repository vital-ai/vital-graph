# 240 — `_get_frames_by_uris` accepts `include_frame_graph` and drops it

## Status: OPEN — found 2026-09-25 by reading the code `issues/210` recommends
## building on. The flag is in the signature and NOWHERE in the body, so the
## multi-URI lookup returns frames without their graphs, HTTP 200, no message.
## The single-URI lookup on the same endpoint DOES implement it.

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
