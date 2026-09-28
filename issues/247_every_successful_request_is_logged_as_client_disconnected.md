# 247 — Every successful request is logged as "client disconnected"

## Status: FIXED 2026-09-28, same day it was measured. The middleware now
## tracks response COMPLETION and treats a close after it as what it is.
## Original report below.

## The test that matters is at the ASGI layer, and that is not incidental

The first three tests written for this went through `TestClient` — and PASSED
WITH THE FIX REVERTED. `TestClient` never sends `http.disconnect`, so they never
entered the `hung_up` branch at all. They assert something worth asserting (the
happy path logs nothing, a real deadline still logs) but they cannot see this
defect.

`TestDisconnectAfterAResponseIsNotAnAbandonment` drives the middleware directly
with a hand-rolled receive/send, delivering the disconnect where production
delivers it: after the whole response has gone out, while the handler is still
winding down. Reverted, it fails with the assertion message. That is the
difference between a test and a decoration.

## Original report — diagnostics defect, measured on production 2026-09-28.
## ~91,800 misleading INFO lines a day. Not a correctness bug: no request is
## harmed, and nothing relies on post-response work. But the signal it destroys
## is the one you would use to find requests that ARE being abandoned.

## The measurement

One request to production, which succeeded — `hits = 1`, `200 OK` in the access
log — produced BOTH of these:

    INFO: 10.1.2.31:22484 - "GET /api/registry/identifiers/lookup?namespace=...
          HTTP/1.1" 200 OK
    request bounded: GET /api/registry/identifiers/lookup — client disconnected

Nothing disconnected. The client got its answer.

Volume on production, prod streams only, 24h:

    "client disconnected"   91,802
    "deadline exceeded"          0

and over 6h the distribution is simply the busiest endpoints:

    14,842  GET  /api/registry/identifiers/lookup     (measured at 60-90ms, all 200)
     2,804  GET  /health
     1,903  GET  /api/graphs/kgentities
       664  POST /api/graphs/kgqueries
       514  POST /api/graphs/sparql/query

`/health` is the tell. An ALB health check does not abandon requests 2,804 times
in six hours, and a 70ms lookup does not get given up on 14,842 times.

## Why it fires

`request_bounds.py` tracks the START of a response and never its END.
`wrapped_send` sets `responding` on `http.response.start`; there is no
corresponding signal for the last body chunk. So phase 2:

    if first_byte in done and handler not in done and gone not in done:
        done, _ = await asyncio.wait({handler, gone}, return_when=FIRST_COMPLETED)
    if handler in done:
        ...
        return
    hung_up = gone in done
    reason = "client disconnected" if hung_up else "deadline exceeded"

A normal HTTP exchange reaches this: the handler sends the whole response, the
client reads it and CLOSES THE CONNECTION — which is what a client is supposed
to do — and `gone` wins the race against a handler coroutine that has delivered
everything and is merely winding down.

**The label is not false, it is unhelpful.** The client did disconnect. It
disconnected because it was finished. The middleware cannot tell that from a
client that walked away mid-query, because it never learned the response was
complete.

## What it costs

**The metric is unusable, which matters because it is the RIGHT metric.**
Abandoned work is worth knowing about — it is wasted database time and, on a
write, a client that does not know what happened. Today every genuine
abandonment is buried under ~91,800 daily false positives, and a query for
"client disconnected" answers "how many requests did you serve".

This was hit directly: a search of these logs for a reported `ReadTimeout`
produced "21,527 abandoned requests in 6 hours, every one a client giving up",
which was wrong in every part. The single controlled request above is what
disproved it.

**A pointless cancel.** The handler is cancelled after it has already sent its
response. Harmless TODAY — `BackgroundTasks` is imported in
`vector_indexes_endpoint.py` and `add_task` is never called anywhere, so there
is no post-response work to kill — but it is a loaded gun: the first endpoint to
schedule work after its response would have it cancelled on every normal request.

## The fix

Track response COMPLETION, and treat a close after it as what it is.

    response_done = asyncio.Event()

    async def wrapped_send(message):
        if message["type"] == "http.response.start":
            responding.set()
        await send(message)
        if (message["type"] == "http.response.body"
                and not message.get("more_body", False)):
            response_done.set()

and in the `hung_up` branch, return quietly when `response_done.is_set()` rather
than cancelling and logging. The handler is finishing; let it.

Keep `deadline exceeded` exactly as it is — that path is correct and, at zero
occurrences in 24h, evidently not firing spuriously.

## What NOT to do

**Do not just lower the log level.** DEBUG would hide the genuine abandonments
along with the noise, and the genuine ones are the reason this log line exists.

**Do not remove the disconnect handling.** Cancelling a read whose client has
gone is correct and deliberate (`issues/044`): it stops burning CPU, a pool slot
and a database backend for a response nobody will read. Only the
ALREADY-RESPONDED case is wrong.

## Verify after fixing

    one successful request  ->  access log 200, and NO "client disconnected"
    /health over an hour    ->  0 occurrences (it is never abandoned)
    a real abandonment      ->  still logged; `curl --max-time 1` against a
                                slow query should produce exactly one
