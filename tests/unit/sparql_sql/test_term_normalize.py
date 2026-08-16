"""One convention for a blank node's stored text, enforced in one place.

`term_text` holds the BARE value; `_:` belongs to serialized RDF syntax. The
read side always agreed. The write side did not, and which convention you got
depended on the entry point — import stripped the prefix, SPARQL UPDATE added
it back, the string sniffer left it on (issues/065).

That is not cosmetic, because `term_uuid` is a deterministic UUIDv5 over
`(term_text, term_type, lang, datatype_id)`. Two spellings are two terms, so a
blank node loaded from a file could not be deleted through SPARQL UPDATE and
vice versa — the delete matched nothing and reported success.
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.term_normalize import (
    normalize_term_text, serialize_term_text)


class TestNormalize:

    def test_strips_the_prefix_from_a_blank_node(self):
        assert normalize_term_text("_:b1", "B") == "b1"

    def test_leaves_a_bare_label_alone(self):
        assert normalize_term_text("b1", "B") == "b1"

    def test_is_idempotent(self):
        """Applied both at storage and at uuid computation, which are not
        always the same call — so double application must be harmless."""
        once = normalize_term_text("_:b1", "B")
        assert normalize_term_text(once, "B") == once

    def test_does_not_touch_other_term_types(self):
        """A URI or literal may legitimately begin with `_:`.

        Stripping by prefix alone rather than by prefix AND type would corrupt
        them, which is the obvious wrong implementation.
        """
        assert normalize_term_text("_:not-a-bnode", "L") == "_:not-a-bnode"
        assert normalize_term_text("_:weird", "U") == "_:weird"

    def test_serialize_is_the_inverse(self):
        assert serialize_term_text("b1", "B") == "_:b1"
        assert serialize_term_text("_:b1", "B") == "_:b1", "must not double it"
        assert serialize_term_text("plain", "L") == "plain"


class TestIdentityAgreesAcrossWritePaths:
    """The consequence that mattered: one node, one uuid, whatever wrote it."""

    def test_update_path_and_load_path_agree(self):
        from vitalgraph.db.sparql_sql.emit_update import (
            _generate_term_uuid as update_uuid, _node_text)
        from vitalgraph.db.sparql_sql.sparql_sql_space_impl import (
            _generate_term_uuid as impl_uuid)
        from vitalgraph.db.jena_sparql.jena_types import BNodeNode

        # What SPARQL UPDATE derives for `_:b1` ...
        from_update = update_uuid(_node_text(BNodeNode(label="b1")), "B")
        # ... and what the load path derives for the same node.
        from_load = impl_uuid("b1", "B")
        assert from_update == from_load, (
            "the same blank node got different term UUIDs from the UPDATE and "
            "load paths, so a delete issued through one cannot match a triple "
            "written through the other")

    def test_a_prefixed_spelling_hashes_to_the_bare_one(self):
        """Defence in depth: even a caller that passes `_:b1` lands on one id."""
        from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        assert _generate_term_uuid("_:b1", "B") == _generate_term_uuid("b1", "B")

    def test_node_text_returns_the_bare_label(self):
        from vitalgraph.db.sparql_sql.emit_update import _node_text
        from vitalgraph.db.jena_sparql.jena_types import BNodeNode
        assert _node_text(BNodeNode(label="b1")) == "b1", (
            "returning `_:b1` here is what made the UPDATE path diverge; it "
            "feeds both the term upsert and the uuid computation")
