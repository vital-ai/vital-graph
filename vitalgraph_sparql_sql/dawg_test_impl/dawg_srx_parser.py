"""
Parse SPARQL Results XML (.srx) and JSON (.srj) files.

Extracts variable names and result bindings into a normalized format
that can be compared across engines.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# SPARQL Results XML namespace
SRX_NS = "http://www.w3.org/2005/sparql-results#"


@dataclass
class SparqlBinding:
    """A single binding value in a SPARQL result row."""
    type: str  # "uri", "literal", "bnode"
    value: str
    datatype: Optional[str] = None
    lang: Optional[str] = None

    def to_normalized_tuple(self) -> tuple:
        """Return a hashable normalized representation."""
        return (self.type, self.value, self.datatype or "", self.lang or "")


@dataclass
class SparqlResults:
    """Parsed SPARQL query results."""
    variables: List[str]
    rows: List[Dict[str, SparqlBinding]]
    is_boolean: bool = False
    boolean_value: Optional[bool] = None
    is_graph: bool = False


def parse_result_file(path: Path) -> Optional[SparqlResults]:
    """Parse a .srx (XML) or .srj (JSON) result file.

    Returns None if the file format is not supported or parsing fails.
    """
    if not path.exists():
        logger.warning("Result file not found: %s", path)
        return None

    suffix = path.suffix.lower()

    if suffix == ".srx":
        return _parse_srx(path)
    elif suffix == ".srj":
        return _parse_srj(path)
    elif suffix == ".ttl":
        return _parse_ttl_graph(path)
    elif suffix == ".rdf":
        return _parse_rdf_xml_graph(path)
    elif suffix == ".trig":
        return _parse_trig_graph(path)
    else:
        logger.warning("Unknown result format: %s", path)
        return None


def _parse_srx(path: Path) -> Optional[SparqlResults]:
    """Parse a SPARQL Results XML file."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        logger.error("XML parse error in %s: %s", path, e)
        return None

    root = tree.getroot()

    # Handle namespace — the root might use the namespace or not
    ns = {"sr": SRX_NS}

    # Try with namespace first, then without
    # NOTE: use 'is not None' — empty elements are falsy in ElementTree
    head = root.find("sr:head", ns)
    if head is None:
        head = root.find("head")
    if head is None:
        logger.error("No <head> element in %s", path)
        return None

    # Check for boolean result (ASK queries)
    boolean_el = root.find("sr:boolean", ns)
    if boolean_el is None:
        boolean_el = root.find("boolean")
    if boolean_el is not None:
        return SparqlResults(
            variables=[],
            rows=[],
            is_boolean=True,
            boolean_value=boolean_el.text.strip().lower() == "true",
        )

    # Extract variable names
    variables = []
    for var_el in head.findall("sr:variable", ns) + head.findall("variable"):
        name = var_el.get("name")
        if name:
            variables.append(name)

    # Extract result rows
    results_el = root.find("sr:results", ns)
    if results_el is None:
        results_el = root.find("results")
    rows: List[Dict[str, SparqlBinding]] = []

    if results_el is not None:
        for result_el in results_el.findall("sr:result", ns) + results_el.findall("result"):
            row: Dict[str, SparqlBinding] = {}
            for binding_el in result_el.findall("sr:binding", ns) + result_el.findall("binding"):
                var_name = binding_el.get("name")
                if var_name is None:
                    continue

                binding = _parse_srx_binding(binding_el, ns)
                if binding is not None:
                    row[var_name] = binding

            rows.append(row)

    return SparqlResults(variables=variables, rows=rows)


def _parse_srx_binding(binding_el, ns: dict) -> Optional[SparqlBinding]:
    """Parse a single <binding> element."""
    # Try with namespace, then without
    for prefix in ["sr:", ""]:
        uri_el = binding_el.find(f"{prefix}uri", ns) if prefix else binding_el.find("uri")
        if uri_el is not None:
            return SparqlBinding(type="uri", value=uri_el.text or "")

        literal_el = binding_el.find(f"{prefix}literal", ns) if prefix else binding_el.find("literal")
        if literal_el is not None:
            return SparqlBinding(
                type="literal",
                value=literal_el.text or "",
                datatype=literal_el.get("datatype"),
                lang=literal_el.get("{http://www.w3.org/XML/1998/namespace}lang"),
            )

        bnode_el = binding_el.find(f"{prefix}bnode", ns) if prefix else binding_el.find("bnode")
        if bnode_el is not None:
            return SparqlBinding(type="bnode", value=bnode_el.text or "")

    return None


def _parse_srj(path: Path) -> Optional[SparqlResults]:
    """Parse a SPARQL Results JSON file."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("JSON parse error in %s: %s", path, e)
        return None

    # Boolean result
    if "boolean" in data:
        return SparqlResults(
            variables=[],
            rows=[],
            is_boolean=True,
            boolean_value=data["boolean"],
        )

    # Variables
    head = data.get("head", {})
    variables = head.get("vars", [])

    # Results
    results = data.get("results", {})
    bindings = results.get("bindings", [])

    rows: List[Dict[str, SparqlBinding]] = []
    for binding_dict in bindings:
        row: Dict[str, SparqlBinding] = {}
        for var_name, val in binding_dict.items():
            row[var_name] = SparqlBinding(
                type=val.get("type", "literal"),
                value=val.get("value", ""),
                datatype=val.get("datatype"),
                lang=val.get("xml:lang"),
            )
        rows.append(row)

    return SparqlResults(variables=variables, rows=rows)


def _parse_ttl_graph(path: Path) -> Optional[SparqlResults]:
    """Parse a Turtle (.ttl) file into triples for CONSTRUCT comparison."""
    try:
        import pyoxigraph
    except ImportError:
        logger.error("pyoxigraph not available for TTL parsing")
        return None

    try:
        store = pyoxigraph.Store()
        store.load(path.read_bytes(), "text/turtle")
    except Exception as e:
        logger.error("TTL parse error in %s: %s", path, e)
        return None

    _XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

    rows: List[Dict[str, SparqlBinding]] = []
    for quad in store:
        triple: Dict[str, SparqlBinding] = {}

        # Subject
        s = quad.subject
        if isinstance(s, pyoxigraph.NamedNode):
            triple["subject"] = SparqlBinding(type="uri", value=s.value)
        elif isinstance(s, pyoxigraph.BlankNode):
            triple["subject"] = SparqlBinding(type="bnode", value=s.value)

        # Predicate
        p = quad.predicate
        triple["predicate"] = SparqlBinding(type="uri", value=p.value)

        # Object
        o = quad.object
        if isinstance(o, pyoxigraph.NamedNode):
            triple["object"] = SparqlBinding(type="uri", value=o.value)
        elif isinstance(o, pyoxigraph.BlankNode):
            triple["object"] = SparqlBinding(type="bnode", value=o.value)
        elif isinstance(o, pyoxigraph.Literal):
            dt = str(o.datatype) if o.datatype else None
            if dt == _XSD_STRING:
                dt = None
            triple["object"] = SparqlBinding(
                type="literal", value=o.value,
                lang=o.language, datatype=dt,
            )

        rows.append(triple)

    return SparqlResults(
        variables=["subject", "predicate", "object"],
        rows=rows,
        is_graph=True,
    )


def _parse_rdf_xml_graph(path: Path) -> Optional[SparqlResults]:
    """Parse an RDF/XML (.rdf) file into triples for CONSTRUCT/DESCRIBE comparison."""
    try:
        import pyoxigraph
    except ImportError:
        logger.error("pyoxigraph not available for RDF/XML parsing")
        return None

    try:
        store = pyoxigraph.Store()
        store.load(path.read_bytes(), "application/rdf+xml")
    except Exception as e:
        logger.error("RDF/XML parse error in %s: %s", path, e)
        return None

    return _store_to_graph_results(store)


def _parse_trig_graph(path: Path) -> Optional[SparqlResults]:
    """Parse a TriG (.trig) file into triples for CONSTRUCT comparison."""
    try:
        import pyoxigraph
    except ImportError:
        logger.error("pyoxigraph not available for TriG parsing")
        return None

    try:
        store = pyoxigraph.Store()
        store.load(path.read_bytes(), "application/trig")
    except Exception as e:
        logger.error("TriG parse error in %s: %s", path, e)
        return None

    return _store_to_graph_results(store)


def _store_to_graph_results(store) -> SparqlResults:
    """Convert a pyoxigraph Store's contents to SparqlResults for graph comparison."""
    import pyoxigraph

    _XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

    rows: List[Dict[str, SparqlBinding]] = []
    for quad in store:
        triple: Dict[str, SparqlBinding] = {}

        s = quad.subject
        if isinstance(s, pyoxigraph.NamedNode):
            triple["subject"] = SparqlBinding(type="uri", value=s.value)
        elif isinstance(s, pyoxigraph.BlankNode):
            triple["subject"] = SparqlBinding(type="bnode", value=s.value)

        p = quad.predicate
        triple["predicate"] = SparqlBinding(type="uri", value=p.value)

        o = quad.object
        if isinstance(o, pyoxigraph.NamedNode):
            triple["object"] = SparqlBinding(type="uri", value=o.value)
        elif isinstance(o, pyoxigraph.BlankNode):
            triple["object"] = SparqlBinding(type="bnode", value=o.value)
        elif isinstance(o, pyoxigraph.Literal):
            dt = str(o.datatype) if o.datatype else None
            if dt == _XSD_STRING:
                dt = None
            triple["object"] = SparqlBinding(
                type="literal", value=o.value,
                lang=o.language, datatype=dt,
            )

        rows.append(triple)

    return SparqlResults(
        variables=["subject", "predicate", "object"],
        rows=rows,
        is_graph=True,
    )
