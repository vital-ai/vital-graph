# Two Paging Paths Order Their Pages Differently

## Status: OPEN — found 2026-08-10, pre-existing, needs a product decision

A KGQuery entity page comes back in a different ORDER depending on which
emission path answered it, and both paths ship today:

    eq/Choice   two-phase          page NOT sorted by entity uri
    eq/Text     two-phase          page NOT sorted by entity uri
    WV eq       generic/set-based  page sorted by entity uri

`_emit_two_phase` pages on the anchor's `subject_uuid` — that is the whole
mechanism, an index walk in uuid order that `LIMIT` can stop early. Entity uuids
are `uuid5` of the uri, so uuid order is unrelated to uri order. The generic
path applies the SPARQL `ORDER BY` and sorts by the uri text.

Both return the correct SET. Verified directly: the same criteria through both
paths gave 848 of 848 identical rows, differing only in order — so this is not a
missing-rows bug.

## Why it matters

For a paged API the order IS part of the answer. Two consequences:

* **Page 1 differs by plan.** A query that qualifies for two-phase and one that
  does not return different first pages for the same question, and which path is
  taken depends on selectivity statistics — so it can change as data changes,
  with no change to the query.
* **Paging is only coherent within one path.** If a query switches paths between
  page 1 and page 2 (statistics refresh, criteria edit), entities can be
  repeated or skipped.

## What it is NOT

Not a regression, and not caused by the `issues/061` work — it was found while
measuring a proposed driver-selection path, by checking whether that path's
pages matched the existing ones. They did not, which is what exposed that the
existing two paths already disagree with each other.

## The decision this needs

Whether a KGQuery page is contractually ordered by the entity uri, or merely
stably ordered by something. That is a product question, not an implementation
one:

* **If uri order is the contract**, two-phase is wrong and cannot be fixed
  cheaply — it depends on walking an index in uuid order. Sorting by uri means
  materialising the match set, which is the O(match set) cost two-phase exists
  to avoid.
* **If any stable order is acceptable**, the generic path is doing needless work
  and could page on the uuid too — and `issues/061`'s driver-selection idea
  becomes viable, because it was only slower once forced into uri order.

## Related

- `issues/061` — the driver-selection work that surfaced this; its proposed path
  measured 48x faster under uuid order and slower than the status quo under uri
  order, so this decision determines whether that idea is worth anything
- `two_phase_kgquery_paging_plan.md` — the uuid-order index walk this rests on
