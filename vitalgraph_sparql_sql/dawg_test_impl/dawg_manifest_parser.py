"""
Parse W3C DAWG SPARQL 1.1 manifest.ttl files to discover test cases.

Uses pyoxigraph to parse the Turtle manifests and extract test metadata:
test name, type, query file, data file(s), expected result file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pyoxigraph

logger = logging.getLogger(__name__)

# RDF namespace prefixes used in DAWG manifests
MF = "http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#"
QT = "http://www.w3.org/2001/sw/DataAccess/tests/test-query#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"

# Test types we care about
QUERY_EVAL_TEST = f"{MF}QueryEvaluationTest"
NEGATIVE_SYNTAX_TEST = f"{MF}NegativeSyntaxTest11"
POSITIVE_SYNTAX_TEST = f"{MF}PositiveSyntaxTest11"


@dataclass
class DawgTestCase:
    """A single DAWG test case extracted from a manifest."""
    name: str
    test_uri: str
    test_type: str  # "QueryEvaluation", "NegativeSyntax", "PositiveSyntax"
    category: str  # e.g. "bind", "aggregates"
    query_file: Optional[Path] = None
    data_file: Optional[Path] = None
    named_graph_files: List[Path] = field(default_factory=list)
    result_file: Optional[Path] = None
    comment: Optional[str] = None


def parse_manifest(manifest_path: Path, category: Optional[str] = None) -> List[DawgTestCase]:
    """Parse a manifest.ttl file and return a list of DawgTestCase objects.

    Args:
        manifest_path: Path to the manifest.ttl file.
        category: Override category name. If None, inferred from directory name.

    Returns:
        List of DawgTestCase objects.
    """
    if not manifest_path.exists():
        logger.warning("Manifest not found: %s", manifest_path)
        return []

    if category is None:
        category = manifest_path.parent.name

    store = pyoxigraph.Store()
    base_iri = f"file://{manifest_path}"

    try:
        with open(manifest_path, "rb") as f:
            store.load(f, "text/turtle", base_iri=base_iri)
    except Exception as e:
        logger.error("Failed to parse manifest %s: %s", manifest_path, e)
        return []

    manifest_dir = manifest_path.parent
    tests: List[DawgTestCase] = []

    # Find all test entries (subjects with rdf:type matching our test types)
    type_map = {
        QUERY_EVAL_TEST: "QueryEvaluation",
        NEGATIVE_SYNTAX_TEST: "NegativeSyntax",
        POSITIVE_SYNTAX_TEST: "PositiveSyntax",
    }

    for rdf_type_uri, test_type_label in type_map.items():
        for quad in store.quads_for_pattern(
            None,
            pyoxigraph.NamedNode(f"{RDF}type"),
            pyoxigraph.NamedNode(rdf_type_uri),
            None,
        ):
            test_subject = quad.subject
            test_uri = test_subject.value if hasattr(test_subject, "value") else str(test_subject)

            # Extract mf:name
            name = _get_literal(store, test_subject, f"{MF}name") or test_uri.split("#")[-1]

            # Extract rdfs:comment
            comment = _get_literal(store, test_subject, f"{RDFS}comment")

            # Extract mf:action (may be a blank node with qt:query and qt:data)
            action_node = _get_object(store, test_subject, f"{MF}action")
            query_file = None
            data_file = None
            named_graph_files = []

            if action_node is not None:
                if isinstance(action_node, pyoxigraph.BlankNode):
                    # Action is a blank node → extract qt:query and qt:data
                    query_obj = _get_object(store, action_node, f"{QT}query")
                    if query_obj and hasattr(query_obj, "value"):
                        query_file = _resolve_path(query_obj.value, manifest_dir, base_iri)

                    data_obj = _get_object(store, action_node, f"{QT}data")
                    if data_obj and hasattr(data_obj, "value"):
                        data_file = _resolve_path(data_obj.value, manifest_dir, base_iri)

                    # Named graphs
                    for gq in store.quads_for_pattern(
                        action_node,
                        pyoxigraph.NamedNode(f"{QT}graphData"),
                        None,
                        None,
                    ):
                        if hasattr(gq.object, "value"):
                            ng = _resolve_path(gq.object.value, manifest_dir, base_iri)
                            if ng:
                                named_graph_files.append(ng)

                elif hasattr(action_node, "value"):
                    # Action is a direct URI → it's the query file (syntax tests)
                    query_file = _resolve_path(action_node.value, manifest_dir, base_iri)

            # Extract mf:result
            result_file = None
            result_obj = _get_object(store, test_subject, f"{MF}result")
            if result_obj and hasattr(result_obj, "value"):
                result_file = _resolve_path(result_obj.value, manifest_dir, base_iri)

            tests.append(DawgTestCase(
                name=name,
                test_uri=test_uri,
                test_type=test_type_label,
                category=category,
                query_file=query_file,
                data_file=data_file,
                named_graph_files=named_graph_files,
                result_file=result_file,
                comment=comment,
            ))

    # Also discover tests from mf:entries list (ARQ-style manifests without rdf:type)
    # Find entries that have mf:name but weren't already found above
    found_uris = {t.test_uri for t in tests}
    for quad in store.quads_for_pattern(
        None, pyoxigraph.NamedNode(f"{MF}name"), None, None,
    ):
        subject = quad.subject
        subject_id = subject.value if hasattr(subject, "value") else str(subject)
        if subject_id in found_uris:
            continue  # Already discovered via rdf:type

        name = quad.object.value if hasattr(quad.object, "value") else str(quad.object)

        # Extract action (query + data)
        action_node = _get_object(store, subject, f"{MF}action")
        query_file = None
        data_file = None
        named_graph_files = []

        if action_node is not None:
            if isinstance(action_node, pyoxigraph.BlankNode):
                query_obj = _get_object(store, action_node, f"{QT}query")
                if query_obj and hasattr(query_obj, "value"):
                    query_file = _resolve_path(query_obj.value, manifest_dir, base_iri)

                data_obj = _get_object(store, action_node, f"{QT}data")
                if data_obj and hasattr(data_obj, "value"):
                    data_file = _resolve_path(data_obj.value, manifest_dir, base_iri)

                for gq in store.quads_for_pattern(
                    action_node,
                    pyoxigraph.NamedNode(f"{QT}graphData"),
                    None, None,
                ):
                    if hasattr(gq.object, "value"):
                        ng = _resolve_path(gq.object.value, manifest_dir, base_iri)
                        if ng:
                            named_graph_files.append(ng)
            elif hasattr(action_node, "value"):
                query_file = _resolve_path(action_node.value, manifest_dir, base_iri)

        result_file = None
        result_obj = _get_object(store, subject, f"{MF}result")
        if result_obj and hasattr(result_obj, "value"):
            result_file = _resolve_path(result_obj.value, manifest_dir, base_iri)

        comment = _get_literal(store, subject, f"{RDFS}comment")

        tests.append(DawgTestCase(
            name=name,
            test_uri=subject_id,
            test_type="QueryEvaluation",  # Assume query eval for ARQ entries
            category=category,
            query_file=query_file,
            data_file=data_file,
            named_graph_files=named_graph_files,
            result_file=result_file,
            comment=comment,
        ))

    # Sort by name for deterministic ordering
    tests.sort(key=lambda t: t.name)
    logger.info("Parsed %d tests from %s (category: %s)", len(tests), manifest_path.name, category)
    return tests


def discover_categories(dawg_root: Path) -> List[str]:
    """Discover available test categories under the DAWG sparql11 directory.

    Returns category names (directory names that contain a manifest.ttl).
    """
    sparql11_dir = dawg_root / "sparql" / "sparql11"
    if not sparql11_dir.exists():
        logger.warning("DAWG sparql11 directory not found: %s", sparql11_dir)
        return []

    categories = []
    for child in sorted(sparql11_dir.iterdir()):
        if child.is_dir() and (child / "manifest.ttl").exists():
            categories.append(child.name)
    return categories


def get_manifest_path(dawg_root: Path, category: str) -> Path:
    """Return the manifest.ttl path for a given category."""
    return dawg_root / "sparql" / "sparql11" / category / "manifest.ttl"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_object(store: pyoxigraph.Store, subject, predicate_uri: str):
    """Get the first object for a given subject+predicate, or None."""
    for quad in store.quads_for_pattern(
        subject,
        pyoxigraph.NamedNode(predicate_uri),
        None,
        None,
    ):
        return quad.object
    return None


def _get_literal(store: pyoxigraph.Store, subject, predicate_uri: str) -> Optional[str]:
    """Get a literal string value for a given subject+predicate, or None."""
    obj = _get_object(store, subject, predicate_uri)
    if obj is not None and hasattr(obj, "value"):
        return obj.value
    return None


def _resolve_path(uri: str, manifest_dir: Path, base_iri: str) -> Optional[Path]:
    """Resolve a URI from a manifest to a local file path."""
    if uri.startswith("file://"):
        # Strip file:// prefix, resolve relative to manifest dir
        local = uri[len("file://"):]
        # The URI may be absolute or contain the manifest dir path
        p = Path(local)
        if p.exists():
            return p
        # Try relative to manifest dir
        rel = uri.replace(base_iri.rsplit("/", 1)[0] + "/", "")
        return manifest_dir / rel

    if uri.startswith("http://") or uri.startswith("https://"):
        # Remote URI — shouldn't happen for test data but handle gracefully
        return None

    # Relative path
    return manifest_dir / uri
