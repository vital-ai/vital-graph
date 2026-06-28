"""
Execute SPARQL queries through our SQL pipeline (SparqlOrchestrator).

Converts the QueryResult from the orchestrator into the same SparqlResults
format used by the .srx parser and pyoxigraph executor — enabling direct
comparison across all engines.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dawg_srx_parser import SparqlBinding, SparqlResults

logger = logging.getLogger(__name__)

# XSD string type — our pipeline strips this, same as pyoxigraph
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


async def execute_query_via_pipeline(
    sparql: str,
    orchestrator,
) -> SparqlResults:
    """Execute a SPARQL query through the SQL pipeline.

    Args:
        sparql: The SPARQL query string.
        orchestrator: A SparqlOrchestrator instance configured for the dawg_test space.

    Returns:
        SparqlResults with the query output.

    Raises:
        SqlPipelineError: If the pipeline fails.
    """
    result = await orchestrator.execute(sparql, include_sql=True)

    if not result.ok:
        raise SqlPipelineError(f"Pipeline error: {result.error}")

    # ASK queries
    if result.query_type == "ASK":
        return SparqlResults(
            variables=[],
            rows=[],
            is_boolean=True,
            boolean_value=result.boolean,
        )

    # CONSTRUCT/DESCRIBE — not yet supported for comparison
    if result.query_type in ("CONSTRUCT", "DESCRIBE"):
        logger.debug("CONSTRUCT/DESCRIBE not yet supported for comparison")
        return SparqlResults(variables=[], rows=[])

    # SELECT queries — convert rows to SparqlBinding format using var_map
    # The var_map (sql_col -> sparql_name) provides the authoritative mapping
    # from opaque SQL column names (v0, v1, ...) back to original SPARQL names.
    var_map = result.var_map or {}
    sparql_vars = result.sparql_vars or []

    if var_map:
        # New path: use var_map for correct SPARQL↔SQL column mapping
        # Build inverse: sparql_name → sql_col
        inv_map = {sparql: sql for sql, sparql in var_map.items()}
        variables = sparql_vars
        rows: List[Dict[str, SparqlBinding]] = []

        for row in result.rows:
            bindings: Dict[str, SparqlBinding] = {}
            for sparql_name in variables:
                sql_col = inv_map.get(sparql_name)
                if sql_col is None:
                    continue
                val = row.get(sql_col)
                if val is None:
                    continue  # Unbound

                binding = _infer_binding(sql_col, val, row)
                if binding is not None:
                    bindings[sparql_name] = binding

            rows.append(bindings)

        return SparqlResults(variables=variables, rows=rows)

    # Fallback: no var_map (ASK/DESCRIBE/UPDATE or legacy path)
    all_columns = result.columns or []
    variables = [c for c in all_columns if not (
        c.endswith("__type") or c.endswith("__uuid") or c.endswith("__lang")
        or c.endswith("__datatype") or c.endswith("__num") or c == "_dummy"
    )]
    rows: List[Dict[str, SparqlBinding]] = []

    for row in result.rows:
        bindings: Dict[str, SparqlBinding] = {}
        for var_name in variables:
            val = row.get(var_name)
            if val is None:
                continue  # Unbound

            binding = _infer_binding(var_name, val, row)
            if binding is not None:
                bindings[var_name] = binding

        rows.append(bindings)

    return SparqlResults(variables=variables, rows=rows)


def _infer_binding(var_name: str, value: Any, row: Dict[str, Any]) -> Optional[SparqlBinding]:
    """Infer a SparqlBinding from a pipeline result value.

    The SQL pipeline returns term_text as the main value. Additional columns
    may contain type/lang/datatype information depending on the query structure.
    We use heuristics to determine the RDF term type.
    """
    if value is None:
        return None

    # Python bool str() gives 'True'/'False'; XSD requires 'true'/'false'
    if isinstance(value, bool):
        val_str = "true" if value else "false"
    else:
        val_str = str(value)

    # Check for companion columns that the pipeline might produce
    # (e.g., var_name__type, var_name__lang, var_name__datatype)
    # PostgreSQL lowercases unquoted identifiers, so also try lowercase
    term_type = row.get(f"{var_name}__type") or row.get(f"{var_name.lower()}__type")
    term_lang = row.get(f"{var_name}__lang") or row.get(f"{var_name.lower()}__lang")
    term_datatype = row.get(f"{var_name}__datatype") or row.get(f"{var_name.lower()}__datatype")

    # If we have explicit type information from the term table
    if term_type == "U":
        return SparqlBinding(type="uri", value=val_str)
    elif term_type == "B":
        return SparqlBinding(type="bnode", value=val_str)
    elif term_type == "L":
        lang = term_lang if term_lang else None
        datatype = term_datatype if term_datatype else None
        # Strip xsd:string — RDF 1.1 treats plain literals and xsd:string as identical
        if datatype == XSD_STRING:
            datatype = None
        # Lang-tagged literals get rdf:langString as their datatype (pyoxigraph convention)
        if lang:
            datatype = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
        return SparqlBinding(type="literal", value=val_str, lang=lang,
                             datatype=datatype)

    # No explicit type — infer from the Python value type
    # (common for computed/aggregate values like COUNT, SUM, AVG, etc.)
    if isinstance(value, bool):
        return SparqlBinding(
            type="literal", value="true" if value else "false",
            datatype="http://www.w3.org/2001/XMLSchema#boolean",
        )
    if isinstance(value, int):
        return SparqlBinding(
            type="literal", value=str(value),
            datatype="http://www.w3.org/2001/XMLSchema#integer",
        )
    if isinstance(value, float):
        # Format: remove trailing zeros but keep at least one decimal
        formatted = f"{value:.15g}"
        return SparqlBinding(
            type="literal", value=formatted,
            datatype="http://www.w3.org/2001/XMLSchema#decimal",
        )
    # Python Decimal from PostgreSQL NUMERIC (SUM, AVG, CAST, arithmetic)
    import decimal
    if isinstance(value, decimal.Decimal):
        normalized = value.normalize()
        if normalized == normalized.to_integral_value():
            # Whole number: xsd:integer (matches SPARQL integer arithmetic)
            return SparqlBinding(
                type="literal", value=str(int(normalized)),
                datatype="http://www.w3.org/2001/XMLSchema#integer",
            )
        return SparqlBinding(
            type="literal", value=str(normalized),
            datatype="http://www.w3.org/2001/XMLSchema#decimal",
        )

    # Heuristic: URIs typically start with http://, https://, urn:, or file://
    if val_str.startswith(("http://", "https://", "urn:", "file://", "mailto:")):
        return SparqlBinding(type="uri", value=val_str)

    # Default: treat as literal
    return SparqlBinding(type="literal", value=val_str)


class SqlPipelineError(Exception):
    """Raised when the SQL pipeline fails."""
    pass
