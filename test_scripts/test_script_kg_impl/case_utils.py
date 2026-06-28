#!/usr/bin/env python3
"""
Test Case Utilities

Shared utility functions for test case implementations.
Provides common functionality for GraphObject handling and quad conversion.
"""

import logging
from typing import List, Any, Dict, Union, Optional

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType
from vitalgraph.model.quad_model import Quad
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list, quad_list_to_graphobjects

logger = logging.getLogger(__name__)


def filter_kgtypes(objects: List[GraphObject]) -> List[KGType]:
    """
    Filter a list of GraphObjects to return only KGType instances.
    
    Args:
        objects: List of GraphObjects
        
    Returns:
        List of KGType objects
    """
    return [obj for obj in objects if isinstance(obj, KGType)]


def quads_to_kgtypes(quads: List[Quad]) -> List[KGType]:
    """
    Convert a list of quads to KGType objects.
    
    Args:
        quads: List of Quad objects from response
        
    Returns:
        List of KGType objects (empty list if conversion fails or no KGTypes found)
    """
    try:
        objects = quad_list_to_graphobjects(quads)
        return filter_kgtypes(objects)
    except Exception as e:
        logger.error(f"Error converting quads to KGTypes: {e}")
        return []


def validate_graphobject_roundtrip(original_kgtypes: List[KGType], graph_id: str = None) -> bool:
    """
    Validate that KGType objects can be round-trip converted through quads.
    
    Args:
        original_kgtypes: Original list of KGType objects
        graph_id: Optional graph ID for quad conversion
        
    Returns:
        True if round-trip conversion is successful, False otherwise
    """
    try:
        quads = graphobjects_to_quad_list(original_kgtypes, graph_id)
        reconstructed = quads_to_kgtypes(quads)
        
        if len(original_kgtypes) != len(reconstructed):
            logger.error(f"Round-trip count mismatch: original={len(original_kgtypes)}, reconstructed={len(reconstructed)}")
            return False
        
        for orig, recon in zip(original_kgtypes, reconstructed):
            if (str(orig.URI) != str(recon.URI) or 
                orig.get_class_uri() != recon.get_class_uri()):
                logger.error(f"Round-trip data mismatch for {orig.URI}")
                return False
        
        logger.debug(f"Round-trip validation successful for {len(original_kgtypes)} KGTypes")
        return True
        
    except Exception as e:
        logger.error(f"Round-trip validation failed: {e}")
        return False

