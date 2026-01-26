"""
KGRelations Read Implementation

This module contains the core implementation logic for KGRelation read/list operations.
It provides backend-agnostic functions for querying and retrieving relations.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# Local imports
from .kg_backend_utils import KGBackendInterface


class KGRelationsReadProcessor:
    """Processor for KGRelation read operations with backend abstraction."""
    
    def __init__(self, backend: KGBackendInterface):
        """
        Initialize with backend interface.
        
        Args:
            backend: Backend interface implementation
        """
        self.backend = backend
        self.logger = logging.getLogger(f"{__name__}.KGRelationsReadProcessor")
    
    async def list_relations(self, space_id: str, graph_id: str,
                           entity_source_uri: Optional[str] = None,
                           entity_destination_uri: Optional[str] = None,
                           relation_type_uri: Optional[str] = None,
                           direction: str = "outgoing",
                           page_size: int = 100,
                           offset: int = 0) -> Tuple[List[Tuple], int]:
        """
        List KG Relations with filtering and pagination.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_source_uri: Optional filter by source entity
            entity_destination_uri: Optional filter by destination entity
            relation_type_uri: Optional filter by relation type
            direction: Direction filter ("outgoing", "incoming", "both")
            page_size: Number of relations per page
            offset: Number of relations to skip
            
        Returns:
            Tuple[List[Tuple], int]: (List of RDFLib triples, total count)
        """
        try:
            self.logger.info(f"Listing KG Relations (page_size: {page_size}, offset: {offset})")
            
            # Build SPARQL query
            query = self._build_list_query(
                graph_id, entity_source_uri, entity_destination_uri,
                relation_type_uri, direction, page_size, offset
            )
            
            # Execute query
            result = await self.backend.execute_sparql_query(space_id, query)
            
            # Handle dictionary response format
            if isinstance(result, dict):
                result = result.get('results', {}).get('bindings', [])
            elif not result:
                result = []
            
            # Convert SPARQL results to RDFLib triples
            from rdflib import URIRef, Literal, BNode
            
            triples = []
            for binding in result:
                # Extract subject, predicate, object from SPARQL binding
                subject_data = binding.get('s', {})
                predicate_data = binding.get('p', {})
                object_data = binding.get('o', {})
                
                # Convert to RDFLib terms
                if subject_data.get('type') == 'uri':
                    subject = URIRef(subject_data.get('value', ''))
                elif subject_data.get('type') == 'bnode':
                    subject = BNode(subject_data.get('value', ''))
                else:
                    continue
                
                if predicate_data.get('type') == 'uri':
                    predicate = URIRef(predicate_data.get('value', ''))
                else:
                    continue
                
                if object_data.get('type') == 'uri':
                    obj = URIRef(object_data.get('value', ''))
                elif object_data.get('type') == 'literal':
                    obj = Literal(object_data.get('value', ''))
                elif object_data.get('type') == 'bnode':
                    obj = BNode(object_data.get('value', ''))
                else:
                    continue
                
                triples.append((subject, predicate, obj))
            
            # Get total count
            count_query = self._build_count_query(
                graph_id, entity_source_uri, entity_destination_uri,
                relation_type_uri, direction
            )
            
            count_result = await self.backend.execute_sparql_query(space_id, count_query)
            
            # Handle dictionary response format
            if isinstance(count_result, dict):
                count_result = count_result.get('results', {}).get('bindings', [])
            
            total_count = 0
            if count_result and len(count_result) > 0:
                total_count = int(count_result[0].get('count', {}).get('value', 0))
            
            self.logger.info(f"✅ Listed {len(triples)} relation RDFLib triples (total: {total_count})")
            return triples, total_count
            
        except Exception as e:
            self.logger.error(f"❌ Failed to list KG Relations: {e}")
            raise
    
    async def get_relation_by_uri(self, space_id: str, graph_id: str, relation_uri: str) -> List[Tuple]:
        """
        Get a specific KG Relation by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relation_uri: URI of the relation to retrieve
            
        Returns:
            List[Tuple]: List of RDFLib triples for the relation
        """
        try:
            self.logger.info(f"Getting KG Relation: {relation_uri}")
            
            # Build SPARQL query
            query = f"""
            SELECT ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    <{relation_uri}> ?p ?o .
                }}
            }}
            """
            
            result = await self.backend.execute_sparql_query(space_id, query)
            
            # Handle dictionary response format
            if isinstance(result, dict):
                result = result.get('results', {}).get('bindings', [])
            
            if not result or len(result) == 0:
                self.logger.info(f"Relation not found: {relation_uri}")
                return []
            
            # Convert SPARQL results to RDFLib triples
            from rdflib import URIRef, Literal, BNode
            
            triples = []
            subject = URIRef(relation_uri)
            
            for binding in result:
                predicate_data = binding.get('p', {})
                object_data = binding.get('o', {})
                
                if predicate_data.get('type') == 'uri':
                    predicate = URIRef(predicate_data.get('value', ''))
                else:
                    continue
                
                if object_data.get('type') == 'uri':
                    obj = URIRef(object_data.get('value', ''))
                elif object_data.get('type') == 'literal':
                    obj = Literal(object_data.get('value', ''))
                elif object_data.get('type') == 'bnode':
                    obj = BNode(object_data.get('value', ''))
                else:
                    continue
                
                triples.append((subject, predicate, obj))
            
            self.logger.info(f"✅ Retrieved relation with {len(triples)} triples")
            return triples
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get KG Relation: {e}")
            raise
    
    def _build_list_query(self, graph_id: str, entity_source_uri: Optional[str],
                         entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                         direction: str, page_size: int, offset: int) -> str:
        """Build SPARQL query for listing relations."""
        
        # Build filter conditions
        filters = []
        
        if entity_source_uri:
            filters.append(f"?s <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_source_uri}> .")
        
        if entity_destination_uri:
            filters.append(f"?s <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{entity_destination_uri}> .")
        
        if relation_type_uri:
            filters.append(f"?s <http://vital.ai/ontology/haley-ai-kg#hasKGRelationType> <{relation_type_uri}> .")
        
        filter_clause = "\n                ".join(filters) if filters else ""
        
        query = f"""
        SELECT ?s ?p ?o WHERE {{
            GRAPH <{graph_id}> {{
                {{
                    SELECT DISTINCT ?s WHERE {{
                        ?s a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
                        {filter_clause}
                    }}
                    ORDER BY ?s
                    LIMIT {page_size}
                    OFFSET {offset}
                }}
                ?s ?p ?o .
            }}
        }}
        ORDER BY ?s
        """
        
        return query
    
    def _build_count_query(self, graph_id: str, entity_source_uri: Optional[str],
                          entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                          direction: str) -> str:
        """Build SPARQL query for counting relations."""
        
        # Build filter conditions
        filters = []
        
        if entity_source_uri:
            filters.append(f"?s <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_source_uri}> .")
        
        if entity_destination_uri:
            filters.append(f"?s <http://vital.ai/ontology/vital-core#hasEdgeDestination> <{entity_destination_uri}> .")
        
        if relation_type_uri:
            filters.append(f"?s <http://vital.ai/ontology/haley-ai-kg#hasKGRelationType> <{relation_type_uri}> .")
        
        filter_clause = "\n            ".join(filters) if filters else ""
        
        query = f"""
        SELECT (COUNT(DISTINCT ?s) AS ?count) WHERE {{
            GRAPH <{graph_id}> {{
                ?s a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
                {filter_clause}
            }}
        }}
        """
        
        return query
