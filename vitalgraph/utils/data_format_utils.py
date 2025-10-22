"""
Data Format Utilities

This module provides utilities for converting between different data formats
used in VitalGraph, including JSON-LD, VitalSigns GraphObjects, and RDF quads.
"""

import logging
from typing import List, Tuple, Optional, Dict, Any, Callable, TypeVar
from pyld import jsonld
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


async def jsonld_to_graphobjects(jsonld_document: Dict[str, Any], vitaltype_validator: Optional[Callable] = None) -> List[G]:
    """
    Convert JSON-LD document to VitalSigns GraphObjects using VitalSigns native functionality with validation.
    
    Args:
        jsonld_document: JSON-LD document containing objects
        vitaltype_validator: Optional function to validate vitaltypes
        
    Returns:
        List of VitalSigns GraphObjects
        
    Raises:
        ImplValidationError: If JSON-LD processing or validation fails
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Log the input document for debugging
        logger.debug(f"🔍 INPUT JSON-LD DOCUMENT TYPE: {type(jsonld_document)}")
        
        # Use VitalSigns native JSON-LD conversion
        vitalsigns = VitalSigns()
        
        # Handle both single object and document with @graph
        if isinstance(jsonld_document, dict):
            if '@graph' in jsonld_document:
                # Document with @graph - use from_jsonld_list
                graph_objects = vitalsigns.from_jsonld_list(jsonld_document)
            else:
                # Single object - use from_jsonld
                single_object = vitalsigns.from_jsonld(jsonld_document)
                graph_objects = [single_object] if single_object else []
        else:
            raise ImplValidationError(f"Invalid JSON-LD document type: {type(jsonld_document)}")
        
        logger.debug(f"VitalSigns converted JSON-LD to {len(graph_objects)} GraphObjects")
        
        # Step 5: Validate that all objects meet criteria if validator provided
        validated_objects = []
        for obj in graph_objects:
            try:
                # Get URI safely - VitalSigns objects may have different URI access patterns
                obj_uri = getattr(obj, 'URI', None) or getattr(obj, 'uri', None) or str(obj)
                
                if not hasattr(obj, 'vitaltype'):
                    raise ImplValidationError(f"Object {obj_uri} missing vitaltype property")
                
                if vitaltype_validator and not vitaltype_validator(obj.vitaltype):
                    raise ImplValidationError(f"Invalid vitaltype '{obj.vitaltype}' for object {obj_uri}")
                
                validated_objects.append(obj)
                
            except AttributeError as e:
                raise ImplValidationError(f"Invalid GraphObject structure: {e}")
        
        logger.debug(f"Successfully converted JSON-LD to {len(validated_objects)} GraphObjects")
        return validated_objects
        
    except ImplValidationError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        raise ImplValidationError(f"Failed to process JSON-LD document: {e}")


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


async def batch_jsonld_to_graphobjects(
    jsonld_document: Dict[str, Any], 
    vitaltype_validator: Optional[Callable] = None
) -> List[G]:
    """
    Convert a JSON-LD document to VitalSigns GraphObjects using VitalSigns native functionality with validation.
    
    Args:
        jsonld_document: Full JSON-LD document with @context and @graph
        vitaltype_validator: Optional function to validate vitaltypes
        
    Returns:
        List of VitalSigns GraphObjects
        
    Raises:
        ImplValidationError: If conversion or validation fails
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Extract objects count for logging
        objects_data = jsonld_document.get("@graph", [])
        objects_count = len(objects_data)
        
        # Use VitalSigns native JSON-LD conversion with full document
        vitalsigns = VitalSigns()
        graph_objects = vitalsigns.from_jsonld_list(jsonld_document)
        
        logger.debug(f"VitalSigns converted {objects_count} JSON-LD objects to {len(graph_objects)} GraphObjects")
        
        # Apply validation if provided
        if vitaltype_validator:
            validated_objects = []
            for obj in graph_objects:
                try:
                    obj_uri = getattr(obj, 'URI', None) or getattr(obj, 'uri', None) or str(obj)
                    
                    if not hasattr(obj, 'vitaltype'):
                        raise ImplValidationError(f"Object {obj_uri} missing vitaltype property")
                    
                    if not vitaltype_validator(obj.vitaltype):
                        raise ImplValidationError(f"Invalid vitaltype '{obj.vitaltype}' for object {obj_uri}")
                    
                    validated_objects.append(obj)
                    
                except AttributeError as e:
                    raise ImplValidationError(f"Invalid GraphObject structure: {e}")
            
            logger.debug(f"Successfully validated {len(validated_objects)} GraphObjects")
            return validated_objects
        
        return graph_objects
        
    except Exception as e:
        objects_count = len(jsonld_document.get("@graph", [])) if isinstance(jsonld_document, dict) else 0
        logger.error(f"Failed to convert {objects_count} objects to GraphObjects: {e}")
        raise ImplValidationError(f"Failed to convert batch objects to GraphObjects: {e}")


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