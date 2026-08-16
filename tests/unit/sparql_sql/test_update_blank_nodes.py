"""Blank nodes in SPARQL UPDATE data blocks (issues/076, facets 1 and 1b).

Two rules from SPARQL 1.1, opposite in direction:

  §19.6  INSERT DATA blank nodes are FRESH — they must not merge with nodes
         already in the store, and each execution introduces new ones.
  §3.1.3 DELETE DATA must not contain a blank node at all — a data block has no
         way to name an existing one, so the operation is meaningless.

Neither was implemented. `_node_text` passed the parsed label straight through,
so `INSERT DATA { _:b1 :p 1 }` run twice wrote ONE node with one triple instead
of two nodes with one each, and merged with any `_:b1` from an unrelated
import. DELETE DATA built a lookup on the label and deleted whatever matched.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    BNodeNode, LiteralNode, QuadPattern, URINode)
from vitalgraph.db.sparql_sql.emit_update import (
    BlankNodeInDeleteData, _freshen_insert_data_bnodes,
    _reject_bnodes_in_delete_data)

G = URINode(value="urn:g")
P = URINode(value="urn:p")


def _q(subj, obj):
    return QuadPattern(subject=subj, predicate=P, object=obj, graph=G)


class TestInsertDataFreshness:

    def test_labels_are_rewritten(self):
        out = _freshen_insert_data_bnodes([_q(BNodeNode(label="b1"),
                                              LiteralNode(value="1"))])
        assert out[0].subject.label != "b1", (
            "the parsed label passed straight through, so a second execution "
            "of the same INSERT DATA would write the same node again")

    def test_one_label_stays_one_node_within_a_request(self):
        """`_:b1 :p 1 . _:b1 :q 2` is ONE node with two triples."""
        out = _freshen_insert_data_bnodes([
            _q(BNodeNode(label="b1"), LiteralNode(value="1")),
            _q(BNodeNode(label="b1"), LiteralNode(value="2")),
        ])
        assert out[0].subject.label == out[1].subject.label

    def test_distinct_labels_stay_distinct(self):
        out = _freshen_insert_data_bnodes([
            _q(BNodeNode(label="b1"), LiteralNode(value="1")),
            _q(BNodeNode(label="b2"), LiteralNode(value="2")),
        ])
        assert out[0].subject.label != out[1].subject.label

    def test_separate_requests_do_not_collide(self):
        """The freshness requirement, and the reason the salt is not a counter.

        A per-request counter restarts at 1 every time, so two requests would
        both allocate `b1_...` and merge again — which is the bug, reintroduced
        by a plausible implementation.
        """
        a = _freshen_insert_data_bnodes([_q(BNodeNode(label="b1"),
                                            LiteralNode(value="1"))])
        b = _freshen_insert_data_bnodes([_q(BNodeNode(label="b1"),
                                            LiteralNode(value="1"))])
        assert a[0].subject.label != b[0].subject.label, (
            "two executions of the same INSERT DATA produced the same blank "
            "node; §19.6 requires each execution to introduce new ones")

    def test_blank_nodes_in_object_position_are_freshened_too(self):
        out = _freshen_insert_data_bnodes([_q(URINode(value="urn:s"),
                                              BNodeNode(label="b1"))])
        assert out[0].object.label != "b1"

    def test_uris_and_literals_are_untouched(self):
        out = _freshen_insert_data_bnodes([_q(URINode(value="urn:s"),
                                              LiteralNode(value="x"))])
        assert out[0].subject.value == "urn:s"
        assert out[0].object.value == "x"


class TestDeleteDataRejectsBlankNodes:

    def test_a_blank_node_subject_is_rejected(self):
        with pytest.raises(BlankNodeInDeleteData):
            _reject_bnodes_in_delete_data([_q(BNodeNode(label="b1"),
                                              LiteralNode(value="1"))])

    def test_a_blank_node_object_is_rejected(self):
        with pytest.raises(BlankNodeInDeleteData):
            _reject_bnodes_in_delete_data([_q(URINode(value="urn:s"),
                                              BNodeNode(label="b1"))])

    def test_an_ordinary_delete_is_allowed(self):
        """Guard the guard: rejecting everything would also pass the two above."""
        _reject_bnodes_in_delete_data([_q(URINode(value="urn:s"),
                                          LiteralNode(value="1"))])

    def test_the_error_names_the_alternative(self):
        """A rejection that does not say what to do instead is a dead end."""
        with pytest.raises(BlankNodeInDeleteData, match="DELETE WHERE"):
            _reject_bnodes_in_delete_data([_q(BNodeNode(label="b1"),
                                              LiteralNode(value="1"))])
