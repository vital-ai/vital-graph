# `sp_graph_synth_10k` Is Loaded From Only Part of Its Own Fixture

## Status: OPEN — found 2026-08-16 while re-promoting the perf baseline

18 tests in `tests/performance/test_nested_frame_traversal.py` fail, all with the
same shape: a query for nested frames returns 0 rows where the manifest says
there should be 1.

    frame 0 at nesting depth 1: got 0, manifest says 1

## Not a code defect — the space is missing the data

The queries filter on `?e <vitaltype> <haley-ai-kg#Edge_hasKGFrame>`. That URI is
**not in the space's term table at all**:

    term_text LIKE '%Edge_hasKGFrame%' in sp_graph_synth_10k_term   ->  0 rows

    edge vitaltypes the space DOES hold:
      Edge_hasKGSlot        91,286
      Edge_hasKGRelation    21,203

So the query genuinely matches nothing, and the generator is right to
short-circuit it. Verified by stripping the `LIMIT 0` wrapper and running the
full plan: still 0 rows. The optimisation is not hiding anything.

## Where the data is

The fixture's own data files DO contain it, in the second file:

    internal_data/graph_synth_10k/graph_syn_0001.nt    3.8 MB     0 occurrences
    internal_data/graph_synth_10k/graph_syn_0002.nt    293 MB    64,218 occurrences

64,218 is 2 x 32,109, which is exactly the `n_nested_frames` the manifest
records. The manifest and the data files agree with each other. **The loaded
space was populated from the first file only** — or from an earlier generation —
and never received the second.

## Why it matters beyond the 18 tests

* `test_the_fixture_actually_contains_nesting` is meant to be the guard against
  precisely this ("a suite that skips its own subject passes by asking
  nothing"). It passes, because it reads the MANIFEST rather than the space. A
  fixture check that consults the description instead of the data cannot detect
  a partial load.
* The 18 failures are indistinguishable at a glance from a traversal regression.
  They cost a real investigation during the `issues/081` baseline work —
  including a worktree comparison that proved nothing, because the worktree had
  no `internal_data/` and skipped all 24 tests silently.
* They are now holes in the promoted perf baseline, so those benches gate
  nothing until the space is reloaded.

## Fix

Reload `sp_graph_synth_10k` from BOTH data files, then re-run the suite and
re-promote the baseline.

Then make the guard check the space rather than the manifest: assert that the
edge type the queries filter on is present in the term table, so a partial load
fails loudly at the first test instead of as 18 confusing row-count mismatches.

## Related

- `issues/081` — found while re-promoting its baseline; these are 18 of the 37
  holes that baseline now carries
- `issues/090` — uses the same fixture family for the traversal-direction work
