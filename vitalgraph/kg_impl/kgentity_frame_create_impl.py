#!/usr/bin/env python3
"""
KGEntity Frame Create Processor Implementation

This module provides the KGEntityFrameCreateProcessor class for creating frames
and linking them to existing KGEntities following the kg_impl processor pattern.

REFACTORING SOURCE: Extracted from KGEntitiesEndpoint._create_or_update_frames()
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Domain model imports for edge creation
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame

# Backend adapter import
from vitalgraph.kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter


@dataclass
class FrameObjectCategories:
    """Categorization of frame objects by type."""
    frame_objects: List[GraphObject]
    slot_objects: List[GraphObject]
    edge_objects: List[GraphObject]


@dataclass
class CreateFrameResult:
    """Result of frame creation operation."""
    success: bool
    created_uris: List[str]
    message: str
    frame_count: int


class KGEntityFrameCreateProcessor:
    """
    Processor for creating frames and linking them to existing KGEntities.
    
    REFACTORING SOURCE: Extract logic from KGEntitiesEndpoint._create_or_update_frames()
    
    Handles:
    - Frame object creation with proper properties
    - Edge_hasEntityKGFrame creation for entity-frame linking  
    - Grouping URI assignment (entity-level + frame-level)
    - Frame graph validation and structure analysis
    - Backend integration for atomic frame creation operations
    - UPDATE/UPSERT operations with existing frame deletion
    """
    
    def __init__(self):
        """Initialize the frame create processor."""
        self.logger = logging.getLogger(__name__)
        self.vitalsigns = VitalSigns()
    
    async def create_entity_frame(
        self,
        backend_adapter: FusekiPostgreSQLBackendAdapter,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        frame_objects: List[GraphObject],
        operation_mode: str = "CREATE",
        parent_frame_uri: Optional[str] = None
    ) -> CreateFrameResult:
        """
        Create frame graph and link to existing entity.
        
        EXTRACTED FROM: _create_or_update_frames() lines 937-1164
        
        Process:
        1. Validate entity exists (existing: lines 957-959)
        2. Categorize frame objects (existing: lines 980-993)
        3. Set dual grouping URIs (existing: lines 995-1011)
        4. Create Edge_hasEntityKGFrame objects (existing: lines 1019-1040)
        5. Handle UPDATE/UPSERT deletion (existing: lines 1061-1123)
        6. Execute atomic creation via backend (existing: lines 1125-1145)
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: URI of the target entity
            frame_objects: List of frame-related GraphObjects
            operation_mode: CREATE, UPDATE, or UPSERT
            
        Returns:
            CreateFrameResult with created URIs and metadata
        """
        try:
            if parent_frame_uri:
                self.logger.info(f"Creating/updating CHILD frames for entity {entity_uri} in space {space_id}, graph {graph_id}, parent_frame_uri={parent_frame_uri}, operation_mode={operation_mode}")
            else:
                self.logger.info(f"Creating/updating TOP-LEVEL frames for entity {entity_uri} in space {space_id}, graph {graph_id}, operation_mode={operation_mode}")
            
            # Step 1: Validate entity exists (extracted from lines 957-959)
            entity_exists = await self.validate_entity_exists(backend_adapter, space_id, graph_id, entity_uri)
            if not entity_exists:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message=f"Target entity {entity_uri} not found in space {space_id}",
                    frame_count=0
                )
            
            # Step 2: Categorize frame objects (extracted from lines 980-993)
            categories = await self.categorize_frame_objects(frame_objects)
            
            # Step 3: Validate frame structure
            if not categories.frame_objects:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="Request must contain at least one KGFrame object",
                    frame_count=0
                )
            
            # Step 4: Set dual grouping URIs (extracted from lines 995-1011)
            # CRITICAL: Pass ALL objects (not just frame_objects) to ensure hierarchical child frames get kGGraphURI set
            all_input_objects = categories.frame_objects + categories.slot_objects + categories.edge_objects
            all_objects = await self.assign_grouping_uris(all_input_objects, entity_uri)
            
            # Step 5: Create Edge_hasEntityKGFrame objects (extracted from lines 1019-1040)
            # Only create entity-frame edges during CREATE operations, not during UPDATE
            # During UPDATE, the edges already exist and should not be recreated
            if not operation_mode or str(operation_mode).upper() not in ['UPDATE', 'UPSERT']:
                entity_frame_edges = await self.create_entity_frame_edges(entity_uri, categories.frame_objects)
                all_objects.extend(entity_frame_edges)
            
            # Step 6: Execute atomic UPDATE/UPSERT or CREATE operation
            if operation_mode and str(operation_mode).upper() in ['UPDATE', 'UPSERT']:
                success = await self.execute_atomic_frame_update(backend_adapter, space_id, graph_id, 
                                                               categories.frame_objects, all_objects, operation_mode)
            else:
                # Step 7: Execute atomic creation via backend (extracted from lines 1125-1145)
                success = await self.execute_frame_creation(backend_adapter, space_id, graph_id, all_objects)
            
            if success:
                created_uris = [str(obj.URI) for obj in all_objects if hasattr(obj, 'URI')]
                self.logger.info(f"Successfully created/updated {len(created_uris)} frame objects")
                
                return CreateFrameResult(
                    success=True,
                    created_uris=created_uris,
                    message=f"Successfully created {len(categories.frame_objects)} frames",
                    frame_count=len(categories.frame_objects)
                )
            else:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="Failed to create/update frames",
                    frame_count=0
                )
                
        except Exception as e:
            self.logger.error(f"Error creating/updating frames: {e}")
            return CreateFrameResult(
                success=False,
                created_uris=[],
                message=f"Error creating/updating frames: {str(e)}",
                frame_count=0
            )
    
    async def validate_entity_exists(self, backend_adapter: FusekiPostgreSQLBackendAdapter, space_id: str, 
                                   graph_id: str, entity_uri: str) -> bool:
        """
        Validate target entity exists before frame creation.
        EXTRACTED FROM: lines 957-959 in _create_or_update_frames()
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: URI of the entity to validate
            
        Returns:
            bool: True if entity exists, False otherwise
        """
        try:
            # Use the existing entity existence check pattern from the endpoint
            # This delegates to KGEntityDeleteProcessor.entity_exists()
            from vitalgraph.kg_impl.kgentity_delete_impl import KGEntityDeleteProcessor
            
            delete_processor = KGEntityDeleteProcessor()
            return await delete_processor.entity_exists(backend_adapter, space_id, graph_id, entity_uri)
            
        except Exception as e:
            self.logger.error(f"Error checking entity existence: {e}")
            return False
    
    async def categorize_frame_objects(self, graph_objects: List[GraphObject]) -> FrameObjectCategories:
        """
        Categorize objects by type: frames, slots, edges.
        EXTRACTED FROM: lines 980-993 in _create_or_update_frames()
        
        Args:
            graph_objects: List of GraphObjects to categorize
            
        Returns:
            FrameObjectCategories with categorized objects
        """
        frame_objects = []
        slot_objects = []
        edge_objects = []
        
        # First pass: categorize objects by type (extracted from lines 980-993)
        for obj in graph_objects:
            # Categorize objects by type
            if hasattr(obj, '__class__'):
                class_name = obj.__class__.__name__
                if 'KGFrame' in class_name:
                    frame_objects.append(obj)
                elif 'KGSlot' in class_name or 'Slot' in class_name:
                    slot_objects.append(obj)
                elif 'Edge_' in class_name:
                    edge_objects.append(obj)
        
        self.logger.info(f"📦 Categorized objects: {len(frame_objects)} frames, {len(slot_objects)} slots, {len(edge_objects)} edges")
        
        return FrameObjectCategories(
            frame_objects=frame_objects,
            slot_objects=slot_objects,
            edge_objects=edge_objects
        )
    
    async def assign_grouping_uris(self, frame_objects: List[GraphObject], 
                                 entity_uri: str) -> List[GraphObject]:
        """
        Assign dual grouping URIs to frame objects.
        EXTRACTED FROM: lines 995-1011 in _create_or_update_frames()
        
        Entity-level: hasKGGraphURI = entity_uri (for complete entity retrieval)
        Frame-level: frameGraphURI = frame_uri (for frame-specific retrieval)
        
        Args:
            frame_objects: List of frame-related GraphObjects
            entity_uri: URI of the target entity
            
        Returns:
            List[GraphObject]: Objects with assigned grouping URIs
        """
        # Second pass: set grouping URIs (extracted from lines 995-1011)
        # CRITICAL: Set kGGraphURI on ALL objects, including hierarchical child frames
        for obj in frame_objects:
            self.logger.info(f"🔍 Processing object {obj.__class__.__name__} with URI: {getattr(obj, 'URI', 'NO_URI')}")
            
            # Log object properties before modification
            try:
                obj_dict = obj.to_json()
                self.logger.info(f"🔍 Object before grouping URI assignment: {obj_dict}")
            except Exception as e:
                self.logger.warning(f"⚠️ Could not serialize object to JSON: {e}")
            
            # Set entity-level grouping URI for ALL objects (using short property name)
            # This is CRITICAL for hierarchical frames - all frames must have kGGraphURI set to the entity
            if hasattr(obj, 'kGGraphURI'):
                obj.kGGraphURI = entity_uri
                self.logger.info(f"🔧 Set kGGraphURI={entity_uri} for {obj.__class__.__name__}")
            else:
                self.logger.warning(f"⚠️ Object {obj.__class__.__name__} does not have kGGraphURI property")
            
            # Set frame-level grouping URI based on object type
            if hasattr(obj, '__class__'):
                class_name = obj.__class__.__name__
                
                # For frame objects, set frameGraphURI to their own URI
                if 'KGFrame' in class_name:
                    obj.frameGraphURI = obj.URI
                    self.logger.info(f"🔧 Set frameGraphURI={obj.URI} for frame {obj.URI}")
                    
                # For slots, set frameGraphURI to the frame they belong to
                elif 'Slot' in class_name:
                    # Find the frame this slot should belong to
                    frame_candidates = [o for o in frame_objects if hasattr(o, '__class__') and 'KGFrame' in o.__class__.__name__]
                    if frame_candidates:
                        target_frame = frame_candidates[0]  # Use first frame (simplified)
                        obj.frameGraphURI = target_frame.URI
                        self.logger.info(f"🔧 Set frameGraphURI={target_frame.URI} for slot {obj.URI}")
                    else:
                        self.logger.warning(f"⚠️ No frame candidates found for slot {obj.URI}")
                
                # For edges within frames, also set frameGraphURI
                elif 'Edge_hasKGSlot' in class_name:
                    # Frame-to-slot edges should have frameGraphURI set to the frame URI
                    frame_candidates = [o for o in frame_objects if hasattr(o, '__class__') and 'KGFrame' in o.__class__.__name__]
                    if frame_candidates:
                        target_frame = frame_candidates[0]  # Use first frame (simplified)
                        
                        obj.frameGraphURI = target_frame.URI
                        self.logger.info(f"🔧 Set frameGraphURI={target_frame.URI} for edge {obj.URI}")
                    else:
                        self.logger.warning(f"⚠️ No frame candidates found for edge {obj.URI}")
            
            # Log object properties after modification
            try:
                obj_dict_after = obj.to_json()
                self.logger.info(f"🔍 Object after grouping URI assignment: {obj_dict_after}")
            except Exception as e:
                self.logger.warning(f"⚠️ Could not serialize modified object to JSON: {e}")
        
        return frame_objects
    
    async def create_entity_frame_edges(self, entity_uri: str, 
                                      frame_objects: List[GraphObject]) -> List[GraphObject]:
        """
        Create Edge_hasEntityKGFrame linking objects for entity-to-frame connections.
        EXTRACTED FROM: lines 1019-1040 in _create_or_update_frames()
        
        Args:
            entity_uri: URI of the target entity
            frame_objects: List of KGFrame objects
            
        Returns:
            List[GraphObject]: Created Edge_hasEntityKGFrame objects
        """
        entity_frame_edges = []
        
        # Create Edge_hasEntityKGFrame edges server-side for each frame (extracted from lines 1019-1040)
        for frame_obj in frame_objects:
            # Create entity-to-frame edge with unique URI
            import uuid
            edge_uri = f"http://edge/entity_frame_edge_{uuid.uuid4()}"
            
            entity_frame_edge = Edge_hasEntityKGFrame()
            entity_frame_edge.URI = edge_uri
            entity_frame_edge.edgeSource = entity_uri
            entity_frame_edge.edgeDestination = frame_obj.URI
            
            # Debug: Verify edge properties are set correctly
            self.logger.debug(f"🔍 Edge properties: URI={entity_frame_edge.URI}, edgeSource={getattr(entity_frame_edge, 'edgeSource', 'NOT_SET')}, edgeDestination={getattr(entity_frame_edge, 'edgeDestination', 'NOT_SET')}")
            
            # Debug: Test individual edge triple generation
            edge_triples = GraphObject.to_triples_list([entity_frame_edge])
            self.logger.debug(f"🔍 Edge {entity_frame_edge.URI} generates {len(edge_triples)} triples:")
            for i, (s, p, o) in enumerate(edge_triples):
                self.logger.debug(f"  Edge triple {i+1}: s={repr(str(s))}, p={repr(str(p))}, o={repr(str(o))}")
            
            # Set grouping URIs for the edge
            if hasattr(entity_frame_edge, 'kGGraphURI'):
                entity_frame_edge.kGGraphURI = entity_uri
            
            entity_frame_edges.append(entity_frame_edge)
            
            self.logger.info(f"🔗 Created entity-to-frame edge: {entity_uri} -> {frame_obj.URI}")
        
        return entity_frame_edges
    
    async def execute_atomic_frame_update(self, backend_adapter: FusekiPostgreSQLBackendAdapter, space_id: str,
                                        graph_id: str, frame_objects: List[GraphObject], all_objects: List[GraphObject],
                                        operation_mode: str) -> bool:
        """
        Execute atomic frame UPDATE/UPSERT using the validated update_quads function.
        
        This method replaces the separate deletion and creation operations with a single
        atomic transaction using the update_quads function that has been validated with
        100% test success rate.
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier  
            frame_objects: List of frame objects being updated
            all_objects: All GraphObjects to create (frames, slots, edges)
            operation_mode: 'UPDATE' or 'UPSERT'
            
        Returns:
            bool: True if atomic update successful, False otherwise
        """
        try:
            self.logger.info(f"🔄 Executing atomic frame {operation_mode} for {len(frame_objects)} frames")
            
            # Step 1: Build delete quads for existing frame data
            delete_quads = await self.build_delete_quads_for_frames(backend_adapter, space_id, graph_id, frame_objects)
            
            # Step 2: Build insert quads for new frame data
            insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
            
            # Step 3: Execute atomic update using validated update_quads function
            success = await backend_adapter.update_quads(space_id, graph_id, delete_quads, insert_quads)
            
            if success:
                self.logger.info(f"✅ Atomic frame {operation_mode} completed successfully")
                return True
            else:
                self.logger.error(f"❌ Atomic frame {operation_mode} failed")
                return False
                
        except Exception as e:
            self.logger.error(f"Error in atomic frame {operation_mode}: {e}")
            return False
    
    async def build_delete_quads_for_frames(self, backend_adapter: FusekiPostgreSQLBackendAdapter, space_id: str,
                                          graph_id: str, frame_objects: List[GraphObject]) -> List[tuple]:
        """
        Build delete quads for existing frame data that needs to be replaced.
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            frame_objects: List of frame objects being updated
            
        Returns:
            List[tuple]: List of quad tuples (subject, predicate, object, graph) to delete
        """
        try:
            delete_quads = []
            
            # Get frame URIs that are being updated
            frame_uris = [str(obj.URI) for obj in frame_objects if hasattr(obj, 'URI')]
            
            if not frame_uris:
                self.logger.info("🔍 No frame URIs found for delete quad building")
                return delete_quads
            
            self.logger.info(f"🔍 Building delete quads for {len(frame_uris)} frames")
            
            # For each frame, find all subjects that belong to it via frameGraphURI
            for frame_uri in frame_uris:
                # Query to find all subjects that have hasFrameGraphURI pointing to this frame
                find_subjects_query = f"""
                SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject <http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI> <{frame_uri}> .
                        ?subject ?predicate ?object .
                    }}
                }}
                """
                
                self.logger.info(f"🔍 Finding triples for frame: {frame_uri}")
                self.logger.info(f"🔍 Delete query: {find_subjects_query}")
                results = await backend_adapter.execute_sparql_query(space_id, find_subjects_query)
                self.logger.info(f"🔍 Delete query results: {results}")
                
                # Convert SPARQL results to delete quads - handle nested structure
                bindings = []
                if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                    bindings = results['results'].get('bindings', [])
                elif isinstance(results, list):
                    bindings = results
                
                for result in bindings:
                    if isinstance(result, dict) and all(key in result for key in ['subject', 'predicate', 'object']):
                        subject = str(result['subject'].get('value', '')) if isinstance(result['subject'], dict) else str(result['subject'])
                        predicate = str(result['predicate'].get('value', '')) if isinstance(result['predicate'], dict) else str(result['predicate'])
                        
                        # Log the raw object to see what Fuseki is returning
                        if isinstance(result['object'], dict):
                            obj_dict = result['object']
                            if obj_dict.get('datatype') and 'float' in obj_dict.get('datatype', '').lower():
                                self.logger.info(f"🔍 FLOAT VALUE from Fuseki: {obj_dict}")
                        
                        obj = str(result['object'].get('value', '')) if isinstance(result['object'], dict) else str(result['object'])
                        
                        if subject and predicate and obj:
                            delete_quads.append((subject, predicate, obj, graph_id))
                
                # Also include the frame itself - find all its triples
                frame_triples_query = f"""
                SELECT DISTINCT ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> ?predicate ?object .
                    }}
                }}
                """
                
                frame_results = await backend_adapter.execute_sparql_query(space_id, frame_triples_query)
                
                # Handle nested structure for frame results
                frame_bindings = []
                if isinstance(frame_results, dict) and 'results' in frame_results and isinstance(frame_results['results'], dict):
                    frame_bindings = frame_results['results'].get('bindings', [])
                elif isinstance(frame_results, list):
                    frame_bindings = frame_results
                
                for result in frame_bindings:
                    if isinstance(result, dict) and all(key in result for key in ['predicate', 'object']):
                        predicate = str(result['predicate'].get('value', '')) if isinstance(result['predicate'], dict) else str(result['predicate'])
                        obj = str(result['object'].get('value', '')) if isinstance(result['object'], dict) else str(result['object'])
                        
                        if predicate and obj:
                            delete_quads.append((frame_uri, predicate, obj, graph_id))
            
            self.logger.info(f"🔍 Built {len(delete_quads)} delete quads")
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads: {e}")
            return []
    
    async def build_insert_quads_for_objects(self, all_objects: List[GraphObject], graph_id: str) -> List[tuple]:
        """
        Build insert quads for new frame data.
        
        Args:
            all_objects: All GraphObjects to create (frames, slots, edges)
            graph_id: Graph identifier
            
        Returns:
            List[tuple]: List of quad tuples (subject, predicate, object, graph) to insert
        """
        try:
            self.logger.info(f"🔍 Building insert quads for {len(all_objects)} objects")
            
            # Log each object type, URI, and check for kGGraphURI property
            for i, obj in enumerate(all_objects):
                obj_type = type(obj).__name__
                obj_uri = str(obj.URI) if hasattr(obj, 'URI') else 'NO_URI'
                has_kg_graph_uri = hasattr(obj, 'kGGraphURI')
                kg_graph_uri_value = str(obj.kGGraphURI) if has_kg_graph_uri and obj.kGGraphURI else 'NOT_SET'
                self.logger.info(f"🔍   Object {i+1}: {obj_type} - {obj_uri}")
                self.logger.info(f"🔍   Has kGGraphURI: {has_kg_graph_uri}, Value: {kg_graph_uri_value}")
            
            # Convert VitalSigns objects to triples
            triples = GraphObject.to_triples_list(all_objects)
            
            self.logger.info(f"🔍 to_triples_list returned {len(triples)} RDFLib triple objects")
            
            # Check if hasKGGraphURI triples are present
            kg_graph_uri_triples = [t for t in triples if 'hasKGGraphURI' in str(t[1])]
            frame_graph_uri_triples = [t for t in triples if 'hasFrameGraphURI' in str(t[1])]
            self.logger.info(f"🔍 Found {len(kg_graph_uri_triples)} hasKGGraphURI triples")
            self.logger.info(f"🔍 Found {len(frame_graph_uri_triples)} hasFrameGraphURI triples")
            
            for triple in kg_graph_uri_triples:
                s, p, o = triple
                self.logger.info(f"🔍   hasKGGraphURI triple: {s} -> {o}")
            
            for i, triple in enumerate(triples[:10]):  # Log first 10 triples
                s, p, o = triple
                self.logger.info(f"🔍   Triple {i+1}: {s} | {p} | {o}")
            if len(triples) > 10:
                self.logger.info(f"🔍   ... and {len(triples) - 10} more triples")
            
            # Convert triples to quads by adding graph_id
            insert_quads = []
            for triple in triples:
                s, p, o = triple
                insert_quads.append((str(s), str(p), str(o), graph_id))
            
            self.logger.info(f"🔍 Built {len(insert_quads)} insert quads")
            return insert_quads
            
        except Exception as e:
            self.logger.error(f"Error building insert quads: {e}")
            return []

    async def handle_frame_update_deletion(self, backend_adapter: FusekiPostgreSQLBackendAdapter, space_id: str, 
                                         graph_id: str, frame_objects: List[GraphObject]) -> bool:
        """
        Handle UPDATE/UPSERT operations by deleting existing frame members.
        EXTRACTED FROM: lines 1061-1123 in _create_or_update_frames()
        
        Process:
        1. Find subjects with frameGraphURI pointing to frames being updated
        2. Delete all triples for those subjects
        3. Prepare for new frame data insertion
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            frame_objects: List of frame objects being updated
            
        Returns:
            bool: True if deletion successful, False otherwise
        """
        try:
            # Get frame URIs that are being updated (extracted from lines 1063)
            frame_uris = [obj.URI for obj in frame_objects if hasattr(obj, 'URI')]
            
            if not frame_uris:
                self.logger.info("🔍 No frame URIs found for update/upsert operation")
                return True
            
            self.logger.info(f"🔍 Processing update/upsert for {len(frame_uris)} frames")
            
            # Use graph_id directly as it's already a full URI
            full_graph_uri = graph_id
            
            # Phase 1: Get all subjects that belong to these frames using frameGraphURI (extracted from lines 1068-1096)
            for frame_uri in frame_uris:
                # Query to find all subjects that have frameGraphURI pointing to this frame
                find_subjects_query = f"""
                SELECT DISTINCT ?subject WHERE {{
                    GRAPH <{full_graph_uri}> {{
                        ?subject <http://vital.ai/ontology/haley-ai-kg#frameGraphURI> <{frame_uri}> .
                    }}
                }}
                """
                
                self.logger.info(f"🔍 Finding subjects for frame: {frame_uri}")
                subject_results = await backend_adapter.execute_sparql_query(space_id, find_subjects_query)
                
                # Extract subject URIs (extracted from lines 1082-1096)
                subject_uris = []
                if isinstance(subject_results, list):
                    for result in subject_results:
                        if isinstance(result, dict) and 'subject' in result:
                            subject_value = result['subject']
                            if isinstance(subject_value, dict):
                                subject_uri = subject_value.get('value')
                            else:
                                subject_uri = str(subject_value)
                            if subject_uri:
                                subject_uris.append(subject_uri)
                
                # Also include the frame itself
                subject_uris.append(frame_uri)
                
                if subject_uris:
                    self.logger.info(f"🔍 Found {len(subject_uris)} subjects to delete for frame {frame_uri}")
                    
                    # Phase 2: Delete all triples for these subjects (extracted from lines 1101-1119)
                    delete_patterns = []
                    for subject_uri in subject_uris:
                        # Use URI directly as VitalSigns produces clean URIs
                        subject_str = str(subject_uri).strip()
                        delete_patterns.append(f"    <{subject_str}> ?p ?o .")
                    
                    delete_query = f"""
                    DELETE {{
                        GRAPH <{full_graph_uri}> {{
                    {chr(10).join(delete_patterns)}
                        }}
                    }} WHERE {{
                        GRAPH <{full_graph_uri}> {{
                    {chr(10).join(delete_patterns)}
                        }}
                    }}
                    """
                    
                    self.logger.info(f"🔍 Deleting existing triples for {len(subject_uris)} subjects of frame {frame_uri}")
                    await backend_adapter.execute_sparql_update(space_id, delete_query)
                else:
                    self.logger.info(f"🔍 No existing subjects found for frame {frame_uri} (new frame)")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error handling frame update deletion: {e}")
            return False
    
    async def execute_frame_creation(self, backend_adapter: FusekiPostgreSQLBackendAdapter, space_id: str, 
                                   graph_id: str, all_objects: List[GraphObject]) -> bool:
        """
        Execute atomic frame creation via backend.
        EXTRACTED FROM: lines 1125-1145 in _create_or_update_frames()
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            all_objects: All GraphObjects to create (frames, slots, edges)
            
        Returns:
            bool: True if creation successful, False otherwise
        """
        try:
            # Debug: Log what objects are being stored
            self.logger.debug(f"🔍 Storing {len(all_objects)} objects to backend:")
            for obj in all_objects:
                self.logger.debug(f"  - {obj.__class__.__name__}: {getattr(obj, 'URI', 'NO_URI')}")
            
            # Convert objects to triples and store (extracted from lines 1043-1145)
            triples = GraphObject.to_triples_list(all_objects)
            
            # Use graph_id directly as it's already a full URI
            full_graph_uri = graph_id
            
            # Build SPARQL INSERT query (back to original working approach)
            triples_str = ""
            edge_triples_count = 0
            for triple in triples:
                s, p, o = triple
                
                # Check RDFLib object types directly to preserve type information
                from rdflib import URIRef, Literal, BNode
                
                # Log the actual type to diagnose formatting issues
                self.logger.info(f"🔍 Object type check: o={repr(o)}, type={type(o).__name__}, isinstance(Literal)={isinstance(o, Literal)}, isinstance(URIRef)={isinstance(o, URIRef)}")
                
                # Format object based on its RDFLib type
                if isinstance(o, Literal):
                    # Literal - wrap in quotes with datatype if present
                    if o.datatype:
                        obj_str = f'"{o}"^^<{o.datatype}>'
                    elif o.language:
                        obj_str = f'"{o}"@{o.language}'
                    else:
                        obj_str = f'"{o}"'
                elif isinstance(o, URIRef):
                    # URI - wrap in angle brackets
                    obj_str = f"<{o}>"
                elif isinstance(o, BNode):
                    # Blank node
                    obj_str = f"_:{o}"
                else:
                    # Fallback for strings - check if it's a URI
                    from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                    if validate_rfc3986(str(o), rule='URI'):
                        obj_str = f"<{o}>"
                    else:
                        obj_str = f'"{o}"'
                
                triples_str += f"    <{s}> <{p}> {obj_str} .\n"
                
                    # Count Edge_hasEntityKGFrame triples
                if 'Edge_hasEntityKGFrame' in str(s) or 'hasEdgeSource' in str(p) or 'hasEdgeDestination' in str(p):
                    edge_triples_count += 1
                    self.logger.debug(f"🔍 Edge triple: s={repr(str(s))}, p={repr(str(p))}, o={repr(str(o))}")
            
            self.logger.debug(f"🔍 Generated {len(triples)} total triples, {edge_triples_count} edge-related triples")
            
            insert_query = f"""
            INSERT DATA {{
                GRAPH <{full_graph_uri}> {{
            {triples_str}
                }}
            }}
            """
            
            # Debug logging to identify double angle bracket issue
            self.logger.debug(f"🔍 Full graph URI: {repr(full_graph_uri)}")
            self.logger.debug(f"🔍 First 5 triples:")
            for i, triple in enumerate(triples[:5]):
                s, p, o = triple
                self.logger.debug(f"  Triple {i+1}: s={repr(str(s))}, p={repr(str(p))}, o={repr(str(o))}")
            # Extract just the edge-related triples for debugging
            edge_triples_in_query = [line for line in insert_query.split('\n') if 'hasEdgeSource' in line or 'hasEdgeDestination' in line or 'Edge_hasEntityKGFrame' in line]
            self.logger.debug(f"🔍 Edge triples in INSERT query ({len(edge_triples_in_query)} lines):")
            for line in edge_triples_in_query[:10]:  # Show first 10 edge-related lines
                self.logger.debug(f"  {line.strip()}")
            
            # Check for double angle brackets
            if '<<' in insert_query or '>>' in insert_query:
                self.logger.error(f"🚨 Double angle brackets detected in SPARQL query!")
                raise ValueError("SPARQL query contains double angle brackets")
            
            # Execute the insert (extracted from line 1145)
            self.logger.debug(f"🔍 Executing SPARQL INSERT with {len(triples)} triples...")
            await backend_adapter.execute_sparql_update(space_id, insert_query)
            self.logger.debug(f"🔍 SPARQL INSERT execution completed")
            
            # Immediate verification: Check if edges were inserted
            verification_query = f"""
            SELECT DISTINCT ?edge ?source ?dest WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?edge a <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?source .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?dest .
                }}
            }}
            LIMIT 5
            """
            
            verification_results = await backend_adapter.execute_sparql_query(space_id, verification_query)
            self.logger.debug(f"🔍 Immediate post-INSERT edge verification: {verification_results}")
            
            # Query all triples in the graph to see what was actually stored
            all_triples_query = f"""
            SELECT ?s ?p ?o WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?s ?p ?o .
                }}
            }}
            LIMIT 100
            """
            
            all_results = await backend_adapter.execute_sparql_query(space_id, all_triples_query)
            self.logger.debug(f"🔍 All triples in graph after INSERT ({len(all_results) if isinstance(all_results, list) else 'unknown'} results):")
            
            # Log first 20 triples to see what's actually stored
            if isinstance(all_results, list):
                for i, result in enumerate(all_results[:20]):
                    if isinstance(result, dict):
                        s = result.get('s', {}).get('value', 'NO_SUBJECT')
                        p = result.get('p', {}).get('value', 'NO_PREDICATE') 
                        o = result.get('o', {}).get('value', 'NO_OBJECT')
                        self.logger.debug(f"  Triple {i+1}: s={s}, p={p}, o={o}")
            elif isinstance(all_results, dict) and 'results' in all_results:
                bindings = all_results['results'].get('bindings', [])
                for i, binding in enumerate(bindings[:20]):
                    s = binding.get('s', {}).get('value', 'NO_SUBJECT')
                    p = binding.get('p', {}).get('value', 'NO_PREDICATE')
                    o = binding.get('o', {}).get('value', 'NO_OBJECT')
                    self.logger.debug(f"  Triple {i+1}: s={s}, p={p}, o={o}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error executing frame creation: {e}")
            return False
