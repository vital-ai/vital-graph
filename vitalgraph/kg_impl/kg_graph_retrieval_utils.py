"""
Centralized utilities for retrieving graph objects with configurable materialized edge filtering.

This module provides a single point of control for all graph object retrieval operations,
ensuring consistent handling of materialized edge predicates across the codebase.

Materialized edge predicates (vg-direct:hasEntityFrame, vg-direct:hasFrame, vg-direct:hasSlot)
are optimization triples created in Fuseki for query performance. They should be filtered out
in most operations to prevent VitalSigns conversion errors, but included in deletion and update
operations to ensure complete cleanup.
"""
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class MaterializedPredicateConstants:
    """Constants for materialized edge predicates."""
    
    MATERIALIZED_PREDICATES = frozenset([
        'http://vital.ai/vitalgraph/direct#hasEntityFrame',
        'http://vital.ai/vitalgraph/direct#hasFrame',
        'http://vital.ai/vitalgraph/direct#hasSlot'
    ])
    
    @classmethod
    def get_filter_clause(cls, predicate_var: str = "?p") -> str:
        """
        Generate SPARQL FILTER clause to exclude materialized predicates.
        
        Args:
            predicate_var: Variable name for predicate (default: "?p")
            
        Returns:
            SPARQL FILTER clause string
            
        Example:
            >>> MaterializedPredicateConstants.get_filter_clause()
            'FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                   ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                   ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)'
        """
        filters = [f"{predicate_var} != <{pred}>" for pred in cls.MATERIALIZED_PREDICATES]
        return f"FILTER({' &&\n           '.join(filters)})"


class GraphObjectRetriever:
    """
    Centralized utility for retrieving graph objects with configurable filtering.
    
    This class provides a single point of control for all graph object retrieval
    operations, ensuring consistent handling of materialized edge predicates.
    
    Usage:
        retriever = GraphObjectRetriever(backend)
        
        # Default: filter OUT materialized edges (for VitalSigns conversion)
        triples = await retriever.get_object_triples(space_id, graph_id, uri)
        
        # Explicit: include materialized edges (for deletion operations)
        triples = await retriever.get_object_triples(
            space_id, graph_id, uri, include_materialized_edges=True
        )
    """
    
    def __init__(self, backend):
        """
        Initialize retriever with backend connection.
        
        Args:
            backend: Backend implementation (Fuseki/PostgreSQL adapter)
        """
        self.backend = backend
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def get_object_triples(
        self,
        space_id: str,
        graph_id: str,
        object_uri: str,
        include_materialized_edges: bool = False
    ) -> List[tuple]:
        """
        Retrieve all triples for a single object.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            object_uri: URI of object to retrieve
            include_materialized_edges: If False (default), exclude vg-direct:* predicates
            
        Returns:
            List of (subject, predicate, object) triples
            
        Use Cases:
            - include_materialized_edges=False (default): Read operations, VitalSigns conversion
            - include_materialized_edges=True: Deletion operations, update operations
        """
        filter_clause = "" if include_materialized_edges else MaterializedPredicateConstants.get_filter_clause()
        
        query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    <{object_uri}> ?p ?o .
                    {filter_clause}
                }}
            }}
        """
        
        self.logger.debug(f"Retrieving object triples for {object_uri} (include_materialized={include_materialized_edges})")
        results = await self.backend.execute_sparql_query(space_id, query)
        
        # Handle dictionary response format (unwrap if needed)
        if isinstance(results, dict):
            results = results.get('results', {}).get('bindings', [])
        
        # Log raw SPARQL results to see format
        if results:
            self.logger.debug(f"🔍 RAW SPARQL RESULTS: {len(results)} rows")
            if len(results) > 0:
                self.logger.debug(f"  First row: {results[0]}")
        
        # Convert SPARQL results to RDFLib triple objects
        from rdflib import URIRef, Literal
        triples = []
        for i, row in enumerate(results):
            try:
                subject = URIRef(object_uri)
                predicate_data = row.get('p', {})
                predicate = URIRef(predicate_data.get('value'))
                obj_data = row.get('o', {})
                obj_value = obj_data.get('value')
                
                # Determine if object is URI or Literal based on SPARQL result type
                if obj_data.get('type') == 'uri':
                    obj = URIRef(obj_value)
                else:
                    # Literal value - match original code behavior
                    obj = Literal(obj_value)
                
                triples.append((subject, predicate, obj))
            except Exception as e:
                self.logger.error(f"Error parsing row {i}: {e}")
                self.logger.error(f"Row data: {row}")
                raise
        
        return triples
    
    async def get_entity_graph(
        self,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        include_materialized_edges: bool = False
    ) -> List[tuple]:
        """
        Retrieve complete entity graph (entity + all related objects via hasKGGraphURI).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            entity_uri: URI of entity
            include_materialized_edges: If False (default), exclude vg-direct:* predicates
            
        Returns:
            List of (subject, predicate, object) triples for entire entity graph
            
        Use Cases:
            - include_materialized_edges=False (default): API responses, VitalSigns conversion
            - include_materialized_edges=True: Deletion operations
        """
        filter_clause = "" if include_materialized_edges else MaterializedPredicateConstants.get_filter_clause()
        
        query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        # Get the entity itself
                        <{entity_uri}> ?p ?o .
                        BIND(<{entity_uri}> AS ?s)
                        {filter_clause}
                    }}
                    UNION
                    {{
                        # Get objects with same entity-level grouping URI
                        ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{entity_uri}> .
                        ?s ?p ?o .
                        {filter_clause}
                    }}
                }}
            }}
        """
        
        self.logger.debug(f"Retrieving entity graph for {entity_uri} (include_materialized={include_materialized_edges})")
        results = await self.backend.execute_sparql_query(space_id, query)
        
        # Handle dictionary response format (unwrap if needed)
        if isinstance(results, dict):
            results = results.get('results', {}).get('bindings', [])
        
        # Convert SPARQL results to RDFLib triple objects
        from rdflib import URIRef, Literal
        triples = []
        for row in results:
            subject_data = row.get('s', {})
            subject = URIRef(subject_data.get('value'))
            predicate_data = row.get('p', {})
            predicate = URIRef(predicate_data.get('value'))
            obj_data = row.get('o', {})
            obj_value = obj_data.get('value')
            
            # Determine if object is URI or Literal based on SPARQL result type
            if obj_data.get('type') == 'uri':
                obj = URIRef(obj_value)
            else:
                # Literal value - match original code behavior
                obj = Literal(obj_value)
            
            triples.append((subject, predicate, obj))
        
        return triples
    
    async def get_objects_by_uris(
        self,
        space_id: str,
        graph_id: str,
        object_uris: List[str],
        include_materialized_edges: bool = False
    ) -> Dict[str, List[tuple]]:
        """
        Retrieve triples for multiple objects in a single query (batch operation).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            object_uris: List of object URIs to retrieve
            include_materialized_edges: If False (default), exclude vg-direct:* predicates
            
        Returns:
            Dictionary mapping object URI to list of triples
            
        Use Cases:
            - include_materialized_edges=False (default): Batch read operations
            - include_materialized_edges=True: Batch deletion operations
            
        Performance:
            This method is optimized for batch operations, reducing round trips to the backend.
        """
        if not object_uris:
            return {}
        
        filter_clause = "" if include_materialized_edges else MaterializedPredicateConstants.get_filter_clause()
        uri_values = " ".join([f"<{uri}>" for uri in object_uris])
        
        query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?s ?p ?o WHERE {{
                VALUES ?s {{ {uri_values} }}
                GRAPH <{graph_id}> {{
                    ?s ?p ?o .
                    {filter_clause}
                }}
            }}
        """
        
        self.logger.debug(f"Batch retrieving {len(object_uris)} objects (include_materialized={include_materialized_edges})")
        results = await self.backend.execute_sparql_query(space_id, query)
        
        # Handle dictionary response format (unwrap if needed)
        if isinstance(results, dict):
            results = results.get('results', {}).get('bindings', [])
        
        # Convert SPARQL results to RDFLib triple objects and group by subject
        from rdflib import URIRef, Literal
        grouped = {}
        for row in results:
            subject_data = row.get('s', {})
            subject_uri = str(subject_data.get('value'))
            if subject_uri not in grouped:
                grouped[subject_uri] = []
            
            subject = URIRef(subject_data.get('value'))
            predicate_data = row.get('p', {})
            predicate = URIRef(predicate_data.get('value'))
            obj_data = row.get('o', {})
            obj_value = obj_data.get('value')
            
            # Determine if object is URI or Literal based on SPARQL result type
            if obj_data.get('type') == 'uri':
                obj = URIRef(obj_value)
            else:
                # Literal value - match original code behavior
                obj = Literal(obj_value)
            
            grouped[subject_uri].append((subject, predicate, obj))
        
        return grouped
    
    async def get_entity_by_reference_id(
        self,
        space_id: str,
        graph_id: str,
        reference_id: str,
        include_materialized_edges: bool = False
    ) -> Optional[List[tuple]]:
        """
        Retrieve entity by reference identifier.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            reference_id: Reference identifier value
            include_materialized_edges: If False (default), exclude vg-direct:* predicates
            
        Returns:
            List of triples for entity, or None if not found
            
        Use Cases:
            - include_materialized_edges=False (default): API lookups, VitalSigns conversion
            - include_materialized_edges=True: Deletion by reference ID
        """
        filter_clause = "" if include_materialized_edges else MaterializedPredicateConstants.get_filter_clause()
        
        query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            PREFIX aimp: <http://vital.ai/ontology/vital-aimp#>
            
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    ?s a haley:KGEntity .
                    ?s aimp:hasReferenceIdentifier "{reference_id}" .
                    ?s ?p ?o .
                    {filter_clause}
                }}
            }}
        """
        
        self.logger.debug(f"Retrieving entity by reference ID '{reference_id}' (include_materialized={include_materialized_edges})")
        results = await self.backend.execute_sparql_query(space_id, query)
        
        # Handle dictionary response format (unwrap if needed)
        if isinstance(results, dict):
            results = results.get('results', {}).get('bindings', [])
        
        if not results:
            return None
        
        # Convert SPARQL results to RDFLib triple objects
        from rdflib import URIRef, Literal
        triples = []
        for row in results:
            subject_data = row.get('s', {})
            subject = URIRef(subject_data.get('value'))
            predicate_data = row.get('p', {})
            predicate = URIRef(predicate_data.get('value'))
            obj_data = row.get('o', {})
            obj_value = obj_data.get('value')
            
            # Determine if object is URI or Literal based on SPARQL result type
            if obj_data.get('type') == 'uri':
                obj = URIRef(obj_value)
            else:
                # Literal value - match original code behavior
                obj = Literal(obj_value)
            
            triples.append((subject, predicate, obj))
        
        return triples
    
    async def get_entity_graph_by_reference_id(
        self,
        space_id: str,
        graph_id: str,
        reference_id: str,
        include_materialized_edges: bool = False
    ) -> Optional[List[tuple]]:
        """
        Retrieve complete entity graph by reference identifier.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            reference_id: Reference identifier value
            include_materialized_edges: If False (default), exclude vg-direct:* predicates
            
        Returns:
            List of triples for entire entity graph, or None if entity not found
            
        Use Cases:
            - include_materialized_edges=False (default): API lookups, VitalSigns conversion
            - include_materialized_edges=True: Deletion by reference ID
        """
        filter_clause = "" if include_materialized_edges else MaterializedPredicateConstants.get_filter_clause()
        
        query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            PREFIX aimp: <http://vital.ai/ontology/vital-aimp#>
            
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        # First find the entity by reference ID
                        ?entity a haley:KGEntity .
                        ?entity aimp:hasReferenceIdentifier "{reference_id}" .
                        ?entity ?p ?o .
                        BIND(?entity AS ?s)
                        {filter_clause}
                    }}
                    UNION
                    {{
                        # Then get all objects grouped with that entity
                        ?entity a haley:KGEntity .
                        ?entity aimp:hasReferenceIdentifier "{reference_id}" .
                        ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> ?entity .
                        ?s ?p ?o .
                        {filter_clause}
                    }}
                }}
            }}
        """
        
        self.logger.debug(f"Retrieving entity graph by reference ID '{reference_id}' (include_materialized={include_materialized_edges})")
        results = await self.backend.execute_sparql_query(space_id, query)
        
        # Handle dictionary response format (unwrap if needed)
        if isinstance(results, dict):
            results = results.get('results', {}).get('bindings', [])
        
        if not results:
            return None
        
        # Convert SPARQL results to RDFLib triple objects
        from rdflib import URIRef, Literal
        triples = []
        for row in results:
            subject_data = row.get('s', {})
            subject = URIRef(subject_data.get('value'))
            predicate_data = row.get('p', {})
            predicate = URIRef(predicate_data.get('value'))
            obj_data = row.get('o', {})
            obj_value = obj_data.get('value')
            
            # Determine if object is URI or Literal based on SPARQL result type
            if obj_data.get('type') == 'uri':
                obj = URIRef(obj_value)
            else:
                # Literal value - match original code behavior
                obj = Literal(obj_value)
            
            triples.append((subject, predicate, obj))
        
        return triples
    
    async def list_objects(
        self,
        space_id: str,
        graph_id: str,
        type_uris: List[str],
        property_filters: Optional[Dict[str, str]] = None,
        include_materialized_edges: bool = False,
        page_size: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        include_count: bool = False
    ) -> Tuple[List[tuple], int]:
        """
        List objects by type with optional property filters, pagination, and search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            type_uris: List of type URIs to filter by (UNION)
            property_filters: Optional dict of property URI -> value URI pairs for additional filtering
            include_materialized_edges: If False (default), exclude vg-direct:* predicates
            page_size: Number of objects per page
            offset: Number of objects to skip
            search: Optional search text to filter by hasName or URI
            include_count: If False (default), skip count query for performance; if True, return actual count
            
        Returns:
            Tuple of (list of RDFLib triples, total count or -1 if include_count=False)
        """
        filter_clause = "" if include_materialized_edges else MaterializedPredicateConstants.get_filter_clause()
        
        # Build type filter using UNION (using rdf:type)
        type_filters = " UNION ".join([f"{{ ?s a <{type_uri}> . }}" for type_uri in type_uris])
        
        # Build property filters
        property_filter_clauses = []
        if property_filters:
            for prop_uri, value_uri in property_filters.items():
                property_filter_clauses.append(f"?s <{prop_uri}> <{value_uri}> .")
        
        # Build search filter if provided
        search_filter_clauses = []
        if search:
            search_filter_clauses.append(f"""
                {{
                    ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
                    FILTER (CONTAINS(LCASE(STR(?name)), LCASE("{search}")))
                }} UNION {{
                    FILTER (CONTAINS(LCASE(STR(?s)), LCASE("{search}")))
                }}
            """)
        
        # Combine all filters
        all_filters = "\n".join(property_filter_clauses)
        if search_filter_clauses:
            all_filters += "\n" + "\n".join(search_filter_clauses)
        
        # Build combined filter for subquery (type + property filters + optional search)
        subquery_filter = f"""
            {type_filters}
            {all_filters}
        """
        
        # Query for objects with pagination
        query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        SELECT DISTINCT ?s WHERE {{
                            {subquery_filter}
                        }}
                        ORDER BY ?s
                        LIMIT {page_size}
                        OFFSET {offset}
                    }}
                    ?s ?p ?o .
                    {filter_clause}
                }}
            }}
            ORDER BY ?s
        """
        
        results = await self.backend.execute_sparql_query(space_id, query)
        
        # Handle dictionary response format (unwrap if needed)
        if isinstance(results, dict):
            results = results.get('results', {}).get('bindings', [])
        
        # Get total count for pagination (optional for performance)
        total_count = -1  # Default to -1 when count is not requested
        if include_count:
            count_query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
                
                SELECT (COUNT(DISTINCT ?s) AS ?count) WHERE {{
                    GRAPH <{graph_id}> {{
                        {subquery_filter}
                    }}
                }}
            """
            
            count_result = await self.backend.execute_sparql_query(space_id, count_query)
            
            # Handle dictionary response format
            if isinstance(count_result, dict):
                count_result = count_result.get('results', {}).get('bindings', [])
            
            if count_result and len(count_result) > 0:
                total_count = int(count_result[0].get('count', {}).get('value', 0))
        
        # Convert SPARQL results to RDFLib triple objects
        from rdflib import URIRef, Literal
        triples = []
        for row in results:
            subject_data = row.get('s', {})
            subject = URIRef(subject_data.get('value'))
            predicate_data = row.get('p', {})
            predicate = URIRef(predicate_data.get('value'))
            obj_data = row.get('o', {})
            obj_value = obj_data.get('value')
            
            # Determine if object is URI or Literal based on SPARQL result type
            if obj_data.get('type') == 'uri':
                obj = URIRef(obj_value)
            else:
                # Literal value - match original code behavior
                obj = Literal(obj_value)
            
            triples.append((subject, predicate, obj))
        
        return triples, total_count
