#!/usr/bin/env python3
"""
Investigation of RDFLib SPARQL Parser for SQL Translation

This script explores RDFLib's SPARQL parsing capabilities to understand
the parse tree structure for translating SPARQL queries to SQL.
"""

import sys
import logging
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.sparql import Query
import pprint

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def analyze_sparql_parse_tree(sparql_query: str):
    """
    Parse a SPARQL query and analyze its structure for SQL translation.
    """
    print(f"\n{'='*60}")
    print(f"ANALYZING SPARQL QUERY:")
    print(f"{'='*60}")
    print(sparql_query)
    print(f"{'='*60}")
    
    try:
        # Step 1: Parse the query into a parse tree
        print("\n1. PARSING QUERY...")
        parsed_query = parseQuery(sparql_query)
        print(f"Parse tree type: {type(parsed_query)}")
        
        # Step 2: Translate to algebra
        print("\n2. TRANSLATING TO ALGEBRA...")
        algebra = translateQuery(parsed_query)
        print(f"Algebra type: {type(algebra)}")
        
        # Step 3: Analyze the algebra structure
        print("\n3. ALGEBRA STRUCTURE:")
        print("Raw algebra object:")
        pprint.pprint(algebra, width=100, depth=10)
        
        # Step 4: Extract key components
        print("\n4. KEY COMPONENTS:")
        analyze_algebra_components(algebra)
        
        # Step 5: Prepare query object for more analysis
        print("\n5. PREPARED QUERY ANALYSIS:")
        prepared_query = prepareQuery(sparql_query)
        print(f"Prepared query type: {type(prepared_query)}")
        if hasattr(prepared_query, 'algebra'):
            print("Prepared query has algebra attribute")
            analyze_algebra_components(prepared_query.algebra)
        
        return {
            'parsed': parsed_query,
            'algebra': algebra,
            'prepared': prepared_query
        }
        
    except Exception as e:
        print(f"ERROR parsing query: {e}")
        import traceback
        traceback.print_exc()
        return None

def analyze_algebra_components(algebra, depth=0):
    """
    Recursively analyze algebra components to understand structure.
    """
    indent = "  " * depth
    
    print(f"{indent}Analyzing: {type(algebra)}")
    
    # Handle different algebra types
    if hasattr(algebra, 'name'):
        print(f"{indent}Name: {algebra.name}")
    
    # For Query objects, look at the algebra attribute
    if hasattr(algebra, 'algebra'):
        print(f"{indent}Has algebra attribute: {type(algebra.algebra)}")
        if depth < 3:  # Prevent infinite recursion
            analyze_algebra_components(algebra.algebra, depth + 1)
    
    # For CompValue objects (common in RDFLib)
    if hasattr(algebra, 'name') and hasattr(algebra, 'get'):
        print(f"{indent}CompValue with name: {algebra.name}")
        
        # Common SPARQL algebra components
        components_to_check = ['p', 'p1', 'p2', 'expr', 'triples', 'vars', 'A', 'datasetClause']
        for comp in components_to_check:
            if comp in algebra:
                value = algebra[comp]
                print(f"{indent}{comp}: {type(value)} = {value}")
                
                # Recursively analyze sub-components
                if hasattr(value, 'name') or hasattr(value, 'algebra'):
                    if depth < 3:
                        analyze_algebra_components(value, depth + 1)
                elif isinstance(value, list) and value:
                    print(f"{indent}  List with {len(value)} items:")
                    for i, item in enumerate(value[:3]):  # Show first 3 items
                        print(f"{indent}    [{i}]: {type(item)} = {item}")
                        if hasattr(item, 'name') or hasattr(item, 'algebra'):
                            if depth < 2:
                                analyze_algebra_components(item, depth + 2)
    
    # For direct dictionary-like access
    if hasattr(algebra, 'keys'):
        keys = list(algebra.keys()) if hasattr(algebra, 'keys') else []
        if keys:
            print(f"{indent}Keys: {keys}")
    
    # Print all non-private attributes for debugging
    attrs = [attr for attr in dir(algebra) if not attr.startswith('_')]
    if attrs:
        print(f"{indent}All attributes: {attrs[:10]}{'...' if len(attrs) > 10 else ''}")

def main():
    """
    Test various SPARQL query patterns to understand parse tree structure.
    """
    
    # Test queries with increasing complexity
    test_queries = [
        # Basic triple pattern
        """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        """,
        
        # Specific predicate
        """
        SELECT ?s ?o WHERE {
            ?s <http://example.org/name> ?o .
        }
        """,
        
        # Filter with comparison
        """
        SELECT ?person ?age WHERE {
            ?person <http://example.org/age> ?age .
            FILTER(?age > 21)
        }
        """,
        
        # Regex filter
        """
        SELECT ?person ?name WHERE {
            ?person <http://example.org/name> ?name .
            FILTER(REGEX(?name, "John.*", "i"))
        }
        """,
        
        # Multiple patterns with OPTIONAL
        """
        SELECT ?person ?name ?age WHERE {
            ?person <http://example.org/name> ?name .
            OPTIONAL { ?person <http://example.org/age> ?age }
        }
        """,
        
        # UNION
        """
        SELECT ?person ?contact WHERE {
            {
                ?person <http://example.org/email> ?contact .
            } UNION {
                ?person <http://example.org/phone> ?contact .
            }
        }
        """,
        
        # Complex filter with multiple conditions
        """
        SELECT ?person ?name ?age WHERE {
            ?person <http://example.org/name> ?name .
            ?person <http://example.org/age> ?age .
            FILTER(?age > 18 && ?age < 65 && CONTAINS(?name, "Smith"))
        }
        """
    ]
    
    results = []
    for i, query in enumerate(test_queries, 1):
        print(f"\n\n{'#'*80}")
        print(f"TEST QUERY {i}")
        print(f"{'#'*80}")
        
        result = analyze_sparql_parse_tree(query.strip())
        results.append(result)
    
    print(f"\n\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Successfully parsed {len([r for r in results if r])} out of {len(results)} queries")
    
    return results

if __name__ == "__main__":
    main()
