"""
Compare SPARQL result sets from different engines.

Handles normalization of:
- Numeric literal types (xsd:integer, xsd:decimal, xsd:double)
- Blank node isomorphism (bnodes match if structure is consistent)
- Unbound variables (missing keys treated as absent)
- Row ordering (ignored for unordered results)
"""

from __future__ import annotations

import logging
import re
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from .dawg_srx_parser import SparqlBinding, SparqlResults

logger = logging.getLogger(__name__)

# XSD numeric types that should be compared by value, not string
XSD = "http://www.w3.org/2001/XMLSchema#"
NUMERIC_TYPES = {
    f"{XSD}integer", f"{XSD}decimal", f"{XSD}double", f"{XSD}float",
    f"{XSD}int", f"{XSD}long", f"{XSD}short", f"{XSD}byte",
    f"{XSD}nonNegativeInteger", f"{XSD}positiveInteger",
    f"{XSD}nonPositiveInteger", f"{XSD}negativeInteger",
    f"{XSD}unsignedInt", f"{XSD}unsignedLong", f"{XSD}unsignedShort",
    f"{XSD}unsignedByte",
}


class ComparisonResult:
    """Result of comparing two result sets."""

    def __init__(self, match: bool, message: str = "",
                 expected_count: int = 0, actual_count: int = 0):
        self.match = match
        self.message = message
        self.expected_count = expected_count
        self.actual_count = actual_count

    def __bool__(self):
        return self.match

    def __repr__(self):
        status = "MATCH" if self.match else "MISMATCH"
        return f"ComparisonResult({status}, expected={self.expected_count}, actual={self.actual_count}, msg={self.message!r})"


def compare_results(
    actual: SparqlResults,
    expected: SparqlResults,
    ordered: bool = False,
) -> ComparisonResult:
    """Compare actual results against expected results.

    Args:
        actual: Results from the engine under test.
        expected: Expected results (from .srx or another oracle).
        ordered: If True, row order must match exactly.

    Returns:
        ComparisonResult with match status and diagnostic message.
    """
    # Boolean results (ASK queries)
    if expected.is_boolean:
        if not actual.is_boolean:
            return ComparisonResult(False, "Expected boolean result, got bindings")
        if actual.boolean_value != expected.boolean_value:
            return ComparisonResult(
                False,
                f"Boolean mismatch: expected {expected.boolean_value}, got {actual.boolean_value}",
            )
        return ComparisonResult(True, "Boolean match")

    # Graph results (CONSTRUCT/DESCRIBE) — compare as triple sets
    if expected.is_graph or actual.is_graph:
        return _compare_graphs(actual, expected)

    # Check variable names match (order doesn't matter)
    exp_vars = set(expected.variables)
    act_vars = set(actual.variables)
    if exp_vars != act_vars:
        # Some engines return extra variables — check if expected vars are a subset
        missing = exp_vars - act_vars
        if missing:
            return ComparisonResult(
                False,
                f"Missing variables in actual: {missing}",
                expected_count=len(expected.rows),
                actual_count=len(actual.rows),
            )

    # Row count check
    if len(expected.rows) != len(actual.rows):
        return ComparisonResult(
            False,
            f"Row count mismatch: expected {len(expected.rows)}, got {len(actual.rows)}",
            expected_count=len(expected.rows),
            actual_count=len(actual.rows),
        )

    # Normalize rows
    norm_expected = [_normalize_row(row, exp_vars) for row in expected.rows]
    norm_actual = [_normalize_row(row, exp_vars) for row in actual.rows]

    if ordered:
        for i, (exp_row, act_row) in enumerate(zip(norm_expected, norm_actual)):
            if exp_row != act_row:
                return ComparisonResult(
                    False,
                    f"Row {i} mismatch: expected {_row_repr(exp_row)}, got {_row_repr(act_row)}",
                    expected_count=len(expected.rows),
                    actual_count=len(actual.rows),
                )
    else:
        # Unordered comparison — check if multisets match
        # Handle bnodes by trying to find a consistent mapping
        if _has_bnodes(norm_expected) or _has_bnodes(norm_actual):
            if not _compare_with_bnode_iso(norm_expected, norm_actual, exp_vars):
                return ComparisonResult(
                    False,
                    "Result set mismatch (with bnode isomorphism check)",
                    expected_count=len(expected.rows),
                    actual_count=len(actual.rows),
                )
        else:
            exp_set = _rows_to_multiset(norm_expected)
            act_set = _rows_to_multiset(norm_actual)
            if exp_set != act_set:
                # Find first difference for diagnostic
                diff = _first_difference(norm_expected, norm_actual)
                return ComparisonResult(
                    False,
                    f"Result set mismatch: {diff}",
                    expected_count=len(expected.rows),
                    actual_count=len(actual.rows),
                )

    return ComparisonResult(
        True,
        f"Match ({len(expected.rows)} rows)",
        expected_count=len(expected.rows),
        actual_count=len(actual.rows),
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

NormalizedBinding = Tuple[str, str, str, str]  # (type, value, datatype, lang)
NormalizedRow = Dict[str, NormalizedBinding]


def _normalize_row(row: Dict[str, SparqlBinding], variables: Set[str]) -> NormalizedRow:
    """Normalize a result row for comparison."""
    normalized: NormalizedRow = {}
    for var in variables:
        if var in row:
            normalized[var] = _normalize_binding(row[var])
        # Missing bindings are simply absent (not included)
    return normalized


def _normalize_binding(b: SparqlBinding) -> NormalizedBinding:
    """Normalize a single binding value."""
    btype = b.type
    value = b.value
    datatype = b.datatype or ""
    lang = b.lang or ""

    # Normalize numeric literals by canonical form and collapse numeric subtypes
    # SPARQL compares numeric values by value regardless of specific type
    if btype == "literal" and datatype in NUMERIC_TYPES:
        try:
            from decimal import Decimal, InvalidOperation
            # Parse to Decimal for lossless comparison across types
            d = Decimal(value)
            # Normalize: strip trailing zeros
            d = d.normalize()
            # Use canonical string representation
            value = str(d)
            # Collapse all numeric subtypes to a common marker for comparison
            datatype = "__NUMERIC__"
        except (ValueError, ArithmeticError, InvalidOperation):
            pass  # Keep original if parsing fails

    # RDF 1.1: xsd:string and plain literals are identical
    if datatype == f"{XSD}string":
        datatype = ""

    # RDF 1.1: lang-tagged literals implicitly have rdf:langString datatype.
    # Normalize: if lang is present, always set datatype to rdf:langString.
    # Also normalize lang tags to lowercase per BCP 47 (case-insensitive).
    RDF_LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
    if btype == "literal" and lang:
        datatype = RDF_LANG_STRING
        lang = lang.lower()

    # Normalize plain literals without explicit datatype
    # "14" with no datatype vs "14"^^xsd:integer — treat as equivalent
    if btype == "literal" and not datatype and not lang:
        # Check if it looks like an integer
        try:
            int(value)
            # Don't auto-promote — leave as-is for strict comparison
        except ValueError:
            pass

    return (btype, value, datatype, lang)


# ---------------------------------------------------------------------------
# Multiset comparison
# ---------------------------------------------------------------------------

def _row_to_hashable(row: NormalizedRow) -> FrozenSet:
    """Convert a normalized row to a hashable frozen set."""
    return frozenset(row.items())


def _rows_to_multiset(rows: List[NormalizedRow]) -> Dict[FrozenSet, int]:
    """Convert rows to a multiset (bag) for unordered comparison."""
    bag: Dict[FrozenSet, int] = {}
    for row in rows:
        key = _row_to_hashable(row)
        bag[key] = bag.get(key, 0) + 1
    return bag


def _first_difference(expected: List[NormalizedRow], actual: List[NormalizedRow]) -> str:
    """Find the first row that differs between expected and actual multisets."""
    exp_bag = _rows_to_multiset(expected)
    act_bag = _rows_to_multiset(actual)

    for key, count in exp_bag.items():
        act_count = act_bag.get(key, 0)
        if act_count < count:
            return f"Expected row not found in actual: {dict(key)}"

    for key, count in act_bag.items():
        exp_count = exp_bag.get(key, 0)
        if exp_count < count:
            return f"Unexpected row in actual: {dict(key)}"

    return "Unknown difference"


# ---------------------------------------------------------------------------
# Blank node isomorphism (simplified)
# ---------------------------------------------------------------------------

def _has_bnodes(rows: List[NormalizedRow]) -> bool:
    """Check if any row contains blank node bindings."""
    for row in rows:
        for binding in row.values():
            if binding[0] == "bnode":
                return True
    return False


def _compare_with_bnode_iso(
    expected: List[NormalizedRow],
    actual: List[NormalizedRow],
    variables: Set[str],
) -> bool:
    """Compare result sets allowing blank node relabeling.

    Uses backtracking search to find a consistent bnode mapping.
    """
    if len(expected) != len(actual):
        return False

    def _backtrack(idx: int, used: List[bool],
                   bnode_map: Dict[str, str]) -> bool:
        if idx == len(expected):
            return True
        exp_row = expected[idx]
        for j, act_row in enumerate(actual):
            if used[j]:
                continue
            saved_map = dict(bnode_map)
            if _rows_match_with_bnodes(exp_row, act_row, bnode_map):
                used[j] = True
                if _backtrack(idx + 1, used, bnode_map):
                    return True
                used[j] = False
            # Restore bnode_map on failure
            bnode_map.clear()
            bnode_map.update(saved_map)
        return False

    return _backtrack(0, [False] * len(actual), {})


def _rows_match_with_bnodes(
    exp: NormalizedRow, act: NormalizedRow,
    bnode_map: Dict[str, str],
) -> bool:
    """Check if two rows match, allowing bnode relabeling."""
    if set(exp.keys()) != set(act.keys()):
        return False

    # Tentative new mappings
    new_mappings: Dict[str, str] = {}

    for var in exp:
        eb = exp[var]
        ab = act.get(var)
        if ab is None:
            return False

        if eb[0] == "bnode" and ab[0] == "bnode":
            exp_id = eb[1]
            act_id = ab[1]
            # Check existing mapping
            if exp_id in bnode_map:
                if bnode_map[exp_id] != act_id:
                    return False
            elif exp_id in new_mappings:
                if new_mappings[exp_id] != act_id:
                    return False
            else:
                new_mappings[exp_id] = act_id
        elif eb != ab:
            return False

    # Commit new mappings
    bnode_map.update(new_mappings)
    return True


def _compare_graphs(
    actual: 'SparqlResults',
    expected: 'SparqlResults',
) -> 'ComparisonResult':
    """Compare graph (CONSTRUCT/DESCRIBE) results as triple sets."""
    graph_vars = {"subject", "predicate", "object"}
    norm_exp = [_normalize_row(r, graph_vars) for r in expected.rows]
    norm_act = [_normalize_row(r, graph_vars) for r in actual.rows]

    if len(norm_exp) != len(norm_act):
        return ComparisonResult(
            False,
            f"Triple count mismatch: expected {len(norm_exp)}, got {len(norm_act)}",
            expected_count=len(norm_exp),
            actual_count=len(norm_act),
        )

    # Use bnode-aware comparison if bnodes present
    if _has_bnodes(norm_exp) or _has_bnodes(norm_act):
        if _compare_with_bnode_iso(norm_exp, norm_act, graph_vars):
            return ComparisonResult(
                True,
                f"Graph match ({len(norm_exp)} triples)",
                expected_count=len(norm_exp),
                actual_count=len(norm_act),
            )
        return ComparisonResult(
            False,
            "Graph mismatch (with bnode isomorphism check)",
            expected_count=len(norm_exp),
            actual_count=len(norm_act),
        )

    exp_set = _rows_to_multiset(norm_exp)
    act_set = _rows_to_multiset(norm_act)
    if exp_set == act_set:
        return ComparisonResult(
            True,
            f"Graph match ({len(norm_exp)} triples)",
            expected_count=len(norm_exp),
            actual_count=len(norm_act),
        )

    diff = _first_difference(norm_exp, norm_act)
    return ComparisonResult(
        False,
        f"Graph mismatch: {diff}",
        expected_count=len(norm_exp),
        actual_count=len(norm_act),
    )


def _row_repr(row: NormalizedRow) -> str:
    """Human-readable row representation."""
    parts = []
    for var, binding in sorted(row.items()):
        btype, value, dt, lang = binding
        if btype == "uri":
            parts.append(f"?{var}=<{value}>")
        elif lang:
            parts.append(f'?{var}="{value}"@{lang}')
        elif dt:
            parts.append(f'?{var}="{value}"^^<{dt}>')
        else:
            parts.append(f'?{var}="{value}"')
    return "{ " + " , ".join(parts) + " }"
