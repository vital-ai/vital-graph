"""A text needle matching nothing empties a query only where it is REQUIRED.

`issues/202`: a servable needle absent from the space was the most expensive
text query measured — 1,681,156 shared buffers against 7,516 for one that
matches — because a matching needle satisfies `LIMIT 25` after a few candidates
and an empty one has nothing to stop it, so it enumerates the candidate set to
prove a zero. It is now answered before emission, the same treatment
`issues/073` gave an absent constant.

THESE TESTS ARE ABOUT THE OTHER DIRECTION. `issues/093` records what the same
optimisation cost when "required" was decided carelessly for constants: every
query with a `GRAPH ?g` over an empty default graph returned ZERO ROWS, silently,
because `LIMIT 0` is not an error and an empty answer is a legitimate one.

So the cases that matter here are the ones that must NOT short-circuit:

    FILTER under OPTIONAL   the outer row still survives a non-matching OPTIONAL
    FILTER in a UNION arm   a sibling arm may still match
    under GROUP             an aggregate over zero rows still produces a row

Unit tests over the predicate, so they need no database. The text-spec lookup is
stubbed: what is under test is the REQUIREDNESS walk, not the expression parsing,
which `needed_texts` already owns.
"""
from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql import prune_union, semijoin
from vitalgraph.db.sparql_sql.ir import (
    KIND_BGP, KIND_FILTER, KIND_JOIN, KIND_UNION, KIND_LEFT_JOIN, KIND_GROUP,
    KIND_PROJECT, KIND_SLICE)

COND = "term_text ILIKE '%ZZQQXX%'"
P_UUID = "0000-pred"


class _Node:
    """Minimal stand-in: the walk reads only `kind` and `children`."""

    def __init__(self, kind, children=None):
        self.kind = kind
        self.children = children or []
        self.filter_exprs = []
        self.var_slots = {}
        self.leaf_terms = {}


class _Aliases:
    def __init__(self, n):
        self.text_stats = {(P_UUID, COND): n}


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    """Every FILTER carries the needle; every BGP binds it."""
    monkeypatch.setattr(semijoin, "text_specs_of_filter",
                        lambda node: [("?v", COND)] if node.kind == KIND_FILTER else [])
    monkeypatch.setattr(semijoin, "text_bgp_binding",
                        lambda bgp, var, aliases: ("q0", P_UUID))


def _required(kind_chain):
    """A FILTER over a BGP, wrapped in `kind_chain` outermost-first."""
    node = _Node(KIND_FILTER, [_Node(KIND_BGP)])
    for kind in reversed(kind_chain):
        node = _Node(kind, [node])
    return node


class TestFiresWhereRequired:

    def test_bare_filter_over_bgp_is_empty(self):
        assert prune_union._required_text_matches_nothing(
            _required([]), _Aliases(0)) is True

    @pytest.mark.parametrize("kind", [KIND_PROJECT, KIND_SLICE, KIND_JOIN])
    def test_emptiness_propagates_through(self, kind):
        assert prune_union._required_text_matches_nothing(
            _required([kind]), _Aliases(0)) is True

    def test_a_join_sibling_does_not_save_it(self):
        """Both sides of a JOIN are required, so one dead side is fatal."""
        node = _Node(KIND_JOIN, [_Node(KIND_BGP), _required([])])
        assert prune_union._required_text_matches_nothing(node, _Aliases(0)) is True


class TestDoesNotFireWhereOptional:

    def test_a_nonzero_needle_is_not_empty(self):
        """The whole optimisation rests on the count, so pin the ordinary case."""
        assert prune_union._required_text_matches_nothing(
            _required([]), _Aliases(3)) is False

    def test_optional_side_does_not_empty_the_query(self):
        """A non-matching OPTIONAL still yields its outer row (issues/093)."""
        node = _Node(KIND_LEFT_JOIN, [_Node(KIND_BGP), _required([])])
        assert prune_union._required_text_matches_nothing(node, _Aliases(0)) is False

    def test_union_arm_does_not_empty_the_query(self):
        """A sibling arm may still match."""
        node = _Node(KIND_UNION, [_required([]), _Node(KIND_BGP)])
        assert prune_union._required_text_matches_nothing(node, _Aliases(0)) is False

    def test_group_does_not_propagate(self):
        """COUNT(*) over zero rows is a row, not an empty result."""
        assert prune_union._required_text_matches_nothing(
            _required([KIND_GROUP]), _Aliases(0)) is False

    def test_no_text_stats_is_no_opinion(self):
        node = _required([])
        aliases = _Aliases(0)
        aliases.text_stats = {}
        assert prune_union._required_text_matches_nothing(node, aliases) is False

    def test_left_join_left_side_still_fires(self):
        """The LEFT side of an OPTIONAL is required, so a dead one IS fatal."""
        node = _Node(KIND_LEFT_JOIN, [_required([]), _Node(KIND_BGP)])
        assert prune_union._required_text_matches_nothing(node, _Aliases(0)) is True
