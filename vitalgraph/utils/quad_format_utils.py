"""
Quad Format Utilities

Conversion between VitalSigns GraphObjects and the two new wire formats:
  1. N-Quads (application/n-quads) — plain text, one quad per line
  2. JSON Quads (application/json) — JSON envelope with {s, p, o, g} maps

Term encoding follows standard N-Quads rules:
  - URIs:                  <http://example.org/thing>
  - Plain string literals: "value"
  - Typed literals:        "30"^^<http://www.w3.org/2001/XMLSchema#integer>
  - Language-tagged:       "hello"@en
  - Blank nodes:           _:b1

Both formats use identical term encoding — conversion between them is mechanical.
"""

import logging
from typing import List, Optional, Tuple, Any

from rdflib import URIRef, Literal, BNode
from rdflib.term import Node

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse

logger = logging.getLogger(__name__)

# The default XSD string datatype — literals with this type omit the ^^<datatype> suffix
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


# ---------------------------------------------------------------------------
# RDFLib term  →  N-Quads string encoding
# ---------------------------------------------------------------------------

def rdflib_term_to_nquads(term: Node) -> str:
    """Encode an RDFLib term as an N-Quads string.

    Returns the standard N-Quads encoding:
      URIRef   → <http://example.org/thing>
      Literal  → "value", "value"^^<datatype>, or "value"@lang
      BNode    → _:label
    """
    if isinstance(term, URIRef):
        return f"<{str(term)}>"
    elif isinstance(term, Literal):
        # Escape special characters in the lexical form
        escaped = _escape_nquads_string(str(term))
        if term.language:
            return f'"{escaped}"@{term.language}'
        elif term.datatype and str(term.datatype) != XSD_STRING:
            return f'"{escaped}"^^<{str(term.datatype)}>'
        else:
            return f'"{escaped}"'
    elif isinstance(term, BNode):
        return f"_:{str(term)}"
    else:
        # Fallback: treat as string literal
        escaped = _escape_nquads_string(str(term))
        return f'"{escaped}"'


def _escape_nquads_string(s: str) -> str:
    """Escape special characters per N-Quads/N-Triples grammar."""
    return (s
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', '\\n')
            .replace('\r', '\\r'))


def _unescape_nquads_string(s: str) -> str:
    """Unescape N-Quads string escape sequences."""
    return (s
            .replace('\\r', '\r')
            .replace('\\n', '\n')
            .replace('\\"', '"')
            .replace('\\\\', '\\'))


# ---------------------------------------------------------------------------
# N-Quads string encoding  →  RDFLib term
# ---------------------------------------------------------------------------

def nquads_term_to_rdflib(term_str: str) -> Node:
    """Parse an N-Quads encoded term string back to an RDFLib term.

    Accepts:
      <http://...>                              → URIRef
      "value"                                   → Literal (plain, no datatype)
      "value"^^<http://...>                     → Literal with datatype
      "value"@lang                              → Literal with language tag
      _:label                                   → BNode
    """
    term_str = term_str.strip()

    if term_str.startswith('<') and term_str.endswith('>'):
        return URIRef(term_str[1:-1])

    if term_str.startswith('_:'):
        return BNode(term_str[2:])

    if term_str.startswith('"'):
        # Find the closing quote (handling escaped quotes)
        i = 1
        while i < len(term_str):
            if term_str[i] == '\\':
                i += 2  # skip escape sequence
                continue
            if term_str[i] == '"':
                break
            i += 1

        lexical = _unescape_nquads_string(term_str[1:i])
        rest = term_str[i + 1:]

        if rest.startswith('^^<') and rest.endswith('>'):
            datatype = URIRef(rest[3:-1])
            return Literal(lexical, datatype=datatype)
        elif rest.startswith('@'):
            lang = rest[1:]
            return Literal(lexical, lang=lang)
        else:
            return Literal(lexical)

    # Fallback: bare string → Literal
    return Literal(term_str)


# ---------------------------------------------------------------------------
# GraphObjects  →  Quad list  (internal representation)
# ---------------------------------------------------------------------------

def graphobjects_to_quad_list(
    graph_objects: List[GraphObject],
    graph_uri: Optional[str] = None
) -> List[Quad]:
    """Convert VitalSigns GraphObjects to a list of Quad models.

    Optimized path: uses to_property_maps + ontology manager for type
    resolution — bypasses rdflib entirely.

    Falls back to the original rdflib path on any error.

    Args:
        graph_objects: VitalSigns GraphObject instances
        graph_uri: Optional graph URI (without angle brackets).
                   If provided, all quads get this graph.
                   If None, quads have g=None (default graph).

    Returns:
        List of Quad Pydantic models with N-Quads term encoding.
    """
    if not graph_objects:
        return []

    try:
        return _graphobjects_to_quad_list_fast(graph_objects, graph_uri)
    except Exception as e:
        logger.warning("Fast GraphObject→Quad path failed (%s), falling back to rdflib", e)
        return _graphobjects_to_quad_list_rdflib(graph_objects, graph_uri)


def _graphobjects_to_quad_list_rdflib(
    graph_objects: List[GraphObject],
    graph_uri: Optional[str] = None
) -> List[Quad]:
    """ORIGINAL: Convert GraphObjects to Quads via rdflib. Kept for revert."""
    if len(graph_objects) == 1:
        triples = graph_objects[0].to_triples()
    else:
        triples = GraphObject.to_triples_list(graph_objects)

    g_encoded = f"<{graph_uri}>" if graph_uri else None

    quads = []
    for s, p, o in triples:
        quads.append(Quad(
            s=rdflib_term_to_nquads(s),
            p=rdflib_term_to_nquads(p),
            o=rdflib_term_to_nquads(o),
            g=g_encoded,
        ))

    logger.debug("Converted %d GraphObjects to %d quads (rdflib path)", len(graph_objects), len(quads))
    return quads


# ---------------------------------------------------------------------------
# Fast outbound path — no rdflib (uses to_property_maps + ontology manager)
# ---------------------------------------------------------------------------

# Cache: property_uri → bool (is URI property)
_uri_prop_cache: dict = {}


def _is_uri_property(prop_uri: str) -> Optional[bool]:
    """Check if a property URI is a URI-typed property via ontology manager."""
    cached = _uri_prop_cache.get(prop_uri)
    if cached is not None:
        return cached

    try:
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        from vital_ai_vitalsigns.model.properties.URIProperty import URIProperty
        vs = VitalSigns()
        ont_manager = vs.get_ontology_manager()
        prop_info = ont_manager.get_property_info(prop_uri)
        prop_class = prop_info.get("prop_class") if prop_info else None
        result = prop_class is URIProperty
        _uri_prop_cache[prop_uri] = result
        return result
    except Exception:
        return None


def _value_to_nquads_outbound(value, is_uri: bool) -> str:
    """Encode a native Python value to an N-Quads object term string."""
    if is_uri and isinstance(value, str):
        return f"<{value}>"
    if isinstance(value, bool):
        return f'"{str(value).lower()}"^^<{_XSD}boolean>'
    if isinstance(value, int):
        return f'"{value}"^^<{_XSD}integer>'
    if isinstance(value, float):
        return f'"{value}"^^<{_XSD}double>'
    if isinstance(value, str):
        escaped = _escape_nquads_string(value)
        return f'"{escaped}"'
    # datetime
    from datetime import datetime
    if isinstance(value, datetime):
        iso = value.isoformat()
        return f'"{iso}"^^<{_XSD}dateTime>'
    # fallback
    escaped = _escape_nquads_string(str(value))
    return f'"{escaped}"'


def _graphobjects_to_quad_list_fast(
    graph_objects: List[GraphObject],
    graph_uri: Optional[str] = None
) -> List[Quad]:
    """Convert GraphObjects → Quads via to_property_maps (no rdflib)."""
    maps = GraphObject.to_property_maps(graph_objects)

    g_encoded = f"<{graph_uri}>" if graph_uri else None
    quads = []

    for pm in maps:
        s = f"<{pm['subject_uri']}>"
        type_uri = pm['type_uri']

        # rdf:type, vitaltype, URIProp triples
        quads.append(Quad(s=s, p=f"<{_RDF_TYPE}>", o=f"<{type_uri}>", g=g_encoded))
        quads.append(Quad(s=s, p=f"<{_VITALTYPE}>", o=f"<{type_uri}>", g=g_encoded))
        quads.append(Quad(s=s, p=f"<{_URI_PROP}>", o=s, g=g_encoded))

        for prop_uri, value in pm['properties'].items():
            p_enc = f"<{prop_uri}>"
            is_uri = _is_uri_property(prop_uri)
            if is_uri is None:
                is_uri = False

            values = value if isinstance(value, list) else [value]
            for v in values:
                o_enc = _value_to_nquads_outbound(v, is_uri)
                quads.append(Quad(s=s, p=p_enc, o=o_enc, g=g_encoded))

    logger.debug("Converted %d GraphObjects to %d quads (fast path)", len(graph_objects), len(quads))
    return quads


def quad_list_to_graphobjects(quads: List[Quad]) -> List[GraphObject]:
    """Convert a list of Quad models back to VitalSigns GraphObjects.

    Optimized path: parses N-Quads terms directly into property maps and
    calls GraphObject.from_property_maps — bypasses rdflib entirely.

    Falls back to the original rdflib path on any error.

    Args:
        quads: List of Quad Pydantic models

    Returns:
        List of VitalSigns GraphObjects
    """
    if not quads:
        return []

    try:
        return _quad_list_to_graphobjects_fast(quads)
    except Exception as e:
        logger.warning("Fast quad→GraphObject path failed (%s), falling back to rdflib", e)
        return _quad_list_to_graphobjects_rdflib(quads)


# ---------------------------------------------------------------------------
# Optimised path — no rdflib
# ---------------------------------------------------------------------------

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
_URI_PROP = "http://vital.ai/ontology/vital-core#URIProp"
_XSD = "http://www.w3.org/2001/XMLSchema#"


def _parse_nquads_object(term_str: str) -> Any:
    """Parse an N-Quads object term into a native Python value.

    Returns:
        str for URIs and plain/language literals,
        int/float/bool/datetime for typed literals.
    """
    term_str = term_str.strip()

    # URI
    if term_str.startswith('<') and term_str.endswith('>'):
        return term_str[1:-1]

    # Blank node — return as-is
    if term_str.startswith('_:'):
        return term_str

    # Literal
    if term_str.startswith('"'):
        i = 1
        while i < len(term_str):
            if term_str[i] == '\\':
                i += 2
                continue
            if term_str[i] == '"':
                break
            i += 1

        lexical = _unescape_nquads_string(term_str[1:i])
        rest = term_str[i + 1:]

        if rest.startswith('^^<') and rest.endswith('>'):
            datatype = rest[3:-1]
            return _convert_typed_literal(lexical, datatype)
        # Language-tagged or plain string → just return lexical value
        return lexical

    return term_str


def _convert_typed_literal(value_str: str, datatype: str):
    """Convert a typed literal to the appropriate Python type."""
    if not datatype.startswith(_XSD):
        return value_str
    local = datatype[len(_XSD):]
    if local in ('integer', 'int', 'long', 'short', 'byte',
                 'nonNegativeInteger', 'positiveInteger',
                 'nonPositiveInteger', 'negativeInteger',
                 'unsignedLong', 'unsignedInt', 'unsignedShort', 'unsignedByte'):
        return int(value_str)
    if local in ('float', 'double', 'decimal'):
        return float(value_str)
    if local == 'boolean':
        return value_str.lower() in ('true', '1')
    if local == 'dateTime':
        from datetime import datetime
        try:
            return datetime.fromisoformat(value_str.replace('Z', '+00:00'))
        except ValueError:
            return value_str
    return value_str


def _parse_nquads_uri(term_str: str) -> str:
    """Extract URI from an N-Quads angle-bracket term."""
    term_str = term_str.strip()
    if term_str.startswith('<') and term_str.endswith('>'):
        return term_str[1:-1]
    return term_str


def _quad_list_to_graphobjects_fast(quads: List[Quad]) -> List[GraphObject]:
    """Convert quads → GraphObjects via from_property_maps (no rdflib)."""
    from collections import defaultdict

    subjects: dict = defaultdict(lambda: {'type_uri': None, 'properties': {}})

    for quad in quads:
        s_uri = _parse_nquads_uri(quad.s)
        p_uri = _parse_nquads_uri(quad.p)
        o_val = _parse_nquads_object(quad.o)

        if p_uri == _RDF_TYPE or p_uri == _VITALTYPE:
            # Type URI — extract the URI value
            if isinstance(o_val, str):
                subjects[s_uri]['type_uri'] = o_val
            continue
        if p_uri == _URI_PROP:
            continue

        props = subjects[s_uri]['properties']
        if p_uri in props:
            existing = props[p_uri]
            if isinstance(existing, list):
                existing.append(o_val)
            else:
                props[p_uri] = [existing, o_val]
        else:
            props[p_uri] = o_val

    entries = []
    for subject_uri, data in subjects.items():
        if data['type_uri']:
            entries.append({
                'subject_uri': subject_uri,
                'type_uri': data['type_uri'],
                'properties': data['properties'],
            })

    if not entries:
        return []

    graph_objects = GraphObject.from_property_maps(entries)
    logger.debug("Converted %d quads to %d GraphObjects (fast path)", len(quads), len(graph_objects))
    return graph_objects


# ---------------------------------------------------------------------------
# Original rdflib path — kept for fallback / revert
# ---------------------------------------------------------------------------

def _quad_list_to_graphobjects_rdflib(quads: List[Quad]) -> List[GraphObject]:
    """ORIGINAL: Convert quads to GraphObjects via rdflib. Kept for revert."""
    from rdflib import Graph as RDFGraph

    g = RDFGraph()
    for quad in quads:
        s = nquads_term_to_rdflib(quad.s)
        p = nquads_term_to_rdflib(quad.p)
        o = nquads_term_to_rdflib(quad.o)
        g.add((s, p, o))

    triples_list = list(g.triples((None, None, None)))
    graph_objects = GraphObject.from_triples_list(triples_list)
    logger.debug("Converted %d quads to %d GraphObjects (rdflib path)", len(quads), len(graph_objects))
    return graph_objects


# ---------------------------------------------------------------------------
# N-Quads text serialization / deserialization
# ---------------------------------------------------------------------------

def quads_to_nquads_text(quads: List[Quad]) -> str:
    """Serialize a list of Quad models to N-Quads text format.

    Each quad becomes one line:  <s> <p> <o> <g> .
    If g is None, the graph label is omitted:  <s> <p> <o> .
    """
    lines = []
    for quad in quads:
        if quad.g:
            lines.append(f"{quad.s} {quad.p} {quad.o} {quad.g} .")
        else:
            lines.append(f"{quad.s} {quad.p} {quad.o} .")
    return "\n".join(lines)


def nquads_text_to_quads(text: str) -> List[Quad]:
    """Parse N-Quads text into a list of Quad models.

    Each non-empty, non-comment line is parsed as:
      <s> <p> <o> .           (triple — default graph)
      <s> <p> <o> <g> .       (quad — named graph)
    """
    quads = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Remove trailing period
        if line.endswith('.'):
            line = line[:-1].rstrip()

        tokens = _tokenize_nquads_line(line)
        if len(tokens) == 3:
            quads.append(Quad(s=tokens[0], p=tokens[1], o=tokens[2], g=None))
        elif len(tokens) >= 4:
            quads.append(Quad(s=tokens[0], p=tokens[1], o=tokens[2], g=tokens[3]))
        else:
            logger.warning(f"Skipping malformed N-Quads line: {line}")

    return quads


def _tokenize_nquads_line(line: str) -> List[str]:
    """Tokenize a single N-Quads line into term strings.

    Handles:
      <uri>       — angle-bracket delimited
      "literal"   — with possible ^^<datatype> or @lang suffix
      _:label     — blank node
    """
    tokens = []
    i = 0
    n = len(line)

    while i < n:
        # Skip whitespace
        while i < n and line[i] in ' \t':
            i += 1
        if i >= n:
            break

        if line[i] == '<':
            # URI: read until closing >
            j = line.index('>', i) + 1
            tokens.append(line[i:j])
            i = j

        elif line[i] == '"':
            # Literal: read until unescaped closing quote, then consume suffix
            j = i + 1
            while j < n:
                if line[j] == '\\':
                    j += 2
                    continue
                if line[j] == '"':
                    break
                j += 1
            j += 1  # past closing quote
            # Check for datatype or language suffix
            if j < n and line[j:j+2] == '^^':
                # Typed literal: ^^<datatype>
                k = line.index('>', j) + 1
                tokens.append(line[i:k])
                i = k
            elif j < n and line[j] == '@':
                # Language tag: @en
                k = j + 1
                while k < n and line[k] not in ' \t':
                    k += 1
                tokens.append(line[i:k])
                i = k
            else:
                tokens.append(line[i:j])
                i = j

        elif line[i:i+2] == '_:':
            # Blank node
            j = i + 2
            while j < n and line[j] not in ' \t':
                j += 1
            tokens.append(line[i:j])
            i = j

        else:
            # Unknown — skip to next whitespace
            j = i
            while j < n and line[j] not in ' \t':
                j += 1
            tokens.append(line[i:j])
            i = j

    return tokens


# ---------------------------------------------------------------------------
# JSON Quads serialization / deserialization
# ---------------------------------------------------------------------------

def quads_to_json_quads_response(
    quads: List[Quad],
    total_count: int,
    page_size: int,
    offset: int,
) -> QuadResponse:
    """Build a QuadResponse envelope from a list of quads + pagination metadata."""
    return QuadResponse(
        total_count=total_count,
        page_size=page_size,
        offset=offset,
        results=quads,
    )


def json_quads_request_to_quads(request: QuadRequest) -> List[Quad]:
    """Extract the quad list from a QuadRequest."""
    return request.quads


# ---------------------------------------------------------------------------
# Convenience: GraphObjects  →  wire format (end-to-end)
# ---------------------------------------------------------------------------

def graphobjects_to_nquads_response(
    graph_objects: List[GraphObject],
    graph_uri: Optional[str] = None,
) -> str:
    """Convert GraphObjects directly to N-Quads text."""
    quads = graphobjects_to_quad_list(graph_objects, graph_uri)
    return quads_to_nquads_text(quads)


def graphobjects_to_json_quads_response(
    graph_objects: List[GraphObject],
    graph_uri: Optional[str] = None,
    total_count: int = 0,
    page_size: int = 0,
    offset: int = 0,
) -> QuadResponse:
    """Convert GraphObjects directly to a JSON Quads response envelope."""
    quads = graphobjects_to_quad_list(graph_objects, graph_uri)
    return quads_to_json_quads_response(quads, total_count, page_size, offset)


def nquads_request_to_graphobjects(nquads_text: str) -> List[GraphObject]:
    """Parse N-Quads request text directly to GraphObjects."""
    quads = nquads_text_to_quads(nquads_text)
    return quad_list_to_graphobjects(quads)


def json_quads_request_to_graphobjects(request: QuadRequest) -> List[GraphObject]:
    """Parse a JSON Quads request directly to GraphObjects."""
    quads = json_quads_request_to_quads(request)
    return quad_list_to_graphobjects(quads)
