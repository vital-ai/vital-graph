"""
DAWG SPARQL 1.1 Update test support.

Parses UpdateEvaluationTest manifests and runs update operations against the
V2 SQL pipeline, comparing pre/post graph state.

Update tests differ from query tests:
  - Action has ut:request (.ru file) instead of qt:query
  - Pre-state: ut:data (default graph) + ut:graphData (named graphs)
  - Post-state: mf:result with ut:data + ut:graphData
  - Comparison is graph state equality, not result set matching
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import pyoxigraph

from .dawg_report import TestResult

logger = logging.getLogger(__name__)

# RDF namespace prefixes used in update manifests
MF = "http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#"
UT = "http://www.w3.org/2009/sparql/tests/test-update#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"

UPDATE_EVAL_TEST = f"{MF}UpdateEvaluationTest"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class NamedGraphSpec:
    """A named graph in an update test (pre or post state)."""
    graph_uri: str
    ttl_file: Path


@dataclass
class DawgUpdateTestCase:
    """A single DAWG UpdateEvaluationTest extracted from a manifest."""
    name: str
    test_uri: str
    category: str
    comment: Optional[str] = None

    # Action (pre-state + request)
    request_file: Optional[Path] = None  # .ru file
    pre_default_data: Optional[Path] = None  # default graph TTL
    pre_named_graphs: List[NamedGraphSpec] = field(default_factory=list)

    # Result (expected post-state)
    post_default_data: Optional[Path] = None  # expected default graph TTL
    post_named_graphs: List[NamedGraphSpec] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Manifest parser for UpdateEvaluationTest
# ---------------------------------------------------------------------------

def parse_update_manifest(
    manifest_path: Path,
    category: Optional[str] = None,
) -> List[DawgUpdateTestCase]:
    """Parse an update manifest.ttl and return update test cases."""
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
    tests: List[DawgUpdateTestCase] = []

    for quad in store.quads_for_pattern(
        None,
        pyoxigraph.NamedNode(f"{RDF}type"),
        pyoxigraph.NamedNode(UPDATE_EVAL_TEST),
        None,
    ):
        subject = quad.subject
        test_uri = subject.value if hasattr(subject, "value") else str(subject)

        name = _get_literal(store, subject, f"{MF}name") or test_uri.split("#")[-1]
        comment = _get_literal(store, subject, f"{RDFS}comment")

        # --- Parse action (pre-state + request) ---
        action_node = _get_object(store, subject, f"{MF}action")
        request_file = None
        pre_default = None
        pre_named: List[NamedGraphSpec] = []

        if action_node is not None:
            # ut:request → .ru file
            req_obj = _get_object(store, action_node, f"{UT}request")
            if req_obj and hasattr(req_obj, "value"):
                request_file = _resolve_path(req_obj.value, manifest_dir, base_iri)

            # ut:data → pre-state default graph
            data_obj = _get_object(store, action_node, f"{UT}data")
            if data_obj and hasattr(data_obj, "value"):
                pre_default = _resolve_path(data_obj.value, manifest_dir, base_iri)

            # ut:graphData → pre-state named graphs
            pre_named = _parse_graph_data(store, action_node, manifest_dir, base_iri)

        # --- Parse result (expected post-state) ---
        result_node = _get_object(store, subject, f"{MF}result")
        post_default = None
        post_named: List[NamedGraphSpec] = []

        if result_node is not None:
            # ut:data → expected default graph
            rdata_obj = _get_object(store, result_node, f"{UT}data")
            if rdata_obj and hasattr(rdata_obj, "value"):
                post_default = _resolve_path(rdata_obj.value, manifest_dir, base_iri)

            # ut:graphData → expected named graphs
            post_named = _parse_graph_data(store, result_node, manifest_dir, base_iri)

        tests.append(DawgUpdateTestCase(
            name=name,
            test_uri=test_uri,
            category=category,
            comment=comment,
            request_file=request_file,
            pre_default_data=pre_default,
            pre_named_graphs=pre_named,
            post_default_data=post_default,
            post_named_graphs=post_named,
        ))

    tests.sort(key=lambda t: t.name)
    logger.info("Parsed %d update tests from %s", len(tests), manifest_path.name)
    return tests


def _parse_graph_data(
    store: pyoxigraph.Store,
    parent_node,
    manifest_dir: Path,
    base_iri: str,
) -> List[NamedGraphSpec]:
    """Parse ut:graphData entries from a parent node.

    Each ut:graphData points to a blank node with:
      - ut:graph → TTL file path
      - rdfs:label → graph URI
    """
    specs: List[NamedGraphSpec] = []
    for gd_quad in store.quads_for_pattern(
        parent_node,
        pyoxigraph.NamedNode(f"{UT}graphData"),
        None,
        None,
    ):
        gd_node = gd_quad.object

        # ut:graph → TTL file
        graph_obj = _get_object(store, gd_node, f"{UT}graph")
        if not graph_obj or not hasattr(graph_obj, "value"):
            continue
        ttl_path = _resolve_path(graph_obj.value, manifest_dir, base_iri)
        if ttl_path is None:
            continue

        # rdfs:label → graph URI
        graph_uri = _get_literal(store, gd_node, f"{RDFS}label")
        if not graph_uri:
            # Fall back to file URI
            graph_uri = graph_obj.value

        specs.append(NamedGraphSpec(graph_uri=graph_uri, ttl_file=ttl_path))
    return specs


# ---------------------------------------------------------------------------
# Graph state comparison
# ---------------------------------------------------------------------------

# A triple as (subject_text, predicate_text, object_text)
Triple = Tuple[str, str, str]
# Graph state: {graph_uri: frozenset of triples}
GraphState = Dict[str, FrozenSet[Triple]]


def load_expected_state(test: DawgUpdateTestCase) -> GraphState:
    """Load the expected post-state from TTL files specified in the test."""
    state: Dict[str, Set[Triple]] = {}

    # Default graph
    if test.post_default_data and test.post_default_data.exists():
        triples = _parse_ttl_to_triples(test.post_default_data)
        state["DEFAULT"] = set(triples)

    # Named graphs
    for ng in test.post_named_graphs:
        if ng.ttl_file.exists():
            triples = _parse_ttl_to_triples(ng.ttl_file)
            state[ng.graph_uri] = set(triples)

    return {k: frozenset(v) for k, v in state.items()}


async def dump_actual_state(
    conn,
    space_id: str,
    expected_graphs: GraphState,
) -> GraphState:
    """Dump the actual graph state from PostgreSQL for comparison.

    Only dumps graphs that appear in the expected state to keep the
    comparison focused.
    """
    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"

    from .dawg_data_loader import DEFAULT_GRAPH_URI

    state: Dict[str, Set[Triple]] = {}

    for graph_key in expected_graphs:
        if graph_key == "DEFAULT":
            graph_uri = DEFAULT_GRAPH_URI
        else:
            graph_uri = graph_key

        sql = f"""
            SELECT
                s.term_text AS s_text, s.term_type AS s_type,
                p.term_text AS p_text,
                o.term_text AS o_text, o.term_type AS o_type,
                o.lang AS o_lang
            FROM {quad_table} q
            JOIN {term_table} s ON q.subject_uuid = s.term_uuid
            JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
            JOIN {term_table} o ON q.object_uuid = o.term_uuid
            JOIN {term_table} g ON q.context_uuid = g.term_uuid
            WHERE g.term_text = $1
        """
        rows = await conn.fetch(sql, graph_uri)

        triples: Set[Triple] = set()
        for row in rows:
            s = _format_term(row["s_text"], row["s_type"])
            p = row["p_text"]
            o = _format_term(row["o_text"], row["o_type"], row.get("o_lang"))
            triples.add((s, p, o))

        state[graph_key] = frozenset(triples)

    return state


def compare_graph_states(
    actual: GraphState,
    expected: GraphState,
) -> Tuple[bool, str]:
    """Compare actual and expected graph states.

    Returns (match, message).
    """
    all_graphs = set(expected.keys()) | set(actual.keys())
    diffs: List[str] = []

    for g in sorted(all_graphs):
        exp = expected.get(g, frozenset())
        act = actual.get(g, frozenset())

        if exp == act:
            continue

        missing = exp - act
        extra = act - exp

        label = f"graph={g}"
        if missing:
            diffs.append(f"{label}: missing {len(missing)} triples")
            for t in sorted(missing)[:3]:
                diffs.append(f"  - {t}")
        if extra:
            diffs.append(f"{label}: {len(extra)} unexpected triples")
            for t in sorted(extra)[:3]:
                diffs.append(f"  + {t}")

    if not diffs:
        return True, ""
    return False, "; ".join(diffs)


# ---------------------------------------------------------------------------
# Test runner for a single update test
# ---------------------------------------------------------------------------

async def run_single_update_test_v2(
    test: DawgUpdateTestCase,
    db_conn,
) -> TestResult:
    """Run a single DAWG UpdateEvaluationTest against the V2 pipeline."""
    from .dawg_data_loader import load_ttl_into_space, DEFAULT_GRAPH_URI
    from .dawg_space_manager import truncate_space, SPACE_ID
    from .dawg_sql_v2_executor import execute_update_via_v2_pipeline, SqlV2PipelineError

    # Validate request file
    if test.request_file is None or not test.request_file.exists():
        return TestResult(
            name=test.name, category=test.category, status="SKIP",
            error_message="Request (.ru) file missing",
        )

    # Read SPARQL Update
    try:
        sparql = test.request_file.read_text(encoding="utf-8")
    except Exception as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            error_message=f"Cannot read request file: {e}",
        )

    # Step 1: Load pre-state
    await truncate_space(db_conn, SPACE_ID)
    if test.pre_default_data and test.pre_default_data.exists():
        await load_ttl_into_space(db_conn, test.pre_default_data, SPACE_ID,
                                  graph_uri=DEFAULT_GRAPH_URI)
    for ng in test.pre_named_graphs:
        if ng.ttl_file.exists():
            await load_ttl_into_space(db_conn, ng.ttl_file, SPACE_ID,
                                      graph_uri=ng.graph_uri)

    # Step 2: Execute update
    t0 = time.time()
    try:
        await execute_update_via_v2_pipeline(sparql, space_id=SPACE_ID, conn=db_conn,
                                             default_graph=DEFAULT_GRAPH_URI)
    except SqlV2PipelineError as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            time_ms=(time.time() - t0) * 1000,
            error_message=f"V2 update error: {e}",
        )
    except Exception as e:
        return TestResult(
            name=test.name, category=test.category, status="ERROR",
            time_ms=(time.time() - t0) * 1000,
            error_message=f"Unexpected: {e}",
        )
    elapsed_ms = (time.time() - t0) * 1000

    # Step 3: Compare post-state
    expected_state = load_expected_state(test)
    actual_state = await dump_actual_state(db_conn, SPACE_ID, expected_state)

    match, message = compare_graph_states(actual_state, expected_state)
    return TestResult(
        name=test.name, category=test.category,
        status="PASS" if match else "FAIL",
        time_ms=elapsed_ms,
        error_message="" if match else message,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_ttl_to_triples(ttl_file: Path) -> List[Triple]:
    """Parse a TTL file into a list of (s, p, o) text triples."""
    triples: List[Triple] = []
    try:
        with open(ttl_file, "rb") as f:
            for t in pyoxigraph.parse(f, "text/turtle",
                                       base_iri=f"file://{ttl_file}"):
                s = _oxigraph_node_text(t.subject)
                p = t.predicate.value
                o = _oxigraph_node_text(t.object)
                triples.append((s, p, o))
    except Exception as e:
        logger.error("Failed to parse %s: %s", ttl_file, e)
    return triples


def _oxigraph_node_text(node) -> str:
    """Convert a pyoxigraph node to a canonical text representation."""
    cls = type(node).__name__
    if cls == "Literal":
        # Include lang tag for comparison
        if node.language:
            return f'"{node.value}"@{node.language}'
        return node.value
    elif cls == "BlankNode":
        return f"_:{node.value}"
    else:
        return node.value


def _format_term(text: str, ttype: str, lang: Optional[str] = None) -> str:
    """Format a term from DB for comparison (matching _oxigraph_node_text)."""
    if ttype == "L" and lang:
        return f'"{text}"@{lang}'
    return text


def _get_object(store: pyoxigraph.Store, subject, predicate_uri: str):
    """Get the first object for a given subject+predicate."""
    for quad in store.quads_for_pattern(
        subject,
        pyoxigraph.NamedNode(predicate_uri),
        None,
        None,
    ):
        return quad.object
    return None


def _get_literal(store: pyoxigraph.Store, subject, predicate_uri: str) -> Optional[str]:
    """Get a literal string value for a given subject+predicate."""
    obj = _get_object(store, subject, predicate_uri)
    if obj is not None and hasattr(obj, "value"):
        return obj.value
    return None


def _resolve_path(uri: str, manifest_dir: Path, base_iri: str) -> Optional[Path]:
    """Resolve a URI from a manifest to a local file path."""
    if uri.startswith("file://"):
        local = uri[len("file://"):]
        p = Path(local)
        if p.exists():
            return p
        rel = uri.replace(base_iri.rsplit("/", 1)[0] + "/", "")
        return manifest_dir / rel

    if uri.startswith("http://") or uri.startswith("https://"):
        return None

    return manifest_dir / uri
