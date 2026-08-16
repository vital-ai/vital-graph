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


class TestSkolemisation:
    """issues/076 facet 2: blank-node labels are scoped, not global.

    RDF 1.1 Concepts: blank node identifiers are "locally scoped to the file or
    RDF store, and are *not* persistent or portable identifiers". Two documents
    each using `_:b0` describe two different nodes. This store made the label
    the identity globally and forever, so they merged — silently, and
    unrecoverably, because nothing recorded that they were ever separate.

    Skolemisation is the spec's own answer (§3.5: "SHOULD mint a new, globally
    unique IRI", using the registered `genid` well-known name), and it is
    DETERMINISTIC here so that re-importing a document reproduces its nodes.
    Random allocation per load would satisfy RDF and break idempotent reload
    (issues/041); deriving from the scope gives both.
    """

    def test_the_same_label_in_different_documents_is_different_nodes(self):
        from vitalgraph.db.sparql_sql.term_normalize import skolem_label
        assert skolem_label("docA", "b0") != skolem_label("docB", "b0"), (
            "two documents using `_:b0` collapsed into one node")

    def test_reimporting_a_document_reproduces_its_nodes(self):
        from vitalgraph.db.sparql_sql.term_normalize import skolem_label
        assert skolem_label("docA", "b0") == skolem_label("docA", "b0"), (
            "re-import produced different nodes, so reload is not idempotent")

    def test_distinct_labels_in_one_document_stay_distinct(self):
        from vitalgraph.db.sparql_sql.term_normalize import skolem_label
        assert skolem_label("docA", "b0") != skolem_label("docA", "b1")

    def test_the_label_is_a_valid_ntriples_label(self):
        """The reason the stored value is a label and not the full Skolem IRI.

        BLANK_NODE_LABEL admits neither `:` nor `/`, so storing the IRI would
        export as `_:http://.../genid/abc`, which no parser reads back.
        """
        import re
        from vitalgraph.db.sparql_sql.term_normalize import skolem_label
        label = skolem_label("docA", "b0")
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", label), label

    def test_iri_form_uses_the_registered_well_known_name(self):
        from vitalgraph.db.sparql_sql.term_normalize import skolem_iri, skolem_label
        assert "/.well-known/genid/" in skolem_iri(skolem_label("docA", "b0"))

    def test_skolem_labels_are_recognisable(self):
        """Labels from before skolemisation must stay distinguishable."""
        from vitalgraph.db.sparql_sql.term_normalize import (
            is_skolem_label, skolem_label)
        assert is_skolem_label(skolem_label("docA", "b0"))
        assert not is_skolem_label("b0")
        assert not is_skolem_label("vgnothex_not_a_digest")

    def test_iri_round_trips(self):
        from vitalgraph.db.sparql_sql.term_normalize import (
            deskolemize_iri, skolem_iri, skolem_label)
        label = skolem_label("docA", "b0")
        assert deskolemize_iri(skolem_iri(label)) == label
        assert deskolemize_iri("http://example.org/ordinary") is None


class TestImportParserScoping:

    def test_import_scopes_blank_nodes_per_document(self):
        from vitalgraph.endpoint.impl.data_import_impl import (
            _parse_nquads_term_for_import as parse)
        a, ta, _ = parse("_:b0", "docA")
        b, tb, _ = parse("_:b0", "docB")
        assert a != b and ta == tb == "B", (
            "the same label in two documents produced one node")

    def test_an_exported_skolem_iri_reads_back_as_a_blank_node(self):
        """The URI branch returns unconditionally, so this is checked first.

        My first version placed the check after it, making it dead code: an
        exported blank node would have come back as an ordinary IRI, losing
        that it was ever blank — the exact round-trip skolemisation exists for.
        """
        from vitalgraph.endpoint.impl.data_import_impl import (
            _parse_nquads_term_for_import as parse)
        from vitalgraph.db.sparql_sql.term_normalize import skolem_iri
        label, _, _ = parse("_:b0", "docA")
        assert parse(f"<{skolem_iri(label)}>") == (label, "B", None)

    def test_an_ordinary_iri_is_still_a_uri(self):
        from vitalgraph.endpoint.impl.data_import_impl import (
            _parse_nquads_term_for_import as parse)
        assert parse("<http://example.org/x>") == ("http://example.org/x", "U", None)
