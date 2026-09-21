# One Entity Matching Twice Is Counted And Returned Twice

## Status: FIXED 2026-09-21 (`0dd38a48`). `entity_slot_sort` holds a row per
## SLOT, and a single criterion is a single arm — so there was no INTERSECT to
## deduplicate it. The count was `count(*)` over slot rows and the page selected
## straight from them. Both now dedupe on `entity_uuid`. Cost measured, below.

**Related:** `issues/222` (the same function, serving a negation as its
opposite), `issues/224` (the same function, unable to bind two of its three
lanes), `issues/161` (what this fast path is)

## The shape that breaks it

One entity with TWO frames of the same type, both carrying the criterion value.
Two Campaign frames on a lead, both `ACTIVE`. The table describes slots, so that
entity has two rows satisfying the probe:

    slot_uuid  entity_uuid  frame_type_path  slot_type_uuid  value_text
    s1         e            [Campaign]       status          ACTIVE
    s2         e            [Campaign]       status          ACTIVE

`fast_slot_filter_count` ran `SELECT count(*) FROM (<arm>) x` and answered 2 for
one entity. `fast_slot_filter_page` selected `entity_uuid` from the same arm,
ordered it and paged it, so the URI came back twice — taking two of the page's
fifty slots and shifting every later offset by one.

It only bites with ONE criterion. Two or more are joined by `INTERSECT`, which
deduplicates as a set operator, so the bug is invisible in exactly the queries
that look complicated and present in the simplest one the path serves.

## Why it read as data rather than as a duplicate

The page is `ORDER BY entity_uuid`, so the repeats sit ADJACENT. A list showing
the same entity twice in a row looks like two records that happen to share a
name — not like a broken query. And the count agreed with the page, because both
counted the same rows, so a consistency check between them (which this module
has, `test_count_and_page_move_together`) passes while both are wrong.

The count is the more serious half. A repeated row on screen is at least
visible; `total_count` is the number the caller pages against, and it was
inflated by however many frames each matching entity carried.

## The fix

    count:  SELECT count(*) FROM (SELECT DISTINCT entity_uuid FROM (<arm>) x) y
    page:   SELECT DISTINCT entity_uuid FROM (<arm>) x ORDER BY entity_uuid ...

`count(*)` over a DISTINCT subquery rather than `count(DISTINCT ...)`: the same
answer from a HashAggregate instead of a sort per group. It also restores what
the function's own docstring already promised — "how many distinct entities
satisfy every criterion".

## What correctness costs here, measured

`sp_lead_synth_100k_entity_slot_sort`, 4,063,149 rows, on the worst arm in the
space — an equality matching 100,000 rows. Warm, three runs, best of:

    count   28.3 ms  ->  112.8 ms
    page    32.0 ms  ->  102.4 ms

So roughly 3-4x on the largest match set the space can produce, and the
dedupe is pure overhead in THAT particular arm (100,000 rows, 100,000 distinct
entities — the synthetic fixture gives each entity one frame). A selective
criterion pays proportionally less.

Recorded rather than negotiated: the alternative to paying it is a count that
overstates and a page that repeats. For scale, the BGP join this path replaces
measured 13.9 s on the same space. If it ever needs reclaiming, the lead is that
`entity_uuid` is the TRAILING column of `idx_{space}_ess_text` under a fully
equality-bound prefix, so a Unique over an ordered index-only scan could stream
and stop at fifty rows; the planner currently chooses a Sort, and finding out
why is a plan question, not a correctness one.

## How it was found

By a fixture accident. `test_space` outlives a single test, and the first
version of `test_slot_filter_serves_a_dated_equality` seeded rows keyed on
`uuid.uuid4()` — so the second parametrised cell saw two rows per entity and the
seventh saw seven. The page came back with the URI repeated, which was a bug in
the fixture and, on inspection, ALSO a real shape the production data can hold.
The fixture is deterministic now and the shape is a test:

    tests/integration/test_slot_filter_serves_a_dated_equality.py::
        test_an_entity_matching_twice_is_one_entity

It asserts both halves: the page returns the entity once, and the count says 3
rather than 4.
