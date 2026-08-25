"""The write and read paths must agree about a term's TYPE.

`issues/135`. `term_uuid` is a UUIDv5 over `(text, type, lang, datatype)`, so a
disagreement about type is not cosmetic — it produces a DIFFERENT term, and the
path that stored a quad and the path that looks it up address different rows.
Every failure is silent: `remove_rdf_quad` reports success having removed
nothing.

Three mechanisms decide it today:

    _ensure_term      by rdflib class, `else 'U'`   — the insert paths
    _infer_type(str)  by string prefix, http/https/urn only
                                                    — remove_rdf_quad,
                                                      get_rdf_quad,
                                                      remove_rdf_quads_batch
    hardcoded 'U'     unconditionally               — ~20 s/p/g call sites

These tests are ARITHMETIC over the term key — no database, no fixtures. They
record the disagreements as they stand so a fix has something to flip, and so
the set cannot grow unnoticed.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Literal, URIRef

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import (
    SparqlSQLSpaceImpl as Impl,
    _generate_term_uuid as term_uuid,
)


def insert_type(term) -> str:
    """What `_ensure_term` decides. Mirrored rather than called: it needs a
    live connection, and the branch under test is the type decision alone."""
    if isinstance(term, URIRef):
        return "U"
    if isinstance(term, BNode):
        return "B"
    if isinstance(term, Literal):
        return "L"
    return "U"


class TestTheSchemeListIsTooShort:
    """`_infer_type` recognises three schemes; RFC 3986 allows any."""

    @pytest.mark.parametrize("uri", [
        "file:///tmp/g.ttl",   # the DAWG harness's graph scheme
        "ftp://x/a",
        "mailto:a@b",
        "did:example:1",
        "tag:example.com,2026:a",
    ])
    def test_a_non_http_uri_is_stored_as_U_and_looked_up_as_L(self, uri):
        stored = insert_type(URIRef(uri))
        looked_up = Impl._infer_type(uri)
        assert stored == "U"
        assert looked_up == "L", (
            f"{uri} now infers {looked_up!r}; if the scheme test was widened, "
            f"delete this case and check issues/135")
        assert term_uuid(uri, stored) != term_uuid(uri, looked_up), (
            "the uuids agree, so the disagreement no longer costs anything")

    @pytest.mark.parametrize("uri", ["http://x/a", "https://x/a", "urn:x:a"])
    def test_the_three_recognised_schemes_do_agree(self, uri):
        assert insert_type(URIRef(uri)) == Impl._infer_type(uri) == "U"


class TestTheBlankNodeBranchIsDeadCode:
    """`_infer_type` tests for `_:`; `issues/065` says we never store it."""

    def test_a_stored_blank_node_label_carries_no_prefix(self):
        assert str(BNode("b1")) == "b1", "the bare-label convention changed"

    def test_so_the_prefix_branch_cannot_fire_for_a_stored_label(self):
        assert Impl._infer_type("_:b1") == "B", "the branch itself still exists"
        assert Impl._infer_type(str(BNode("b1"))) == "L", (
            "a bare label now infers something other than 'L' — if it infers "
            "'B', the convention and the inference were reconciled")

    def test_a_blank_node_is_unreachable_in_every_position(self):
        label = str(BNode("b1"))
        stored = insert_type(BNode("b1"))
        assert stored == "B"
        # object position: _infer_type; subject/predicate/graph: forced 'U'
        assert term_uuid(label, stored) != term_uuid(label, Impl._infer_type(label))
        assert term_uuid(label, stored) != term_uuid(label, "U")


class TestAnUnknownPythonTypeBecomesAUri:
    """`_ensure_term`'s `else` branch, and why 'L' would be the better default."""

    def test_a_bare_string_object_is_typed_as_a_uri(self):
        assert insert_type("plain text") == "U", (
            "the else-branch changed; if it is now 'L', issues/135 defect 3 is "
            "fixed and this file should say so")

    def test_which_disagrees_with_how_it_is_read_back(self):
        v = "plain text"
        assert Impl._infer_type(v) == "L"
        assert term_uuid(v, insert_type(v)) != term_uuid(v, Impl._infer_type(v))
