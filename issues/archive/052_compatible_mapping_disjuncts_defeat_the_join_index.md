# Compatible-Mapping Disjuncts Turn Every OPTIONAL Join Into a Nested Loop

## Status: FIXED 2026-08-09

`is_empty` on a text slot took **over 120 seconds on a 10,000-entity fixture**.
The cause is not specific to `is_empty`; it applies to every OPTIONAL.

## The condition

SPARQL's compatible-mapping rule says an unbound variable matches anything, so
join conditions were emitted as:

```sql
(l.v__uuid IS NULL OR r.v__uuid IS NULL OR l.v__uuid = r.v__uuid)
```

That is not an equijoin. PostgreSQL cannot hash or merge on it, so it plans a
nested loop with a join filter:

```
Nested Loop Left Join
  Join Filter: ((mv2.dest_node_uuid IS NULL) OR (q16.subject_uuid IS NULL)
                OR (mv2.dest_node_uuid = q16.subject_uuid))
```

`is_empty` is `OPTIONAL { ?slot <valueProp> ?v } FILTER(!BOUND(?v))`, so it
always takes this path — and pays for it against the whole slot population.

## When the disjuncts are dead

A variable bound by a required triple pattern is never NULL. If neither side of
the join contains anything that can produce an unbound value — no OPTIONAL, no
UNION branch omitting the variable, no VALUES carrying UNDEF — both `IS NULL`
tests are constant false and the condition reduces to plain equality.

The NULL-extension OPTIONAL requires still happens. It comes from the LEFT JOIN
itself, not from the ON clause. That is the point easily missed: the disjuncts
were never what made OPTIONAL work.

`_all_required()` walks the subtree for `LEFT_JOIN`, `UNION`, `TABLE` and
`MINUS`; the disjunct is dropped only when the subtree is free of all four and
the variable is `from_triple`.

An earlier attempt tested `child.kind == KIND_BGP`, which was too strict — the
left side of a LEFT JOIN is typically a JOIN of BGPs, whose variables are just
as bound — and dropped only the right disjunct, leaving
`(l IS NULL OR l = r)`, still not an equijoin and still 120s+.

## Measured

| | before | after |
|---|---|---|
| `is_empty` / text slot, 10k entities | **>120,000 ms** | **1,518 ms** |

## Verification

The semantics guard is the DAWG conformance suite, which exists for exactly
these OPTIONAL and compatible-mapping rules: **0 failures**.

Correctness was also checked on data where `is_empty` actually matches. The
fixtures cannot express it — **0 of 387,700 slots lack a value**, so every
`is_empty` comparison returns nothing and proves nothing. Values were stripped
from `CompanyStateCode` slots inside a rolled-back transaction to create real
empty slots: 100 rows before the change, 100 after.

That vacuity nearly caused this change to ship on evidence that proved nothing —
three comparisons "matched" while both sides returned zero rows.

## Unit coverage

`test_left_join_shared_var` asserted `IS NULL` appears in the SQL, which encoded
the mechanism rather than the semantics. Replaced by two tests: a plain equijoin
when both sides are required, and the NULL-tolerant form when a nested OPTIONAL
can leave a variable unbound.

## Related

- `scripts/perf_shape_matrix.py` — found it; `is_empty` was the one cell that
  exceeded its per-cell budget
- `issues/050` — the other fixture-expressiveness gap
