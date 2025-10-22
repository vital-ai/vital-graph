"""
Mock implementation of KGEntitiesEndpoint for testing with VitalSigns native JSON-LD functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper vitaltype handling for KGEntity objects
- Complete CRUD operations following real endpoint patterns
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgentities_model import EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument
from ai_haley_kg_domain.model.KGEntity import KGEntity


class MockKGEntitiesEndpoint(MockBaseEndpoint):
    """Mock implementation of KGEntitiesEndpoint with VitalSigns native functionality."""
    
    def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> EntitiesResponse:
        """
        List KGEntities with pagination and optional search using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of entities per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            EntitiesResponse with VitalSigns native JSON-LD document
        """
        self._log_method_call("list_kgentities", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, search=search)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty response for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return EntitiesResponse(
                    entities=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Get KGEntity vitaltype URI
            kgentity_vitaltype = self._get_vitaltype_uri("KGEntity")
            
            # Build SPARQL query with optional search
            if search:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgentity_vitaltype}> .
                        ?subject ?predicate ?object .
                        ?subject vital:hasName ?name .
                        FILTER(CONTAINS(LCASE(?name), LCASE("{search}")))
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgentity_vitaltype}> .
                        ?subject ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            
            # Execute query
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                # No results found
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return EntitiesResponse(
                    entities=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Group results by subject to reconstruct entities
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns KGEntity objects
            entities = []
            for subject_uri, properties in subjects_data.items():
                entity = self._convert_sparql_to_vitalsigns_object(kgentity_vitaltype, subject_uri, properties)
                if entity:
                    entities.append(entity)
            
            # Get total count (separate query)
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject a <{kgentity_vitaltype}> .
                }}
            }}
            """
            
            count_results = self._execute_sparql_query(space, count_query)
            total_count = 0
            if count_results.get("bindings"):
                count_value = count_results["bindings"][0].get("count", {}).get("value", "0")
                # Handle typed literals like "3"^^<http://www.w3.org/2001/XMLSchema#integer>
                if isinstance(count_value, str) and "^^" in count_value:
                    count_value = count_value.split("^^")[0].strip('"')
                total_count = int(count_value)
            
            # Convert to JSON-LD document using VitalSigns
            entities_jsonld = self._objects_to_jsonld_document(entities)
            
            return EntitiesResponse(
                entities=JsonLdDocument(**entities_jsonld),
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGEntities: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return EntitiesResponse(
                entities=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    def get_kgentity(self, space_id: str, graph_id: str, uri: str) -> JsonLdDocument:
        """
        Get a specific KGEntity by URI using pyoxigraph SPARQL query.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Entity URI
            
        Returns:
            JsonLdDocument with VitalSigns native JSON-LD conversion
        """
        self._log_method_call("get_kgentity", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty document for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Clean URI
            clean_uri = uri.strip('<>')
            
            # Query for entity data
            query = f"""
            SELECT ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    <{clean_uri}> ?predicate ?object .
                }}
            }}
            """
            
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                # Entity not found
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Reconstruct entity properties
            properties = {}
            for binding in results["bindings"]:
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                properties[predicate] = obj_value
            
            # Convert to VitalSigns KGEntity object
            kgentity_vitaltype = self._get_vitaltype_uri("KGEntity")
            entity = self._convert_sparql_to_vitalsigns_object(kgentity_vitaltype, clean_uri, properties)
            
            if entity:
                # Convert to JSON-LD using VitalSigns native functionality
                entity_jsonld = entity.to_jsonld()
                return JsonLdDocument(**entity_jsonld)
            else:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
                
        except Exception as e:
            self.logger.error(f"Error getting KGEntity {uri}: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
    def create_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument) -> EntityCreateResponse:
        """
        Create KGEntities from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing KGEntity data
            
        Returns:
            EntityCreateResponse with created URIs and count
        """
        self._log_method_call("create_kgentities", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityCreateResponse(
                    message="Space not found",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            entities = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not entities:
                return EntityCreateResponse(
                    message="No valid entities found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Filter for KGEntity objects only
            kgentities = [obj for obj in entities if isinstance(obj, KGEntity)]
            
            if not kgentities:
                return EntityCreateResponse(
                    message="No KGEntity objects found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Store entities in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, kgentities, graph_id)
            
            # Get created URIs (convert VitalSigns CombinedProperty to string)
            created_uris = [str(entity.URI) for entity in kgentities]
            
            return EntityCreateResponse(
                message=f"Successfully created {stored_count} KGEntity(s)",
                created_count=stored_count,
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating KGEntities: {e}")
            return EntityCreateResponse(
                message=f"Error creating KGEntities: {e}",
                created_count=0, 
                created_uris=[]
            )
    
    def update_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument) -> EntityUpdateResponse:
        """
        Update KGEntities from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing updated KGEntity data
            
        Returns:
            EntityUpdateResponse with updated URI
        """
        self._log_method_call("update_kgentities", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityUpdateResponse(
                    message="Space not found",
                    updated_uri=""
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            entities = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not entities:
                return EntityUpdateResponse(
                    message="No valid entities found in document",
                    updated_uri=""
                )
            
            # Filter for KGEntity objects only
            kgentities = [obj for obj in entities if isinstance(obj, KGEntity)]
            
            if not kgentities:
                return EntityUpdateResponse(
                    message="No KGEntity objects found in document",
                    updated_uri=""
                )
            
            # Update entities in pyoxigraph (DELETE + INSERT pattern)
            updated_uri = None
            for entity in kgentities:
                # Delete existing triples for this entity
                if self._delete_quads_from_store(space, entity.URI, graph_id):
                    # Insert updated triples
                    if self._store_vitalsigns_objects_in_pyoxigraph(space, [entity], graph_id) > 0:
                        updated_uri = str(entity.URI)
                        break  # Return first successfully updated entity
            
            if updated_uri:
                return EntityUpdateResponse(
                    message=f"Successfully updated KGEntity: {updated_uri}",
                    updated_uri=updated_uri
                )
            else:
                return EntityUpdateResponse(
                    message="No KGEntities were updated",
                    updated_uri=""
                )
            
        except Exception as e:
            self.logger.error(f"Error updating KGEntities: {e}")
            return EntityUpdateResponse(
                message=f"Error updating KGEntities: {e}",
                updated_uri=""
            )
    
    def delete_kgentity(self, space_id: str, graph_id: str, uri: str) -> EntityDeleteResponse:
        """
        Delete a KGEntity by URI using pyoxigraph SPARQL DELETE.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Entity URI to delete
            
        Returns:
            EntityDeleteResponse with deletion count
        """
        self._log_method_call("delete_kgentity", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityDeleteResponse(
                    message="Space not found",
                    deleted_count=0
                )
            
            # Delete quads from pyoxigraph
            if self._delete_quads_from_store(space, uri, graph_id):
                return EntityDeleteResponse(
                    message=f"Successfully deleted KGEntity: {uri}",
                    deleted_count=1
                )
            else:
                return EntityDeleteResponse(
                    message=f"KGEntity not found: {uri}",
                    deleted_count=0
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting KGEntity {uri}: {e}")
            return EntityDeleteResponse(
                message=f"Error deleting KGEntity {uri}: {e}",
                deleted_count=0
            )
    
    def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list: str) -> EntityDeleteResponse:
        """
        Delete multiple KGEntities by URI list using pyoxigraph batch operations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of URIs to delete
            
        Returns:
            EntityDeleteResponse with total deletion count
        """
        self._log_method_call("delete_kgentities_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return EntityDeleteResponse(
                    message="Space not found",
                    deleted_count=0
                )
            
            # Parse URI list
            uris = [uri.strip() for uri in uri_list.split(',') if uri.strip()]
            
            if not uris:
                return EntityDeleteResponse(
                    message="No URIs provided",
                    deleted_count=0
                )
            
            # Delete each entity
            deleted_count = 0
            for uri in uris:
                if self._delete_quads_from_store(space, uri, graph_id):
                    deleted_count += 1
            
            return EntityDeleteResponse(
                message=f"Successfully deleted {deleted_count} of {len(uris)} KGEntity(s)",
                deleted_count=deleted_count
            )
            
        except Exception as e:
            self.logger.error(f"Error batch deleting KGEntities: {e}")
            return EntityDeleteResponse(
                message=f"Error batch deleting KGEntities: {e}",
                deleted_count=0
            )
    
    def get_kgentity_frames(self, space_id: str, graph_id: str, entity_uri: Optional[str] = None, 
                           page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> Dict[str, Any]:
        """
        Get frames associated with KGEntities using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Optional specific entity URI
            page_size: Number of frames per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            Dictionary with entity frames data
        """
        self._log_method_call("get_kgentity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, page_size=page_size, offset=offset, search=search)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return {"entity_frames": [], "total_count": 0}
            
            # Build SPARQL query to find frame relationships
            if entity_uri:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?frame ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        <{entity_uri}> haley:hasFrame ?frame .
                        ?frame ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?entity ?frame ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?entity a haley:KGEntity .
                        ?entity haley:hasFrame ?frame .
                        ?frame ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            
            results = self._execute_sparql_query(space, query)
            
            # Process results (simplified for now)
            entity_frames = []
            if results.get("bindings"):
                # Group and process frame data
                # This would need more sophisticated processing based on actual frame relationships
                entity_frames = [{"frame_uri": binding.get("frame", {}).get("value", "")} 
                               for binding in results["bindings"]]
            
            return {
                "entity_frames": entity_frames,
                "total_count": len(entity_frames)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting KGEntity frames: {e}")
            return {"entity_frames": [], "total_count": 0}
