# A Negated Frame Criterion Is Served As A Positive One

## Status: FIXED 2026-09-21 (`0dd38a48`). `fast_slot_filter._eq_criteria` never
## read `FrameCriteria.negate`, so a criterion asking for the entities WITHOUT a
## frame pattern was served as an equality probe FOR it — the complement of the
## question, with a plausible count and no error. It now declines and the
## general pipeline answers.

**Related:** `issues/223` (the same function, counting one entity twice),
`issues/224` (the same function, unable to bind two of its three lanes),
`issues/161` (what this fast path is and why its gate is a block-list)

## What it did

`FrameCriteria.negate` means "match entities that do NOT have this frame
pattern". The general path implements it by wrapping the whole pattern:

    kg_query_builder.py:803
        if frame_criterion.negate:
            where_clauses.append(f"FILTER NOT EXISTS {{ {' '.join(frame_clauses)} }}")

The fast path's `_eq_criteria` walks each criterion for `frame_type`,
`slot_criteria` and nested `frame_criteria`, and reads no other attribute. The
flag was not rejected, not warned about, not consulted — it did not exist as far
as that function was concerned. `can_serve_filter` then returned True and the
INTERSECT of equality probes selected precisely the entities the caller asked to
EXCLUDE.

**This is not a subset, it is the complement.** Every failure mode this module
documents is about returning a SUBSET — a short table quietly dropping rows. A
subset at least intersects the right answer. This returned the rows on the other
side of the predicate.

## It was reachable, which is the part worth checking before believing any of this

The flag survives the whole way to the gate. The endpoint copies it onto the
builder criteria at three sites:

    kgquery_endpoint.py:757    negate=getattr(frame_crit, 'negate', False)
    kgquery_endpoint.py:1067   negate=getattr(frame_crit, 'negate', False)
    kgquery_endpoint.py:1641   negate=getattr(frame_crit, 'negate', False)

and `_try_fast_slot_filter` (`kgquery_endpoint.py:627`) hands that same object
to `can_serve_filter`. So a negated criterion reached a probe built as though it
were positive. The model field is documented and public
(`kgentities_model.py:68`).

## Why nothing caught it

The count and the page were CONSISTENT with each other — both computed from the
same wrong set — so every internal check agreed. `test_fast_slot_filter_gate`
had nine cells for what the path must refuse (a non-`eq` comparator, a missing
entity type, an unmapped slot class, a frameless criterion) and none for
`negate`, because the gate was written against the shape of the TABLE rather
than against the shape of the MODEL. The table has no column that could express
negation, so the question never came up; the model has a field that demands it.

## The fix, and why it is a decline rather than an EXCEPT

`walk` refuses at every level it visits, nested criteria included:

    if getattr(fc, "negate", False):
        return False

Emitting `EXCEPT` instead would be wrong for the reason this whole module is
gated on a completeness marker. Absence of a row in `entity_slot_sort` means
"no such slot IN THE TABLE", which an incomplete table produces exactly as
readily as the data does. Under a positive probe an incomplete table costs
MATCHES; under a negation the same incompleteness INVENTS them. Negation is the
one direction where staleness adds rows, so it is the one direction this table
must not serve at all while completeness is the caller's job.

`fast_slot_sort` shares `_eq_criteria`, so the sorted half of a filtered list
inherited both the defect and the fix without a second edit.

## Tests

`tests/unit/sparql_sql/test_fast_slot_filter_gate.py`:

    test_a_negated_frame_criterion_refuses
    test_a_negated_NESTED_frame_criterion_refuses_too

and an end-to-end cell over real rows,
`tests/integration/test_slot_filter_serves_a_dated_equality.py::
test_a_negated_frame_criterion_is_not_served_as_a_positive_one`, which asserts
BOTH halves decline — a page that declines beside a count that serves would
leave the request paying for the complement anyway.

## How it was found

Not from a log, and not by anyone using it: by reading `_eq_criteria` while
fixing `issues/224` in the same function. Worth stating plainly, because it
means the field's users — if any — got wrong answers silently for as long as the
path has existed, and nothing in the system would have said so.
