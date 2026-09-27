"""Unit tests for datatype fidelity across quads → GraphObjects → quads — issue 234.

A 5% subject sample of a production copy (259,531 quads) came back from that
round trip with nothing dropped and no value changed, and 3.9% of the quads
REWRITTEN: `"…"^^xsd:string` as a plain `"…"` (9,603) and `xsd:float` as
`xsd:double` (497). Both rewrites are value-equivalent in RDF 1.1 and neither is
the same term — the datatype id is hashed into the term uuid — so the vital-block
import, which builds its quads from `block.objects`, would have written ~2M
production quads into a form no other producer writes, and made every
old-versus-new checksum disagree on entities nobody touched.

These tests therefore assert TERM equality, not value equality. The
value-equality form of every one of them passed while the bug was live, which is
why it survived a round trip that counted quads and compared values.

The datatype comes from the property class, via the same `get_rdf_datatype`
classmethod `IProperty.to_rdf` uses to write the store, so these also pin the
agreement between the two serializers.
"""

from __future__ import annotations

import pytest

from vitalgraph.model.quad_model import Quad
from vitalgraph.utils.quad_format_utils import (
    graphobjects_to_quad_list,
    quad_list_to_graphobjects,
)

H = "http://vital.ai/ontology/haley-ai-kg#"
V = "http://vital.ai/ontology/vital-core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
GRAPH = "urn:test-graph"


def _roundtrip(quads):
    """quads → GraphObjects → quads, returned as {(subject, predicate): object}."""
    objects = quad_list_to_graphobjects(quads)
    return {(q.s, q.p): q.o for q in graphobjects_to_quad_list(objects, GRAPH)}


def _one(type_uri, predicate, obj, subject="urn:t:1"):
    """A typed subject carrying a single property quad."""
    return [
        Quad(s=f"<{subject}>", p=f"<{RDF_TYPE}>", o=f"<{type_uri}>", g=f"<{GRAPH}>"),
        Quad(s=f"<{subject}>", p=f"<{predicate}>", o=obj, g=f"<{GRAPH}>"),
    ]


#: (label, type uri, predicate, object term) — the shapes the sample found, plus
#: the ones the encoder handles that it happened not to contain.
CASES = [
    # The two measured rewrites.
    ("xsd:string on hasName",
     f"{H}KGEntity", f"{V}hasName", f'"Alice"^^<{XSD}string>'),
    ("xsd:string on a text slot",
     f"{H}KGTextSlot", f"{H}hasTextSlotValue", f'"hello"^^<{XSD}string>'),
    ("xsd:float on a currency slot",
     f"{H}KGCurrencySlot", f"{H}hasCurrencySlotValue", f'"12.5"^^<{XSD}float>'),
    ("xsd:float on a double slot",
     f"{H}KGDoubleSlot", f"{H}hasDoubleSlotValue", f'"0.125"^^<{XSD}float>'),
    # Already correct before the fix — pinned so they stay that way.
    ("xsd:integer on a frame sequence",
     f"{H}KGFrame", f"{H}hasFrameSequence", f'"0"^^<{XSD}integer>'),
    ("xsd:boolean",
     f"{H}KGEntity", f"{V}isActive", f'"true"^^<{XSD}boolean>'),
]


@pytest.mark.parametrize("label,type_uri,predicate,obj",
                         CASES, ids=[c[0] for c in CASES])
class TestTheTermSurvivesTheRoundTrip:

    def test_object_term_is_byte_identical(self, label, type_uri, predicate, obj):
        quads = _one(type_uri, predicate, obj)
        out = _roundtrip(quads)
        assert out[(f"<urn:t:1>", f"<{predicate}>")] == obj

    def test_datatype_is_not_dropped(self, label, type_uri, predicate, obj):
        """The specific failure: the suffix disappears and the term looks fine."""
        out = _roundtrip(_one(type_uri, predicate, obj))
        assert "^^<" in out[(f"<urn:t:1>", f"<{predicate}>")]


class TestTheTwoMeasuredRewrites:
    """Named individually, because these are the ones that were happening."""

    def test_xsd_string_does_not_become_a_plain_literal(self):
        out = _roundtrip(_one(f"{H}KGEntity", f"{V}hasName",
                              f'"Alice"^^<{XSD}string>'))
        assert out[("<urn:t:1>", f"<{V}hasName>")] != '"Alice"'

    def test_xsd_float_does_not_become_xsd_double(self):
        out = _roundtrip(_one(f"{H}KGCurrencySlot", f"{H}hasCurrencySlotValue",
                              f'"12.5"^^<{XSD}float>'))
        assert f"{XSD}double" not in out[("<urn:t:1>", f"<{H}hasCurrencySlotValue>")]


class TestUriPropertiesAndAnnotations:
    """Two things the fix must NOT change."""

    def test_a_uri_property_stays_a_uri(self):
        """A URI object must not acquire a datatype and become a literal."""
        out = _roundtrip(_one(f"{H}KGTextSlot", f"{H}hasKGSlotType",
                              "<urn:some:slot-type>"))
        assert out[("<urn:t:1>", f"<{H}hasKGSlotType>")] == "<urn:some:slot-type>"

    def test_an_annotation_stays_a_plain_literal(self):
        """`add_to_list_impl` writes annotations as bare `Literal(str(av))` — no
        datatype — so the store holds them plain. Emitting `^^xsd:string` here
        would be the same defect pointed the other way."""
        quads = _one(f"{H}KGEntity",
                     "http://www.w3.org/2000/01/rdf-schema#label", '"a label"')
        out = _roundtrip(quads)
        assert out[("<urn:t:1>",
                    "<http://www.w3.org/2000/01/rdf-schema#label>")] == '"a label"'

    def test_a_language_tag_survives_on_an_annotation(self):
        quads = _one(f"{H}KGEntity",
                     "http://www.w3.org/2000/01/rdf-schema#label", '"étiquette"@fr')
        out = _roundtrip(quads)
        assert out[("<urn:t:1>",
                    "<http://www.w3.org/2000/01/rdf-schema#label>")] == '"étiquette"@fr'


class TestAWholeSubjectRoundTrips:
    """The sample's actual shape: one subject, several typed literals at once."""

    def test_no_quad_is_rewritten(self):
        src = [
            Quad(s="<urn:t:9>", p=f"<{RDF_TYPE}>", o=f"<{H}KGEntity>", g=f"<{GRAPH}>"),
            Quad(s="<urn:t:9>", p=f"<{V}hasName>", o=f'"Widget"^^<{XSD}string>',
                 g=f"<{GRAPH}>"),
            Quad(s="<urn:t:9>", p=f"<{V}isActive>", o=f'"true"^^<{XSD}boolean>',
                 g=f"<{GRAPH}>"),
            Quad(s="<urn:t:9>", p=f"<{H}hasKGGraphURI>", o="<urn:t:9>", g=f"<{GRAPH}>"),
        ]
        out = _roundtrip(src)
        rewritten = [(q.p, q.o, out.get((q.s, q.p))) for q in src
                     if q.p != f"<{RDF_TYPE}>" and out.get((q.s, q.p)) != q.o]
        assert rewritten == []
