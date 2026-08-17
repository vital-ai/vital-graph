# The Fixture Loader and the Perf Tests Default to Different Clusters

## Status: FIXED 2026-08-16 (data reloaded, guard added); ONE DECISION LEFT

18 tests in `tests/performance/test_nested_frame_traversal.py` failed, all the
same shape: a query for nested frames returned 0 rows where the manifest said 1.

    frame 0 at nesting depth 1: got 0, manifest says 1

## The cause

`VG_TEST_PG_PORT` has TWO different defaults across 21 files:

    scripts/load_wordnet_csv.py     default 5433   <- writes the fixture
    scripts/perf_seed_data.py       default 5433
    tests/performance/conftest.py   default 5432   <- reads it
    tests/integration/conftest.py   default 5432
    tests/api/conftest.py           default 5432

With no override the fixture is seeded into the container cluster and the tests
read the host cluster. Measured:

    port 5433:  8 spaces, sp_graph_synth_10k = 2,425,530 quads   (correct)
    port 5432: 99 spaces, sp_graph_synth_10k = 1,889,439 quads   (stale)

The host cluster carries a same-named space left over from earlier work, so the
tests found *something* and produced plausible wrong answers instead of failing
to connect. `Edge_hasKGFrame` — the edge the traversal queries filter on —
existed in neither the stale space nor its term table.

`load_wordnet_csv.py`'s own docstring says it "reads the same `VG_TEST_PG_*`
variables as `tests/performance/conftest.py` ... so a fixture lands in the
cluster the tests that use it will look in". It reads the same VARIABLE; it does
not share the same DEFAULT, and with the variable unset that sentence is false.
The docstring also records that a near-identical split (COPY to 5433, resync to
5432) was found and fixed once before — inside that one script.

## Corrections to the first version of this issue

Two, both from measuring the wrong cluster:

* I reported the space as "loaded from only the first of its two data files".
  It was not — it was a different, older space entirely, in a different
  cluster.
* I reported the `.nt` files as using `rdf:type` where the query wants
  `vital-core#vitaltype`, implying a generator mismatch. They carry BOTH:
  318,636 of each. There was no generator problem.

Every `psql` in that investigation went to 5432 while the loader wrote 5433 —
the same mistake the tests were making, made again while investigating it.

## Fixed

* Fixture reloaded into BOTH clusters from the CSVs. The 18 tests pass, and
  `Edge_hasKGFrame` is present at 32,109 — exactly the manifest's
  `n_nested_frames`.
* **`test_the_space_holds_the_nesting_the_manifest_describes`** asks the SPACE
  for the edge count and compares it with the manifest. The existing guard,
  written so "a suite that skips its own subject" could not pass by asking
  nothing, read the manifest at both ends and so compared it with itself. The
  new one fails with a message naming the port split, because "0 nested edges"
  is not self-explanatory and cost a long investigation once.

## Left open — a decision, not a fix

**Which cluster should `VG_TEST_PG_PORT` default to?** Aligning them is right;
which way is a call about how this environment is meant to work:

* make the loaders default to 5432, matching all three test conftests; or
* make the perf conftest default to 5433, matching the seeders, keeping perf
  fixtures in the isolated container cluster.

Not decided here. A wrong guess silently moves where everyone's fixtures land,
which is the same failure with the arrow reversed.

## Related

- `issues/081` — found while re-promoting its baseline; these were 18 of the 37
  holes it carries. Worth re-promoting once this is settled.
