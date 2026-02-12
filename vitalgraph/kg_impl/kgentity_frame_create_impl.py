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

# RDFLib imports for proper quad building with type preservation
from rdflib import URIRef, Literal, BNode

# Domain model imports for edge creation
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame

# Backend adapter import
from vitalgraph.kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter


def _sparql_binding_to_rdflib(binding) -> Any:
    """
    Convert a SPARQL result binding (dict with value/type/datatype/language)
    to the corresponding RDFLib object, preserving datatype and language info.

    Handles:
        - {"type": "uri", "value": "..."} → URIRef
        - {"type": "literal", "value": "...", "datatype": "..."} → Literal with datatype
        - {"type": "literal", "value": "...", "language": "..."} → Literal with lang
        - {"type": "literal", "value": "..."} → plain Literal
        - {"type": "bnode", "value": "..."} → BNode
        - plain string → URIRef if valid URI, else Literal
    """
    if isinstance(binding, dict):
        value = binding.get('value', '')
        term_type = binding.get('type', 'literal')
        if term_type == 'uri':
            return URIRef(value)
        elif term_type == 'literal':
            datatype = binding.get('datatype')
            language = binding.get('language')
            if datatype:
                return Literal(value, datatype=URIRef(datatype))
            elif language:
                return Literal(value, lang=language)
            else:
                return Literal(value)
        elif term_type == 'bnode':
            return BNode(value)
    # Fallback for plain strings
    if isinstance(binding, str):
        from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
        if validate_rfc3986(binding, rule='URI'):
            return URIRef(binding)
        return Literal(binding)
    return Literal(str(binding))


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
    fuseki_success: Optional[bool] = None


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
            import time as _time
            _p0 = _time.time()
            if parent_frame_uri:
                self.logger.debug(f"Creating/updating CHILD frames for entity {entity_uri} in space {space_id}, graph {graph_id}, parent_frame_uri={parent_frame_uri}, operation_mode={operation_mode}")
            else:
                self.logger.debug(f"Creating/updating TOP-LEVEL frames for entity {entity_uri} in space {space_id}, graph {graph_id}, operation_mode={operation_mode}")
            
            # Step 1: Validate entity exists (extracted from lines 957-959)
            # Skip for UPDATE/UPSERT — validate_frame_ownership already confirmed entity exists upstream
            if not operation_mode or str(operation_mode).upper() not in ['UPDATE', 'UPSERT']:
                entity_exists = await self.validate_entity_exists(backend_adapter, space_id, graph_id, entity_uri)
                if not entity_exists:
                    return CreateFrameResult(
                        success=False,
                        created_uris=[],
                        message=f"Target entity {entity_uri} not found in space {space_id}",
                        frame_count=0
                    )
            
            _p1 = _time.time()
            self.logger.info(f"⏱️ PROCESSOR validate_entity: {_p1-_p0:.3f}s")
            
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
            
            _p2 = _time.time()
            self.logger.info(f"⏱️ PROCESSOR categorize+grouping+edges: {_p2-_p1:.3f}s")
            
            # Step 6: Execute atomic UPDATE/UPSERT or CREATE operation
            fuseki_success = True
            if operation_mode and str(operation_mode).upper() in ['UPDATE', 'UPSERT']:
                success, fuseki_success = await self.execute_atomic_frame_update(backend_adapter, space_id, graph_id, 
                                                               categories.frame_objects, all_objects, operation_mode)
            else:
                # Step 7: Execute atomic creation via backend (extracted from lines 1125-1145)
                success, fuseki_success = await self.execute_frame_creation(backend_adapter, space_id, graph_id, all_objects)
            
            if success:
                created_uris = [str(obj.URI) for obj in all_objects if hasattr(obj, 'URI')]
                self.logger.debug(f"Successfully created/updated {len(created_uris)} frame objects")
                
                return CreateFrameResult(
                    success=True,
                    created_uris=created_uris,
                    message=f"Successfully created {len(categories.frame_objects)} frames",
                    frame_count=len(categories.frame_objects),
                    fuseki_success=fuseki_success
                )
            else:
                return CreateFrameResult(
                    success=False,
                    created_uris=[],
                    message="Failed to create/update frames",
                    frame_count=0,
                    fuseki_success=fuseki_success
                )
                
        except Exception as e:
            self.logger.error(f"Error creating/updating frames: {e}")
            return CreateFrameResult(
                success=False,
                created_uris=[],
                message=f"Error creating/updating frames: {str(e)}",
                frame_count=0,
                fuseki_success=False
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
        
        self.logger.debug(f"📦 Categorized objects: {len(frame_objects)} frames, {len(slot_objects)} slots, {len(edge_objects)} edges")
        
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
            self.logger.debug(f"🔍 Processing object {obj.__class__.__name__} with URI: {getattr(obj, 'URI', 'NO_URI')}")
            
            # Log object properties before modification
            try:
                obj_dict = obj.to_json()
                self.logger.debug(f"🔍 Object before grouping URI assignment: {obj_dict}")
            except Exception as e:
                self.logger.warning(f"⚠️ Could not serialize object to JSON: {e}")
            
            # Set entity-level grouping URI for ALL objects (using short property name)
            # This is CRITICAL for hierarchical frames - all frames must have kGGraphURI set to the entity
            if hasattr(obj, 'kGGraphURI'):
                obj.kGGraphURI = entity_uri
                self.logger.debug(f"🔧 Set kGGraphURI={entity_uri} for {obj.__class__.__name__}")
            else:
                self.logger.warning(f"⚠️ Object {obj.__class__.__name__} does not have kGGraphURI property")
            
            # Set frame-level grouping URI based on object type
            if hasattr(obj, '__class__'):
                class_name = obj.__class__.__name__
                
                # For frame objects, set frameGraphURI to their own URI
                if 'KGFrame' in class_name:
                    obj.frameGraphURI = obj.URI
                    self.logger.debug(f"🔧 Set frameGraphURI={obj.URI} for frame {obj.URI}")
                    
                # For slots, set frameGraphURI to the frame they belong to
                elif 'Slot' in class_name:
                    # Find the frame this slot should belong to
                    frame_candidates = [o for o in frame_objects if hasattr(o, '__class__') and 'KGFrame' in o.__class__.__name__]
                    if frame_candidates:
                        target_frame = frame_candidates[0]  # Use first frame (simplified)
                        obj.frameGraphURI = target_frame.URI
                        self.logger.debug(f"🔧 Set frameGraphURI={target_frame.URI} for slot {obj.URI}")
                    else:
                        self.logger.warning(f"⚠️ No frame candidates found for slot {obj.URI}")
                
                # For edges within frames, also set frameGraphURI
                elif 'Edge_hasKGSlot' in class_name:
                    # Frame-to-slot edges should have frameGraphURI set to the frame URI
                    frame_candidates = [o for o in frame_objects if hasattr(o, '__class__') and 'KGFrame' in o.__class__.__name__]
                    if frame_candidates:
                        target_frame = frame_candidates[0]  # Use first frame (simplified)
                        
                        obj.frameGraphURI = target_frame.URI
                        self.logger.debug(f"🔧 Set frameGraphURI={target_frame.URI} for edge {obj.URI}")
                    else:
                        self.logger.warning(f"⚠️ No frame candidates found for edge {obj.URI}")
            
            # Log object properties after modification
            try:
                obj_dict_after = obj.to_json()
                self.logger.debug(f"🔍 Object after grouping URI assignment: {obj_dict_after}")
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
            
            self.logger.debug(f"🔗 Created entity-to-frame edge: {entity_uri} -> {frame_obj.URI}")
        
        return entity_frame_edges
    
    async def execute_atomic_frame_update(self, backend_adapter: FusekiPostgreSQLBackendAdapter, space_id: str,
                                        graph_id: str, frame_objects: List[GraphObject], all_objects: List[GraphObject],
                                        operation_mode: str) -> tuple:
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
            Tuple of (success: bool, fuseki_success: Optional[bool])
        """
        try:
            import time
            t0 = time.time()
            self.logger.debug(f"🔄 Executing atomic frame {operation_mode} for {len(frame_objects)} frames")
            
            # Step 1: Build delete quads for existing frame data
            delete_quads = await self.build_delete_quads_for_frames(backend_adapter, space_id, graph_id, frame_objects)
            t1 = time.time()
            self.logger.info(f"⏱️ FRAME_UPDATE step1 build_delete_quads: {t1-t0:.3f}s ({len(delete_quads)} quads)")
            
            # Step 2: Build insert quads for new frame data
            insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
            t2 = time.time()
            self.logger.info(f"⏱️ FRAME_UPDATE step2 build_insert_quads: {t2-t1:.3f}s ({len(insert_quads)} quads)")
            
            # Step 2.5: Diff — only delete removed quads, only insert added quads
            # Use string keys for comparison (RDFLib objects don't hash consistently
            # across different construction paths), then map back to original quads.
            def _quad_str_key(q):
                return (str(q[0]), str(q[1]), str(q[2]), str(q[3]))
            
            old_key_map = {_quad_str_key(q): q for q in delete_quads}
            new_key_map = {_quad_str_key(q): q for q in insert_quads}
            unchanged_keys = set(old_key_map.keys()) & set(new_key_map.keys())
            actual_deletes = [old_key_map[k] for k in set(old_key_map.keys()) - unchanged_keys]
            actual_inserts = [new_key_map[k] for k in set(new_key_map.keys()) - unchanged_keys]
            self.logger.info(f"⏱️ FRAME_UPDATE diff: {len(unchanged_keys)} unchanged, {len(actual_deletes)} to delete, {len(actual_inserts)} to insert")
            
            # Step 3: Execute atomic update with only the changed quads
            success = await backend_adapter.update_quads(space_id, graph_id, actual_deletes, actual_inserts)
            t3 = time.time()
            self.logger.info(f"⏱️ FRAME_UPDATE step3 update_quads: {t3-t2:.3f}s")
            self.logger.info(f"⏱️ FRAME_UPDATE total: {t3-t0:.3f}s")
            
            if success:
                self.logger.debug(f"✅ Atomic frame {operation_mode} completed successfully")
                return (True, True)
            else:
                self.logger.error(f"❌ Atomic frame {operation_mode} failed")
                return (False, False)
                
        except Exception as e:
            self.logger.error(f"Error in atomic frame {operation_mode}: {e}")
            return (False, False)
    
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
                self.logger.debug("🔍 No frame URIs found for delete quad building")
                return delete_quads
            
            self.logger.debug(f"🔍 Building delete quads for {len(frame_uris)} frames")
            
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
                
                self.logger.debug(f"🔍 Finding triples for frame: {frame_uri}")
                self.logger.debug(f"🔍 Delete query: {find_subjects_query}")
                results = await backend_adapter.execute_sparql_query(space_id, find_subjects_query)
                self.logger.debug(f"🔍 Delete query results: {results}")
                
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
                        
                        # Reconstruct RDFLib object from full binding to preserve datatype/language
                        o = _sparql_binding_to_rdflib(result.get('object', ''))
                        
                        if subject and predicate and o is not None:
                            delete_quads.append((subject, predicate, o, graph_id))
                
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
                        # Reconstruct RDFLib object from full binding to preserve datatype/language
                        o = _sparql_binding_to_rdflib(result.get('object', ''))
                        
                        if predicate and o is not None:
                            delete_quads.append((frame_uri, predicate, o, graph_id))
            
            self.logger.debug(f"🔍 Built {len(delete_quads)} delete quads")
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
            self.logger.debug(f"🔍 Building insert quads for {len(all_objects)} objects")
            
            # Log each object type, URI, and check for kGGraphURI property
            for i, obj in enumerate(all_objects):
                obj_type = type(obj).__name__
                obj_uri = str(obj.URI) if hasattr(obj, 'URI') else 'NO_URI'
                has_kg_graph_uri = hasattr(obj, 'kGGraphURI')
                kg_graph_uri_value = str(obj.kGGraphURI) if has_kg_graph_uri and obj.kGGraphURI else 'NOT_SET'
                self.logger.debug(f"🔍   Object {i+1}: {obj_type} - {obj_uri}")
                self.logger.debug(f"🔍   Has kGGraphURI: {has_kg_graph_uri}, Value: {kg_graph_uri_value}")
            
            # Convert VitalSigns objects to triples
            triples = GraphObject.to_triples_list(all_objects)
            
            self.logger.debug(f"🔍 to_triples_list returned {len(triples)} RDFLib triple objects")
            
            # Check if hasKGGraphURI triples are present
            kg_graph_uri_triples = [t for t in triples if 'hasKGGraphURI' in str(t[1])]
            frame_graph_uri_triples = [t for t in triples if 'hasFrameGraphURI' in str(t[1])]
            self.logger.debug(f"🔍 Found {len(kg_graph_uri_triples)} hasKGGraphURI triples")
            self.logger.debug(f"🔍 Found {len(frame_graph_uri_triples)} hasFrameGraphURI triples")
            
            for triple in kg_graph_uri_triples:
                s, p, o = triple
                self.logger.debug(f"🔍   hasKGGraphURI triple: {s} -> {o}")
            
            for i, triple in enumerate(triples[:10]):  # Log first 10 triples
                s, p, o = triple
                self.logger.debug(f"🔍   Triple {i+1}: {s} | {p} | {o}")
            if len(triples) > 10:
                self.logger.debug(f"🔍   ... and {len(triples) - 10} more triples")
            
            # Convert triples to quads by adding graph_id
            # Keep RDFLib objects (especially Literal with datatype/language)
            # so downstream formatters (_format_term, _format_sparql_term,
            # _extract_term_info) can preserve type information.
            insert_quads = []
            for triple in triples:
                s, p, o = triple
                insert_quads.append((str(s), str(p), o, graph_id))
            
            self.logger.debug(f"🔍 Built {len(insert_quads)} insert quads")
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
    
    async def _build_delete_quads_for_subjects(self, backend_adapter: FusekiPostgreSQLBackendAdapter,
                                               space_id: str, graph_id: str,
                                               all_objects: List[GraphObject]) -> List[tuple]:
        """
        Query existing triples for all subject URIs that are about to be inserted.
        Returns delete quads so that existing data is cleaned before insert,
        preventing triple accumulation when a subject is written more than once.
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            all_objects: Objects whose subject URIs will be checked
            
        Returns:
            List of (subject, predicate, object, graph) tuples to delete
        """
        try:
            subject_uris = set()
            for obj in all_objects:
                if hasattr(obj, 'URI') and obj.URI:
                    subject_uris.add(str(obj.URI))
            
            if not subject_uris:
                return []
            
            # Batch query: find all existing triples for these subjects
            subject_values = " ".join(f"<{uri}>" for uri in subject_uris)
            query = f"""SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    VALUES ?subject {{ {subject_values} }}
                    ?subject ?predicate ?object .
                }}
            }}"""
            
            results = await backend_adapter.execute_sparql_query(space_id, query)
            
            # Parse SPARQL results into quad tuples
            delete_quads = []
            bindings = []
            if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                bindings = results['results'].get('bindings', [])
            elif isinstance(results, list):
                bindings = results
            
            for row in bindings:
                if isinstance(row, dict):
                    s = str(row['subject'].get('value', '')) if isinstance(row.get('subject'), dict) else str(row.get('subject', ''))
                    p = str(row['predicate'].get('value', '')) if isinstance(row.get('predicate'), dict) else str(row.get('predicate', ''))
                    # Reconstruct RDFLib object from full binding dict to preserve datatype/language
                    o_binding = row.get('object', '')
                    o = _sparql_binding_to_rdflib(o_binding)
                    if s and p and o is not None:
                        delete_quads.append((s, p, o, graph_id))
            
            if delete_quads:
                self.logger.info(f"🧹 Pre-cleanup: found {len(delete_quads)} existing triples for {len(subject_uris)} subjects")
            
            return delete_quads
            
        except Exception as e:
            self.logger.error(f"Error building delete quads for subjects: {e}")
            return []

    async def execute_frame_creation(self, backend_adapter: FusekiPostgreSQLBackendAdapter, space_id: str, 
                                   graph_id: str, all_objects: List[GraphObject]) -> bool:
        """
        Execute atomic frame creation via backend using update_quads.
        
        Uses a single transaction that deletes any existing triples for all
        subject URIs and inserts the new triples atomically.  This prevents
        triple accumulation when CREATE is called for subjects that already
        exist (e.g. a second write for the same slot URI).
        
        Args:
            backend_adapter: Backend adapter for database operations
            space_id: Space identifier
            graph_id: Graph identifier
            all_objects: All GraphObjects to create (frames, slots, edges)
            
        Returns:
            Tuple of (success: bool, fuseki_success: bool)
        """
        try:
            import time as _time
            _t0 = _time.time()
            
            self.logger.debug(f"🔍 Storing {len(all_objects)} objects to backend:")
            for obj in all_objects:
                self.logger.debug(f"  - {obj.__class__.__name__}: {getattr(obj, 'URI', 'NO_URI')}")
            
            # Step 1: Build insert quads from VitalSigns objects
            insert_quads = await self.build_insert_quads_for_objects(all_objects, graph_id)
            _t1 = _time.time()
            self.logger.info(f"⏱️ FRAME_CREATE step1 build_insert_quads: {_t1-_t0:.3f}s ({len(insert_quads)} quads)")
            
            # Step 2: Query existing triples for all subjects being created (pre-cleanup)
            delete_quads = await self._build_delete_quads_for_subjects(
                backend_adapter, space_id, graph_id, all_objects)
            _t2 = _time.time()
            self.logger.info(f"⏱️ FRAME_CREATE step2 build_delete_quads: {_t2-_t1:.3f}s ({len(delete_quads)} quads)")
            
            # Step 3: Diff — only delete removed quads, only insert added quads
            # Use string keys for comparison, map back to original quads with RDFLib objects.
            def _quad_str_key(q):
                return (str(q[0]), str(q[1]), str(q[2]), str(q[3]))
            
            old_key_map = {_quad_str_key(q): q for q in delete_quads}
            new_key_map = {_quad_str_key(q): q for q in insert_quads}
            unchanged_keys = set(old_key_map.keys()) & set(new_key_map.keys())
            actual_deletes = [old_key_map[k] for k in set(old_key_map.keys()) - unchanged_keys]
            actual_inserts = [new_key_map[k] for k in set(new_key_map.keys()) - unchanged_keys]
            self.logger.info(f"⏱️ FRAME_CREATE diff: {len(unchanged_keys)} unchanged, "
                           f"{len(actual_deletes)} to delete, {len(actual_inserts)} to insert")
            
            # Step 4: Atomic update — single PG transaction, single Fuseki request
            success = await backend_adapter.update_quads(
                space_id, graph_id, actual_deletes, actual_inserts)
            _t3 = _time.time()
            self.logger.info(f"⏱️ FRAME_CREATE step3 update_quads: {_t3-_t2:.3f}s")
            self.logger.info(f"⏱️ FRAME_CREATE total: {_t3-_t0:.3f}s")
            
            if success:
                self.logger.debug(f"✅ Atomic frame creation completed successfully")
                return (True, True)
            else:
                self.logger.error(f"❌ Atomic frame creation failed")
                return (False, False)
            
        except Exception as e:
            self.logger.error(f"Error executing frame creation: {e}")
            return (False, False)
