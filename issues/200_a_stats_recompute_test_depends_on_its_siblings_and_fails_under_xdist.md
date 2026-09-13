# A Stats-Recompute Test Depends on Its Siblings, and Fails Under xdist

## Status: OPEN — intermittent, pre-existing, and it fails for a reason unrelated to what it tests

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
