"""
SPARQL Helper Utilities for VitalGraph Mock Endpoints

This module provides common SPARQL operations used across multiple mock endpoints
to reduce code duplication and improve maintainability.
"""

import logging
from typing import Dict, Any, List, Optional


def check_object_exists_in_graph(space, uri: str, graph_id: str) -> bool:
    """
    Check if any object with the given URI exists as a subject in the specified graph.
    
    This function performs a simple SPARQL query to check if the given URI appears
    as a subject in any triple within the specified graph.
    
    Args:
        space: Mock space instance with pyoxigraph
        uri: URI to check for existence (should not include angle brackets)
        graph_id: Graph ID to search in
        
    Returns:
        bool: True if object exists as a subject, False otherwise
        
    Example:
        >>> exists = check_object_exists_in_graph(space, "http://example.org/entity1", "graph1")
        >>> print(exists)  # True or False
    """
    try:
        if graph_id:
            query = f"""
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{uri}> ?p ?o .
                }}
            }} LIMIT 1
            """
        else:
            query = f"""
            SELECT ?s WHERE {{
                <{uri}> ?p ?o .
            }} LIMIT 1
            """
        results = space.query_sparql(query)
        return len(results.get("bindings", [])) > 0
    except Exception:
        return False


def build_paginated_list_query(
    object_type: str, 
    graph_id: str, 
    page_size: int, 
    offset: int, 
    search_term: Optional[str] = None,
    additional_filters: Optional[List[str]] = None
) -> str:
    """
    Build a SPARQL query for paginated listing of objects with optional search.
    
    Args:
        object_type: The RDF type URI for the objects to list
        graph_id: Graph ID to search in
        page_size: Number of results per page
        offset: Offset for pagination
        search_term: Optional search term to filter by name/label
        additional_filters: Optional list of additional SPARQL filter clauses
        
    Returns:
        str: Complete SPARQL query string
    """
    # Base query structure
    where_clauses = [f"?subject a <{object_type}> ."]
    
    # Add search filter if provided
    if search_term:
        search_filter = f"""
        {{
            ?subject <http://vital.ai/ontology/vital-core#hasName> ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{search_term}")))
        }} UNION {{
            ?subject <http://www.w3.org/2000/01/rdf-schema#label> ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{search_term}")))
        }}
        """
        where_clauses.append(search_filter)
    
    # Add additional filters if provided
    if additional_filters:
        where_clauses.extend(additional_filters)
    
    # Build complete query
    where_clause = " ".join(where_clauses)
    
    query = f"""
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?subject ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            {where_clause}
            ?subject ?predicate ?object .
        }}
    }}
    ORDER BY ?subject
    LIMIT {page_size}
    OFFSET {offset}
    """
    
    return query.strip()


def build_count_query(object_type: str, graph_id: str, search_term: Optional[str] = None) -> str:
    """
    Build a SPARQL query to count objects of a specific type.
    
    Args:
        object_type: The RDF type URI for the objects to count
        graph_id: Graph ID to search in
        search_term: Optional search term to filter by name/label
        
    Returns:
        str: SPARQL COUNT query string
    """
    where_clauses = [f"?subject a <{object_type}> ."]
    
    # Add search filter if provided
    if search_term:
        search_filter = f"""
        {{
            ?subject <http://vital.ai/ontology/vital-core#hasName> ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{search_term}")))
        }} UNION {{
            ?subject <http://www.w3.org/2000/01/rdf-schema#label> ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{search_term}")))
        }}
        """
        where_clauses.append(search_filter)
    
    where_clause = " ".join(where_clauses)
    
    query = f"""
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
        GRAPH <{graph_id}> {{
            {where_clause}
        }}
    }}
    """
    
    return query.strip()


def execute_sparql_query_safe(space, query: str, logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """
    Execute a SPARQL query with error handling and logging.
    
    Args:
        space: Mock space instance with pyoxigraph
        query: SPARQL query string to execute
        logger: Optional logger instance for error reporting
        
    Returns:
        Dict[str, Any]: Query results with 'bindings' key, empty if error
    """
    try:
        if logger:
            logger.debug(f"Executing SPARQL query: {query[:200]}{'...' if len(query) > 200 else ''}")
        
        results = space.query_sparql(query)
        
        if logger:
            binding_count = len(results.get("bindings", []))
            logger.debug(f"SPARQL query returned {binding_count} bindings")
        
        return results
        
    except Exception as e:
        if logger:
            logger.error(f"Error executing SPARQL query: {e}")
            logger.debug(f"Failed query: {query}")
        return {"bindings": []}


def build_object_retrieval_query(uri: str, graph_id: str) -> str:
    """
    Build a SPARQL query to retrieve all properties of a specific object.
    
    Args:
        uri: URI of the object to retrieve
        graph_id: Graph ID to search in
        
    Returns:
        str: SPARQL query string
    """
    query = f"""
    SELECT ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            <{uri}> ?predicate ?object .
        }}
    }}
    ORDER BY ?predicate
    """
    
    return query.strip()


def build_grouping_uri_query(grouping_uri: str, graph_id: str) -> str:
    """
    Build a SPARQL query to retrieve all objects with a specific grouping URI.
    
    Args:
        grouping_uri: The grouping URI to filter by
        graph_id: Graph ID to search in
        
    Returns:
        str: SPARQL query string
    """
    query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    
    SELECT ?subject ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            ?subject haley:hasKGGraphURI <{grouping_uri}> .
            ?subject ?predicate ?object .
        }}
    }}
    ORDER BY ?subject ?predicate
    """
    
    return query.strip()
