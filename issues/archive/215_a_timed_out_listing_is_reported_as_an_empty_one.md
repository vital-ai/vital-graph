# A Timed-Out Listing Is Reported As An Empty One

## Status: FIXED 2026-09-18. Observed, not inferred — the SAME request was seen
## returning 0 entities and 25 entities minutes apart, both HTTP 200, the
## difference being only whether the query finished. The listing now answers 200
## with `status=QUERY_FAILED`; the other two helpers raise rather than flatten.

**Related:** `issues/211` (the same silence from a different cause — a SPARQL
block that annihilated results and reported success), `issues/188` (a gate
disabled by absence)

## What was observed

    02:44:59  execute_sparql_query(sp_lead_synth_100k) failed:
              canceling statement due to statement timeout
    02:44:59  LIST_ENTITIES timing: ... query=56070ms ... (0 entities, 0 quads)
              GET /api/graphs/kgentities?...&sort_by=...hasObjectModificationDateTime
              HTTP/1.1" 200 OK

and, on the same endpoint and space a minute later once the cache was warm:

    02:45:52  LIST_ENTITIES timing: ... query=2595ms ... (25 entities, 200 quads)
              ... same request ... HTTP/1.1" 200 OK

**Identical status, identical body shape, opposite meaning.** A caller cannot
distinguish "this space has no entities" from "your query ran for 56 seconds
and was killed".

## The mechanism

`execute_sparql_query` reports failure correctly. Its handler returns

    {'results': {'bindings': []}, 'success': False, 'error': str(e)}

which is the domain-outcome convention and is right. The failure is discarded
one layer up, in `kgentity_list_impl.py:56`:

    def _extract_bindings(result) -> list:
        if isinstance(result, dict):
            return result.get('results', {}).get('bindings', [])
        return []

It reads `bindings` and never looks at `success`. An empty list for "no rows"
and an empty list for "the query was killed" are then the same value, and
`ListEntitiesResult` has no field to carry the difference even if a caller
wanted it:

    @dataclass
    class ListEntitiesResult:
        entities: List[GraphObject]
        total_count: int

The endpoint builds its `QuadResponse` straight from `result.entities` with no
success check. **17 call sites use `_extract_bindings`, across four modules,
and NONE of them checks `success`.**

## Why this one stings

The same endpoint, forty lines below the silent failure, is careful about
exactly this distinction for a lesser field:

    # The guard matters. A non-empty page reported with total_count == 0
    # means the count was not computed, and answering False there is the
    # exact defect this replaces — a confident No standing in for "no
    # one counted". None says so.

`has_more` refuses to state a confident False when nobody counted. The entity
list, in the same function, states a confident empty when nobody succeeded.

## Not the same as the space being slow

The slowness is real and has its own cause — `sp_lead_synth_100k` is excluded
from maintenance, so it has no `entity_prop_sort`, the fast path declines and
the fallback pays 800k buffers of per-row term lookups for 200 rows
(`plan_shape` reported `ratio: 500.0`, `max_loops: 100000`, twice). That is a
fixture-shaped problem on a fixture space and it is not what this issue is
about.

This issue is that the FAILURE was invisible. A slow query that reports being
slow is a tuning question. A killed query that reports an empty result is a
correctness question, and it would read identically on a space that is
genuinely empty.

## The fix

**`OperationStatus.QUERY_FAILED`**, the read-side counterpart to
`STORE_FAILED`. Its ABSENCE is why the bug existed: a failed read had no status
to land on except `EMPTY`, and `EMPTY` is a success status. It sits outside
`_SUCCESS_STATUSES`, so `success` derives to False and the pair cannot be
emitted inconsistently.

**`SparqlQueryFailed`** (`utils/db_retry.py`), RAISED rather than returned so
it cannot be flattened again by accident. It carries the error text, and the
test asserts the text survives — an error the caller cannot read is barely
better than the silence it replaced.

**All three `_extract_bindings` copies** refuse to flatten. They were fixed
together because they are three copies of one function with one flaw, and
fixing one is how this comes back.

**The listing answers 200 with the failure stated**: `status=QUERY_FAILED`,
`message`, empty results, `has_more=None`. 200 rather than 500 because that is
the domain-outcome contract every other fault on these routes already uses.

## Where the contract applies, and where raising is right

The entity listing was fixed first because it is the one that was OBSERVED
failing. Finishing the job, 2026-09-18, produced a boundary worth stating
rather than a blanket rule.

**LISTINGS get 200 with the failure stated.** They return a status-bearing
envelope, so they can. Both are now done:

    kgentities  _list_entities   -> QuadResponse(status=QUERY_FAILED, message)
    kgtypes     _list_kgtypes    -> QuadResponse(status=QUERY_FAILED, message)

The kgtypes one matters more than its size suggests. `issues/100` was six
KGType searches returning nothing, and what made it take weeks was precisely
that nothing distinguished "found none" from "failed" — this endpoint, that
symptom.

**WRITE paths raise, and should.** `get_existing_object_uris` and
`count_objects` return a `List[str]` and an `int`; they have no envelope to put
a status in, and their caller is the DELETE path
(`impl_utils.get_existing_quads_for_uris`). A read that fails while resolving
what to delete must abort loudly, not report success with an empty list — that
is `issues/023`'s rule about a widened delete, arriving from the read side.

So the unevenness is not laziness: a raise IS the contract where there is
nothing to carry a status, and the endpoints that can carry one now do.

## What this does NOT need

Do not "fix" it by raising the statement timeout. The timeout did its job —
it stopped a runaway query. The defect is downstream of it.
