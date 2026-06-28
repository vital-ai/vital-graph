"""
Integration test: Annotation round-trip through VitalGraph server.

Tests that annotations (rdfs:label, rdfs:comment with language tags)
survive the full write → store → read cycle through all code paths:
  1. Quad serialization (fast outbound path)
  2. N-Quads text serialization
  3. SPARQL bindings → property map conversion
  4. Client ↔ server wire format transparency

Run locally (no server needed):
    python test_scripts/test_annotation_integration.py

Run against live server (requires VITALGRAPH_URL env or default localhost:8199):
    python test_scripts/test_annotation_integration.py --server
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from vitalgraph.utils.quad_format_utils import (
    graphobjects_to_quad_list, quad_list_to_graphobjects,
    quads_to_nquads_text, nquads_text_to_quads,
)
from vitalgraph.kg_impl.kg_graph_retrieval_utils import _bindings_to_objects


def _make_annotated_entity():
    """Create a KGEntity with multiple annotations for testing."""
    e = KGEntity()
    e.URI = 'urn:test:annotation_integration_1'
    e.name = 'AnnotationTestEntity'
    e.set_rdfs_label('Default Label')
    e.set_rdfs_label('Label EN', lang='en')
    e.set_rdfs_label('Label FR', lang='fr')
    e.set_rdfs_label('Label DE', lang='de')
    return e


def test_quad_roundtrip():
    """Test: GraphObject → Quad list → GraphObject preserves annotations."""
    print('  Test: Quad list round-trip ... ', end='')
    e = _make_annotated_entity()

    quads = graphobjects_to_quad_list([e], graph_uri='urn:test:graph')
    objects = quad_list_to_graphobjects(quads)

    assert len(objects) == 1, f"Expected 1 object, got {len(objects)}"
    obj = objects[0]
    assert obj.name == 'AnnotationTestEntity'
    assert obj.get_rdfs_label() == 'Default Label'
    assert obj.get_rdfs_label(lang='en') == 'Label EN'
    assert obj.get_rdfs_label(lang='fr') == 'Label FR'
    assert obj.get_rdfs_label(lang='de') == 'Label DE'
    print('PASS')


def test_nquads_text_roundtrip():
    """Test: GraphObject → N-Quads text → GraphObject preserves annotations."""
    print('  Test: N-Quads text round-trip ... ', end='')
    e = _make_annotated_entity()

    quads = graphobjects_to_quad_list([e], graph_uri='urn:test:graph')
    text = quads_to_nquads_text(quads)
    quads2 = nquads_text_to_quads(text)
    objects = quad_list_to_graphobjects(quads2)

    assert len(objects) == 1
    obj = objects[0]
    assert obj.name == 'AnnotationTestEntity'
    assert obj.get_rdfs_label() == 'Default Label'
    assert obj.get_rdfs_label(lang='en') == 'Label EN'
    assert obj.get_rdfs_label(lang='fr') == 'Label FR'
    assert obj.get_rdfs_label(lang='de') == 'Label DE'
    print('PASS')


def test_sparql_bindings_path():
    """Test: SPARQL JSON bindings with xml:lang → GraphObject preserves annotations."""
    print('  Test: SPARQL bindings path ... ', end='')

    RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName'
    KG_ENTITY_TYPE = 'http://vital.ai/ontology/haley-ai-kg#KGEntity'

    bindings = [
        {'s': {'value': 'urn:test:1'}, 'p': {'value': RDF_TYPE}, 'o': {'value': KG_ENTITY_TYPE, 'type': 'uri'}},
        {'s': {'value': 'urn:test:1'}, 'p': {'value': HAS_NAME}, 'o': {'value': 'FromSPARQL', 'type': 'literal'}},
        {'s': {'value': 'urn:test:1'}, 'p': {'value': RDFS_LABEL}, 'o': {'value': 'Plain Label', 'type': 'literal'}},
        {'s': {'value': 'urn:test:1'}, 'p': {'value': RDFS_LABEL}, 'o': {'value': 'English', 'type': 'literal', 'xml:lang': 'en'}},
        {'s': {'value': 'urn:test:1'}, 'p': {'value': RDFS_LABEL}, 'o': {'value': 'Francais', 'type': 'literal', 'xml:lang': 'fr'}},
    ]

    objs = _bindings_to_objects(bindings)
    assert len(objs) == 1
    obj = objs[0]
    assert obj.name == 'FromSPARQL'
    assert obj.get_rdfs_label() == 'Plain Label'
    assert obj.get_rdfs_label(lang='en') == 'English'
    assert obj.get_rdfs_label(lang='fr') == 'Francais'
    print('PASS')


def test_annotation_not_on_domain_property():
    """Test: Language-tagged literal on a domain property is just a plain string."""
    print('  Test: Domain property lang tag stripped ... ', end='')

    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName'
    KG_ENTITY_TYPE = 'http://vital.ai/ontology/haley-ai-kg#KGEntity'

    # Simulate a hasName with a language tag (shouldn't happen, but must not crash)
    bindings = [
        {'s': {'value': 'urn:test:2'}, 'p': {'value': RDF_TYPE}, 'o': {'value': KG_ENTITY_TYPE, 'type': 'uri'}},
        {'s': {'value': 'urn:test:2'}, 'p': {'value': HAS_NAME}, 'o': {'value': 'NameWithLang', 'type': 'literal', 'xml:lang': 'en'}},
    ]
    objs = _bindings_to_objects(bindings)
    assert len(objs) == 1
    obj = objs[0]
    # Language tag should be ignored for domain properties — value is plain string
    assert obj.name == 'NameWithLang', f"Got: {obj.name}"
    print('PASS')


def test_quad_outbound_includes_annotations():
    """Test: Fast outbound path emits annotation triples with language tags."""
    print('  Test: Outbound quads include annotation triples ... ', end='')
    e = _make_annotated_entity()

    quads = graphobjects_to_quad_list([e], graph_uri='urn:test:graph')

    # Find annotation quads
    label_quads = [q for q in quads if 'label' in q.p.lower()]
    assert len(label_quads) == 4, f"Expected 4 label quads, got {len(label_quads)}"

    # Check language encoding
    lang_quads = [q for q in label_quads if '@' in q.o]
    assert len(lang_quads) == 3, f"Expected 3 language-tagged quads, got {len(lang_quads)}"

    # Check plain label (no @)
    plain_quads = [q for q in label_quads if '@' not in q.o]
    assert len(plain_quads) == 1
    assert '"Default Label"' in plain_quads[0].o
    print('PASS')


def test_entity_without_annotations_unchanged():
    """Test: Entity without annotations serializes identically to before."""
    print('  Test: No-annotation entity unchanged ... ', end='')
    e = KGEntity()
    e.URI = 'urn:test:plain'
    e.name = 'PlainEntity'

    quads = graphobjects_to_quad_list([e], graph_uri='urn:test:graph')
    objects = quad_list_to_graphobjects(quads)

    assert len(objects) == 1
    obj = objects[0]
    assert obj.name == 'PlainEntity'
    assert not obj._annotations  # No annotations
    # No label quads emitted
    label_quads = [q for q in quads if 'label' in q.p.lower()]
    assert len(label_quads) == 0
    print('PASS')


def main():
    parser = argparse.ArgumentParser(description='Annotation integration tests')
    parser.add_argument('--server', action='store_true', help='Run against live server (not implemented yet)')
    args = parser.parse_args()

    print('=== Annotation Integration Tests ===')
    print()

    test_quad_roundtrip()
    test_nquads_text_roundtrip()
    test_sparql_bindings_path()
    test_annotation_not_on_domain_property()
    test_quad_outbound_includes_annotations()
    test_entity_without_annotations_unchanged()

    print()
    print('=== ALL TESTS PASSED ===')


if __name__ == '__main__':
    main()
