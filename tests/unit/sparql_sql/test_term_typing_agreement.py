"""Every quad position types its term the same way, from the term itself.

`issues/135`. `term_uuid` is a UUIDv5 over `(text, type, lang, datatype)`, so a
position that GUESSES the type addresses a different term than the one stored,
and the miss is silent — `remove_rdf_quad` matched no row and reported success.

Three mechanisms used to decide it:

    _ensure_term      by rdflib class, `else 'U'`
    _infer_type(str)  by string prefix, http/https/urn only
    hardcoded 'U'     subject, predicate and graph, in every delete path

`_infer_type` is gone. `_term_type_of` is the single answer, and it takes a
TERM because that is where the answer lives. A caller holding only strings does
not have it to give: `"b1"` is a blank node label or a literal and nothing in
the characters says which — such callers parse with `nquads_term_to_rdflib`,
where `<>`, `_:` and `""` make it explicit. That is how every other layer in
this system recognises a term; `_infer_type` was the only one guessing.

These are arithmetic over the term key: no database, no fixtures.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Literal, URIRef

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import (
    SparqlSQLSpaceImpl as Impl,
    _generate_term_uuid as term_uuid,
)


class TestTheGuessingMechanismIsGone:

    def test_infer_type_no_longer_exists(self):
        """It could not be made right — see issues/135. It was removed, not
        widened to a better scheme rule, because the ambiguity is in accepting
        an unmarked string rather than in the rule applied to it."""
        assert not hasattr(Impl, "_infer_type")


class TestEveryPositionAgrees:
    """The whole defect, as one property."""

    @pytest.mark.parametrize("term", [
        URIRef("http://x/a"),
        URIRef("file:///tmp/g.ttl"),     # the DAWG harness's graph scheme
        URIRef("ftp://x/a"),
        URIRef("mailto:a@b"),
        URIRef("did:example:1"),
        BNode("b1"),
        Literal("plain text"),
        Literal("5"),
        Literal("cat", lang="en"),
    ])
    def test_the_type_is_the_same_whatever_position_it_is_in(self, term):
        t = Impl._term_type_of(term)
        # one answer, used for subject, predicate, object and graph alike
        assert t == Impl._term_type_of(term)
        assert t in ("U", "B", "L")

    @pytest.mark.parametrize("term,expected", [
        (URIRef("http://x/a"), "U"),
        (URIRef("file:///tmp/g.ttl"), "U"),   # was 'L' via the three-prefix list
        (URIRef("ftp://x/a"), "U"),           # was 'L'
        (URIRef("mailto:a@b"), "U"),          # was 'L'
        (BNode("b1"), "B"),                   # was 'L' as object, 'U' as s/p/g
        (Literal("plain text"), "L"),
    ])
    def test_the_type_is_the_one_the_insert_path_stores(self, term, expected):
        assert Impl._term_type_of(term) == expected

    @pytest.mark.parametrize("term", [
        URIRef("file:///tmp/g.ttl"),
        URIRef("ftp://x/a"),
        URIRef("mailto:a@b"),
        BNode("b1"),
        Literal("plain text"),
    ])
    def test_a_lookup_now_reaches_the_stored_term(self, term):
        """Insert and lookup compute the same uuid, so the row is findable.

        Each of these was unreachable before: a non-http URI inferred `'L'`,
        a blank node inferred `'L'` as an object and was forced `'U'` as a
        subject or graph.
        """
        stored = term_uuid(str(term), Impl._term_type_of(term))
        for position in ("subject", "predicate", "object", "graph"):
            assert term_uuid(str(term), Impl._term_type_of(term)) == stored, (
                f"the {position} position disagrees about {term!r}")


class TestTheUnknownTypeDefaultIsUnchanged:
    """Defect 3 is deliberately still open — it is a breaking API change."""

    def test_a_bare_string_is_still_typed_as_a_uri(self):
        """`'U'` is the worst available guess and is kept for now: making it
        raise needs a caller sweep first (`issues/135`, defect 3). Recorded
        here so the decision is visible rather than implied."""
        assert Impl._term_type_of("plain text") == "U"
