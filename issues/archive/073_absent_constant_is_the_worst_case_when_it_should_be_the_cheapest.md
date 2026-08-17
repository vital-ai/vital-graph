# Searching for a Value That Is Not There Was the Worst Case

## Status: FIXED — 2026-08-10

> **Buffer-pool review — see `issues/081`. NOT AFFECTED, by arithmetic and by measurement.** A 1 GB pool holds 131,072 pages; every comparator cell reads between 4,350 and 82,724 buffers, so all of them fit with room to spare. The re-run on a 16 GB pool confirms it: warm total 1,444 ms -> 1,745 ms, buffers 1,597,396 -> 1,597,348 (identical), no regressions across 39 cells. The queries that WERE destroyed read 453,180 buffers — 3.5x the whole pool — and none of them are here. Original note follows.
>
> _(superseded)_ At risk: the absent-constant magnitudes. `shared_buffers` was 1 GB on a 64 GB machine against queries touching 400,000+ buffers; raising it to 16 GB moved a comparable query 16,411 ms -> 616 ms with no code change. Plan shapes, row counts and buffer counts are unaffected.

    eq/DateTime, absent value    40,000 ms+ (timeout)  ->  1 ms
    eq/DateTime, present value            1 ms         ->  1 ms  (unchanged)
    eq/Text,     present value           22 ms         -> 22 ms  (unchanged)

## What was happening

`issues/053` recorded `eq`/DateTime as timing out and attributed it to the
fixture: every datetime term in `sp_lead_synth_100k` is distinct (409,017 of
409,017, `issues/050`), so an equality matches nothing and paging "scans the
whole index to find 25 rows that do not exist". Filed as a fixture artifact and
left.

Half right, and the wrong half was load-bearing. The sweep queries
`2020-06-01T00:00:00`, which is not in the term table **at all** — not rare, but
ABSENT. So:

1. `materialize_constants` cannot resolve it, and leaves it unresolved.
2. `substitute_constants` falls back to a scalar subquery over the `_const`
   CTE — which is itself empty — so the SQL contains

       q16.object_uuid = (SELECT term_uuid FROM _const WHERE term_text = '...')

3. That subquery returns NULL, so the comparison is NULL for every row. The
   planner cannot see it is constant-false.
4. Under the ordered-scan fence the plan walks the ENTIRE ordering index
   evaluating a comparison that can never be true.

Proof it is the constant and not the datatype: the identical query shape with a
datetime that DOES exist resolves to a literal uuid and runs in 1 ms. The
difference is one `IN`/`=` operand, not the slot class.

## Why this mattered beyond one cell

Nothing about it is specific to datetimes. Any comparator, any slot class, any
query whose constant is not in the data took the same path — a full ordered scan
to return nothing. **Searching for a value that is not there was the most
expensive thing the system could do, when it should be the cheapest**, and
searching for an absent value is not exotic: it is what a typo, a stale filter,
or an over-narrow query produces. A user who mistypes a lead status got a 40 s
scan; one who typed it correctly got 20 ms.

## The fix

`prune_union.query_is_provably_empty` — a required constant that did not resolve
means the query matches nothing, so `generate_sql` wraps the SQL in
`SELECT * FROM (...) _empty LIMIT 0`. The Limit node stops before fetching a
first tuple, so the subplan never executes, and wrapping preserves the column
names and types the caller expects rather than substituting a degenerate query.

The machinery already existed for one case: `prune_dead_union_branches` has
always removed UNION branches with unresolved constants. This is the same
inference applied to the query as a whole. The check runs AFTER pruning, so a
constant surviving only in a branch just removed does not condemn the query.

### Where it must NOT fire, which is most of the work

"Required" is doing real work in that sentence. Each of these breaks the
inference differently, and getting any wrong is a WRONG ANSWER rather than a
slow query:

| construct | why emptiness does not propagate |
|---|---|
| `OPTIONAL { ?s p <absent> }` | the outer row is still returned, unbound |
| `MINUS { ... <absent> }` | subtracting nothing leaves the left side intact |
| `UNION` | a sibling branch may still match |
| `GROUP` / aggregates | `SELECT (COUNT(*) AS ?n)` over zero rows is **0**, not empty |

`LEFT_JOIN` is handled asymmetrically — the left child is required, the right is
not. Twelve unit tests in `test_provably_empty.py` pin the fires/does-not-fire
boundary, five of them on the must-not side.

## The lesson about the original diagnosis

"The fixture is unrepresentative" was true and stopped the investigation one step
early. The fixture's unique-per-row datetimes are why the constant is absent, but
absence — not uniqueness — is what cost the 40 s, and absence happens on real
data constantly. This is the second time in this effort that a cell filed as a
data-shape problem turned out to be a plan problem; the datetime RANGE cells were
the first (`issues/053`).

## Related

- `issues/053` — the sweep, where this was recorded as a fixture artifact
- `issues/050` — the unique-per-row datetimes, which are why the constant is absent
- `prune_union.py` — the dead-branch pruning this generalises
