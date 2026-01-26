"""
VitalSigns Helper Utilities for VitalGraph Mock Endpoints

This module provides common VitalSigns operations including object creation,
JSON-LD conversion, and property handling utilities.
"""

import logging
from typing import Dict, Any, List, Optional, Union
from vitalgraph.model.jsonld_model import JsonLdDocument


def create_vitalsigns_objects_from_jsonld(jsonld_document: Dict[str, Any], 
                                        logger: Optional[logging.Logger] = None) -> List[Any]:
    """
    Create VitalSigns objects from JSON-LD document with error handling.
    
    Args:
        jsonld_document: JSON-LD document dictionary
        logger: Optional logger for error reporting
        
    Returns:
        List[Any]: List of VitalSigns objects
    """
    try:
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vitalsigns = VitalSigns()
        
        # Remove null graph fields that cause errors
        if "graph" in jsonld_document and jsonld_document["graph"] is None:
            jsonld_document = {k: v for k, v in jsonld_document.items() if k != "graph"}
        if "@graph" in jsonld_document and jsonld_document["@graph"] is None:
            jsonld_document = {k: v for k, v in jsonld_document.items() if k != "@graph"}
        
        # Fix JSON-LD field names - convert ALL 'id' to '@id' and 'type' to '@type'
        def fix_jsonld_fields(obj):
            """Recursively fix JSON-LD field names throughout the structure"""
            if isinstance(obj, dict):
                fixed_obj = {}
                
                for key, value in obj.items():
                    # Convert field names - replace 'id' with '@id' and 'type' with '@type'
                    if key == 'id':
                        new_key = '@id'
                    elif key == 'type':
                        new_key = '@type'
                    else:
                        new_key = key
                    
                    # Recursively process values
                    if isinstance(value, (dict, list)):
                        fixed_obj[new_key] = fix_jsonld_fields(value)
                    else:
                        fixed_obj[new_key] = value
                        
                return fixed_obj
            elif isinstance(obj, list):
                return [fix_jsonld_fields(item) for item in obj]
            else:
                return obj
        
        # Apply the fix to the entire document
        jsonld_document = fix_jsonld_fields(jsonld_document)
        
        # Fix invalid @context entries that cause "keywords cannot be overridden" error
        if isinstance(jsonld_document, dict) and "@context" in jsonld_document:
            context = jsonld_document["@context"]
            if isinstance(context, dict):
                # Remove invalid keyword redefinitions
                if "@type" in context:
                    del context["@type"]
                if "@id" in context:
                    del context["@id"]
        
        # Log successful conversion
        if logger:
            logger.debug(f"Applied JSON-LD field fixes to document with {len(jsonld_document.get('@graph', []))} items")
        # Handle both single objects and graph arrays
        if "@graph" in jsonld_document and isinstance(jsonld_document["@graph"], list):
            if logger:
                logger.info(f"Calling VitalSigns.from_jsonld_list() with {len(jsonld_document['@graph'])} items")
            objects = vitalsigns.from_jsonld_list(jsonld_document)
        else:
            if logger:
                logger.info(f"Calling VitalSigns.from_jsonld() with single object")
            objects = [vitalsigns.from_jsonld(jsonld_document)]
        
        # Log what VitalSigns returned
        if logger:
            logger.debug(f"VitalSigns returned {len(objects) if objects else 0} objects")
            if objects:
                # Count object types
                type_counts = {}
                for obj in objects:
                    if obj is not None:
                        obj_type = obj.__class__.__name__
                        type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
                logger.debug(f"Object type distribution: {type_counts}")
        
        # Ensure we return a list
        if not isinstance(objects, list):
            objects = [objects] if objects else []
        
        # Filter out None objects
        valid_objects = [obj for obj in objects if obj is not None]
        
        if logger:
            logger.info(f"Filtered to {len(valid_objects)} valid VitalSigns objects")
            logger.info(f"Valid object types: {[type(obj).__name__ for obj in valid_objects[:5]]}")
        
        return valid_objects
        
    except Exception as e:
        if logger:
            logger.error(f"Failed to create VitalSigns objects from JSON-LD: {e}")
        return []


def convert_triples_to_vitalsigns_objects(triples: List[Dict[str, str]], 
                                        logger: Optional[logging.Logger] = None) -> List[Any]:
    """
    Convert RDF triples to VitalSigns objects using N-Triples format.
    
    Args:
        triples: List of RDF triple dictionaries with 'subject', 'predicate', 'object' keys
        logger: Optional logger for error reporting
        
    Returns:
        List[Any]: List of VitalSigns objects
    """
    try:
        if not triples:
            return []
        
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
        
        if logger:
            logger.debug(f"Converting {len(triples)} triples to VitalSigns objects")
            logger.debug(f"RDF data:\n{rdf_data}")
        
        # Log each triple to see what's causing the warnings
        if logger:
            logger.info(f"=== DEBUGGING VITALSIGNS CONVERSION ===")
            logger.info(f"Processing {len(triples)} triples:")
            for i, triple in enumerate(triples):
                logger.info(f"  Triple {i}: {triple}")
            logger.info(f"Generated RDF N-Triples data:")
            for i, line in enumerate(rdf_data.split('\n')):
                logger.info(f"  RDF Line {i}: {line}")
        
        # Use VitalSigns to convert RDF to objects
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vitalsigns = VitalSigns()
        
        if logger:
            logger.info(f"Calling VitalSigns.from_rdf_list() with {len(rdf_data)} characters of RDF data")
        
        vitalsigns_objects = vitalsigns.from_rdf_list(rdf_data)
        
        if logger:
            logger.info(f"VitalSigns.from_rdf_list() returned {len(vitalsigns_objects) if vitalsigns_objects else 0} objects")
        
        if vitalsigns_objects:
            if logger:
                logger.debug(f"Successfully created {len(vitalsigns_objects)} VitalSigns objects")
            return vitalsigns_objects
        else:
            if logger:
                logger.warning("VitalSigns conversion returned no objects")
            return []
            
    except Exception as e:
        if logger:
            logger.error(f"Error converting triples to VitalSigns objects: {e}")
        return []


def objects_to_jsonld_document(objects: List[Any], logger: Optional[logging.Logger] = None) -> JsonLdDocument:
    """
    Convert VitalSigns objects to JsonLdDocument with proper single/multiple object handling.
    
    Args:
        objects: List of VitalSigns objects
        logger: Optional logger for error reporting
        
    Returns:
        JsonLdDocument: JSON-LD document containing the objects
    """
    try:
        if not objects:
            # Return empty document
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
        
        # Convert objects to JSON-LD
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        jsonld_data = GraphObject.to_jsonld_list(objects)
        
        if logger:
            logger.debug(f"Converted {len(objects)} objects to JSON-LD")
        
        # Ensure single objects are wrapped in graph array for consistency
        if 'graph' not in jsonld_data and 'id' in jsonld_data:
            # Single object returned directly - wrap it in graph array
            context = jsonld_data.get('@context', {})
            object_data = {k: v for k, v in jsonld_data.items() if k != '@context'}
            jsonld_data = {
                '@context': context,
                'graph': [object_data]
            }
            if logger:
                logger.debug("Wrapped single object in graph array")
        
        return JsonLdDocument(**jsonld_data)
        
    except Exception as e:
        if logger:
            logger.error(f"Error converting objects to JSON-LD document: {e}")
        # Return empty document on error
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return JsonLdDocument(**empty_jsonld)


def extract_object_uris(objects: List[Any]) -> List[str]:
    """
    Extract URIs from a list of VitalSigns objects.
    
    Args:
        objects: List of VitalSigns objects
        
    Returns:
        List[str]: List of URIs extracted from objects
    """
    uris = []
    
    for obj in objects:
        if hasattr(obj, 'URI'):
            uri_value = str(obj.URI)
            if uri_value and uri_value != 'None':
                uris.append(uri_value)
    
    return uris


def filter_objects_by_type(objects: List[Any], object_type: str) -> List[Any]:
    """
    Filter VitalSigns objects by their vitaltype.
    
    Args:
        objects: List of VitalSigns objects
        object_type: Type to filter by (e.g., "KGEntity", "KGFrame", "KGSlot")
        
    Returns:
        List[Any]: Filtered list of objects
    """
    filtered_objects = []
    
    for obj in objects:
        if hasattr(obj, 'vitaltype') and object_type in str(obj.vitaltype):
            filtered_objects.append(obj)
    
    return filtered_objects


def get_primary_object(objects: List[Any], object_type: str) -> Optional[Any]:
    """
    Get the primary object of a specific type from a list of objects.
    
    Args:
        objects: List of VitalSigns objects
        object_type: Type to look for (e.g., "KGEntity", "KGFrame")
        
    Returns:
        Optional[Any]: The primary object if found and unique, None otherwise
    """
    filtered_objects = filter_objects_by_type(objects, object_type)
    
    if len(filtered_objects) == 1:
        return filtered_objects[0]
    else:
        return None


def cast_property_value(obj: Any, property_name: str, target_type: type = str) -> Any:
    """
    Safely cast a VitalSigns property value to the target type.
    
    Args:
        obj: VitalSigns object
        property_name: Name of the property to cast
        target_type: Target type to cast to (default: str)
        
    Returns:
        Any: Cast property value or None if property doesn't exist
    """
    try:
        if hasattr(obj, property_name):
            property_value = getattr(obj, property_name)
            if property_value is not None:
                return target_type(property_value)
        return None
    except (ValueError, TypeError):
        return None


def safe_get_property(obj: Any, property_name: str, default_value: Any = None) -> Any:
    """
    Safely get a property value from a VitalSigns object.
    
    Args:
        obj: VitalSigns object
        property_name: Name of the property to get
        default_value: Default value if property doesn't exist or is None
        
    Returns:
        Any: Property value or default value
    """
    try:
        if hasattr(obj, property_name):
            value = getattr(obj, property_name)
            return value if value is not None else default_value
        return default_value
    except Exception:
        return default_value


def validate_object_structure(objects: List[Any], required_types: List[str],
                             logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """
    Validate that objects contain the required types and structure.
    
    Args:
        objects: List of VitalSigns objects to validate
        required_types: List of required object types
        logger: Optional logger for error reporting
        
    Returns:
        Dict[str, Any]: Validation result with success status and details
    """
    try:
        result = {
            "success": True,
            "found_types": {},
            "missing_types": [],
            "errors": []
        }
        
        # Count objects by type
        for obj in objects:
            if hasattr(obj, 'vitaltype'):
                obj_type = str(obj.vitaltype)
                for required_type in required_types:
                    if required_type in obj_type:
                        if required_type not in result["found_types"]:
                            result["found_types"][required_type] = 0
                        result["found_types"][required_type] += 1
        
        # Check for missing required types
        for required_type in required_types:
            if required_type not in result["found_types"]:
                result["missing_types"].append(required_type)
                result["success"] = False
        
        if logger:
            logger.debug(f"Object structure validation: {result}")
        
        return result
        
    except Exception as e:
        if logger:
            logger.error(f"Error validating object structure: {e}")
        return {
            "success": False,
            "found_types": {},
            "missing_types": required_types,
            "errors": [str(e)]
        }


def create_empty_jsonld_document() -> JsonLdDocument:
    """
    Create an empty JSON-LD document.
    
    Returns:
        JsonLdDocument: Empty JSON-LD document
    """
    from vital_ai_vitalsigns.model.GraphObject import GraphObject
    empty_jsonld = GraphObject.to_jsonld_list([])
    return JsonLdDocument(**empty_jsonld)


def strip_grouping_uris_from_document(document: JsonLdDocument) -> JsonLdDocument:
    """
    Strip any existing grouping URIs from client document.
    
    This implements server-side authority over grouping URI assignment by removing
    any client-provided hasKGGraphURI and hasFrameGraphURI values.
    
    Args:
        document: JsonLdDocument to strip grouping URIs from
        
    Returns:
        JsonLdDocument: Document with grouping URIs removed
        
    Note:
        This is currently a placeholder implementation that returns the document as-is
        since this is a mock implementation. In a real implementation, this would
        traverse the JSON-LD structure and remove grouping URI properties.
    """
    # TODO: Implement actual grouping URI stripping logic
    # For now, return the document as-is since this is a mock implementation
    return document


def generate_uuid() -> str:
    """
    Generate a UUID for new objects.
    
    Returns:
        str: UUID string for use in object URIs
    """
    import uuid
    return str(uuid.uuid4())


def convert_triples_to_vitalsigns_objects(triples: List[Dict[str, str]], logger) -> List[Any]:
    """Convert triples to VitalSigns objects using list-specific RDF functions.
    
    Args:
        triples: List of triple dicts with 'subject', 'predicate', 'object' keys
        logger: Logger instance for debugging
        
    Returns:
        List of VitalSigns objects converted from the triples
    """
    try:
        # Convert triples to N-Triples format string
        rdf_lines = []
        for triple in triples:
            subject = triple['subject'].strip('<>')
            predicate = triple['predicate'].strip('<>')
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
        logger.info(f"RDF data being passed to VitalSigns:\n{rdf_data}")
        
        # Use VitalSigns list-specific function for multiple objects
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vitalsigns = VitalSigns()
        
        logger.debug(f"Converting {len(triples)} triples to VitalSigns objects using from_rdf_list")
        
        # Use from_rdf_list for handling multiple objects
        vitalsigns_objects = vitalsigns.from_rdf_list(rdf_data)
        
        if vitalsigns_objects:
            logger.debug(f"Converted {len(triples)} triples to {len(vitalsigns_objects)} VitalSigns objects")
            return vitalsigns_objects
        else:
            logger.warning("VitalSigns conversion returned no objects")
            return []
            
    except Exception as e:
        logger.error(f"Error converting triples to VitalSigns objects: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return []


def convert_triples_to_jsonld(triples: List[Dict[str, str]], logger) -> Dict[str, Any]:
    """Convert list of triples to JSON-LD document.
    
    Args:
        triples: List of triple dicts with 'subject', 'predicate', 'object' keys
        logger: Logger instance for debugging
        
    Returns:
        Dict containing JSON-LD document with @context and @graph
    """
    try:
        # First try to convert via VitalSigns objects for validation
        vitalsigns_objects = convert_triples_to_vitalsigns_objects(triples, logger)
        
        if vitalsigns_objects:
            # Convert VitalSigns objects to JSON-LD using to_json and JSON parsing
            jsonld_objects = []
            for obj in vitalsigns_objects:
                try:
                    # Debug: Check the VitalSigns object type
                    logger.debug(f"Converting VitalSigns object: {type(obj).__name__} with URI: {obj.URI}")
                    
                    # VitalSigns objects have to_jsonld() method for JSON-LD conversion
                    obj_jsonld_dict = obj.to_jsonld()
                    if obj_jsonld_dict:
                        # Fix JSON-LD field names - convert 'id' to '@id' and 'type' to '@type'
                        def fix_jsonld_fields(obj):
                            if isinstance(obj, dict):
                                fixed_obj = {}
                                for key, value in obj.items():
                                    if key == 'id':
                                        new_key = '@id'
                                    elif key == 'type':
                                        new_key = '@type'
                                    else:
                                        new_key = key
                                    
                                    if isinstance(value, (dict, list)):
                                        fixed_obj[new_key] = fix_jsonld_fields(value)
                                    else:
                                        fixed_obj[new_key] = value
                                return fixed_obj
                            elif isinstance(obj, list):
                                return [fix_jsonld_fields(item) for item in obj]
                            else:
                                return obj
                        
                        # Apply the fix
                        obj_jsonld_dict = fix_jsonld_fields(obj_jsonld_dict)
                        
                        # Debug: Check if @type is present in the JSON-LD
                        if '@type' in obj_jsonld_dict:
                            logger.debug(f"Object {obj.URI} has @type: {obj_jsonld_dict['@type']}")
                        else:
                            logger.warning(f"Object {obj.URI} missing @type in JSON-LD")
                            
                        jsonld_objects.append(obj_jsonld_dict)
                except Exception as e:
                    logger.warning(f"Failed to convert VitalSigns object {obj.URI} to JSON-LD: {e}")
                    continue
            
            return {
                "@context": {},
                "@graph": jsonld_objects
            }
        else:
            # Fallback to simple JSON-LD conversion
            return simple_triples_to_jsonld(triples)
            
    except Exception as e:
        logger.error(f"Error converting triples to JSON-LD: {e}")
        # Fallback to simple conversion
        return simple_triples_to_jsonld(triples)


def simple_triples_to_jsonld(triples: List[Dict[str, str]]) -> Dict[str, Any]:
    """Fallback simple conversion of triples to JSON-LD.
    
    Args:
        triples: List of triple dicts with 'subject', 'predicate', 'object' keys
        
    Returns:
        Dict containing simple JSON-LD document with @context and @graph
    """
    # Group triples by subject
    subjects = {}
    for triple in triples:
        subject = triple['subject']
        predicate = triple['predicate']
        obj = triple['object']
        
        if subject not in subjects:
            subjects[subject] = {"@id": subject}
        
        # Handle different predicate types
        if predicate == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type":
            subjects[subject]["@type"] = obj
        else:
            # Simple property assignment (could be enhanced for complex objects)
            subjects[subject][predicate] = obj
    
    # Convert to JSON-LD format
    return {
        "@context": {},
        "@graph": list(subjects.values())
    }
