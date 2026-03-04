"""
Data Format Utilities

This module provides utilities for converting between different data formats
used in VitalGraph, including VitalSigns GraphObjects and RDF quads.
"""

import logging
from typing import List, Tuple, Optional, Dict, Any, Callable, TypeVar
from rdflib import Graph, URIRef, Literal, BNode
import json

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Type variable for GraphObject
G = TypeVar('G', bound=Optional['GraphObject'])


class ImplValidationError(Exception):
    """Base class for implementation validation errors."""
    pass


def _strip_angle_brackets(uri_text: str) -> str:
    """
    Strip angle brackets from URI text if present.
    
    Args:
        uri_text: URI text that may have angle brackets
        
    Returns:
        Clean URI text without angle brackets
    """
    if uri_text.startswith('<') and uri_text.endswith('>'):
        return uri_text[1:-1]
    return uri_text


async def graphobjects_to_quads(graph_objects: List[G], graph_id: str) -> List[Tuple[Any, Any, Any, Any]]:
    """
    Convert VitalSigns GraphObjects to RDF quads using VitalSigns native functionality.
    
    Args:
        graph_objects: List of VitalSigns GraphObjects
        graph_id: Graph URI to use as context
        
    Returns:
        List of tuples (subject, predicate, object, graph) as RDFLib Identifiers
        
    Raises:
        ImplValidationError: If GraphObject conversion fails
    """
    logger = logging.getLogger(__name__)
    
    try:
        from rdflib import URIRef
        
        # Use VitalSigns native to_triples_list method
        if len(graph_objects) == 1:
            # Single object - use to_triples
            triples_list = graph_objects[0].to_triples()
        else:
            # Multiple objects - use to_triples_list  
            triples_list = graph_objects[0].to_triples_list(graph_objects)
        
        # Convert triples to quads by adding graph context
        graph_uri = URIRef(_strip_angle_brackets(graph_id))
        
        quads = []
        
        for s, p, o in triples_list:
            quads.append((s, p, o, graph_uri))
        
        logger.debug(f"Successfully converted {len(graph_objects)} GraphObjects to {len(quads)} quads")
        return quads
        
    except Exception as e:
        logger.error(f"Failed to convert {len(graph_objects)} GraphObjects to quads: {e}")
        raise ImplValidationError(f"Failed to convert GraphObjects to quads: {e}")


async def batch_graphobjects_to_quads(graph_objects: List[G], graph_id: str) -> List[Tuple[Any, Any, Any, Any]]:
    """
    Convert a list of VitalSigns GraphObjects to RDF quads using VitalSigns native functionality.
    
    Args:
        graph_objects: List of VitalSigns GraphObjects
        graph_id: Graph identifier for the quads
        
    Returns:
        List of RDF quads (tuples)
        
    Raises:
        ImplValidationError: If conversion fails
    """
    logger = logging.getLogger(__name__)
    
    try:
        from rdflib import URIRef, Graph
        
        # Use VitalSigns native to_triples_list method
        if len(graph_objects) == 1:
            # Single object - use to_triples
            triples_list = graph_objects[0].to_triples()
        else:
            # Multiple objects - use to_triples_list  
            triples_list = graph_objects[0].to_triples_list(graph_objects)
        
        # Convert triples to quads by adding graph context
        graph_uri = URIRef(_strip_angle_brackets(graph_id))
        
        quads = []
        
        for s, p, o in triples_list:
            quads.append((s, p, o, graph_uri))
        
        logger.debug(f"Successfully converted {len(triples_list)} triples to {len(quads)} quads with graph: {graph_id}")
        return quads
        
    except Exception as e:
        logger.error(f"Failed to convert {len(graph_objects)} GraphObjects to quads: {e}")
        raise ImplValidationError(f"Failed to convert batch GraphObjects to quads: {e}")