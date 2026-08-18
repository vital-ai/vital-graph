# KGType Search Finds Nothing on the Test Stack

## Status: ROOT CAUSE FOUND 2026-08-18 — the WRITE failed, not the search

`sp_kg_types` was one of the eight spaces missing `{space}_entity_slot_sort`, and
`add_rdf_quads_batch_bulk` maintains that table. The app log for the exact window:

    01:02:28.558  add_rdf_quads_batch_bulk(sp_kg_types) failed:
                  relation "sp_kg_types_entity_slot_sort" does not exist
    01:02:32.677  (same)
    01:04:24.287  (same)
    01:05:34.872  (same)

Four failures between 01:02:28 and 01:05:34 UTC — 21:02 to 21:05 EDT — and this
issue was filed at 21:06. Nothing was stored, so every search found nothing:
keyword, FTS and vector alike, which is exactly why all six failed together and
why the "keyword needs no embeddings" observation never narrowed anything.

It stopped reproducing because `migrate_space_schema --all`, run on 2026-08-17 to
close the schema-drift gap, created the missing table. There have been no such
errors since.

### The reasoning that missed it, twice

**"The search path does not reference `entity_slot_sort` (grepped), and the table
is still empty for this space, so that repair is unlikely to be it."** Both halves
true, and the conclusion wrong: the WRITE path references it. I grepped the side
that reads and concluded about the side that writes. The table being empty was
consistent with the failure, not evidence against it.

The later narrowing — "search returning zero means the index was empty, so the
failure is in the sync" — was right about the search and wrong about the sync.
The index was empty because the quads were never written, one layer below.

### A related defect, NOT this one

`add_rdf_quads_batch_bulk` catches the exception, logs it, and `return 0`. One
caller in `kg_backend_utils.store_objects` checks for that — `if inserted == 0
and len(quads) > 0` — and returns `success=False`. That check never fired here:
there is no "store_objects: 0 quads inserted" line in the log, so the kgtypes
create reaches a caller that does not check. A write that fails and returns 0 is
indistinguishable from a write of nothing, and only one caller tells them apart.
Worth its own investigation.

### What this says about the earlier eliminations

They were right and now have a cause to point at. The port confusion and stale
image were ruled out on timestamps; the search path is exonerated because it was
never reached. The instrumentation added on 2026-08-18 would have found this in
one run — it asserts the index is populated before searching, and the index was
empty because the write failed.

Attributed to a class on 2026-08-18, which the issue previously could not do.

Sampling the index tables once a second while the fixture runs:

    t=0-2s   quads=0   fts=0  vec=0     types not created yet
    t=3-5s   quads=21  fts=3  vec=3     created AND indexed inside one second
    t=6s+    quads=0   fts=0  vec=0     fixture cleaned up

`fts=3, vec=3` is exactly the three types created. When healthy, indexing
completes in about a second — well inside the fixture's 3-second wait, with no
race worth speaking of.

**So a search returning zero means the index was EMPTY, not that the search was
wrong.** The search path returns results whenever rows are present, and the rows
appear almost immediately. That exonerates the query side and puts the failure in
the sync that populates `_fts_kgtype_default` / `_vec_kgtype_default`.

What is still unknown is why the sync would not have run on 2026-08-16. Worth
noting alongside: the app container was logging `_poll_space` errors for spaces
that had been deleted, repeatedly and with tracebacks, and that worker was given
a skip list the same day. Whether the kgtype auto-sync shares that machinery, and
whether a wedged worker stops it, has NOT been checked — it is the first thing to
look at if this returns, and it is checkable now that the fixture reports index
counts.

The `4722c78` timeline still rules out the port confusion and a stale image; see
below.

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

### RULED OUT: the 8001/8002 confusion, and a stale app image

Both are the obvious suspects and the timestamps exclude them:

    image built        2026-08-16 20:55:05 EDT
    container started  2026-08-16 20:55:08 EDT
    issue filed        2026-08-16 21:06        (commit 4722c78)

The app container is running the SAME image in the SAME container it was eleven
minutes before these failures were recorded, and has not been rebuilt or
restarted since. And this issue was filed IN `4722c78` — the commit that made
every suite follow one stack configuration — so the failures were observed AFTER
the port fix, against the intended target.

**That narrows it to the database side**, because the application side is
provably unchanged between failing and passing. What happened in between:

  * postgres restarted, which recycled every pooled connection the app held
  * `dynamic_shared_memory_type` went posix -> sysv (`issues/102`)
  * `sp_kg_types` gained an empty `{space}_entity_slot_sort` (`issues/055`)

The third is already unlikely — the search path does not reference that table and
it is still empty. Of the remaining two, the connection recycle is the one that
fits the SHAPE of the symptom: zero rows rather than an error. A pool holding
connections whose cached statements were prepared against an earlier state of the
space would answer, and answer emptily, which is what was seen. That is a
hypothesis and it is untested — recorded so the next person starts there rather
than at the port.

### RULED OUT: the test datasets loaded on 2026-08-17

`sp_lead_synth_10k` was loaded and `sp_graph_skew_2k` regenerated, so the obvious
question is whether these tests simply found data they had been missing. They did
not, and it is checkable rather than arguable: `search_env` CREATES its three
types through the API into `SP_KG_TYPES` and searches for those. It reads no
fixture. `sp_kg_types` was not among the spaces loaded — it received one empty
`entity_slot_sort` table from the schema repair and nothing else.

### A BETTER LEAD than the connection-pool guess above

Checking that turned up the layer these searches actually depend on:

    sp_kg_types_fts_index       2 rows
    sp_kg_types_vector_index    2 rows
    sp_kg_types_rdf_quad        0 quads

The types are searched through `fts_index` and `vector_index`, which a background
sync populates — and `search_env` sleeps 3.0 s waiting for exactly that. A sync
that is slow, wedged or not running returns an EMPTY result rather than an error,
which is the symptom, and it explains all six at once: keyword and FTS read
`fts_index`, the three vector cases and the hybrid read `vector_index`. The
earlier note reasoned that keyword search "needs no embeddings" and so could not
be the vector sync — true, and it does need the FTS index, which the same worker
class maintains.

That is a better hypothesis than the connection recycle, and it is testable while
the failure is live: check whether `fts_index` has a row for each created type
before the search runs.

**Not evidence:** the app log carries 46 `does not exist` warnings today, all from
maintenance jobs chasing spaces dropped during this session's cleanup. They are a
consequence of today, not a record of yesterday.

### The lead is now instrumented (2026-08-18)

`search_env` checks, after its 3-second wait, that the created types actually
reached the index, and warns naming this issue if they did not. That is the one
question that has to be asked WHILE the failure is live: by the time anyone
looks, the fixture has cleaned up and the evidence is gone.

Measured while building it, and it corrected the guess in the section above:

    sp_kg_types_fts_index        2 rows   — the index DEFINITIONS
                                            (document_segments, kgtype_default)
    sp_kg_types_fts_kgtype_default        — where the indexed rows actually live
    sp_kg_types_vec_kgtype_default        — likewise for vectors

The first version of the check counted `_fts_index` and would have warned on
every healthy run, because two rows there means two indexes are CONFIGURED, not
that two types were indexed. The per-index tables hold 0 rows at rest and at
least 3 during the fixture, which is also the first positive evidence that the
sync is running at all — something this issue could never establish while the
failure was live.

A warning rather than an assertion: keyword search reads the FTS index and the
vector cases read the other, so a partial sync should still let some of the six
speak for themselves, and a hard failure would replace six informative failures
with one uninformative error.

**Left open deliberately rather than closed.** A test that starts passing for
unknown reasons can stop passing for the same unknown reasons. If these six fail
again, restart the app container FIRST and see whether that alone fixes it: that
is the cheapest way to confirm or kill the connection-state hypothesis, and it
was never tried while the failure was live.

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
