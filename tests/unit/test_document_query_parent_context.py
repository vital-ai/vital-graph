"""The parent/original lookup in a document query is ONE nested group (`issues/288`).

It was two SIBLING OPTIONALs. When the parent group did not match -- a hit that
is a parent copy or an original, or a parent copy without a name --
`?_parent_doc` was unbound when the original group ran, so that group matched
ANY edge in the graph: the hit came back once per edge, its "parent" a slot and
its "original" the frame above it. Asserted on the generated SPARQL, which is
where the shape lives; the API test proves the consequence.
"""

from __future__ import annotations

import re

from vitalgraph.sparql.kg_query_builder import DocumentQueryCriteria, KGQueryCriteriaBuilder


def _where(**kw) -> str:
    return KGQueryCriteriaBuilder()._build_document_where_clause(DocumentQueryCriteria(**kw))


def _group_at(text: str, start: int) -> str:
    """The balanced `{ ... }` group whose opening brace is at or after `start`."""
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i:j + 1]
    raise AssertionError("unbalanced braces")


def test_the_original_is_looked_up_inside_the_parent_group():
    w = _where(include_parent_context=True, include_original_uri=True)
    parent = _group_at(w, w.index("OPTIONAL { ?_parent_edge"))
    assert "?_orig_edge" in parent, (
        "the original lookup must be nested in the parent group, or an "
        f"unmatched parent leaves it free to match any edge:\n{w}")
    # And nowhere outside it.
    assert w.count("?_orig_edge vital-core:hasEdgeSource") == 1


def test_both_hops_are_segment_edges():
    w = _where(include_parent_context=True, include_original_uri=True)
    assert len(re.findall(r"vital-core:vitaltype haley:Edge_hasKGDocumentSegment", w)) == 2, w


def test_a_nameless_parent_copy_still_resolves():
    w = _where(include_parent_context=True)
    parent = _group_at(w, w.index("OPTIONAL { ?_parent_edge"))
    assert "OPTIONAL { ?_parent_doc vital-core:hasName ?_parent_name . }" in parent, parent
