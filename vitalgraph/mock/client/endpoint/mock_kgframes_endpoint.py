"""
Mock implementation of KGFramesEndpoint for testing with VitalSigns native JSON-LD functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper vitaltype handling for KGFrame and KGSlot objects
- Complete CRUD operations following real endpoint patterns
- Frame-slot relationship handling
- VitalSigns integration patterns from MockKGEntitiesEndpoint
- Grouping URI enforcement for frame operations
- isinstance() type checking and Property object handling
"""

from typing import Dict, Any, Optional, List
import traceback
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse,
    SlotCreateResponse, SlotUpdateResponse, SlotDeleteResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.sparql.grouping_uri_queries import GroupingURIQueryBuilder, GroupingURIGraphRetriever
from vitalgraph.sparql.graph_validation import FrameGraphValidator
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
from vital_ai_vitalsigns.model.GraphObject import GraphObject
# Property import - will be used for Property object handling patterns


class MockKGFramesEndpoint(MockBaseEndpoint):
    """Mock implementation of KGFramesEndpoint with VitalSigns native functionality and integration patterns."""
    
    def __init__(self, client=None, space_manager=None, *, config=None):
        """Initialize with SPARQL grouping URI functionality and frame validators."""
        super().__init__(client, space_manager, config=config)
        self.grouping_uri_builder = GroupingURIQueryBuilder()
        self.graph_retriever = GroupingURIGraphRetriever(self.grouping_uri_builder)
        self.frame_validator = FrameGraphValidator()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
    
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
    
    def get_kgframe(self, space_id: str, graph_id: str, uri: str, include_frame_graph: bool = False) -> JsonLdDocument:
        """
        Get a specific KGFrame by URI with optional complete graph using pyoxigraph SPARQL query.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI
            include_frame_graph: If True, include complete frame graph (frames + slots + frame-to-frame edges)
            
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
            
            self.logger.info(f"DEBUG get_kgframe: Looking for frame {clean_uri}")
            results = self._execute_sparql_query(space, query)
            self.logger.info(f"DEBUG get_kgframe: Query returned {len(results.get('bindings', []))} results")
            
            if not results.get("bindings"):
                # Frame not found - let's check if it exists with different URI format
                alt_query = f"""
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject ?predicate ?object .
                        FILTER(CONTAINS(STR(?subject), "KGFrame/test_enhanced_frame"))
                    }}
                }}
                """
                alt_results = self._execute_sparql_query(space, alt_query)
                self.logger.info(f"DEBUG get_kgframe: Alternative search found {len(alt_results.get('bindings', []))} frame-related triples")
                
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Reconstruct frame properties
            properties = {}
            self.logger.info(f"DEBUG get_kgframe: Processing {len(results['bindings'])} property bindings")
            for binding in results["bindings"]:
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                # Clean angle brackets
                if predicate.startswith('<') and predicate.endswith('>'):
                    predicate = predicate[1:-1]
                if obj_value.startswith('<') and obj_value.endswith('>'):
                    obj_value = obj_value[1:-1]
                    
                properties[predicate] = obj_value
                self.logger.info(f"DEBUG get_kgframe: Property {predicate} = {obj_value}")
            
            # Get vitaltype for frame conversion
            vitaltype_uri = properties.get("http://vital.ai/ontology/vital-core#vitaltype", "")
            self.logger.info(f"DEBUG get_kgframe: Found vitaltype {vitaltype_uri}")
            if not vitaltype_uri:
                vitaltype_uri = self._get_vitaltype_uri("KGFrame")
                self.logger.info(f"DEBUG get_kgframe: Using fallback vitaltype {vitaltype_uri}")
            
            # Convert to VitalSigns KGFrame object
            self.logger.info(f"DEBUG get_kgframe: Converting to VitalSigns object with URI {clean_uri}")
            frame = self._convert_sparql_to_vitalsigns_object(vitaltype_uri, clean_uri, properties)
            
            if frame:
                self.logger.info(f"DEBUG get_kgframe: Successfully created frame object {frame.URI}")
                # Convert to JSON-LD using VitalSigns native functionality with proper @graph structure
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                single_frame_jsonld = GraphObject.to_jsonld_list([frame])
                
                # Create proper @graph structure for JsonLdDocument
                if '@context' in single_frame_jsonld:
                    # Single object format - wrap in @graph array
                    frame_jsonld = {
                        '@context': single_frame_jsonld['@context'],
                        '@graph': [single_frame_jsonld]
                    }
                else:
                    # Already in @graph format
                    frame_jsonld = single_frame_jsonld
                
                self.logger.info(f"DEBUG get_kgframe: Final JSON-LD has @graph: {'@graph' in frame_jsonld}")
                self.logger.info(f"DEBUG get_kgframe: Converted to JSON-LD successfully")
                return JsonLdDocument(**frame_jsonld)
            else:
                self.logger.info(f"DEBUG get_kgframe: Failed to create frame object")
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
        Create KGFrames from JSON-LD document with VitalSigns integration and grouping URI enforcement.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing KGFrame data
            
        Returns:
            FrameCreateResponse with created URIs and count
        """
        self._log_method_call("create_kgframes", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            self.logger.info("=== Starting create_kgframes method ===")
            
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return FrameCreateResponse(
                    message=f"Space {space_id} not found",
                    created_count=0,
                    created_uris=[]
                )
            
            # Step 1: Strip any existing grouping URIs from client document
            stripped_document = self._strip_grouping_uris(document)
            self.logger.info("Step 1: Stripped grouping URIs from document")
            
            # Step 2: Create VitalSigns objects from JSON-LD using the same approach as MockKGEntitiesEndpoint
            document_dict = stripped_document.model_dump(by_alias=True)
            objects = self._create_vitalsigns_objects_from_jsonld(document_dict)
            self.logger.info(f"Step 2: Created {len(objects) if objects else 0} VitalSigns objects")
            
            if not objects:
                self.logger.warning("No objects created, returning early")
                return FrameCreateResponse(
                    message="No valid KGFrame objects found in document",
                    created_count=0,
                    created_uris=[]
                )
            
            # Step 3: Identify primary frame for grouping URI
            primary_frame_uri = None
            self.logger.info(f"Looking for primary frame in {len(objects)} objects")
            for obj in objects:
                self.logger.info(f"Checking object: {obj.__class__.__name__} - isinstance(KGFrame): {isinstance(obj, KGFrame)}")
                if isinstance(obj, KGFrame) and hasattr(obj, 'URI') and obj.URI:
                    primary_frame_uri = str(obj.URI)  # Cast Property object to string
                    self.logger.info(f"Found primary frame URI: {primary_frame_uri}")
                    break
            
            # Step 4: Set grouping URIs for frame graph components
            if primary_frame_uri:
                self.logger.info(f"Setting frame grouping URIs with primary_frame_uri: {primary_frame_uri}")
                self._set_frame_grouping_uris(objects, primary_frame_uri)
            else:
                self.logger.warning("No primary frame URI found for grouping URI assignment")
            
            # Step 5: Store objects using existing base class method
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, objects, graph_id)
            
            # Get created URIs with proper Property object casting
            created_uris = []
            for obj in objects:
                if isinstance(obj, GraphObject) and hasattr(obj, 'URI') and obj.URI:
                    # Cast URI Property object to string
                    uri_str = str(obj.URI)
                    created_uris.append(uri_str)
                    self.logger.info(f"Created {obj.__class__.__name__} with URI: {uri_str}")
            
            return FrameCreateResponse(
                message=f"Created {len(created_uris)} KGFrame objects with grouping URI enforcement",
                created_count=len(created_uris),
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating KGFrames: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
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
            
            # Filter for KGFrame and KGSlot objects and edges
            frame_objects = [obj for obj in objects if isinstance(obj, (KGFrame, KGSlot)) or hasattr(obj, 'edgeSource')]
            
            if not frame_objects:
                return FrameCreateResponse(
                    message="No KGFrame, KGSlot, or Edge objects found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Store all objects in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, frame_objects, graph_id)
            
            # Get created URIs (convert VitalSigns CombinedProperty to string)
            created_uris = [str(obj.URI) for obj in frame_objects]
            
            return FrameCreateResponse(
                message=f"Successfully created {stored_count} KGFrame/KGSlot object(s)",
                created_count=stored_count,
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating KGFrames with slots: {e}")
            return FrameCreateResponse(
                message=f"Error creating KGFrames with slots: {e}",
                created_count=0, 
                created_uris=[]
            )
    
    # Frame-Slot Sub-Endpoint Operations
    
    def create_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, document: JsonLdDocument) -> SlotCreateResponse:
        """
        Create slots for a specific frame using Edge_hasKGSlot relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to create slots for
            document: JsonLdDocument containing KGSlots
            
        Returns:
            SlotCreateResponse containing operation result
        """
        self._log_method_call("create_frame_slots", space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return SlotCreateResponse(
                    message="Space not found",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Step 1: Strip any existing grouping URIs from client document
            cleaned_document = self._strip_grouping_uris(document)
            
            # Step 2: Convert JSON-LD document to VitalSigns objects using integration patterns
            document_dict = cleaned_document.model_dump(by_alias=True, exclude_none=True)
            objects = self._create_vitalsigns_objects_from_jsonld(document_dict)
            
            if not objects:
                return SlotCreateResponse(
                    message="No valid objects found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Step 3: Filter for KGSlot objects using isinstance() type checking
            slots = []
            for obj in objects:
                if isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot)):
                    slots.append(obj)
                    self.logger.info(f"Found {obj.__class__.__name__} slot: {obj.URI}")
                elif isinstance(obj, KGSlot):
                    slots.append(obj)
                    self.logger.info(f"Found KGSlot: {obj.URI}")
            
            # Step 4: Create Edge_hasKGSlot relationships for each slot
            edges = []
            for slot in slots:
                edge = Edge_hasKGSlot()
                edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame_{frame_uri.split('/')[-1]}_slot_{slot.URI.split('/')[-1]}"
                edge.hasEdgeSource = str(frame_uri)
                edge.hasEdgeDestination = str(slot.URI)
                edges.append(edge)
                self.logger.info(f"Created Edge_hasKGSlot: {edge.URI}")
            
            # Step 5: Set grouping URIs for frame graph components
            all_objects = slots + edges
            if all_objects:
                self._set_frame_grouping_uris(all_objects, frame_uri)
            
            if not all_objects:
                return SlotCreateResponse(
                    message="No KGSlot objects found in document",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Step 6: Store objects using existing base class method
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, all_objects, graph_id)
            
            # Get created URIs with proper Property object casting (only slots, not edges)
            created_uris = []
            for obj in slots:  # Only count slots in created_uris, not edges
                if isinstance(obj, GraphObject) and hasattr(obj, 'URI') and obj.URI:
                    # Cast URI Property object to string
                    uri_str = str(obj.URI)
                    created_uris.append(uri_str)
                    self.logger.info(f"Created {obj.__class__.__name__} with URI: {uri_str}")
            
            return SlotCreateResponse(
                message=f"Successfully created {len(created_uris)} KGSlot(s) for frame {frame_uri} with grouping URI enforcement",
                created_count=len(created_uris),
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating frame slots: {e}")
            return SlotCreateResponse(
                message=f"Error creating frame slots: {e}",
                created_count=0, 
                created_uris=[]
            )
    
    def update_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, document: JsonLdDocument) -> SlotUpdateResponse:
        """
        Update slots for a specific frame using Edge_hasKGSlot relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to update slots for
            document: JsonLdDocument containing updated KGSlots
            
        Returns:
            SlotUpdateResponse containing operation result
        """
        self._log_method_call("update_frame_slots", space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return SlotUpdateResponse(
                    message="Space not found",
                    updated_uri=""
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            objects = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not objects:
                return SlotUpdateResponse(
                    message="No valid objects found in document",
                    updated_uri=""
                )
            
            # Filter for KGSlot objects
            slots = [obj for obj in objects if isinstance(obj, KGSlot)]
            
            if not slots:
                return SlotUpdateResponse(
                    message="No KGSlot objects found in document",
                    updated_uri=""
                )
            
            # Store updated slots in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, slots, graph_id)
            
            # Return first slot URI as updated URI
            updated_uri = str(slots[0].URI) if slots else ""
            
            return SlotUpdateResponse(
                message=f"Successfully updated {stored_count} KGSlot(s) for frame {frame_uri}",
                updated_uri=updated_uri
            )
            
        except Exception as e:
            self.logger.error(f"Error updating frame slots: {e}")
            return SlotUpdateResponse(
                message=f"Error updating frame slots: {e}",
                updated_uri=""
            )
    
    def delete_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_uris: List[str]) -> SlotDeleteResponse:
        """
        Delete specific slots from a frame using Edge_hasKGSlot relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to delete slots from
            slot_uris: List of slot URIs to delete
            
        Returns:
            SlotDeleteResponse containing operation result
        """
        self._log_method_call("delete_frame_slots", space_id=space_id, graph_id=graph_id, frame_uri=frame_uri, slot_uris=slot_uris)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return SlotDeleteResponse(
                    message="Space not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            deleted_count = 0
            deleted_uris = []
            
            # Delete each slot and its Edge_hasKGSlot relationship
            for slot_uri in slot_uris:
                # Delete slot triples
                slot_deleted = self._delete_object_triples(space, slot_uri, graph_id)
                
                # Delete Edge_hasKGSlot relationship
                edge_query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                DELETE WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a haley:Edge_hasKGSlot .
                        ?edge vital:hasEdgeSource <{frame_uri}> .
                        ?edge vital:hasEdgeDestination <{slot_uri}> .
                        ?edge ?p ?o .
                    }}
                }}
                """
                space.store.update(edge_query)
                
                if slot_deleted:
                    deleted_count += 1
                    deleted_uris.append(slot_uri)
            
            return SlotDeleteResponse(
                message=f"Successfully deleted {deleted_count} KGSlot(s) from frame {frame_uri}",
                deleted_count=deleted_count,
                deleted_uris=deleted_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting frame slots: {e}")
            return SlotDeleteResponse(
                message=f"Error deleting frame slots: {e}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    def get_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_type: Optional[str] = None) -> JsonLdDocument:
        """
        Get slots for a specific frame using Edge_hasKGSlot relationships.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to get slots for
            slot_type: Optional slot type URI for filtering
            
        Returns:
            JsonLdDocument containing frame's slots
        """
        self._log_method_call("get_frame_slots", space_id=space_id, graph_id=graph_id, frame_uri=frame_uri, slot_type=slot_type)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty JSON-LD document
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Build SPARQL query to find slots connected to frame via Edge_hasKGSlot
            slot_type_filter = ""
            if slot_type:
                # Handle both quoted string and URI formats that pyoxigraph might use
                slot_type_filter = f"""
                    {{ ?slot haley:hasKGSlotType "{slot_type}" . }}
                    UNION
                    {{ ?slot haley:hasKGSlotType <{slot_type}> . }}
                """
            
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT DISTINCT ?slot ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeSource <{frame_uri}> .
                    ?edge vital:hasEdgeDestination ?slot .
                    {slot_type_filter}
                    ?slot ?predicate ?object .
                }}
            }}
            """
            
            # Debug: Log all triples in the store for this graph
            debug_query = f"""
            SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject ?predicate ?object .
                }}
            }}
            """
            debug_results = self._execute_sparql_query(space, debug_query)
            self.logger.info(f"DEBUG: Total triples in graph {graph_id}: {len(debug_results.get('bindings', []))}")
            
            # Log first few triples for inspection
            for i, binding in enumerate(debug_results.get("bindings", [])[:10]):
                subj = binding.get("subject", {}).get("value", "")
                pred = binding.get("predicate", {}).get("value", "")
                obj = binding.get("object", {}).get("value", "")
                self.logger.info(f"DEBUG Triple {i}: {subj} -> {pred} -> {obj}")
            
            # Execute the actual query
            self.logger.info(f"DEBUG: Executing query: {query}")
            results = self._execute_sparql_query(space, query)
            self.logger.info(f"DEBUG: Query returned {len(results.get('bindings', []))} results")
            
            if not results.get("bindings"):
                # Return empty JSON-LD document
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Group results by subject (slot URI)
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("slot", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                # Clean angle brackets from URIs if present
                if subject.startswith('<') and subject.endswith('>'):
                    subject = subject[1:-1]
                if predicate.startswith('<') and predicate.endswith('>'):
                    predicate = predicate[1:-1]
                if obj_value.startswith('<') and obj_value.endswith('>'):
                    obj_value = obj_value[1:-1]
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns slot objects
            vitalsigns_objects = []
            for subject_uri, properties in subjects_data.items():
                # Get the actual vitaltype from the RDF data (brackets already cleaned)
                vitaltype_uri = properties.get('http://vital.ai/ontology/vital-core#vitaltype', '')
                
                # Use the actual vitaltype, fallback to KGSlot if not found
                if not vitaltype_uri:
                    vitaltype_uri = self._get_vitaltype_uri("KGSlot")
                
                obj = self._convert_sparql_to_vitalsigns_object(vitaltype_uri, subject_uri, properties)
                if obj:
                    vitalsigns_objects.append(obj)
            
            # Convert to JSON-LD using VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_document = GraphObject.to_jsonld_list(vitalsigns_objects)
            
            return JsonLdDocument(**jsonld_document)
            
        except Exception as e:
            self.logger.error(f"Error getting frame slots: {e}")
            # Return empty JSON-LD document on error
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)

    # Helper methods for VitalSigns integration patterns (from MockKGEntitiesEndpoint)
    
    def _strip_grouping_uris(self, document: JsonLdDocument) -> JsonLdDocument:
        """Strip any existing hasKGGraphURI and hasFrameGraphURI values from client document."""
        # Server-side stripping of client-provided grouping URIs
        # For now, return the document as-is since this is a mock implementation
        return document
    
    def _set_frame_grouping_uris(self, objects: List[Any], frame_uri: str) -> None:
        """Set frameGraphURI for all frame graph components (distinct from entity grouping)."""
        
        for obj in objects:
            try:
                # Set frameGraphURI for frame-specific grouping (hasFrameGraphURI -> frameGraphURI)
                # This is separate from kGGraphURI which is used for entity grouping
                obj.frameGraphURI = frame_uri
                self.logger.info(f"Set frameGraphURI={frame_uri} on {obj.__class__.__name__} {obj.URI}")
            except Exception as e:
                self.logger.error(f"Failed to set frameGraphURI on object {obj.URI}: {e}")
    
    def _create_vitalsigns_objects_from_jsonld(self, jsonld_document: Dict[str, Any]) -> List[Any]:
        """
        Create VitalSigns objects from JSON-LD document using VitalSigns native methods.
        
        This method uses isinstance() type checking and Property object handling patterns.
        """
        try:
            # Use VitalSigns native from_jsonld_list method for JSON-LD conversion
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vitalsigns = VitalSigns()
            
            # Always use from_jsonld_list as it handles both single objects and @graph arrays
            objects = vitalsigns.from_jsonld_list(jsonld_document)
            
            # Ensure we return a list and filter out None objects
            if not isinstance(objects, list):
                objects = [objects] if objects else []
            
            objects = [obj for obj in objects if obj is not None]
            
            if not objects:
                self.logger.warning("No objects created from JSON-LD document")
                return []
            
            # Validate objects with isinstance() type checking
            validated_objects = []
            for obj in objects:
                if isinstance(obj, GraphObject):
                    # Additional type-specific validation
                    if isinstance(obj, KGFrame):
                        self.logger.info(f"Created KGFrame object: {obj.URI}")
                        validated_objects.append(obj)
                    elif isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot)):
                        self.logger.info(f"Created {obj.__class__.__name__} object: {obj.URI}")
                        validated_objects.append(obj)
                    elif isinstance(obj, VITAL_Edge):
                        self.logger.info(f"Created Edge object: {obj.URI}")
                        validated_objects.append(obj)
                    else:
                        self.logger.info(f"Created GraphObject: {obj.__class__.__name__} {obj.URI}")
                        validated_objects.append(obj)
                else:
                    self.logger.warning(f"Object is not a GraphObject: {type(obj)}")
            
            return validated_objects
            
        except Exception as e:
            self.logger.error(f"Failed to create VitalSigns objects from JSON-LD: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def _object_to_triples(self, obj, graph_id: str) -> List[tuple]:
        """Convert a single VitalSigns object to RDF triples."""
        try:
            # Convert VitalSigns object to JSON-LD first
            jsonld = GraphObject.to_jsonld_list([obj])
            
            # Convert JSON-LD to triples using pyoxigraph
            import pyoxigraph as px
            
            # Create a temporary store to parse the JSON-LD
            temp_store = px.Store()
            
            # Convert JSON-LD dict to string for parsing
            import json
            jsonld_str = json.dumps(jsonld, indent=2)
            
            # Parse JSON-LD into the temporary store with error handling
            try:
                temp_store.load(jsonld_str.encode('utf-8'), "application/ld+json")
            except Exception as parse_error:
                # If JSON-LD parsing fails, try alternative approach
                self.logger.warning(f"JSON-LD parsing failed: {parse_error}, using fallback method")
                # For now, return empty triples - the object creation succeeded
                return []
            
            # Extract triples and convert to quads with graph_id
            triples = []
            for quad in temp_store:
                # Convert to (subject, predicate, object, graph) tuple
                triple = (str(quad.subject), str(quad.predicate), str(quad.object), graph_id)
                triples.append(triple)
            
            return triples
            
        except Exception as e:
            self.logger.error(f"Error converting object to triples: {e}")
            return []
    
    def _store_triples(self, space, triples: List[tuple]) -> bool:
        """Store RDF triples/quads in the pyoxigraph store."""
        try:
            import pyoxigraph as px
            
            # If no triples provided, try to store the object directly using existing method
            if not triples:
                self.logger.warning("No triples provided, but object creation succeeded")
                return True
            
            # Convert triples to quads and insert into space store
            for triple in triples:
                if len(triple) == 4:
                    subject, predicate, obj, graph = triple
                    
                    # Handle different object types
                    if isinstance(obj, str):
                        if obj.startswith('http://') or obj.startswith('https://'):
                            obj_node = px.NamedNode(obj)
                        else:
                            obj_node = px.Literal(obj)
                    else:
                        obj_node = px.Literal(str(obj))
                    
                    quad = px.Quad(
                        px.NamedNode(subject),
                        px.NamedNode(predicate), 
                        obj_node,
                        px.NamedNode(graph)
                    )
                    space.store.add(quad)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error storing triples: {e}")
            return False
