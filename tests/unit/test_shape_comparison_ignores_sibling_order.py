"""Plan shape: the COUNTS gate, the ORDER reports.

`issues/113`. `perf_compare` compared the flattened pre-order walk of a plan
elementwise, so `traversal.skew2k.dedup.depth3` FAILED the baseline with 39 nodes
before and after, an identical multiset of node types, identical rows, and cost
within noise — one `Index Only Scan` had moved position.

Sibling order carries no meaning: PostgreSQL may emit a hash join's inputs either
way round, and two scans under the same parent are unordered with respect to each
other.

WHY THIS IS NOT A RELAXATION. `shape.node_types` is the metric that catches REAL
plan flips — `issues/112` was diagnosed from `Gather Merge` becoming a `Sort`
above a `Gather`. A gate that also fires when nothing changed is one people learn
to skim, and the next genuine flip is skimmed with it. Making it fire ONLY on a
real change is what keeps it worth reading.

WHAT IS GIVEN UP, DELIBERATELY. A multiset cannot see a parent/child swap that
preserves it — a `Sort` above a `Gather` versus the reverse. That is why an
order-only difference is still REPORTED rather than dropped: it is visible at the
level a reordering deserves, instead of failing the build or vanishing.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from scripts.perf_compare import compare_bench, FAIL, INFO, load_thresholds


def _bench(node_types, **metrics):
    m = {"shared_buffers": 1000, "actual_rows": 17}
    m.update(metrics)
    return {"bench_id": "b", "status": "ok", "metrics": m,
            "shape": {"node_types": list(node_types), "indexes": [],
                      "seq_scans": []}}


def _shape_findings(base_nodes, cur_nodes):
    out = compare_bench("b", _bench(base_nodes), _bench(cur_nodes),
                        load_thresholds())
    return [f for f in out if f["metric"].startswith("shape.")]


class TestAReorderIsNotARegression:

    def test_swapping_two_siblings_does_not_fail(self):
        """The exact shape of the issues/113 finding."""
        base = ["Nested Loop", "Index Only Scan", "Index Scan", "Sort"]
        cur = ["Nested Loop", "Index Scan", "Index Only Scan", "Sort"]
        found = _shape_findings(base, cur)
        assert found, "an order change must still be visible"
        assert all(f["level"] == INFO for f in found)
        assert "different order" in found[0]["detail"]

    def test_the_report_names_what_moved(self):
        base = ["Nested Loop", "Index Only Scan", "Index Scan"]
        cur = ["Nested Loop", "Index Scan", "Index Only Scan"]
        detail = _shape_findings(base, cur)[0]["detail"]
        assert "Index" in detail and "issues/113" in detail

    def test_an_identical_shape_says_nothing(self):
        assert _shape_findings(["Sort", "Gather"], ["Sort", "Gather"]) == []


class TestARealFlipStillFails:

    def test_an_index_scan_becoming_a_seq_scan_fails(self):
        """The flip this metric exists for."""
        found = _shape_findings(["Nested Loop", "Index Only Scan"],
                                ["Nested Loop", "Seq Scan"])
        assert found and found[0]["level"] == FAIL
        assert "Seq Scan" in found[0]["detail"]

    def test_the_failure_names_the_difference_not_two_long_lists(self):
        """The old message printed both 39-element lists, which is unreadable at
        the width a terminal reports findings in."""
        found = _shape_findings(["Nested Loop", "Index Only Scan"],
                                ["Nested Loop", "Seq Scan"])
        d = found[0]["detail"]
        assert "gained" in d and "lost" in d
        assert len(d) < 120, "the point is that it fits on a line"

    def test_the_issues_112_flip_is_caught(self):
        """Gather Merge -> Gather changes the multiset, so counts see it."""
        found = _shape_findings(["Limit", "Gather Merge", "Sort"],
                                ["Limit", "Sort", "Gather"])
        assert found and found[0]["level"] == FAIL

    def test_a_node_appearing_fails(self):
        found = _shape_findings(["Limit", "Sort"], ["Limit", "Sort", "Materialize"])
        assert found and found[0]["level"] == FAIL
        assert "Materialize" in found[0]["detail"]


class TestWhatThisCannotSee:

    def test_a_parent_child_swap_preserving_the_multiset_only_reports(self):
        """Stated as a test so it is a known limit rather than a surprise.

        A `Sort` above a `Gather` and a `Gather` above a `Sort` are different
        plans with the same multiset. Counts cannot tell them apart, so this
        reports rather than fails — which is why the order difference is kept
        instead of discarded. If this ever needs to gate, the fix is a structural
        tree comparison (issues/113 option 3), not a return to elementwise.
        """
        found = _shape_findings(["Limit", "Sort", "Gather"],
                                ["Limit", "Gather", "Sort"])
        assert found and found[0]["level"] == INFO
