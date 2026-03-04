"""
Utility functions for KGFrames client tests.

Provides helper functions for preparing VitalSigns objects for client endpoint calls.
"""

from typing import List, Union
from vital_ai_vitalsigns.model.GraphObject import GraphObject


def normalize_to_object_list(objects: Union[GraphObject, List[GraphObject]]) -> List[GraphObject]:
    """
    Normalize GraphObject input to a list of GraphObjects.
    
    The client endpoints now accept List[GraphObject] directly and handle
    serialization to quads internally. This helper simply ensures the input
    is always a list.
    
    Args:
        objects: Single GraphObject or list of GraphObjects
        
    Returns:
        List of GraphObject instances
    """
    if isinstance(objects, GraphObject):
        return [objects]
    if isinstance(objects, list):
        return objects
    raise ValueError(f"Invalid objects type: {type(objects)}")


# Backward-compatible alias (deprecated — callers should pass objects directly)
def convert_to_object_list_request(objects: Union[GraphObject, List[GraphObject]]) -> List[GraphObject]:
    """Deprecated: Client endpoints now accept List[GraphObject] directly.
    This function simply normalizes input to a list for backward compatibility."""
    return normalize_to_object_list(objects)
