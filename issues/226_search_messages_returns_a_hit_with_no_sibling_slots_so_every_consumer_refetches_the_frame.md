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

## Proposal

A `project_slots=[<slot type uri>, …]` parameter on `search_messages`, filled
where the hit is already assembled.

The shape is already there. `_build_message_search_sparql` emits
`?slot <haley:hasKGSlotType> <slot_type>` to narrow the search, and the frame is
already bound — `?slot <haley:hasFrameGraphURI> ?frame` is projected
unconditionally, because the FTS push-down needs it (see the comment at that
site: every indexed slot carries both, zero missing). So sibling slots of the
same `frameGraphURI` are one more join from what the query already binds.

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
