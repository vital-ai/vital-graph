#!/usr/bin/env python3
"""
KG Entity Graph Validation

This module provides comprehensive validation functions for KG entity graphs using
SPARQL-based graph walking to verify hierarchy integrity, detect dangling edges,
and compare edge-based discovery with grouping URI-based discovery.

Used for testing and validation to ensure correct graph maintenance.
"""

import logging
from typing import List, Dict, Set, Tuple, Any, Optional, Deque
from collections import deque, defaultdict
from dataclasses import dataclass

# Graph utilities import
from ..utils.graph_utils import DAGStructure, DAGNode, compare_dag_structures

# Backend adapter import
from .kg_backend_utils import FusekiPostgreSQLBackendAdapter


@dataclass
class EntityGraphValidationResult:
    """Result of comprehensive entity graph validation."""
    valid: bool
    entity_uri: str
    discovered_frames: Set[str]
    hierarchy_valid: bool
    grouping_consistency: bool
    validation_errors: List[str]
    validation_warnings: List[str]
    edge_based_discovery: Dict[str, Any]
    grouping_based_discovery: Dict[str, Any]
    comparison_results: Dict[str, Any]


@dataclass
class FrameHierarchyNode:
    """Represents a frame node in the hierarchy."""
    frame_uri: str
    parent_frames: Set[str]
    child_frames: Set[str]
    level: int
    entity_uri: str
    discovered_via_edge: bool = True
    discovered_via_grouping: bool = True


class KGEntityGraphValidator:
    """
    Comprehensive validator for KG entity graphs using SPARQL-based exploration.
    
    Performs deep validation of entity graph structure, hierarchy integrity,
    and consistency between edge-based and grouping URI-based discovery.
    """
    
    def __init__(self, backend_adapter: FusekiPostgreSQLBackendAdapter, logger: logging.Logger):
        """
        Initialize the entity graph validator.
        
        Args:
            backend_adapter: Backend adapter for SPARQL operations
            logger: Logger instance
        """
        self.backend = backend_adapter
        self.logger = logger
    
    async def discover_entity_graph_via_edges(self, space_id: str, graph_id: str, entity_uri: str) -> Dict[str, FrameHierarchyNode]:
        """
        Discover complete entity graph using SPARQL edge traversal with queue-based exploration.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to start discovery from
            
        Returns:
            Dict[str, FrameHierarchyNode]: Mapping of frame URIs to hierarchy nodes
        """
        discovered_frames = {}
        exploration_queue: Deque[Tuple[str, int]] = deque()  # (frame_uri, level)
        visited_frames: Set[str] = set()
        
        try:
            # Step 1: Find root frames directly connected to entity
            root_frames_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?frame_uri WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasEntityKGFrame ;
                          vital:hasEdgeSource <{entity_uri}> ;
                          vital:hasEdgeDestination ?frame_uri .
                    ?frame_uri a haley:KGFrame .
                }}
            }}
            """
            
            root_result = await self.backend.execute_sparql_query(space_id, root_frames_query)
            root_frame_uris = self._extract_uris_from_results(root_result, 'frame_uri')
            
            # Add root frames to exploration queue
            for frame_uri in root_frame_uris:
                exploration_queue.append((frame_uri, 0))
                discovered_frames[frame_uri] = FrameHierarchyNode(
                    frame_uri=frame_uri,
                    parent_frames=set(),  # Root frames have no parents
                    child_frames=set(),
                    level=0,
                    entity_uri=entity_uri
                )
            
            # Step 2: Queue-based exploration of frame hierarchy
            while exploration_queue:
                current_frame_uri, current_level = exploration_queue.popleft()
                
                if current_frame_uri in visited_frames:
                    continue
                
                visited_frames.add(current_frame_uri)
                
                # Find child frames of current frame
                child_frames_query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?child_frame WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a haley:Edge_hasKGFrame ;
                              vital:hasEdgeSource <{current_frame_uri}> ;
                              vital:hasEdgeDestination ?child_frame .
                        ?child_frame a haley:KGFrame .
                    }}
                }}
                """
                
                child_result = await self.backend.execute_sparql_query(space_id, child_frames_query)
                child_frame_uris = self._extract_uris_from_results(child_result, 'child_frame')
                
                # Process each child frame
                for child_uri in child_frame_uris:
                    # Update current frame's children
                    if current_frame_uri in discovered_frames:
                        discovered_frames[current_frame_uri].child_frames.add(child_uri)
                    
                    # Add or update child frame
                    if child_uri not in discovered_frames:
                        discovered_frames[child_uri] = FrameHierarchyNode(
                            frame_uri=child_uri,
                            parent_frames={current_frame_uri},
                            child_frames=set(),
                            level=current_level + 1,
                            entity_uri=entity_uri
                        )
                        # Add to exploration queue
                        exploration_queue.append((child_uri, current_level + 1))
                    else:
                        # Update existing node
                        discovered_frames[child_uri].parent_frames.add(current_frame_uri)
            
            self.logger.info(f"Discovered {len(discovered_frames)} frames via edge traversal for entity {entity_uri}")
            return discovered_frames
            
        except Exception as e:
            self.logger.error(f"Error discovering entity graph via edges: {e}")
            return {}
    
    async def discover_entity_graph_via_grouping_uris(self, space_id: str, graph_id: str, entity_uri: str) -> Dict[str, FrameHierarchyNode]:
        """
        Discover entity graph using grouping URI-based approach.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to discover frames for
            
        Returns:
            Dict[str, FrameHierarchyNode]: Mapping of frame URIs to hierarchy nodes
        """
        discovered_frames = {}
        
        try:
            # Find all frames with matching hasKGGraphURI
            grouping_frames_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?frame_uri WHERE {{
                GRAPH <{graph_id}> {{
                    ?frame_uri a haley:KGFrame ;
                               haley:hasKGGraphURI <{entity_uri}> .
                }}
            }}
            """
            
            grouping_result = await self.backend.execute_sparql_query(space_id, grouping_frames_query)
            frame_uris = self._extract_uris_from_results(grouping_result, 'frame_uri')
            
            # For each frame, determine its relationships
            for frame_uri in frame_uris:
                # Find parent frames
                parent_query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?parent_frame WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a haley:Edge_hasKGFrame ;
                              vital:hasEdgeSource ?parent_frame ;
                              vital:hasEdgeDestination <{frame_uri}> .
                    }}
                }}
                """
                
                parent_result = await self.backend.execute_sparql_query(space_id, parent_query)
                parent_uris = self._extract_uris_from_results(parent_result, 'parent_frame')
                
                # Find child frames
                child_query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?child_frame WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a haley:Edge_hasKGFrame ;
                              vital:hasEdgeSource <{frame_uri}> ;
                              vital:hasEdgeDestination ?child_frame .
                    }}
                }}
                """
                
                child_result = await self.backend.execute_sparql_query(space_id, child_query)
                child_uris = self._extract_uris_from_results(child_result, 'child_frame')
                
                # Determine level (root frames have no parents)
                level = 0 if not parent_uris else -1  # Will be calculated later
                
                discovered_frames[frame_uri] = FrameHierarchyNode(
                    frame_uri=frame_uri,
                    parent_frames=set(parent_uris),
                    child_frames=set(child_uris),
                    level=level,
                    entity_uri=entity_uri,
                    discovered_via_grouping=True
                )
            
            # Calculate levels for non-root frames
            self._calculate_frame_levels(discovered_frames)
            
            self.logger.info(f"Discovered {len(discovered_frames)} frames via grouping URIs for entity {entity_uri}")
            return discovered_frames
            
        except Exception as e:
            self.logger.error(f"Error discovering entity graph via grouping URIs: {e}")
            return {}
    
    def _calculate_frame_levels(self, frames: Dict[str, FrameHierarchyNode]):
        """Calculate hierarchy levels for frames."""
        # Find root frames (no parents)
        root_frames = [uri for uri, node in frames.items() if not node.parent_frames]
        
        # BFS to calculate levels
        queue = deque([(uri, 0) for uri in root_frames])
        visited = set()
        
        while queue:
            frame_uri, level = queue.popleft()
            
            if frame_uri in visited:
                continue
                
            visited.add(frame_uri)
            frames[frame_uri].level = level
            
            # Add children to queue
            for child_uri in frames[frame_uri].child_frames:
                if child_uri in frames and child_uri not in visited:
                    queue.append((child_uri, level + 1))
    
    async def validate_bidirectional_hierarchy(self, space_id: str, graph_id: str, frames: Dict[str, FrameHierarchyNode]) -> Tuple[bool, List[str]]:
        """
        Validate hierarchy integrity using bidirectional traversal.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frames: Discovered frames to validate
            
        Returns:
            Tuple[bool, List[str]]: (is_valid, list_of_errors)
        """
        errors = []
        
        try:
            # Validate parent-child consistency
            for frame_uri, node in frames.items():
                # For each child, verify it lists this frame as parent
                for child_uri in node.child_frames:
                    if child_uri in frames:
                        if frame_uri not in frames[child_uri].parent_frames:
                            errors.append(f"Inconsistent parent-child relationship: {frame_uri} -> {child_uri}")
                
                # For each parent, verify it lists this frame as child
                for parent_uri in node.parent_frames:
                    if parent_uri in frames:
                        if frame_uri not in frames[parent_uri].child_frames:
                            errors.append(f"Inconsistent child-parent relationship: {parent_uri} -> {frame_uri}")
            
            # Check for cycles
            cycle_errors = self._detect_cycles(frames)
            errors.extend(cycle_errors)
            
            # Check for orphaned frames (frames with no path to entity)
            orphan_errors = await self._detect_orphaned_frames(space_id, graph_id, frames)
            errors.extend(orphan_errors)
            
            return len(errors) == 0, errors
            
        except Exception as e:
            self.logger.error(f"Error validating bidirectional hierarchy: {e}")
            return False, [f"Validation error: {str(e)}"]
    
    def _detect_cycles(self, frames: Dict[str, FrameHierarchyNode]) -> List[str]:
        """Detect cycles in frame hierarchy."""
        errors = []
        visited = set()
        rec_stack = set()
        
        def dfs(frame_uri: str, path: List[str]) -> bool:
            if frame_uri in rec_stack:
                cycle_path = " -> ".join(path + [frame_uri])
                errors.append(f"Cycle detected: {cycle_path}")
                return True
            
            if frame_uri in visited:
                return False
            
            visited.add(frame_uri)
            rec_stack.add(frame_uri)
            
            if frame_uri in frames:
                for child_uri in frames[frame_uri].child_frames:
                    if dfs(child_uri, path + [frame_uri]):
                        return True
            
            rec_stack.remove(frame_uri)
            return False
        
        # Check each frame
        for frame_uri in frames:
            if frame_uri not in visited:
                dfs(frame_uri, [])
        
        return errors
    
    async def _detect_orphaned_frames(self, space_id: str, graph_id: str, frames: Dict[str, FrameHierarchyNode]) -> List[str]:
        """Detect frames that are not reachable from entity."""
        errors = []
        
        try:
            # Find frames that should be connected to entity
            entity_uri = next(iter(frames.values())).entity_uri if frames else None
            if not entity_uri:
                return errors
            
            # Find root frames (directly connected to entity)
            root_frames = [uri for uri, node in frames.items() if not node.parent_frames]
            
            # BFS from root frames to find reachable frames
            reachable = set()
            queue = deque(root_frames)
            
            while queue:
                frame_uri = queue.popleft()
                if frame_uri in reachable:
                    continue
                    
                reachable.add(frame_uri)
                
                if frame_uri in frames:
                    queue.extend(frames[frame_uri].child_frames)
            
            # Find orphaned frames
            all_frames = set(frames.keys())
            orphaned = all_frames - reachable
            
            for orphan_uri in orphaned:
                errors.append(f"Orphaned frame not reachable from entity: {orphan_uri}")
            
            return errors
            
        except Exception as e:
            self.logger.error(f"Error detecting orphaned frames: {e}")
            return [f"Orphan detection error: {str(e)}"]
    
    def _extract_uris_from_results(self, results, variable_name: str) -> List[str]:
        """Extract URIs from SPARQL query results."""
        uris = []
        
        try:
            if isinstance(results, dict) and results.get("results", {}).get("bindings"):
                for binding in results["results"]["bindings"]:
                    uri = binding.get(variable_name, {}).get("value")
                    if uri:
                        uris.append(uri)
            elif hasattr(results, 'bindings'):
                for binding in results.bindings:
                    if variable_name in binding:
                        uris.append(str(binding[variable_name]))
        except Exception as e:
            self.logger.error(f"Error extracting URIs from results: {e}")
        
        return uris
    
    async def validate_complete_entity_graph(self, space_id: str, graph_id: str, entity_uri: str) -> EntityGraphValidationResult:
        """
        Perform comprehensive validation of entity graph including frame-level validation.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to validate
            
        Returns:
            EntityGraphValidationResult: Comprehensive validation results
        """
        try:
            # Step 1: Discover entity graph via edges
            edge_based_frames = await self.discover_entity_graph_via_edges(space_id, graph_id, entity_uri)
            
            # Step 2: Discover entity graph via grouping URIs
            grouping_based_frames = await self.discover_entity_graph_via_grouping_uris(space_id, graph_id, entity_uri)
            
            # Step 3: Validate hierarchy integrity
            hierarchy_valid, hierarchy_errors = await self.validate_bidirectional_hierarchy(space_id, graph_id, edge_based_frames)
            
            # Step 4: Compare entity-level discovery methods
            entity_comparison_results = self._compare_discovery_methods(edge_based_frames, grouping_based_frames)
            
            # Step 5: Validate frame-level grouping URIs for all discovered frames
            frame_validation_results = {}
            frame_validation_errors = []
            frame_validation_warnings = []
            
            all_frame_uris = set(edge_based_frames.keys()) | set(grouping_based_frames.keys())
            
            for frame_uri in all_frame_uris:
                self.logger.info(f"🔍 Validating frame-level grouping URIs for frame: {frame_uri}")
                
                frame_validation = await self.validate_frame_graph_integrity(space_id, graph_id, frame_uri)
                frame_validation_results[frame_uri] = frame_validation
                
                if not frame_validation.get('valid', False):
                    frame_validation_errors.extend(frame_validation.get('validation_errors', []))
                
                if frame_validation.get('validation_warnings'):
                    frame_validation_warnings.extend(frame_validation.get('validation_warnings', []))
            
            # Step 6: Compile comprehensive results
            all_errors = (hierarchy_errors + 
                         entity_comparison_results.get('errors', []) + 
                         frame_validation_errors)
            all_warnings = (entity_comparison_results.get('warnings', []) + 
                           frame_validation_warnings)
            
            # Check overall frame validation consistency
            frame_validation_consistent = all(result.get('valid', False) for result in frame_validation_results.values())
            
            self.logger.info(f"✅ Entity graph validation completed:")
            self.logger.info(f"   Entity-level frames: {len(all_frame_uris)}")
            self.logger.info(f"   Hierarchy valid: {hierarchy_valid}")
            self.logger.info(f"   Entity grouping consistent: {entity_comparison_results.get('consistent', False)}")
            self.logger.info(f"   Frame-level validation consistent: {frame_validation_consistent}")
            self.logger.info(f"   Total errors: {len(all_errors)}")
            self.logger.info(f"   Total warnings: {len(all_warnings)}")
            
            return EntityGraphValidationResult(
                valid=len(all_errors) == 0,
                entity_uri=entity_uri,
                discovered_frames=all_frame_uris,
                hierarchy_valid=hierarchy_valid,
                grouping_consistency=entity_comparison_results.get('consistent', False) and frame_validation_consistent,
                validation_errors=all_errors,
                validation_warnings=all_warnings,
                edge_based_discovery={
                    'frame_count': len(edge_based_frames),
                    'frames': {uri: {
                        'level': node.level,
                        'parent_count': len(node.parent_frames),
                        'child_count': len(node.child_frames)
                    } for uri, node in edge_based_frames.items()}
                },
                grouping_based_discovery={
                    'frame_count': len(grouping_based_frames),
                    'frames': {uri: {
                        'level': node.level,
                        'parent_count': len(node.parent_frames),
                        'child_count': len(node.child_frames)
                    } for uri, node in grouping_based_frames.items()}
                },
                comparison_results={
                    'entity_level': entity_comparison_results,
                    'frame_level': frame_validation_results,
                    'frame_validation_consistent': frame_validation_consistent
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error in complete entity graph validation: {e}")
            return EntityGraphValidationResult(
                valid=False,
                entity_uri=entity_uri,
                discovered_frames=set(),
                hierarchy_valid=False,
                grouping_consistency=False,
                validation_errors=[f"Validation failed: {str(e)}"],
                validation_warnings=[],
                edge_based_discovery={},
                grouping_based_discovery={},
                comparison_results={}
            )
    
    def _compare_discovery_methods(self, edge_based: Dict[str, FrameHierarchyNode], grouping_based: Dict[str, FrameHierarchyNode]) -> Dict[str, Any]:
        """Compare edge-based and grouping URI-based discovery results."""
        errors = []
        warnings = []
        
        edge_frames = set(edge_based.keys())
        grouping_frames = set(grouping_based.keys())
        
        # Check for missing frames
        missing_in_grouping = edge_frames - grouping_frames
        missing_in_edge = grouping_frames - edge_frames
        
        if missing_in_grouping:
            errors.append(f"Frames found via edges but missing in grouping URI discovery: {missing_in_grouping}")
        
        if missing_in_edge:
            errors.append(f"Frames found via grouping URIs but missing in edge discovery: {missing_in_edge}")
        
        # Check consistency for common frames
        common_frames = edge_frames & grouping_frames
        for frame_uri in common_frames:
            edge_node = edge_based[frame_uri]
            grouping_node = grouping_based[frame_uri]
            
            if edge_node.parent_frames != grouping_node.parent_frames:
                errors.append(f"Parent mismatch for {frame_uri}: edge={edge_node.parent_frames}, grouping={grouping_node.parent_frames}")
            
            if edge_node.child_frames != grouping_node.child_frames:
                errors.append(f"Child mismatch for {frame_uri}: edge={edge_node.child_frames}, grouping={grouping_node.child_frames}")
            
            if edge_node.level != grouping_node.level:
                warnings.append(f"Level mismatch for {frame_uri}: edge={edge_node.level}, grouping={grouping_node.level}")
        
        return {
            'consistent': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'edge_frame_count': len(edge_frames),
            'grouping_frame_count': len(grouping_frames),
            'common_frame_count': len(common_frames),
            'missing_in_grouping_count': len(missing_in_grouping),
            'missing_in_edge_count': len(missing_in_edge)
        }
    
    async def discover_frame_graph_via_edges(self, space_id: str, graph_id: str, frame_uri: str) -> Dict[str, Any]:
        """
        Discover complete frame graph using SPARQL edge traversal (frame-to-slot edges).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to discover slots for
            
        Returns:
            Dict[str, Any]: Frame graph discovery results with slots and edges
        """
        try:
            # Step 1: Find all slots connected to this frame via Edge_hasKGSlot
            frame_slots_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?slot_uri ?slot_type WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot ;
                          vital:hasEdgeSource <{frame_uri}> ;
                          vital:hasEdgeDestination ?slot_uri .
                    ?slot_uri a ?slot_type .
                }}
            }}
            """
            
            slots_result = await self.backend.execute_sparql_query(space_id, frame_slots_query)
            discovered_slots = {}
            
            if isinstance(slots_result, dict) and slots_result.get("results", {}).get("bindings"):
                for binding in slots_result["results"]["bindings"]:
                    slot_uri = binding.get("slot_uri", {}).get("value")
                    slot_type = binding.get("slot_type", {}).get("value")
                    
                    if slot_uri and slot_type:
                        # Extract simple type name
                        type_name = slot_type.split('#')[-1] if '#' in slot_type else slot_type
                        discovered_slots[slot_uri] = {
                            'type': type_name,
                            'discovered_via_edge': True
                        }
            
            # Step 2: Find all Edge_hasKGSlot edges for this frame
            frame_edges_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?edge_uri WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge_uri a haley:Edge_hasKGSlot ;
                              vital:hasEdgeSource <{frame_uri}> .
                }}
            }}
            """
            
            edges_result = await self.backend.execute_sparql_query(space_id, frame_edges_query)
            discovered_edges = []
            
            if isinstance(edges_result, dict) and edges_result.get("results", {}).get("bindings"):
                for binding in edges_result["results"]["bindings"]:
                    edge_uri = binding.get("edge_uri", {}).get("value")
                    if edge_uri:
                        discovered_edges.append(edge_uri)
            
            self.logger.info(f"Discovered frame graph via edges for {frame_uri}: {len(discovered_slots)} slots, {len(discovered_edges)} edges")
            
            return {
                'frame_uri': frame_uri,
                'slots': discovered_slots,
                'edges': discovered_edges,
                'slot_count': len(discovered_slots),
                'edge_count': len(discovered_edges),
                'discovery_method': 'edge_based'
            }
            
        except Exception as e:
            self.logger.error(f"Error discovering frame graph via edges: {e}")
            return {
                'frame_uri': frame_uri,
                'slots': {},
                'edges': [],
                'slot_count': 0,
                'edge_count': 0,
                'discovery_method': 'edge_based',
                'error': str(e)
            }
    
    async def discover_frame_graph_via_grouping_uri(self, space_id: str, graph_id: str, frame_uri: str) -> Dict[str, Any]:
        """
        Discover frame graph using frameGraphURI-based approach.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to discover components for
            
        Returns:
            Dict[str, Any]: Frame graph discovery results with slots and objects
        """
        try:
            # Find all objects with matching hasFrameGraphURI
            grouping_objects_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?object_uri ?object_type WHERE {{
                GRAPH <{graph_id}> {{
                    ?object_uri haley:hasFrameGraphURI <{frame_uri}> ;
                                a ?object_type .
                }}
            }}
            """
            
            grouping_result = await self.backend.execute_sparql_query(space_id, grouping_objects_query)
            discovered_objects = {}
            discovered_slots = {}
            discovered_edges = []
            
            if isinstance(grouping_result, dict) and grouping_result.get("results", {}).get("bindings"):
                for binding in grouping_result["results"]["bindings"]:
                    object_uri = binding.get("object_uri", {}).get("value")
                    object_type = binding.get("object_type", {}).get("value")
                    
                    if object_uri and object_type:
                        # Extract simple type name
                        type_name = object_type.split('#')[-1] if '#' in object_type else object_type
                        
                        # Categorize objects (check Edge first to avoid Edge_hasKGSlot being categorized as Slot)
                        if 'Edge' in type_name:
                            discovered_edges.append(object_uri)
                        elif 'Slot' in type_name:
                            discovered_slots[object_uri] = {
                                'type': type_name,
                                'discovered_via_grouping': True
                            }
                        
                        discovered_objects[object_uri] = {
                            'type': type_name,
                            'discovered_via_grouping': True
                        }
            
            self.logger.info(f"Discovered frame graph via grouping URI for {frame_uri}: {len(discovered_slots)} slots, {len(discovered_edges)} edges, {len(discovered_objects)} total objects")
            
            return {
                'frame_uri': frame_uri,
                'slots': discovered_slots,
                'edges': discovered_edges,
                'objects': discovered_objects,
                'slot_count': len(discovered_slots),
                'edge_count': len(discovered_edges),
                'object_count': len(discovered_objects),
                'discovery_method': 'grouping_based'
            }
            
        except Exception as e:
            self.logger.error(f"Error discovering frame graph via grouping URI: {e}")
            return {
                'frame_uri': frame_uri,
                'slots': {},
                'edges': [],
                'objects': {},
                'slot_count': 0,
                'edge_count': 0,
                'object_count': 0,
                'discovery_method': 'grouping_based',
                'error': str(e)
            }
    
    def _compare_frame_discovery_methods(self, edge_based: Dict[str, Any], grouping_based: Dict[str, Any]) -> Dict[str, Any]:
        """Compare edge-based and grouping URI-based frame discovery results."""
        errors = []
        warnings = []
        frame_uri = edge_based.get('frame_uri', 'unknown')
        
        # Compare slot discovery
        edge_slots = set(edge_based.get('slots', {}).keys())
        grouping_slots = set(grouping_based.get('slots', {}).keys())
        
        missing_in_grouping = edge_slots - grouping_slots
        missing_in_edge = grouping_slots - edge_slots
        
        if missing_in_grouping:
            errors.append(f"Frame {frame_uri}: Slots found via edges but missing in grouping URI discovery: {missing_in_grouping}")
        
        if missing_in_edge:
            errors.append(f"Frame {frame_uri}: Slots found via grouping URI but missing in edge discovery: {missing_in_edge}")
        
        # Compare slot counts
        edge_slot_count = edge_based.get('slot_count', 0)
        grouping_slot_count = grouping_based.get('slot_count', 0)
        
        if edge_slot_count != grouping_slot_count:
            errors.append(f"Frame {frame_uri}: Slot count mismatch - edge discovery: {edge_slot_count}, grouping discovery: {grouping_slot_count}")
        
        # Compare slot types for common slots
        common_slots = edge_slots & grouping_slots
        for slot_uri in common_slots:
            edge_slot_info = edge_based['slots'].get(slot_uri, {})
            grouping_slot_info = grouping_based['slots'].get(slot_uri, {})
            
            edge_type = edge_slot_info.get('type')
            grouping_type = grouping_slot_info.get('type')
            
            if edge_type != grouping_type:
                warnings.append(f"Frame {frame_uri}: Slot type mismatch for {slot_uri} - edge: {edge_type}, grouping: {grouping_type}")
        
        return {
            'frame_uri': frame_uri,
            'consistent': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'edge_slot_count': edge_slot_count,
            'grouping_slot_count': grouping_slot_count,
            'common_slot_count': len(common_slots),
            'missing_in_grouping_count': len(missing_in_grouping),
            'missing_in_edge_count': len(missing_in_edge)
        }
    
    async def validate_frame_graph_integrity(self, space_id: str, graph_id: str, frame_uri: str) -> Dict[str, Any]:
        """
        Validate frame graph integrity by comparing edge-based and grouping URI-based discovery.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to validate
            
        Returns:
            Dict[str, Any]: Frame validation results
        """
        try:
            # Step 1: Discover frame graph via edges
            edge_based_result = await self.discover_frame_graph_via_edges(space_id, graph_id, frame_uri)
            
            # Step 2: Discover frame graph via grouping URI
            grouping_based_result = await self.discover_frame_graph_via_grouping_uri(space_id, graph_id, frame_uri)
            
            # Step 3: Compare discovery methods
            comparison_result = self._compare_frame_discovery_methods(edge_based_result, grouping_based_result)
            
            # Step 4: Overall validation result
            is_valid = comparison_result['consistent'] and not edge_based_result.get('error') and not grouping_based_result.get('error')
            
            return {
                'frame_uri': frame_uri,
                'valid': is_valid,
                'edge_based_discovery': edge_based_result,
                'grouping_based_discovery': grouping_based_result,
                'comparison_results': comparison_result,
                'validation_errors': comparison_result.get('errors', []),
                'validation_warnings': comparison_result.get('warnings', [])
            }
            
        except Exception as e:
            self.logger.error(f"Error validating frame graph integrity: {e}")
            return {
                'frame_uri': frame_uri,
                'valid': False,
                'validation_errors': [f"Frame validation failed: {str(e)}"],
                'validation_warnings': [],
                'error': str(e)
            }