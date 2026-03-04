"""
Unit tests for jena_sql_generator.py

Tests each Op→SQL translation using canned Op trees (no sidecar or DB needed).
Verifies the generated SQL is syntactically valid and structurally correct.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_types import *
from vitalgraph_sparql_sql.jena_sql_generator import (
    generate_sql, op_to_sql, expr_to_sql,
    SQLContext, AliasGenerator, SQLFragment,
    update_to_sql,
)

SPACE = "test_space"


def _ctx():
    """Fresh SQLContext for each test."""
    return SQLContext(space_id=SPACE)


# ---------------------------------------------------------------------------
# Helper: check SQL is parseable and contains expected fragments
# ---------------------------------------------------------------------------

def _assert_sql_contains(test_case, sql: str, *fragments: str):
    """Assert that every fragment appears in the generated SQL (case-insensitive)."""
    sql_lower = sql.lower()
    for frag in fragments:
        test_case.assertIn(
            frag.lower(), sql_lower,
            f"\nExpected fragment: {frag}\nNot found in SQL:\n{sql}"
        )


def _assert_sql_not_contains(test_case, sql: str, *fragments: str):
    sql_lower = sql.lower()
    for frag in fragments:
        test_case.assertNotIn(frag.lower(), sql_lower,
            f"\nUnexpected fragment: {frag}\nFound in SQL:\n{sql}")


# ===========================================================================
# AliasGenerator
# ===========================================================================

class TestAliasGenerator(unittest.TestCase):

    def test_sequential(self):
        g = AliasGenerator()
        self.assertEqual(g.next("q"), "q0")
        self.assertEqual(g.next("q"), "q1")
        self.assertEqual(g.next("t"), "t0")
        self.assertEqual(g.next("q"), "q2")
        self.assertEqual(g.next("t"), "t1")

    def test_different_prefixes(self):
        g = AliasGenerator()
        self.assertEqual(g.next("a"), "a0")
        self.assertEqual(g.next("b"), "b0")
        self.assertEqual(g.next("a"), "a1")


# ===========================================================================
# SQLContext
# ===========================================================================

class TestSQLContext(unittest.TestCase):

    def test_table_names(self):
        ctx = _ctx()
        self.assertEqual(ctx.quad_table, "test_space_rdf_quad")
        self.assertEqual(ctx.term_table, "test_space_term")

    def test_child_scope_shares_aliases(self):
        ctx = _ctx()
        a1 = ctx.aliases.next("q")
        child = ctx.child_scope()
        a2 = child.aliases.next("q")
        self.assertEqual(a1, "q0")
        self.assertEqual(a2, "q1")  # shared counter

    def test_child_scope_clones_bindings(self):
        ctx = _ctx()
        ctx.bind_var("s", "q0.subject_uuid", "t0")
        child = ctx.child_scope()
        child.bind_var("p", "q1.predicate_uuid", "t1")
        self.assertIn("s", child.bindings)
        self.assertNotIn("p", ctx.bindings)  # parent not affected

    def test_bind_var_returns_existing(self):
        ctx = _ctx()
        b1 = ctx.bind_var("x", "q0.subject_uuid", "t0")
        b2 = ctx.bind_var("x", "q1.object_uuid", "t99")
        self.assertIs(b1, b2)
        self.assertEqual(b2.uuid_col, "q0.subject_uuid")


# ===========================================================================
# OpBGP → SQL
# ===========================================================================

class TestOpBGP(unittest.TestCase):

    def test_single_triple_all_vars(self):
        """?s ?p ?o → one quad table, three term joins."""
        op = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=VarNode(name="p"),
                object=VarNode(name="o"),
            )
        ])
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- single_triple_all_vars ---")
        print(sql)
        _assert_sql_contains(self, sql,
            "test_space_rdf_quad",
            "test_space_term",
            "JOIN",
        )
        # All three vars should be exposed
        self.assertIn("s", frag.exposed_vars)
        self.assertIn("p", frag.exposed_vars)
        self.assertIn("o", frag.exposed_vars)

    def test_single_triple_with_uri_predicate(self):
        """?s <http://ex.org/name> ?o → predicate resolved via term_text filter."""
        op = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/name"),
                object=VarNode(name="o"),
            )
        ])
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- single_triple_uri_predicate ---")
        print(sql)
        _assert_sql_contains(self, sql,
            "http://ex.org/name",
            "term_type = 'U'",
        )

    def test_two_triples_shared_subject(self):
        """?s a <Type> . ?s <name> ?name → shared ?s creates join condition."""
        op = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                object=URINode(value="http://ex.org/Person"),
            ),
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/name"),
                object=VarNode(name="name"),
            ),
        ])
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- two_triples_shared_subject ---")
        print(sql)
        _assert_sql_contains(self, sql,
            "rdf-syntax-ns#type",
            "http://ex.org/name",
            "http://ex.org/person",  # case insensitive check
        )
        self.assertIn("name", frag.exposed_vars)

    def test_literal_object(self):
        """?s <p> "hello" → literal filter."""
        op = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/label"),
                object=LiteralNode(value="hello"),
            )
        ])
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- literal_object ---")
        print(sql)
        _assert_sql_contains(self, sql, "'hello'", "term_type = 'L'")

    def test_empty_bgp(self):
        op = OpBGP(triples=[])
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- empty_bgp ---")
        print(sql)
        _assert_sql_contains(self, sql, "select", "1")

    def test_graph_scoped_bgp(self):
        """Graph-scoped BGP should add context_uuid filter."""
        op = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=VarNode(name="p"),
                object=VarNode(name="o"),
            )
        ])
        ctx = _ctx()
        ctx.graph_uri = "urn:my_graph"
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- graph_scoped_bgp ---")
        print(sql)
        _assert_sql_contains(self, sql, "urn:my_graph", "context_uuid")


# ===========================================================================
# OpFilter → SQL
# ===========================================================================

class TestOpFilter(unittest.TestCase):

    def test_simple_filter(self):
        """FILTER(?o = <http://ex.org/Person>) on top of a BGP."""
        bgp = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=VarNode(name="p"),
                object=VarNode(name="o"),
            )
        ])
        op = OpFilter(
            exprs=[ExprFunction(name="eq", args=[
                ExprVar(var="o"),
                ExprValue(node=URINode(value="http://ex.org/Person")),
            ])],
            sub_op=bgp,
        )
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- simple_filter ---")
        print(sql)
        _assert_sql_contains(self, sql, "http://ex.org/person")


# ===========================================================================
# OpJoin / OpLeftJoin / OpUnion
# ===========================================================================

class TestJoins(unittest.TestCase):

    def _bgp_sp(self):
        return OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/type"),
                object=VarNode(name="type"),
            )
        ])

    def _bgp_name(self):
        return OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/name"),
                object=VarNode(name="name"),
            )
        ])

    def test_join(self):
        op = OpJoin(left=self._bgp_sp(), right=self._bgp_name())
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- join ---")
        print(sql)
        _assert_sql_contains(self, sql, "join")
        self.assertIn("type", frag.exposed_vars)
        self.assertIn("name", frag.exposed_vars)

    def test_left_join(self):
        op = OpLeftJoin(left=self._bgp_sp(), right=self._bgp_name(), exprs=[])
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- left_join ---")
        print(sql)
        _assert_sql_contains(self, sql, "left join")

    def test_union(self):
        op = OpUnion(left=self._bgp_sp(), right=self._bgp_name())
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- union ---")
        print(sql)
        _assert_sql_contains(self, sql, "union")


# ===========================================================================
# OpProject / OpSlice / OpDistinct / OpOrder
# ===========================================================================

class TestProjectSliceDistinctOrder(unittest.TestCase):

    def _base_op(self):
        """SELECT ?s ?name WHERE { ?s <type> ?type . ?s <name> ?name }"""
        return OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/type"),
                object=VarNode(name="type"),
            ),
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/name"),
                object=VarNode(name="name"),
            ),
        ])

    def test_project(self):
        op = OpProject(vars=["s", "name"], sub_op=self._base_op())
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- project ---")
        print(sql)
        # Should have "AS s" and "AS name"
        _assert_sql_contains(self, sql, "as s", "as name")
        # Should NOT have "type" in the projection
        self.assertIn("s", frag.exposed_vars)
        self.assertIn("name", frag.exposed_vars)

    def test_slice(self):
        op = OpSlice(start=10, length=20, sub_op=self._base_op())
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- slice ---")
        print(sql)
        _assert_sql_contains(self, sql, "limit", "offset")

    def test_distinct(self):
        op = OpDistinct(sub_op=self._base_op())
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- distinct ---")
        print(sql)
        _assert_sql_contains(self, sql, "distinct")

    def test_order_asc(self):
        op = OpOrder(
            conditions=[SortCondition(direction="ASC", expr=ExprVar(var="name"))],
            sub_op=self._base_op(),
        )
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- order_asc ---")
        print(sql)
        _assert_sql_contains(self, sql, "order by")

    def test_order_desc(self):
        op = OpOrder(
            conditions=[SortCondition(direction="DESC", expr=ExprVar(var="name"))],
            sub_op=self._base_op(),
        )
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- order_desc ---")
        print(sql)
        _assert_sql_contains(self, sql, "desc")


# ===========================================================================
# OpGroup / OpExtend
# ===========================================================================

class TestGroupExtend(unittest.TestCase):

    def test_group(self):
        bgp = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                object=VarNode(name="type"),
            )
        ])
        op = OpGroup(group_vars=["type"], aggregators=[], sub_op=bgp)
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- group ---")
        print(sql)
        _assert_sql_contains(self, sql, "group by")

    def test_extend(self):
        bgp = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=VarNode(name="p"),
                object=VarNode(name="o"),
            )
        ])
        op = OpExtend(
            var="label",
            expr=ExprFunction(name="concat", args=[
                ExprVar(var="s"),
                ExprValue(node=LiteralNode(value=" - ")),
                ExprVar(var="o"),
            ]),
            sub_op=bgp,
        )
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- extend ---")
        print(sql)
        self.assertIn("label", frag.exposed_vars)


# ===========================================================================
# OpGraph / OpMinus / OpNull
# ===========================================================================

class TestGraphMinusNull(unittest.TestCase):

    def test_graph(self):
        bgp = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=VarNode(name="p"),
                object=VarNode(name="o"),
            )
        ])
        op = OpGraph(graph_node=URINode(value="urn:test_graph"), sub_op=bgp)
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- graph ---")
        print(sql)
        _assert_sql_contains(self, sql, "urn:test_graph")

    def test_minus(self):
        left = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/p1"),
                object=VarNode(name="o"),
            )
        ])
        right = OpBGP(triples=[
            TriplePattern(
                subject=VarNode(name="s"),
                predicate=URINode(value="http://ex.org/p2"),
                object=VarNode(name="o"),
            )
        ])
        op = OpMinus(left=left, right=right)
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        print("--- minus ---")
        print(sql)
        _assert_sql_contains(self, sql, "except")

    def test_null(self):
        op = OpNull()
        ctx = _ctx()
        frag = op_to_sql(op, ctx)
        sql = frag.select.sql(dialect="postgres", pretty=True)
        self.assertIn("1", sql)


# ===========================================================================
# Expr → SQL
# ===========================================================================

class TestExprToSQL(unittest.TestCase):

    def test_expr_var(self):
        ctx = _ctx()
        ctx.bind_var("x", "q0.subject_uuid", "t0")
        result = expr_to_sql(ExprVar(var="x"), ctx)
        self.assertEqual(result, "t0.term_text")

    def test_expr_value_uri(self):
        ctx = _ctx()
        result = expr_to_sql(ExprValue(node=URINode(value="http://ex.org/foo")), ctx)
        self.assertEqual(result, "'http://ex.org/foo'")

    def test_expr_value_literal_int(self):
        ctx = _ctx()
        result = expr_to_sql(
            ExprValue(node=LiteralNode(value="42", datatype="http://www.w3.org/2001/XMLSchema#integer")),
            ctx
        )
        self.assertEqual(result, "42")

    def test_expr_value_literal_string(self):
        ctx = _ctx()
        result = expr_to_sql(
            ExprValue(node=LiteralNode(value="hello")),
            ctx
        )
        self.assertEqual(result, "'hello'")

    def test_binary_eq(self):
        ctx = _ctx()
        ctx.bind_var("x", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprFunction(name="eq", args=[
                ExprVar(var="x"),
                ExprValue(node=LiteralNode(value="test")),
            ]),
            ctx
        )
        self.assertIn("=", result)
        self.assertIn("t0.term_text", result)

    def test_bound(self):
        ctx = _ctx()
        ctx.bind_var("x", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprFunction(name="bound", args=[ExprVar(var="x")]),
            ctx
        )
        self.assertIn("IS NOT NULL", result)

    def test_isuri(self):
        ctx = _ctx()
        ctx.bind_var("x", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprFunction(name="isURI", args=[ExprVar(var="x")]),
            ctx
        )
        self.assertIn("term_type", result)
        self.assertIn("'U'", result)

    def test_contains(self):
        ctx = _ctx()
        ctx.bind_var("x", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprFunction(name="contains", args=[
                ExprVar(var="x"),
                ExprValue(node=LiteralNode(value="test")),
            ]),
            ctx
        )
        self.assertIn("POSITION", result)

    def test_regex(self):
        ctx = _ctx()
        ctx.bind_var("x", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprFunction(name="regex", args=[
                ExprVar(var="x"),
                ExprValue(node=LiteralNode(value="^test")),
                ExprValue(node=LiteralNode(value="i")),
            ]),
            ctx
        )
        self.assertIn("~*", result)

    def test_if(self):
        ctx = _ctx()
        result = expr_to_sql(
            ExprFunction(name="if", args=[
                ExprValue(node=LiteralNode(value="true", datatype="http://www.w3.org/2001/XMLSchema#boolean")),
                ExprValue(node=LiteralNode(value="yes")),
                ExprValue(node=LiteralNode(value="no")),
            ]),
            ctx
        )
        self.assertIn("CASE", result)
        self.assertIn("WHEN", result)
        self.assertIn("ELSE", result)

    def test_aggregator_count(self):
        ctx = _ctx()
        ctx.bind_var("s", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprAggregator(name="COUNT", distinct=False, expr=ExprVar(var="s")),
            ctx
        )
        self.assertEqual(result, "COUNT(t0.term_text)")

    def test_aggregator_count_distinct(self):
        ctx = _ctx()
        ctx.bind_var("s", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprAggregator(name="COUNT", distinct=True, expr=ExprVar(var="s")),
            ctx
        )
        self.assertEqual(result, "COUNT(DISTINCT t0.term_text)")

    def test_aggregator_group_concat(self):
        ctx = _ctx()
        ctx.bind_var("x", "q0.subject_uuid", "t0")
        result = expr_to_sql(
            ExprAggregator(name="GROUP_CONCAT", distinct=False, expr=ExprVar(var="x"), separator="; "),
            ctx
        )
        self.assertIn("STRING_AGG", result)


# ===========================================================================
# Update → SQL
# ===========================================================================

class TestUpdateToSQL(unittest.TestCase):

    def test_insert_data(self):
        op = UpdateDataInsert(quads=[
            QuadPattern(
                subject=URINode(value="http://ex.org/s"),
                predicate=URINode(value="http://ex.org/p"),
                object=LiteralNode(value="hello"),
                graph=URINode(value="urn:g1"),
            )
        ])
        ctx = _ctx()
        sql = update_to_sql(op, ctx)
        print("--- insert_data ---")
        print(sql)
        _assert_sql_contains(self, sql,
            "insert into",
            "test_space_rdf_quad",
            "http://ex.org/s",
            "http://ex.org/p",
            "hello",
            "urn:g1",
        )

    def test_delete_data(self):
        op = UpdateDataDelete(quads=[
            QuadPattern(
                graph=None,
                subject=URINode(value="http://ex.org/s"),
                predicate=URINode(value="http://ex.org/p"),
                object=LiteralNode(value="hello"),
            )
        ])
        ctx = _ctx()
        sql = update_to_sql(op, ctx)
        print("--- delete_data ---")
        print(sql)
        _assert_sql_contains(self, sql,
            "delete from",
            "test_space_rdf_quad",
            "http://ex.org/s",
        )


# ===========================================================================
# Full generate_sql() — realistic nested tree
# ===========================================================================

class TestGenerateSQL(unittest.TestCase):

    def test_select_s_p_o_limit_10(self):
        """SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"""
        tree = CompileResult(
            ok=True,
            meta=type('M', (), {'sparql_form': 'QUERY'})(),
            algebra=OpSlice(
                start=0,
                length=10,
                sub_op=OpProject(
                    vars=["s", "p", "o"],
                    sub_op=OpBGP(triples=[
                        TriplePattern(
                            subject=VarNode(name="s"),
                            predicate=VarNode(name="p"),
                            object=VarNode(name="o"),
                        )
                    ])
                )
            ),
            update_ops=None,
            error=None,
        )
        sql = generate_sql(tree, "lead_test")
        print("\n--- full SELECT ?s ?p ?o LIMIT 10 ---")
        print(sql)
        _assert_sql_contains(self, sql, "lead_test_rdf_quad", "lead_test_term", "limit")

    def test_select_distinct_with_filter(self):
        """SELECT DISTINCT ?s WHERE { ?s <type> ?t . FILTER(?t = <Person>) }"""
        tree = CompileResult(
            ok=True,
            meta=type('M', (), {'sparql_form': 'QUERY'})(),
            algebra=OpDistinct(
                sub_op=OpProject(
                    vars=["s"],
                    sub_op=OpFilter(
                        exprs=[ExprFunction(name="eq", args=[
                            ExprVar(var="t"),
                            ExprValue(node=URINode(value="http://ex.org/Person")),
                        ])],
                        sub_op=OpBGP(triples=[
                            TriplePattern(
                                subject=VarNode(name="s"),
                                predicate=URINode(value="http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                                object=VarNode(name="t"),
                            )
                        ])
                    )
                )
            ),
            update_ops=None,
            error=None,
        )
        sql = generate_sql(tree, "lead_test")
        print("\n--- full SELECT DISTINCT with FILTER ---")
        print(sql)
        _assert_sql_contains(self, sql, "distinct", "http://ex.org/person")

    def test_optional_pattern(self):
        """SELECT ?s ?name WHERE { ?s a <Type> . OPTIONAL { ?s <name> ?name } }"""
        tree = CompileResult(
            ok=True,
            meta=type('M', (), {'sparql_form': 'QUERY'})(),
            algebra=OpProject(
                vars=["s", "name"],
                sub_op=OpLeftJoin(
                    left=OpBGP(triples=[
                        TriplePattern(
                            subject=VarNode(name="s"),
                            predicate=URINode(value="http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                            object=URINode(value="http://ex.org/Thing"),
                        )
                    ]),
                    right=OpBGP(triples=[
                        TriplePattern(
                            subject=VarNode(name="s"),
                            predicate=URINode(value="http://ex.org/name"),
                            object=VarNode(name="name"),
                        )
                    ]),
                    exprs=[],
                )
            ),
            update_ops=None,
            error=None,
        )
        sql = generate_sql(tree, "lead_test")
        print("\n--- full OPTIONAL pattern ---")
        print(sql)
        _assert_sql_contains(self, sql, "left join")


if __name__ == "__main__":
    unittest.main(verbosity=2)
