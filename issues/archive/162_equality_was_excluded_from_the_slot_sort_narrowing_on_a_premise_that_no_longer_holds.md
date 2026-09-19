# Equality Was Excluded From The Slot-Sort Narrowing On A Premise That No Longer Holds

## Status: CLOSED 2026-09-18 as SUPERSEDED — the narrowing is DELETED.
##
## All three items were answered and the answer was that this issue's premise
## was wrong. The exclusion it set out to overturn is RIGHT for the shapes it
## was written about (item 2, measured). The one shape it was wrong about is
## served better and BY DEFAULT by `fast_slot_filter` — 46.9 ms against this
## narrowing's 519 ms, gated on the coverage marker rather than an env var
## (`issues/161`).
##
## So the code was a disabled, slower duplicate of a live mechanism, and a
## 37-72x regression wherever else it fired. Deleted rather than kept behind a
## flag: leaving it invited someone to enable it on the strength of this issue's
## TITLE.

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

## 2. ANSWERED 2026-09-18 — the exclusion HOLDS, and this issue was wrong

Measured on `sp_lead_types`, whole-query buffers, narrowing ON against the same
generated SQL with the clause removed. Same rows in every pair:

    shape          ON        OFF     
    text_eq        10,565    146     72.4x WORSE
    int_eq          6,023    160     37.6x WORSE
    int_eq_rare     7,550    164     46.0x WORSE

The comment this issue set out to overturn — "equality already reaches the term
semi-join with an accurate estimate" — is RIGHT about the shapes it was written
for. It was wrong about exactly one: the 53M-quad production shape where the
semi-join timed out at 55 s and the slot set answered in 519 ms.

So the narrowing is a targeted fix for one pathology and a large regression
everywhere else, which is what OFF BY DEFAULT already encodes. That default is
now pinned by a test, so enabling it becomes a deliberate act rather than a
one-character edit.

BUFFERS, NOT WALL-CLOCK, for the reason recorded below: this fixture varied 6.7s
to timeout with no code change, and anything concluded from one pair of timings
there is noise. Buffers are a property of the plan.

THE CONTROL BROKE FIRST AND LOOKED LIKE A RESULT. Stripping the clause with a
regex that stopped at the first `)` cut the subquery in half, and the "off"
column came back as a SQL syntax error — indistinguishable at a glance from the
narrowing being the only form that runs. A paren-balanced strip fixed it. A
broken control looks exactly like a broken subject.

## 3. IMPLEMENTED 2026-09-18 — numeric and datetime equality

`_typed_equality` emits `value_num = CAST('<lex>' AS NUMERIC)` and
`value_dt = CAST('<lex>' AS TIMESTAMP)`, casting the SAME way the column was
populated from the term table rather than normalising in Python — two
definitions of equality would eventually disagree.

Validated in PYTHON, not SQL: PostgreSQL constant-folds `CAST('abc' AS NUMERIC)`
at PLAN time, so a runtime guard never executes and the query dies with "invalid
input syntax". Deliberately stricter than PostgreSQL — declining a form the
database would accept costs a narrowing; accepting one it rejects costs the
query. Verified to SEEK: `Index Cond: (slot_type_uuid = ... AND value_num =
'1'::numeric)` on the partial `ess_num` index.

## What was deleted, and what was kept

DELETED: `slot_equality_constraints`, `EQUALITY_NARROWING_ENABLED`,
`_typed_equality` and its lexical regexes, the generator's Stage 2a.2b call
site, and the two tests pinning them. `slot_sort_range.py` 616 -> ~400 lines.

KEPT: `EQUALITY_LANE`, because `component_intersect` uses it — deleting it would
have broken a different mechanism. And the `COLLATE "C"` fix in that emitter,
which is the half of item 1's work that was NOT superseded. It is disabled by
default too, but a path that is silently 480x slower when enabled should not be
left for whoever flips the flag.

## What this issue was worth, honestly

Its thesis was wrong and it was not wasted:

  * it identified a real production pathology (55 s timeout), which `issues/161`
    then solved properly;
  * it found and fixed a real wrong-answer bug — `_const_uris` reused for a slot
    VALUE, so a literal missed the lookup, defaulted to `''`, and an
    INTERSECTION on `value_text = ''` removed every row. That class recurs and
    the diagnosis is recorded;
  * it produced the rule "for an ADDITIVE optimisation, assert on the GENERATED
    SQL", which caught a probe firing on nothing during this very closure;
  * item 2 is now a measured negative result, so the question is settled rather
    than open to being re-opened on intuition.

A conclusive no is a result. What it is not is a reason to keep the code.

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
