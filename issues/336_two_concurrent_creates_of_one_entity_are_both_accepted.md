# 336: Two concurrent creates of one entity are both accepted, and the entity is then unreadable as a graph

## Status: FIXED 2026-11-11 (uncommitted), tested locally. Production data repaired: not yet.

Reported from production (server 0.0.101-prod line). 27 entities in two spaces
were affected between 2026-10-20 and 2026-11-11, and new ones were appearing
every few days.

## The defect

Entity `create` (`KGEntityCreateProcessor._handle_create_mode`) checked "does
any of these URIs exist?" with `batch_check_uris_exist`, and then called
`store_objects`. These were two separate operations, with no lock and no
transaction around them. Two clients that each read not-found and created the
same entity at once both passed the check, and **both creates were accepted**.

Every client-supplied property carries the same value on both requests, so the
quad primary key silently dedupes it. The two timestamps
(`hasObjectCreationTime` and `hasObjectModificationDateTime`) are stamped per
request, so the entity ended up with two values of each. From then on:

- the graph read (`include_entity_graph=true`) cannot build the entity from a
  list of datetimes, logs `SKIPPING entity`, and returns `found` with 0 objects;
- the entity-only read and the frames read still find it;
- a create retry gets `already_exists`, so a caller that creates on an empty
  graph read loops until it gives up.

This is the race `issues/173` fixed for upsert. `issues/174` then locked the
other write paths but did not list entity create.

Reproduced against a local server: two concurrent creates per URI for 20 URIs
were all accepted, and all 20 graph reads returned 0 objects.

## The fix

`SparqlSQLBackendAdapter.create_objects_atomic` follows the pattern of
`upsert_objects_atomic`. In one transaction it:

1. takes `lock_entities` on the request's entity URIs;
2. re-checks every URI in the request (the entity and its sub-objects) with `_present`;
3. writes with `add_rdf_quads_batch_bulk` on the same connection.

The second of two racing creates waits on the lock, then sees the first one's
committed subjects and gets `already_exists`. A create and an upsert of one
entity now serialize too, because they share the lock.

The early `batch_check_uris_exist` read stays as the fast answer for the common
case. A backend without the atomic path falls back to the old sequence and logs
that it is not serialized.

The processor's own `update` mode is still delete-then-store, but the endpoint
never reaches it: `operation_mode=update` goes through `update_entity_graph`,
which already holds the entity lock.

## Tests

`tests/integration/test_concurrent_creates_of_one_entity.py` has three tests:

- **10 URIs, two concurrent creates each:** exactly one `created` and one
  `already_exists` per URI, one value of each timestamp, and the graph reads
  with all 3 objects.
- **A sub-object clash** found only by the locked re-check is refused, and
  nothing is written.
- **Negative control:** with the atomic path switched off, the same race has
  both creates accepted and stores two creation times. Without this, the first
  test could pass only because the window was never hit. It passed on 4 of 4
  runs.

## Repairing affected data

`scripts/repair_duplicate_single_valued.py` keeps the earliest creation time
and the latest modification time. It now:

- takes `--ssl` and `--statement-timeout` (default 15min), so it runs against a
  managed database with a 60 s role default;
- runs a dry run as a read-only session;
- lists the affected subjects with `--subjects`.

It was tested end to end on the reproduction above: 40 rows were removed, and
all 20 graphs read again without a restart.
