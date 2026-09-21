# A JSON Criterion Value Cannot Bind Against A Typed Column

## Status: FIXED 2026-09-21 (`0dd38a48`, `f3ce3eee`; the `entity_prop_sort` twin
## in `ed165956`). Dates and floats arrive from the API as JSON and were bound
## straight against TIMESTAMP and NUMERIC columns, so asyncpg refused them and
## both callers caught the error and declined. Answers stayed correct; the fast
## path was simply never reached from the API that feeds it.

**Related:** `issues/222` and `issues/223` (the other two defects in this same
function), `issues/172` (two fast paths each declining the other's input)

## What was seen

In production, once per dated listing, from the `entity_prop_sort` twin:

    WARNING - prop_sort page failed, caller will fall back
    asyncpg.exceptions.DataError: invalid input for query argument $4:
        '2026-06-23T14:00:00.000Z' (expected a datetime.date or
        datetime.datetime instance, got 'str')

    WARNING - prop_sort count failed, caller will fall back
    ... the same, from the count ...

The slot-filter form is identical at `$5` and is caught at DEBUG, so it never
appeared anywhere at all.

## The mechanism, which is the same in three places

`SlotCriteria.value` is `Optional[Any]` and the criteria come from JSON, so a
date is a `str` and a number is an `int` or a `float`. The table stores three
lanes — `value_text TEXT`, `value_num NUMERIC`, `value_dt TIMESTAMP`.

asyncpg types each parameter from the statement PostgreSQL describes back. Bind
`value_dt = $n` and $n IS a timestamp as far as the driver is concerned, so a
string is rejected before the query is ever sent. Write `$n::timestamp` and the
cast does the same thing more explicitly. Either way the DataError is raised at
bind time, the blanket `except` catches it, the path declines, and the query
falls to the join — 13.9 s against 46.9 ms for the slot filter, and a SPARQL
walk for the property listing.

Three sites, one cause:

    fast_prop_sort.build_page_sql        $n::timestamp   range on a listing
    fast_prop_sort.fast_entity_prop_count  $n::timestamp (its own inline copy)
    fast_slot_filter._probe              = $n            equality on a slot

and `fast_frame_prop_sort` carried a fourth copy of the first.

The consequence is that `created_after` / `created_before` / `modified_after` /
`modified_before` had NEVER been served by `entity_prop_sort`, in any space,
while every other filter on the same table was — and no dated or float-valued
slot equality had ever been served by `entity_slot_sort`.

## Why nothing noticed for so long

A decline and a crash-then-decline are indistinguishable from outside: both end
in the slow path returning the right answer. The only symptom was latency, on
precisely the queries a user is least surprised to find slow (a date range over
a big listing).

And the tests never asked. `test_count_and_page_move_together` has five shapes
and every one filters on `status` or sorts by name; not one carries a date.

## The fix is a SQL function, not a Python parse

    value_dt = vitalgraph_iso_to_utc($n)      -- $n stays TEXT

Two things this buys that a `datetime.fromisoformat` in Python would not:

**It cannot drift from the column.** `value_dt` IS
`vitalgraph_iso_to_utc(term_text)` — `term.dt_val` is a STORED generated column
over that function, normalised to UTC. Reading the bound with the same function
is the only form that cannot disagree with the values it is compared against.
`::timestamp` IGNORES the offset, so a `2026-06-23T14:00:00+05:00` bound would
have compared as 14:00 UTC against rows stored at 09:00 — a filter silently five
hours wide, wrong even if a `datetime` had been passed.

**It costs one call per query, not one per row.** The function is IMMUTABLE, so
it folds into the index condition. Measured on a 500,000-row scratch table:

    Index Cond: (dt_val = '2026-06-23 14:00:00'::timestamp)   custom plan: folded at plan time
    Index Cond: (dt_val = vitalgraph_iso_to_utc($1))          generic plan: still the index cond
       Index Searches: 1   Heap Fetches: 0   Execution Time: 0.167 ms

One evaluation, ~3.6 us (200,000 iterations, loop baseline subtracted), flat in
the table size. Nothing is parsed per row at query time in either direction: the
text was parsed once, at insert, into eight bytes.

Numbers coerce to `Decimal` in Python instead, because there is no normalisation
POLICY for a number — only a type — so there is nothing to keep in one place.
A non-finite `Decimal` (`NaN`, `inf`) declines: it is a valid value that matches
nothing, which is not an answer.

## The equality case needed one thing the range case did not

A range on a listing compares two normalised instants and that is all. An
equality has to decide whether `2026-06-23T14:00:00Z` equals
`2026-06-23T14:00:00` — and XSD says a timezoned and an untimezoned dateTime are
INCOMPARABLE, since the answer depends on an offset nobody supplied.
`vitalgraph_iso_to_utc` reads an untimezoned value AS IF UTC, so normalising
alone would declare them equal: a wrong MATCH, not a missing one.

The general pipeline already answers this, in `filter_pushdown._eq_cond`, with a
timezone-agreement guard. The probe now carries the same one, reading
`value_text` — which holds `term_text` for every row whatever its lane — so it
costs no join, and it runs only over rows the index condition has already
narrowed to that instant:

    stored                       bound 2026-06-23T14:00:00.000Z
    2026-06-23T14:00:00Z         match      -- same instant
    2026-06-23T09:00:00-05:00    match      -- same instant, written apart
    2026-06-23T14:00:00          NO match   -- incomparable, no offset given
    2026-06-24T14:00:00Z         NO match   -- different instant

A value that is not a date declines the whole query rather than being served as
empty: `vitalgraph_iso_to_utc` returns NULL for anything that is not strict ISO,
so an unparseable bound would match nothing, and the general pipeline can still
match such a literal lexically. `_ISO_RE` — the pipeline's own test, imported,
not restated — decides which it is.

## The sorted half had to be fixed separately, and briefly regressed

`fast_slot_sort._filter_exists` applies the SAME criteria to the SAME table when
the list carries a sort, and calls the same `_eq_criteria` — but emitted its own
bare `= $n`. So converting the value in one place left a filtered list servable
and the identical list WITH a sort declining, which is `issues/172` restated.
Worse, for the window between `0dd38a48` and `f3ce3eee` it was a regression:
anything handing the criteria a real `datetime` used to bind there and stopped.
JSON callers were never affected. `_value_sql` and `_tz_guard` now hold the one
definition of how a lane is compared and both paths call them.

## Tests

    tests/unit/sparql_sql/test_date_bounds_are_not_cast_to_timestamp.py
        the three prop-sort builders, including the count's inline copy
    tests/unit/sparql_sql/test_slot_filter_binds_every_lane.py
        all three lanes, the guard's polarity, the sort path, a mixed conjunction
    tests/integration/test_date_range_filters_are_served.py
        eight cells over real rows, including an offset bound and its UTC twin
    tests/integration/test_slot_filter_serves_a_dated_equality.py
        ten cells, including the instant written three ways and the untimezoned
        value that must NOT match it

Every one of them fails against the code as it was.

## What this does NOT need

Do not "fix" the class by casting parameters to the column type in the other
fast paths. The cast is what caused it. A typed column reached from a JSON
criterion needs the value converted where the conversion has a POLICY (numbers,
in Python) or normalised by the function that produced the column (dates, in
SQL) — and the second is only safe because that function is IMMUTABLE and
already exists.
