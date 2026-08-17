# KGType Search Finds Nothing on the Test Stack

## Status: NO LONGER REPRODUCES 2026-08-17 — cause still NOT established

All eight `TestKGTypeSearch` cases pass, including the six that failed. Nothing
was done to the search path; two things changed underneath it on 2026-08-17:

* **`issues/102`** — the stack could not run a PARALLEL QUERY at all (Docker's
  default 64 MB `/dev/shm`, no `shm_size`). Fixed with
  `dynamic_shared_memory_type = sysv` and a `docker restart`, which also
  restarted every connection.
* **`issues/055`'s schema repair** — `sp_kg_types` was one of eight spaces
  missing `{space}_entity_slot_sort`, created by `migrate_space_schema --all`.

**Neither is a satisfying explanation and I am not claiming one.** The search path
does not reference `entity_slot_sort` (grepped), and the table is still empty for
this space, so that repair is unlikely to be it. A parallel-query failure raises
`DiskFullError` rather than returning zero rows, which is what these tests saw —
so `issues/102` does not obviously fit either. The postgres restart is the third
candidate and the least falsifiable.

What can be said: the symptom is gone, it was never attributed, and the original
question — did this predate the move to the test stack — was never answered
because the dev app was deliberately stopped.

**Left open deliberately rather than closed.** A test that starts passing for
unknown reasons can stop passing for the same unknown reasons. If these six fail
again, the first thing to check is whether a parallel plan is involved, and the
second is whether the app container was restarted since the space was created.

Six `tests/api/test_kgtypes_api.py::TestKGTypeSearch` cases fail on the docker
test stack:

    test_keyword_search              assert 0 >= 1
    test_fts_search
    test_vector_search_man_finds_person
    test_vector_search_restaurant
    test_vector_search_company
    test_hybrid_search

The fixture creates three types through the API and asserts the create
succeeded, then every search returns zero.

## What is known

* The failure includes **keyword** search, which needs no embeddings, so it is
  not simply the vector auto-sync being slow.
* `sp_kg_types` exists on both clusters with the same search infrastructure —
  2 vector indexes and 2 fts indexes on each. Not a missing-index gap.
* Listing `sp_kg_types` returns `status: empty, total_count: 0` after the run,
  but the fixture cleans up, so that observation is not evidence.
* `test_trigger_maintenance` and `test_query_by_parent_document` also failed in
  the full run and **pass in isolation**, so those two are ordering-dependent
  and separate from these six.

## What is NOT known, and why

**Whether these failed before the suite moved to the test stack.** The suite
previously ran against the dev app on :8001 with the host database; that app is
currently stopped, so there is no comparison to make. I did not restart it to
find out, because it was stopped deliberately.

The stack move is not an obvious cause: these tests create their data and search
for it through the SAME server, so the routing change cannot split them across
two systems the way it could for tests mixing API calls with direct SQL. But
"not an obvious cause" is not "ruled out", and the honest state is unestablished.

## How to settle it

Start the dev app, point `tests/api` back at it
(`LOCAL_CLIENT_SERVER_URL=http://localhost:8001` and
`VG_TEST_PG_PORT=5432 VG_TEST_PG_PASSWORD=`), and run the same six. If they fail
there too, this predates the move and is a real search defect. If they pass,
something about the test stack's `sp_kg_types` differs and the next question is
what.

## Related

- `issues/099` — the stack split these were found during
- The two ordering-dependent failures above are worth their own look; a test
  that passes alone and fails in a suite is usually shared state
