# `include_slot_counts` Makes the Entity Detail Page 160x Slower

## Status: FIXED 2026-08-13 via `issues/087`

The slot-count query goes **3,436 ms -> 0.2 ms**, and a frame with slots reports
8, matching the UI's "8/8 shown". The cause was never local to this page: see
`087`. The endpoint and UI need no change.

## Superseded: ROOT CAUSE FOUND — not local to this page

**The cause is `issues/087`: `VALUES` with URI constants is never materialized to
term UUIDs, so it degenerates into a full scan with a text comparison.** This
page's 160x is that defect seen through one endpoint. Fixing it here alone would
leave the same cost in KGQuery entity-URI filtering, connection and relation
queries, document management, segment deletion, and `DESCRIBE` — 18 files build
a `VALUES` clause.

`EXPLAIN ANALYZE` on the slot-count query, with real frame URIs:

    Parallel Seq Scan on sp_lead_synth_100k_term t_v2   (10.4M-row term table)
    Parallel Seq Scan on sp_lead_synth_100k_edge  mv0   (full edge table)
    Join Filter: (mv0.source_node_uuid IS NULL)
                 OR ('urn:acme:lead:...frame:leadstatusframe:0'::text
                     = t_v2.term_text)
    Rows Removed by Join Filter: 1,292,333
    Buffers: shared hit=325,953

That confirms the hypothesis recorded below and refutes nothing else in it: the
`VALUES ?frame` restriction is applied as a post-join text filter, so the work is
proportional to the term and edge tables rather than to the two frames asked
about. The query returns 0 rows — correctly, both top frames are parents with no
direct slots — and still reads 325,953 buffers to say so.

**What that changes about the fix.** The three directions below are still valid
as mitigations, but the real fix is `087`. In particular, "bound the count query
by the frames asked for" is not an endpoint change: it is making `VALUES` reach
`materialize_constants` like every other constant already does.

## Original status: OPEN — measured 2026-08-13

Reported from the UI as an entity page that "loads very slowly in two phases".
Reproduced and attributed.

    GET frames, include_slot_counts=True     4,309 ms   (median of 3)
    GET frames, include_slot_counts=False       26.9 ms
                                              ------
                                                 160x

One query option accounts for essentially the whole page load.

## The page as the UI actually loads it

`sp_lead_synth_100k`, entity `urn:acme:lead:SYN000046907`, 2 top frames and 9
child frames:

    phase 1  top frames                        5,002.6 ms
    phase 2  children of top frame 1           4,314.6 ms
             children of top frame 2           4,158.2 ms
             9 slot requests            27 - 174 ms each   (~520 ms total)
             ----------------------------------------------
             TOTAL                     13,998.3 ms over 12 requests

That is the "two phases" the report describes: the frame tree arrives, then the
slots fill in. **14 seconds for one entity.**

## The N+1 is real and is NOT the problem

The page issues one slot request per expanded frame, which looks like the
obvious culprit and is not: those requests cost 27-174 ms each, ~520 ms of the
14 seconds. **Three `get_kgentity_frames` calls account for 13.5 s of it**, and
each is slow only because of `include_slot_counts`.

## The irony worth stating plainly

`include_slot_counts` exists to AVOID fetching slots — its own docstring says it
"lets a client decide whether a frame needs slot pagination without fetching its
slots". Fetching the slots costs 27-174 ms. Counting them costs 4,300 ms.
**The optimisation is ~100x more expensive than the work it avoids.**

## Mechanism — partly established, one hypothesis DISPROVED

`_count_slots_for_frames` (`kg_sparql_query.py:693`) is already batched — one
grouped query for the whole page, not one per frame, so that is not it:

    SELECT ?frame (COUNT(DISTINCT ?slot) AS ?slot_count) WHERE {
        GRAPH <g> {
            VALUES ?frame { <f1> <f2> }
            ?edge a haley:Edge_hasKGSlot ;
                  vital:hasEdgeSource ?frame ;
                  vital:hasEdgeDestination ?slot .
        }
    } GROUP BY ?frame

**Disproved:** that `a` (`rdf:type`) rather than `vital:vitaltype` costs it the
edge-table rewrite. Measured both forms — 3,806 ms and 3,613 ms, and
`{space}_edge` appears in the generated SQL either way. The rewrite fires.

**Supported, and now CONFIRMED by the plan above:** the `VALUES ?frame`
restriction is not bounding the scan. In that same test the query matched **0 rows and still took 3.7 s**, which
is the signature of work proportional to all `Edge_hasKGSlot` edges in the space
(~1M+ here) rather than to the two frames asked about. A grouped aggregate whose
input is not restricted by the `VALUES` join would behave exactly like this.

Next step is the EXPLAIN, not more guessing — the shape to look for is whether
the `VALUES` list drives the scan or is applied above it.

## Why this is worth fixing rather than working around

* It is on the **default path for viewing any entity**, the most ordinary thing
  a user does.
* It scales with the SPACE, not with the entity: the same two frames cost 27 ms
  to enumerate and 4.3 s to count, so a bigger space makes an unchanged entity
  page slower.
* A client-side workaround (drop `include_slot_counts`) is available and cheap —
  the UI could fetch slots and count them, which is 100x faster — but that
  leaves a 160x endpoint option in place for every other caller.

## Fix directions

1. **Bound the count query by the frames asked for.** If the `VALUES` join is
   not restricting the aggregate, that is the bug and the fix.
2. **Reconsider whether the option should exist.** Its purpose is to decide
   whether a frame needs slot pagination; the slot request itself already
   returns a total count, costs 27-174 ms, and is what the UI issues next
   anyway.
3. **Have the UI stop requesting it** as an immediate mitigation, independent of
   1 and 2.

## Related

- `issues/079` — same family: a check whose cost is unbounded in the healthy
  case.
- `planning/planning_performance/unexplored_performance_surface.md` — recorded
  in the gap list.
