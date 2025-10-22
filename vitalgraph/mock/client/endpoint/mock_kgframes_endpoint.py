"""
Mock implementation of KGFramesEndpoint for testing with VitalSigns native JSON-LD functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper vitaltype handling for KGFrame and KGSlot objects
- Complete CRUD operations following real endpoint patterns
- Frame-slot relationship handling
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot


class MockKGFramesEndpoint(MockBaseEndpoint):
    """Mock implementation of KGFramesEndpoint with VitalSigns native functionality."""
    
    def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> FramesResponse:
        """
        List KGFrames with pagination and optional search using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of frames per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            FramesResponse with VitalSigns native JSON-LD document
        """
        self._log_method_call("list_kgframes", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, search=search)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty response for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return FramesResponse(
                    frames=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Get KGFrame vitaltype URI
            kgframe_vitaltype = self._get_vitaltype_uri("KGFrame")
            
            # Build SPARQL query with optional search
            if search:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgframe_vitaltype}> .
                        ?subject ?predicate ?object .
                        ?subject vital:name ?name .
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
                        ?subject a <{kgframe_vitaltype}> .
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
                return FramesResponse(
                    frames=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Group results by subject to reconstruct frames
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns KGFrame objects
            frames = []
            for subject_uri, properties in subjects_data.items():
                frame = self._convert_sparql_to_vitalsigns_object(kgframe_vitaltype, subject_uri, properties)
                if frame:
                    frames.append(frame)
            
            # Get total count (separate query)
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject a <{kgframe_vitaltype}> .
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
            frames_jsonld = self._objects_to_jsonld_document(frames)
            
            return FramesResponse(
                frames=JsonLdDocument(**frames_jsonld),
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGFrames: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return FramesResponse(
                frames=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    def get_kgframe(self, space_id: str, graph_id: str, uri: str) -> JsonLdDocument:
        """
        Get a specific KGFrame by URI using pyoxigraph SPARQL query.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Frame URI
            
        Returns:
            JsonLdDocument with VitalSigns native JSON-LD conversion
        """
        self._log_method_call("get_kgframe", space_id=space_id, graph_id=graph_id, uri=uri)
        
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
            
            # Query for frame data
            query = f"""
            SELECT ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    <{clean_uri}> ?predicate ?object .
                }}
            }}
            """
            
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                # Frame not found
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Reconstruct frame properties
            properties = {}
            for binding in results["bindings"]:
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                properties[predicate] = obj_value
            
            # Convert to VitalSigns KGFrame object
            kgframe_vitaltype = self._get_vitaltype_uri("KGFrame")
            frame = self._convert_sparql_to_vitalsigns_object(kgframe_vitaltype, clean_uri, properties)
            
            if frame:
                # Convert to JSON-LD using VitalSigns native functionality
                frame_jsonld = frame.to_jsonld()
                return JsonLdDocument(**frame_jsonld)
            else:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
                
        except Exception as e:
            self.logger.error(f"Error getting KGFrame {uri}: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
    def create_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
        """
        Create KGFrames from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing KGFrame data
            
        Returns:
            FrameCreateResponse with created URIs and count
        """
        self._log_method_call("create_kgframes", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameCreateResponse(
                    message="Space not found",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            objects = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not objects:
                return FrameCreateResponse(
                    message="No valid objects found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Filter for KGFrame objects only
            kgframes = [obj for obj in objects if isinstance(obj, KGFrame)]
            
            if not kgframes:
                return FrameCreateResponse(
                    message="No KGFrame objects found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Store frames in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, kgframes, graph_id)
            
            # Get created URIs (convert VitalSigns CombinedProperty to string)
            created_uris = [str(frame.URI) for frame in kgframes]
            
            return FrameCreateResponse(
                message=f"Successfully created {stored_count} KGFrame(s)",
                created_count=stored_count,
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating KGFrames: {e}")
            return FrameCreateResponse(
                message=f"Error creating KGFrames: {e}",
                created_count=0, 
                created_uris=[]
            )
    
    def update_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameUpdateResponse:
        """
        Update KGFrames from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing updated KGFrame data
            
        Returns:
            FrameUpdateResponse with updated URI
        """
        self._log_method_call("update_kgframes", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameUpdateResponse(
                    message="Space not found",
                    updated_uri=""
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            objects = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not objects:
                return FrameUpdateResponse(
                    message="No valid objects found in document",
                    updated_uri=""
                )
            
            # Filter for KGFrame objects only
            kgframes = [obj for obj in objects if isinstance(obj, KGFrame)]
            
            if not kgframes:
                return FrameUpdateResponse(
                    message="No KGFrame objects found in document",
                    updated_uri=""
                )
            
            # Update frames in pyoxigraph (DELETE + INSERT pattern)
            updated_uri = None
            for frame in kgframes:
                # Delete existing triples for this frame
                if self._delete_quads_from_store(space, frame.URI, graph_id):
                    # Insert updated triples
                    if self._store_vitalsigns_objects_in_pyoxigraph(space, [frame], graph_id) > 0:
                        updated_uri = str(frame.URI)
                        break  # Return first successfully updated frame
            
            if updated_uri:
                return FrameUpdateResponse(
                    message=f"Successfully updated KGFrame: {updated_uri}",
                    updated_uri=updated_uri
                )
            else:
                return FrameUpdateResponse(
                    message="No KGFrames were updated",
                    updated_uri=""
                )
            
        except Exception as e:
            self.logger.error(f"Error updating KGFrames: {e}")
            return FrameUpdateResponse(
                message=f"Error updating KGFrames: {e}",
                updated_uri=""
            )
    
    def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> FrameDeleteResponse:
        """
        Delete a KGFrame by URI using pyoxigraph SPARQL DELETE.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Frame URI to delete
            
        Returns:
            FrameDeleteResponse with deletion count
        """
        self._log_method_call("delete_kgframe", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameDeleteResponse(
                    message="Space not found",
                    deleted_count=0
                )
            
            # Delete quads from pyoxigraph
            if self._delete_quads_from_store(space, uri, graph_id):
                return FrameDeleteResponse(
                    message=f"Successfully deleted KGFrame: {uri}",
                    deleted_count=1
                )
            else:
                return FrameDeleteResponse(
                    message=f"KGFrame not found: {uri}",
                    deleted_count=0
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting KGFrame {uri}: {e}")
            return FrameDeleteResponse(
                message=f"Error deleting KGFrame {uri}: {e}",
                deleted_count=0
            )
    
    def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> FrameDeleteResponse:
        """
        Delete multiple KGFrames by URI list using pyoxigraph batch operations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of URIs to delete
            
        Returns:
            FrameDeleteResponse with total deletion count
        """
        self._log_method_call("delete_kgframes_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameDeleteResponse(
                    message="Space not found",
                    deleted_count=0
                )
            
            # Parse URI list
            uris = [uri.strip() for uri in uri_list.split(',') if uri.strip()]
            
            if not uris:
                return FrameDeleteResponse(
                    message="No URIs provided",
                    deleted_count=0
                )
            
            # Delete each frame
            deleted_count = 0
            for uri in uris:
                if self._delete_quads_from_store(space, uri, graph_id):
                    deleted_count += 1
            
            return FrameDeleteResponse(
                message=f"Successfully deleted {deleted_count} of {len(uris)} KGFrame(s)",
                deleted_count=deleted_count
            )
            
        except Exception as e:
            self.logger.error(f"Error batch deleting KGFrames: {e}")
            return FrameDeleteResponse(
                message=f"Error batch deleting KGFrames: {e}",
                deleted_count=0
            )
    
    def get_kgframe_with_slots(self, space_id: str, graph_id: str, uri: str) -> JsonLdDocument:
        """
        Get a specific KGFrame with its associated slots using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Frame URI
            
        Returns:
            JsonLdDocument containing frame and its slots with VitalSigns native JSON-LD conversion
        """
        self._log_method_call("get_kgframe_with_slots", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Clean URI
            clean_uri = uri.strip('<>')
            
            # Query for frame and its slots
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        <{clean_uri}> ?predicate ?object .
                        BIND(<{clean_uri}> as ?subject)
                    }}
                    UNION
                    {{
                        ?subject haley:kGFrameSlotFrame <{clean_uri}> .
                        ?subject ?predicate ?object .
                    }}
                }}
            }}
            """
            
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Group results by subject
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns objects
            all_objects = []
            for subject_uri, properties in subjects_data.items():
                if subject_uri == clean_uri:
                    # This is the frame
                    kgframe_vitaltype = self._get_vitaltype_uri("KGFrame")
                    obj = self._convert_sparql_to_vitalsigns_object(kgframe_vitaltype, subject_uri, properties)
                else:
                    # This is a slot
                    kgslot_vitaltype = self._get_vitaltype_uri("KGSlot")
                    obj = self._convert_sparql_to_vitalsigns_object(kgslot_vitaltype, subject_uri, properties)
                
                if obj:
                    all_objects.append(obj)
            
            # Convert to JSON-LD document using VitalSigns
            objects_jsonld = self._objects_to_jsonld_document(all_objects)
            return JsonLdDocument(**objects_jsonld)
            
        except Exception as e:
            self.logger.error(f"Error getting KGFrame with slots {uri}: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
    def create_kgframes_with_slots(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
        """
        Create KGFrames with their associated slots from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing KGFrame and KGSlot data
            
        Returns:
            FrameCreateResponse with created URIs and count
        """
        self._log_method_call("create_kgframes_with_slots", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameCreateResponse(created_count=0, created_uris=[])
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            objects = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not objects:
                return FrameCreateResponse(created_count=0, created_uris=[])
            
            # Filter for KGFrame and KGSlot objects
            frame_objects = [obj for obj in objects if isinstance(obj, (KGFrame, KGSlot))]
            
            if not frame_objects:
                return FrameCreateResponse(created_count=0, created_uris=[])
            
            # Store all objects in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, frame_objects, graph_id)
            
            # Get created URIs
            created_uris = [obj.URI for obj in frame_objects]
            
            return FrameCreateResponse(
                created_count=stored_count,
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating KGFrames with slots: {e}")
            return FrameCreateResponse(created_count=0, created_uris=[])
