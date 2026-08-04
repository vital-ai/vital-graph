"""Unit tests for KGDocument segment write protection term parsing.

`_check_write_protection` reads the segment-type predicate/object out of a
`Quad`, whose fields carry N-Quads term encoding. It used to do that with
`q.o.strip('"').split('"')[0]`, which mis-parses any literal containing an
escaped quote, a datatype suffix, or a language tag — either missing a managed
type (protection silently off) or mangling an ordinary value.

No server or database required.
"""

from __future__ import annotations

from vitalgraph.endpoint.kgdocuments_endpoint import KGDocumentsEndpoint
from vitalgraph.model.quad_model import Quad

SEG_TYPE_PRED = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTypeURI"
NAME_PRED = "http://vital.ai/ontology/vital-core#hasName"


def _check(quads):
    """Call the protection check without constructing a live endpoint."""
    return KGDocumentsEndpoint._check_write_protection(KGDocumentsEndpoint, quads)


class TestWriteProtectionTermParsing:

    def test_rejects_managed_segment_type_as_uri_term(self):
        q = Quad(s="<urn:doc:1>", p=f"<{SEG_TYPE_PRED}>",
                 o="<urn:segtype:text_chunk>")
        assert _check([q]) is not None

    def test_rejects_managed_segment_type_as_plain_literal(self):
        q = Quad(s="<urn:doc:1>", p=f"<{SEG_TYPE_PRED}>",
                 o='"urn:segtype:text_chunk"')
        assert _check([q]) is not None

    def test_allows_unmanaged_segment_type(self):
        q = Quad(s="<urn:doc:1>", p=f"<{SEG_TYPE_PRED}>",
                 o="<urn:segtype:user_defined>")
        assert _check([q]) is None

    def test_allows_ordinary_document_quad(self):
        q = Quad(s="<urn:doc:1>", p=f"<{NAME_PRED}>", o='"My Document"')
        assert _check([q]) is None

    # --- cases the old strip/split parser got wrong -----------------------

    def test_literal_with_escaped_quote_is_not_mangled(self):
        """`split('"')[0]` truncates at the escaped quote, yielding a wrong
        value. Must parse the full lexical form and allow the write."""
        q = Quad(s="<urn:doc:1>", p=f"<{NAME_PRED}>",
                 o='"he said \\"hi\\" to me"')
        assert _check([q]) is None

    def test_typed_literal_datatype_suffix_ignored(self):
        q = Quad(s="<urn:doc:1>", p=f"<{NAME_PRED}>",
                 o='"42"^^<http://www.w3.org/2001/XMLSchema#integer>')
        assert _check([q]) is None

    def test_language_tagged_managed_type_still_caught(self):
        """A language tag must not smuggle a managed type past the check."""
        q = Quad(s="<urn:doc:1>", p=f"<{SEG_TYPE_PRED}>",
                 o='"urn:segtype:text_chunk"@en')
        assert _check([q]) is not None

    def test_managed_type_as_typed_literal_still_caught(self):
        q = Quad(s="<urn:doc:1>", p=f"<{SEG_TYPE_PRED}>",
                 o='"urn:segtype:segmentation_parent"^^'
                   '<http://www.w3.org/2001/XMLSchema#string>')
        assert _check([q]) is not None

    def test_scans_all_quads_not_just_first(self):
        quads = [
            Quad(s="<urn:doc:1>", p=f"<{NAME_PRED}>", o='"ok"'),
            Quad(s="<urn:doc:1>", p=f"<{SEG_TYPE_PRED}>",
                 o="<urn:segtype:markdown_section>"),
        ]
        assert _check(quads) is not None

    def test_empty_quad_list_allowed(self):
        assert _check([]) is None
