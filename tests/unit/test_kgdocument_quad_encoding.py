"""
Regression test: KGDocument upload quads must be N-Quads encoded.

`Quad.o` carries an N-Quads *term*, not a bare value. A bare string mostly
survives because the parser falls through to "plain literal" — but a value that
starts with '<' and ends with '>' is then read back as a URI and loses both
characters. Every HTML document looks exactly like that, so an unquoted
`<p>alpha</p>` round-tripped as `p>alpha</p`. Found while implementing the
upload path (issue 018 item 4).
"""

from vitalgraph.endpoint.kgdocuments_endpoint import _literal_term, _uri_term
from vitalgraph.utils.quad_format_utils import parse_nquads_object, parse_nquads_uri


class TestTermEncoding:
    def test_uri_term_is_bracketed(self):
        assert _uri_term("urn:kgdocument:1") == "<urn:kgdocument:1>"

    def test_literal_term_is_quoted(self):
        assert _literal_term("hello") == '"hello"'

    def test_html_literal_round_trips_intact(self):
        html = "<p>alpha</p>"
        assert parse_nquads_object(_literal_term(html)) == html

    def test_full_html_document_round_trips_intact(self):
        html = "<html><body><h1>Coffee</h1></body></html>"
        assert parse_nquads_object(_literal_term(html)) == html

    def test_bare_html_is_the_bug_being_prevented(self):
        # Demonstrates why encoding is required: unencoded, the same string
        # parses as a URI and silently loses its outer angle brackets.
        assert parse_nquads_object("<p>alpha</p>") == "p>alpha</p"

    def test_embedded_quotes_and_newlines_survive(self):
        value = 'He said "hi"\nSecond line\tTabbed'
        assert parse_nquads_object(_literal_term(value)) == value

    def test_backslashes_survive(self):
        value = r"C:\path\to\file"
        assert parse_nquads_object(_literal_term(value)) == value

    def test_markdown_headings_survive(self):
        md = "# Coffee\n\nA **brewed** drink.\n\n## History\n\nEthiopia."
        assert parse_nquads_object(_literal_term(md)) == md

    def test_uri_term_round_trips_as_uri(self):
        uri = "http://vital.ai/ontology/haley-ai-kg#KGDocument"
        assert parse_nquads_object(_uri_term(uri)) == uri


class TestDocumentQuadsUseEncodedTerms:
    """The builder itself must emit encoded terms, not bare strings."""

    @staticmethod
    def _build(html: str):
        from vitalgraph.document.document_converter import EXT_HTML, convert_to_markdown
        from vitalgraph.endpoint.kgdocuments_endpoint import KGDocumentsEndpoint

        conversion = convert_to_markdown(html.encode(), "page.html")
        # _build_document_quads does not touch instance state, so an unconstructed
        # instance is enough to exercise it without a space manager or router.
        return KGDocumentsEndpoint._build_document_quads(
            None,
            doc_uri="urn:kgdocument:test",
            title="Test",
            conversion=conversion,
            source_url=None,
            file_node_uri="urn:kgdocument:test:source",
            html_extensions=EXT_HTML,
        )

    def test_every_term_is_encoded(self):
        quads = self._build("<h1>A</h1><h2>B</h2>")
        for q in quads:
            assert q.s.startswith("<") and q.s.endswith(">"), q.s
            assert q.p.startswith("<") and q.p.endswith(">"), q.p
            assert q.o.startswith(("<", '"')), q.o

    def test_html_content_survives_the_builder(self):
        html = "<html><h1>A</h1><h2>B</h2></html>"
        quads = self._build(html)
        html_quads = [q for q in quads if "HTMLContent" in q.p]
        assert len(html_quads) == 1
        assert parse_nquads_object(html_quads[0].o) == html

    def test_file_node_link_is_modelled_as_an_edge(self):
        # hasKGDocumentFileNode is an Edge class, not a datatype property —
        # written as a plain predicate it is silently dropped at store time.
        quads = self._build("<h1>A</h1><h2>B</h2>")

        assert not [q for q in quads if q.p.endswith('hasKGDocumentFileNode>')], \
            "the link must not be a bare predicate — it would be dropped"

        edge_types = [
            q for q in quads
            if q.p.endswith("22-rdf-syntax-ns#type>")
            and "Edge_hasKGDocumentFileNode" in q.o
        ]
        assert len(edge_types) == 1
        edge_uri = parse_nquads_uri(edge_types[0].s)

        src = [q for q in quads if q.s == edge_types[0].s and q.p.endswith("hasEdgeSource>")]
        dst = [q for q in quads if q.s == edge_types[0].s and q.p.endswith("hasEdgeDestination>")]
        assert parse_nquads_object(src[0].o) == "urn:kgdocument:test"
        assert parse_nquads_object(dst[0].o) == "urn:kgdocument:test:source"
        assert edge_uri.startswith("urn:kgdocument:test")
