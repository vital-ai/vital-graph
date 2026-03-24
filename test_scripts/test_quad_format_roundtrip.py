"""
Round-trip test for N-Quads and JSON Quads format utilities.

Tests that VitalSigns GraphObjects can be serialized to both formats
and deserialized back without data loss. Covers:
  - KGEntity (string properties)
  - KGFrame (string properties)
  - KGTextSlot (text literal)
  - KGIntegerSlot (typed integer literal)
  - KGDateTimeSlot (typed datetime literal)
  - KGBooleanSlot (typed boolean literal)
  - Edge_hasEntityKGFrame (URI properties)
  - Edge_hasKGSlot (URI properties)
  - N-Quads text round-trip
  - JSON Quads model round-trip
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

# Quad format utilities
from vitalgraph.utils.quad_format_utils import (
    graphobjects_to_quad_list,
    quads_to_nquads_text,
    nquads_text_to_quads,
    rdflib_term_to_nquads,
    nquads_term_to_rdflib,
    graphobjects_to_json_quads_response,
    graphobjects_to_nquads_response,
)
from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse


GRAPH_URI = "http://vital.ai/graph/test-roundtrip"


def build_test_objects():
    """Build a representative set of VitalSigns objects covering all KG types."""

    entity = KGEntity()
    entity.URI = "urn:test:entity:001"
    entity.name = "Test Entity"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"

    frame = KGFrame()
    frame.URI = "urn:test:frame:001"
    frame.name = "Contact Info"
    frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ContactFrame"

    text_slot = KGTextSlot()
    text_slot.URI = "urn:test:slot:text:001"
    text_slot.name = "Email"
    text_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EmailSlot"
    text_slot.textSlotValue = "alice@example.com"

    int_slot = KGIntegerSlot()
    int_slot.URI = "urn:test:slot:int:001"
    int_slot.name = "Age"
    int_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#AgeSlot"
    int_slot.integerSlotValue = 30

    bool_slot = KGBooleanSlot()
    bool_slot.URI = "urn:test:slot:bool:001"
    bool_slot.name = "Active"
    bool_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#ActiveSlot"
    bool_slot.booleanSlotValue = False

    dt_slot = KGDateTimeSlot()
    dt_slot.URI = "urn:test:slot:dt:001"
    dt_slot.name = "Created"
    dt_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#CreatedSlot"
    dt_slot.dateTimeSlotValue = datetime(2024, 6, 15)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = "urn:test:edge:entity_frame:001"
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = frame.URI

    edge_fs = Edge_hasKGSlot()
    edge_fs.URI = "urn:test:edge:frame_slot:001"
    edge_fs.edgeSource = frame.URI
    edge_fs.edgeDestination = text_slot.URI

    return [entity, frame, text_slot, int_slot, bool_slot, dt_slot, edge_ef, edge_fs]


def test_term_encoding():
    """Test individual RDFLib term → N-Quads string → RDFLib term round-trip."""
    from rdflib import URIRef, Literal, BNode, XSD

    passed = 0
    failed = 0

    test_cases = [
        ("URI", URIRef("http://example.org/thing")),
        ("Plain literal", Literal("hello world")),
        ("Integer literal", Literal(42, datatype=XSD.integer)),
        ("Boolean literal", Literal(False, datatype=XSD.boolean)),
        ("Date literal", Literal("2024-06-15", datatype=XSD.date)),
        ("DateTime literal", Literal("2024-06-15T00:00:00", datatype=XSD.dateTime)),
        ("Double literal", Literal(3.14, datatype=XSD.double)),
        ("Lang literal", Literal("bonjour", lang="fr")),
        ("Blank node", BNode("b123")),
        ("Escaped literal", Literal('line1\nline2\r\n"quoted"')),
    ]

    logger.info("\n=== Test: Individual Term Encoding Round-Trip ===")
    for label, term in test_cases:
        encoded = rdflib_term_to_nquads(term)
        decoded = nquads_term_to_rdflib(encoded)

        # Compare string representations (RDFLib equality can be quirky across types)
        ok = str(decoded) == str(term) and type(decoded) == type(term)
        if isinstance(term, Literal):
            ok = ok and decoded.datatype == term.datatype and decoded.language == term.language

        if ok:
            logger.info(f"  PASS  {label}: {encoded}")
            passed += 1
        else:
            logger.error(f"  FAIL  {label}: {encoded} → {decoded!r} (expected {term!r})")
            failed += 1

    return passed, failed


def test_nquads_text_roundtrip():
    """Test GraphObjects → N-Quads text → parse back to Quad list."""
    logger.info("\n=== Test: N-Quads Text Round-Trip ===")

    objects = build_test_objects()

    # Forward: GraphObjects → Quads → N-Quads text
    quads = graphobjects_to_quad_list(objects, GRAPH_URI)
    nquads_text = quads_to_nquads_text(quads)

    logger.info(f"  Serialized {len(objects)} GraphObjects to {len(quads)} quads")
    logger.info(f"  N-Quads text size: {len(nquads_text)} bytes, {len(nquads_text.splitlines())} lines")

    # Show first 5 lines
    for line in nquads_text.splitlines()[:5]:
        logger.info(f"    {line}")
    if len(nquads_text.splitlines()) > 5:
        logger.info(f"    ... and {len(nquads_text.splitlines()) - 5} more lines")

    # Reverse: N-Quads text → Quad list
    parsed_quads = nquads_text_to_quads(nquads_text)

    passed = 0
    failed = 0

    if len(parsed_quads) == len(quads):
        logger.info(f"  PASS  Quad count matches: {len(parsed_quads)}")
        passed += 1
    else:
        logger.error(f"  FAIL  Quad count mismatch: {len(parsed_quads)} != {len(quads)}")
        failed += 1

    # Verify each quad round-trips
    for i, (orig, parsed) in enumerate(zip(quads, parsed_quads)):
        if orig.s == parsed.s and orig.p == parsed.p and orig.o == parsed.o and orig.g == parsed.g:
            passed += 1
        else:
            logger.error(f"  FAIL  Quad {i} mismatch:")
            logger.error(f"    orig:   s={orig.s} p={orig.p} o={orig.o} g={orig.g}")
            logger.error(f"    parsed: s={parsed.s} p={parsed.p} o={parsed.o} g={parsed.g}")
            failed += 1

    logger.info(f"  Verified {passed} quads match")
    return passed, failed


def test_json_quads_roundtrip():
    """Test GraphObjects → JSON Quads response → serialize → parse back."""
    logger.info("\n=== Test: JSON Quads Round-Trip ===")

    objects = build_test_objects()

    # Forward: GraphObjects → QuadResponse
    response = graphobjects_to_json_quads_response(
        objects, GRAPH_URI, total_count=100, page_size=50, offset=0
    )

    # Serialize to JSON and back
    json_str = response.model_dump_json()
    parsed_response = QuadResponse.model_validate_json(json_str)

    passed = 0
    failed = 0

    # Check metadata
    for field in ["total_count", "page_size", "offset"]:
        orig_val = getattr(response, field)
        parsed_val = getattr(parsed_response, field)
        if orig_val == parsed_val:
            passed += 1
        else:
            logger.error(f"  FAIL  {field}: {parsed_val} != {orig_val}")
            failed += 1

    # Check quads
    if len(parsed_response.results) == len(response.results):
        logger.info(f"  PASS  Result count matches: {len(parsed_response.results)}")
        passed += 1
    else:
        logger.error(f"  FAIL  Result count: {len(parsed_response.results)} != {len(response.results)}")
        failed += 1

    for i, (orig, parsed) in enumerate(zip(response.results, parsed_response.results)):
        if orig == parsed:
            passed += 1
        else:
            logger.error(f"  FAIL  Result {i} mismatch")
            failed += 1

    logger.info(f"  JSON size: {len(json_str)} bytes")
    logger.info(f"  Verified {passed} fields/quads match")
    return passed, failed


def test_quad_request_model():
    """Test QuadRequest serialization/deserialization."""
    logger.info("\n=== Test: QuadRequest Model ===")

    quads = [
        Quad(s="<urn:test:s1>", p="<urn:test:p1>", o='"hello"', g="<urn:test:g1>"),
        Quad(s="<urn:test:s2>", p="<urn:test:p2>", o='"42"^^<http://www.w3.org/2001/XMLSchema#integer>'),
    ]

    request = QuadRequest(quads=quads)
    json_str = request.model_dump_json()
    parsed = QuadRequest.model_validate_json(json_str)

    passed = 0
    failed = 0

    if len(parsed.quads) == 2:
        passed += 1
    else:
        failed += 1

    if parsed.quads[0].g == "<urn:test:g1>":
        passed += 1
    else:
        failed += 1

    if parsed.quads[1].g is None:
        logger.info("  PASS  g=None for default graph quad")
        passed += 1
    else:
        logger.error(f"  FAIL  g should be None, got: {parsed.quads[1].g}")
        failed += 1

    logger.info(f"  QuadRequest JSON size: {len(json_str)} bytes")
    return passed, failed


def test_nquads_convenience():
    """Test the convenience function for direct GraphObjects → N-Quads text."""
    logger.info("\n=== Test: Convenience Functions ===")

    objects = build_test_objects()
    nquads_text = graphobjects_to_nquads_response(objects, GRAPH_URI)

    passed = 0
    failed = 0

    if nquads_text and len(nquads_text.splitlines()) > 0:
        logger.info(f"  PASS  graphobjects_to_nquads_response: {len(nquads_text.splitlines())} lines")
        passed += 1
    else:
        logger.error("  FAIL  graphobjects_to_nquads_response returned empty")
        failed += 1

    # Verify every line ends correctly (no trailing whitespace issues)
    for i, line in enumerate(nquads_text.splitlines()):
        if line.endswith('.'):
            passed += 1
        else:
            logger.error(f"  FAIL  Line {i} missing period: {line}")
            failed += 1

    return passed, failed


def main():
    total_passed = 0
    total_failed = 0

    for test_fn in [
        test_term_encoding,
        test_nquads_text_roundtrip,
        test_json_quads_roundtrip,
        test_quad_request_model,
        test_nquads_convenience,
    ]:
        p, f = test_fn()
        total_passed += p
        total_failed += f

    logger.info(f"\n{'='*60}")
    logger.info(f"  TOTAL: {total_passed} passed, {total_failed} failed")
    logger.info(f"{'='*60}")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
