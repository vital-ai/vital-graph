"""
Utility functions for KGFrames client tests.

Provides helper functions for converting VitalSigns objects to appropriate JSON-LD formats.
"""

from typing import List, Union
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument


def convert_to_jsonld_request(objects: Union[GraphObject, List[GraphObject]]) -> Union[JsonLdObject, JsonLdDocument]:
    """
    Convert VitalSigns GraphObject(s) to appropriate JSON-LD request format.
    
    - Single object -> JsonLdObject (uses to_jsonld())
    - Multiple objects -> JsonLdDocument (uses to_jsonld_list())
    - Empty list -> JsonLdDocument with empty graph
    
    Args:
        objects: Single GraphObject or list of GraphObjects
        
    Returns:
        JsonLdObject for single object, JsonLdDocument for multiple/zero objects
    """
    # Handle single object (not in a list)
    if isinstance(objects, GraphObject):
        jsonld_dict = objects.to_jsonld()
        return JsonLdObject(**jsonld_dict)
    
    # Handle list of objects
    if isinstance(objects, list):
        if len(objects) == 0:
            # Empty list -> empty document
            return JsonLdDocument(graph=[])
        elif len(objects) == 1:
            # Single object in list -> use JsonLdObject
            jsonld_dict = objects[0].to_jsonld()
            return JsonLdObject(**jsonld_dict)
        else:
            # Multiple objects -> use JsonLdDocument
            jsonld_doc = GraphObject.to_jsonld_list(objects)
            return JsonLdDocument(graph=jsonld_doc['@graph'])
    
    raise ValueError(f"Invalid objects type: {type(objects)}")
