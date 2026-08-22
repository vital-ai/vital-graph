# A Non-Selective Entity-Type Predicate Costs 6x Buffers and 10x Time

## Status: OPEN — measured 2026-08-22 and traced to the PLAN SHAPE, not to the
## optimizer. A first trace blamed the search in `_try_selective_driven` and was
## WRONG; the correction is below. No fix applied.

Adding an entity-type criterion that matches **every** entity makes the same
KGQuery 5.9x more expensive in buffers and 9.8x slower. It filters nothing and
costs six times the work.

## Measured

`sp_lead_synth_100k`, `contains "CA"` on `CompanyStateCode`, page 25. Both
sides warmed first, then alternated, median of three — the cold-first ordering
that produced this question in the first place is exactly what `issues/081`
warns about:

    entity type   needs_ordered_scan   median      buffers
    generic       False                 6.37s      4,043,455
    specific      False                62.56s     23,861,490
    ratio                               9.81x          5.90x

Both return the same 25 rows from the same 9,220 candidates.

## The type predicate is not a filter here

Every entity in the fixture carries it:

    subjects with vitaltype = KGEntity                     100,000
    subjects with hasKGEntityType = urn:acme:kg:entity:Lead 100,000

So `specific` and `generic` select the identical entity set. The 6x is pure
overhead.

## Where it goes: intermediate rows, not extra output

The two plans have the same shape — `Nested Loop / Limit / Unique / Sort` over
9,220 candidates — and diverge underneath. Rows at matching depths:

    depth                       generic     specific
    below the text criterion    100,000     100,000
    next                        100,000     700,000
    next                        100,000     800,000
    Gather                      100,000     800,000

The generic arm holds 100,000 rows from the bottom of the tree upward. The
specific arm expands to 800,000 and is then reduced back to 100,000 and finally
to 9,220. Same answer, eight times the intermediate material.

## Traced: the restructuring is never even considered

The two arms produce structurally different SQL.

**Generic** isolates the entity set as its own subquery and joins it once:

    FROM (SELECT q0.subject_uuid AS v0__uuid
          FROM ..._rdf_quad AS q0
          WHERE q0.predicate_uuid = <vitaltype>
            AND q0.object_uuid = <KGEntity> AND q0.context_uuid = <graph>) ...
    JOIN (<the whole frame/slot walk>) AS j1 ON j0.v0__uuid = j1.v2__uuid

**Specific** inlines the type triples into one flat join tree, correlated but
positioned among the frame and slot joins:

    JOIN ..._rdf_quad AS q0 ON q0.predicate_uuid = <hasKGEntityType>
       AND q0.object_uuid = <Lead> AND q0.context_uuid = <graph>
       AND mv0.source_node_uuid = q0.subject_uuid

The joins ARE correlated — this is not a cartesian product. The difference is
that the generic shape reduces to the entity set once, while the flat shape
lets the walk expand first.

The emitter's own decision log says why, and the two arms fail for **different**
reasons:

    generic   selective-driven declined: driver 50000 not selective vs anchor 100000
    specific  selective-driven declined: no 2-child JOIN within 6 hops

The generic arm was evaluated and declined on the merits. The specific arm was
never evaluated at all. Instrumenting the decline shows why — `node=None`:

`emit_slice.py:589`

    node = plan.child
    for _ in range(6):
        if node is None or node.kind == KIND_JOIN:
            break
        node = node.children[0] if node.children else None
    if node is None or node.kind != KIND_JOIN or len(node.children or []) != 2:
        return None

The search follows **one spine**, `children[0]`, for six hops, and `node`
becomes `None`.

### That reading was wrong, and the correction is the finding

The obvious inference — the spine misses a join that is off to one side — is
false. Replacing the spine walk with a breadth-first search over every child
declines identically. Dumping the plan trees shows why:

    generic                       specific
    order                         order
      distinct                      distinct
        project                       project
          filter                        filter
            join   (2 children)           bgp   (0 children)
              bgp
              bgp

**The specific query has no JOIN node at all.** Its entire pattern is one BGP,
so there is nothing for a join-restructuring pass to restructure, and
`_try_selective_driven` is right to decline. The generic query is a JOIN of two
BGPs, which is what gives it a two-sided shape to work with — an entity side
that reduces to 100,000 rows, joined once to the walk.

So the cost is decided BEFORE the optimizer sees it, by whatever builds one BGP
in one case and a join of two in the other. Adding the entity-type criterion is
what collapses the plan into a single BGP; the flat SQL join tree, and the
800,000 intermediate rows, follow from that.

### What that means for a fix

Widening the optimizer's search — the change this issue previously proposed —
is pointless. It was written, tested against this shape, and made no
difference: the decline is correct.

The question is instead why the plan builder emits a single BGP once an entity
type is present, and whether it should emit the same JOIN-of-two-BGPs shape it
produces without one. That is in the plan construction, not in `emit_slice`,
and it has not been traced.

## Next step

Trace the plan builder: find where the entity-type criterion causes one BGP
instead of a JOIN of two, and establish whether the single-BGP form is
deliberate. Only then is there a fix worth measuring.

Note for whoever picks this up: the perf baseline `query.json` was stale on
statistics as of 2026-08-22 — 20 benches differ from it, most as `shared_read`
(cold pool) and some as genuine plan flips, with
`stats.fixture_last_analyze` moving 2026-08-20 -> 2026-08-22. Compare a change
against a control run taken in the same session, not against that baseline,
until it is re-promoted.

## Why it matters beyond the benchmark

`needs_ordered_scan=False` on both, so the fence is not involved. A caller
asking for a typed entity list — the ordinary case, since real queries name an
entity type — pays this on every page. And the cost is invisible in the small
fixture: the same shape on the 10k fixture finishes inside the fence bench's
20 s probe, which is why it surfaced only as a skip.

## How it was found

`issues/117`, investigating six skipped shapes in the fence bench. Four were a
needle that could not match; two were cold cache. This is what remained after
both were accounted for, and it is the only one of the three that is a product
problem rather than a test defect.
