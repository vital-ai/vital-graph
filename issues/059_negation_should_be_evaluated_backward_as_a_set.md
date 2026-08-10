# Negation Traverses Forward Per Entity When It Should Run Backward Once

## Status: OPEN — prerequisites built and wired, emitter not started

Everything the rewrite depends on is committed and tested:

* `edge_type_uuid` (`issues/060`) — a typed hop is a column predicate, 42s -> 1.5s
* `{space}_edge_fanout` — per edge type x relation type x direction, with p99/max
* `choose_direction` — validated on all three fixtures, and it declines the
  dangerous case: `worksFor` gets FORWARD because its backward tail is 886
* `extract_traversal` — reads the edge chain out of a BGP
* a gate in `_emit_two_phase` that declines when the probe amplifies forward
* `sp_kg_rel` — the only fixture that can refute a wrong direction rule

**The emitter is not started, and the remaining work is larger than this issue
first implied.** The `NOT EXISTS` body is a ONE-hop traversal — the outer query
has already walked entity -> frame -> frame — so the 700ms measurement came from
restructuring the whole query backward, not the sub-plan. See the correction
below.

## Status: OPEN, measured 2026-08-10 — 285x on the table, `sp_lead_synth_100k`

    current engine (anchor + forward probe per entity)   > 200 s (timeout)
    backward, existence-first, set-wise                    ~700 ms

Same question, same data, same indexes, same answer (0 rows).

## The two plans

The engine evaluates `not_exists` by anchoring on the entity-type BGP, scanning
all 100,000 entities in `subject_uuid` order, and probing forward from each:

    for each entity:  entity -> frame -> frame -> NOT EXISTS(slot of type X)

The backward form starts from the constrained end and does each hop once, as a
set:

    slots WHERE hasKGSlotType = MQLRating        index range scan     100,000
      <- edge (dest -> source)  x3 hops          set-wise, DISTINCT   100,000
    entities EXCEPT that set                     anti-join                  0

Nothing here is a missing index — every leaf in the forward plan is already an
`Index Only Scan`. The difference is that the backward form does the traversal
**once over 100,000 rows** instead of **100,000 times over a traversal**.

## Why the engine cannot pick it

`emit_slice._emit_two_phase` anchors on the entity-type BGP because it needs
`subject_uuid` order for O(page) paging, then probes forward. The selective
criterion always lands *inside* the probe. There is no path in the plan space
that starts from the slots and walks back — so this is not an estimation problem
the planner could solve with better statistics, and not one an index fixes.

It is also actively fenced: `emit_bgp_exists` appends `OFFSET 0` precisely to
stop PostgreSQL flattening the correlated subquery into a semi-join, because
flattening destroys the ordered scan that makes paging O(page). That fence is
correct for a dense match set and is exactly what prevents the good plan when the
match set is sparse or empty.

Adding a selective criterion does not help. `eq` on a text slot runs in ~1 s
alone; combined with the negation the query still times out, because phase 1
still scans all 100,000 entities and `eq` becomes another probe rather than the
driver.

## Scope

Every remaining timeout in `issues/053` has this shape — a selective constraint
sitting somewhere anchor-and-probe cannot drive from:

| cells | why |
|---|---|
| `not_exists` x2 | this issue |
| `eq`/DateTime | probes 100,000 times for a value almost nothing matches |
| `gt`, `gte` /DateTime | broad match set, blocking sort |

## Caveats on the 700 ms

Honest limits of the measurement:

* The hand query walks **untyped** edges. With type discrimination added it is
  **22 s**, not 700 ms — see below, that is the edge-table issue, not this one.
* Because this fixture's answer is 0, an over-approximating traversal still
  yields 0. The timing is demonstrated; semantic equivalence in general is not.
* It computes the whole anti-join rather than a page. For an empty answer that is
  the same thing; for a non-empty one, ordering and limiting the result set is
  cheap relative to the traversal.

## Correction to the 700ms measurement

The hand-written backward query anti-joined the entity population against
"entities reachable from a matching slot". That is only the right answer because
in `sp_lead_synth_100k` **every** entity has the frame path, so "entities with
the path" and "all entities" coincide.

In general the answer is

    entities WITH the positive path   MINUS   entities with the path AND the slot

and both sides have to be computed. The 700ms figure is therefore a floor rather
than an estimate of the finished thing — a shortcut the fixture happened to
permit, and the kind that makes a measurement look better than the
implementation will be. Worth stating plainly before anyone plans around it.

## Cost to implement

Closer to the existing edge-table rewrite than to the paging work: a plan-level
pass that recognises "anti-join over a traversal" and emits the backward set
form, rather than a change to plan *selection*.

* **Recognition** — a `KIND_FILTER` holding a negated `ExprExists` over a
  traversal whose constrained end is a bound constant. The shape is already
  detected by `emit_slice._foldable_exists_join`.
* **Direction** — the edge table already indexes both ways
  (`idx_*_edge_src_dst`, `idx_*_edge_dst_src`), so backward hops need no new
  structure.
* **The hard part** — deciding *when*. The backward form is right when the
  negation's constrained end is selective and the result sparse; the current
  forward probe is right when matches are dense (it delivers 47-163 ms on
  `not_has`/`not_has_any`, which this must not regress). That is D3 in
  `two_phase_kgquery_paging_plan.md`, and this issue is its most concrete case.
* **Verification** — `test_comparator_coverage` pins all six negation cells, and
  `perf_shape_matrix` compares full result sets against the rewrite forced off.

Rough order: comparable to `rewrite_edge_table` (~1 pass, ~300 lines with
guards), plus the gate. The gate is the risk, not the rewrite.

## Related

- `issues/060` — the edge table has no type column, which is why the typed
  backward query is 22 s instead of 700 ms
- `issues/053` — the sweep; this covers most of what remains
- `issues/057` — the forward fold, which closed 4 of 6 negation cells
- `two_phase_kgquery_paging_plan.md` — D3
