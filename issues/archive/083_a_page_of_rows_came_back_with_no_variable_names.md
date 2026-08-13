# The Unsorted Criteria Query Returned Rows With No Variable Names

## Status: FIXED 2026-08-12

The core KGQuery shape — entity type + frame/slot criteria, no sort — returned
**nothing** through the API, at every offset, while the SQL underneath returned
the correct rows.

    SQL executed                          13 rows, all correct
    API response      status=FOUND  total_count=13  entity_uris=[]

## Cause

`generate_sql` builds `var_map` by walking the TypeRegistry and **skipping any
entry whose `sql_name` is unset**:

    for sparql_name in ctx.types.all_vars():
        info = ctx.types.get(sparql_name)
        if info and info.sql_name:
            var_map[info.sql_name] = sparql_name

`_rows_to_sparql_bindings` then converts each row by iterating `var_map`. An
empty `var_map` produces one binding per row with **no keys at all** — 13
bindings, 13 empty dicts — and the endpoint's `binding.get('entity')` finds
nothing.

The registry was empty because the paging emitters build their own outer SELECT
instead of delegating to `emit_bgp`, and `emit_bgp` is what registers a
variable. `_emit_two_phase` even reads the registry:

    info = ctx.types.get(key)
    sn = info.sql_name if info and info.sql_name else key

The fallback fired on every one of these queries — which is why the columns were
named `entity`, `entity__uuid` rather than `v0`, `v0__uuid`. The fallback made
the SQL correct and readable and hid the missing registration completely.

Fix: `_register_projection` in `emit_slice.py`, called where the emitter builds
its projection, setting both the entry and its `sql_name`.

## Which shapes were affected

Measured before the fix, `var_map` size against rows the SQL returned:

    entity + frame criteria, unsorted, offset 0     var_map=0   13 rows
    entity + frame criteria, unsorted, offset 5     var_map=0    8 rows
    entity + frame criteria, SORTED,   offset 0     var_map=6   13 rows
    entity type only,        unsorted, offset 0     var_map=1   20 rows
    plain SELECT ?s ?p ?o                           var_map=3    5 rows

**Frame criteria + no sort** — precisely the shape that takes the two-phase
paging path, and precisely the shape all the recent performance work has been
tuning. Adding a sort avoided it, which is why it could sit unnoticed.

## Why nothing caught it

Every test asserts one level too low. The perf benches assert `len(rows)` from
`conn.fetch`, and the plan tests assert SQL text — the SQL and the rows are
CORRECT here, so both pass. Nothing ran `_rows_to_sparql_bindings` with the
generator's own `var_map`, which is the step the server actually performs.

`tests/integration/test_kgquery_bindings_are_named.py` closes that: it goes
through `sparql_execute`, the fixture that performs the identical conversion, and
asserts the projected variable is NAMED rather than merely present.

The API contributed by making the failure invisible: `issues/082` — no KGQuery
path checks the `success` flag, so "backend broken" and "nothing matched" and
"rows returned but unnameable" are one response.

## What it cost, which is the argument for the test

Several steps went into A/B-testing code versions across two servers and a git
worktree, on the theory that a recent change had regressed it. It had not — the
bug is older than the window I bisected. Two of those steps were wasted on
invalid experiments (a local server that could not resolve the sidecar; a file
revert that could not affect an already-running server). The load driver's new
guard is what surfaced it in the first place.

## Found alongside, and NOT fixed by this

The same test proved `issues/078`'s shipped fix returned incorrect pages, and it
was reverted. Deep paging is O(offset) again, and correct.

## Related

- `issues/082` — the failure was unreportable, which is why this took so long.
- `issues/078` — reverted on evidence from the same test.
- `issues/075` — D1; the ordering question underneath both.
