# A Specific Entity Type Pages Safely Only to 12 Rows

## Status: OPEN — live, measured, and previously tracked only by an xfail
## pointing at two CLOSED issues

`test_page_size_before_plan_flip[specific-10k]`, run with `--runxfail`:

    AssertionError: paging falls back to a blocking plan above 12 rows — a
    caller asking for 13 gets a page costing O(matches) rather than O(page)
    assert (12 is None or 12 >= 100)

`MIN_SAFE_PAGE_SIZE` is 100. The default page size is 25. So **the default page
already exceeds the safe threshold** for this shape: a KGQuery with a SPECIFIC
entity type on the 10k fixture gets an O(matches) plan at the size callers
actually use.

## Why it had no issue

The xfail says:

> issues/047 — the split-BGP anchor flips to a blocking sort at 19 rows on 10k,
> below the default page size of 25

Both issues it could belong to are closed:

* `issues/047` — "paging plan flips to a blocking sort above 51 rows" —
  **FIXED 2026-08-08 (page and capped count)**
* `issues/045` — "semijoin never fires when entity type is specific" —
  **FIXED 2026-08-07, 24.5-32.3s → 2ms**

And the number has moved: the marker says 19, the measurement says 12. So this is
not the defect either issue described, it is a residual with the same shape,
carrying a citation to work that is done. An xfail is a fine way to stop a known
defect failing the build; it is a poor way to own one, because nothing reviews
the reason when the issue it names is closed.

## What is known

* It is specific to a SPECIFIC entity type. The `generic` parameter passes at
  both fixture sizes.
* It is specific to the 10k fixture. `specific-100k` passes — the threshold there
  is 161-180, comfortably above the page size, which is why the xfail was
  narrowed to 10k (`issues/113` work).
* The threshold is data-dependent: 52 on a production copy, 161-180 on 100k, 12
  here. That is the pattern `issues/047` documented — the planner prorating an
  ordered scan's cost by the LIMIT and getting it wrong — so the cause is
  probably the same mechanism, not a new one.

## What to do

1. Establish whether 12 is a regression from 19 or just a different measurement
   of the same instability. `git log` on the emit path since 2026-08-08 is the
   place to start; the fixture has been reloaded since, so re-measuring on the
   commit the 19 came from is the honest comparison.
2. Decide whether a threshold BELOW the default page size is acceptable for any
   shape. If it is not, this is a correctness-of-service bug rather than a
   benchmark finding: every caller of that shape is paying O(matches).
3. Either fix it or re-point the xfail at THIS issue, so the marker names
   something open.

## Related

- `issues/047`, `issues/045` — both closed, both cited by the marker
- `issues/112`, `issues/113` — the same theme: a gate that names something other
  than what it measures
