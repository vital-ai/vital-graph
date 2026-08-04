"""Unit tests for update WHERE clause element mapping — issue 023.

`VALUES` (and several other constructs) in a SPARQL *update*'s WHERE were
silently replaced with an empty BGP, which is the join identity — so the
constraint vanished and `DELETE { ?s ?p ?o } WHERE { VALUES ?s {...} ?s ?p ?o }`
deleted the entire graph while reporting success.

These tests cover both halves of the fix:
  1. the missing element handlers, and
  2. the fail-closed fall-through, which is what generalizes to constructs
     nobody has thought of yet.

Update WHERE patterns arrive as Jena *syntax* Elements (`map_element_to_op`),
not compiled algebra (`map_op`) — that asymmetry is why SELECT was unaffected
and why the existing `VALUES` tests all passed.  Fixtures below mirror
`vitalgraph-jena-sidecar/.../serializer/ElementSerializer.java`.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_ast_mapper import (
    UnsupportedSparqlElement,
    map_element_to_op,
    map_update_op,
)
from vitalgraph.db.jena_sparql.jena_types import (
    ExprExists,
    OpBGP,
    OpFilter,
    OpGraph,
    OpJoin,
    OpLeftJoin,
    OpMinus,
    OpTable,
    URINode,
    VarNode,
)


# ---------------------------------------------------------------------------
# Fixture builders — shapes as emitted by ElementSerializer.java
# ---------------------------------------------------------------------------

def _uri(value: str) -> dict:
    return {"type": "uri", "value": value}


def _var(name: str) -> dict:
    return {"type": "var", "name": name}


def _path_block(*triples) -> dict:
    return {
        "type": "ElementPathBlock",
        "triples": [
            {"subject": s, "predicate": p, "object": o} for s, p, o in triples
        ],
    }


def _spo() -> dict:
    """The `?s ?p ?o` pattern."""
    return _path_block((_var("s"), _var("p"), _var("o")))


def _values(vars_, rows) -> dict:
    """VALUES — note `rows` are POSITIONAL lists aligned to `vars`."""
    return {"type": "ElementValues", "vars": list(vars_), "rows": rows}


def _group(*elements) -> dict:
    return {"type": "ElementGroup", "elements": list(elements)}


def _collect_ops(op, acc=None):
    """Flatten an algebra tree into a list of nodes, for containment asserts."""
    acc = [] if acc is None else acc
    acc.append(op)
    for attr in ("left", "right", "sub_op"):
        child = getattr(op, attr, None)
        if child is not None and hasattr(child, "__dataclass_fields__"):
            _collect_ops(child, acc)
    return acc


# ---------------------------------------------------------------------------
# The fail-closed fall-through — the assertion that generalizes
# ---------------------------------------------------------------------------

class TestFailClosed:
    """An untranslatable element must reject the update, never widen it."""

    def test_unknown_element_raises(self):
        with pytest.raises(UnsupportedSparqlElement):
            map_element_to_op({"type": "ElementSomethingNobodyWroteYet"})

    def test_unknown_element_does_not_return_empty_bgp(self):
        """Guards the exact regression: empty BGP is the join identity."""
        try:
            result = map_element_to_op({"type": "ElementFutureConstruct"})
        except UnsupportedSparqlElement:
            return  # correct
        pytest.fail(
            f"fall-through returned {result!r} instead of raising; an empty BGP "
            f"here silently widens the caller's pattern (issue 023)"
        )

    def test_service_raises(self):
        """SERVICE has no SQL translation — must not be silently dropped."""
        with pytest.raises(UnsupportedSparqlElement):
            map_element_to_op({
                "type": "ElementService",
                "serviceURI": _uri("http://remote.example/sparql"),
                "silent": False,
                "sub": _spo(),
            })

    def test_unknown_inside_group_propagates(self):
        """A group must not swallow an untranslatable child."""
        with pytest.raises(UnsupportedSparqlElement):
            map_element_to_op(_group(_spo(), {"type": "ElementBogus"}))

    def test_error_names_the_element_type(self):
        with pytest.raises(UnsupportedSparqlElement, match="ElementBogus"):
            map_element_to_op({"type": "ElementBogus"})


# ---------------------------------------------------------------------------
# VALUES — the reported bug
# ---------------------------------------------------------------------------

class TestElementValues:

    def test_single_var_single_row(self):
        op = map_element_to_op(
            _values(["s"], [[_uri("urn:probe:doc0")]])
        )
        assert isinstance(op, OpTable)
        assert op.vars == ["s"]
        assert op.rows == [{"s": URINode(value="urn:probe:doc0")}]

    def test_rows_are_positional_not_keyed(self):
        """ElementValues rows are lists aligned to `vars` (unlike OpTable's
        algebra-path serialization, which is keyed by var name)."""
        op = map_element_to_op(_values(
            ["a", "b"],
            [[_uri("urn:x"), _uri("urn:y")]],
        ))
        assert op.rows == [{
            "a": URINode(value="urn:x"),
            "b": URINode(value="urn:y"),
        }]

    def test_multiple_rows(self):
        op = map_element_to_op(_values(
            ["s"],
            [[_uri("urn:a")], [_uri("urn:b")], [_uri("urn:c")]],
        ))
        assert len(op.rows) == 3
        assert [r["s"].value for r in op.rows] == ["urn:a", "urn:b", "urn:c"]

    def test_undef_maps_to_none(self):
        op = map_element_to_op(_values(
            ["a", "b"],
            [[_uri("urn:x"), None]],
        ))
        assert op.rows == [{"a": URINode(value="urn:x"), "b": None}]

    def test_empty_rows(self):
        op = map_element_to_op(_values(["s"], []))
        assert isinstance(op, OpTable)
        assert op.rows == []

    def test_values_survives_a_group(self):
        """The regression: VALUES joined with ?s ?p ?o must remain in the tree."""
        op = map_element_to_op(_group(
            _values(["s"], [[_uri("urn:probe:doc0")]]),
            _spo(),
        ))
        nodes = _collect_ops(op)
        tables = [n for n in nodes if isinstance(n, OpTable)]
        assert len(tables) == 1, (
            "VALUES was dropped from the update WHERE — the remaining "
            "?s ?p ?o is unconstrained and would delete the whole graph"
        )
        assert tables[0].rows == [{"s": URINode(value="urn:probe:doc0")}]
        # and it must be joined, not replaced
        assert any(isinstance(n, OpJoin) for n in nodes)

    def test_values_order_independent(self):
        """VALUES after the triple pattern must survive too."""
        op = map_element_to_op(_group(
            _spo(),
            _values(["s"], [[_uri("urn:probe:doc0")]]),
        ))
        assert any(isinstance(n, OpTable) for n in _collect_ops(op))


# ---------------------------------------------------------------------------
# The other constructs that hit the same fall-through
# ---------------------------------------------------------------------------

class TestOtherDroppedElements:

    def test_triples_block_maps_to_bgp(self):
        """ElementTriplesBlock shares ElementPathBlock's shape.  Dropping it
        would have vaporized an entire WHERE body."""
        op = map_element_to_op({
            "type": "ElementTriplesBlock",
            "triples": [{
                "subject": _var("s"),
                "predicate": _uri("urn:p"),
                "object": _var("o"),
            }],
        })
        assert isinstance(op, OpBGP)
        assert len(op.triples) == 1
        assert op.triples[0].predicate == URINode(value="urn:p")

    def test_minus_wraps_accumulated_result(self):
        """MINUS carries only its right side; it must wrap, not join."""
        op = map_element_to_op(_group(
            _spo(),
            {"type": "ElementMinus", "sub": _path_block(
                (_var("s"), _uri("urn:keep"), _var("x"))
            )},
        ))
        assert isinstance(op, OpMinus)
        assert isinstance(op.left, OpBGP)
        assert isinstance(op.right, OpBGP)
        assert op.right.triples[0].predicate == URINode(value="urn:keep")

    def test_bare_minus_uses_empty_left(self):
        op = map_element_to_op({"type": "ElementMinus", "sub": _spo()})
        assert isinstance(op, OpMinus)
        assert isinstance(op.left, OpBGP) and not op.left.triples

    def test_not_exists_becomes_negated_filter(self):
        op = map_element_to_op(_group(
            _spo(),
            {"type": "ElementNotExists", "sub": _path_block(
                (_var("s"), _uri("urn:guard"), _var("g"))
            )},
        ))
        assert isinstance(op, OpFilter)
        assert len(op.exprs) == 1
        assert isinstance(op.exprs[0], ExprExists)
        assert op.exprs[0].negated is True
        assert isinstance(op.sub_op, OpBGP)

    def test_exists_becomes_positive_filter(self):
        op = map_element_to_op(_group(
            _spo(),
            {"type": "ElementExists", "sub": _spo()},
        ))
        assert isinstance(op, OpFilter)
        assert op.exprs[0].negated is False


# ---------------------------------------------------------------------------
# Shapes the issue recorded as already-correct — keep them correct
# ---------------------------------------------------------------------------

class TestExistingShapesStillWork:

    def test_single_element_group_is_unwrapped(self):
        """A one-element group must not gain a spurious join wrapper."""
        op = map_element_to_op(_group(_spo()))
        assert isinstance(op, OpBGP)
        assert len(op.triples) == 1

    def test_empty_group(self):
        assert map_element_to_op(_group()) == OpBGP(triples=[])

    def test_filter_still_wraps(self):
        """FILTER(?s IN (...)) — listed as correct in the issue."""
        op = map_element_to_op(_group(
            _spo(),
            {"type": "ElementFilter", "expr": {
                "type": "ExprFunction",
                "name": "in",
                "args": [_var("s"), _uri("urn:probe:doc0")],
            }},
        ))
        assert isinstance(op, OpFilter)
        assert isinstance(op.sub_op, OpBGP)

    def test_named_graph_still_maps(self):
        op = map_element_to_op({
            "type": "ElementNamedGraph",
            "graphNode": _uri("urn:g"),
            "sub": _spo(),
        })
        assert isinstance(op, OpGraph)
        assert op.graph_node == URINode(value="urn:g")

    def test_optional_still_maps(self):
        op = map_element_to_op({"type": "ElementOptional", "sub": _spo()})
        assert isinstance(op, OpLeftJoin)
        assert isinstance(op.right, OpBGP)
        assert len(op.right.triples) == 1

    def test_optional_reads_the_sub_key(self):
        """The serializer emits the nested element as "sub", not "element" —
        reading the wrong key dropped every OPTIONAL in an update WHERE."""
        op = map_element_to_op(_group(
            _spo(),
            {"type": "ElementOptional", "sub": _path_block(
                (_var("s"), _uri("urn:opt"), _var("v"))
            )},
        ))
        assert isinstance(op, OpLeftJoin), (
            "OPTIONAL was dropped from the update WHERE"
        )
        assert op.right.triples[0].predicate == URINode(value="urn:opt")
        # the accumulated pattern is the left side, not an empty BGP
        assert isinstance(op.left, OpBGP) and op.left.triples


# ---------------------------------------------------------------------------
# End-to-end at the update-op level — the exact issue 023 statement
# ---------------------------------------------------------------------------

class TestUpdateModifyIntegration:
    """DELETE { GRAPH <g> { ?s ?p ?o } }
       WHERE  { GRAPH <g> { VALUES ?s { <urn:probe:doc0> } ?s ?p ?o } }"""

    def _issue_023_update(self) -> dict:
        return {
            "type": "UpdateModify",
            "deleteQuads": [{
                "graph": _uri("urn:g"),
                "subject": _var("s"),
                "predicate": _var("p"),
                "object": _var("o"),
            }],
            "insertQuads": [],
            "wherePattern": _group({
                "type": "ElementNamedGraph",
                "graphNode": _uri("urn:g"),
                "sub": _group(
                    _values(["s"], [[_uri("urn:probe:doc0")]]),
                    _spo(),
                ),
            }),
        }

    def test_values_reaches_the_where_pattern(self):
        op = map_update_op(self._issue_023_update())
        tables = [n for n in _collect_ops(op.where_pattern)
                  if isinstance(n, OpTable)]
        assert len(tables) == 1, (
            "VALUES did not survive into UpdateModify.where_pattern — the "
            "DELETE would match every triple in the graph (issue 023)"
        )
        assert tables[0].vars == ["s"]
        assert tables[0].rows == [{"s": URINode(value="urn:probe:doc0")}]

    def test_delete_template_preserved(self):
        op = map_update_op(self._issue_023_update())
        assert len(op.delete_quads) == 1
        assert op.delete_quads[0].subject == VarNode(name="s")

    def test_untranslatable_where_rejects_the_whole_update(self):
        """Fail closed at the update level, not just the element level."""
        bad = self._issue_023_update()
        bad["wherePattern"] = _group(_spo(), {"type": "ElementNotYetSupported"})
        with pytest.raises(UnsupportedSparqlElement):
            map_update_op(bad)
