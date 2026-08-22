# A Non-Selective Entity-Type Predicate Costs 6x Buffers and 10x Time

## Status: OPEN — measured 2026-08-22. Cause localised to intermediate row
## growth; the emitter change that would fix it is NOT yet identified.

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

## Reading, and what has NOT been established

800,000 is close to 100,000 entities x the per-entity frame/slot fan-out, which
suggests the type predicate is being joined against the ALREADY-EXPANDED row
set — every frame and slot row of an entity re-checked for the entity's type —
rather than applied to the entity set before the expansion, where it would cost
one probe per entity and could not multiply anything.

That is a reading of the row counts, not a proven cause. The emitter has not
been traced, and no fix is proposed here. Establishing it means finding where
the `hasKGEntityType` triple is placed in the generated SQL relative to the
frame and slot joins, and whether the join order is chosen by the generator or
left to PostgreSQL.

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
