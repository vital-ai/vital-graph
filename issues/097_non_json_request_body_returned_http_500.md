# A Non-JSON Request Body Returned HTTP 500 on Every Endpoint

## Status: FIXED 2026-08-16 — found by running the SPARQL 1.1 Protocol suite

Any request carrying a body whose `Content-Type` was not JSON, to any endpoint
expecting a pydantic model, returned **HTTP 500 Internal Server Error** instead
of 422.

    curl -H 'Content-Type: application/x-www-form-urlencoded' \
         -d 'query=ASK {}' '.../api/graphs/sparql/query?space_id=X'
    -->  HTTP 500

## Mechanism

`vitalgraph/main/main.py` installs a custom `RequestValidationError` handler,
added to log validation failures in detail. It returned:

    JSONResponse(status_code=422, content={"detail": exc.errors()})

When a request BODY fails validation, pydantic v2 puts the offending input in
`error["input"]`. For a body whose Content-Type is not JSON, that input is raw
`bytes`. `json.dumps` cannot serialise bytes, so **the handler itself raised**,
and a raising exception handler produces a 500.

FastAPI's own default handler wraps the errors in `jsonable_encoder` for exactly
this reason. This one was written to add logging and dropped it.

## Why it survived

Every ordinary path was correct:

| request | status |
|---|---|
| JSON body, wrong field | 422 |
| malformed JSON | 422 |
| missing query parameter | 422 |
| **non-JSON Content-Type** | **500** |

Writing a test for this handler means sending JSON, and sending JSON works. The
failure needed a request no test in the repo had ever made — until a
specification suite made 22 of them.

## Blast radius

Not a SPARQL issue. It applied to **every endpoint taking a request model**. A
caller's mistake was reported as a server fault, which pages whoever watches the
error rate and buries real 500s in noise. It also contradicts this project's own
rule that domain outcomes return 200/4xx with the outcome in the body and
non-200 is reserved for genuine server-level failures.

## The fix, and the half-fix that came first

Adding `jsonable_encoder` took the 500s from 22 to 2. The remaining two were
`bad_query_non_utf8` and `bad_update_non_utf8`: the encoder's default rule for
bytes is `o.decode()`, which assumes UTF-8 and raises `UnicodeDecodeError` on a
UTF-16 body — inside the handler written to prevent the 500.

Rebuilding and re-measuring is what caught that. Asserting the fix would not
have.

`_safe_errors()` now takes the raw input out of the encoder's path: decoded if
it is text, described if it is not (`<24 bytes, not valid UTF-8>`), truncated
either way. The truncation is worth having independently — echoing a whole
request body back to the caller can be large, and can contain whatever they
sent, including credentials put in the wrong field. `loc`, `msg` and `type`,
which are what a caller needs to fix the request, are untouched.

## Verification

    first run    2/34 pass, 22 × HTTP 500
    encoder fix  10/34 pass, 2 × HTTP 500
    final        12/34 pass, 0 × 5xx

- `tests/unit/test_validation_error_handler.py` — 19 cases covering UTF-8,
  UTF-16, binary, oversized and non-serialisable `ctx` inputs. Verified to FAIL
  against the pre-fix code.
- `tests/conformance/test_dawg_protocol.py::test_no_server_faults` — asserts no
  SPARQL Protocol request produces a 5xx, for all 34. A 422 is a PASS there;
  "we do not accept that content type" is an honest answer, "Internal Server
  Error" is not.

## Related

- `planning/planning_sparql_features/dawg_conformance_coverage.md` §6.1
- The remaining 22 protocol failures are honest gaps, not crashes; one group of
  them needs a 200-vs-4xx architectural decision
