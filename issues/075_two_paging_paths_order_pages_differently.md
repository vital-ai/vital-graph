# Two Paging Paths Order Their Pages Differently

## Status: RESOLVED 2026-08-12 — D1 kept, and the substitution made honest

D1's ordering is unchanged and now measured (117x, below). What changed is that
it is no longer a SUBSTITUTION:

* the builder emits no `ORDER BY` when the caller requested no sort;
* `collect._collect_slice` imposes one and MARKS it `stable_paging`;
* every emitter answers a marked order with the entity uuid — two-phase, the
  generic path, and the deep page — so they agree, which is what `issues/078`
  needed;
* an unmarked `ORDER BY` is answered as written. Two-phase declines it rather
  than substituting, which closes a real violation: a hand-written
  `ORDER BY ?s` was being given uuid order, and that is a different page, not a
  reordered one.

Gates: 1779 unit; 196 integration incl. a new test that a requested order is
delivered ASC and DESC; comparator sweep 0 cells slow warm with buffer counts
IDENTICAL to baseline on every cell, i.e. identical plans.

> **PARTLY RESOLVED 2026-08-11.** The unsorted deep-page path now orders by entity UUID, matching page 1, so a single pagination sequence no longer crosses two orderings — verified: page2 == first50[25:], 0 rows missed (`issues/078`). What remains open is the SEMANTIC question this issue was filed on: uuid order is not the URI order `ORDER BY ?entity` asks for, and decision D1's justification for that was measured on a 1 GB buffer pool (`issues/081`). The paths agreeing makes the deviation consistent, not correct.

> **THIS NOW BLOCKS A 50x FIX (`issues/078`).** Skipping semi-join marking for deep pages makes page 201 go 16,271 ms -> 326 ms, flat at any depth. It cannot ship because page 1 and page 2 would come from the two differently-ordered paths this issue describes: measured, iterating page 1 -> page 2 silently SKIPS 25 rows. 'Each path is internally consistent' holds only while one pagination sequence uses a single path.


## D1 RE-ARGUED ON A FAITHFUL MEASUREMENT — 2026-08-12

This issue recorded the honest test as never taken: it has to move the ordering
INSIDE the page subquery, which pulls the term join into the page. Taken now, on
the corrected 16 GB pool, by ordering two-phase's page by the requested key.
Both columns are warm medians of 3; buffers are the machine-independent half.

    offset      UUID order (today)            REQUESTED URI order
         0      55 ms      623,874 buf        6,448 ms   14,093,952 buf
       250     764 ms    9,062,842 buf       33,447 ms  397,914,872 buf
     1,000   3,157 ms   36,359,970 buf       45,235 ms  397,914,872 buf

**117x on page 1, and 22x the buffers.** The original justification for D1 was
"3,683 ms against a 3,208 ms baseline" — a 15% difference. That measurement was
not faithful (it re-ordered the 25 rows already selected). The real cost is two
orders of magnitude larger, so **D1 stands, and now on evidence rather than
assertion.**

The mechanism is structural, not tuning. The order key is `term_text`, which
lives in the term table; the anchor scan produces `subject_uuid`. Ordering on
the key therefore requires resolving text for EVERY candidate before the first
row can be returned — the 397,914,872-buffer figure is identical at offset 250
and 1,000 because both materialise the whole match set. Early termination and
the requested order are mutually exclusive here.

**And it is not cosmetic.** The first 25 by URI text and the first 25 by uuid
share **0 of 25** entities. D1 does not reorder a page, it selects a different
page.

## THE ACTUAL DEFECT IS UPSTREAM — the builder asks for an order it does not want

`kg_query_builder.py:827` sets `order_by = "ORDER BY ?entity"` as the DEFAULT,
for callers who expressed no sort preference at all. So:

* the SPARQL says "order by ?entity";
* every fast path ignores that and pages by uuid (D1);
* nothing downstream can distinguish "the caller asked for URI order" from
  "the builder filled in a default" — they are the same SPARQL text.

That is the root of every ordering inconsistency in `078`: two emitters read the
same clause and answer it differently, and neither is wrong given what it was
told. It also means a RAW SPARQL query with a genuine `ORDER BY ?s` is silently
given uuid order by the same code, which is a real violation rather than an
accepted trade.

### The fix this points at, and why it is cheap

Measured: page 1 of the same query with the `ORDER BY` clause REMOVED costs
**70 ms against 50 ms**. The default clause is not load-bearing for performance —
it costs 40%, not a cliff.

So:

1. the builder emits NO `ORDER BY` when no sort was requested;
2. the SQL layer imposes a deterministic paging order — the anchor uuid — for a
   paged query that requested none. Required regardless: without an ORDER BY,
   PostgreSQL guarantees no stable order between pages, so pagination is unsafe;
3. uuid order becomes CORRECT rather than a substitution — SPARQL permits any
   order when none is requested — and a genuine `ORDER BY ?s` is honoured again;
4. every path can then agree on uuid, which is the consistency `078` needs. The
   uuid-ordered deep page that failed as attempt 6 fails only because page 1
   sometimes comes from a text-ordered path; with all paths on uuid it is
   correct, and it was 58x.

Observable KGQuery behaviour does not change — those queries already return uuid
order today. What changes is that the query text stops asking for something else.

**REOPENED for re-argument 2026-08-11 — the performance basis is void.** D1 was
accepted as a deliberate trade: uuid paging order in exchange for a page that
early-terminates. The recorded justification is a timing — "the text sort cost
the entire win, 3,683 ms against a 3,208 ms baseline" — measured with
`shared_buffers = 1 GB` on a 64 GB machine. Raising the pool to 16 GB moved a
comparable query from 16,411 ms to 616 ms with NO code change, so every timing
of that era is suspect.

This does not make D1 wrong. It removes the evidence D1 was decided on. The
semantic question — is a page ordered by an opaque uuid acceptable when the
caller did not ask for an order — should now be answered on its own terms, and
if the answer is still yes, re-justified with a measurement taken on a correctly
configured server.

A re-test was attempted and was NOT VALID: replacing the outer ORDER BY gave
50 ms (uuid) vs 46 ms (URI text), but that only re-orders the 25 rows already
selected. D1 governs page MEMBERSHIP, set by the ordering inside the page
subquery. A faithful test has to move the ordering there, which pulls the term
join into the page — the very cost D1 exists to avoid. Still unmeasured.

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
