# A Failed Backend Query Is Reported As A Successful Empty Result

## Status: FIXED 2026-08-12

    dead backend, before    HTTP 200  status=FOUND  total_count=0  uris=[]
    dead backend, after     HTTP 500  "[Errno 8] nodename nor servname ..."

    genuine miss, before    status=FOUND   (enum defines FOUND as ">= 1")
    genuine miss, after     status=EMPTY   success=True

All 28 call sites now go through `_checked_query`, which raises
`BackendQueryError` when the backend reports its own failure. Routing them
through one wrapper rather than adding 28 checks is deliberate: the bug was a
MISSING check, and a missed site is silent and looks exactly like an empty match
set. A unit test asserts no raw `execute_sparql_query` remains in the endpoint.

**A fourth thing was wrong, found only by checking end to end.** With the
endpoint returning `EMPTY` correctly, the client still reported `FOUND` — every
`from_raw` copied the payload and dropped `status` and `message`, so the typed
response fell back to its default. A status the caller never receives is not a
status. Fixed in all four converters.

`query_quads` now raises instead of returning the failure's empty list.

`execute_sparql_query` already reports its own failures. On any exception it
returns

    {'results': {'bindings': []}, 'success': False, 'error': str(e)}

**No KGQuery path ever reads `success` or `error`.** `grep -n "success"
vitalgraph/endpoint/kgquery_endpoint.py` matches NOTHING. The endpoint reads
only `results.bindings`, finds the empty list the failure produced, and builds a
normal response from it:

    results = await backend.execute_sparql_query(space_id, sparql_query)
    ...
    if results and results.get("results") and results["results"].get("bindings"):
        # ← failure took the same branch as a genuinely empty match set

`_extract_total_count` does the same thing and returns `0`.

So a backend that is completely unreachable produces:

    status      = OperationStatus.FOUND
    total_count = 0
    entity_uris = []
    HTTP 200

## Two contract violations, not one

`OperationStatus` defines these itself, in `vitalgraph/model/result_status.py`:

    FOUND = "found"   # read returned >= 1
    EMPTY = "empty"   # read matched nothing (still success=True)

1. **A failure is reported as a success.** There is no status in the enum for
   "the query did not run", and the caller cannot distinguish "no leads in
   California" from "the query engine is down".
2. **Even a genuine miss is wrong.** Zero results is `FOUND`, which the enum
   defines as `>= 1`. `EMPTY` exists for exactly this and is not used here.

This is not the HTTP-200-for-domain-outcomes convention. That convention is
about *domain* outcomes carrying a truthful status in the body. This returns an
untruthful status — a backend outage is not a domain outcome.

## How it was found, which is the argument for fixing it

While adding KGQuery operations to the load driver, a local server returned
`total=0, uris=[]` for a criterion that demonstrably matches 13 organizations.
Several steps were spent A/B-testing code versions across two servers and a
worktree, because the API's answer was indistinguishable from a real empty
result. The actual cause was in the server log the whole time:

    execute_sparql_query(kg_load_test) failed:
        [Errno 8] nodename nor servname provided, or not known

The Jena sidecar hostname did not resolve. **Every** query failed; every one was
reported as a successful empty read. Nothing in any response indicated it.

That is the cost: a whole class of infrastructure failure is invisible from the
API, and an investigation is sent looking for a data or code explanation for it.

## Why this matters more than a normal error-handling gap

* **The load driver reports green against a dead backend.** It counts a response
  as successful unless `is_success` is `False`; these responses say `FOUND`. A
  full run would publish healthy latency percentiles for queries that never
  executed — fast ones, since failing costs nothing. Any perf number taken this
  way is meaningless and looks fine.
* **Every performance measurement through the API has the same exposure.** A
  timing of a query that silently did not run is a timing of the error path.
* **It defeats monitoring.** Nothing distinguishes an outage from quiet traffic.

## Fix

**The fix is small: check the flag at each call site, return a distinct status
for a backend fault, use `EMPTY` for a genuine miss, and audit `query_quads`,
which drops the flag too. Highest leverage per line in the list, because it is
the bug that hides other bugs.**


1. Check `success` at every `execute_sparql_query` call site in
   `kgquery_endpoint.py` and propagate the failure as a distinct status rather
   than an empty page. A backend fault is a server-level error, not a domain
   outcome, so this is one of the cases that is NOT a 200.
2. Return `EMPTY` rather than `FOUND` when a read matches nothing, per the
   enum's own definitions.
3. Audit the other consumers. `query_quads` has the same shape and drops the
   flag on the floor:

       result = await self.execute_sparql_query(space_id, sparql_query)
       return result.get('results', {}).get('bindings', [])

4. Add a load-driver guard so this cannot silently pass again — a response that
   reports a non-zero total while returning no rows at offset 0, or that reports
   a non-success status, must be counted as a failure. **Done** as part of
   adding the query operations; the driver would otherwise have been the tool
   least able to detect the condition it is most affected by.

## A second shape the guard surfaced — ATTRIBUTED AND FIXED, `issues/083`

First driver run with the guard in place, against the dev container on `:8001`:

    kgquery_page1        24 reqs   24 failures
    kgquery_deep_page     7 reqs    3 failures   (exactly its offset=0 draws)
    kgquery_sorted        8 reqs    0 failures
    sparql_select         7 reqs    0 failures

The unsorted first page reports `total_count=13` and returns **no rows**, while
the same query sorted returns all 13. So the count and the page disagree, which
is the second condition the guard checks.

**Resolved: it was a real, current defect.** Written up here as unattributed
because the only server that could run the query was a stale image. Once a
current server was rebuilt it reproduced immediately, and the cause was
`var_map` coming back empty for the two-phase shape, so every row was converted
to a binding with no keys — correct SQL, correct rows, nothing named. Fixed in
`issues/083`.

What the run does establish: the ops exercise the paths, and the guard converts
a silent anomaly into a visible failure rate. Before it, this run would have
reported 0 failures and published a healthy 42 ms p50 for a page returning
nothing.

## Related

- `issues/044` — bounded requests; same theme of a failure that does not surface.
- `load_test_scripts/load_test.py` — where the driver-side guard lives.
