# The KGQuery Fast Paths Silently Drop `include_entity_graph`

## Status: CONFIRMED and FIXED 2026-09-16. Reproduced against the vg-test
## stack — a sorted page and a filtered page both returned 25 URIs, a correct
## total and ZERO entity graphs for requests that set the flag, with the server
## log naming `entity_slot_sort` as what served them. Both fast paths now
## hydrate. Regression test at
## `tests/unit/test_fast_path_keeps_include_entity_graph.py`, verified to fail
## without the fix.

**Related:** `issues/096` / `issues/161` (the two fast paths), `issues/172`
(which widened the sort path and so widened this), `issues/208` (the projection
that would replace the flag on these shapes)

## The defect

`POST /kgqueries` with `include_entity_graph=True` returns `entity_graphs`
populated ONLY when the query falls through to the general SPARQL pipeline.
Neither fast path looks at the flag, and neither sets the field.

    kgquery_endpoint.py:755   _try_fast_slot_sort(...)    -> returns, or None
    kgquery_endpoint.py:764   _try_fast_slot_filter(...)  -> returns, or None
    kgquery_endpoint.py:876   if query_request.include_entity_graph and entity_uris:
                                  entity_graphs = await self._fetch_entity_graphs(...)

Line 876 is BELOW both returns. The fast-path responses are built at `:488` and
`:595` and neither passes `entity_graphs`, so the field stays None.

`grep -n include_entity_graph` over `kgquery_endpoint.py`, `fast_slot_sort.py`
and `fast_slot_filter.py` finds exactly one hit: line 876. Neither `can_serve`
nor `can_serve_filter` lists the flag among its disqualifiers, and both
enumerate their disqualifiers explicitly — `filter_decline_reason` names nine.

## Why it is a wrong answer and not a slow one

The caller asked for the graphs. It gets a 200, a correct URI page, a correct
total, and `entity_graphs: null` — the same response the flag's absence
produces. Nothing in the response, the status or the log says the flag was
ignored. A client that renders from `entity_graphs` renders an empty list of
rows for a query that matched thousands.

The trigger is not exotic. It is any query the table can serve:

  * a slot-value sort (`can_serve`) — "sort the lead list by Company"
  * frame-criteria equality with an entity type (`can_serve_filter`) — "leads
    in this campaign"
  * since `issues/172`, both together, which is THE list view

So the shapes most likely to want hydration are exactly the shapes that lose it.
And the better the fast paths get, the more callers fall into it — `172`
widening the sort path to accept frame criteria widened this at the same time.

## Why it has not been noticed

`tests/performance/test_entity_graph_fanout_bench.py` is the only bench on the
flag, and it queries by `entity_type` alone (`:120`) — no sort criteria, no
frame criteria. `can_serve` needs a slot-based `SortCriteria` and
`can_serve_filter` needs `frame_criteria`, so both decline and the bench always
measures the general pipeline. It cannot see this.

The `include_entity_graph` tests under `tests/api/` are all on the
`/kgentities` routes, not `/kgqueries`.

## The sibling surface gets it right, which is the argument for the shape of the fix

`kgentity_list_impl.list_entities:157` branches on the flag BEFORE choosing a
path, routing to `_list_entities_fast` or `_list_entities_with_graph`, and the
graph path hydrates each URI of the page (`:795`). Its own fast path
(`fast_entity_prop_page`, via `kg_backend_utils.py:1252`) sits INSIDE that
branch rather than in front of it.

`/kgqueries` has the opposite structure: choose the path, then hydrate, with the
hydration on only one of the three branches.

## The fix, as taken

1. **Hydrate after the fast path.** DONE — both paths, plus the `count_only`
   case which has no page to hydrate. `_fetch_entity_graphs` takes a list of URIs
   and nothing else; both fast paths have the URIs before they build their
   response. This keeps the fast path's win — the page selection is what was
   slow — and pays the fan-out only because the caller asked for it.
2. **Decline the fast path when the flag is set.** One line in each of
   `can_serve` / `can_serve_filter`, correct and much worse: it returns the
   query to the pipeline measured at >90 s on a 53.4M-quad space, to buy
   hydration that option 1 gets for the same +80-290 ms.

Option 1 also has to cover `count_only`, which the filter path serves and where
there is no page to hydrate.

`issues/208` is the better long-run answer for the list-view shape — a named
slot projection out of `entity_slot_sort` instead of ~18,600 quads per page —
but it does not subsume this. The flag is a general request for the whole entity
graph and will outlive any projection surface.

## REPRODUCED, then FIXED — 2026-09-16

`lead_nurture_grouped` on the vg-test stack, four requests, all four with
`include_entity_graph=True` except the control. `test_scripts/perf/verify_entity_graph_on_fast_paths.py`.

    BEFORE                            uris    total   graphs    quads       ms
    baseline (no sort, no filter)       25  100,000       25   18,937   43,451
    + a slot-value sort                 25  100,000        0        0      980
    + frame-criteria equality           25   15,032        0        0      260
    control (the sort, flag OFF)        25  100,000        0        0      145

    AFTER
    baseline (no sort, no filter)       25  100,000       25   18,937   18,797
    + a slot-value sort                 25  100,000       25   18,000    5,900
    + frame-criteria equality           25   15,032       25   18,460    4,176
    control (the sort, flag OFF)        25  100,000        0        0      587

The server log is what makes those middle rows evidence rather than a guess —
before:

    _try_fast_slot_sort   INFO  Entity slot sort via entity_slot_sort:
                                25 uris, total=100000, 947ms
    _try_fast_slot_filter INFO  Entity slot filter via entity_slot_sort:
                                25 uris, total=15032, 246ms

and after, the same lines with the hydration accounted for separately:

    _try_fast_slot_sort   INFO  Entity graph fetch (fast sort path):
                                25 entities, 5067ms
    _try_fast_slot_sort   INFO  Entity slot sort via entity_slot_sort:
                                25 uris, total=100000, 5587ms

Wall-clock across the two runs is not comparable — the second ran with warm
buffers, which is why the baseline nearly halved. What is categorical is 0
graphs becoming 25 with the same criteria and the same served path.

**Option 1 was taken, and the measurement retires option 2.** Declining the fast
path when the flag is set would have cost the general pipeline's 38,670 ms page
(the log's figure for the baseline query, cold) to buy the 4-5 s of hydration
that hydrating in place buys directly. The control row is the other half of the
fix: flag off, no fan-out, 587 ms — hydrating unasked would have handed back the
whole point of the fast path.

Hydration sits OUTSIDE the `async with pool.acquire()` block so it does not hold
a pool connection while it runs SPARQL, and INSIDE the `try` so that a hydration
failure returns the query to the general pipeline rather than serving a page
with the field missing — which is the defect itself.

**This is the strongest case yet for `issues/208`.** The fix's whole cost is a
3.5-5.1 s fan-out of the entire entity graph — 18,000+ quads for 25 entities —
where a list view renders eight columns, measured at 0.76 ms out of
`entity_slot_sort`. The right end state is that a caller naming its columns
never pays this fan-out at all.

## Not yet established

- Whether any real caller sends both together today. If the portal's list view
  hydrates through a second `/kgentities` request instead, this was latent
  rather than live — which changes how urgently it needed fixing, not whether
  it was a defect.
- ~~Whether the `/kgframes` fast path has the same hole for
  `include_frame_graph`.~~ CHECKED 2026-09-16: it does not. There the flag is
  implemented on the URI-LOOKUP routes only and is not a parameter of the paged
  listing, so the listing's fast paths cannot bypass it. The check found a
  different defect on the query surface instead — `include_frame_graph` is
  accepted by `POST /kgqueries` and implemented nowhere. See `issues/210`.
- Whether `entity_uris` ordering is preserved through `_fetch_entity_graphs`
  (it returns a dict keyed by URI, so the page order lives in `entity_uris`
  either way — worth confirming a client does not depend on dict order).

## Reproduce

    grep -n "include_entity_graph" vitalgraph/endpoint/kgquery_endpoint.py

One hit, at line 876, below both fast-path returns.
