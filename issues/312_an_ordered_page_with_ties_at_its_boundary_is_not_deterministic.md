# 312 — An ordered page with ties at its boundary is not deterministic, on either path

## Status: OPEN, 2026-10-26. Explained; the fix (a tiebreak for ordered pages) is undecided.

## What was seen

The planner's contract corpus reported `l2_page` (lead 100k) as returning different rows from
today's SQL in every run since the planner first planned it. That made it the one standing
result difference in the corpus.

```sparql
SELECT ?d ?name ?state ?rating WHERE { GRAPH <urn:sp_lead_synth_100k> {
  ?d h:hasKGEntityType <urn:acme:kg:entity:Lead> .
  ?a h:hasKGGraphURI ?d ; h:hasKGSlotType <...:CompanyName> ; h:hasTextSlotValue ?name .
  ?b h:hasKGGraphURI ?d ; h:hasKGSlotType <...:CompanyStateCode> ; h:hasTextSlotValue ?state .
  ?c h:hasKGGraphURI ?d ; h:hasKGSlotType <...:MQLRating> ; h:hasDoubleSlotValue ?rating .
} } ORDER BY DESC(?rating) LIMIT 25
```

Both paths return 25 rows. The `?rating` column is identical in value and order; the leads
behind it differ.

## Explanation

**Ties.** On lead 100k, 59 leads have the top rating of 100.0, and 90 more have 99.9. A page of
25 ordered by rating alone is any 25 of the 59. SPARQL leaves the order of rows with equal sort
keys undefined (15.1), so both answers are correct. Each path picks a different 25, decided by
its own physical plan.

This is not a planner defect, and it is not specific to the planner.

## Why it still matters

The page is not deterministic on EITHER path. Consecutive pages (`OFFSET 25`, `OFFSET 50`, ...)
can repeat or skip rows wherever ties cross a page boundary. That can happen across separate
executions of the same plan, and certainly whenever the plan changes: a statistics refresh, the
planner on or off, a different install. A client paging through a sorted list could miss
entities.

Unordered pages already get a total order: the generator synthesizes an ORDER BY on the term
uuid (`hints["stable_paging"]`, issues/075, 078), and the planner honours it (`q.synth_order`).
Ordered pages get no tiebreak.

## Options

1. **Append a tiebreak to every ordered page:** the projected variables' term uuids, after the
   user's keys, on both paths. Pages then partition the full result. Cost: one more sort key;
   it can break an index-ordered early stop that relied on the user's key alone. The planner's
   early-stop walk would need the composite.
2. **Leave SPARQL's semantics and document it.** Clients that page must order by a unique key.
   The KG list builders already add the entity URI as a final key (`ORDER BY ?sort_missing
   ?sort_num ?frame`); `l2_page` is a hand-written corpus query that does not.
3. **Corpus only:** make the contract check compare such pages up to ties (same sort-key
   multiset, rows drawn from the tied set). This does not address paging.

Recommendation: option 1 for the planner and the generator together, verified by the partition
check (pages concatenate to the full ordered result, no repeats, no gaps). Until then, the
contract corpus should report `l2_page` as "equal up to ties", not as a difference.

## Evidence

- `test_scripts_internal/planner_ext/corpus/results/lead100k_c21.txt`: `l2_page`, `rows identical:
  False (as multiset False)`, `same-order columns ['v6']` (the rating).
- Tie count: `GROUP BY ?rating ORDER BY DESC(?rating)` over the same pattern gives 100.0: 59,
  99.9: 90, 99.8: 103.
