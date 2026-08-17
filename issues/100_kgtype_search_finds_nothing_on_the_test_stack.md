# KGType Search Finds Nothing on the Test Stack

## Status: OPEN — provenance NOT established, 2026-08-16

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
