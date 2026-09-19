# Equality Was Excluded From The Slot-Sort Narrowing On A Premise That No Longer Holds

## Status: PARTLY FIXED 2026-09-18. Item 1 was not a measurement, it was a
## DEFECT — the narrowing was firing and costing more than it saved, and that is
## fixed. Items 2 and 3 are untouched: whether the exclusion still holds for the
## shapes the comment was written about, and numeric/datetime equality, which
## nothing has measured.
##
## Written FIXED first, which is the error this file's own archiving rule
## exists to catch: a header claiming more than the body supports.

## What is recorded today

`slot_sort_range.py` narrows a slot against `entity_slot_sort` for RANGE
criteria, and says why equality is not included:

    # Only the ordering comparators. Equality is deliberately excluded: it
    # already reaches the term semi-join with an accurate estimate, and it is
    # the shape the criterion gate is built around.
    RANGE_OPS = {">=", ">", "<=", "<"}

`VALUE_LANE` in the same module carries only the numeric and datetime
predicates — `hasDouble/Integer/Long/Currency/DateTimeSlotValue`. There is no
`value_text` lane, so no text or URI predicate can be narrowed at all.

## Why the premise is in doubt

Measured this session on `lead_nurture_100k` (53M quads), the production Nurture
shape, one equality on a URI slot value:

    generated SQL, edge walk        TIMEOUT at 55s
    the same answer driven from
    the slot set, by hand              519 ms warm

That is not "already reaches the term semi-join with an accurate estimate". The
plan anchors on `hasKGEntityType = <Lead>` — every entity — because
`semijoin._split_bgp` picks the anchor STRUCTURALLY ("every quad table binding
the projected variable and nothing else"), so the discriminating constant is
ineligible to anchor. Both reachable plans then start from 100,000 candidates:
the probe runs ~49,000 EXISTS subplans, and declining it merge-joins all
5,277,000 edge rows at an estimated cost of 1,250,744,169.

The comment may still be right about the shapes it was written for. It is
demonstrably not right about this one.

## What was attempted, and the mistake worth recording

`slot_equality_constraints` was added to the same module, mirroring
`slot_range_constraint` and anchored on the SLOT for the same soundness reason.
It never fired: it looked its predicate up in `VALUE_LANE`, which has no text
lane, so every candidate was skipped and the function reported nothing. It was
dead from the moment it was written.

Nothing caught that for two measurement rounds. The timings looked plausible
(14s, 7s, 28s — all environmental variance), the debug log could not
distinguish "did not fire" from "not logged at this level", and only checking
the emitted SQL for `entity_slot_sort` settled it. The lesson is the check, not
the bug: for an ADDITIVE optimisation, assert on the generated SQL, because a
missing addition changes nothing observable except speed.

## 1. ESTABLISHED 2026-09-18 — the index was never being used for the value

Measured on `lead_nurture_grouped` (4,064,500 slot-sort rows, PG 18.4), the
exact shape this module emits, one row returned:

    Index Cond: (slot_type_uuid = ...)
    Filter:     (value_text = 'SYN000088727')
    Rows Removed by Filter: 99999
    Index Searches: 19
    Buffers: 92,139        Execution Time: 2,231 ms

Skip scan DOES engage — 19 index searches over the unconstrained leading
columns, which answers the question as asked. The value is the problem:
`value_text` arrives as a FILTER, not a seek.

`idx_{space}_ess_text` indexes `value_text COLLATE "C"` and the database
collation is `en_US.utf8`, so an equality in the default collation cannot use
that index column. Adding the clause:

    Index Cond: (slot_type_uuid = ... AND value_text = 'SYN000088727')
    Buffers: 192           Execution Time: 8 ms

**480x the buffers and 266x the time, for a clause whose absence changes
nothing about the ANSWER.** That is why "Performance: NOT established" below
recorded "roughly halved" and could not resolve it: the narrowing was firing
and scanning 100,000 rows to do it.

CONSTRAINING THE PREFIX IS NECESSARY AND NOT SUFFICIENT.
`component_intersect` supplies `entity_type_uuid` AND `slot_type_uuid` and
still filtered 99,999 rows at 71,313 buffers. Both emitters now collate.

The schema comment beside the index already assumed this — "COLLATE \"C\"
matches what the generator emits for a text ORDER BY". True of the sort path,
and false of the equality narrowing from the day it was written.

Pinned by `tests/unit/sparql_sql/test_slot_value_text_is_collated.py`, asserting
on the GENERATED SQL for the reason this issue itself recorded: for an additive
optimisation a missing clause changes nothing observable except speed, and speed
on these fixtures varies by more than the effect.

## What remains to establish
2. **Whether the exclusion still holds elsewhere.** The comment's claim should
   be re-tested for the shapes it was written about, not just overridden because
   it is wrong for this one.
3. **Numeric and datetime equality.** Deferred: they need the literal in the
   column's type, and nothing has measured them.

## ROOT CAUSE of the wrong answer, found 2026-09-05

With the narrowing on, `SFLeadId = "SYN000000000"` returned 0 where the correct
answer is 1, in 238 ms. The generated constraint was:

    ... IN (SELECT slot_uuid FROM lead_nurture_100k_entity_slot_sort
            WHERE slot_type_uuid = '36152afe-...'::uuid AND value_text = '')

`value_text = ''` — an EMPTY STRING. `_const_uris()` maps
`__CONST_c_N__ -> text` for URI constants ONLY (`if ttype == "U"`), and it was
reused to look up a slot VALUE. A text slot's value is a LITERAL, so the lookup
missed, `.get(..., "")` returned the default, and the comparison matched nothing.
In an INTERSECTION that deletes every row.

That is why the split was exactly URI vs literal: `urn:acme:campaign:000` is a
URI and stayed correct; `"SYN000000000"` is a literal and returned 0. Same shape
as `issues/157` — code that handles URIs correctly and drops literals, failing
as a confident empty result rather than an error.

### Fixed

  * `_const_terms()` — token -> lexical form for ANY term type, used for values.
    Kept separate from `_const_uris` rather than widening it: predicate lookups
    genuinely want URIs only, and a literal predicate is a different bug.
  * An empty value now REFUSES to emit (`if not value_text`), so an unresolvable
    constant can never become `value_text = ''`.
  * `_const_uris`' docstring names this failure, for the next reuse.

Verified: all four shapes correct with the narrowing on.

## Performance: NOT established

    shape                off          on
    campaign head        23,471 ms    25,165 ms
    campaign + ABSENT    19,962 ms    TIMEOUT
    SFLeadId present        421 ms       219 ms
    SFLeadId ABSENT         131 ms        77 ms

The text-literal shapes roughly halved. The campaign shapes are NOT comparable
from single runs: that shape measured 6.7s, 13.5s, 19.9s, 32s and timeout across
this session with no code difference between several of those runs. Anything
concluded from one pair of numbers there is noise.

WHAT A DECISION NEEDS: repeated alternating runs on a quiet stack, reporting a
distribution rather than a value. The fixture is excluded from maintenance now
(`docker-compose.test.yml`), which removes the largest known perturbation, but
the variance above was measured AFTER that exclusion.

Default remains OFF (`VG_SLOT_SORT_EQUALITY_NARROWING`).
