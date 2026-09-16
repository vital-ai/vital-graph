# MINUS And An Alternation Path Read The Whole Population For One Page

## Status: OPEN, and the alternation half is a CORRECTNESS defect as well as a
## cost one: `?s p|p ?o` returns 120,000 solutions where SPARQL requires
## 240,000. Diagnosed to `emit_path.py:380`. Found by the first run of the
## `issues/193` shape bench.

## The measurement

Seven SPARQL shapes, each `LIMIT 25`, each returning exactly 25 rows, on
`sp_lead_synth_10k` (7.4M quads). `EXPLAIN (ANALYZE, BUFFERS)`, warmed first:

    MINUS                 661,626 buffers      ~5.2 GB
    alternation path      477,751 buffers      ~3.7 GB
    sub-SELECT              1,575
    OPTIONAL                  406
    BIND / LCASE+CONTAINS     127
    UNION (bound var)         127

Identical to the buffer on a second run (661,626 and 477,751 again), so this is
the PLAN, not a cold cache.

A 5,000x spread between shapes returning the same 25 rows.

## What the two expensive shapes have in common

    MINUS       ?s vitaltype KGTextSlot . MINUS { ?s hasBooleanSlotValue ?b }
    path        ?e hasEdgeSource|hasEdgeDestination ?n

Both are O(POPULATION), not O(page): the anti-join has to be resolved for every
candidate before `LIMIT` can take 25, and the alternation appears to materialise
both arms rather than stopping once 25 rows exist. `KGTextSlot` has 115,000+
instances in this fixture and the two edge predicates 527,700 each, so the page
is paying for the whole set either way.

That is the same shape as `issues/040` — "kgquery paging is O(matches), not
O(page)" — arriving through a different operator, and the same property
`fast_prop_sort` is valued for: staying flat as the page deepens.

## Why nothing caught it

`issues/193` counted the operators appearing anywhere in `tests/performance`:
`MINUS` **0**, property paths **0**. Both were entirely unbenched, so there was
no number to regress. This was found by the first run of the bench written to
close that gap, before it had measured anything twice.

## Not yet established

- Whether the LIMIT can push through either shape at all, or whether the cost is
  semantic (an anti-join genuinely needs the population) rather than a plan
  defect. `MINUS` may be irreducible; the alternation probably is not.
- Whether a deeper page costs more, which distinguishes "O(population) once"
  from "O(offset) per page" — `fast_prop_sort` documents that distinction as the
  one that actually matters to a user.
- Whether the generated SQL for an alternation path is a UNION of two scans (in
  which case the LIMIT should be pushable into each arm) or something else.

## Where to look

`tests/performance/test_sparql_shape_coverage.py` reproduces both in about a
second each. The generated SQL comes through `_generate_sql`, so the plan is one
`EXPLAIN` away.

## Diagnosed 2026-09-15

### First: the numbers are real, unlike `issues/206`'s

`issues/206` was withdrawn the same day because it benched the GENERATOR's SQL
while the runtime rewrites it. Checked here before going further: both shapes
report `needs_ordered_scan=False`, so no fence is applied and the generated SQL
IS what executes. These numbers stand.

### The cost is O(population) ONCE, not O(offset)

    MINUS        offset 0: 661,625 buffers    offset 2000: 669,647   (+1.2%)
    alternation  offset 0: 477,751            offset 2000: 493,751   (+3.3%)

So this is NOT `issues/040`'s failure mode, where a deep page pays for every
skipped row. It is a fixed floor paid once, whatever the page. Better, but the
floor is ~5 GB of buffers to return 25 rows.

### The alternation emits a DEDUPLICATING union, and that is a spec deviation

`emit_path.py:380`:

    sql = f"({sql_l}) UNION ({sql_r})"

A plain `UNION`, not `UNION ALL`. SPARQL 1.1 translates `X p1|p2 Y` to
`Union(BGP(X p1 Y), BGP(X p2 Y))`, and SPARQL's Union is MULTISET union —
duplicates are preserved unless `DISTINCT` is requested. Measured:

    ?s p   ?o    120,000 solutions
    ?s p|p ?o    120,000 solutions     should be 240,000

So solutions are silently dropped. It is also what makes the shape expensive:
a deduplicating union must materialise and hash both arms before `LIMIT` can
take 25, which is the 477,751 buffers.

**Both problems have the same one-word fix and it is NOT safe to just make it.**

### Why `UNION ALL` cannot simply be substituted

The header of `emit_path.py` records why the dedup is there:

    The recursive CTEs below use `UNION`, which deduplicates, and that is what
    normally terminates a transitive closure over cyclic data: revisiting a pair
    adds no new row.

and then records a runaway that happened when that dedup was accidentally
defeated — `(s,e,1)` and `(s,e,2)` counted as different rows, so the recursion
ran to the `MAX_PATH_DEPTH = 100` cap: "300 rows with the depth column, 9
without — and 9 is the correct answer."

`PathAlt` is not itself recursive, so `UNION ALL` is right for a bare `p1|p2`.
But an alternation nested inside `+` or `*` feeds the recursive CTE, and
duplicates there are exactly what the termination argument relies on not having.

### What the fix needs

- `UNION ALL` for `PathAlt` only where it is NOT beneath a recursive path
  operator, or a demonstration that the recursive CTE's own dedup is sufficient.
- A test pinning transitive closure over CYCLIC data, since that is the case the
  header says this protects and nothing currently asserts it.
- A test pinning `p|p` at 2x, which is the spec behaviour and is what caught it.

### Still not established

- Whether MINUS's floor is semantic. An anti-join may genuinely need the
  population; unlike the alternation, no obvious spec deviation is in play, and
  its SQL contains no UNION at all.
- Whether other `UNION` uses in `emit_path.py` (lines 421, 440, 474, 498) are
  the recursive ones the header defends or further instances of this.