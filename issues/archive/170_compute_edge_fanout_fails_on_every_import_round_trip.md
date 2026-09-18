# `compute_edge_fanout` Fails On Every Import Round Trip

## Status: FIXED. Reproduces on every `test_bulk_export` round trip.

    resync_all(inttest_exp_dst_*): edge fan-out skipped
      (null value in column "edge_type_uuid" of relation
       "inttest_exp_dst_*_edge_fanout")

`compute_edge_fanout` raises a NOT NULL violation when run against a
freshly-imported space. It is caught and logged as a warning, so nothing fails —
the space simply ends up with no edge fan-out statistics.

## Consequence

DEGRADED PLANS, NOT WRONG ANSWERS. Fan-out is a plan input: without it, any
choice that consults edge fan-out is made without it. `sync_edge_fanout`
describes itself as "the statistic nothing else expresses", so the plans it
informs fall back to whatever the other statistics support.

## Why it was not noticed

It was the FIRST line of a four-warning cascade that read like one failure:

    edge fan-out      null value in column "edge_type_uuid"   <- the real one
    entity fan-out    current transaction is aborted          <- collateral
    geo               current transaction is aborted          <- collateral
    final ANALYZE     current transaction is aborted          <- collateral

The other three were caused by the first: `resync_all`'s optional steps caught
their exceptions but ran inside a transaction, where a raised statement aborts
everything after it. That is fixed (`534a437`, each optional step now runs in
its own SAVEPOINT), and this warning now appears alone — which is how it became
legible.

## Hypothesis, untested

An ORDERING problem rather than a data one. The derivation reads an edge type
that the restore has not populated at the point it runs, so it derives a NULL
`edge_type_uuid` and the insert rejects it. If so it is fixed by ordering the
rebuild after whatever supplies the type, or by having the derivation skip rows
it cannot type rather than inserting them.

Worth checking whether it also fails outside an import — the same NULL could
arise on any space whose edge rows lack a type, in which case this is not about
restore at all.

## Reproduce

    python -m pytest tests/integration/test_bulk_export.py::test_export_import_round_trip \
        -q --log-cli-level=WARNING


## Related

`issues/171` — a statistic whose absence went unremarked this long should have
to justify its rebuild. Unlike `entity_fanout` this one IS read, so it is a
measurement question rather than a deletion.


---

# FIXED. The hypothesis was wrong; the cause is simpler.

The issue guessed an ORDERING problem — the derivation reading an edge type the
restore had not populated yet. It is not. The cause is that the guard checks the
COLUMN EXISTS and never that it is POPULATED:

    has_type = SELECT 1 FROM information_schema.columns
                WHERE table_name = $1 AND column_name = 'edge_type_uuid'

An edge carrying `hasEdgeSource` and `hasEdgeDestination` but NO `vitaltype`
derives a NULL `edge_type_uuid`. The aggregate propagates it and the insert
violates the fan-out table's NOT NULL, so ONE untyped edge discards the whole
space's statistics.

REPRODUCED DIRECTLY, not inferred: a space computing 6 fan-out rows cleanly,
plus a single untyped edge, gives `NotNullViolationError: null value in column
"edge_type_uuid"`. It failed on every `bulk_export` round trip because that
fixture builds edges from exactly those two predicates and no type.

Real data carries a vitaltype, which is why no populated space showed it — three
checked at 5,277,000 / 570,696 / 4,977,000 edges, zero NULLs. A rare, legal
shape that was fatal.

## The fix

Untyped edges are EXCLUDED from the aggregate and the count is logged at
WARNING. Excluded rather than given a sentinel, unlike `relation_type_uuid` on
the same table: that sentinel means "not a relation", which is a real category,
whereas "no type at all" is not one this statistic answers questions about.
Fan-out is per edge type; pooling untyped edges under a zero uuid would invent a
type and report a fan-out for it.

WARNING rather than debug because dropping rows quietly is how a statistic
drifts from the data it describes.

## Three tests, each verified to fail against the old code

  * an untyped edge does not fail the derivation;
  * the typed edges are STILL COUNTED — guarding the over-correction, where a
    WHERE that also filtered typed rows would "not fail" while silently
    emptying the statistic;
  * no row is written under the zero-uuid bucket.

## Why it took this long to see

It was the first line of a four-warning cascade that read like one failure. The
other three were `resync_all` catching exceptions inside a transaction that was
already aborted. Fixing that cascade (`issues/168`) is what made this legible —
the bug was buried in noise it had itself caused.
