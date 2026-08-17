# 055 — fixture loaders and the tests that use them target different clusters

## Status: FIXED 2026-08-17 — one resolver, and the target is now announced

The suites were unified earlier. The NINETEEN maintenance scripts were not, and
that is where it kept biting: they carried their own copies of the five
connection defaults across two env families that could not see each other.

    VG_TEST_PG_*   10 scripts, all defaulting to port 5432
    VG_PG_*         7 scripts, all defaulting to port 5432
    the loaders     2 scripts, defaulting to 5433 — and the suites read 5433

So exporting the variable the tests use left half the scripts pointed at the
other cluster. Hit twice in one session on 2026-08-17: `migrate_space_schema.py`
took `VG_TEST_PG_PORT=5433` and `repair_derived_tables.py` ignored it, needing
`--port 5433` passed by hand.

**For a migration script this is worse than for a loader.** A loader writes a
fixture where nobody looks. A migration ALTERS whichever cluster it reached, and
the host carries same-named spaces, so it succeeds and reports success — which
is `issues/099` one layer up.

### What changed

* `vitalgraph_sparql_sql_dev.db.get_connection_params` learned the `VG_PG_*`
  family, so folding the scripts onto it could not silently ignore a variable
  someone already had set. Precedence is now `VG_TEST_PG_*` -> `VG_PG_*` ->
  `PG*` -> `LOCAL_DB_*` -> the docker test stack, and it is decided rather than
  incidental: with both families set, the one the suites use wins.
* `add_pg_arguments(parser)` and `pg_kwargs()` give a script its five
  connection settings from that one place. All 19 scripts use one or the other;
  none reads `VG_*_PG_*` directly any more.
* The default is 5433, which settles the question `issues/099` left open. It is
  also the safe direction: an unset environment now reaches the disposable
  cluster rather than the one with real data on it.
* **The target is printed before any work.** `describe_target` names the host,
  port, database AND which cluster that is — "docker test stack" or "host
  cluster" — because the failure mode here is a script doing the right thing to
  the wrong database and reporting success. Naming it is what makes that visible
  without reading the code.

  It prints with `flush=True`. These scripts log to stderr while `print`
  block-buffers on stdout when piped, so without the flush the banner appeared
  AFTER the work it announces — worse than not printing it, and it took a
  second look to notice.

### The guard

`tests/unit/test_pg_target_is_shared.py` (46 cases) fails on any script that
reads `VG_*_PG_*` directly, checks each env family can still override, pins the
precedence and the 5433 default, and asserts the inventory is non-empty so a
glob that matches nothing cannot pass as compliance. The next script will be
written by copying an existing one; this is what stops it inheriting a private
default.

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
