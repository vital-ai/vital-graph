# The Geo Table Is Not Rebuilt On Restore

## Status: FIXED. Found by the `issues/168` audit, unmeasured.

`bulk_export.import_space` TRUNCATEs and re-COPYs the core tables, then rebuilds
a fixed list of derived tables. Geo has never been on that list. So after a
restore, `{space}_geo` still holds points extracted from the PREVIOUS contents.

This is the same defect `issues/168` fixed for `entity_slot_sort`, one table
over, and it matters for the same reason: GEO IS DERIVED FROM THE QUADS, so a
stale geo table can produce WRONG ANSWERS to a geo query — points for entities
that no longer exist, and none for the entities that now do.

That distinguishes it from the other two absentees, which are plan-only:

    geo               derived from quads   -> CAN BE WRONG
    value histograms  plan input           -> degraded plans, correct answers
    edge/entity fanout plan input          -> degraded plans, correct answers

## What is not known

Whether it belongs INLINE or DEFERRED, because its cost has not been measured.
That is the whole question, and `issues/168` is the precedent for getting it
wrong in both directions:

  * rebuilt inline, it runs under the ACCESS EXCLUSIVE lock the restore's
    TRUNCATE holds until COMMIT, so a slow rebuild blocks every query on the
    space — the outage `issues/161` is about;
  * left as it is, a restore serves wrong geo answers with no error.

`populate_geo` runs per graph and scans quads for lat/lon. On a small space that
is likely trivial and belongs inline; on a large one it is the `entity_slot_sort`
situation again. MEASURE IT BEFORE CHOOSING.

## The safe answer either way

Whatever the cost, the restore must not leave the table describing the previous
contents. If the rebuild is cheap, run it inline. If it is not, EMPTY the table
at restore and let a job repopulate it — but only once the geo read path
declines on an empty table rather than returning "no points", which is the exact
trap the sort path had (`issues/168`): an empty derived table read as an
authoritative empty answer.

CHECK THAT FIRST. If the geo read path cannot distinguish "no points here" from
"not built yet", emptying it is worse than leaving it stale, and the deferral
option is closed until that is fixed.

## Related

`issues/168` — the same omission for `entity_slot_sort`, with the sort-path trap
described.
`issues/167` — under a block-list, a restore would take a block covering geo too,
which is the general form of this fix.


---

# FIXED, INLINE — and the deferral option was closed by measurement

The issue asked whether geo belongs inline or deferred, and said to measure
before choosing. Measured:

    lead_nurture_grouped (74.2M quads)    2,268 ms
    wordnet_frames        (8.9M quads)      476 ms

against the 45 minutes `entity_slot_sort` takes on the same space. Detection is
datatype-driven, so the cost tracks geo literals rather than the size of the
space. Cheap enough to hold the restore's lock for.

## The deferral option was not merely worse, it was unavailable

The issue flagged the precondition: emptying the table is only safe if the geo
read path DECLINES on an empty table rather than answering "no points". It does
not. The read is a correlated subquery —

    (SELECT MIN(ST_Distance(location, ST_MakePoint(...)::geography))
       FROM {space}_geo WHERE subject_uuid = ... )

— and `MIN` over no rows is NULL, so a geo filter over an empty table SILENTLY
EXCLUDES EVERY ENTITY. Stale answers from the previous contents and empty
answers from a truncated table are both wrong, and unlike the slot-sort table
there is no marker gating the geo read to decline on.

So the choice was never inline-versus-deferred. It was inline-versus-wrong.

## The fix

`import_space` rebuilds geo per registered graph, after registering them (the
catalog is what it iterates). A failure logs at WARNING and says the space may
answer geo queries from the previous contents — not debug, because that is a
wrong answer rather than a slow one.
