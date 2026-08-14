# 055 — fixture loaders and the tests that use them target different clusters

## Status: OPEN — the port disagreement is still there, and it bit again 2026-08-14

Loader split-brain fixed; the seed/test port disagreement remains by design and
is the part that needs a decision.

**It recurred while loading a new fixture on 2026-08-14.**
`scripts/load_wordnet_csv.py` still defaults to port 5433 (the container), so
loading a space created on the HOST cluster failed with

    psycopg.errors.UndefinedTable: relation "sp_graph_synth_10k_rdf_quad" does not exist

after the space had been created successfully on 5432. The failure was loud, so
nothing was corrupted — but it is the benign half of the hazard the loader's own
docstring warns about. The other half is a space of the SAME NAME existing in
both clusters, where the load silently truncates and repopulates the wrong one.

Workaround in use: `VG_TEST_PG_PORT=5432 VG_TEST_PG_USER=postgres
VG_TEST_PG_PASSWORD= python scripts/load_wordnet_csv.py ...`, recorded in
`tests/performance/graph_fixtures.py` so the next person does not rediscover it.

That this needed rediscovering, and a workaround written into a fixture module,
is the argument for making the decision rather than continuing to document it.

## Symptom

`test_comparator_coverage.py` reported `SKIPPED [26] space sp_lead_types does
not exist`. The space existed. It was in the other cluster.

    port 5433 (container):  sp_lead_types, sp_lead_empty, sp_lead_synth_10k
    port 5432 (host):       sp_lead_synth_10k, sp_lead_synth_100k,
                            sp_lead_dup, sp_lead_depth1

## Cause 1 — the loader wrote to two clusters at once

`scripts/load_wordnet_csv.py` had two independent sets of connection defaults:

    dsn()                    port 5433, user postgres, password 'testpass'
    _resync_auxiliary(...)   port 5432, user postgres, password ''

Run with no env overrides, it `COPY`s the quad and term tables into the
container cluster and then resyncs auxiliary tables **on the host cluster**,
against whatever space happens to share that name there.

The resync is not incidental. Its own docstring says it is "Not optional" and
cites issues/041: `COPY` bypasses the incremental sync hooks, so a pre-existing
`{space}_edge` survives the load describing the space's *previous* contents, and
`ensure_edge_table` will not notice because it only checks that the table exists
and is non-empty. Row counts can match exactly while every uuid is wrong, and
frame traversals then return zero rows with no error.

Pointing that step at a different database is the same failure with a longer
fuse — and on the host cluster it is worse than a no-op, because it will happily
resync a *real* space of the same name.

**Fixed:** both now come from one `pg_env()`.

## Cause 2 — seeding and testing disagree by default

Still true, and deliberate enough that it should be decided rather than patched:

    scripts/perf_seed_data.pg_params()      VG_TEST_PG_PORT default "5433"
    tests/performance/conftest.py           VG_TEST_PG_PORT default "5432"

So a fixture built with defaults lands where tests run with defaults will not
look. Nothing errors — the fixture builds fine and the tests skip.

## Why this mattered more than a skip usually does

The skip is silent, and it hid a real defect. `gt` on a numeric slot was timing
out at 60 seconds (issues/054) while the suite that would have caught it
reported 26 skips and a green run. The fixture had been present earlier in the
same session, so the tests had passed against it once; nothing announced when
that stopped being true.

Two things follow, neither done yet:

* **The perf suite should fail rather than skip when a fixture it is named after
  is missing** — at least under an opt-in strict flag used in CI. A test that
  cannot run is not a test that passed.
* **One default for which cluster is which.** Aligning `perf_seed_data` to 5432
  is the smaller change but risks the container workflow; the alternative is to
  make both read a single shared helper and force the choice to be explicit.

## Meanwhile

`scripts/load_lead_types_dataset.sh` exists so this fixture is one command to
rebuild, and it pins the connection defaults to what
`tests/performance/conftest.py` reads. Reconstructing the arguments by hand is
how it ended up in the wrong cluster.
