# A Collection Longer Than the Path Cap Is Silently Truncated

## Status: OPEN — found 2026-08-22 while measuring
## `planning/planning_sparql_features/rdf_collections.md`

Reading an RDF collection with the standard idiom returns **101 items** for a
200-element list and **101** for a 400-element list. No error, no warning, no
partial-result flag. Just the wrong answer.

    list length    items returned    time        buffers
        100              100          139 ms       394,253
        200              101        1,795 ms     5,617,926
        400              101       17,975 ms    37,546,274

Query:

    SELECT ?item WHERE { GRAPH <g> {
      :s :items ?l . ?l rdf:rest* ?node . ?node rdf:first ?item } }

## Cause

`emit_path.py:49`

    MAX_PATH_DEPTH = 100  # cycle prevention + backstop; NOT the runaway fence

applied as `WHERE r.depth < 100` in the recursive CTEs at `:379`, `:400`, `:456`.

The constant is well chosen **for what it was chosen for**. Its comment says so:
"Kept at the original 100 so it never truncates real frame nesting", and for
entity/frame/slot traversal a depth of 100 is far beyond anything real.

A collection breaks that assumption. An `rdf:rest` chain's depth **is** its
length, so the cap is not a backstop against pathological nesting — it is a
hard limit on list size, and it sits exactly where lists stop being small.

## Why this is worse than a slow query

The repository's traversal work fences runaway cost with `statement_timeout`
and `temp_file_limit`, which fail LOUDLY. This fails quietly: the query
succeeds, returns rows, and 100 of them are right. A caller has no way to
distinguish a 101-element answer from a truncated one without knowing the list
length independently — and the natural way to learn the length is the same
capped walk.

Note the interaction with cost: at 400 elements the truncated walk still burns
37.5M buffers and 18 seconds to return a wrong answer.

## Options

1. **Raise the cap.** Cheapest, and does not fix anything — it moves the
   silent truncation to a larger number. The comment at `:47` already wishes
   the constant were per-query configurable.
2. **Make truncation loud.** If the recursion hits the cap, fail the query
   rather than return a short answer. Turns silent wrongness into a stated
   limit, and is small. Does not make long lists work.
3. **Expose the ordinal the recursion already computes.** `emit_path.py:377`
   carries `depth` through the CTE and uses it only for the cap. That number is
   the list position. Recognising the `rest*`/`first` idiom and answering it
   from one CTE instead of two joined would remove the O(n^2) — but it does not
   remove the cap, and it is only worth doing if lists get large.

**Do (2), and only (2), for now.** A wrong answer is a different category of
problem from a slow one, and today there is no signal at all. (1) alone moves
silent truncation to a larger number. (3) is an optimisation for a workload
that does not exist — collections in our data hold a handful of members, where
the whole position query costs 791 buffers and 14.6 ms.

A derived table was considered and rejected as disproportionate; see
`rdf_collections.md` §9.1.

## Test gap

No test in the repository constructs an `rdf:first`/`rdf:rest` chain, so
nothing exercises this at any length. Found by executing it by hand while
documenting the feature.
