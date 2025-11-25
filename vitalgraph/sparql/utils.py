"""SPARQL Utilities

Utility functions for SPARQL operations in the KG context.
"""

import logging
from typing import Dict, List, Any, Optional
import uuid

logger = logging.getLogger(__name__)


def generate_graph_uri(base_uri: str, graph_type: str = "kg") -> str:
    """Generate a graph URI for hasKGGraphURI or hasFrameGraphURI properties.
    
    Args:
        base_uri: Base URI of the entity or frame
        graph_type: Type of graph ("kg" for entity graphs, "frame" for frame graphs)
        
    Returns:
        Generated graph URI
    """
    if graph_type == "kg":
        return f"{base_uri}/kg-graph"
    elif graph_type == "frame":
        return f"{base_uri}/frame-graph"
    else:
        return f"{base_uri}/{graph_type}-graph"


def extract_uri_from_sparql_result(result: Dict[str, Any], variable_name: str) -> Optional[str]:
    """Extract URI value from SPARQL query result.
    
    Args:
        result: SPARQL result dictionary
        variable_name: Name of the variable to extract
        
    Returns:
        URI string or None if not found
    """
    if variable_name in result:
        var_data = result[variable_name]
        if isinstance(var_data, dict) and 'value' in var_data:
            return var_data['value']
        elif isinstance(var_data, str):
            return var_data
    return None


def build_prefixes() -> str:
    """Build standard SPARQL prefixes for KG operations.
    
    Returns:
        SPARQL prefix declarations
    """
    return """
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    """


def escape_sparql_string(value: str) -> str:
    """Escape a string value for use in SPARQL queries.
    
    Args:
        value: String value to escape
        
    Returns:
        Escaped string safe for SPARQL
    """
    # Escape quotes and backslashes
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def build_graph_clause(graph_id: Optional[str]) -> str:
    """Build GRAPH clause for SPARQL queries.
    
    Args:
        graph_id: Graph ID to query, or None for default graph
        
    Returns:
        GRAPH clause string or empty string
    """
    if graph_id:
        return f"GRAPH <{graph_id}> {{"
    else:
        return ""


def close_graph_clause(graph_id: Optional[str]) -> str:
    """Close GRAPH clause for SPARQL queries.
    
    Args:
        graph_id: Graph ID that was opened, or None
        
    Returns:
        Closing brace or empty string
    """
    if graph_id:
        return "}"
    else:
        return ""


def validate_uri(uri: str) -> bool:
    """Validate that a string is a valid URI.
    
    Args:
        uri: URI string to validate
        
    Returns:
        True if valid URI
    """
    try:
        # Basic URI validation - should start with http:// or https://
        return uri.startswith(('http://', 'https://')) and len(uri) > 10
    except Exception:
        return False


def generate_unique_uri(base_namespace: str, prefix: str = "item") -> str:
    """Generate a unique URI with UUID.
    
    Args:
        base_namespace: Base namespace for the URI
        prefix: Prefix for the item name
        
    Returns:
        Unique URI string
    """
    unique_id = str(uuid.uuid4())
    return f"{base_namespace.rstrip('/')}/{prefix}-{unique_id}"


def count_triples_by_type(triples: List[Dict[str, str]]) -> Dict[str, int]:
    """Count triples by their predicate types.
    
    Args:
        triples: List of triple dictionaries
        
    Returns:
        Dict mapping predicate URIs to counts
    """
    counts = {}
    for triple in triples:
        predicate = triple.get('predicate', 'unknown')
        counts[predicate] = counts.get(predicate, 0) + 1
    return counts


def filter_triples_by_predicate(triples: List[Dict[str, str]], predicate_uri: str) -> List[Dict[str, str]]:
    """Filter triples by predicate URI.
    
    Args:
        triples: List of triple dictionaries
        predicate_uri: Predicate URI to filter by
        
    Returns:
        Filtered list of triples
    """
    return [triple for triple in triples if triple.get('predicate') == predicate_uri]


def get_subjects_from_triples(triples: List[Dict[str, str]]) -> List[str]:
    """Extract unique subject URIs from triples.
    
    Args:
        triples: List of triple dictionaries
        
    Returns:
        List of unique subject URIs
    """
    subjects = set()
    for triple in triples:
        if 'subject' in triple:
            subjects.add(triple['subject'])
    return list(subjects)


def get_objects_from_triples(triples: List[Dict[str, str]]) -> List[str]:
    """Extract unique object values from triples.
    
    Args:
        triples: List of triple dictionaries
        
    Returns:
        List of unique object values
    """
    objects = set()
    for triple in triples:
        if 'object' in triple:
            objects.add(triple['object'])
    return list(objects)


def build_values_clause(variable: str, values: List[str]) -> str:
    """Build SPARQL VALUES clause for a list of values.
    
    Args:
        variable: Variable name (without ?)
        values: List of values to include
        
    Returns:
        SPARQL VALUES clause
    """
    if not values:
        return ""
    
    # Escape and format values
    formatted_values = []
    for value in values:
        if validate_uri(value):
            formatted_values.append(f"<{value}>")
        else:
            formatted_values.append(escape_sparql_string(value))
    
    values_str = " ".join(formatted_values)
    return f"VALUES ?{variable} {{ {values_str} }}"


def build_union_query(queries: List[str]) -> str:
    """Build SPARQL UNION query from multiple query patterns.
    
    Args:
        queries: List of query patterns to union
        
    Returns:
        SPARQL UNION query
    """
    if not queries:
        return ""
    
    if len(queries) == 1:
        return queries[0]
    
    # Join with UNION
    union_parts = []
    for query in queries:
        union_parts.append(f"{{ {query} }}")
    
    return " UNION ".join(union_parts)


def format_sparql_query(query: str) -> str:
    """Format SPARQL query for better readability.
    
    Args:
        query: SPARQL query string
        
    Returns:
        Formatted query string
    """
    # Remove extra whitespace and normalize line breaks
    lines = []
    for line in query.split('\n'):
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    
    return '\n'.join(lines)
