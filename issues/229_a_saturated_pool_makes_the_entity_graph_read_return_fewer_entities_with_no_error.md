# A Saturated Pool Makes The Entity-Graph Read Return Fewer Entities With No Error

## Status: FIXED 2026-09-24 — all three links, plus the response can now state a
## shortfall. What remains is a sizing question, not a silence.

## Summary

`GET /api/graphs/kgentities?include_entity_graph=true` answers HTTP 200 with a
correct `total_count` and FEWER entity graphs than were asked for, carrying
nothing to say anything failed, whenever the app's asyncpg pool is saturated.

Found while copying nurture actions into `prod_kg_archive`. A run of 500
entities at `--batch 100 --parallel 10` reported 500 successes and wrote 500 to
its done log; **387 arrived.** 113 were missing and nothing anywhere said so.

## The chain, all four links

**1. The pool runs out.** Ten concurrent workers reading ~60k quads each, on top
of live traffic:

    WARNING - pool state (acquire timed out): size=30 idle=0 min=15 max=30   x113

**2. The failure is a RETURN VALUE, not an exception.**
`execute_sparql_query` deliberately reports it in-band so callers can choose the
HTTP status (`sparql_sql_space_impl.py:2305`):

    return {'results': {'bindings': []}, 'success': False, 'error': str(e),
            'timed_out': is_query_timeout(e)}

Note the exception here stringifies to nothing, so the log line is
`execute_sparql_query(prod_kg) failed: ` with an empty tail — 113 of them,
matching the 113 lost entities exactly.

**3. The batched retriever read `bindings` and ignored `success`**
(`kg_graph_retrieval_utils.py:838`) — the same defect `issues/215` fixed in
`_extract_bindings`, whose comment reads "A FAILED query is not an EMPTY one".
Fixed in one reader, missed in the other:

    results = await self.backend.execute_sparql_query(space_id, query)
    if isinstance(results, dict):
        results = results.get('results', {}).get('bindings', [])
    if not results:
        return {}                      # <- a killed query is now an empty page

**4. Two silent skips above it finish the job** (`kgentity_list_impl.py:364`).
The caller distinguishes `None` (batched fetch raised → fall back to per-entity
retrieval) from a dict (it worked). `{}` is a dict, so THE FALLBACK NEVER RAN —
and the copy loop drops anything missing without a word:

    for uri in entity_uris:
        objs = graphs.get(uri)
        if objs:                       # <- no else, no count, no warning
            entities.extend(objs)

The per-entity fallback path below it has the same shape: `except Exception →
log a WARNING → return None`, and the same `if objs:`. It did not fire here (no
such warnings in the logs), but it would swallow the same way.

## Fixed

Link 3 only. The retriever now raises `SparqlQueryFailed` when `success` is
False, which lets the caller's fallback do what it was written for. Regression
test in `tests/unit/test_batched_entity_graph_failure_is_not_empty.py`,
falsified against the unfixed code (2 of 4 cases fail without it), including the
empty-error-message case, since the pool-timeout exception has no text and an
emptiness check would have missed it.

## Also fixed

**The silent skips now record.** `list_entities_with_graph` collects every URI
asked for and not returned instead of dropping it at `if objs:`, in BOTH the
batched path and the per-entity fallback, and logs at ERROR rather than WARNING
— it is removing an entity from a response that will still say 200.

**`_get_entities_by_uris` was the path that actually lost the 113**, not the
paged listing. Its `except Exception -> return [], 0` is now
`return [], 0, True`, and the failures are aggregated. Found because fixing the
paged path changed nothing for `uri_list`, which is the route a bulk copy uses.

**The response states the shortfall.** `QuadResponse` gained two fields, and
they answer DIFFERENT questions:

  * `missing_uris` — asked for and not returned, for any reason, possibly
    because it does not exist;
  * `incomplete` — whether the shortfall came from a FAILURE and is therefore
    retryable. Three-valued: None means the route cannot say, exactly as
    `has_more`. A caller reading None as False reintroduces this issue.

Verified against a live server: 4 URIs where 2 exist returns
`missing_uris=[the two absent]`, `incomplete=False` — a truthful empty answer,
not a fault. `scripts/archive_kg_entities.py` now raises on a short read rather
than counting entity subjects itself, falling back to that count only when the
server answers `incomplete: None`.

## NOT fixed, and worth a decision

**The pool may simply be too small for this shape.** `size=30 idle=0 max=30`
under 10 concurrent entity-graph reads plus normal traffic. Whether the fix is a
larger pool, a concurrency limit on this route, or backpressure is not
established — only that exhaustion is reachable from an ordinary bulk read.

## Blast radius beyond the copy

Any consumer of `include_entity_graph=true` under load. The portal reaches
VitalGraph through the Resource API, so a short page there reads as "these
entities have no graph" rather than as an error. No evidence either way that it
has happened in portal traffic — the failure leaves no trace in the response,
which is the point of this issue.

## Reproduce

Saturate the pool (10+ concurrent large entity-graph reads) and compare the
distinct entity subjects returned against the `uri_list` requested.
