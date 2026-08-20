"""Plan shape is compared as a TREE: sibling order is erased, depth is not.

`issues/113`, option 3. The metric went through three forms, and the first two
each failed in a way the next fixed:

  * **elementwise on a flat pre-order walk** — failed `dedup.depth3` with 39
    identical nodes, identical rows and cost within noise, because one
    `Index Only Scan` had moved position. PostgreSQL may emit a hash join's
    inputs either way round, so that is not a change.
  * **the node-type multiset** — fixed that, and could not see a `Sort` above a
    `Gather` becoming a `Gather` above a `Sort`. Same counts, different plan.
  * **a canonical tree**, which is both: children are sorted by their own
    subtree, so a sibling swap normalises away, while parent/child survives.

        Sort above Gather    ["Sort",   [["Gather", []]]]
        Gather above Sort    ["Gather", [["Sort",   []]]]

WHY IT HAS TO BE EXACTLY THIS SHARP. `shape.*` is what catches real plan flips —
`issues/112` was diagnosed from `Gather Merge` becoming a `Sort` above a
`Gather`. Too loose and it misses them; too strict and it fires on noise, and a
gate that fires on noise is one people skim past, taking the next real flip with
it.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from scripts.perf_compare import (compare_bench, load_thresholds, FAIL, INFO,
                                  canon, tree_edges as compare_tree_edges)
from tests.performance.perf_record import (canonical_tree,
                                           tree_edges as record_tree_edges)
from tests.performance import harness


def _n(node_type, *children):
    d = {"Node Type": node_type}
    if children:
        d["Plans"] = list(children)
    return d


def _bench(root, *, with_tree=True):
    nodes = list(harness._walk(root))
    shape = {"node_types": [n.get("Node Type", "") for n in nodes],
             "indexes": [], "seq_scans": []}
    if with_tree:
        shape["tree"] = canonical_tree(root)
    return {"bench_id": "b", "status": "ok",
            "metrics": {"shared_buffers": 1000, "actual_rows": 17},
            "shape": shape}


def _findings(base_root, cur_root, **kw):
    out = compare_bench("b", _bench(base_root, **kw), _bench(cur_root, **kw),
                        load_thresholds())
    return [f for f in out if f["metric"].startswith("shape.")]


class TestSiblingOrderIsErased:

    def test_a_swap_produces_no_finding_at_all(self):
        """The issues/113 case. Not downgraded to a note — genuinely equal."""
        a = _n("Nested Loop", _n("Index Only Scan"), _n("Index Scan"))
        b = _n("Nested Loop", _n("Index Scan"), _n("Index Only Scan"))
        assert _findings(a, b) == []

    def test_two_children_of_the_same_type_are_ordered_by_subtree(self):
        """Sorting on node type alone would make these compare equal."""
        a = _n("Hash Join", _n("Sort", _n("Seq Scan")), _n("Sort", _n("Index Scan")))
        b = _n("Hash Join", _n("Sort", _n("Index Scan")), _n("Sort", _n("Seq Scan")))
        assert _findings(a, b) == [], "the same two subtrees, swapped"

    def test_an_identical_plan_says_nothing(self):
        assert _findings(_n("Limit", _n("Sort")), _n("Limit", _n("Sort"))) == []


class TestDepthIsNotErased:
    """The property the multiset could not hold."""

    def test_sort_above_gather_differs_from_gather_above_sort(self):
        a = _n("Limit", _n("Sort", _n("Gather")))
        b = _n("Limit", _n("Gather", _n("Sort")))
        found = _findings(a, b)
        assert found and found[0]["level"] == FAIL
        assert found[0]["metric"] == "shape.tree"

    def test_the_same_nodes_reparented_is_a_change(self):
        a = _n("A", _n("B", _n("C")))
        b = _n("A", _n("B"), _n("C"))
        found = _findings(a, b)
        assert found and found[0]["level"] == FAIL


class TestRealFlipsStillFail:

    def test_index_scan_becoming_seq_scan(self):
        found = _findings(_n("Nested Loop", _n("Index Only Scan")),
                          _n("Nested Loop", _n("Seq Scan")))
        assert found and found[0]["level"] == FAIL
        assert "Seq Scan" in found[0]["detail"]

    def test_the_message_is_edges_not_nested_lists(self):
        """The elementwise version printed two 39-element lists side by side."""
        found = _findings(_n("Nested Loop", _n("Index Only Scan")),
                          _n("Nested Loop", _n("Seq Scan")))
        d = found[0]["detail"]
        assert ">" in d and "gained" in d and "lost" in d
        assert len(d) < 140


class TestAnOlderBaselineSaysSo:
    """issues/081's rule: absence is not agreement."""

    def test_a_baseline_without_a_tree_is_reported(self):
        a = _n("Nested Loop", _n("Index Only Scan"))
        out = compare_bench("b", _bench(a, with_tree=False), _bench(a),
                            load_thresholds())
        notes = [f for f in out if f["metric"] == "shape.tree"]
        assert notes and notes[0]["level"] == INFO
        assert "re-promote" in notes[0]["detail"]


class TestTheTwoCopiesAgree:
    """`perf_compare` keeps a local `tree_edges` rather than importing from the
    test package, because a script reaching into `tests/` inverts the
    dependency. That is only safe while they agree."""

    @pytest.mark.parametrize("root", [
        _n("Limit", _n("Sort", _n("Gather"))),
        _n("Hash Join", _n("Seq Scan"), _n("Index Scan", _n("Materialize"))),
        _n("Solo"),
    ])
    def test_identical_output(self, root):
        t = canonical_tree(root)
        assert compare_tree_edges(t) == record_tree_edges(t)


class TestTheComparisonCanonicalisesRatherThanTrusting:
    """The recorder already writes a canonical tree, so `canon` is a no-op in
    normal use. It runs anyway because the gate must not depend on HOW the
    baseline was produced — an older recorder, or a future one with a different
    sort key, has to compare as the same plan. Caught by a test that swapped
    children in a STORED tree and saw it fail: an artificial input, but the same
    shape as a recorder change."""

    def test_a_non_canonical_tree_compares_equal_to_its_canonical_form(self):
        canonical = ["NL", [["A", []], ["B", []]]]
        shuffled = ["NL", [["B", []], ["A", []]]]
        assert canonical != shuffled, "the inputs must actually differ"
        assert canon(canonical) == canon(shuffled)

    def test_canonicalisation_reaches_every_level(self):
        a = ["R", [["P", [["X", []], ["Y", []]]]]]
        b = ["R", [["P", [["Y", []], ["X", []]]]]]
        assert canon(a) == canon(b)

    def test_it_does_not_flatten_depth(self):
        assert canon(["A", [["B", []]]]) != canon(["B", [["A", []]]])
