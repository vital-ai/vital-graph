"""
KG Validation Utilities

This module provides validation functions for KG entities, frames, and related objects.
It includes structure validation, relationship validation, and data integrity checks.
"""

import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot


@dataclass
class ValidationResult:
    """Result of a validation operation."""
    valid: bool
    message: str
    errors: List[str] = None
    warnings: List[str] = None
    data: Optional[Dict[str, Any]] = None


class KGEntityValidator:
    """Validator for KG entity structures and relationships."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGEntityValidator")
    
    def validate_entity_structure(self, objects: List[GraphObject]) -> ValidationResult:
        """
        Validate the structure of KG entity objects.
        
        Args:
            objects: List of VitalSigns objects to validate
            
        Returns:
            ValidationResult with validation details
        """
        try:
            errors = []
            warnings = []
            
            # Categorize objects
            entities = [obj for obj in objects if isinstance(obj, KGEntity)]
            frames = [obj for obj in objects if isinstance(obj, KGFrame)]
            slots = [obj for obj in objects if isinstance(obj, KGSlot)]
            edges = [obj for obj in objects if isinstance(obj, VITAL_Edge)]
            
            # Validate we have at least one entity
            if not entities:
                errors.append("No KGEntity objects found in the structure")
            
            # Validate entity properties
            for entity in entities:
                entity_errors = self._validate_entity_properties(entity)
                errors.extend(entity_errors)
            
            # Validate frame properties
            for frame in frames:
                frame_errors = self._validate_frame_properties(frame)
                errors.extend(frame_errors)
            
            # Validate slot properties
            for slot in slots:
                slot_errors = self._validate_slot_properties(slot)
                errors.extend(slot_errors)
            
            # Validate edge relationships
            edge_errors = self._validate_edge_relationships(edges, entities, frames, slots)
            errors.extend(edge_errors)
            
            # Check for orphaned objects
            orphan_warnings = self._check_orphaned_objects(objects)
            warnings.extend(orphan_warnings)
            
            return ValidationResult(
                valid=len(errors) == 0,
                message=f"Validation {'passed' if len(errors) == 0 else 'failed'} with {len(errors)} errors, {len(warnings)} warnings",
                errors=errors,
                warnings=warnings,
                data={
                    "entity_count": len(entities),
                    "frame_count": len(frames),
                    "slot_count": len(slots),
                    "edge_count": len(edges)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error during entity structure validation: {e}")
            return ValidationResult(
                valid=False,
                message=f"Validation error: {str(e)}",
                errors=[str(e)]
            )
    
    def validate_frame_structure(self, objects: List[GraphObject]) -> ValidationResult:
        """
        Validate frame structure and extract frame URIs.
        
        Args:
            objects: List of VitalSigns objects containing frames
            
        Returns:
            ValidationResult with frame URIs and validation details
        """
        try:
            errors = []
            warnings = []
            
            # Extract frames
            frames = [obj for obj in objects if isinstance(obj, KGFrame)]
            
            if not frames:
                return ValidationResult(
                    valid=False,
                    message="No KGFrame objects found",
                    errors=["No KGFrame objects found in the structure"]
                )
            
            # Validate each frame
            frame_uris = []
            for frame in frames:
                if not frame.URI:
                    errors.append(f"Frame missing URI: {frame}")
                    continue
                
                frame_uri = str(frame.URI)
                frame_uris.append(frame_uri)
                
                # Validate frame properties
                frame_errors = self._validate_frame_properties(frame)
                errors.extend(frame_errors)
            
            return ValidationResult(
                valid=len(errors) == 0,
                message=f"Frame validation {'passed' if len(errors) == 0 else 'failed'}",
                errors=errors,
                warnings=warnings,
                data={"frame_uris": frame_uris}
            )
            
        except Exception as e:
            self.logger.error(f"Error during frame structure validation: {e}")
            return ValidationResult(
                valid=False,
                message=f"Frame validation error: {str(e)}",
                errors=[str(e)]
            )
    
    def _validate_entity_properties(self, entity: KGEntity) -> List[str]:
        """Validate individual entity properties."""
        errors = []
        
        # Check required properties
        if not entity.URI:
            errors.append(f"Entity missing URI: {entity}")
        
        try:
            if entity.name and len(str(entity.name).strip()) == 0:
                errors.append(f"Entity has empty name: {entity.URI}")
        except:
            # Entity doesn't have name property
            pass
        
        # Validate URI format
        if entity.URI:
            uri_str = str(entity.URI)
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if not validate_rfc3986(uri_str, rule='URI'):
                errors.append(f"Entity URI not in proper format: {uri_str}")
        
        return errors
    
    def _validate_frame_properties(self, frame: KGFrame) -> List[str]:
        """Validate individual frame properties."""
        errors = []
        
        # Check required properties
        if not frame.URI:
            errors.append(f"Frame missing URI: {frame}")
        
        # Validate URI format
        if frame.URI:
            uri_str = str(frame.URI)
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if not validate_rfc3986(uri_str, rule='URI'):
                errors.append(f"Frame URI not in proper format: {uri_str}")
        
        return errors
    
    def _validate_slot_properties(self, slot: KGSlot) -> List[str]:
        """Validate individual slot properties."""
        errors = []
        
        # Check required properties
        if not slot.URI:
            errors.append(f"Slot missing URI: {slot}")
        
        # Validate URI format
        if slot.URI:
            uri_str = str(slot.URI)
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if not validate_rfc3986(uri_str, rule='URI'):
                errors.append(f"Slot URI not in proper format: {uri_str}")
        
        return errors
    
    def _validate_edge_relationships(self, edges: List[VITAL_Edge], 
                                   entities: List[KGEntity], 
                                   frames: List[KGFrame], 
                                   slots: List[KGSlot]) -> List[str]:
        """Validate edge relationships are consistent."""
        errors = []
        
        # Create URI sets for quick lookup
        entity_uris = {str(e.URI) for e in entities}
        frame_uris = {str(f.URI) for f in frames}
        slot_uris = {str(s.URI) for s in slots}
        all_uris = entity_uris | frame_uris | slot_uris
        
        for edge in edges:
            # Validate edge has source and destination
            if not edge.edgeSource:
                errors.append(f"Edge missing edgeSource: {edge.URI}")
                continue
            
            if not edge.edgeDestination:
                errors.append(f"Edge missing edgeDestination: {edge.URI}")
                continue
            
            source_uri = str(edge.edgeSource)
            dest_uri = str(edge.edgeDestination)
            
            # Check if source and destination exist in our object set
            if source_uri not in all_uris:
                errors.append(f"Edge source not found in objects: {source_uri}")
            
            if dest_uri not in all_uris:
                errors.append(f"Edge destination not found in objects: {dest_uri}")
        
        return errors
    
    def _check_orphaned_objects(self, objects: List[GraphObject]) -> List[str]:
        """Check for objects that might be orphaned (not connected to main entity)."""
        warnings = []
        
        # This is a simplified check - in a full implementation, you'd analyze
        # the graph structure to find truly orphaned objects
        entities = [obj for obj in objects if isinstance(obj, KGEntity)]
        frames = [obj for obj in objects if isinstance(obj, KGFrame)]
        slots = [obj for obj in objects if isinstance(obj, KGSlot)]
        edges = [obj for obj in objects if isinstance(obj, VITAL_Edge)]
        
        # If we have frames but no entity-frame edges, warn about potential orphans
        if frames and not any('hasKGFrame' in str(type(edge)) or 'hasEntityKGFrame' in str(type(edge)) 
                             for edge in edges):
            warnings.append("Frames found but no entity-frame connection edges detected")
        
        # If we have slots but no frame-slot edges, warn about potential orphans
        if slots and not any('hasKGSlot' in str(type(edge)) or 'hasFrameKGSlot' in str(type(edge)) 
                            for edge in edges):
            warnings.append("Slots found but no frame-slot connection edges detected")
        
        return warnings


class KGGroupingURIManager:
    """Manager for setting and validating grouping URIs on KG objects."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.KGGroupingURIManager")
    
    def set_dual_grouping_uris_with_frame_separation(self, objects: List[GraphObject], entity_uri: str) -> None:
        """
        Set dual grouping URIs with frame separation logic.
        
        This implements the same logic as the current KGEntities endpoint:
        - Entity-level grouping (hasKGGraphURI) for complete entity graph retrieval
        - Frame-level grouping (hasFrameGraphURI) for complete frame graph retrieval
        
        Args:
            objects: List of VitalSigns objects to process
            entity_uri: URI of the main entity
        """
        try:
            # Categorize objects by type
            entities = [obj for obj in objects if isinstance(obj, KGEntity)]
            frames = [obj for obj in objects if isinstance(obj, KGFrame)]
            slots = [obj for obj in objects if isinstance(obj, KGSlot)]
            edges = [obj for obj in objects if isinstance(obj, VITAL_Edge)]
            
            # Set entity-level grouping URI on all objects
            for obj in objects:
                obj.kGGraphURI = entity_uri
            
            self.logger.info(f"Set kGGraphURI={entity_uri} on {len(objects)} objects")
            
            # Set frame-level grouping URIs using frame separation logic
            self.logger.info(f"Processing {len(frames)} frames, {len(slots)} slots, {len(edges)} edges for frame grouping")
            
            for frame in frames:
                frame_uri = str(frame.URI)
                
                # Find all objects that belong to this frame
                frame_objects = [frame]  # Include the frame itself
                
                # Find slots and edges connected to this frame
                slots_found = 0
                for edge in edges:
                    if (edge.edgeSource and str(edge.edgeSource) == frame_uri and
                        edge.edgeDestination):
                        dest_uri = str(edge.edgeDestination)
                        # Find the slot object
                        for slot in slots:
                            if str(slot.URI) == dest_uri:
                                frame_objects.append(slot)
                                # Also add the edge itself to frame objects
                                frame_objects.append(edge)
                                slots_found += 1
                                break
                
                if slots_found > 0:
                    self.logger.info(f"Frame {frame_uri.split(':')[-2] if ':' in frame_uri else frame_uri}: found {slots_found} slots")
                
                # Set frame-level grouping URI on frame objects (including edges)
                for obj in frame_objects:
                    obj.frameGraphURI = frame_uri
                    # self.logger.debug(f"Set frameGraphURI={frame_uri} on {type(obj).__name__} {obj.URI}")
            
            self.logger.info(f"Set dual grouping URIs for {len(objects)} objects with entity URI: {entity_uri}")
            
        except Exception as e:
            self.logger.error(f"Error setting dual grouping URIs: {e}")
            raise
    
    def validate_grouping_uris(self, objects: List[GraphObject], entity_uri: str) -> ValidationResult:
        """
        Validate that grouping URIs are properly set on objects.
        
        Args:
            objects: List of VitalSigns objects to validate
            entity_uri: Expected entity URI for grouping
            
        Returns:
            ValidationResult with validation details
        """
        try:
            errors = []
            warnings = []
            
            entity_grouping_count = 0
            frame_grouping_count = 0
            
            for obj in objects:
                # Check entity-level grouping
                try:
                    if obj.kGGraphURI == entity_uri:
                        entity_grouping_count += 1
                    else:
                        warnings.append(f"Object has incorrect entity grouping URI: {obj.URI}")
                except:
                    # Object doesn't have kGGraphURI property
                    pass
                
                # Check frame-level grouping
                try:
                    if obj.kGFrameGraphURI:
                        frame_grouping_count += 1
                except:
                    # Object doesn't have kGFrameGraphURI property
                    pass
            
            return ValidationResult(
                valid=len(errors) == 0,
                message=f"Grouping URI validation {'passed' if len(errors) == 0 else 'failed'}",
                errors=errors,
                warnings=warnings,
                data={
                    "entity_grouping_count": entity_grouping_count,
                    "frame_grouping_count": frame_grouping_count
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error validating grouping URIs: {e}")
            return ValidationResult(
                valid=False,
                message=f"Grouping URI validation error: {str(e)}",
                errors=[str(e)]
            )


class KGHierarchicalFrameValidator:
    """Validator for hierarchical frame operations and relationships."""
    
    def __init__(self, backend_adapter, logger: logging.Logger):
        """
        Initialize the hierarchical frame validator.
        
        Args:
            backend_adapter: Backend adapter for SPARQL operations
            logger: Logger instance
        """
        self.backend = backend_adapter
        self.logger = logger
    
    async def validate_parent_frame(self, space_id: str, graph_id: str, entity_uri: str, parent_frame_uri: str) -> bool:
        """
        Validate that parent_frame_uri exists and belongs to the specified entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI that should own the parent frame
            parent_frame_uri: Parent frame URI to validate
            
        Returns:
            bool: True if parent frame is valid, False otherwise
        """
        try:
            # SPARQL query to check if parent frame exists and has kGGraphURI matching entity
            # Since parent_frame_uri is for immediate parent-child only, we just validate:
            # 1. Parent frame exists
            # 2. Parent frame belongs to this entity (has matching kGGraphURI)
            validation_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            ASK {{
                GRAPH <{graph_id}> {{
                    # Check if parent frame exists and belongs to this entity
                    <{parent_frame_uri}> a haley:KGFrame ;
                                         haley:hasKGGraphURI <{entity_uri}> .
                }}
            }}
            """
            
            # Debug: First check what properties the frame actually has
            debug_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?p ?o WHERE {{
                GRAPH <{graph_id}> {{
                    <{parent_frame_uri}> ?p ?o .
                }}
            }}
            """
            
            debug_result = await self.backend.execute_sparql_query(space_id, debug_query)
            self.logger.info(f"🔍 DEBUG: Frame {parent_frame_uri} properties: {debug_result}")
            
            # Execute validation query
            result = await self.backend.execute_sparql_query(space_id, validation_query)
            self.logger.info(f"🔍 DEBUG: Validation query result for {parent_frame_uri}: {result}")
            self.logger.info(f"🔍 DEBUG: Validation query was: {validation_query}")
            
            # Parse ASK query result
            if hasattr(result, 'boolean'):
                validation_result = result.boolean
                self.logger.info(f"🔍 DEBUG: Parsed boolean result: {validation_result}")
                return validation_result
            elif isinstance(result, dict):
                # Check for nested boolean in results.bindings.boolean
                if 'results' in result and 'bindings' in result['results'] and 'boolean' in result['results']['bindings']:
                    validation_result = result['results']['bindings']['boolean']
                    self.logger.info(f"🔍 DEBUG: Parsed nested boolean result: {validation_result}")
                    return validation_result
                # Check for direct boolean in result
                elif 'boolean' in result:
                    validation_result = result['boolean']
                    self.logger.info(f"🔍 DEBUG: Parsed dict boolean result: {validation_result}")
                    return validation_result
                else:
                    self.logger.warning(f"Could not find boolean in result structure: {result}")
                    return False
            elif isinstance(result, bool):
                self.logger.info(f"🔍 DEBUG: Direct boolean result: {result}")
                return result
            else:
                # If we can't parse the result, assume invalid for safety
                self.logger.warning(f"Could not parse parent frame validation result: {result}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error validating parent frame {parent_frame_uri}: {e}")
            return False
    
    async def validate_frame_ownership(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str]) -> Dict[str, bool]:
        """
        Validate that a list of frame URIs belong to the specified entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI that should own the frames
            frame_uris: List of frame URIs to validate
            
        Returns:
            Dict[str, bool]: Mapping of frame URIs to their ownership validation results
        """
        validation_results = {}
        
        try:
            for frame_uri in frame_uris:
                # SPARQL query to validate frame ownership
                ownership_query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                ASK {{
                    GRAPH <{graph_id}> {{
                        <{frame_uri}> a haley:KGFrame ;
                                      haley:hasKGGraphURI <{entity_uri}> .
                    }}
                }}
                """
                
                # Execute ownership validation
                result = await self.backend.execute_sparql_query(ownership_query)
                
                # Parse ASK query result
                if hasattr(result, 'boolean'):
                    validation_results[frame_uri] = result.boolean
                elif isinstance(result, dict) and 'boolean' in result:
                    validation_results[frame_uri] = result['boolean']
                elif isinstance(result, bool):
                    validation_results[frame_uri] = result
                else:
                    validation_results[frame_uri] = False
                    self.logger.warning(f"Could not parse ownership validation result for {frame_uri}: {result}")
            
            self.logger.info(f"Validated ownership for {len(frame_uris)} frames")
            return validation_results
            
        except Exception as e:
            self.logger.error(f"Error validating frame ownership: {e}")
            # Return False for all frames on error
            return {frame_uri: False for frame_uri in frame_uris}
    
    async def validate_frame_hierarchy(self, space_id: str, graph_id: str, entity_uri: str, parent_frame_uri: str, child_frame_uris: List[str]) -> ValidationResult:
        """
        Validate hierarchical frame relationships between parent and child frames.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI that owns the frames
            parent_frame_uri: Parent frame URI
            child_frame_uris: List of child frame URIs
            
        Returns:
            ValidationResult: Comprehensive validation result
        """
        try:
            errors = []
            warnings = []
            
            # Step 1: Validate parent frame exists and belongs to entity
            parent_valid = await self.validate_parent_frame(space_id, graph_id, entity_uri, parent_frame_uri)
            if not parent_valid:
                errors.append(f"Parent frame {parent_frame_uri} does not exist or does not belong to entity {entity_uri}")
            
            # Step 2: Validate child frames exist and belong to entity
            child_ownership = await self.validate_frame_ownership(space_id, graph_id, entity_uri, child_frame_uris)
            invalid_children = [uri for uri, valid in child_ownership.items() if not valid]
            if invalid_children:
                errors.extend([f"Child frame {uri} does not exist or does not belong to entity {entity_uri}" for uri in invalid_children])
            
            # Step 3: Validate hierarchical connections exist
            for child_uri in child_frame_uris:
                if child_ownership.get(child_uri, False):  # Only check valid children
                    connection_query = f"""
                    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                    PREFIX vital: <http://vital.ai/ontology/vital-core#>
                    
                    ASK {{
                        GRAPH <{graph_id}> {{
                            ?edge a haley:Edge_hasKGFrame ;
                                  vital:hasEdgeSource <{parent_frame_uri}> ;
                                  vital:hasEdgeDestination <{child_uri}> .
                        }}
                    }}
                    """
                    
                    connection_result = await self.backend.execute_sparql_query(connection_query)
                    connection_exists = False
                    
                    if hasattr(connection_result, 'boolean'):
                        connection_exists = connection_result.boolean
                    elif isinstance(connection_result, dict) and 'boolean' in connection_result:
                        connection_exists = connection_result['boolean']
                    elif isinstance(connection_result, bool):
                        connection_exists = connection_result
                    
                    if not connection_exists:
                        warnings.append(f"Missing Edge_hasKGFrame connection between {parent_frame_uri} and {child_uri}")
            
            # Determine overall validation result
            is_valid = len(errors) == 0
            message = f"Hierarchical frame validation {'passed' if is_valid else 'failed'}"
            if errors:
                message += f" with {len(errors)} errors"
            if warnings:
                message += f" and {len(warnings)} warnings"
            
            return ValidationResult(
                valid=is_valid,
                message=message,
                errors=errors if errors else None,
                warnings=warnings if warnings else None,
                data={
                    "parent_frame_valid": parent_valid,
                    "valid_child_count": len([uri for uri, valid in child_ownership.items() if valid]),
                    "invalid_child_count": len(invalid_children),
                    "total_child_count": len(child_frame_uris)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error validating frame hierarchy: {e}")
            return ValidationResult(
                valid=False,
                message=f"Frame hierarchy validation error: {str(e)}",
                errors=[str(e)]
            )
