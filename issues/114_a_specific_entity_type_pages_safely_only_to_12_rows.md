# "A Specific Entity Type Pages Safely Only to 12 Rows" — It Does Not

## Status: WITHDRAWN 2026-08-20, same day it was filed. The bench was measuring a
## plan that never runs. The measurement is fixed; there was no service defect.

## What was filed, and why it was wrong

`test_page_size_before_plan_flip[specific-10k]` reported, with `--runxfail`:

    paging falls back to a blocking plan above 12 rows — a caller asking for 13
    gets a page costing O(matches) rather than O(page)

I filed that as a live defect, reasoning that the default page size is 25 and
therefore every caller of that shape was paying O(matches).

**`_flips_to_blocking_plan` ran a bare `EXPLAIN`.** `execute_sparql_query` runs
the statement inside `SET LOCAL enable_sort = off` whenever the generator sets
`needs_ordered_scan`, and this shape sets it at every page size. Measured on the
10k fixture, specific entity type:

    page  needs_ordered_scan  unfenced Sort  fenced Sort
      10        True               no            no
      12        True               no            no
      13        True              YES            no
      25        True              YES            no
     500        True              YES            no

Fenced — which is what production does — there is no flip at any size up to 500.
The "threshold at 12" was a property of a plan that never executes.

## Why this was avoidable

`_fenced` exists in the same file, with a docstring that says exactly this:

> Measuring the plan WITHOUT that fence describes something that never runs —
> and reports a growth ratio the served query does not have.

The growth-curve test uses it. `_flips_to_blocking_plan` did not, because
`_criteria_to_sql` returned only `gen.sql` and discarded `needs_ordered_scan`, so
the flag was not available at the point the decision was made. A helper that
throws away the one field a caller needs to be correct will eventually have a
caller that is not.

## What changed

* `_criteria_to_gen` returns the whole `GenerateResult`; `_criteria_to_sql` is a
  thin wrapper for callers that only want SQL.
* `_flips_to_blocking_plan` fences when `needs_ordered_scan` is set and not
  otherwise — mirroring the executor rather than improving on it, because
  forcing `enable_sort = off` on a shape that genuinely needs a sort reads as a
  273x regression.
* The xfail is gone. All four parameters pass on their own merits.

## The bench that replaces the threshold search — and the version of it that was wrong

`tests/performance/test_paging_fence_covers_every_shape.py` enumerates 6 criteria
shapes x 2 entity types x 2 page sizes x 2 fixtures and asserts a property rather
than searching for a number.

**The first attempt asserted the wrong property** — "a plan containing a Sort must
be fenced". It fired on 24 shapes, and measuring them disproved it:

    shape       flag    unfenced   fenced     fencing would be
    eq-rare     False     35,409   435,228    12x WORSE
    range-mid   False     51,182   312,248     6x WORSE
    eq-common   True      54,561    54,561    identical

For those shapes the sort-based plan IS the right one and `False` is the correct
judgement. A Sort is not a defect, and forcing `enable_sort = off` on a shape
that needs one is the 273x regression this repository already documents. Had that
version shipped, the "fix" would have been to set the flag on 24 shapes and make
them all catastrophically slower.

What is actually checkable is whether the flag AGREES with which plan is cheaper:

    fenced materially cheaper   -> the flag must be True
    unfenced materially cheaper -> the flag must be False

Both sides measured in the same run, compared as a ratio (2x to count as
decisive), with a probe timeout that is itself a measurement — a side that cannot
finish is not the cheaper side. Currently 0 failing; inverting the flag fails 17
ways, in both directions, with ratios of 36.5x and 172.6x.

## What remains true, and is the real question

The THRESHOLD was never a stable quantity — 12, 19, 52, 161-180 across datasets
and dates — because it is a cost-model crossover, not a property of the system.
That is worth stating plainly: a test that searches for the page size at which
the planner changes its mind is measuring the planner's arithmetic against one
data distribution.

The fence is the answer to that, and it already exists: it removes the crossover
entirely rather than locating it. What this bench should assert is that the fence
APPLIES — `needs_ordered_scan` set for every shape that needs it — since a shape
that misses the flag is the only way the cliff becomes reachable. That is a
property with a yes/no answer, not a number that moves with the data.

Two shapes are known to have missed the flag: this one (measured correctly, it
does set it) and the selective range criterion in `issues/111`, which did not —
`needs_ordered_scan=False` at the tight threshold, where the unfenced plan
genuinely ran. So the failure mode is real; it just was not happening here.

## Related

- `issues/111` — a shape where the flag really was False and the unfenced plan ran
- `issues/047` — the fence, and why it is a GUC rather than a hint
- `issues/112`, `issues/113` — the same theme: a gate reporting something other
  than what it names
