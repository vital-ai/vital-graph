"""CONSTRUCT template instantiation — issue 025.

The WHERE pattern of a CONSTRUCT query executes through the ordinary SELECT
machinery; what was missing is the step that turns each solution into triples.
This module is that step, kept free of database access so it can be tested
directly against SPARQL 1.1 §16.2 rather than only end-to-end.

Everything here operates on SPARQL JSON term dicts
(``{'type': 'uri', 'value': ...}``) — the same shape
``_rows_to_sparql_bindings`` produces and the REST layer already emits.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from ..jena_sparql.jena_types import (
    BNodeNode, LiteralNode, RDFNode, TriplePattern, URINode, VarNode,
)

logger = logging.getLogger(__name__)

Term = Dict[str, Any]
Triple = Dict[str, Term]


def _node_to_term(node: RDFNode) -> Optional[Term]:
    """Convert a constant template node to a SPARQL JSON term."""
    if isinstance(node, URINode):
        return {"type": "uri", "value": node.value}
    if isinstance(node, LiteralNode):
        term: Term = {"type": "literal", "value": node.value}
        if node.lang:
            term["xml:lang"] = node.lang
        elif node.datatype:
            term["datatype"] = node.datatype
        return term
    if isinstance(node, BNodeNode):
        return {"type": "bnode", "value": node.label}
    return None


def _resolve(node: RDFNode, binding: Dict[str, Term],
             bnode_scope: Dict[str, str], row_index: int) -> Optional[Term]:
    """Resolve one template position against one solution.

    Returns None when the position cannot be filled — an unbound variable —
    which per §16.2 means the *triple* is skipped, not the whole solution.
    """
    if isinstance(node, VarNode):
        return binding.get(node.name)
    if isinstance(node, BNodeNode):
        # §16.2: a blank node in the template yields a *fresh* blank node for
        # every solution. Sharing one label across rows would silently merge
        # otherwise-distinct constructed subjects.
        label = bnode_scope.get(node.label)
        if label is None:
            label = f"b{row_index}_{node.label}"
            bnode_scope[node.label] = label
        return {"type": "bnode", "value": label}
    return _node_to_term(node)


def _is_legal(subject: Term, predicate: Term, obj: Term) -> bool:
    """RDF forbids some term/position combinations; §16.2 skips those triples.

    Nothing downstream validates this, and a literal in the subject position
    would be emitted as a triple no RDF parser could read back.
    """
    if subject.get("type") == "literal":
        return False
    if predicate.get("type") != "uri":
        return False
    return True


def instantiate_construct(
    template: Iterable[TriplePattern],
    bindings: List[Dict[str, Term]],
) -> List[Triple]:
    """Instantiate a CONSTRUCT template over solutions, per SPARQL 1.1 §16.2.

    - each solution fills the template once;
    - a triple whose subject/predicate/object is unbound is **skipped**, while
      the rest of that solution's triples are kept;
    - template blank nodes are freshly allocated per solution;
    - illegal triples (literal subject, non-IRI predicate) are skipped;
    - the result is a set — CONSTRUCT returns a graph, not a bag — with
      insertion order preserved for stable output.
    """
    template = list(template)
    out: List[Triple] = []
    seen = set()
    skipped_unbound = 0

    for row_index, binding in enumerate(bindings):
        bnode_scope: Dict[str, str] = {}
        for pattern in template:
            s = _resolve(pattern.subject, binding, bnode_scope, row_index)
            p = _resolve(pattern.predicate, binding, bnode_scope, row_index)
            o = _resolve(pattern.object, binding, bnode_scope, row_index)

            if s is None or p is None or o is None:
                skipped_unbound += 1
                continue
            if not _is_legal(s, p, o):
                continue

            key = (
                s.get("type"), s.get("value"),
                p.get("type"), p.get("value"),
                o.get("type"), o.get("value"),
                o.get("xml:lang"), o.get("datatype"),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append({"subject": s, "predicate": p, "object": o})

    if skipped_unbound:
        logger.debug(
            "CONSTRUCT: skipped %d template triple(s) with unbound positions",
            skipped_unbound)
    return out


def describe_targets(
    describe_nodes: Iterable[RDFNode],
    bindings: List[Dict[str, Term]],
) -> List[str]:
    """Resolve DESCRIBE targets to concrete URIs.

    Targets are constants (``DESCRIBE <uri>``) or variables bound by the WHERE
    clause (``DESCRIBE ?s WHERE { … }``), and a query may mix both. Only IRIs
    are describable — a variable that binds to a literal contributes nothing.
    Order is preserved and duplicates removed.
    """
    uris: List[str] = []
    seen = set()

    def _add(value: str) -> None:
        if value not in seen:
            seen.add(value)
            uris.append(value)

    for node in describe_nodes:
        if isinstance(node, URINode):
            _add(node.value)
        elif isinstance(node, VarNode):
            for binding in bindings:
                term = binding.get(node.name)
                if term and term.get("type") == "uri":
                    _add(term["value"])
    return uris
