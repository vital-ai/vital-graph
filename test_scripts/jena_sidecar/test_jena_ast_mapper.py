"""
Unit tests for the Jena AST mapper.

Tests JSON → Python type conversion using canned JSON fixtures
(no sidecar or database required).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import unittest
from vitalgraph_sparql_sql.jena_ast_mapper import (
    map_compile_response, map_op, map_node, map_expr, map_update_op,
)
from vitalgraph_sparql_sql.jena_types import *


class TestMapNode(unittest.TestCase):
    def test_var_node(self):
        n = map_node({"type": "var", "name": "s"})
        self.assertIsInstance(n, VarNode)
        self.assertEqual(n.name, "s")

    def test_uri_node(self):
        n = map_node({"type": "uri", "value": "http://example.org/p"})
        self.assertIsInstance(n, URINode)
        self.assertEqual(n.value, "http://example.org/p")

    def test_literal_plain(self):
        n = map_node({"type": "literal", "value": "hello"})
        self.assertIsInstance(n, LiteralNode)
        self.assertEqual(n.value, "hello")
        self.assertIsNone(n.lang)
        self.assertIsNone(n.datatype)

    def test_literal_typed(self):
        n = map_node({
            "type": "literal",
            "value": "42",
            "datatype": "http://www.w3.org/2001/XMLSchema#integer"
        })
        self.assertIsInstance(n, LiteralNode)
        self.assertEqual(n.value, "42")
        self.assertEqual(n.datatype, "http://www.w3.org/2001/XMLSchema#integer")

    def test_literal_lang(self):
        n = map_node({"type": "literal", "value": "bonjour", "lang": "fr"})
        self.assertIsInstance(n, LiteralNode)
        self.assertEqual(n.lang, "fr")

    def test_bnode(self):
        n = map_node({"type": "bnode", "label": "b0"})
        self.assertIsInstance(n, BNodeNode)
        self.assertEqual(n.label, "b0")


class TestMapExpr(unittest.TestCase):
    def test_expr_var(self):
        e = map_expr({"type": "ExprVar", "var": "x"})
        self.assertIsInstance(e, ExprVar)
        self.assertEqual(e.var, "x")

    def test_node_value(self):
        e = map_expr({
            "type": "NodeValue",
            "node": {"type": "literal", "value": "5",
                     "datatype": "http://www.w3.org/2001/XMLSchema#integer"}
        })
        self.assertIsInstance(e, ExprValue)
        self.assertIsInstance(e.node, LiteralNode)
        self.assertEqual(e.node.value, "5")

    def test_expr_function2(self):
        e = map_expr({
            "type": "ExprFunction2",
            "name": "gt",
            "args": [
                {"type": "ExprVar", "var": "o"},
                {"type": "NodeValue", "node": {
                    "type": "literal", "value": "5",
                    "datatype": "http://www.w3.org/2001/XMLSchema#integer"
                }}
            ]
        })
        self.assertIsInstance(e, ExprFunction)
        self.assertEqual(e.name, "gt")
        self.assertEqual(len(e.args), 2)
        self.assertIsInstance(e.args[0], ExprVar)
        self.assertIsInstance(e.args[1], ExprValue)

    def test_expr_aggregator(self):
        e = map_expr({
            "type": "ExprAggregator",
            "name": "COUNT",
            "aggregator": {
                "name": "COUNT",
                "distinct": True,
                "expr": {"type": "ExprVar", "var": "s"}
            }
        })
        self.assertIsInstance(e, ExprAggregator)
        self.assertEqual(e.name, "COUNT")
        self.assertTrue(e.distinct)
        self.assertIsInstance(e.expr, ExprVar)


class TestMapOp(unittest.TestCase):
    def test_op_bgp(self):
        op = map_op({
            "type": "OpBGP",
            "triples": [{
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "uri", "value": "http://example.org/p"},
                "object": {"type": "var", "name": "o"}
            }]
        })
        self.assertIsInstance(op, OpBGP)
        self.assertEqual(len(op.triples), 1)
        self.assertIsInstance(op.triples[0].subject, VarNode)
        self.assertIsInstance(op.triples[0].predicate, URINode)

    def test_op_bgp_two_triples(self):
        op = map_op({
            "type": "OpBGP",
            "triples": [
                {
                    "subject": {"type": "var", "name": "s"},
                    "predicate": {"type": "uri", "value": "http://ex.org/p"},
                    "object": {"type": "var", "name": "o"}
                },
                {
                    "subject": {"type": "var", "name": "s"},
                    "predicate": {"type": "uri", "value": "http://ex.org/q"},
                    "object": {"type": "var", "name": "z"}
                }
            ]
        })
        self.assertIsInstance(op, OpBGP)
        self.assertEqual(len(op.triples), 2)

    def test_op_project(self):
        op = map_op({
            "type": "OpProject",
            "vars": ["s", "p", "o"],
            "subOp": {
                "type": "OpBGP",
                "triples": [{
                    "subject": {"type": "var", "name": "s"},
                    "predicate": {"type": "var", "name": "p"},
                    "object": {"type": "var", "name": "o"}
                }]
            }
        })
        self.assertIsInstance(op, OpProject)
        self.assertEqual(op.vars, ["s", "p", "o"])
        self.assertIsInstance(op.sub_op, OpBGP)

    def test_op_slice(self):
        op = map_op({
            "type": "OpSlice",
            "start": -9223372036854775808,
            "length": 10,
            "subOp": {
                "type": "OpProject",
                "vars": ["s"],
                "subOp": {"type": "OpBGP", "triples": [{
                    "subject": {"type": "var", "name": "s"},
                    "predicate": {"type": "var", "name": "p"},
                    "object": {"type": "var", "name": "o"}
                }]}
            }
        })
        self.assertIsInstance(op, OpSlice)
        self.assertEqual(op.start, 0)  # normalized from negative
        self.assertEqual(op.length, 10)
        self.assertIsInstance(op.sub_op, OpProject)

    def test_op_filter(self):
        op = map_op({
            "type": "OpFilter",
            "exprs": [{
                "type": "ExprFunction2",
                "name": "gt",
                "args": [
                    {"type": "ExprVar", "var": "o"},
                    {"type": "NodeValue", "node": {
                        "type": "literal", "value": "5",
                        "datatype": "http://www.w3.org/2001/XMLSchema#integer"
                    }}
                ]
            }],
            "subOp": {
                "type": "OpBGP",
                "triples": [{
                    "subject": {"type": "var", "name": "s"},
                    "predicate": {"type": "uri", "value": "http://ex.org/p"},
                    "object": {"type": "var", "name": "o"}
                }]
            }
        })
        self.assertIsInstance(op, OpFilter)
        self.assertEqual(len(op.exprs), 1)
        self.assertIsInstance(op.exprs[0], ExprFunction)
        self.assertIsInstance(op.sub_op, OpBGP)

    def test_op_left_join(self):
        op = map_op({
            "type": "OpLeftJoin",
            "left": {"type": "OpBGP", "triples": [{
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "uri", "value": "http://ex.org/p"},
                "object": {"type": "var", "name": "o"}
            }]},
            "right": {"type": "OpBGP", "triples": [{
                "subject": {"type": "var", "name": "o"},
                "predicate": {"type": "uri", "value": "http://ex.org/q"},
                "object": {"type": "var", "name": "z"}
            }]},
            "exprs": []
        })
        self.assertIsInstance(op, OpLeftJoin)
        self.assertIsInstance(op.left, OpBGP)
        self.assertIsInstance(op.right, OpBGP)
        self.assertEqual(op.exprs, [])

    def test_op_union(self):
        op = map_op({
            "type": "OpUnion",
            "left": {"type": "OpBGP", "triples": [{
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "uri", "value": "http://ex.org/a"},
                "object": {"type": "var", "name": "o"}
            }]},
            "right": {"type": "OpBGP", "triples": [{
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "uri", "value": "http://ex.org/b"},
                "object": {"type": "var", "name": "o"}
            }]}
        })
        self.assertIsInstance(op, OpUnion)
        self.assertIsInstance(op.left, OpBGP)
        self.assertIsInstance(op.right, OpBGP)

    def test_op_order(self):
        op = map_op({
            "type": "OpOrder",
            "conditions": [{
                "direction": "ASC",
                "expr": {"type": "ExprVar", "var": "s"}
            }],
            "subOp": {"type": "OpBGP", "triples": [{
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "var", "name": "p"},
                "object": {"type": "var", "name": "o"}
            }]}
        })
        self.assertIsInstance(op, OpOrder)
        self.assertEqual(len(op.conditions), 1)
        self.assertEqual(op.conditions[0].direction, "ASC")
        self.assertIsInstance(op.conditions[0].expr, ExprVar)

    def test_op_distinct(self):
        op = map_op({
            "type": "OpDistinct",
            "subOp": {"type": "OpProject", "vars": ["s"],
                      "subOp": {"type": "OpBGP", "triples": [{
                          "subject": {"type": "var", "name": "s"},
                          "predicate": {"type": "var", "name": "p"},
                          "object": {"type": "var", "name": "o"}
                      }]}}
        })
        self.assertIsInstance(op, OpDistinct)
        self.assertIsInstance(op.sub_op, OpProject)

    def test_op_extend(self):
        op = map_op({
            "type": "OpExtend",
            "var": "label",
            "expr": {"type": "ExprVar", "var": "name"},
            "subOp": {"type": "OpBGP", "triples": [{
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "uri", "value": "http://ex.org/name"},
                "object": {"type": "var", "name": "name"}
            }]}
        })
        self.assertIsInstance(op, OpExtend)
        self.assertEqual(op.var, "label")
        self.assertIsInstance(op.expr, ExprVar)

    def test_op_graph(self):
        op = map_op({
            "type": "OpGraph",
            "graphNode": {"type": "uri", "value": "http://ex.org/graph1"},
            "subOp": {"type": "OpBGP", "triples": [{
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "var", "name": "p"},
                "object": {"type": "var", "name": "o"}
            }]}
        })
        self.assertIsInstance(op, OpGraph)
        self.assertIsInstance(op.graph_node, URINode)
        self.assertEqual(op.graph_node.value, "http://ex.org/graph1")

    def test_op_minus(self):
        bgp = {"type": "OpBGP", "triples": [{
            "subject": {"type": "var", "name": "s"},
            "predicate": {"type": "var", "name": "p"},
            "object": {"type": "var", "name": "o"}
        }]}
        op = map_op({"type": "OpMinus", "left": bgp, "right": bgp})
        self.assertIsInstance(op, OpMinus)

    def test_op_null(self):
        op = map_op({"type": "OpNull"})
        self.assertIsInstance(op, OpNull)

    def test_unknown_op(self):
        op = map_op({"type": "OpFutureThing"})
        self.assertIsInstance(op, OpNull)


class TestMapUpdateOp(unittest.TestCase):
    def test_insert_data(self):
        u = map_update_op({
            "type": "UpdateDataInsert",
            "quads": [{
                "graph": None,
                "subject": {"type": "uri", "value": "http://ex.org/s"},
                "predicate": {"type": "uri", "value": "http://ex.org/p"},
                "object": {"type": "literal", "value": "hello"}
            }]
        })
        self.assertIsInstance(u, UpdateDataInsert)
        self.assertEqual(len(u.quads), 1)
        self.assertIsNone(u.quads[0].graph)
        self.assertIsInstance(u.quads[0].subject, URINode)
        self.assertIsInstance(u.quads[0].object, LiteralNode)

    def test_delete_data(self):
        u = map_update_op({
            "type": "UpdateDataDelete",
            "quads": [{
                "graph": None,
                "subject": {"type": "uri", "value": "http://ex.org/s"},
                "predicate": {"type": "uri", "value": "http://ex.org/p"},
                "object": {"type": "literal", "value": "old"}
            }]
        })
        self.assertIsInstance(u, UpdateDataDelete)
        self.assertEqual(len(u.quads), 1)

    def test_update_modify(self):
        u = map_update_op({
            "type": "UpdateModify",
            "withGraph": None,
            "deleteQuads": [{
                "graph": None,
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "uri", "value": "http://ex.org/old"},
                "object": {"type": "var", "name": "o"}
            }],
            "insertQuads": [{
                "graph": None,
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "uri", "value": "http://ex.org/new"},
                "object": {"type": "var", "name": "o"}
            }],
            "usingGraphs": [],
            "wherePattern": {
                "type": "OpBGP",
                "triples": [{
                    "subject": {"type": "var", "name": "s"},
                    "predicate": {"type": "uri", "value": "http://ex.org/old"},
                    "object": {"type": "var", "name": "o"}
                }]
            }
        })
        self.assertIsInstance(u, UpdateModify)
        self.assertEqual(len(u.delete_quads), 1)
        self.assertEqual(len(u.insert_quads), 1)
        self.assertIsInstance(u.where_pattern, OpBGP)

    def test_update_clear(self):
        u = map_update_op({
            "type": "UpdateClear",
            "target": "ALL",
            "silent": False
        })
        self.assertIsInstance(u, UpdateClear)
        self.assertEqual(u.target, "ALL")

    def test_update_load(self):
        u = map_update_op({
            "type": "UpdateLoad",
            "source": "http://example.org/data.ttl",
            "destGraph": "http://example.org/graph",
            "silent": True
        })
        self.assertIsInstance(u, UpdateLoad)
        self.assertEqual(u.source, "http://example.org/data.ttl")
        self.assertTrue(u.silent)


class TestMapCompileResponse(unittest.TestCase):
    def test_select_query(self):
        data = {
            "ok": True,
            "meta": {},
            "input": {"sparqlHash": "sha256:abc"},
            "phases": {
                "parsedQuery": {
                    "queryType": "SELECT",
                    "projectVars": ["s", "p", "o"],
                    "distinct": False,
                    "reduced": False,
                    "limit": 10,
                    "offset": 0,
                    "orderBy": [],
                    "groupBy": [],
                    "having": [],
                    "sparqlForm": "QUERY"
                },
                "algebraCompiled": {
                    "op": {
                        "type": "OpSlice",
                        "start": -9223372036854775808,
                        "length": 10,
                        "subOp": {
                            "type": "OpProject",
                            "vars": ["s", "p", "o"],
                            "subOp": {
                                "type": "OpBGP",
                                "triples": [{
                                    "subject": {"type": "var", "name": "s"},
                                    "predicate": {"type": "var", "name": "p"},
                                    "object": {"type": "var", "name": "o"}
                                }]
                            }
                        }
                    }
                },
                "updateOperations": None
            },
            "error": None,
            "warnings": []
        }
        result = map_compile_response(data)
        self.assertTrue(result.ok)
        self.assertEqual(result.meta.sparql_form, "QUERY")
        self.assertEqual(result.meta.query_type, "SELECT")
        self.assertEqual(result.meta.project_vars, ["s", "p", "o"])
        self.assertEqual(result.meta.limit, 10)
        self.assertIsInstance(result.algebra, OpSlice)
        self.assertEqual(result.algebra.length, 10)
        self.assertEqual(len(result.update_ops), 0)

    def test_update_response(self):
        data = {
            "ok": True,
            "meta": {},
            "input": {"sparqlHash": "sha256:xyz"},
            "phases": {
                "parsedQuery": {
                    "sparqlForm": "UPDATE",
                    "operationCount": 1
                },
                "algebraCompiled": None,
                "updateOperations": [{
                    "type": "UpdateDataInsert",
                    "quads": [{
                        "graph": None,
                        "subject": {"type": "uri", "value": "http://ex.org/s"},
                        "predicate": {"type": "uri", "value": "http://ex.org/p"},
                        "object": {"type": "literal", "value": "hello"}
                    }]
                }]
            },
            "error": None,
            "warnings": []
        }
        result = map_compile_response(data)
        self.assertTrue(result.ok)
        self.assertEqual(result.meta.sparql_form, "UPDATE")
        self.assertIsNone(result.algebra)
        self.assertEqual(len(result.update_ops), 1)
        self.assertIsInstance(result.update_ops[0], UpdateDataInsert)

    def test_error_response(self):
        data = {
            "ok": False,
            "meta": {},
            "input": {"sparqlHash": "sha256:bad"},
            "phases": {
                "parsedQuery": {"sparqlForm": "QUERY"}
            },
            "error": {"message": "Lexical error at line 1"},
            "warnings": []
        }
        result = map_compile_response(data)
        self.assertFalse(result.ok)
        self.assertIn("Lexical error", result.error)

    def test_nested_op_tree(self):
        """Test a realistic nested tree: Slice > Project > Order > Filter > LeftJoin."""
        data = {
            "ok": True,
            "phases": {
                "parsedQuery": {
                    "queryType": "SELECT", "projectVars": ["s"],
                    "sparqlForm": "QUERY", "limit": 10, "offset": 0,
                    "distinct": False, "reduced": False,
                    "orderBy": [{"direction": "ASC", "expr": "?s"}],
                    "groupBy": [], "having": []
                },
                "algebraCompiled": {
                    "op": {
                        "type": "OpSlice", "start": -9223372036854775808, "length": 10,
                        "subOp": {
                            "type": "OpProject", "vars": ["s"],
                            "subOp": {
                                "type": "OpOrder",
                                "conditions": [{"direction": "ASC",
                                                "expr": {"type": "ExprVar", "var": "s"}}],
                                "subOp": {
                                    "type": "OpFilter",
                                    "exprs": [{
                                        "type": "ExprFunction2", "name": "gt",
                                        "args": [
                                            {"type": "ExprVar", "var": "o"},
                                            {"type": "NodeValue", "node": {
                                                "type": "literal", "value": "5",
                                                "datatype": "http://www.w3.org/2001/XMLSchema#integer"
                                            }}
                                        ]
                                    }],
                                    "subOp": {
                                        "type": "OpLeftJoin",
                                        "left": {"type": "OpBGP", "triples": [{
                                            "subject": {"type": "var", "name": "s"},
                                            "predicate": {"type": "uri", "value": "http://ex.org/p"},
                                            "object": {"type": "var", "name": "o"}
                                        }]},
                                        "right": {"type": "OpBGP", "triples": [{
                                            "subject": {"type": "var", "name": "o"},
                                            "predicate": {"type": "uri", "value": "http://ex.org/q"},
                                            "object": {"type": "var", "name": "z"}
                                        }]},
                                        "exprs": []
                                    }
                                }
                            }
                        }
                    }
                },
                "updateOperations": None
            },
            "error": None, "warnings": []
        }
        result = map_compile_response(data)
        self.assertTrue(result.ok)
        # Walk the tree
        self.assertIsInstance(result.algebra, OpSlice)
        self.assertEqual(result.algebra.length, 10)
        proj = result.algebra.sub_op
        self.assertIsInstance(proj, OpProject)
        self.assertEqual(proj.vars, ["s"])
        order = proj.sub_op
        self.assertIsInstance(order, OpOrder)
        filt = order.sub_op
        self.assertIsInstance(filt, OpFilter)
        self.assertEqual(filt.exprs[0].name, "gt")
        lj = filt.sub_op
        self.assertIsInstance(lj, OpLeftJoin)
        self.assertIsInstance(lj.left, OpBGP)
        self.assertIsInstance(lj.right, OpBGP)


if __name__ == "__main__":
    unittest.main()
