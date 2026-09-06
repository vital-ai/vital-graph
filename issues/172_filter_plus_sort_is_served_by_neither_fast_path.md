# Filter + Sort Is Served By Neither Fast Path

## Status: OPEN, and now MEASURED. Filter alone answers in 5ms; the same
## filter with a sort does not finish in 120s. Found by reading what the
## consuming portal asks for, then confirmed on a 74M-quad fixture.

## The gap

Two fast paths read `{space}_entity_slot_sort`, and each declines the other's
input:

    can_serve_filter   returns False if `sort_criteria` is set
                       "A sort is the OTHER path's job. Serving both here would
                        mean ordering by a column this query never selected."

    can_serve (sort)   returns False if `frame_criteria` is set
                       "The table sorts a population; it does not select one."

Both refusals are individually correct and locally well-argued. Together they
mean A FILTERED, SORTED LIST IS SERVED BY NEITHER, and falls through to the
general SPARQL pipeline — the path measured at >90s on a 53M-quad space where
the fast path answers the same question in ~20ms.

## Why that matters more than it looks

A filtered, sorted list is not an exotic shape. It is THE list view: pick a
status and a campaign, sort by name or modified date, page through. The portal's
entity router has a dedicated "Sorted query" branch that builds exactly this —
frame criteria with `eq` slots, plus a sort — and it is the shape a user
produces by clicking a column header on a filtered list.

So the two paths cover the two halves of the product's main screen and neither
covers the screen.

## What IS servable, for contrast

`_eq_criteria` walks nested frames and accepts any number of frames and slots as
long as every comparator is `eq` — so the portal's multi-frame conjunction
(nurture status + campaign URI, plus a second frame's channel slot) is fine on
its own. Adding `sort_by` to it is what loses the fast path.

That is a cliff, not a slope: the same query with and without a sort differs by
orders of magnitude, and nothing in the response says which one happened.

## THE QUESTIONS THIS CAME FROM, to be finished

Raised while reading the portal's routers. The first is answered; the rest are
open and worth answering before optimising anything.

  1. DOES THE PORTAL PULL FULL GRAPHS TO RENDER A LIST? YES, AND IT IS FORCED
     TO. The sorted criteria call returns URIs only, so the router fetches every
     row's whole entity graph by URI in a second batched call, with the comment:
     "this path otherwise returns URIs only, which blanks every column sourced
     from the entity summary (name, modified date)".

     So rendering a name column costs an entire entity graph per row. If
     `query_entities` returned entity summary properties — or honoured
     `include_entity_graph`, which the router notes it IGNORES — the second call
     and most of its payload would not exist.

  2. Are the portal's page sizes still right? The diagnostic cases use 5, 20 and
     50, and the route caps at 200. With a fast path at ~20ms a small page is
     cheap; with the general pipeline a large page is what makes it fatal. The
     page size interacts with which path serves it, and neither side knows.

  3. Does the portal issue separate count and list calls where the
     implementation already runs them concurrently? `list_entities` runs count
     and URI queries together; a caller doing its own count in a separate
     request pays twice for one of them.

  4. Which portal criteria shapes MISS the fast path? Question 1 above found one
     (any sort). Others to check: a non-`eq` comparator anywhere in a
     conjunction disqualifies the WHOLE query, and a slot hanging directly off
     the entity rather than under a frame is not in the table at all.

## Options, none costed yet

  * TEACH THE FILTER PATH TO ORDER. It selects a population by criteria; the
    sort column is a slot value it could carry. The stated objection — "ordering
    by a column this query never selected" — is about the current SELECT, not
    about the table.
  * TEACH THE SORT PATH TO SELECT. Symmetric, and the objection there is
    stronger: it is written to order a whole population.
  * A THIRD PATH for filter+sort, at the cost of a third thing to keep correct.
  * DECIDE IT IS ACCEPTABLE and make the general pipeline fast enough for it —
    which is `issues/161`'s problem and has no answer yet.

MEASURE FIRST. This issue asserts a cliff from reading the two gates; it does
not yet have a number for the filtered+sorted shape on a large space. That
measurement is the first task, because if the general pipeline happens to serve
this shape acceptably the whole issue is a documentation fix.


---

# WHAT THE SCREENS NEED — the part we ARE locked into

The query SPECIFICATION is not fixed; the CONTENT the screens surface is. So the
useful move is to specify better queries for the same content and measure those,
rather than optimise the queries that exist. This section records the content,
taken from the consuming portal's routers and frontend hooks.

## Screen 1 — the entity list

Filters offered, all optional except the type:

    entity_type            REQUIRED
    search                 text within entity names
    status / exclude_status
    created_after / before, modified_after / before
    action_type            membership in a list-valued property
    frame/slot criteria    equality on slot values, multi-frame
    sort_by                an ENTITY PROPERTY uri, asc/desc
    sort_slot_type         or a SLOT value, asc/desc
    page / limit           limit defaults 50, capped at 200

Rendered per row: THE ROOT ENTITY OBJECT ONLY. `_summary_from_graph` picks the
object whose URI matches the entity and ignores the rest of the graph.

## Screen 2 — the row's detail, PREFETCHED

The list also returns `entity_graphs`: every row's full graph, which the
frontend seeds into its cache so opening a row costs no request. Its own note:
"one request per page instead of 1 + page_size, and ~33x less server work."

THIS IS NOT WASTE, and an earlier reading of this issue nearly recorded it as
such. The graphs are used. The list screen renders one object per row and the
detail view consumes the rest, without a second round trip.

## What that means for a better specification

The two needs are separable and are currently fused into one call:

    A. SUMMARIES   filtered + sorted + paged root entity objects. Small.
                   This is the one that falls off the fast-path cliff above,
                   and it is the one the user waits for before seeing anything.
    B. GRAPHS      the same page's full graphs, a prefetch for a click that may
                   never come. Large, and already batched into one query.

A better specification would let A return without waiting for B — the list can
paint from summaries alone, and the prefetch can follow. Today they are one
response, so the slowest part of the page gates the fastest.

Whether B should be eager at all is a product judgement about click-through
rate, and is NOT ours to make here. But it is a lever the current single-call
shape does not expose, and exposing it costs nothing if A is served separately.

## The measurement that decides this

    A alone      filtered + sorted + paged summaries, page 50
    A + B        the same, with graphs, as today
    B alone      the batched graph fetch for 50 known URIs

on a 50M+ space, with the fast-path cliff above both present and absent. If A is
fast and B dominates, the fix is to split the response. If A is slow because of
the cliff, splitting changes nothing until the cliff is fixed — and that
ordering is the whole reason to measure before proposing.


---

# MEASURED, on `lead_nurture_grouped` (74.2M quads, page 50)

The gates decline it, as read:

    filter only   filter_path=True    sort_path=False
    filter+sort   filter_path=False   sort_path=False

And the fallback does not merely degrade:

    general pipeline, filter only          5 ms      50 rows
    general pipeline, filter + SORT        TIMED OUT at 120s

    (the same filter on the fast path:    21 ms count / 22 ms page 50,
     78,496 matches; the page's 50 graphs batched: 49 ms / 37,760 triples)

So the cliff is not a factor. It is the difference between 5ms and never.

Worth noting the filter-only case is FASTER through the general pipeline (5ms)
than through the fast path (21ms). The fast path is not what makes filtering
work here; the sort is what makes it fail.

## WHY: the sort defeats early termination

`EXPLAIN` on the filter+sort SQL gives a cost of 23,173,646,587 — twenty-three
billion — over this shape:

    Limit 50
      Sort            (p0.v11, p0.v0)
        Subquery Scan
          Sort        (e0.v10 COLLATE "C", e0.v0)
            GroupAggregate
              Sort
                Nested Loop  ... cost 23,173,611,670

Three nested sorts and an aggregate above a nested loop. The filter-only query
stops as soon as it has 50 rows; the sorted one must resolve ALL 78,496 matching
entities and their sort keys before it can take the first 50. Every row of the
match set is paid for to return a page of fifty.

That is exactly the property `emit_slice._emit_two_phase` documents itself as
depending on — "only O(page) while the planner drives it from an ordered,
early-terminating scan" — and exactly what the slot-sort table exists to
provide.

## THE FIX IS AVAILABLE IN THE TABLE THAT ALREADY EXISTS

Both halves of this query are answerable from `{space}_entity_slot_sort`:

    the FILTER   entities whose (frame_type_path, slot_type, value_text) match
                 the campaign criterion
    the SORT     the same entities' value_text for the sort slot

and `idx_{space}_ess_text` is
`(context_uuid, entity_type_uuid, frame_type_path, slot_type_uuid, value_text,
entity_uuid)` — leading columns for the filter, and an ORDERED value_text for
the sort. A filtered, sorted page is two index scans on one table intersected on
`entity_uuid`, ordered by the sort scan's `value_text`, limited to the page.

The sort path's stated objection — "The table sorts a population; it does not
select one" — is a statement about the current implementation, not about the
table. The table can do both, and this measurement is the reason to make it.

## What this does NOT show

Only one filter shape and one sort key, on one fixture, with a warm cache. It
does not show where the cliff STARTS: a smaller match set may sort acceptably,
and the interesting number for a product decision is the match count at which
this becomes unservable, not that 78,496 does.
