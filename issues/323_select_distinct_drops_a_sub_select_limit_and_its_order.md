# 323 — SELECT DISTINCT drops a sub-SELECT's LIMIT, and its ORDER BY without a LIMIT

## Status: FIXED 2026-10-27 on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defects

On the default path, which production runs. Silent wrong answers.

1. **A sub-SELECT's LIMIT under an outer DISTINCT is dropped.**

   ```sparql
   SELECT DISTINCT ?t WHERE { { SELECT ?t ?v WHERE { ?s :type ?t ; :value ?v } ORDER BY ?v LIMIT 20 } }
   ```

   answered the distinct `?t` of EVERY row (7 on `sp_lead_synth_10k`), where the 20
   lowest-valued rows hold at most 3. The DISTINCT push-down (`emit_distinct._emit_pushdown`,
   deduplicating on uuid columns before the term joins) emitted the pattern directly and
   skipped the modifiers between, and SLICE was among them. A LIMIT below a DISTINCT is
   always a sub-SELECT's own (the statement's is above), and decides which rows exist.

2. **`SELECT DISTINCT … ORDER BY` without a LIMIT comes back unordered.** Jena's algebra
   puts ORDER inside PROJECT inside DISTINCT, and deduplicating does not keep an order: the
   push-down skipped the ORDER outright (no ORDER BY in the SQL), and the plain path kept it
   inside the deduplicated subquery, where `ORDER BY DESC(?t)` came back ascending. Only a
   LIMIT's slice re-applied the order (`emit_slice`), and on the text column alone, so a
   number sorted as text: `ORDER BY DESC(?v) LIMIT 5` put "99.9" above "100.0".

## How it was found

Item 1 of the qtree planner's API declines (a sub-SELECT with a LIMIT below the outer
query's modifiers, the KGQuery capped count). Probing the shape on both paths, the planner
answered 1 row and today's SQL 7, which the data rules out.

## Fix

- `emit_distinct`: the push-down never skips a SLICE (`_SAFE_MODIFIER_KINDS`).
- `emit_slice.reorder_over_distinct`: the ORDER buried below a DISTINCT applied again above
  it with the generator's own keys (`variable_order_keys`: value, date, collated text,
  issues/295), as an ORDER BY over the same variable sorts elsewhere. `emit_slice` uses it
  in place of its text-only keys; the generator applies it at the statement's root when the
  root is the DISTINCT (no LIMIT), for variables the DISTINCT projects.

Visible change: a paged `SELECT DISTINCT … ORDER BY ?x` now orders text by code point
(`collation.collate`), as every other ORDER BY on this path has since issues/295, where it
used the database's collation.

## Test

`tests/integration/test_distinct_keeps_order_and_sub_select_limit.py`: the sub-SELECT's
LIMIT, ascending and descending DISTINCT orders with no LIMIT, numeric DISTINCT orders with
and without one. Four of the five fail before the fix (the ascending one passes by chance).
