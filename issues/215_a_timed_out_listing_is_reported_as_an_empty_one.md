# A Timed-Out Listing Is Reported As An Empty One

## Status: OPEN, observed on the dev instance 2026-09-18. Not inferred from
## code — the SAME request was seen returning 0 entities and 25 entities minutes
## apart, both HTTP 200, the difference being only whether the query finished.

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

## What to do

1. **Carry the failure.** `_extract_bindings` should not flatten it — either
   raise on `success is False`, or return it so the caller must handle it.
   Raising is the smaller change and matches the policy `issues/211` settled
   on: refuse rather than degrade to an empty answer.
2. **Decide the HTTP contract deliberately.** The convention here is 200 for
   domain outcomes and non-200 only for server-level errors. A statement
   timeout is the latter, so 500 is defensible — but 200 with an explicit
   error in the body is equally defensible and less disruptive to clients.
   What is NOT defensible is the current 200 with an empty success.
3. **Check the other 16 call sites.** The listing is where it was seen; it is
   unlikely to be the only place the same flattening hides a failure.

## What this does NOT need

Do not "fix" it by raising the statement timeout. The timeout did its job —
it stopped a runaway query. The defect is downstream of it.
