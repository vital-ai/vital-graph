# `include_frame_graph` Is Accepted On `/kgqueries` And Implemented Nowhere

## Status: OPEN, reproduced 2026-09-16. `POST /kgqueries` accepts
## `include_frame_graph`, the official client exposes it as a parameter, and
## the server hardcodes `frame_graph=None`. True and False return byte-identical
## results. Smaller than `issues/209` — nothing is wrong, something declared is
## simply absent — but the caller cannot tell the difference from here.

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
