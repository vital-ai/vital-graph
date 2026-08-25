"""
Parse SPARQL Results XML (.srx), JSON (.srj), CSV (.csv) and TSV (.tsv) files.

Extracts variable names and result bindings into a normalized format
that can be compared across engines.

ON CSV, AND WHY IT IS NOT JUST ANOTHER FORMAT. SPARQL 1.1's CSV serialisation
is LOSSY BY SPECIFICATION: it writes the lexical value and nothing else, so
datatypes, language tags and the URI/literal/bnode distinction are all gone.
Measured, from the DAWG corpus itself — the same result set, both ways:

    csvtsv01.csv    http://example.org/s1,http://example.org/p1,foo
    csvtsv01.tsv    <http://example.org/s1>\t<http://example.org/p1>\t"foo"

So a CSV expectation can only support a comparison on VALUES. Parsing one and
handing it to the ordinary comparator would fail every row on a type mismatch
that the file never claimed to encode — failures that say nothing whatever about
the engine under test. `SparqlResults.lossy_types` marks that, and the comparator
degrades its check to match, rather than the parser inventing types to make the
comparison look strict. TSV keeps full term syntax and needs no such thing.
"""

from __future__ import annotations

import csv as _csv
import io
import json
import logging
import re
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
    # True when the source format could not carry term types — CSV only. The
    # comparator reads this and compares values alone. It is a property of the
    # FILE, not a request by the caller, which is why it lives here.
    lossy_types: bool = False


class ResultParseError(Exception):
    """A result file we should have been able to read could not be read.

    Raised rather than returned, because returning was the bug. Every caller
    turned a None into `pytest.skip`, a skip counts as green, and so an
    unreadable expectation looked exactly like a passing test. Three separate
    coverage holes were found that way -- `csv-tsv-res`/`json-res` skipping for
    want of a parser, `XFAIL_TESTS_V2` deferring `test_sql_v2`, and six
    `sparql10/dataset` result files that had been unparseable for as long as
    the category had been wired (issues/130). The type exists so that failure
    to read an expectation is a test failure, not a silent absence.
    """


class UnsupportedResultFormat(ResultParseError):
    """The harness has no parser for this file's format at all.

    A capability gap rather than a defect, so skipping on it is defensible --
    but it is a distinct type so that each call site has to say so on purpose,
    instead of inheriting the decision from a bare None.
    """


_PARSERS = {
    ".srx": lambda p: _parse_srx(p),
    ".srj": lambda p: _parse_srj(p),
    ".ttl": lambda p: _parse_ttl_graph(p),
    ".rdf": lambda p: _parse_rdf_xml_graph(p),
    ".trig": lambda p: _parse_trig_graph(p),
    ".csv": lambda p: _parse_csv(p),
    ".tsv": lambda p: _parse_tsv(p),
}


def parse_result_file(path: Path) -> SparqlResults:
    """Parse a DAWG expected-result file.

    Raises:
        UnsupportedResultFormat: no parser exists for this extension.
        ResultParseError: the file is missing, or a parser was found and could
            not read it. Callers must NOT turn this into a skip.
    """
    if not path.exists():
        raise ResultParseError(f"Result file not found: {path}")

    suffix = path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise UnsupportedResultFormat(
            f"No parser for {suffix!r} result files: {path}")

    result = parser(path)
    if result is None:
        # The individual parsers still signal failure with None and log the
        # cause. Converting it here means no future parser can reintroduce the
        # silent-skip behaviour just by following the local convention.
        raise ResultParseError(
            f"Could not parse {suffix!r} result file (see log for cause): {path}")
    return result


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


_RS = "http://www.w3.org/2001/sw/DataAccess/tests/result-set#"


def _rs_term(store, node) -> Optional["SparqlBinding"]:
    """One `rs:value` object as a binding."""
    import pyoxigraph
    if isinstance(node, pyoxigraph.NamedNode):
        return SparqlBinding(type="uri", value=node.value)
    if isinstance(node, pyoxigraph.BlankNode):
        return SparqlBinding(type="bnode", value=node.value)
    if isinstance(node, pyoxigraph.Literal):
        dt = node.datatype.value if node.datatype else None
        if dt == "http://www.w3.org/2001/XMLSchema#string":
            dt = None
        return SparqlBinding(type="literal", value=node.value,
                             datatype=dt, lang=node.language)
    return None


def _parse_rs_result_set(store) -> Optional[SparqlResults]:
    """Parse the DAWG RDF result-set vocabulary into bindings.

    `sparql10` predates SRX and encodes expected results as RDF:

        [] rdf:type rs:ResultSet ;
           rs:resultVariable "p", "v" ;
           rs:solution [ rs:binding [ rs:value "abc"@en-gb ; rs:variable "v" ] ] .

    Without this, a `.ttl` result was read as a GRAPH and compared as
    CONSTRUCT triples, so every case reported a triple-count mismatch against
    its own expectation — `expected 10, got 1` for `LangMatches-1`, 10 being
    the triples in the file rather than anything about the query
    (`issues/125`).
    """
    import pyoxigraph

    rs_set = list(store.quads_for_pattern(
        None, pyoxigraph.NamedNode(f"{_RS}resultVariable"), None, None))
    solutions = list(store.quads_for_pattern(
        None, pyoxigraph.NamedNode(f"{_RS}solution"), None, None))
    booleans = list(store.quads_for_pattern(
        None, pyoxigraph.NamedNode(f"{_RS}boolean"), None, None))

    if booleans:
        v = booleans[0].object
        return SparqlResults(variables=[], rows=[], is_boolean=True,
                             boolean_value=str(v.value).lower() == "true")
    if not rs_set and not solutions:
        return None                      # not a result set; treat as a graph

    variables = [q.object.value for q in rs_set]

    rows: List[Dict[str, SparqlBinding]] = []
    for sol in solutions:
        row: Dict[str, SparqlBinding] = {}
        for b in store.quads_for_pattern(
                sol.object, pyoxigraph.NamedNode(f"{_RS}binding"), None, None):
            name = value = None
            for q in store.quads_for_pattern(b.object, None, None, None):
                if q.predicate.value == f"{_RS}variable":
                    name = q.object.value
                elif q.predicate.value == f"{_RS}value":
                    value = _rs_term(store, q.object)
            if name is not None and value is not None:
                row[name] = value
        rows.append(row)

    # `rs:resultVariable` is unordered in RDF, so a variable bound in a
    # solution but absent from the header would silently vanish.
    for row in rows:
        for k in row:
            if k not in variables:
                variables.append(k)
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
        store.load(path.read_bytes(), "text/turtle",
                   base_iri=f"file://{path}")
    except Exception as e:
        logger.error("TTL parse error in %s: %s", path, e)
        return None

    # A .ttl result file is EITHER a CONSTRUCT graph or the DAWG RDF
    # result-set vocabulary. Reading the second as the first compares
    # bindings against triples and can only fail.
    as_result_set = _parse_rs_result_set(store)
    if as_result_set is not None:
        return as_result_set

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
        store.load(path.read_bytes(), "application/rdf+xml",
                   base_iri=f"file://{path}")
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
        store.load(path.read_bytes(), "application/trig",
                   base_iri=f"file://{path}")
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


# ---------------------------------------------------------------------------
# CSV / TSV  (SPARQL 1.1 Query Results CSV and TSV Formats)
# ---------------------------------------------------------------------------

# A TSV term, in the N-Triples-ish syntax the TSV format uses. Numerics appear
# bare (`4`, `5.5`, `1.0e6`) and carry an implied xsd type; everything else is
# explicitly delimited.
_TSV_URI = re.compile(r"^<(.*)>$", re.S)
_TSV_BNODE = re.compile(r"^_:(.*)$", re.S)
_TSV_LITERAL = re.compile(
    r'^"(?P<v>.*)"'
    r'(?:@(?P<lang>[A-Za-z][A-Za-z0-9-]*)|\^\^<(?P<dt>[^>]*)>)?$',
    re.S,
)
_TSV_INTEGER = re.compile(r"^[+-]?\d+$")
_TSV_DECIMAL = re.compile(r"^[+-]?\d*\.\d+$")
_TSV_DOUBLE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)[eE][+-]?\d+$")

_XSD = "http://www.w3.org/2001/XMLSchema#"

# Escapes the TSV format defines inside quoted literals.
_TSV_ESCAPES = {
    "t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f",
    '"': '"', "'": "'", "\\": "\\",
}


def _unescape(text: str) -> str:
    """Resolve backslash escapes in a TSV literal body."""
    if "\\" not in text:
        return text
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append(_TSV_ESCAPES.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_tsv_term(cell: str) -> Optional[SparqlBinding]:
    """Parse one TSV cell into a binding, or None for an unbound value.

    An EMPTY cell means unbound, which is distinct from an empty literal `""`.
    Collapsing the two would silently turn OPTIONAL's absence into a value.
    """
    cell = cell.strip()
    if not cell:
        return None

    m = _TSV_URI.match(cell)
    if m:
        return SparqlBinding(type="uri", value=m.group(1))

    m = _TSV_BNODE.match(cell)
    if m:
        return SparqlBinding(type="bnode", value=m.group(1))

    m = _TSV_LITERAL.match(cell)
    if m:
        return SparqlBinding(
            type="literal",
            value=_unescape(m.group("v")),
            datatype=m.group("dt"),
            lang=m.group("lang"),
        )

    # Bare numerics carry an implied datatype. Checked longest-form first:
    # `1.0e6` also matches nothing else, but `.5` would match decimal and
    # double both if the order were reversed.
    if _TSV_DOUBLE.match(cell):
        return SparqlBinding(type="literal", value=cell, datatype=f"{_XSD}double")
    if _TSV_DECIMAL.match(cell):
        return SparqlBinding(type="literal", value=cell, datatype=f"{_XSD}decimal")
    if _TSV_INTEGER.match(cell):
        return SparqlBinding(type="literal", value=cell, datatype=f"{_XSD}integer")

    logger.warning("Unparseable TSV term %r — treating as a plain literal", cell)
    return SparqlBinding(type="literal", value=cell)


def _parse_tsv(path: Path) -> Optional[SparqlResults]:
    """Parse a SPARQL Results TSV file.

    Not lossy: the TSV format carries full term syntax, so this returns bindings
    the ordinary comparator can check strictly.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("Cannot read %s: %s", path, e)
        return None

    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        logger.error("Empty TSV result file: %s", path)
        return None

    # The header names variables WITH the leading `?`.
    variables = [v.strip().lstrip("?") for v in lines[0].split("\t")]

    rows: List[Dict[str, SparqlBinding]] = []
    for line in lines[1:]:
        cells = line.split("\t")
        row: Dict[str, SparqlBinding] = {}
        for var, cell in zip(variables, cells):
            term = _parse_tsv_term(cell)
            if term is not None:
                row[var] = term
        rows.append(row)

    return SparqlResults(variables=variables, rows=rows)


def _parse_csv(path: Path) -> Optional[SparqlResults]:
    """Parse a SPARQL Results CSV file.

    LOSSY — see the module docstring. Every value comes back as a literal
    because the format does not record what it was, and `lossy_types` tells the
    comparator to compare on value alone. The one exception the format does keep
    is `_:label` for a blank node, which is preserved so bnode isomorphism still
    has something to work with.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("Cannot read %s: %s", path, e)
        return None

    reader = _csv.reader(io.StringIO(text))
    try:
        records = list(reader)
    except _csv.Error as e:
        logger.error("CSV parse error in %s: %s", path, e)
        return None

    while records and not any(c.strip() for c in records[-1]):
        records.pop()
    if not records:
        logger.error("Empty CSV result file: %s", path)
        return None

    variables = [v.strip() for v in records[0]]

    rows: List[Dict[str, SparqlBinding]] = []
    for record in records[1:]:
        row: Dict[str, SparqlBinding] = {}
        for var, cell in zip(variables, record):
            if cell == "":
                continue  # unbound; empty literals are indistinguishable here
            if cell.startswith("_:"):
                row[var] = SparqlBinding(type="bnode", value=cell[2:])
            else:
                row[var] = SparqlBinding(type="literal", value=cell)
        rows.append(row)

    return SparqlResults(variables=variables, rows=rows, lossy_types=True)
