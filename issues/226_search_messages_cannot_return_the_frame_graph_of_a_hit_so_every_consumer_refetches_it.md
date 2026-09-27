# KGQuery FTS Cannot Return The Frame Graph Of A Hit, So Every Consumer Refetches It

## Status: OPEN — feature request from a downstream consumer 2026-09-21.
## COST, NOT CORRECTNESS. The reporter explicitly ranked it below `issues/225`
## and asked that it not queue ahead.
##
## PRICED 2026-09-25, and the list-view half is much cheaper than this file
## assumed: a frame-keyed probe on `entity_slot_sort` serves a 25-frame page in
## **31 buffers** against 2,295 for the refetch it replaces — on a column and an
## index that ALREADY EXIST and have no reader. Two claims below are corrected by
## measurement: the frame graph is ~12k buffers, not "anywhere near" 3.5-5.1 s
## (the conclusion "do not default it" survives, the reason changes), and
## `_get_frames_by_uris` does NOT produce frame graphs — see `issues/240`.
## Still NOTHING BUILT. See the appended section.

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

## MEASURED 2026-09-25 — the list-view case is a 31-buffer probe, and this file's cost estimate was an order of magnitude high

Three things came out of pricing the options on a production-shaped space. The
capability is cheaper than this file assumed, the expensive option is cheaper
too, and the route both this file and `issues/210` recommend does not work.

### The fixture

`nurture_typed` on the vg test stack (5433) is this issue's shape at scale:

    nurture_typed_entity_slot_sort   2,995,193 rows   (now 2,934,198)
    distinct frames                    509,203
    distinct owning entities            87,110         (now 85,330)
    distinct slot types                    146
    MsgTimestamp / MsgChannel / MsgDirection / MsgSender / MsgCycleNumber

2026-09-26: a local delete experiment on the vg test stack consumed ~2% of
this space (1,780 of 87,110 entities, 1,011,607 quads). Figures above are
the ORIGINAL measurements with the current values beside them — the drop is
that experiment, NOT a regression. There is no local source to reload from:
`nurture_msg_prod` was dropped and the only local prod copy is less than
half the size.

                                       322,036 each
    MsgContent                         322,020

So the slot types this issue names by hand are the ones the table already holds,
at ~5.9 slots per frame — the "seven quads, no timestamp, no channel" structure
described above, 322,036 times.

### The numbers

One 25-frame page, frames drawn ordered by `frame_uuid` so they are SCATTERED
rather than one conversation — the realistic case for a page of FTS hits, and the
worse one for locality. Two columns, `MsgTimestamp` and `MsgChannel`. All three
forms return the same 50 values for the same 25 frames.

| for one 25-frame page | buffers | warm exec ms (min/med/max, 5 reps) |
|---|---:|---|
| frame-keyed probe on `entity_slot_sort` | **31** | 0.33 / 1.03 / 1.61 |
| the same 2 values walked from the QUADS | 2,295 | 8.96 / 13.16 / 22.55 |
| whole frame graph, term-resolved | 11,924 | 53.6 / 85.7 / 341.8 |

**74x on buffers against the refetch this issue exists to remove; 385x against
the whole frame graph.** That mirrors `issues/208`'s 76x on the entity side
almost exactly.

Buffers are the finding, not the milliseconds: the buffer counts were
byte-identical across three repetitions of each form, while `nurture_typed` is
NOT in `VG_MAINTENANCE_EXCLUDE_SPACES` and three sessions were active during
timing, which is where the ms spread comes from. First-run figures (15.9 ms,
133.3 ms, 1,621 ms) are cold and excluded.

### The capability is a column and an index that ALREADY EXIST and have no reader

This file says "check `db/sparql_sql/slot_projection.py` first". Doing so finds
something better than a pattern to copy:

  * `entity_slot_sort` carries **`frame_uuid UUID NOT NULL`**
    (`sparql_sql_schema.py:1242`).
  * **`idx_{space}_ess_frame ON (frame_uuid)`** exists
    (`sparql_sql_schema.py:1801`), created for the incremental maintenance DELETE
    — its comment says "walks up from a touched entity or frame".
  * **No reader uses it.** `slot_projection`, `fast_slot_sort`,
    `component_intersect` and `slot_sort_range` do not mention `frame_uuid` at
    all.

So this is `issues/208`'s finding one surface over — the table, the column and
the index are built and maintained, and nothing reads them in this direction.
The probe is the entity query with one predicate changed:

    WHERE context_uuid = $1
      AND frame_uuid = ANY($2::uuid[])
      AND slot_type_uuid = ANY($3::uuid[])

    Index Scan using idx_nurture_typed_ess_frame   31 buffers, 50 rows

Two ways the frame version is BETTER than the entity one it copies, both from
the plan rather than assumed:

  * **No `frame_type_path` matching.** The path exists to say which frame under
    an entity a slot belongs to. Anchored on the frame there is nothing to
    disambiguate — which also removes the whole-path-match hazard
    `component_intersect.py:39` records as a wrong-rows failure.
  * **Better selectivity.** It read 170 rows to return 50 (~6.8 slots per
    frame). The entity form reads 1,025 to return 200, because an entity's probe
    spans every frame it owns.

No term join either: `_term_uuid(frame_uri)` gives the probe key, and
`FTSMatch.frame_uri` is already in the result before anything is fetched.

### This file's cost estimate for the frame graph was too pessimistic

Above: *"If frame hydration lands anywhere near the entity figure"* of 3.5-5.1 s.
It does not. The whole frame graph for 25 frames is **2,567 quads / 11,924
buffers / 53.6-341.8 ms**, term-resolved. The entity graph is ~18,000 quads for
25 entities — ~7x more data, and the timings track that ratio.

**The conclusion survives and should be kept: do not default it.** 11,924
buffers is 385x the projection and 2-14x the 17-25 ms search it decorates. But
it should be declined on that number, not on a feared 3.5 s, because the gap
between those two readings is the difference between "never" and "offer it for a
detail view".

Two related corrections, both from reading the entity path rather than inferring
from its figure:

  * **`_fetch_entity_graphs` is already batched and cache-fronted**
    (`kgquery_endpoint.py:1834` — one query over a `VALUES` clause, misses only).
    So 3.5-5.1 s is ONE query resolving ~18,000 quads, not N round trips. TERM
    RESOLUTION is where it goes: adding the three term joins to the frame-graph
    query took it from 2,122 to 11,924 buffers, 5.6x, for the same 2,567 quads.
  * **`_get_frames_by_uris` is per-URI**, one `get_object` per frame under
    `bounded_gather`. Implementing the frame graph through it inherits 25 round
    trips instead of the one batched query the entity side already uses.

### The per-page query already does the walk and reads the wrong lanes

`_build_entity_slot_refs_query` (`kgquery_endpoint.py:2225`) already runs ONCE
PER PAGE with `VALUES ?frame { ... }`, already walks
`frame -hasEdgeSource/hasEdgeDestination-> slot -hasKGSlotType-> type`, and
already reads a slot value — but only `hasEntitySlotValue` and
`hasUriSlotValue`. Every literal lane is absent.

So "attach AFTER narrowing" and "one join, not one per requested slot type" are
already the shape in the code; what is missing is the value lanes. That makes a
SPARQL-level fix look like one more UNION arm — but there are **27
`has*SlotValue` predicates** in the ontology, so it is 27 arms. `entity_slot_sort`
has already collapsed all of them into `value_text`/`value_num`/`value_dt`, which
is the stronger argument for the derived-table route over the SPARQL one.

### The route this file recommends does not work — filed as `issues/240`

> **KGQuery already holds the input.** `_get_frames_by_uris` takes a list of
> frame URIs

It takes the list and it takes `include_frame_graph`, and the flag appears
NOWHERE in the function body (`kgframes_endpoint.py:1349`). The multi-URI lookup
returns frames without their graphs, HTTP 200, no message; the single-URI form
implements it. `issues/210` states this surface is clean and is wrong for the
`uris=` form. See `issues/240`.

### Caveats on the above

  * **The coverage gate applies.** `slot_sort_is_blocked` defaults to BLOCKED on
    any uncertainty, and a block must decline the WHOLE projection — a short
    table renders a blank column, which reads as "no value set"
    (`issues/208`). `nurture_typed` holds zero blocks so it is servable; 16
    spaces / 40 type-rows are blocked right now, so the gate does bite.
  * **Coverage is exact here; the structural risk is not addressed.** For
    `MsgChannel`: 322,036 slots in the quads, 322,036 rows in the table, zero
    missing in either direction. All 509,203 frames with slots have slot-sort
    rows. But `entity_uuid` is `NOT NULL` in that table, so a frame with no
    OWNING ENTITY gets no row at all — not live on this space, unverified
    elsewhere, and `frame_slot` is the table that would cover it (it holds every
    frame's slots, and no values).
  * **SQL only.** Endpoint overhead, GraphObject rebuild and serialisation are
    outside every figure here. Nothing was measured through the API.
