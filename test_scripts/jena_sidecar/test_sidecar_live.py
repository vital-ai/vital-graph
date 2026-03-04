"""
Live integration test: send real SPARQL through the sidecar,
map the response to Python types, and verify the result tree.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sidecar_client import SidecarClient
from vitalgraph_sparql_sql.jena_ast_mapper import map_compile_response
from vitalgraph_sparql_sql.jena_types import *

QUERIES = [
    # (label, sparql, expected_top_op_type, expected_form)
    (
        "Simple SELECT",
        "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10",
        OpSlice,
        "QUERY",
    ),
    (
        "SELECT DISTINCT with FILTER",
        """SELECT DISTINCT ?s WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> ?t .
            FILTER(?t = <http://vital.ai/ontology/haley-ai-kg#KGEntity>)
        }""",
        OpDistinct,
        "QUERY",
    ),
    (
        "SELECT with OPTIONAL and ORDER BY",
        """SELECT ?s ?name WHERE {
            ?s a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            OPTIONAL { ?s <http://vital.ai/ontology/vital-core#hasName> ?name }
        } ORDER BY ?name LIMIT 20""",
        OpSlice,
        "QUERY",
    ),
    (
        "SELECT with UNION",
        """SELECT ?s WHERE {
            { ?s a <http://vital.ai/ontology/haley-ai-kg#KGTextSlot> }
            UNION
            { ?s a <http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot> }
        } LIMIT 5""",
        OpSlice,
        "QUERY",
    ),
    (
        "GROUP BY with COUNT",
        """SELECT ?type (COUNT(?s) AS ?count) WHERE {
            ?s a ?type
        } GROUP BY ?type ORDER BY DESC(?count) LIMIT 10""",
        OpSlice,
        "QUERY",
    ),
    (
        "GRAPH scoped query",
        """SELECT ?s ?p ?o WHERE {
            GRAPH <urn:lead_test> { ?s ?p ?o }
        } LIMIT 5""",
        OpSlice,
        "QUERY",
    ),
    (
        "INSERT DATA",
        'INSERT DATA { <http://ex.org/s> <http://ex.org/p> "hello" }',
        None,  # no algebra for updates
        "UPDATE",
    ),
    (
        "DELETE/INSERT WHERE",
        """DELETE { ?s <http://ex.org/old> ?o }
           INSERT { ?s <http://ex.org/new> ?o }
           WHERE  { ?s <http://ex.org/old> ?o }""",
        None,
        "UPDATE",
    ),
    (
        "CONSTRUCT",
        """CONSTRUCT { ?s ?p ?o } WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            ?s ?p ?o
        } LIMIT 10""",
        OpSlice,
        "QUERY",
    ),
    (
        "ASK",
        """ASK WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/haley-ai-kg#KGEntity>
        }""",
        OpBGP,  # ASK typically compiles to just the BGP
        "QUERY",
    ),
]

def main():
    passed = 0
    failed = 0

    print("=" * 70)
    print("Live Sidecar + AST Mapper Integration Tests")
    print("=" * 70)

    with SidecarClient() as client:
        for label, sparql, expected_top_type, expected_form in QUERIES:
            print(f"\n--- {label} ---")
            try:
                raw = client.compile(sparql)
                result = map_compile_response(raw)

                # Check ok
                if not result.ok:
                    print(f"  FAIL: ok=False, error={result.error}")
                    failed += 1
                    continue

                # Check form
                if result.meta.sparql_form != expected_form:
                    print(f"  FAIL: expected form={expected_form}, got {result.meta.sparql_form}")
                    failed += 1
                    continue

                # Check top-level type
                if expected_form == "QUERY":
                    if result.algebra is None:
                        print(f"  FAIL: algebra is None for QUERY")
                        failed += 1
                        continue
                    if expected_top_type and not isinstance(result.algebra, expected_top_type):
                        print(f"  FAIL: expected {expected_top_type.__name__}, got {type(result.algebra).__name__}")
                        failed += 1
                        continue
                    print(f"  OK: algebra={type(result.algebra).__name__}")
                    # Print tree summary
                    _print_tree(result.algebra, indent=2)
                else:
                    if not result.update_ops:
                        print(f"  FAIL: no update_ops for UPDATE")
                        failed += 1
                        continue
                    print(f"  OK: {len(result.update_ops)} update op(s)")
                    for i, u in enumerate(result.update_ops):
                        print(f"    [{i}] {type(u).__name__}")

                passed += 1

            except Exception as e:
                print(f"  FAIL: {e}")
                failed += 1

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'=' * 70}")
    return 0 if failed == 0 else 1


def _print_tree(op, indent=0):
    """Print a compact tree representation of an Op."""
    prefix = "  " * indent
    name = type(op).__name__
    extra = ""
    if isinstance(op, OpSlice):
        extra = f" start={op.start} length={op.length}"
        print(f"{prefix}{name}{extra}")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpProject):
        extra = f" vars={op.vars}"
        print(f"{prefix}{name}{extra}")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpDistinct):
        print(f"{prefix}{name}")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpReduced):
        print(f"{prefix}{name}")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpOrder):
        dirs = [f"{c.direction}" for c in op.conditions]
        print(f"{prefix}{name} [{', '.join(dirs)}]")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpFilter):
        names = [e.name if isinstance(e, ExprFunction) else type(e).__name__ for e in op.exprs]
        print(f"{prefix}{name} [{', '.join(names)}]")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpBGP):
        print(f"{prefix}{name} ({len(op.triples)} triple(s))")
    elif isinstance(op, OpLeftJoin):
        print(f"{prefix}{name}")
        _print_tree(op.left, indent + 1)
        _print_tree(op.right, indent + 1)
    elif isinstance(op, OpJoin):
        print(f"{prefix}{name}")
        _print_tree(op.left, indent + 1)
        _print_tree(op.right, indent + 1)
    elif isinstance(op, OpUnion):
        print(f"{prefix}{name}")
        _print_tree(op.left, indent + 1)
        _print_tree(op.right, indent + 1)
    elif isinstance(op, OpGraph):
        g = op.graph_node.value if isinstance(op.graph_node, URINode) else str(op.graph_node)
        print(f"{prefix}{name} <{g}>")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpGroup):
        print(f"{prefix}{name} vars={op.group_vars}")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpExtend):
        print(f"{prefix}{name} ?{op.var}")
        _print_tree(op.sub_op, indent + 1)
    elif isinstance(op, OpMinus):
        print(f"{prefix}{name}")
        _print_tree(op.left, indent + 1)
        _print_tree(op.right, indent + 1)
    else:
        print(f"{prefix}{name}")


if __name__ == "__main__":
    sys.exit(main())
