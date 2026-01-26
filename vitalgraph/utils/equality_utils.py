from __future__ import annotations

from typing import Optional, Union, List
from .kg_member_utils import KGMemberUtils


class KGGraphObjectEqualityUtils:
    """Utility class containing equality comparison functionality for KG GraphObjects."""

    @staticmethod
    def equals(graph_object_a: 'GraphObject', graph_object_b: 'GraphObject', 
               ignore_properties: Optional[Union[List[str], None]] = None) -> bool:
        """
        Compare two GraphObjects for equality.
        
        Two GraphObjects are considered equal if they have:
        1. The same set of properties (including URI), excluding ignored properties
        2. All non-ignored properties have equal values
        3. Same extern properties (for GraphContainerObjects), excluding ignored properties
        
        Args:
            graph_object_a: First GraphObject to compare
            graph_object_b: Second GraphObject to compare
            ignore_properties: List of property URIs to ignore during comparison.
                             Useful for server-set properties like grouping URIs.
            
        Returns:
            bool: True if the objects are equal, False otherwise
        """
        # Handle null cases
        if graph_object_a is None and graph_object_b is None:
            return True
        if graph_object_a is None or graph_object_b is None:
            return False
            
        # Check if both objects are of the same type
        if type(graph_object_a) != type(graph_object_b):
            return False
            
        # Normalize ignore_properties to empty list if None
        ignore_list = ignore_properties or []
            
        # Compare main properties
        if not KGGraphObjectEqualityUtils._compare_properties(
            graph_object_a._properties, 
            graph_object_b._properties,
            ignore_list
        ):
            return False
            
        # Compare extern properties for GraphContainerObjects
        from vital_ai_vitalsigns.model.VITAL_GraphContainerObject import VITAL_GraphContainerObject
        
        is_container_a = isinstance(graph_object_a, VITAL_GraphContainerObject)
        is_container_b = isinstance(graph_object_b, VITAL_GraphContainerObject)
        
        # Both should be containers or both should not be containers
        if is_container_a != is_container_b:
            return False
            
        if is_container_a and is_container_b:
            if not KGGraphObjectEqualityUtils._compare_properties(
                graph_object_a._extern_properties,
                graph_object_b._extern_properties,
                ignore_list
            ):
                return False
                
        return True
    
    @staticmethod
    def _compare_properties(props_a: dict, props_b: dict, ignore_properties: List[str]) -> bool:
        """
        Compare two property dictionaries for equality, ignoring specified properties.
        
        Args:
            props_a: First property dictionary
            props_b: Second property dictionary
            ignore_properties: List of property URIs to ignore during comparison
            
        Returns:
            bool: True if properties are equal, False otherwise
        """
        # Filter out ignored properties
        filtered_props_a = {k: v for k, v in props_a.items() if k not in ignore_properties}
        filtered_props_b = {k: v for k, v in props_b.items() if k not in ignore_properties}
        
        # Check if both dictionaries have the same keys (after filtering)
        if set(filtered_props_a.keys()) != set(filtered_props_b.keys()):
            return False
            
        # Compare each property value
        for key in filtered_props_a.keys():
            prop_a = filtered_props_a[key]
            prop_b = filtered_props_b[key]
            
            # Handle None cases
            if prop_a is None and prop_b is None:
                continue
            if prop_a is None or prop_b is None:
                return False
                
            # Compare property values using their to_json representation
            # This ensures consistent comparison across different property types
            try:
                value_a = prop_a.to_json()["value"] if hasattr(prop_a, 'to_json') else prop_a
                value_b = prop_b.to_json()["value"] if hasattr(prop_b, 'to_json') else prop_b
                
                if value_a != value_b:
                    return False
            except Exception:
                # Fallback to direct comparison if to_json fails
                if prop_a != prop_b:
                    return False
                    
        return True

    @staticmethod
    def equals_ignore_grouping(graph_object_a: 'GraphObject', graph_object_b: 'GraphObject') -> bool:
        """
        Convenience method to compare GraphObjects while ignoring common grouping properties.
        
        Args:
            graph_object_a: First GraphObject to compare
            graph_object_b: Second GraphObject to compare
            
        Returns:
            bool: True if the objects are equal (ignoring grouping properties), False otherwise
        """
        # Common grouping properties that are typically set by the server
        grouping_properties = [
            'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI',      # Entity-level grouping
            'http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI',   # Frame-level grouping
        ]
        
        return KGGraphObjectEqualityUtils.equals(
            graph_object_a, 
            graph_object_b, 
            ignore_properties=grouping_properties
        )
