"""
Utility functions for KGFrames tests.

Provides helper functions for converting VitalSigns objects to quads.
"""

from typing import List, Union
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list
from vitalgraph.model.quad_model import Quad


def convert_to_quads(objects: Union[GraphObject, List[GraphObject]], graph_id: str) -> List[Quad]:
    """
    Convert VitalSigns GraphObject(s) to a list of Quads.
    
    Args:
        objects: Single GraphObject or list of GraphObjects
        graph_id: Graph ID for the quad graph context
        
    Returns:
        List of Quad objects
    """
    if isinstance(objects, GraphObject):
        return graphobjects_to_quad_list([objects], graph_id)
    
    if isinstance(objects, list):
        if len(objects) == 0:
            return []
        return graphobjects_to_quad_list(objects, graph_id)
    
    raise ValueError(f"Invalid objects type: {type(objects)}")
