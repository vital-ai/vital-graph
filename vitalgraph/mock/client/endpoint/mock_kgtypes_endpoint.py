"""
Mock implementation of KGTypesEndpoint for testing with VitalSigns native JSON-LD functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper vitaltype handling for KGType objects
- Complete CRUD operations following real endpoint patterns
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgtypes_model import (
    KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument
from ai_haley_kg_domain.model.KGType import KGType


class MockKGTypesEndpoint(MockBaseEndpoint):
    """Mock implementation of KGTypesEndpoint with VitalSigns native functionality."""
    
    def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> KGTypeListResponse:
        """
        List KGTypes with pagination and optional search using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of types per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            KGTypeListResponse with VitalSigns native JSON-LD document
        """
        self._log_method_call("list_kgtypes", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, search=search)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty response for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return KGTypeListResponse(
                    types=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Get KGType vitaltype URI
            kgtype_vitaltype = self._get_vitaltype_uri("KGType")
            
            # Build SPARQL query with optional search
            if search:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgtype_vitaltype}> .
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
                        ?subject a <{kgtype_vitaltype}> .
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
                return KGTypeListResponse(
                    types=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Group results by subject to reconstruct types
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns KGType objects
            types = []
            for subject_uri, properties in subjects_data.items():
                kgtype = self._convert_sparql_to_vitalsigns_object(kgtype_vitaltype, subject_uri, properties)
                if kgtype:
                    types.append(kgtype)
            
            # Get total count (separate query)
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject a <{kgtype_vitaltype}> .
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
            types_jsonld = self._objects_to_jsonld_document(types)
            
            return KGTypeListResponse(
                types=JsonLdDocument(**types_jsonld),
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGTypes: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return KGTypeListResponse(
                types=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> JsonLdDocument:
        """
        Get a specific KGType by URI using pyoxigraph SPARQL query.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Type URI
            
        Returns:
            JsonLdDocument with VitalSigns native JSON-LD conversion
        """
        self._log_method_call("get_kgtype", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty document for non-existent space
                empty_jsonld = self.vitalsigns.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Clean URI
            clean_uri = uri.strip('<>')
            
            # Query for type data
            query = f"""
            SELECT ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    <{clean_uri}> ?predicate ?object .
                }}
            }}
            """
            
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                # Type not found
                empty_jsonld = self.vitalsigns.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Reconstruct type properties
            properties = {}
            for binding in results["bindings"]:
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                properties[predicate] = obj_value
            
            # Convert to VitalSigns KGType object
            kgtype_vitaltype = self._get_vitaltype_uri("KGType")
            kgtype = self._convert_sparql_to_vitalsigns_object(kgtype_vitaltype, clean_uri, properties)
            
            if kgtype:
                # Convert to JSON-LD using VitalSigns native functionality
                type_jsonld = kgtype.to_jsonld()
                return JsonLdDocument(**type_jsonld)
            else:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
                
        except Exception as e:
            self.logger.error(f"Error getting KGType {uri}: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
    def create_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> KGTypeCreateResponse:
        """
        Create KGTypes from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing KGType data
            
        Returns:
            KGTypeCreateResponse with created URIs and count
        """
        self._log_method_call("create_kgtypes", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return KGTypeCreateResponse(
                    message="Space not found",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            types = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not types:
                return KGTypeCreateResponse(
                    message="No valid types found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Filter for KGType objects only
            kgtypes = [obj for obj in types if isinstance(obj, KGType)]
            
            if not kgtypes:
                return KGTypeCreateResponse(
                    message="No KGType objects found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Store types in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, kgtypes, graph_id)
            
            # Get created URIs (convert VitalSigns CombinedProperty to string)
            created_uris = [str(kgtype.URI) for kgtype in kgtypes]
            
            return KGTypeCreateResponse(
                message=f"Successfully created {stored_count} KGType(s)",
                created_count=stored_count,
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating KGTypes: {e}")
            return KGTypeCreateResponse(
                message=f"Error creating KGTypes: {e}",
                created_count=0, 
                created_uris=[]
            )
    
    def update_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> KGTypeUpdateResponse:
        """
        Update KGTypes from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing updated KGType data
            
        Returns:
            KGTypeUpdateResponse with updated URI
        """
        self._log_method_call("update_kgtypes", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return KGTypeUpdateResponse(
                    message="Space not found",
                    updated_uri=""
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            types = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not types:
                return KGTypeUpdateResponse(
                    message="No valid types found in document",
                    updated_uri=""
                )
            
            # Filter for KGType objects only
            kgtypes = [obj for obj in types if isinstance(obj, KGType)]
            
            if not kgtypes:
                return KGTypeUpdateResponse(
                    message="No KGType objects found in document",
                    updated_uri=""
                )
            
            # Update types in pyoxigraph (DELETE + INSERT pattern)
            updated_uri = None
            for kgtype in kgtypes:
                # Delete existing triples for this type
                if self._delete_quads_from_store(space, kgtype.URI, graph_id):
                    # Insert updated triples
                    if self._store_vitalsigns_objects_in_pyoxigraph(space, [kgtype], graph_id) > 0:
                        updated_uri = str(kgtype.URI)
                        break  # Return first successfully updated type
            
            if updated_uri:
                return KGTypeUpdateResponse(
                    message=f"Successfully updated KGType: {updated_uri}",
                    updated_uri=updated_uri
                )
            else:
                return KGTypeUpdateResponse(
                    message="No KGTypes were updated",
                    updated_uri=""
                )
            
        except Exception as e:
            self.logger.error(f"Error updating KGTypes: {e}")
            return KGTypeUpdateResponse(
                message=f"Error updating KGTypes: {e}",
                updated_uri=""
            )
    
    def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeDeleteResponse:
        """
        Delete a KGType by URI using pyoxigraph SPARQL DELETE.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Type URI to delete
            
        Returns:
            KGTypeDeleteResponse with deletion count
        """
        self._log_method_call("delete_kgtype", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return KGTypeDeleteResponse(
                    message="Space not found",
                    deleted_count=0
                )
            
            # Delete quads from pyoxigraph
            if self._delete_quads_from_store(space, uri, graph_id):
                return KGTypeDeleteResponse(
                    message=f"Successfully deleted KGType: {uri}",
                    deleted_count=1
                )
            else:
                return KGTypeDeleteResponse(
                    message=f"KGType not found: {uri}",
                    deleted_count=0
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting KGType {uri}: {e}")
            return KGTypeDeleteResponse(
                message=f"Error deleting KGType {uri}: {e}",
                deleted_count=0
            )
    
    def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> KGTypeDeleteResponse:
        """
        Delete multiple KGTypes by URI list using pyoxigraph batch operations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of URIs to delete
            
        Returns:
            KGTypeDeleteResponse with total deletion count
        """
        self._log_method_call("delete_kgtypes_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return KGTypeDeleteResponse(
                    message="Space not found",
                    deleted_count=0
                )
            
            # Parse URI list
            uris = [uri.strip() for uri in uri_list.split(',') if uri.strip()]
            
            if not uris:
                return KGTypeDeleteResponse(
                    message="No URIs provided",
                    deleted_count=0
                )
            
            # Delete each type
            deleted_count = 0
            for uri in uris:
                if self._delete_quads_from_store(space, uri, graph_id):
                    deleted_count += 1
            
            return KGTypeDeleteResponse(
                message=f"Successfully deleted {deleted_count} of {len(uris)} KGType(s)",
                deleted_count=deleted_count
            )
            
        except Exception as e:
            self.logger.error(f"Error batch deleting KGTypes: {e}")
            return KGTypeDeleteResponse(
                message=f"Error batch deleting KGTypes: {e}",
                deleted_count=0
            )
