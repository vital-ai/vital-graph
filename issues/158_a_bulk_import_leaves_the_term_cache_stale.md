# A Bulk Import Leaves The Running Server's Term Cache Stale

## Status: FIXED 2026-09-04. This file was rewritten twice before the cause was
## found; both wrong diagnoses are kept at the end, because the way they were
## wrong is the useful part.

## What happens

`generator._term_cache` maps `(space_id, text, type, lang, datatype) -> term_uuid`
for the life of the PROCESS. A bulk import TRUNCATES the term table and reloads
it, and `term_uuid` is a UUIDv5 over exactly those components — so if a literal's
datatype changes between loads, its uuid changes and every cached mapping for
that space is wrong.

A server holding the old mapping then emits SQL looking for a term that no
longer exists:

    'SYN000000000'  stored after reload   ea15bbc8...  (datatype_id=1, xsd:string)
                    what the SQL asked for daa00b9e...  (datatype_id=NULL, cached)

The query is correct, the data is correct, the answer is 0 rows, and nothing
reports anything. Restarting the server fixed it instantly and nothing else
changed — which is how the cache was identified.

## WHEN IT ACTUALLY BITES — narrower than "every import"

Verified end to end after the fix: a CLI import that RELOADS THE SAME DATA under
the same conventions is harmless. Term uuids are deterministic over
`(text, type, lang, datatype)`, so an identical reload produces identical uuids
and every cached mapping stays valid. Measured — the affected query returned 1
both before and after a server restart:

    after CLI import, server NOT restarted    total=1
    after restart (cache cleared)             total=1

The cache goes stale only when a reload CHANGES a literal's identity — its
datatype or language. That is what happened here: the space was reloaded while
the importer's `xsd:string` handling was being changed, so `'SYN000000000'` moved
from `datatype_id=NULL` to `datatype_id=1` and its uuid changed underneath a
running server.

That is rare but not exotic: it is any schema or ingest change that alters how a
value is typed, applied by reloading a space — which is precisely when someone
is least expecting stale reads, and the failure is silent.

THE WARNING IS DELIBERATELY CONSERVATIVE. It fires on every import without a
signal manager, because the importer cannot know whether any uuid changed
without comparing old and new term tables — which would cost more than the
warning is worth. A false warning costs a line of log; a missed one costs a day.

## Why it was not caught

`invalidate_term_cache(space_id)` HAS EXISTED all along, next to
`invalidate_datatype_cache` and `invalidate_stats_cache`. It had no callers
outside its own unit test. The cross-process mechanism was complete for the
other two caches and simply absent for this one:

    notify_cache_invalidate("datatype", ...)   sent, and handled
    notify_cache_invalidate("stats", ...)      sent, and handled
    notify_cache_invalidate("term", ...)       never sent, no handler branch

## The fix

  * `vitalgraphapp_impl._handle_cache_invalidate` gains a `term` branch calling
    `invalidate_term_cache(space_id)`.
  * `ImportEngine` takes an optional `signal_manager` and calls
    `_invalidate_term_cache(space_id)` after the resync, which clears this
    process's cache and notifies the others.
  * When there is NO signal manager — which is the CLI's case, and exactly the
    case that bit — it logs a WARNING naming the consequence: a running server
    still holds the old mappings and will return 0 rows until restarted. A
    command-line import cannot reach a server's memory, so the only honest
    options are to tell it or to say so.

## Two wrong diagnoses, and why

1. **"Two datatype conventions disagree."** Believed because
   `rdflib.Literal("CA").datatype is None` while the CSV loader stores
   `xsd:string` — a fact about a bare library object generalised to the
   application without checking it. Production settled it: 375,186 xsd:string
   terms and ZERO untyped, in three spaces including one written through the
   CRUD path. There is one convention.

2. **"The flat text-criterion path drops the datatype when hashing."** Believed
   because the SQL demonstrably looked for the untyped uuid. It does not:
   `generator._norm_dt` already collapses plain and `xsd:string` deliberately,
   with a comment recording the same measurement. The untyped uuid came from the
   CACHE, populated while the space briefly held untyped terms during an
   experiment.

Both were built on real observations and neither survived one more measurement.
The tell in each case was a mechanism proposed but never traced end to end —
the SQL was inspected, the resolution path was not.

## Related

  * `issues/157` — the importer discarding datatypes. Genuinely fixed, and the
    reload sequence used to verify it is what exposed this.
  * `issues/156` — an interrupted bulk import leaves a space unindexed. Same
    family: a supported operation leaving the system in a state nothing detects.
