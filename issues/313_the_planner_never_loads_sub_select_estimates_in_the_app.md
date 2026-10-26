# 313 — In the app, the planner never loads its sub-select estimates (a json codec), so range and IN filters are never driven

## Status: FIXED and VERIFIED in the app at scale, 2026-10-26 (45b83c43). Production picks it up with the next deploy.

## Defect

`qcard.load_sublinks` prices each leaf's `col IN (SELECT ... FROM term WHERE ...)` filter: a range
criterion, a slot-sort fast path. It does that by running `EXPLAIN (FORMAT JSON)` and parsing the
result with `json.loads`.

The server's connection pools register a `json` / `jsonb` codec on every connection
(`sparql_sql_db_impl._init_conn`), so there the value arrives already decoded, as a list.
`json.loads(list)` raised `TypeError: the JSON object must be str, bytes or bytearray, not list`.
`planner_ext` caught it as `declined: qtree_derived_stats`, and the planner carried on WITHOUT any
sub-select estimate.

Consequences, wherever the planner (the plugin path) runs in the app, production included:
- `_pick_driver` never found a sub-select to drive a unit from. The case that motivated driving
  (lead 100k, `MQLRating >= 99.9`: 3.3 s undriven against 31 ms for today's SQL) ran undriven.
- A unit holding such a filter got step-rows advice that PostgreSQL could not always match.
  This was the API suite's `advice not applied: u0.q2 rows` on a document query, once the suite
  built statistics for its spaces.

Every script that measured the planner (`contract.py`, the corpus runs) used plain asyncpg
connections, which return the JSON as text. They never saw the failure.

## Fix

- `qcard.py`: accept the decoded value (`v if isinstance(v, (list, dict)) else json.loads(v)`).
- `contract.py` (test_scripts_internal) registers the app's codecs (`_init_conn`) on its
  connection, so the corpus measures what the app runs.

## Verification

- The API suite with statistics built (`VG_TEST_BUILD_STATS`) must not fail on advice for this
  shape.
- Then compare `qtree_derived_stats` declines in the app log: there should be none.
- At scale: a range-criterion KGQuery in the app (lead 100k) should show a driven unit
  (`bgp u0 steps(r_q… q…)`).

## Verified 2026-10-26

**API suite, with statistics built** (`12ee0eb1`):
- 0 failures, 712 queries planned;
- no `qtree_derived_stats` declines in the app log.

**Through the app on lead 100k** (`high_rated_edge_count`, an MQLRating >= 65 criterion over
the edge chain):
- the slot unit is driven from the range sub-select: `bgp u0 steps(r_q16 q16 q15)`;
- 690-920 ms warm (12.8 s on the first, cold run after a restart).

The contract corpus measures the same query at 0.9-5.2 s planned against 13-22 s for today's
SQL.
