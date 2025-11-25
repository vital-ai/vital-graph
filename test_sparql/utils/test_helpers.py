"""Test Helper Functions

Utility functions to support SPARQL package testing.
"""

import logging
from typing import Dict, List, Any, Set
from vitalgraph.sparql.triple_store import TemporaryTripleStore


def setup_test_logging():
    """Set up logging for tests."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def create_test_store_with_data(document: Dict[str, Any]) -> TemporaryTripleStore:
    """Create a test triple store and load it with data.
    
    Args:
        document: JSON-LD document to load
        
    Returns:
        Loaded TemporaryTripleStore instance
    """
    store = TemporaryTripleStore()
    store.load_jsonld_document(document)
    return store


def count_triples_by_subject(triples: List[Dict[str, str]]) -> Dict[str, int]:
    """Count triples grouped by subject.
    
    Args:
        triples: List of triple dictionaries
        
    Returns:
        Dict mapping subject URIs to triple counts
    """
    counts = {}
    for triple in triples:
        subject = triple.get('subject', 'unknown')
        counts[subject] = counts.get(subject, 0) + 1
    return counts


def extract_subjects_from_graph(graph_data: Dict[str, List]) -> Set[str]:
    """Extract all unique subjects from separated graph data.
    
    Args:
        graph_data: Graph data with categorized triples
        
    Returns:
        Set of unique subject URIs
    """
    subjects = set()
    for category_triples in graph_data.values():
        for triple in category_triples:
            if 'subject' in triple:
                subjects.add(triple['subject'])
    return subjects


def validate_graph_structure(graph_data: Dict[str, List], expected_categories: List[str]) -> bool:
    """Validate that graph data has expected structure.
    
    Args:
        graph_data: Graph data to validate
        expected_categories: List of expected category keys
        
    Returns:
        True if structure is valid
    """
    # Check that all expected categories are present
    for category in expected_categories:
        if category not in graph_data:
            return False
    
    # Check that all values are lists
    for category, triples in graph_data.items():
        if not isinstance(triples, list):
            return False
        
        # Check that each triple has required fields
        for triple in triples:
            if not isinstance(triple, dict):
                return False
            if not all(key in triple for key in ['subject', 'predicate', 'object']):
                return False
    
    return True


def find_triples_with_predicate(triples: List[Dict[str, str]], predicate_uri: str) -> List[Dict[str, str]]:
    """Find all triples with a specific predicate.
    
    Args:
        triples: List of triple dictionaries
        predicate_uri: Predicate URI to search for
        
    Returns:
        List of matching triples
    """
    return [triple for triple in triples if triple.get('predicate') == predicate_uri]


def find_triples_with_subject(triples: List[Dict[str, str]], subject_uri: str) -> List[Dict[str, str]]:
    """Find all triples with a specific subject.
    
    Args:
        triples: List of triple dictionaries
        subject_uri: Subject URI to search for
        
    Returns:
        List of matching triples
    """
    return [triple for triple in triples if triple.get('subject') == subject_uri]


def assert_no_duplicate_subjects_across_graphs(separated_graphs: Dict[str, Dict[str, List]]) -> bool:
    """Assert that no subject appears in multiple entity/frame graphs.
    
    Args:
        separated_graphs: Dict of separated graphs
        
    Returns:
        True if no duplicates found
        
    Raises:
        AssertionError: If duplicate subjects are found
    """
    all_subjects = set()
    
    for graph_uri, graph_data in separated_graphs.items():
        graph_subjects = extract_subjects_from_graph(graph_data)
        
        # Check for overlaps
        overlap = all_subjects & graph_subjects
        if overlap:
            raise AssertionError(f"Duplicate subjects found across graphs: {overlap}")
        
        all_subjects.update(graph_subjects)
    
    return True


def count_total_triples(graph_data: Dict[str, List]) -> int:
    """Count total number of triples in graph data.
    
    Args:
        graph_data: Graph data with categorized triples
        
    Returns:
        Total number of triples
    """
    return sum(len(triples) for triples in graph_data.values())


def extract_uris_by_type(document: Dict[str, Any], rdf_type: str) -> List[str]:
    """Extract URIs of objects with specific RDF type from JSON-LD document.
    
    Args:
        document: JSON-LD document
        rdf_type: RDF type to filter by (e.g., "haley:KGEntity")
        
    Returns:
        List of URIs with the specified type
    """
    uris = []
    
    for obj in document.get('@graph', []):
        if isinstance(obj, dict):
            obj_type = obj.get('@type')
            if obj_type == rdf_type:
                obj_id = obj.get('@id')
                if obj_id:
                    uris.append(obj_id)
    
    return uris


def create_minimal_jsonld_document(objects: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a minimal JSON-LD document with given objects.
    
    Args:
        objects: List of object dictionaries
        
    Returns:
        JSON-LD document
    """
    return {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital-core": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        "@graph": objects
    }


def validate_sparql_query_syntax(query: str) -> bool:
    """Basic validation of SPARQL query syntax.
    
    Args:
        query: SPARQL query string
        
    Returns:
        True if query appears to have valid syntax
    """
    # Basic checks
    query_upper = query.upper()
    
    # Must contain SELECT, CONSTRUCT, ASK, or DESCRIBE
    if not any(keyword in query_upper for keyword in ['SELECT', 'CONSTRUCT', 'ASK', 'DESCRIBE']):
        return False
    
    # Must contain WHERE clause for most queries
    if 'SELECT' in query_upper or 'CONSTRUCT' in query_upper:
        if 'WHERE' not in query_upper:
            return False
    
    # Check for balanced braces
    open_braces = query.count('{')
    close_braces = query.count('}')
    if open_braces != close_braces:
        return False
    
    return True


def compare_query_results(results1: List[Dict], results2: List[Dict]) -> bool:
    """Compare two sets of SPARQL query results for equality.
    
    Args:
        results1: First set of results
        results2: Second set of results
        
    Returns:
        True if results are equivalent
    """
    if len(results1) != len(results2):
        return False
    
    # Convert to sets of tuples for comparison (order-independent)
    def result_to_tuple(result):
        return tuple(sorted(result.items()))
    
    set1 = {result_to_tuple(r) for r in results1}
    set2 = {result_to_tuple(r) for r in results2}
    
    return set1 == set2


def mock_sparql_result(variable_bindings: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """Create a mock SPARQL result with variable bindings.
    
    Args:
        variable_bindings: Dict mapping variable names to values
        
    Returns:
        Mock SPARQL result dictionary
    """
    result = {}
    for var, value in variable_bindings.items():
        result[var] = {
            'type': 'uri' if value.startswith('http') else 'literal',
            'value': value
        }
    return result
