"""Graph Validation

Validates and separates KG entity and frame graphs using Edge-based relationships.
Uses VitalSigns native methods and proper isinstance() type checking.
"""

import logging
from typing import Dict, List, Any, Set, Optional

from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

logger = logging.getLogger(__name__)


class EntityGraphValidator:
    """Validates and separates entity graphs using Edge-based relationships."""
    
    def __init__(self):
        """Initialize the entity graph validator."""
        self.vitalsigns = VitalSigns()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def validate_and_separate_entity_graph(self, jsonld_document: dict) -> Dict[str, Dict]:
        """
        Validate and separate entity graphs from JSON-LD document.
        Uses Edge-based relationship discovery instead of direct properties.
        """
        # Step 1: Convert JSON-LD to VitalSigns objects
        objects = self.vitalsigns.from_jsonld_list(jsonld_document)
        
        # Step 2: Categorize objects using isinstance
        entities = []
        frames = []
        slots = []
        edges = []
        
        for obj in objects:
            if isinstance(obj, KGEntity):
                entities.append(obj)
            elif isinstance(obj, KGFrame):
                frames.append(obj)
            elif isinstance(obj, KGSlot):  # Catches all slot subclasses
                slots.append(obj)
            elif isinstance(obj, VITAL_Edge):
                edges.append(obj)
        
        # Step 3: Build entity graphs using Edge relationships
        entity_graphs = {}
        for entity in entities:
            entity_uri = str(entity.URI)
            entity_graph = self._build_entity_graph_from_edges(
                entity, frames, slots, edges
            )
            entity_graphs[entity_uri] = entity_graph
        
        # Step 4: Validate completeness and detect orphaned objects
        self._validate_graph_completeness(entity_graphs, objects)
        
        return entity_graphs
    
    def _build_entity_graph_from_edges(self, entity: KGEntity, frames: List[KGFrame], 
                                     slots: List[KGSlot], edges: List[VITAL_Edge]) -> Dict:
        """Build entity graph using Edge-based relationship discovery."""
        entity_uri = str(entity.URI)
        entity_graph = {
            'entities': [entity],
            'frames': [],
            'slots': [],
            'edges': []
        }
        
        # Find frames connected to this entity via Edge_hasKGFrame
        entity_frames = self._find_entity_frames(entity_uri, frames, edges)
        entity_graph['frames'].extend(entity_frames)
        
        # Find slots connected to entity frames via Edge_hasKGSlot
        for frame in entity_frames:
            frame_uri = str(frame.URI)
            frame_slots = self._find_frame_slots(frame_uri, slots, edges)
            entity_graph['slots'].extend(frame_slots)
        
        # Find all edges related to this entity graph
        related_edges = self._find_related_edges(entity_uri, entity_frames, edges)
        entity_graph['edges'].extend(related_edges)
        
        return entity_graph
    
    def _find_entity_frames(self, entity_uri: str, frames: List[KGFrame], 
                           edges: List[VITAL_Edge]) -> List[KGFrame]:
        """Find frames connected to entity via Edge_hasKGFrame relationships."""
        connected_frames = []
        
        for edge in edges:
            # Check if this is an Edge_hasKGFrame connecting to our entity
            if (hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination') and
                str(edge.hasEdgeSource) == entity_uri and 
                type(edge).__name__ == 'Edge_hasKGFrame'):
                
                # Find the destination frame
                destination_uri = str(edge.hasEdgeDestination)
                for frame in frames:
                    if str(frame.URI) == destination_uri:
                        connected_frames.append(frame)
                        break
        
        return connected_frames
    
    def _find_frame_slots(self, frame_uri: str, slots: List[KGSlot], 
                         edges: List[VITAL_Edge]) -> List[KGSlot]:
        """Find slots connected to frame via Edge_hasKGSlot relationships."""
        connected_slots = []
        
        for edge in edges:
            # Check if this is an Edge_hasKGSlot connecting to our frame
            if (hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination') and
                str(edge.hasEdgeSource) == frame_uri and 
                type(edge).__name__ == 'Edge_hasKGSlot'):
                
                # Find the destination slot
                destination_uri = str(edge.hasEdgeDestination)
                for slot in slots:
                    if str(slot.URI) == destination_uri:
                        connected_slots.append(slot)
                        break
        
        return connected_slots
    
    def _find_related_edges(self, entity_uri: str, entity_frames: List[KGFrame], 
                           edges: List[VITAL_Edge]) -> List[VITAL_Edge]:
        """Find all edges related to this entity graph."""
        related_edges = []
        frame_uris = {str(frame.URI) for frame in entity_frames}
        
        for edge in edges:
            if hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination'):
                source_uri = str(edge.hasEdgeSource)
                destination_uri = str(edge.hasEdgeDestination)
                
                # Include edges where source or destination is part of this entity graph
                if (source_uri == entity_uri or source_uri in frame_uris or
                    destination_uri == entity_uri or destination_uri in frame_uris):
                    related_edges.append(edge)
        
        return related_edges
    
    def _validate_graph_completeness(self, entity_graphs: Dict[str, Dict], 
                                   all_objects: List) -> None:
        """Validate that all objects are accounted for in entity graphs."""
        accounted_objects = set()
        
        # Collect all objects that are part of entity graphs
        for entity_uri, graph in entity_graphs.items():
            for obj_list in graph.values():
                for obj in obj_list:
                    accounted_objects.add(str(obj.URI))
        
        # Check for orphaned objects
        orphaned_objects = []
        for obj in all_objects:
            if str(obj.URI) not in accounted_objects:
                orphaned_objects.append(obj)
        
        if orphaned_objects:
            orphaned_uris = [str(obj.URI) for obj in orphaned_objects]
            raise ValueError(f"Found {len(orphaned_objects)} orphaned objects not "
                           f"belonging to any entity graph: {orphaned_uris}")


class FrameGraphValidator:
    """Validates and separates frame graphs using Edge-based relationships."""
    
    def __init__(self):
        self.vitalsigns = VitalSigns()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def validate_and_separate_frame_graph(self, jsonld_document: dict) -> Dict[str, Dict]:
        """
        Validate and separate frame graphs from JSON-LD document.
        Uses Edge-based relationship discovery for frame-to-frame and frame-to-slot relationships.
        """
        # Step 1: Convert JSON-LD to VitalSigns objects
        objects = self.vitalsigns.from_jsonld_list(jsonld_document)
        
        # Step 2: Categorize objects using isinstance
        frames = []
        slots = []
        edges = []
        
        for obj in objects:
            if isinstance(obj, KGFrame):
                frames.append(obj)
            elif isinstance(obj, KGSlot):  # Catches all slot subclasses
                slots.append(obj)
            elif isinstance(obj, VITAL_Edge):
                edges.append(obj)
        
        # Step 3: Build frame graphs using Edge relationships
        frame_graphs = {}
        processed_frames = set()
        
        for frame in frames:
            frame_uri = str(frame.URI)
            if frame_uri not in processed_frames:
                frame_graph = self._build_frame_graph_from_edges(
                    frame, frames, slots, edges, processed_frames
                )
                frame_graphs[frame_uri] = frame_graph
        
        # Step 4: Validate completeness
        self._validate_frame_graph_completeness(frame_graphs, objects)
        
        return frame_graphs
    
    def _build_frame_graph_from_edges(self, root_frame: KGFrame, all_frames: List[KGFrame],
                                    slots: List[KGSlot], edges: List[VITAL_Edge],
                                    processed_frames: Set[str]) -> Dict:
        """Build frame graph using Edge-based relationship discovery."""
        frame_uri = str(root_frame.URI)
        processed_frames.add(frame_uri)
        
        frame_graph = {
            'frames': [root_frame],
            'slots': [],
            'edges': []
        }
        
        # Find slots connected to this frame via Edge_hasKGSlot
        frame_slots = self._find_frame_slots(frame_uri, slots, edges)
        frame_graph['slots'].extend(frame_slots)
        
        # Find child frames connected via Edge_hasKGFrame (frame-to-frame)
        child_frames = self._find_child_frames(frame_uri, all_frames, edges)
        for child_frame in child_frames:
            child_uri = str(child_frame.URI)
            if child_uri not in processed_frames:
                # Recursively build child frame graphs
                child_graph = self._build_frame_graph_from_edges(
                    child_frame, all_frames, slots, edges, processed_frames
                )
                frame_graph['frames'].extend(child_graph['frames'])
                frame_graph['slots'].extend(child_graph['slots'])
                frame_graph['edges'].extend(child_graph['edges'])
        
        # Find all edges related to this frame graph
        related_edges = self._find_frame_related_edges(frame_uri, frame_slots, edges)
        frame_graph['edges'].extend(related_edges)
        
        return frame_graph
    
    def _find_child_frames(self, parent_frame_uri: str, frames: List[KGFrame],
                          edges: List[VITAL_Edge]) -> List[KGFrame]:
        """Find child frames connected via Edge_hasKGFrame relationships."""
        child_frames = []
        
        for edge in edges:
            # Check if this is an Edge_hasKGFrame with parent frame as source
            if (hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination') and
                str(edge.hasEdgeSource) == parent_frame_uri and 
                type(edge).__name__ == 'Edge_hasKGFrame'):
                
                # Find the destination frame
                destination_uri = str(edge.hasEdgeDestination)
                for frame in frames:
                    if str(frame.URI) == destination_uri:
                        child_frames.append(frame)
                        break
        
        return child_frames
    
    def _find_frame_slots(self, frame_uri: str, slots: List[KGSlot], 
                         edges: List[VITAL_Edge]) -> List[KGSlot]:
        """Find slots connected to frame via Edge_hasKGSlot relationships."""
        connected_slots = []
        
        for edge in edges:
            # Check if this is an Edge_hasKGSlot connecting to our frame
            if (hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination') and
                str(edge.hasEdgeSource) == frame_uri and 
                type(edge).__name__ == 'Edge_hasKGSlot'):
                
                # Find the destination slot
                destination_uri = str(edge.hasEdgeDestination)
                for slot in slots:
                    if str(slot.URI) == destination_uri:
                        connected_slots.append(slot)
                        break
        
        return connected_slots
    
    def _find_frame_related_edges(self, frame_uri: str, frame_slots: List[KGSlot],
                                 edges: List[VITAL_Edge]) -> List[VITAL_Edge]:
        """Find all edges related to this frame and its slots."""
        related_edges = []
        slot_uris = {str(slot.URI) for slot in frame_slots}
        
        for edge in edges:
            if hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination'):
                source_uri = str(edge.hasEdgeSource)
                destination_uri = str(edge.hasEdgeDestination)
                
                # Include edges where source or destination is part of this frame graph
                if (source_uri == frame_uri or source_uri in slot_uris or
                    destination_uri == frame_uri or destination_uri in slot_uris):
                    related_edges.append(edge)
        
        return related_edges
    
    def _validate_frame_graph_completeness(self, frame_graphs: Dict[str, Dict],
                                         all_objects: List) -> None:
        """Validate that all frame-related objects are accounted for."""
        accounted_objects = set()
        
        # Collect all objects that are part of frame graphs
        for frame_uri, graph in frame_graphs.items():
            for obj_list in graph.values():
                for obj in obj_list:
                    accounted_objects.add(str(obj.URI))
        
        # Check for orphaned frame-related objects
        orphaned_objects = []
        for obj in all_objects:
            # Only check frames, slots, and edges (entities are handled separately)
            if (isinstance(obj, (KGFrame, KGSlot, VITAL_Edge)) and 
                str(obj.URI) not in accounted_objects):
                orphaned_objects.append(obj)
        
        if orphaned_objects:
            orphaned_uris = [str(obj.URI) for obj in orphaned_objects]
            raise ValueError(f"Found {len(orphaned_objects)} orphaned frame-related objects: {orphaned_uris}")
