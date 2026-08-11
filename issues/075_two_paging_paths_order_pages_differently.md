# Two Paging Paths Order Their Pages Differently

## Status: NOT A BUG — this is decision D1, already made and accepted

Corrected 2026-08-10, same day it was filed. The original text below called this
an open product question. It is not: `two_phase_kgquery_paging_plan.md` records

> **D1 — UUID paging order: ANSWERED, accepted.** Only affects queries with no
> explicit `sort_criteria` (`kg_query_builder.py:819` replaces the default
> entirely when sorting is requested). It also aligns KGQuery with the entity
> fast path, which already pages by `subject_uuid`
> (`kg_backend_utils.py:121`) — today the two return pages in different orders.

So uuid paging order is deliberate, its blast radius is bounded to queries that
asked for no particular sort, and it was chosen partly to make KGQuery agree
with the entity fast path. The default `ORDER BY ?entity` is what a caller gets
when they express no preference, not a contract they relied on.

The observation that survives is the smaller half of D1's own note: the GENERIC
(set-based) path still sorts by uri, so the two KGQuery paths disagree with each
other. D1 accepted uuid order; nothing has since made the generic path follow
it. That is a consistency gap to close in the generic path's direction of
travel, not a defect in two-phase.

**What this changes for `issues/061`.** The driver-selection path measured 48x
faster under uuid order and slower than the status quo once forced to uri order.
Given D1, uuid order is the accepted behaviour for exactly the queries that path
targets — so the idea is viable after all, and the "it is only fast because it
is wrong" conclusion I reached was itself wrong.

### How this was filed incorrectly

I measured that the two paths disagree, could not find a decision, and wrote it
up as needing one. The decision was in the planning document I had been editing
throughout the same session. Grepping the plan for "order" before writing an
issue would have cost one command.

## Original writeup — kept, but read the status above first

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
