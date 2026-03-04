"""
Mock implementation of KGRelationsEndpoint for testing with VitalSigns native functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper Edge_hasKGRelation handling
- Complete CRUD operations following real endpoint patterns
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgrelations_model import (
    RelationsResponse, RelationResponse, RelationCreateResponse, RelationUpdateResponse,
    RelationUpsertResponse, RelationDeleteRequest, RelationDeleteResponse,
    RelationQueryRequest, RelationQueryResponse
)
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge


class MockKGRelationsEndpoint(MockBaseEndpoint):
    """Mock implementation of KGRelationsEndpoint with VitalSigns native functionality."""
    
    def __init__(self, client=None, space_manager=None, *, config=None):
        """Initialize with relation-specific functionality."""
        super().__init__(client, space_manager, config=config)
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
    
    def list_relations(self, space_id: str, graph_id: str, 
                      entity_source_uri: Optional[str] = None,
                      entity_destination_uri: Optional[str] = None,
                      relation_type_uri: Optional[str] = None,
                      direction: str = "all",
                      page_size: int = 10, 
                      offset: int = 0) -> RelationsResponse:
        """
        List KG Relations with filtering and pagination using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_source_uri: Filter by source entity URI
            entity_destination_uri: Filter by destination entity URI
            relation_type_uri: Filter by relation type URN
            direction: Direction filter (all, incoming, outgoing)
            page_size: Number of relations per page
            offset: Offset for pagination
            
        Returns:
            RelationsResponse with VitalSigns native objects
        """
        self._log_method_call("list_relations", space_id, graph_id, 
                             entity_source_uri=entity_source_uri,
                             entity_destination_uri=entity_destination_uri,
                             relation_type_uri=relation_type_uri,
                             direction=direction,
                             page_size=page_size, offset=offset)
        
        try:
            # Get space for SPARQL operations
            if not self.space_manager:
                raise ValueError("Space manager not available")
            
            space = self.space_manager.get_space(space_id)
            if not space:
                raise ValueError(f"Space {space_id} not found")
            
            # Build SPARQL query for listing relations
            sparql_query = self._build_list_relations_query(
                graph_id, entity_source_uri, entity_destination_uri,
                relation_type_uri, direction, page_size, offset
            )
            
            # Execute SPARQL query
            result = space.query_sparql(sparql_query)
            
            # Convert SPARQL results to VitalSigns objects
            relations = self._sparql_results_to_relations(result)
            
            # Get total count for pagination
            total_count = self._get_relations_count(
                space, graph_id, entity_source_uri, entity_destination_uri,
                relation_type_uri, direction
            )
            
            quads = graphobjects_to_quad_list(relations, graph_id) if relations else []
            
            return RelationsResponse(
                results=quads,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Failed to list relations: {e}")
            return RelationsResponse(
                results=[],
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    def get_relation(self, space_id: str, graph_id: str, relation_uri: str) -> RelationResponse:
        """
        Get a specific KG Relation by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            relation_uri: Relation URI
            
        Returns:
            RelationResponse with relation data
        """
        self._log_method_call("get_relation", space_id, graph_id, relation_uri)
        
        try:
            # Get space for SPARQL operations
            if not self.space_manager:
                raise ValueError("Space manager not available")
            
            space = self.space_manager.get_space(space_id)
            if not space:
                raise ValueError(f"Space {space_id} not found")
            
            # Build SPARQL query for specific relation
            sparql_query = self._build_get_relation_query(graph_id, relation_uri)
            
            # Execute SPARQL query
            result = space.query_sparql(sparql_query)
            
            # Convert SPARQL results to VitalSigns objects
            relations = self._sparql_results_to_relations(result)
            
            if not relations:
                raise ValueError(f"Relation {relation_uri} not found")
            
            quads = graphobjects_to_quad_list([relations[0]], graph_id)
            
            return RelationResponse(results=quads, total_count=1)
            
        except Exception as e:
            self.logger.error(f"Failed to get relation {relation_uri}: {e}")
            raise
    
    def create_relations(self, space_id: str, graph_id: str, document: List) -> RelationCreateResponse:
        """Create KG Relations from graph objects."""
        self._log_method_call("create_relations", space_id, graph_id)
        
        try:
            # Accept graph objects directly
            relations = self._document_to_relations(document)
            
            # Validate relations
            self._validate_relations(relations)
            
            # Store relations in space
            created_uris = self._store_relations_in_space(space_id, graph_id, relations)
            
            return RelationCreateResponse(
                message=f"Successfully created {len(created_uris)} relations",
                created_count=len(created_uris),
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Failed to create relations: {e}")
            raise
    
    def update_relations(self, space_id: str, graph_id: str, document: List) -> RelationUpdateResponse:
        """Update KG Relations with proper validation."""
        self._log_method_call("update_relations", space_id, graph_id)
        
        try:
            # Accept graph objects directly
            relations = self._document_to_relations(document)
            
            # Validate relations exist
            self._validate_relations_exist(space_id, graph_id, relations)
            
            # Update relations in space (delete old, insert new)
            updated_uris = self._update_relations_in_space(space_id, graph_id, relations)
            
            return RelationUpdateResponse(
                message=f"Successfully updated {len(updated_uris)} relations",
                updated_uri=updated_uris[0] if updated_uris else None
            )
            
        except Exception as e:
            self.logger.error(f"Failed to update relations: {e}")
            raise
    
    def upsert_relations(self, space_id: str, graph_id: str, document: List) -> RelationUpsertResponse:
        """Upsert KG Relations (create or update)."""
        self._log_method_call("upsert_relations", space_id, graph_id)
        
        try:
            # Accept graph objects directly
            relations = self._document_to_relations(document)
            
            # Determine which relations exist
            existing_uris = self._get_existing_relation_uris(space_id, graph_id, relations)
            
            # Separate into create and update operations
            create_relations = [r for r in relations if str(r.URI) not in existing_uris]
            update_relations = [r for r in relations if str(r.URI) in existing_uris]
            
            # Perform operations
            created_uris = []
            updated_uris = []
            
            if create_relations:
                created_uris = self._store_relations_in_space(space_id, graph_id, create_relations)
            
            if update_relations:
                updated_uris = self._update_relations_in_space(space_id, graph_id, update_relations)
            
            total_count = len(created_uris) + len(updated_uris)
            all_uris = created_uris + updated_uris
            
            return RelationUpsertResponse(
                message=f"Successfully upserted {total_count} relations ({len(created_uris)} created, {len(updated_uris)} updated)",
                created_count=total_count,
                created_uris=all_uris
            )
            
        except Exception as e:
            self.logger.error(f"Failed to upsert relations: {e}")
            raise
    
    def delete_relations(self, space_id: str, graph_id: str, request: RelationDeleteRequest) -> RelationDeleteResponse:
        """Delete KG Relations by URIs."""
        self._log_method_call("delete_relations", space_id, graph_id, relation_uris=request.relation_uris)
        
        try:
            # Delete relations from space
            deleted_count = self._delete_relations_from_space(space_id, graph_id, request.relation_uris)
            
            return RelationDeleteResponse(
                message=f"Successfully deleted {deleted_count} relations",
                deleted_count=deleted_count,
                deleted_uris=request.relation_uris[:deleted_count]
            )
            
        except Exception as e:
            self.logger.error(f"Failed to delete relations: {e}")
            raise
    
    def query_relations(self, space_id: str, graph_id: str, request: RelationQueryRequest) -> RelationQueryResponse:
        """Query KG Relations with complex criteria."""
        self._log_method_call("query_relations", space_id, graph_id, criteria=request.criteria)
        
        try:
            # Build complex SPARQL query from criteria
            sparql_query = self._build_query_relations_sparql(
                graph_id, request.criteria, request.page_size, request.offset
            )
            
            # Get space for SPARQL operations
            if not self.space_manager:
                raise ValueError("Space manager not available")
            
            space = self.space_manager.get_space(space_id)
            if not space:
                raise ValueError(f"Space {space_id} not found")
            
            # Execute SPARQL query
            result = space.query_sparql(sparql_query)
            
            # Extract relation URIs from results
            relation_uris = self._extract_relation_uris_from_sparql_results(result)
            
            # Get total count
            total_count = self._get_query_relations_count(space, graph_id, request.criteria)
            
            return RelationQueryResponse(
                relation_uris=relation_uris,
                total_count=total_count,
                page_size=request.page_size,
                offset=request.offset
            )
            
        except Exception as e:
            self.logger.error(f"Failed to query relations: {e}")
            raise
    
    # Helper methods (to be implemented in Task 3)
    def _build_list_relations_query(self, graph_id: str, entity_source_uri: Optional[str],
                                   entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                                   direction: str, page_size: int, offset: int) -> str:
        """Build SPARQL query for listing relations."""
        # Build base query
        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital: <http://vital.ai/ontology/vital-core#>",
            "",
            "SELECT ?relation ?source ?destination ?type WHERE {"
        ]
        
        # Add graph context if specified
        if graph_id:
            query_parts.append(f"    GRAPH <{graph_id}> {{")
            indent = "        "
        else:
            indent = "    "
        
        # Base pattern for relations
        query_parts.extend([
            f"{indent}?relation a haley:Edge_hasKGRelation .",
            f"{indent}?relation vital:hasEdgeSource ?source .",
            f"{indent}?relation vital:hasEdgeDestination ?destination .",
            f"{indent}?relation haley:hasKGRelationType ?type ."
        ])
        
        # Add filters based on parameters
        filters = []
        
        # Entity source filter
        if entity_source_uri:
            if direction in ["all", "outgoing"]:
                filters.append(f"?source = <{entity_source_uri}>")
        
        # Entity destination filter  
        if entity_destination_uri:
            if direction in ["all", "incoming"]:
                filters.append(f"?destination = <{entity_destination_uri}>")
        
        # Relation type filter
        if relation_type_uri:
            filters.append(f"?type = <{relation_type_uri}>")
        
        # Handle direction-based filtering for single entity
        if direction == "outgoing" and entity_source_uri and not entity_destination_uri:
            # Already handled by source filter above
            pass
        elif direction == "incoming" and entity_destination_uri and not entity_source_uri:
            # Already handled by destination filter above
            pass
        elif direction == "all" and (entity_source_uri or entity_destination_uri):
            # For "all" direction with single entity, we need UNION
            if entity_source_uri and not entity_destination_uri:
                # Show all relations where entity is source OR destination
                query_parts = [
                    "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
                    "PREFIX vital: <http://vital.ai/ontology/vital-core#>",
                    "",
                    "SELECT ?relation ?source ?destination ?type WHERE {"
                ]
                
                if graph_id:
                    query_parts.append(f"    GRAPH <{graph_id}> {{")
                    inner_indent = "        "
                else:
                    inner_indent = "    "
                
                query_parts.extend([
                    f"{inner_indent}{{",
                    f"{inner_indent}    # Outgoing relations",
                    f"{inner_indent}    ?relation a haley:Edge_hasKGRelation .",
                    f"{inner_indent}    ?relation vital:hasEdgeSource <{entity_source_uri}> .",
                    f"{inner_indent}    ?relation vital:hasEdgeDestination ?destination .",
                    f"{inner_indent}    ?relation haley:hasKGRelationType ?type .",
                    f"{inner_indent}    BIND(<{entity_source_uri}> AS ?source)",
                    f"{inner_indent}}} UNION {{",
                    f"{inner_indent}    # Incoming relations", 
                    f"{inner_indent}    ?relation a haley:Edge_hasKGRelation .",
                    f"{inner_indent}    ?relation vital:hasEdgeSource ?source .",
                    f"{inner_indent}    ?relation vital:hasEdgeDestination <{entity_source_uri}> .",
                    f"{inner_indent}    ?relation haley:hasKGRelationType ?type .",
                    f"{inner_indent}    BIND(<{entity_source_uri}> AS ?destination)",
                    f"{inner_indent}}}"
                ])
                
                # Add relation type filter if specified
                if relation_type_uri:
                    # Insert filter into both UNION branches
                    query_parts.insert(-7, f"{inner_indent}    FILTER(?type = <{relation_type_uri}>)")
                    query_parts.insert(-2, f"{inner_indent}    FILTER(?type = <{relation_type_uri}>)")
        
        # Add filters if any (for non-UNION queries)
        if filters and "UNION" not in "\n".join(query_parts):
            for filter_expr in filters:
                query_parts.append(f"{indent}FILTER({filter_expr})")
        
        # Close graph context if specified
        if graph_id:
            query_parts.append("    }")
        
        # Close main WHERE clause
        query_parts.append("}")
        
        # Add ordering and pagination
        query_parts.extend([
            "ORDER BY ?relation",
            f"LIMIT {page_size}",
            f"OFFSET {offset}"
        ])
        
        return "\n".join(query_parts)
    
    def _build_count_relations_query(self, graph_id: str, entity_source_uri: Optional[str],
                                   entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                                   direction: str) -> str:
        """Build SPARQL count query for relations."""
        # Build base count query
        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital: <http://vital.ai/ontology/vital-core#>",
            "",
            "SELECT (COUNT(DISTINCT ?relation) AS ?count) WHERE {"
        ]
        
        # Add graph context if specified
        if graph_id:
            query_parts.append(f"    GRAPH <{graph_id}> {{")
            indent = "        "
        else:
            indent = "    "
        
        # Base pattern for relations
        query_parts.extend([
            f"{indent}?relation a haley:Edge_hasKGRelation .",
            f"{indent}?relation vital:hasEdgeSource ?source .",
            f"{indent}?relation vital:hasEdgeDestination ?destination .",
            f"{indent}?relation haley:hasKGRelationType ?type ."
        ])
        
        # Add filters based on parameters
        filters = []
        
        # Entity source filter
        if entity_source_uri:
            if direction in ["all", "outgoing"]:
                filters.append(f"?source = <{entity_source_uri}>")
        
        # Entity destination filter  
        if entity_destination_uri:
            if direction in ["all", "incoming"]:
                filters.append(f"?destination = <{entity_destination_uri}>")
        
        # Relation type filter
        if relation_type_uri:
            filters.append(f"?type = <{relation_type_uri}>")
        
        # Add filters
        for filter_expr in filters:
            query_parts.append(f"{indent}FILTER({filter_expr})")
        
        # Close graph context if specified
        if graph_id:
            query_parts.append("    }")
        
        # Close main WHERE clause
        query_parts.append("}")
        
        return "\n".join(query_parts)
    
    def _sparql_results_to_relations(self, sparql_result: Dict[str, Any]) -> List[Edge_hasKGRelation]:
        """Convert SPARQL results to VitalSigns relation objects."""
        relations = []
        
        # Handle SPARQL result format (bindings)
        bindings = sparql_result.get('bindings', [])
        
        for binding in bindings:
            try:
                # Create VitalSigns relation object
                relation = Edge_hasKGRelation()
                
                # Extract values from SPARQL binding
                relation_uri = binding.get('relation', {}).get('value')
                source_uri = binding.get('source', {}).get('value')
                destination_uri = binding.get('destination', {}).get('value')
                relation_type = binding.get('type', {}).get('value')
                
                if relation_uri:
                    relation.URI = self._clean_uri(relation_uri)
                if source_uri:
                    relation.edgeSource = self._clean_uri(source_uri)
                if destination_uri:
                    relation.edgeDestination = self._clean_uri(destination_uri)
                if relation_type:
                    relation.kGRelationType = self._clean_uri(relation_type)
                
                relations.append(relation)
                
            except Exception as e:
                self.logger.warning(f"Failed to convert SPARQL binding to relation: {e}")
                continue
        
        return relations
    
    def _relations_to_quad_list(self, relations: List[Edge_hasKGRelation], graph_id: str = None) -> list:
        """Convert relation objects to quad list."""
        return graphobjects_to_quad_list(relations, graph_id)
    
    def _document_to_relations(self, document) -> List[Edge_hasKGRelation]:
        """Extract Edge_hasKGRelation objects from a list of GraphObjects or a wrapper with .graph."""
        try:
            relations = []
            
            # Determine the source list of objects
            if isinstance(document, list):
                items = document
            elif hasattr(document, 'graph') and document.graph:
                items = document.graph
            else:
                return relations
            
            for obj in items:
                if isinstance(obj, Edge_hasKGRelation):
                    relations.append(obj)
                elif isinstance(obj, VITAL_Edge):
                    # Copy edge properties into an Edge_hasKGRelation
                    relation = Edge_hasKGRelation()
                    relation.URI = obj.URI
                    if hasattr(obj, 'edgeSource'):
                        relation.edgeSource = obj.edgeSource
                    if hasattr(obj, 'edgeDestination'):
                        relation.edgeDestination = obj.edgeDestination
                    if hasattr(obj, 'kGRelationType'):
                        relation.kGRelationType = obj.kGRelationType
                    relations.append(relation)
                else:
                    self.logger.warning(f"Skipping non-relation object: {type(obj).__name__}")
            
            return relations
            
        except Exception as e:
            self.logger.error(f"Failed to extract relations: {e}")
            raise ValueError(f"Invalid input for relations: {e}")
    
    def _validate_relations(self, relations: List[Edge_hasKGRelation]) -> None:
        """Validate relation objects."""
        for relation in relations:
            # Validate required fields
            if not relation.URI:
                raise ValueError("Relation must have a URI")
            
            if not relation.edgeSource:
                raise ValueError(f"Relation {relation.URI} must have an edgeSource")
            
            if not relation.edgeDestination:
                raise ValueError(f"Relation {relation.URI} must have an edgeDestination")
            
            if not relation.kGRelationType:
                raise ValueError(f"Relation {relation.URI} must have a kGRelationType")
            
            # Validate relation type format (should be URN)
            relation_type = str(relation.kGRelationType)
            if not relation_type.startswith('urn:'):
                self.logger.warning(f"Relation type {relation_type} should be a URN (starting with 'urn:')")
            
            # Validate URIs format
            source_uri = str(relation.edgeSource)
            dest_uri = str(relation.edgeDestination)
            
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if not validate_rfc3986(source_uri, rule='URI'):
                self.logger.warning(f"Source URI {source_uri} should be a valid URI")
            
            if not validate_rfc3986(dest_uri, rule='URI'):
                self.logger.warning(f"Destination URI {dest_uri} should be a valid HTTP URI")
    
    def _store_relations_in_space(self, space_id: str, graph_id: str, relations: List[Edge_hasKGRelation]) -> List[str]:
        """Store relations in space and return created URIs."""
        try:
            if not self.space_manager:
                raise ValueError("Space manager not available")
            
            space = self.space_manager.get_space(space_id)
            if not space:
                raise ValueError(f"Space {space_id} not found")
            
            # Convert relations to RDF triples
            all_rdf_triples = []
            for relation in relations:
                try:
                    # Use VitalSigns native RDF conversion
                    rdf_output = relation.to_rdf()
                    # Split into individual triples and clean them
                    triples = [line.strip() for line in rdf_output.strip().split('\n') if line.strip()]
                    all_rdf_triples.extend(triples)
                except Exception as e:
                    self.logger.error(f"Failed to convert relation {relation.URI} to RDF: {e}")
                    continue
            
            # Combine all triples into a single RDF document
            rdf_document = '\n'.join(all_rdf_triples)
            
            # Load RDF data into the space
            result = space.load_rdf_data(rdf_document, format_type="turtle", graph_id=graph_id)
            
            if result:
                self.logger.info(f"Successfully stored {len(relations)} relations in space {space_id}")
                return [str(r.URI) for r in relations]
            else:
                raise ValueError("Failed to load RDF data into space")
                
        except Exception as e:
            self.logger.error(f"Failed to store relations in space: {e}")
            raise
    
    def _get_relations_count(self, space, graph_id: str, entity_source_uri: Optional[str],
                           entity_destination_uri: Optional[str], relation_type_uri: Optional[str],
                           direction: str) -> int:
        """Get total count of relations matching filters."""
        try:
            # Build count query (similar to list query but with COUNT)
            count_query = self._build_count_relations_query(
                graph_id, entity_source_uri, entity_destination_uri, 
                relation_type_uri, direction
            )
            
            # Execute count query
            result = space.query_sparql(count_query)
            
            # Extract count from results
            bindings = result.get('bindings', [])
            if bindings and len(bindings) > 0:
                count_value = bindings[0].get('count', {}).get('value', '0')
                # Handle XSD integer format like "1"^^<http://www.w3.org/2001/XMLSchema#integer>
                if isinstance(count_value, str):
                    # Extract just the number part before ^^
                    if '^^' in count_value:
                        count_value = count_value.split('^^')[0].strip('"')
                    # Remove quotes if present
                    count_value = count_value.strip('"')
                try:
                    return int(count_value)
                except ValueError:
                    self.logger.warning(f"Could not parse count value: {count_value}")
                    return 0
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Failed to get relations count: {e}")
            return 0
    
    def _get_vitalsigns_context(self) -> Dict[str, Any]:
        """Get VitalSigns namespace context."""
        # TODO: Use proper VitalSigns context
        return {
            "@vocab": "http://vital.ai/ontology/vital-core#",
            "haley": "http://vital.ai/ontology/haley-ai-kg#"
        }
    
    # Additional helper methods will be implemented in subsequent tasks
    def _build_get_relation_query(self, graph_id: str, relation_uri: str) -> str:
        """Build SPARQL query for getting specific relation."""
        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital: <http://vital.ai/ontology/vital-core#>",
            "",
            "SELECT ?relation ?source ?destination ?type WHERE {"
        ]
        
        # Add graph context if specified
        if graph_id:
            query_parts.append(f"    GRAPH <{graph_id}> {{")
            indent = "        "
        else:
            indent = "    "
        
        # Specific relation pattern
        query_parts.extend([
            f"{indent}BIND(<{relation_uri}> AS ?relation)",
            f"{indent}?relation a haley:Edge_hasKGRelation .",
            f"{indent}?relation vital:hasEdgeSource ?source .",
            f"{indent}?relation vital:hasEdgeDestination ?destination .",
            f"{indent}?relation haley:hasKGRelationType ?type ."
        ])
        
        # Close graph context if specified
        if graph_id:
            query_parts.append("    }")
        
        query_parts.append("}")
        
        return "\n".join(query_parts)
    
    def _clean_uri(self, uri_value: str) -> str:
        """Clean URI by removing < > brackets if present."""
        if isinstance(uri_value, str):
            # Strip < > brackets that might be added by RDF serialization
            uri_value = uri_value.strip('<>')
        return uri_value
    
    def _build_delete_relation_query(self, graph_id: str, relation_uri: str) -> str:
        """Build SPARQL DELETE query for specific relation."""
        query_parts = [
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>",
            "PREFIX vital: <http://vital.ai/ontology/vital-core#>",
            ""
        ]
        
        if graph_id:
            query_parts.extend([
                f"DELETE {{",
                f"    GRAPH <{graph_id}> {{",
                f"        <{relation_uri}> ?p ?o .",
                f"    }}",
                f"}}",
                f"WHERE {{",
                f"    GRAPH <{graph_id}> {{",
                f"        <{relation_uri}> ?p ?o .",
                f"    }}",
                f"}}"
            ])
        else:
            query_parts.extend([
                f"DELETE {{",
                f"    <{relation_uri}> ?p ?o .",
                f"}}",
                f"WHERE {{",
                f"    <{relation_uri}> ?p ?o .",
                f"}}"
            ])
        
        return "\n".join(query_parts)
    
    def _validate_relations_exist(self, space_id: str, graph_id: str, relations: List[Edge_hasKGRelation]) -> None:
        """Validate that relations exist for update operations."""
        if not self.space_manager:
            raise ValueError("Space manager not available")
        
        space = self.space_manager.get_space(space_id)
        if not space:
            raise ValueError(f"Space {space_id} not found")
        
        for relation in relations:
            # Build query to check if relation exists
            check_query = self._build_get_relation_query(graph_id, str(relation.URI))
            
            try:
                result = space.query_sparql(check_query)
                bindings = result.get('bindings', [])
                
                if not bindings:
                    raise ValueError(f"Relation {relation.URI} does not exist and cannot be updated")
                    
            except Exception as e:
                self.logger.warning(f"Could not validate existence of relation {relation.URI}: {e}")
                # Continue with update attempt even if validation fails
    
    def _update_relations_in_space(self, space_id: str, graph_id: str, relations: List[Edge_hasKGRelation]) -> List[str]:
        """Update relations in space."""
        try:
            # For update, we delete the old relations and insert new ones
            relation_uris = [str(r.URI) for r in relations]
            
            # Delete existing relations
            deleted_count = self._delete_relations_from_space(space_id, graph_id, relation_uris)
            self.logger.info(f"Deleted {deleted_count} existing relations for update")
            
            # Insert updated relations
            updated_uris = self._store_relations_in_space(space_id, graph_id, relations)
            
            return updated_uris
            
        except Exception as e:
            self.logger.error(f"Failed to update relations in space: {e}")
            raise
    
    def _get_existing_relation_uris(self, space_id: str, graph_id: str, relations: List[Edge_hasKGRelation]) -> List[str]:
        """Get URIs of relations that already exist."""
        existing_uris = []
        
        if not self.space_manager:
            return existing_uris
        
        space = self.space_manager.get_space(space_id)
        if not space:
            return existing_uris
        
        for relation in relations:
            try:
                # Check if relation exists
                check_query = self._build_get_relation_query(graph_id, str(relation.URI))
                result = space.query_sparql(check_query)
                bindings = result.get('bindings', [])
                
                if bindings:
                    existing_uris.append(str(relation.URI))
                    
            except Exception as e:
                self.logger.warning(f"Could not check existence of relation {relation.URI}: {e}")
                continue
        
        return existing_uris
    
    def _delete_relations_from_space(self, space_id: str, graph_id: str, relation_uris: List[str]) -> int:
        """Delete relations from space."""
        try:
            if not self.space_manager:
                raise ValueError("Space manager not available")
            
            space = self.space_manager.get_space(space_id)
            if not space:
                raise ValueError(f"Space {space_id} not found")
            
            deleted_count = 0
            
            for relation_uri in relation_uris:
                # Build DELETE query for specific relation
                delete_query = self._build_delete_relation_query(graph_id, relation_uri)
                
                try:
                    # Execute delete query - try different methods
                    if hasattr(space, 'update_sparql'):
                        result = space.update_sparql(delete_query)
                    elif hasattr(space, 'query_sparql'):
                        # Some implementations use query_sparql for updates too
                        result = space.query_sparql(delete_query)
                    else:
                        self.logger.warning(f"No SPARQL update method available for deletion")
                        continue
                    
                    if result:
                        deleted_count += 1
                        self.logger.info(f"Deleted relation: {relation_uri}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete relation {relation_uri}: {e}")
                    continue
            
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to delete relations from space: {e}")
            return 0
    
    def _build_query_relations_sparql(self, graph_id: str, criteria, page_size: int, offset: int) -> str:
        """Build complex SPARQL query from criteria."""
        # Use the same logic as list_relations but with criteria object
        return self._build_list_relations_query(
            graph_id=graph_id,
            entity_source_uri=criteria.entity_source_uri,
            entity_destination_uri=criteria.entity_destination_uri,
            relation_type_uri=criteria.relation_type_uri,
            direction=criteria.direction,
            page_size=page_size,
            offset=offset
        )
    
    def _extract_relation_uris_from_sparql_results(self, result: Dict[str, Any]) -> List[str]:
        """Extract relation URIs from SPARQL results."""
        relation_uris = []
        
        # Handle SPARQL result format (bindings)
        bindings = result.get('bindings', [])
        
        for binding in bindings:
            try:
                relation_uri = binding.get('relation', {}).get('value')
                if relation_uri:
                    relation_uris.append(self._clean_uri(relation_uri))
            except Exception as e:
                self.logger.warning(f"Failed to extract relation URI from binding: {e}")
                continue
        
        return relation_uris
    
    def _get_query_relations_count(self, space, graph_id: str, criteria) -> int:
        """Get total count for query results."""
        # Use the same logic as get_relations_count but with criteria object
        return self._get_relations_count(
            space=space,
            graph_id=graph_id,
            entity_source_uri=criteria.entity_source_uri,
            entity_destination_uri=criteria.entity_destination_uri,
            relation_type_uri=criteria.relation_type_uri,
            direction=criteria.direction
        )
