# `compute_edge_fanout` Fails On Every Import Round Trip

## Status: OPEN. Reproduces on every `test_bulk_export` round trip.

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
