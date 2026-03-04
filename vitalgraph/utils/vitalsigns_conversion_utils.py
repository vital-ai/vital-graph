"""
VitalSigns Conversion Utilities

This module contains utility functions for converting between VitalSigns objects,
RDF triples, and pyoxigraph storage operations.
"""

from typing import List, Dict, Any, Tuple
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge


def store_triples_impl(endpoint_instance, space, triples: List[Tuple]) -> bool:
    """
    Store RDF triples/quads in the pyoxigraph store.
    
    Args:
        endpoint_instance: The endpoint instance (for access to logger)
        space: Space object containing the store
        triples: List of tuples representing RDF triples/quads
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        import pyoxigraph as px
        
        # If no triples provided, try to store the object directly using existing method
        if not triples:
            endpoint_instance.logger.warning("No triples provided, but object creation succeeded")
            return True
        
        # Convert triples to quads and insert into space store
        for triple in triples:
            if len(triple) == 4:
                subject, predicate, obj, graph = triple
                
                # Handle different object types
                if isinstance(obj, str):
                    from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                    if validate_rfc3986(obj, rule='URI'):
                        obj_node = px.NamedNode(obj)
                    else:
                        obj_node = px.Literal(obj)
                else:
                    obj_node = px.Literal(str(obj))
                
                quad = px.Quad(
                    px.NamedNode(subject),
                    px.NamedNode(predicate), 
                    obj_node,
                    px.NamedNode(graph)
                )
                space.store.add(quad)
        
        return True
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error storing triples: {e}")
        return False


def convert_triples_to_vitalsigns_objects_impl(endpoint_instance, triples: List[Dict[str, str]]) -> List[Any]:
    """
    Convert triples to VitalSigns objects using list-specific RDF functions.
    
    Args:
        endpoint_instance: The endpoint instance (for access to logger)
        triples: List of dictionaries representing RDF triples
        
    Returns:
        List of VitalSigns objects
    """
    try:
        # Convert triples to N-Triples format string
        rdf_lines = []
        for triple in triples:
            subject = triple['subject'].strip('<>')
            predicate = triple['predicate'].strip('<>')
            obj_original = triple['object']
            obj = triple['object'].strip('<>')
            
            # Format as N-Triple based on object type
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if validate_rfc3986(obj, rule='URI'):
                # URI object - ensure proper angle bracket formatting
                rdf_lines.append(f'<{subject}> <{predicate}> <{obj}> .')
            else:
                # Literal object - add quotes if not already quoted
                if obj.startswith('"') and obj.endswith('"'):
                    # Already quoted literal - use as is
                    rdf_lines.append(f'<{subject}> <{predicate}> {obj} .')
                else:
                    # Unquoted literal - check if it's numeric or needs quotes
                    try:
                        # Try to parse as number - if successful, don't quote
                        float(obj)
                        rdf_lines.append(f'<{subject}> <{predicate}> {obj} .')
                    except ValueError:
                        # Not a number - add quotes and escape
                        escaped_obj = obj.replace('"', '\\"')
                        rdf_lines.append(f'<{subject}> <{predicate}> "{escaped_obj}" .')
        
        rdf_data = '\n'.join(rdf_lines)
        
        # Use VitalSigns list-specific function for multiple objects
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vitalsigns = VitalSigns()
        
        endpoint_instance.logger.debug(f"Converting {len(triples)} triples to VitalSigns objects using from_rdf_list")
        
        # Use from_rdf_list for handling multiple objects
        vitalsigns_objects = vitalsigns.from_rdf_list(rdf_data)
        
        if vitalsigns_objects:
            endpoint_instance.logger.debug(f"Converted {len(triples)} triples to {len(vitalsigns_objects)} VitalSigns objects")
            return vitalsigns_objects
        else:
            endpoint_instance.logger.warning("VitalSigns conversion returned no objects")
            return []
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error converting triples to VitalSigns objects: {e}")
        import traceback
        endpoint_instance.logger.error(f"Traceback: {traceback.format_exc()}")
        return []


