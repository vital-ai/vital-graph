"""Unit tests for CONSTRUCT/DESCRIBE instantiation — issue 025.

CONSTRUCT and DESCRIBE were parsed and then dropped one layer short of use:
the WHERE pattern executed and its *bindings* were returned, so any template
that was not a verbatim echo of the WHERE variables diverged silently.

These test the instantiation rules from SPARQL 1.1 §16.2 directly, because
several are invisible end-to-end — a shared blank node across solutions, or a
skipped partial triple, still produces plausible-looking output.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.construct import (
    describe_targets, instantiate_construct,
)
from vitalgraph.db.jena_sparql.jena_types import (
    BNodeNode, LiteralNode, TriplePattern, URINode, VarNode,
)


def _uri(v):
    return {"type": "uri", "value": v}


def _lit(v, **kw):
    return dict({"type": "literal", "value": v}, **kw)


def _t(s, p, o):
    return TriplePattern(subject=s, predicate=p, object=o)


V = VarNode
U = URINode


class TestTemplateIsNotTheBindings:
    """The defect: any template that is not an echo of the WHERE variables."""

    def test_constant_predicate_in_template(self):
        """`CONSTRUCT { ?s :knows ?o }` over `{ ?s :friend ?o }` — the emitted
        predicate must be the template's, not the pattern's."""
        triples = instantiate_construct(
            [_t(V("s"), U("urn:knows"), V("o"))],
            [{"s": _uri("urn:a"), "p": _uri("urn:friend"), "o": _uri("urn:b")}],
        )
        assert triples == [{
            "subject": _uri("urn:a"),
            "predicate": _uri("urn:knows"),
            "object": _uri("urn:b"),
        }]

    def test_reordered_terms(self):
        """Template inverts the pattern — output must follow the template."""
        triples = instantiate_construct(
            [_t(V("o"), V("p"), V("s"))],
            [{"s": _uri("urn:a"), "p": _uri("urn:r"), "o": _uri("urn:b")}],
        )
        assert triples[0]["subject"] == _uri("urn:b")
        assert triples[0]["object"] == _uri("urn:a")

    def test_subset_projection(self):
        """A solution binding more variables than the template uses."""
        triples = instantiate_construct(
            [_t(V("s"), U("urn:p"), U("urn:const"))],
            [{"s": _uri("urn:a"), "p": _uri("urn:x"), "o": _lit("ignored")}],
        )
        assert len(triples) == 1
        assert triples[0]["object"] == _uri("urn:const")

    def test_multiple_template_triples_per_solution(self):
        triples = instantiate_construct(
            [_t(V("s"), U("urn:p1"), V("o")), _t(V("s"), U("urn:p2"), V("o"))],
            [{"s": _uri("urn:a"), "o": _uri("urn:b")}],
        )
        assert len(triples) == 2
        assert {t["predicate"]["value"] for t in triples} == {"urn:p1", "urn:p2"}


class TestDeduplication:
    """CONSTRUCT returns a graph, not a bag."""

    def test_duplicate_triples_across_solutions_collapse(self):
        triples = instantiate_construct(
            [_t(V("s"), U("urn:p"), U("urn:o"))],
            [{"s": _uri("urn:a")}, {"s": _uri("urn:a")}, {"s": _uri("urn:b")}],
        )
        assert len(triples) == 2

    def test_literals_differing_only_by_datatype_are_distinct(self):
        triples = instantiate_construct(
            [_t(U("urn:s"), U("urn:p"), V("o"))],
            [{"o": _lit("1", datatype="urn:int")},
             {"o": _lit("1", datatype="urn:str")}],
        )
        assert len(triples) == 2

    def test_literals_differing_only_by_lang_are_distinct(self):
        triples = instantiate_construct(
            [_t(U("urn:s"), U("urn:p"), V("o"))],
            [{"o": _lit("x", **{"xml:lang": "en"})},
             {"o": _lit("x", **{"xml:lang": "fr"})}],
        )
        assert len(triples) == 2


class TestBlankNodes:

    def test_fresh_bnode_per_solution(self):
        """§16.2: a template bnode yields a *new* bnode for each solution.
        Sharing one label would silently merge distinct constructed subjects."""
        triples = instantiate_construct(
            [_t(BNodeNode(label="b"), U("urn:p"), V("s"))],
            [{"s": _uri("urn:a")}, {"s": _uri("urn:b")}],
        )
        labels = {t["subject"]["value"] for t in triples}
        assert len(labels) == 2, f"bnode shared across solutions: {labels}"

    def test_same_bnode_within_one_solution(self):
        """Two template triples naming the same bnode must agree within a row."""
        triples = instantiate_construct(
            [_t(BNodeNode(label="b"), U("urn:p1"), V("s")),
             _t(BNodeNode(label="b"), U("urn:p2"), V("s"))],
            [{"s": _uri("urn:a")}],
        )
        assert triples[0]["subject"]["value"] == triples[1]["subject"]["value"]

    def test_distinct_bnodes_stay_distinct(self):
        triples = instantiate_construct(
            [_t(BNodeNode(label="b1"), U("urn:p"), V("s")),
             _t(BNodeNode(label="b2"), U("urn:p"), V("s"))],
            [{"s": _uri("urn:a")}],
        )
        assert triples[0]["subject"]["value"] != triples[1]["subject"]["value"]


class TestSkipping:

    def test_unbound_position_skips_only_that_triple(self):
        """§16.2 skips the *triple*, not the whole solution — the issue text
        said 'skip rows', which would drop valid output."""
        triples = instantiate_construct(
            [_t(V("s"), U("urn:p"), V("missing")),
             _t(V("s"), U("urn:q"), U("urn:const"))],
            [{"s": _uri("urn:a")}],
        )
        assert len(triples) == 1
        assert triples[0]["predicate"] == _uri("urn:q")

    def test_literal_subject_is_skipped(self):
        """RDF forbids it; emitting it would produce unparseable output."""
        triples = instantiate_construct(
            [_t(V("s"), U("urn:p"), U("urn:o"))],
            [{"s": _lit("not a subject")}],
        )
        assert triples == []

    def test_non_iri_predicate_is_skipped(self):
        triples = instantiate_construct(
            [_t(U("urn:s"), V("p"), U("urn:o"))],
            [{"p": _lit("not a predicate")}],
        )
        assert triples == []

    def test_literal_object_is_allowed(self):
        triples = instantiate_construct(
            [_t(U("urn:s"), U("urn:p"), V("o"))],
            [{"o": _lit("fine")}],
        )
        assert len(triples) == 1

    def test_no_solutions_yields_no_triples(self):
        assert instantiate_construct([_t(V("s"), U("urn:p"), V("o"))], []) == []


class TestConstantTemplateNodes:

    def test_literal_with_lang_and_datatype(self):
        triples = instantiate_construct(
            [_t(U("urn:s"), U("urn:p"), LiteralNode(value="x", lang="en"))],
            [{}],
        )
        assert triples[0]["object"]["xml:lang"] == "en"

        triples = instantiate_construct(
            [_t(U("urn:s"), U("urn:p"),
                LiteralNode(value="1", datatype="urn:int"))],
            [{}],
        )
        assert triples[0]["object"]["datatype"] == "urn:int"

    def test_fully_constant_template_emits_once_per_solution_then_dedups(self):
        triples = instantiate_construct(
            [_t(U("urn:s"), U("urn:p"), U("urn:o"))],
            [{}, {}, {}],
        )
        assert len(triples) == 1


class TestDescribeTargets:

    def test_constant_uri(self):
        assert describe_targets([U("urn:a")], []) == ["urn:a"]

    def test_variable_resolved_from_bindings(self):
        got = describe_targets(
            [V("s")], [{"s": _uri("urn:a")}, {"s": _uri("urn:b")}])
        assert got == ["urn:a", "urn:b"]

    def test_duplicates_removed_order_preserved(self):
        got = describe_targets(
            [V("s")], [{"s": _uri("urn:b")}, {"s": _uri("urn:a")},
                       {"s": _uri("urn:b")}])
        assert got == ["urn:b", "urn:a"]

    def test_non_uri_bindings_ignored(self):
        """Only IRIs are describable; a literal binding contributes nothing."""
        got = describe_targets(
            [V("s")], [{"s": _lit("not a uri")}, {"s": _uri("urn:a")}])
        assert got == ["urn:a"]

    def test_mixed_constants_and_variables(self):
        got = describe_targets([U("urn:const"), V("s")], [{"s": _uri("urn:a")}])
        assert got == ["urn:const", "urn:a"]

    def test_unbound_variable_yields_nothing(self):
        assert describe_targets([V("s")], [{}]) == []
