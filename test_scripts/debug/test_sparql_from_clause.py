#!/usr/bin/env python3
"""
Test script to examine how RDFLib parses FROM clauses in SPARQL queries
"""

from rdflib.plugins.sparql import prepareQuery
import json

def test_from_clause_parsing():
    """Test how RDFLib parses FROM clauses"""
    
    # Test query with FROM clause
    sparql_query = """
    SELECT ?s ?p ?o
    FROM <urn:kgframe-wordnet-002>
    WHERE {
      ?s ?p ?o .
    }
    LIMIT 10
    OFFSET 0
    """
    
    print("=== SPARQL Query ===")
    print(sparql_query)
    print()
    
    # Parse with RDFLib
    prepared_query = prepareQuery(sparql_query)
    query_algebra = prepared_query.algebra
    
    print("=== Query Algebra Structure ===")
    print(f"Query type: {query_algebra.name}")
    print(f"Query attributes: {dir(query_algebra)}")
    print()
    
    # Check for dataset clauses
    if hasattr(query_algebra, 'datasetClause'):
        print(f"Dataset clause: {query_algebra.datasetClause}")
    
    # Check for FROM graphs
    if hasattr(query_algebra, 'from_'):
        print(f"FROM graphs: {query_algebra.from_}")
    
    # Check for other graph-related attributes
    for attr in ['dataset', 'defaultGraphs', 'namedGraphs', 'from_', 'datasetClause']:
        if hasattr(query_algebra, attr):
            value = getattr(query_algebra, attr)
            print(f"{attr}: {value}")
    
    print()
    print("=== Full Algebra Object ===")
    print(f"Algebra: {query_algebra}")
    
    # Try to access the dataset clause from the prepared query
    if hasattr(prepared_query, 'query'):
        print(f"Prepared query object: {prepared_query.query}")
        if hasattr(prepared_query.query, 'dataset'):
            print(f"Query dataset: {prepared_query.query.dataset}")
    
    print()
    print("=== Pattern Analysis ===")
    pattern = query_algebra.p
    print(f"Pattern type: {pattern.name}")
    print(f"Pattern attributes: {dir(pattern)}")

if __name__ == "__main__":
    test_from_clause_parsing()
