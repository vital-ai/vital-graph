# `search_messages` Returns A Hit With No Sibling Slots, So Every Consumer Refetches The Frame

## Status: OPEN — feature request from a downstream consumer 2026-09-21.
## COST, NOT CORRECTNESS. The reporter explicitly ranked it below `issues/225`
## and asked that it not queue ahead.

**Related:** `issues/225` (the correctness defect from the same report)

## The gap

`MessageHit` is `{entity_uri, slot_uri, frame_uri, text, score}`.

Every consumer rendering a message row also needs the sibling slots of the same
frame — `MsgTimestamp` and `MsgChannel` at minimum, to show when a message was
sent and over which channel. None are projected, so each consumer writes the
same per-page frame fetch after the search returns.

That is N round trips per page, duplicated in every consumer, to assemble data
the search already had a join away.

## The unit is the FRAME, not a bigger slot — and both names already exist

**CORRECTION to this issue as first written.** It proposed inventing a
`project_slots=[…]` parameter. That reinvents two things that already exist, and
the right fix is to reuse them rather than add a third vocabulary.

First, what is NOT the answer: returning "the whole slot object". The matching
slot carries exactly seven quads —

    hasKGSlotType      …:slot:MsgContent
    hasTextSlotValue   "I just finished the application …"
    hasFrameGraphURI   urn:…:nurture:00QUg00
    hasKGGraphURI      urn:…:nurture:00QUg00
    rdf:type / URIProp / vitaltype

— and **no timestamp, no channel**. Those are separate SLOTS under the same
frame. `MessageHit` already IS the whole slot object: `text` is
`hasTextSlotValue`, `frame_uri` is `hasFrameGraphURI`, `entity_uri` is
`hasKGGraphURI`. Everything else on the node is a type constant. Widening the
slot yields nothing; the containing FRAME is the unit that holds all six values
together.

Two existing mechanisms already say this:

* **`slot_projection`** (`kgqueries_model.py:191`, `List[SlotProjection]`) —
  IMPLEMENTED on the entity query surface (`kgquery_endpoint.py:447`, backed by
  `db/sparql_sql/slot_projection.py`). Its docstring states the intent exactly:
  "a list view gets one row per entity whichever" — naming the columns wanted
  instead of fetching a subtree. This is the primitive a message list wants.
* **`include_frame_graph`** — IMPLEMENTED on `/kgframes`, but only on the URI
  LOOKUPS `_get_frame_by_uri` / `_get_frames_by_uris`
  (`kgframes_endpoint.py:1347`), NOT on any paged listing. On `/kgqueries` it is
  a documented parameter that does nothing — `issues/210`, where option 2
  shipped so the flag at least now SAYS so, and option 1 is still open.

So `search_messages` should expose `slot_projection` with the same shape and
semantics as the entity query, rather than a new parameter spelled differently.
`_get_frames_by_uris` is the ready-made path for the whole-frame variant, and
search already has its exact input: every hit carries `frame_uri`, bound
unconditionally because the FTS push-down needs it.

## Why `slot_projection` rather than defaulting to the whole frame graph

Because hydration is not cheap, and this search is fast. `issues/209` measured
graph hydration after the page at **3.5-5.1 s for 25 entities** on the entity
side. An unranked message page is **17-25 ms**. If frame-graph hydration lands
anywhere near that entity figure, returning full frame graphs by default would
cost two orders of magnitude more than the search it decorates.

That is `issues/208`'s argument in one line: a caller naming what it wants
should not pay a whole-graph fan-out for it. A message row needs two slots, not
a subtree.

Offer both, default to neither:

    slot_projection=[MsgTimestamp, MsgChannel]   the list view — cheap, named
    include_frame_graph=True                      the detail view — whole frame

Measure the second before offering it, against the unranked path specifically.

## What to be careful about, since this touches the measured path

**Do not widen the candidate set.** `vg:textSearch` compiles to a correlated
scalar subquery keyed on the bound variable's uuid; it scores what the BGP has
already produced and cannot drive from the GIN index, so cost tracks the
CANDIDATE SET, not the match count. Constraining to one slot type cut
candidates 55.7x on a measured space. A sibling projection must attach to hits
AFTER narrowing — never as an additional unconstrained slot pattern, which
would re-widen exactly what `slot_type` narrowed.

**Projecting a slot is not free in the unranked path.** `order_by="slot"`
(`vg:textMatch`) is cheap because nothing is scored and the page stops at
`page_size`. A per-hit join is bounded by `page_size` and so should stay cheap,
but it should be MEASURED against the unranked path, not just the ranked one —
the two have different cost shapes and the unranked one is the recommendation.

**One join, not one per requested slot type.** The obvious implementation adds
a pattern per entry in `project_slots`; at 2-3 entries that is 2-3 more joins
per hit. Prefer a single join over the frame's slots filtered by an `IN`, so
cost is flat in the length of the list.

## Why it is worth doing rather than documenting

The alternative is what they do now: every consumer writes the same fetch.
That is the shape that produces N slightly different implementations, one of
which eventually pages differently or drops a slot type, and the bug then looks
like a search defect rather than a consumer one.

Not urgent. Their words: "Cost, not correctness — we can absorb it."
