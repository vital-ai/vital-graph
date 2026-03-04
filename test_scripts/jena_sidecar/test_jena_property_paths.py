"""
Unit tests for property path support:
  - Path string parsing (jena_ast_mapper.parse_path_string)
  - OpPath AST mapping
  - SQL generation (collect → resolve → emit)
"""

import sys, os, unittest

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_types import (
    VarNode, URINode, OpPath,
    PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne, PathNegPropSet,
)
from vitalgraph_sparql_sql.jena_ast_mapper import (
    parse_path_string, map_op,
)
from vitalgraph_sparql_sql.jena_sql_ir import AliasGenerator
from vitalgraph_sparql_sql.jena_sql_collect import collect
from vitalgraph_sparql_sql.jena_sql_resolve import resolve
from vitalgraph_sparql_sql.jena_sql_emit import emit

SPACE_ID = "test_space"


# ===========================================================================
# Path string parser tests
# ===========================================================================

class TestPathParsing(unittest.TestCase):

    def test_simple_link(self):
        p = parse_path_string("<http://example.org/knows>")
        self.assertIsInstance(p, PathLink)
        self.assertEqual(p.uri, "http://example.org/knows")

    def test_one_or_more(self):
        p = parse_path_string("<http://example.org/knows>+")
        self.assertIsInstance(p, PathOneOrMore)
        self.assertIsInstance(p.sub, PathLink)
        self.assertEqual(p.sub.uri, "http://example.org/knows")

    def test_zero_or_more(self):
        p = parse_path_string("<http://example.org/knows>*")
        self.assertIsInstance(p, PathZeroOrMore)
        self.assertIsInstance(p.sub, PathLink)

    def test_zero_or_one(self):
        p = parse_path_string("<http://example.org/knows>?")
        self.assertIsInstance(p, PathZeroOrOne)
        self.assertIsInstance(p.sub, PathLink)

    def test_inverse(self):
        p = parse_path_string("^<http://example.org/knows>")
        self.assertIsInstance(p, PathInverse)
        self.assertIsInstance(p.sub, PathLink)
        self.assertEqual(p.sub.uri, "http://example.org/knows")

    def test_sequence(self):
        p = parse_path_string("<http://example.org/a>/<http://example.org/b>")
        self.assertIsInstance(p, PathSeq)
        self.assertIsInstance(p.left, PathLink)
        self.assertIsInstance(p.right, PathLink)
        self.assertEqual(p.left.uri, "http://example.org/a")
        self.assertEqual(p.right.uri, "http://example.org/b")

    def test_alternative(self):
        p = parse_path_string("<http://example.org/a>|<http://example.org/b>")
        self.assertIsInstance(p, PathAlt)
        self.assertIsInstance(p.left, PathLink)
        self.assertIsInstance(p.right, PathLink)

    def test_composite_one_or_more(self):
        # (<a>/<b>)+ — sequence inside one-or-more
        p = parse_path_string("(<http://example.org/a>/<http://example.org/b>)+")
        self.assertIsInstance(p, PathOneOrMore)
        self.assertIsInstance(p.sub, PathSeq)

    def test_inverse_one_or_more(self):
        p = parse_path_string("^<http://example.org/knows>+")
        # ^ binds tighter: this is (^<knows>)+  — Jena writes ^<uri>+
        # Our parser: ^ applies to primary, then + applies to result
        # Actually: _parse_unary sees ^, recurses, the inner _parse_unary
        # sees <uri> then +, so we get PathInverse(PathOneOrMore(PathLink))
        # Wait — ^ is parsed first, then the suffix + applies to the result of ^
        # Let me re-check: _parse_unary starts with ^, calls _parse_unary on rest
        # Inner _parse_unary sees <uri>, then _parse_primary returns PathLink
        # Then checks for +, finds it, returns PathOneOrMore(PathLink)
        # So outer gets PathInverse(PathOneOrMore(PathLink))
        self.assertIsInstance(p, PathInverse)
        self.assertIsInstance(p.sub, PathOneOrMore)
        self.assertIsInstance(p.sub.sub, PathLink)

    def test_negated_single(self):
        p = parse_path_string("!<http://example.org/a>")
        self.assertIsInstance(p, PathNegPropSet)
        self.assertEqual(p.uris, ["http://example.org/a"])

    def test_negated_multi(self):
        p = parse_path_string("!(<http://example.org/a>|<http://example.org/b>)")
        self.assertIsInstance(p, PathNegPropSet)
        self.assertEqual(len(p.uris), 2)
        self.assertIn("http://example.org/a", p.uris)
        self.assertIn("http://example.org/b", p.uris)

    def test_three_step_sequence(self):
        p = parse_path_string("<http://a>/<http://b>/<http://c>")
        # Should be PathSeq(PathSeq(a, b), c) due to left-associativity
        self.assertIsInstance(p, PathSeq)
        self.assertIsInstance(p.left, PathSeq)
        self.assertIsInstance(p.right, PathLink)
        self.assertEqual(p.right.uri, "http://c")

    def test_alt_with_sequence(self):
        # alt binds looser than seq: <a>/<b>|<c> = (<a>/<b>) | <c>
        p = parse_path_string("<http://a>/<http://b>|<http://c>")
        self.assertIsInstance(p, PathAlt)
        self.assertIsInstance(p.left, PathSeq)
        self.assertIsInstance(p.right, PathLink)


# ===========================================================================
# OpPath AST mapping tests
# ===========================================================================

class TestOpPathMapping(unittest.TestCase):

    def test_map_op_path_simple(self):
        json_op = {
            "type": "OpPath",
            "triplePath": {
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "path", "value": "<http://example.org/knows>+"},
                "object": {"type": "var", "name": "o"},
            }
        }
        op = map_op(json_op)
        self.assertIsInstance(op, OpPath)
        self.assertIsInstance(op.subject, VarNode)
        self.assertEqual(op.subject.name, "s")
        self.assertIsInstance(op.object, VarNode)
        self.assertEqual(op.object.name, "o")
        self.assertIsInstance(op.path, PathOneOrMore)
        self.assertIsInstance(op.path.sub, PathLink)
        self.assertEqual(op.path.sub.uri, "http://example.org/knows")

    def test_map_op_path_sequence(self):
        json_op = {
            "type": "OpPath",
            "triplePath": {
                "subject": {"type": "var", "name": "x"},
                "predicate": {"type": "path", "value": "<http://a>/<http://b>"},
                "object": {"type": "var", "name": "y"},
            }
        }
        op = map_op(json_op)
        self.assertIsInstance(op, OpPath)
        self.assertIsInstance(op.path, PathSeq)

    def test_map_op_path_with_uri_subject(self):
        json_op = {
            "type": "OpPath",
            "triplePath": {
                "subject": {"type": "uri", "value": "http://example.org/Alice"},
                "predicate": {"type": "path", "value": "<http://example.org/knows>*"},
                "object": {"type": "var", "name": "person"},
            }
        }
        op = map_op(json_op)
        self.assertIsInstance(op, OpPath)
        self.assertIsInstance(op.subject, URINode)
        self.assertEqual(op.subject.value, "http://example.org/Alice")
        self.assertIsInstance(op.path, PathZeroOrMore)


# ===========================================================================
# SQL generation tests (collect → resolve → emit)
# ===========================================================================

class TestPathSQLGeneration(unittest.TestCase):

    def _gen_sql(self, op):
        aliases = AliasGenerator()
        plan = collect(op, SPACE_ID, aliases)
        resolved = resolve(plan, SPACE_ID, aliases)
        return emit(resolved, SPACE_ID)

    def test_simple_link_sql(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathLink(uri="http://example.org/knows"),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("start_uuid", sql)
        self.assertIn("end_uuid", sql)
        self.assertIn("predicate_uuid", sql)
        self.assertIn("term_text", sql)
        self.assertIn(SPACE_ID, sql)

    def test_one_or_more_generates_recursive_cte(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathOneOrMore(sub=PathLink(uri="http://example.org/knows")),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("WITH RECURSIVE", sql)
        self.assertIn("depth", sql)
        self.assertIn("UNION", sql)
        self.assertIn("DISTINCT", sql)

    def test_zero_or_more_generates_recursive_cte(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathZeroOrMore(sub=PathLink(uri="http://example.org/knows")),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("WITH RECURSIVE", sql)
        # Zero-or-more includes identity (start = end)
        self.assertIn("subject_uuid AS start_uuid, q.subject_uuid AS end_uuid", sql)

    def test_zero_or_one_no_recursive(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathZeroOrOne(sub=PathLink(uri="http://example.org/knows")),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        # Should NOT have WITH RECURSIVE — just UNION of identity and one step
        self.assertNotIn("WITH RECURSIVE", sql)
        self.assertIn("UNION", sql)

    def test_sequence_generates_join(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathSeq(
                left=PathLink(uri="http://example.org/a"),
                right=PathLink(uri="http://example.org/b"),
            ),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("lp.start_uuid", sql)
        self.assertIn("rp.end_uuid", sql)
        self.assertIn("JOIN", sql)

    def test_alternative_generates_union(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathAlt(
                left=PathLink(uri="http://example.org/a"),
                right=PathLink(uri="http://example.org/b"),
            ),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("UNION", sql)

    def test_inverse_swaps_columns(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathInverse(sub=PathLink(uri="http://example.org/knows")),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("inv.end_uuid AS start_uuid", sql)
        self.assertIn("inv.start_uuid AS end_uuid", sql)

    def test_negated_prop_set(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathNegPropSet(uris=["http://example.org/a", "http://example.org/b"]),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("!=", sql)
        self.assertIn("http://example.org/a", sql)
        self.assertIn("http://example.org/b", sql)

    def test_uri_subject_constraint(self):
        op = OpPath(
            subject=URINode(value="http://example.org/Alice"),
            path=PathOneOrMore(sub=PathLink(uri="http://example.org/knows")),
            object=VarNode(name="person"),
        )
        sql = self._gen_sql(op)
        self.assertIn("http://example.org/Alice", sql)
        self.assertIn("start_uuid =", sql)

    def test_uri_object_constraint(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathOneOrMore(sub=PathLink(uri="http://example.org/knows")),
            object=URINode(value="http://example.org/Bob"),
        )
        sql = self._gen_sql(op)
        self.assertIn("http://example.org/Bob", sql)
        self.assertIn("end_uuid =", sql)

    def test_graph_scoping(self):
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathLink(uri="http://example.org/knows"),
            object=VarNode(name="o"),
        )
        aliases = AliasGenerator()
        plan = collect(op, SPACE_ID, aliases, graph_uri="http://example.org/graph1")
        resolved = resolve(plan, SPACE_ID, aliases)
        sql = emit(resolved, SPACE_ID)
        self.assertIn("context_uuid", sql)
        self.assertIn("http://example.org/graph1", sql)

    def test_composite_path_recursive_seq_plus(self):
        # (<a>/<b>)+ — sequence inside one-or-more
        op = OpPath(
            subject=VarNode(name="s"),
            path=PathOneOrMore(sub=PathSeq(
                left=PathLink(uri="http://example.org/a"),
                right=PathLink(uri="http://example.org/b"),
            )),
            object=VarNode(name="o"),
        )
        sql = self._gen_sql(op)
        self.assertIn("WITH RECURSIVE", sql)
        self.assertIn("lp.start_uuid", sql)  # sequence join inside the CTE


# ===========================================================================
# End-to-end: map_op → SQL
# ===========================================================================

class TestEndToEnd(unittest.TestCase):

    def test_full_pipeline_from_json(self):
        """Test the complete pipeline: JSON → OpPath → SQL."""
        json_op = {
            "type": "OpPath",
            "triplePath": {
                "subject": {"type": "var", "name": "s"},
                "predicate": {"type": "path", "value": "<http://example.org/knows>+"},
                "object": {"type": "var", "name": "o"},
            }
        }
        op = map_op(json_op)
        aliases = AliasGenerator()
        plan = collect(op, SPACE_ID, aliases)
        resolved = resolve(plan, SPACE_ID, aliases)
        sql = emit(resolved, SPACE_ID)
        self.assertIn("WITH RECURSIVE", sql)
        self.assertIn("term_text", sql)
        # Should produce valid-looking SQL with no obvious errors
        self.assertNotIn("None", sql)
        self.assertNotIn("NULL AS start_uuid", sql)


if __name__ == "__main__":
    unittest.main()
