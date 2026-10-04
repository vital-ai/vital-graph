# 259 — A query that times out leaves no SQL and no plan, so the worst case is the least diagnosable

## Status: FIXED 2026-10-04 (`027a07d1`, released in 0.0.44). A query that fails now leaves one
## WARNING `failed_query` line with its SPARQL, its whole generated SQL, the
## SQL fingerprint, the stage it stopped in, the timing of every completed phase
## and the plan decisions with their `stage_ms`. See "As built" at the end.

## What is and is not recorded

Measured against production's `/ecs/vitalgraph-prod` for the two cancellations of
2026-10-03 (`issues/258`):

| | recorded |
|---|---|
| that a timeout happened | **yes** — ERROR, from two loggers independently |
| which space | **yes** — `execute_sparql_query(the_actions_space) failed: …` |
| which user | yes, on a separate INFO line per query |
| when | yes |
| **the SPARQL text** | **NO** |
| **the generated SQL** | **NO** |
| **the plan** | **NO** |
| **the per-stage timings** | **NO** |

The three lines a cancellation produces are these, and they are the whole record:

    ERROR  execute_sparql_query  execute_sparql_query(the_actions_space) failed:
                                 canceling statement due to statement timeout
    ERROR  _execute_query        SPARQL query failed: canceling statement due to …
    INFO   _execute_query         ENDPOINT: Backend returned result: {'results':
                                 {'bindings': []}, 'success': False, 'error': …}

## Why — two mechanisms, both conditional on COMPLETION

1. **`report_slow_query` fires only when a query finishes.** It is reached after
   execution returns, so a statement cancelled by `statement_timeout` raises past
   it. Everything that log carries — `total_ms`, `gen_ms`, `exec_ms`,
   `acquire_ms`, `stage_ms` (including `load_pair_stats`, `load_quad_stats`,
   `ensure_edge_table`), `plan_shape`, `sql_excerpt`, `sql_fingerprint`,
   `disproportionate`, `plan_decisions` — is unavailable for exactly the queries
   that most need it.
2. **The query text is logged at DEBUG and DEBUG is off for that logger.**
   `sparql_query_endpoint.py:80`:

       self.logger.debug(f"Query: {query[:200]}{'...' if len(query) > 200 else ''}")

   Confirmed absent in production: **zero** log lines from
   `sparql_query_endpoint` at DEBUG in a 2 h window, while the INFO line beside
   it (`Executing SPARQL query in space '…' for user '…'`) is present. It is also
   truncated to 200 characters, which would not have held either query in
   `issues/258`.

## What this cost, concretely

`issues/258` needed the two queries' text supplied by hand and the SQL
regenerated on a LOCAL space, because production had kept neither. The
diagnosis — an unbound `GRAPH ?g` estimating one row — came from a local
`EXPLAIN`, not from the incident. A second occurrence on a different shape would
start from zero again.

It also produced a wrong argument, which is the sharper cost. "No slow query in
48 h contains `EXISTS`" was offered as evidence that the reported `FILTER
EXISTS`/`FILTER NOT EXISTS` queries were not the problem. **The evidence was
void**: cancelled queries never reach that log, so their absence from it says
nothing. An instrumentation gap that makes a reviewer confidently wrong is worse
than one that merely leaves them uninformed.

## Scale — this is about the next one, not a backlog

Across the full 72 h retention there are **2** statement-timeout cancellations,
both the manual probes of `issues/258`, and the ALB reports **zero** target or
ELB 5xx over the same window. So nothing is being lost at volume. The case for
fixing it is that the next timeout should be diagnosable from its own log line
rather than from a reconstruction.

## What to change

Both are small and neither needs a new mechanism.

1. **Log the query text at INFO on FAILURE.** The string is already formatted at
   `sparql_query_endpoint.py:80`; the failure path at :123 has `query` in scope.
   Untruncated, or truncated far above 200 characters — a 200-char cap excludes
   the realistic shapes.
2. **Emit what is already in hand when the statement is cancelled.** By the time
   the cancellation is caught, generation has completed, so `sql_fingerprint`,
   `stage_ms` and the generated SQL all exist. Emit them from the cancellation
   path before re-raising, in the same shape `report_slow_query` uses, so one
   parser reads both.

A plan is NOT available — the statement never finished, and asking PostgreSQL for
one would re-run it. `sql_fingerprint` plus the SQL is enough to obtain a plan
deliberately afterwards, which is what had to be done by hand here.

## What NOT to do

- **Do not lower `statement_timeout` to make these fail faster.** The 60 s cap is
  `issues/136`'s and is load-bearing elsewhere; and a faster failure with no
  content is still no content.
- **Do not turn on DEBUG for the endpoint in production.** That logs every query,
  not the failing ones, on a path handling thousands an hour — and `09c8280`
  moved per-request audit lines TO debug deliberately, which this would undo.
- Do not route the text through the `slow_query` logger by lowering its
  threshold. The threshold is not the issue; completion is.

## Verify after fixing

- a deliberately cancelled query (e.g. `issues/258`'s Q2 against
  `the_actions_space`, unbound) leaves the SPARQL and the generated SQL in the
  log, at INFO or above
- the text is not truncated below the length of that query
- a SUCCESSFUL query does not start logging its text at INFO — the change is to
  the failure path only, and the request volume is why
- `report_slow_query`'s own behaviour is unchanged for completing queries
- a cancelled query's record carries `sql_fingerprint`, so the plan can be
  obtained afterwards on demand

## Neighbours

- `issues/258` — the defect this gap obscured, and the reason it is filed first:
  without this, the next occurrence of `258`'s shape is as opaque as the last.
- `issues/228` — ends in the same `canceling statement due to statement timeout`
  surfacing as an HTTP 500, and records "**what made that one execution exceed
  60 s is NOT established**". That sentence is this issue, observed a month
  earlier and attributed to the query rather than to the instrumentation.
- `issues/253` — the write path's answer to the same question: `_phase_breakdown`
  records marks OUTSIDE the `try` precisely because "the losses this exists to
  explain all END IN AN EXCEPTION, so a breakdown logged only on the happy path
  would miss every one of them". The read path has not had that correction
  applied, and the reasoning transfers verbatim.

## As built (2026-10-04, `027a07d1`, 0.0.44)

`plan_shape.report_failed_query`, called from the `except` of
`SparqlSQLSpaceImpl.execute_sparql_query`, so it covers EVERY caller of the
query path — the SPARQL endpoint, the KG endpoints, internal reads — not only
`sparql_query_endpoint`. That is why change 1 above (log the query text at INFO
in the endpoint's failure path) was not made separately: the backend record
carries the text, untruncated to 20,000 characters, for all of them.

- Same JSON shape as `slow_query` — `space`, `sql_fingerprint`, `timing`,
  `sparql`, `plan_decisions` — so one parser reads both; plus `stage`
  (compile / acquire / generate / resolve / execute / convert), `timed_out`,
  `error`, and the SQL itself up to `VG_FAILED_QUERY_SQL_CHARS` (default
  100,000), not the slow-query excerpt: the point is to obtain the plan
  afterwards.
- The phase marks live OUTSIDE the `try`, as `issues/253` did for the write
  path, so a failure reports the phases that completed and how long the failing
  one ran (`<stage>_ms_until_failure`, `failed_after_ms`).
- Any failure, not only a timeout; `timed_out` says which.
- No plan, as decided: the statement never finished.
- Successful queries are unchanged: nothing new is logged for them.

**Verified live** on the vg test stack: the app restarted with
`VITALGRAPH_READ_STATEMENT_TIMEOUT_MS=1`, a SPARQL query sent through the API,
and the container log carried `failed_query` with the probe's SPARQL, the full
10,973-character SQL, `sql_fingerprint`, `stage=execute`, `timed_out=true`,
per-phase timings and `stage_ms`; then restored. Unit:
`tests/unit/test_a_failed_query_leaves_its_sql.py` drives `execute_sparql_query`
with a connection that raises `QueryCanceledError`: 2 of 3 FAIL without the fix
(the third is the guard that a successful query logs no text).

