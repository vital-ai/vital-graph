"""
Type Binding Module — convert SQL result rows to SPARQL bindings.

Centralizes the logic for interpreting companion columns (__type, __lang,
__datatype) and Python value types into proper RDF term types (URI, literal,
blank node) with correct datatype and language annotations.

This replaces the scattered _infer_binding() logic in v1's dawg_sql_executor.py.
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XSD = "http://www.w3.org/2001/XMLSchema#"
XSD_STRING = f"{XSD}string"
XSD_INTEGER = f"{XSD}integer"
XSD_DECIMAL = f"{XSD}decimal"
XSD_DOUBLE = f"{XSD}double"
XSD_BOOLEAN = f"{XSD}boolean"
RDF_LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"

COMPANION_SUFFIXES = ("__type", "__uuid", "__lang", "__datatype")


# ---------------------------------------------------------------------------
# SparqlBinding — the output type
# ---------------------------------------------------------------------------

@dataclass
class SparqlBinding:
    """A single binding value in a SPARQL result row.

    Matches the format used by the DAWG test harness (SRX parser, pyoxigraph
    executor) so results can be directly compared across engines.
    """
    type: str  # "uri", "literal", "bnode"
    value: str
    datatype: Optional[str] = None
    lang: Optional[str] = None

    def to_normalized_tuple(self) -> tuple:
        """Return a hashable normalized representation for comparison."""
        return (self.type, self.value, self.datatype or "", self.lang or "")


# ---------------------------------------------------------------------------
# Core binding functions
# ---------------------------------------------------------------------------

def sql_to_sparql_binding(
    sql_col: str,
    value: Any,
    row: Dict[str, Any],
) -> Optional[SparqlBinding]:
    """Convert a SQL result value + companion columns to a SparqlBinding.

    Args:
        sql_col: The SQL column name (e.g. "v0" or "s").
        value: The raw Python value from the SQL result.
        row: The full SQL result row (for companion column lookup).

    Returns:
        A SparqlBinding, or None if the value is unbound (NULL).
    """
    if value is None:
        return None

    # Normalize value to string
    val_str = _value_to_string(value)

    # Look up companion columns
    term_type = _get_companion(row, sql_col, "__type")
    term_lang = _get_companion(row, sql_col, "__lang")
    term_datatype = _get_companion(row, sql_col, "__datatype")

    # Path 1: Explicit type from companion column
    if term_type is not None:
        return _binding_from_companions(val_str, term_type, term_lang, term_datatype)

    # Path 2: Infer from Python value type
    return _binding_from_python_type(value, val_str)


def sql_row_to_bindings(
    row: Dict[str, Any],
    var_map: Dict[str, str],
    sparql_vars: List[str],
) -> Dict[str, SparqlBinding]:
    """Convert a full SQL result row to a dict of SPARQL bindings.

    Args:
        row: The SQL result row (column_name → value).
        var_map: Mapping from SQL column name → SPARQL variable name.
        sparql_vars: Ordered list of SPARQL variable names to extract.

    Returns:
        Dict mapping SPARQL variable name → SparqlBinding.
    """
    # Build inverse map: sparql_name → sql_col
    inv_map = {sparql: sql for sql, sparql in var_map.items()}
    bindings: Dict[str, SparqlBinding] = {}

    for sparql_name in sparql_vars:
        sql_col = inv_map.get(sparql_name)
        if sql_col is None:
            continue
        val = row.get(sql_col)
        if val is None:
            continue

        binding = sql_to_sparql_binding(sql_col, val, row)
        if binding is not None:
            bindings[sparql_name] = binding

    return bindings


# ---------------------------------------------------------------------------
# Numeric normalization
# ---------------------------------------------------------------------------

def normalize_numeric(value: Any, datatype: Optional[str] = None) -> str:
    """Normalize a numeric value to its canonical SPARQL string representation.

    SPARQL has specific canonical forms:
      - xsd:integer: no decimal point, no leading zeros (except "0")
      - xsd:decimal: at least one digit before and after decimal point
      - xsd:double: scientific notation with exactly one digit before decimal
    """
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, int):
        return str(value)

    if isinstance(value, decimal.Decimal):
        return _normalize_decimal(value, datatype)

    if isinstance(value, float):
        if datatype == XSD_DOUBLE:
            return _normalize_double(value)
        # Default: treat as decimal
        return f"{value:.15g}"

    return str(value)


def _normalize_decimal(value: decimal.Decimal, datatype: Optional[str] = None) -> str:
    """Normalize a Python Decimal to SPARQL canonical form."""
    normalized = value.normalize()

    # If it's a whole number and datatype is integer (or no explicit decimal datatype)
    if normalized == normalized.to_integral_value():
        if datatype is None or datatype == XSD_INTEGER:
            return str(int(normalized))
        # Explicit decimal: keep decimal point
        if datatype == XSD_DECIMAL:
            return f"{normalized}.0" if "." not in str(normalized) else str(normalized)

    return str(normalized)


def _normalize_double(value: float) -> str:
    """Normalize a float to XSD double canonical form (scientific notation)."""
    if value == 0.0:
        return "0.0E0"
    formatted = f"{value:.15E}"
    # Remove trailing zeros in mantissa
    mantissa, exp = formatted.split("E")
    mantissa = mantissa.rstrip("0").rstrip(".")
    if "." not in mantissa:
        mantissa += ".0"
    return f"{mantissa}E{int(exp)}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _value_to_string(value: Any) -> str:
    """Convert a Python value to its string representation."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, decimal.Decimal):
        normalized = value.normalize()
        if normalized == normalized.to_integral_value():
            return str(int(normalized))
        return str(normalized)
    return str(value)


def _get_companion(row: Dict[str, Any], col: str, suffix: str) -> Optional[str]:
    """Look up a companion column value, trying both original and lowercase."""
    val = row.get(f"{col}{suffix}")
    if val is not None:
        return val if val else None
    val = row.get(f"{col.lower()}{suffix}")
    if val is not None:
        return val if val else None
    return None


def _binding_from_companions(
    val_str: str,
    term_type: str,
    term_lang: Optional[str],
    term_datatype: Optional[str],
) -> SparqlBinding:
    """Create a SparqlBinding from explicit companion column values."""
    if term_type == "U":
        return SparqlBinding(type="uri", value=val_str)
    if term_type == "B":
        return SparqlBinding(type="bnode", value=val_str)

    # Literal (term_type == "L" or anything else)
    lang = term_lang if term_lang else None
    datatype = term_datatype if term_datatype else None

    # Normalize xsd:boolean canonical forms: "0"→"false", "1"→"true"
    if datatype == XSD_BOOLEAN:
        if val_str == "0":
            val_str = "false"
        elif val_str == "1":
            val_str = "true"

    # RDF 1.1: xsd:string is the default, strip it for comparison
    if datatype == XSD_STRING:
        datatype = None

    # Lang-tagged literals get rdf:langString as their datatype
    if lang:
        datatype = RDF_LANG_STRING

    return SparqlBinding(type="literal", value=val_str,
                         lang=lang, datatype=datatype)


def _binding_from_python_type(value: Any, val_str: str) -> SparqlBinding:
    """Infer a SparqlBinding from a Python value type (no companion columns)."""
    if isinstance(value, bool):
        return SparqlBinding(type="literal",
                             value="true" if value else "false",
                             datatype=XSD_BOOLEAN)

    if isinstance(value, int):
        return SparqlBinding(type="literal", value=str(value),
                             datatype=XSD_INTEGER)

    if isinstance(value, float):
        formatted = f"{value:.15g}"
        return SparqlBinding(type="literal", value=formatted,
                             datatype=XSD_DECIMAL)

    if isinstance(value, decimal.Decimal):
        normalized = value.normalize()
        if normalized == normalized.to_integral_value():
            return SparqlBinding(type="literal", value=str(int(normalized)),
                                 datatype=XSD_INTEGER)
        return SparqlBinding(type="literal", value=str(normalized),
                             datatype=XSD_DECIMAL)

    # Heuristic: URIs typically start with known schemes
    if val_str.startswith(("http://", "https://", "urn:", "file://", "mailto:")):
        return SparqlBinding(type="uri", value=val_str)

    # Default: plain literal
    return SparqlBinding(type="literal", value=val_str)
