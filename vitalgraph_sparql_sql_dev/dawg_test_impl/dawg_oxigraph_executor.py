"""
Execute SPARQL queries against an in-memory pyoxigraph store.

Loads .ttl test data into a pyoxigraph.Store, runs a SPARQL query,
and returns results in the same SparqlResults format used by the
.srx parser — enabling direct comparison.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import pyoxigraph

from .dawg_srx_parser import SparqlBinding, SparqlResults

logger = logging.getLogger(__name__)


def execute_query(
    sparql: str,
    data_file: Optional[Path] = None,
    named_graph_files: Optional[List[Path]] = None,
) -> SparqlResults:
    """Execute a SPARQL query against test data using pyoxigraph.

    Args:
        sparql: The SPARQL query string.
        data_file: Path to the default graph data (.ttl file). May be None.
        named_graph_files: Paths to named graph data files.

    Returns:
        SparqlResults with the query output.

    Raises:
        SparqlExecutionError: If the query fails to execute.
    """
    store = pyoxigraph.Store()

    # Load default graph data
    if data_file is not None and data_file.exists():
        mime = _mime_for_path(data_file)
        try:
            with open(data_file, "rb") as f:
                store.load(
                    f, mime,
                    base_iri=f"file://{data_file}",
                    to_graph=pyoxigraph.DefaultGraph(),
                )
        except Exception as e:
            raise SparqlExecutionError(f"Failed to load data {data_file}: {e}") from e

    # Load named graphs
    if named_graph_files:
        for ng_file in named_graph_files:
            if ng_file.exists():
                mime = _mime_for_path(ng_file)
                graph_name = pyoxigraph.NamedNode(f"file://{ng_file}")
                try:
                    with open(ng_file, "rb") as f:
                        store.load(f, mime, base_iri=f"file://{ng_file}", to_graph=graph_name)
                except Exception as e:
                    logger.warning("Failed to load named graph %s: %s", ng_file, e)

    # Execute the query
    try:
        result = store.query(sparql)
    except Exception as e:
        raise SparqlExecutionError(f"Query execution failed: {e}") from e

    return _convert_result(result)


def _convert_result(result) -> SparqlResults:
    """Convert a pyoxigraph query result to our SparqlResults format."""
    # Boolean result (ASK) — pyoxigraph returns QueryBoolean, not plain bool
    if isinstance(result, bool) or type(result).__name__ == "QueryBoolean":
        return SparqlResults(
            variables=[],
            rows=[],
            is_boolean=True,
            boolean_value=bool(result),
        )

    # SELECT results
    if hasattr(result, "variables"):
        variables = [str(v.value) for v in result.variables]
        rows: List[Dict[str, SparqlBinding]] = []

        for solution in result:
            row: Dict[str, SparqlBinding] = {}
            for i, var_name in enumerate(variables):
                val = solution[i]
                if val is None:
                    continue  # Unbound variable

                binding = _term_to_binding(val)
                if binding is not None:
                    row[var_name] = binding

            rows.append(row)

        return SparqlResults(variables=variables, rows=rows)

    # CONSTRUCT/DESCRIBE results (triples)
    triples: List[Dict[str, SparqlBinding]] = []
    try:
        for triple in result:
            row: Dict[str, SparqlBinding] = {}
            s_binding = _term_to_binding(triple.subject)
            p_binding = _term_to_binding(triple.predicate)
            o_binding = _term_to_binding(triple.object)
            if s_binding and p_binding and o_binding:
                row["subject"] = s_binding
                row["predicate"] = p_binding
                row["object"] = o_binding
                triples.append(row)
    except Exception as e:
        logger.warning("Error iterating CONSTRUCT results: %s", e)

    return SparqlResults(
        variables=["subject", "predicate", "object"],
        rows=triples,
        is_graph=True,
    )


def _term_to_binding(term) -> Optional[SparqlBinding]:
    """Convert a pyoxigraph term to a SparqlBinding."""
    type_name = type(term).__name__

    if type_name == "NamedNode":
        return SparqlBinding(type="uri", value=term.value)

    elif type_name == "Literal":
        datatype = str(term.datatype.value) if term.datatype else None
        lang = str(term.language) if term.language else None

        # pyoxigraph always sets a datatype; strip xsd:string as it's the default
        if datatype == "http://www.w3.org/2001/XMLSchema#string":
            datatype = None

        return SparqlBinding(
            type="literal",
            value=term.value,
            datatype=datatype,
            lang=lang,
        )

    elif type_name == "BlankNode":
        return SparqlBinding(type="bnode", value=term.value)

    else:
        logger.warning("Unknown term type: %s", type_name)
        return None


def _mime_for_path(path: Path) -> str:
    """Determine MIME type from file extension."""
    suffix = path.suffix.lower()
    return {
        ".ttl": "text/turtle",
        ".nt": "application/n-triples",
        ".nq": "application/n-quads",
        ".rdf": "application/rdf+xml",
        ".xml": "application/rdf+xml",
        ".trig": "application/trig",
    }.get(suffix, "text/turtle")


class SparqlExecutionError(Exception):
    """Raised when SPARQL query execution fails."""
    pass
