# A Stats-Recompute Test Depends on Its Siblings, and Fails Under xdist

## Status: FIXED 2026-09-13 — the test establishes its own precondition

`a1c102a4`. It now inserts its own second predicate, with a biggest pair and a
tail, so "every predicate's biggest before any predicate's second" is a claim
about that predicate too. Deliberately small next to the anchor: the point is
that it is a DIFFERENT predicate, not a large one.

The property the docstring argues for is kept — `truth` is still computed from
whatever the space actually holds, so the assertion is still SIZED to the shared
space. What changed is that it no longer DEPENDS on it.

Verified in both directions:

    run ALONE (the case that failed)     passes   (was `assert 1 >= 2`)
    whole file in order                  11 / 11
    still catches its own defect         yes

That last check is the one that mattered. Reintroducing the `issues/153`
ordering defect — `ORDER BY count(*) ASC` in the window, ranking by the SMALLEST
pair — makes it fire "a predicate's stored row is not its LARGEST pair", and
restoring the order makes it pass. A fix that quietly defanged a regression test
would have been worse than the flake it removed.

The old failure message now describes a different cause and says so: reaching
that assertion means this test's own insert did not land, not that a sibling was
missing. An explicit `assert Q in truth` states it directly.

### No sibling carries the same assumption

Every test in the module was run on its own, which is the check that finds this
class of defect — a data dependency shows up as "passes in file order, fails
alone", with no parallelism needed:

    test_every_predicate_is_represented_even_under_a_tight_cap          PASS
    test_large_pairs_survive_there_is_no_upper_bound                    PASS
    test_it_is_idempotent                                               PASS
    test_it_replaces_rather_than_accumulates                            PASS
    test_pred_stats_is_rebuilt_too                                      PASS
    test_below_the_cap_it_matches_the_quads_exactly                     PASS
    test_singletons_are_excluded_and_that_is_the_only_exclusion         PASS
    test_the_anchor_survives_a_cap_far_below_its_predicates_pair_count  PASS
    test_every_predicate_gets_its_biggest_before_any_gets_its_second    PASS
    test_recompute_streams_the_aggregate_and_restores_the_setting       PASS
    test_the_index_the_streaming_aggregate_needs_is_still_created       PASS

11 of 11. The module is isolation-clean.

Worth keeping as a technique rather than a one-off: `test_space` being
module-scoped means ANY module using it can grow this dependency silently, and
running one test alone is a cheap way to find it. The failing test here was
conspicuous because it ASSERTS on the shared state; one that merely reads it
would fail more quietly, or pass with wrong data.

## Original filing, kept for the record

`tests/integration/test_stats_recompute.py::test_every_predicate_gets_its_biggest_before_any_gets_its_second`
fails intermittently under `pytest tests/integration -n 4 -m "not serial"`:

    assert len(truth) >= 2, "need at least two predicates to show fairness"
    E  AssertionError: need at least two predicates to show fairness
    E  assert 1 >= 2
    E   +  where 1 = len({UUID('f7495918-50f4-4bed-b960-908456333c44'): 5000})

It has nothing to do with the fairness property the test exists to protect. The
test never gets far enough to check it.

## The mechanism

`test_space` (`tests/integration/conftest.py:180`) is `scope="module"`: one
ephemeral space per module, shared by every test in it, and predicates
ACCUMULATE in it as those tests run.

`anchor_space` inserts ONE predicate. The second — the one that makes "every
predicate's biggest before any predicate's second" a meaningful claim — comes
from a SIBLING test earlier in the same module.

Under xdist's default `--dist load`, tests from one module are handed to
whichever worker is free. A module-scoped fixture is per WORKER, so a worker
that receives this test and not its siblings builds a fresh space, runs
`anchor_space`, and sees exactly one predicate.

Reproduced deterministically without any parallelism at all:

    pytest tests/integration/test_stats_recompute.py                  11 passed
    pytest tests/integration/test_stats_recompute.py::test_every_...   FAILED

Passing in file order and failing alone is the signature: it is not a race, it
is a data dependency. The parallel run only decides how often the dependency
goes unmet.

## It is acknowledged in the test, as a feature

    Sized to the space rather than to a constant, because `test_space` is
    shared and carries predicates from other tests — which is exactly the
    condition the first version of this test got wrong.

That reasoning is sound for THRESHOLDS: sizing an assertion to whatever the
shared space holds is more robust than hard-coding a count. It does not extend
to REQUIRING a second predicate to be there. The test reads the shared space as
a given rather than establishing what it needs, so "shared" silently became
"depends on".

## Why this matters beyond one flake

A test that fails for a reason unrelated to its subject teaches the wrong
lesson twice. First it costs an investigation — this one was found while
verifying an unrelated change to `edge_fanout` maintenance, and the first
question was whether that change had caused it (it had not: the failure
reproduces with the change reverted). Second, a test that is known to fail
sometimes stops being read as a signal, which is exactly what its own
`issues/153` lineage was written to prevent — it is a REGRESSION test for a
planner fairness property, verified at the time to fail under the wrong
ordering.

## Fix

Make the test establish its own precondition: insert a second predicate with a
pair of its own, rather than hoping a sibling left one. That keeps the
sized-to-the-space assertion the docstring argues for while removing the
dependency, and it makes the test correct under any distribution.

`--dist loadfile` (or `loadscope`) would also hide it by keeping a module on one
worker, and is worth considering for the suite generally, but it is a
workaround here: the test would still be wrong when run alone, which is how
anyone debugging it will run it.

Check whether the sibling tests in this module carry the same assumption. This
one is visible because it asserts on the shared state; another that merely READS
it would fail less loudly.
