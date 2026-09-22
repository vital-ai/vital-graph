# KGQuery FTS Cannot Return The Frame Graph Of A Hit, So Every Consumer Refetches It

## Status: OPEN — feature request from a downstream consumer 2026-09-21.
## COST, NOT CORRECTNESS. The reporter explicitly ranked it below `issues/225`
## and asked that it not queue ahead.

**Related:** `issues/210` (`include_frame_graph` accepted on `/kgqueries` and
implemented nowhere — the same missing capability on the neighbouring surface),
`issues/208` (a caller naming what it wants should not pay a whole-graph
fan-out), `issues/209` (what hydration after the page actually costs),
`issues/225` (the correctness defect from the same report)

## The gap

A search matches a SLOT. A message is a FRAME. There is no way to ask for the
second.

`FrameQueryResult.fts_matches` returns `FTSMatch(subject_uri, frame_uri,
owner_entity_uri, target_kind, text)`. That is the matching slot metadata and
nothing else, so every consumer rendering a message row goes back to the
database for the rest of the frame — N round trips per page, reimplemented in
every consumer.

    MsgContent      <- what matched, and all the search returns
    MsgChannel         sms
    MsgTimestamp       2026-08-12T18:38:01.788310+00:00
    MsgDirection       inbound
    MsgSender          +1929…
    MsgCycleNumber     5

A conversation row in a UI is "inbound, sms, Aug 12 6:38pm — *I just finished
the application…*". One of those four fields comes from the search.

## What is NOT the fix, because it is the obvious first guess

Returning "the whole slot object" gains nothing. The matching slot carries
exactly seven quads:

    hasKGSlotType      …:slot:MsgContent
    hasTextSlotValue   "I just finished the application …"
    hasFrameGraphURI   urn:…:nurture:00QUg00
    hasKGGraphURI      urn:…:nurture:00QUg00
    rdf:type / URIProp / vitaltype

**No timestamp, no channel.** Those are separate SLOTS of the same frame, not
properties of this one. `FTSMatch` already carries the useful matching-slot
metadata — `text` is `hasTextSlotValue`, `frame_uri` is `hasFrameGraphURI`,
`owner_entity_uri` is `hasKGGraphURI`, and the remainder are type constants.

A bigger slot is not the answer. A different unit is.

## The names already exist — do not invent a third

* **`include_frame_graph`** — IMPLEMENTED on `/kgframes`, but only on the URI
  LOOKUPS `_get_frame_by_uri` / `_get_frames_by_uris`
  (`kgframes_endpoint.py:1347`), never on a paged listing. On `/kgqueries` it is
  a documented parameter that does nothing (`issues/210`; option 2 shipped so
  the flag now SAYS so, option 1 is still open). It remains a no-op on
  FTS-selected `frame_query` results.
* **`slot_projection`** (`kgqueries_model.py:191`, `List[SlotProjection]`) —
  IMPLEMENTED on the entity query surface (`kgquery_endpoint.py:447`, backed by
  `db/sparql_sql/slot_projection.py`). Its docstring is the intent exactly:
  name the columns wanted so "a list view gets one row per entity".

So this is not a missing idea. It is a capability that exists on neighbouring
surfaces and was never extended to this one.

**KGQuery already holds the input.** `_get_frames_by_uris` takes a list of frame
URIs, and every FTS-selected `FrameQueryResult` carries `frame_uri`; every
`FTSMatch` is attached only after the result page is chosen. The indexed slot
carries both `hasKGGraphURI` and `hasFrameGraphURI`, so the builder's input is
sitting in the result already.

## Offer both, default to neither

    slot_projection=[MsgTimestamp, MsgChannel]    list view — cheap, named
    include_frame_graph=True                       detail view — whole frame

**Do not make the frame graph the default.** `issues/209` measured hydration
after the page at **3.5-5.1 s for 25 entities** on the entity side. An unranked
message page is **17-25 ms**. If frame hydration lands anywhere near the entity
figure, a default frame graph costs two orders of magnitude more than the search
it decorates — `issues/208`'s argument restated.

A message list wants two slots. A message detail view wants the frame. Those are
different requests and should stay different.

## What to be careful about, since this touches the measured path

**Attach AFTER narrowing, never as another search pattern.** `vg:textSearch`
compiles to a correlated scalar subquery keyed on the bound variable's uuid; it
scores what the BGP already produced and cannot drive from the GIN index, so
cost tracks the CANDIDATE SET, not the match count. Constraining to one slot
type cut candidates 55.7x on a measured space. Adding an unconstrained slot
pattern to the search re-widens exactly that.

**Measure against the UNRANKED path.** `order_by="slot"` (`vg:textMatch`) is
cheap because nothing is scored and the page stops at `page_size`; it is also
the recommendation for broad queries. A per-hit join is bounded by `page_size`
and should stay cheap, but the two paths have different cost shapes and only the
ranked one has been measured with decoration.

**One join, not one per requested slot type.** The naive implementation adds a
pattern per entry; at 2-3 entries that is 2-3 more joins per hit. Prefer a
single join over the frame's slots filtered by an `IN`, so cost is flat in the
length of the list. Check `db/sparql_sql/slot_projection.py` first — it serves
this shape on the entity surface, and the point of reusing it is not to
re-decide this.

## Until then

Consumers should fetch per PAGE, keyed on the `frame_uri` each hit carries — one
query for the page's frames, not one per hit. A page of 25 is at most 25 frames
and usually fewer, since several hits often share a conversation.

## Why it is worth doing rather than documenting

The alternative is the status quo: every consumer writes the same fetch. That is
the shape that produces N slightly different implementations, one of which
eventually pages differently or drops a slot type — and the bug then looks like a
search defect rather than a consumer one.

Not urgent. The reporter's words: "Cost, not correctness — we can absorb it."
