# Equality Was Excluded From The Slot-Sort Narrowing On A Premise That No Longer Holds

## Status: OPEN. Implementing the text lane; the exclusion's rationale needs
## re-testing at the term semi-join level.

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

## What remains to establish

1. **The text lane's index.** `slot_sort_range` deliberately leaves the leading
   index columns unconstrained and relies on PG18 skip-scan, measured for the
   `value_num` PARTIAL index. The text index
   `(context_uuid, entity_type_uuid, frame_type_path, slot_type_uuid,
   value_text, entity_uuid)` is not partial and has not been measured that way.
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
