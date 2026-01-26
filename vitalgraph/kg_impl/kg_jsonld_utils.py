"""
JSON-LD utilities for KG operations.
Provides utilities for converting between JSON-LD and VitalSigns GraphObjects.
"""

import logging
from typing import List, Union, Any
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

logger = logging.getLogger(__name__)


class KGJsonLdUtils:
    """Utility class for JSON-LD operations in KG implementations."""
    
    @staticmethod
    def convert_jsonld_to_graph_objects(jsonld_data: Union[Any, dict]) -> List[GraphObject]:
        """
        Convert JSON-LD data to VitalSigns GraphObject instances.
        
        Args:
            jsonld_data: JSON-LD data (JsonLdObject, JsonLdDocument, or dict)
            
        Returns:
            List[GraphObject]: List of VitalSigns GraphObject instances
        """
        try:
            # Convert to dict for VitalSigns processing
            if hasattr(jsonld_data, 'model_dump'):
                # Pydantic model - use by_alias=True to get proper JSON-LD format
                data_dict = jsonld_data.model_dump(by_alias=True)
            elif isinstance(jsonld_data, dict):
                # Already a dict
                data_dict = jsonld_data
            else:
                logger.error(f"Invalid jsonld_data type: {type(jsonld_data)}")
                return []
            
            # Create VitalSigns instance and convert JSON-LD to objects
            vs = VitalSigns()
            
            # Check if it's a single object or document with @graph
            if '@graph' in data_dict:
                # Document with @graph - use from_jsonld_list
                objects = vs.from_jsonld_list(data_dict)
            else:
                # Single object - use from_jsonld
                obj = vs.from_jsonld(data_dict)
                objects = [obj] if obj else []
            
            objects = objects if objects else []
            
            if not objects:
                logger.warning("No objects created from JSON-LD data")
                return []
            
            # Ensure all objects are GraphObject instances
            graph_objects = []
            for obj in objects:
                if isinstance(obj, GraphObject):
                    graph_objects.append(obj)
                else:
                    logger.warning(f"Skipping non-GraphObject: {type(obj)}")
            
            logger.debug(f"Converted JSON-LD to {len(graph_objects)} GraphObject instances")
            return graph_objects
            
        except Exception as e:
            logger.error(f"Error converting JSON-LD to objects: {e}")
            return []
    
    @staticmethod
    def convert_graph_objects_to_jsonld(graph_objects: List[GraphObject], 
                                       context: str = "https://vitalgraph.ai/contexts/vital-core") -> Union[dict, List[dict]]:
        """
        Convert VitalSigns GraphObject instances to JSON-LD format.
        
        Args:
            graph_objects: List of VitalSigns GraphObject instances
            context: JSON-LD context URL
            
        Returns:
            dict: Single JSON-LD object if len(graph_objects) == 1
            dict: JSON-LD document with @graph array if len(graph_objects) != 1
        """
        try:
            if not graph_objects:
                return {
                    "@context": context,
                    "@graph": []
                }
            
            # Convert each object to JSON-LD
            jsonld_objects = []
            for obj in graph_objects:
                try:
                    obj_dict = obj.to_jsonld()
                    jsonld_objects.append(obj_dict)
                except Exception as e:
                    logger.warning(f"Error converting object to JSON-LD: {e}")
            
            # Handle single object case - return JsonLdObject format, not document
            if len(jsonld_objects) == 1:
                single_obj = jsonld_objects[0]
                # Add context if not already present
                if "@context" not in single_obj:
                    single_obj["@context"] = context
                return single_obj
            
            # Multiple objects - return JsonLdDocument format with @graph
            return {
                "@context": context,
                "@graph": jsonld_objects
            }
            
        except Exception as e:
            logger.error(f"Error converting GraphObjects to JSON-LD: {e}")
            return {
                "@context": context,
                "@graph": []
            }
    
    @staticmethod
    def convert_single_graph_object_to_jsonld(graph_object: GraphObject, 
                                            context: str = "https://vitalgraph.ai/contexts/vital-core") -> dict:
        """
        Convert a single VitalSigns GraphObject to JSON-LD object format (not document).
        
        Args:
            graph_object: Single VitalSigns GraphObject instance
            context: JSON-LD context URL
            
        Returns:
            dict: JSON-LD object (JsonLdObject format)
        """
        try:
            obj_dict = graph_object.to_jsonld()
            
            # Add context if not already present
            if "@context" not in obj_dict:
                obj_dict["@context"] = context
                
            return obj_dict
            
        except Exception as e:
            logger.error(f"Error converting single GraphObject to JSON-LD: {e}")
            return {
                "@context": context,
                "@type": "Error"
            }