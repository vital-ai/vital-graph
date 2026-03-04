"""Mock Base Endpoint

Base class for all mock endpoint implementations.
Provides common functionality and structure for mock endpoints with VitalSigns native support.
"""

from typing import Dict, Any, Optional, List, Union
import logging

# VitalSigns imports for native functionality
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot

logger = logging.getLogger(__name__)


class MockBaseEndpoint:
    """
    Base class for all mock endpoints.
    
    Provides common functionality including client reference,
    logging, and stub response generation.
    """
    
    def __init__(self, client, space_manager=None, *, config=None):
        """
        Initialize the mock endpoint.
        
        Args:
            client: Reference to the mock VitalGraph client
            space_manager: Reference to the mock space manager
            config: Optional config object for endpoint configuration
        """
        self.client = client
        self.space_manager = space_manager
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Initialize VitalSigns for native operations
        self.vitalsigns = VitalSigns()
    
    def _create_stub_response(self, operation: str, **kwargs) -> Dict[str, Any]:
        """
        Create a stub response for testing.
        
        Args:
            operation: Name of the operation
            **kwargs: Additional response data
            
        Returns:
            Dictionary containing stub response
        """
        response = {
            "status": "success",
            "operation": operation,
            "message": f"Mock {operation} operation completed",
            "mock": True,
            **kwargs
        }
        
        self.logger.debug(f"Generated stub response for {operation}: {response}")
        return response
    
    def _create_error_response(self, operation: str, error_message: str, **kwargs) -> Dict[str, Any]:
        """
        Create an error response for testing.
        
        Args:
            operation: Name of the operation
            error_message: Error message
            **kwargs: Additional error data
            
        Returns:
            Dictionary containing error response
        """
        response = {
            "status": "error",
            "operation": operation,
            "error": error_message,
            "mock": True,
            **kwargs
        }
        
        self.logger.debug(f"Generated error response for {operation}: {response}")
        return response
    
    def _log_method_call(self, method_name: str, *args, **kwargs):
        """
        Log method call for debugging.
        
        Args:
            method_name: Name of the method being called
            *args: Method arguments
            **kwargs: Method keyword arguments
        """
        self.logger.info(f"Mock {method_name} called with args={args}, kwargs={kwargs}")
    
    # ========================================
    # VitalSigns Native Helper Functions
    # ========================================
    
    def _convert_sparql_to_vitalsigns_object(self, vitaltype_uri: str, uri: str, properties: Dict[str, Any]) -> GraphObject:
        """
        Convert SPARQL query results to VitalSigns object using native functionality.
        
        Args:
            vitaltype_uri: The vitaltype URI for the object
            uri: The object URI
            properties: Dictionary of properties from SPARQL results
            
        Returns:
            VitalSigns GraphObject instance
        """
        try:
            # Clean URI - remove angle brackets if present
            clean_uri = str(uri).strip('<>').strip('<>')
            
            # Build RDF string for VitalSigns from_rdf method instead
            rdf_lines = []
            
            # Add core triples in N-Triples format
            rdf_lines.append(f'<{clean_uri}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{vitaltype_uri}> .')
            rdf_lines.append(f'<{clean_uri}> <http://vital.ai/ontology/vital-core#vitaltype> <{vitaltype_uri}> .')
            rdf_lines.append(f'<{clean_uri}> <http://vital.ai/ontology/vital-core#URIProp> <{clean_uri}> .')
            
            # Add all properties from SPARQL results as N-Triples
            for prop_uri, value in properties.items():
                # Clean property URI and value
                clean_prop_uri = str(prop_uri).strip('<>').strip('<>')
                clean_value = str(value).strip('"').strip('<>') if isinstance(value, str) else value
                
                # Skip system properties that are already handled
                if clean_prop_uri in [
                    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                    "http://vital.ai/ontology/vital-core#vitaltype", 
                    "http://vital.ai/ontology/vital-core#URIProp"
                ]:
                    continue
                
                # Format as N-Triple based on value type
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                if validate_rfc3986(clean_value, rule='URI'):
                    # URI value
                    rdf_lines.append(f'<{clean_uri}> <{clean_prop_uri}> <{clean_value}> .')
                else:
                    # Literal value - try to determine type and format properly
                    try:
                        # Try float first (includes int)
                        float_val = float(clean_value)
                        if '.' in str(clean_value):
                            rdf_lines.append(f'<{clean_uri}> <{clean_prop_uri}> "{float_val}"^^<http://www.w3.org/2001/XMLSchema#float> .')
                        else:
                            rdf_lines.append(f'<{clean_uri}> <{clean_prop_uri}> "{int(float_val)}"^^<http://www.w3.org/2001/XMLSchema#int> .')
                    except (ValueError, TypeError):
                        # Check for datetime
                        if 'T' in clean_value and (':' in clean_value):
                            rdf_lines.append(f'<{clean_uri}> <{clean_prop_uri}> "{clean_value}"^^<http://www.w3.org/2001/XMLSchema#dateTime> .')
                        else:
                            # Default to string
                            rdf_lines.append(f'<{clean_uri}> <{clean_prop_uri}> "{clean_value}"^^<http://www.w3.org/2001/XMLSchema#string> .')
            
            # Join into RDF string
            rdf_string = '\n'.join(rdf_lines)
            
            # Use VitalSigns to create object from RDF string - no hardcoded classes
            obj = self.vitalsigns.from_rdf_list(rdf_string)
            
            # from_triples_list returns a list, get the first object
            if obj and len(obj) > 0:
                return obj[0]
            else:
                self.logger.warning(f"No objects created from triples for URI: {clean_uri}")
                return None
            
        except Exception as e:
            self.logger.error(f"Error converting SPARQL to VitalSigns object: {e}")
            self.logger.error(f"  URI: {uri}")
            self.logger.error(f"  VitalType: {vitaltype_uri}")
            self.logger.error(f"  Properties: {properties}")
            return None
    
    def _objects_to_quad_response(self, objects: List[GraphObject]) -> Dict[str, Any]:
        """
        Convert VitalSigns objects to a quad response dict.
        
        Args:
            objects: List of VitalSigns GraphObject instances
            
        Returns:
            Dict with 'results' key containing quad dicts
        """
        try:
            from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list
            quads = graphobjects_to_quad_list(objects)
            return {"results": [q.model_dump() for q in quads]}
            
        except Exception as e:
            self.logger.error(f"Error converting objects to quad response: {e}")
            return {"results": []}
    
    def _instantiate_vitalsigns_object(self, vitaltype_uri: str, uri: str, **properties) -> GraphObject:
        """
        Instantiate a VitalSigns object with proper vitaltype and properties.
        
        Args:
            vitaltype_uri: The vitaltype URI for the object
            uri: The object URI
            **properties: Object properties
            
        Returns:
            VitalSigns GraphObject instance
        """
        try:
            # Determine the appropriate class based on vitaltype
            if "KGEntity" in vitaltype_uri:
                obj = KGEntity()
            elif "KGType" in vitaltype_uri:
                obj = KGType()
            elif "KGFrame" in vitaltype_uri and "Slot" not in vitaltype_uri:
                obj = KGFrame()
            elif "KGFrameSlot" in vitaltype_uri:
                obj = KGFrameSlot()
            else:
                # Generic GraphObject
                obj = GraphObject()
            
            # Set URI
            obj.URI = uri
            
            # Set properties
            for key, value in properties.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)
            
            return obj
            
        except Exception as e:
            self.logger.error(f"Error instantiating VitalSigns object: {e}")
            return None
    
    def _create_objects_from_triples(self, triples: List[tuple]) -> List[GraphObject]:
        """
        Create VitalSigns objects from RDF triples using VitalSigns helper functions.
        
        Args:
            triples: List of RDF triples
            
        Returns:
            List of VitalSigns GraphObject instances
        """
        try:
            # Use VitalSigns native conversion
            return self.vitalsigns.from_triples_list(triples)
            
        except Exception as e:
            self.logger.error(f"Error creating objects from triples: {e}")
            return []
    
    def _rdf_to_vitalsigns_objects(self, rdf_data: str) -> List[GraphObject]:
        """
        Convert RDF data to VitalSigns objects using VitalSigns helper functions.
        
        Args:
            rdf_data: RDF data string
            
        Returns:
            List of VitalSigns GraphObject instances
        """
        try:
            # Use VitalSigns native conversion (no format parameter)
            objects = self.vitalsigns.from_rdf(rdf_data)
            
            # Ensure we return a list
            if not isinstance(objects, list):
                objects = [objects] if objects else []
            
            return objects
            
        except Exception as e:
            self.logger.error(f"Error creating objects from RDF: {e}")
            return []
    
    def _quads_to_rdf_string(self, quads: List[Dict[str, str]]) -> str:
        """
        Convert quads to RDF N-Triples string format that VitalSigns can parse.
        
        Args:
            quads: List of quad dictionaries with subject, predicate, object, graph
            
        Returns:
            RDF string in N-Triples format
        """
        try:
            rdf_lines = []
            
            for quad in quads:
                subject = quad["subject"]
                predicate = quad["predicate"] 
                obj = quad["object"]
                
                # Format as N-Triple: <subject> <predicate> <object> .
                # Clean URIs by removing angle brackets if already present
                clean_subject = subject.strip('<>')
                clean_predicate = predicate.strip('<>')
                
                # Determine if object is a literal or URI
                if obj.startswith('"'):
                    # It's a literal, keep as is
                    object_part = obj
                else:
                    from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                    if validate_rfc3986(obj, rule='URI'):
                        # It's a URI, wrap in angle brackets
                        clean_object = obj.strip('<>')
                        object_part = f'<{clean_object}>'
                    else:
                        # Assume it's a literal without quotes
                        object_part = f'"{obj}"'
                
                # N-Triples format (ignore graph for now, just convert to triples)
                rdf_line = f'<{clean_subject}> <{clean_predicate}> {object_part} .'
                rdf_lines.append(rdf_line)
            
            return '\n'.join(rdf_lines)
            
        except Exception as e:
            self.logger.error(f"Error converting quads to RDF string: {e}")
            return ""
    
    def _convert_objects_to_triples(self, objects: List[GraphObject]) -> List[tuple]:
        """
        Convert VitalSigns objects to RDF triples using VitalSigns helper functions.
        
        Args:
            objects: List of VitalSigns GraphObject instances
            
        Returns:
            List of RDF triples
        """
        try:
            # Convert each object to triples and combine
            all_triples = []
            for obj in objects:
                triples = obj.to_triples()
                all_triples.extend(triples)
            return all_triples
            
        except Exception as e:
            self.logger.error(f"Error converting objects to triples: {e}")
            return []
    
    def _triples_to_vitalsigns_objects(self, triples: List[tuple]) -> List[GraphObject]:
        """
        Convert RDF triples back to VitalSigns objects using VitalSigns helper functions.
        
        Args:
            triples: List of RDF triples (subject, predicate, object)
            
        Returns:
            List of VitalSigns GraphObject instances
        """
        try:
            # Convert triples to RDF string format for VitalSigns
            if triples and isinstance(triples[0], str):
                # Already in RDF string format
                rdf_data = '\n'.join(triples)
            else:
                # Convert tuple format to RDF N-Triples strings
                rdf_lines = []
                for triple in triples:
                    if len(triple) == 3:
                        subj, pred, obj = triple
                        # Clean URIs - remove angle brackets if present
                        clean_subj = subj.strip('<>')
                        clean_pred = pred.strip('<>')
                        clean_obj = obj.strip('<>')
                        
                        # Format as N-Triples
                        triple_str = f"<{clean_subj}> <{clean_pred}> "
                        from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                        if validate_rfc3986(clean_obj, rule='URI'):
                            triple_str += f"<{clean_obj}> ."
                        else:
                            # Remove any existing quotes before adding new ones
                            clean_literal = clean_obj.strip('"')
                            triple_str += f'"{clean_literal}" .'
                        rdf_lines.append(triple_str)
                rdf_data = '\n'.join(rdf_lines)
            
            # Debug specific properties we're tracking
            if 'hasKGGraphAssertionDateTime' in rdf_data:
                self.logger.info(f"*** RDF data contains hasKGGraphAssertionDateTime")
                for line in rdf_data.split('\n'):
                    if 'hasKGGraphAssertionDateTime' in line:
                        self.logger.info(f"*** Triple: {line}")
            
            # Use VitalSigns RDF conversion - try from_rdf instead of from_rdf_list for single objects
            try:
                # First try from_rdf for single object conversion
                objects = self.vitalsigns.from_rdf(rdf_data)
                if objects:
                    objects = [objects] if not isinstance(objects, list) else objects
                    self.logger.info(f"from_rdf returned {len(objects)} objects")
                else:
                    # Fallback to from_rdf_list
                    objects = self.vitalsigns.from_rdf_list(rdf_data)
                    self.logger.info(f"from_rdf_list returned {len(objects) if objects else 0} objects")
            except Exception as e:
                self.logger.warning(f"from_rdf failed: {e}, trying from_rdf_list")
                objects = self.vitalsigns.from_rdf_list(rdf_data)
            
            # Ensure we return a list
            if not isinstance(objects, list):
                objects = [objects] if objects else []
            
            return objects
            
        except Exception as e:
            self.logger.error(f"Error converting triples to VitalSigns objects: {e}")
            return []
    
    def _triples_to_quad_response(self, triples: List[tuple]) -> Dict[str, Any]:
        """
        Convert RDF triples to a quad response dict.
        
        Args:
            triples: List of RDF triples (subject, predicate, object)
            
        Returns:
            Dict with 'results' key containing quad dicts
        """
        try:
            results = []
            for subject, predicate, obj in triples:
                results.append({
                    "s": str(subject),
                    "p": str(predicate),
                    "o": str(obj),
                    "g": ""
                })
            
            self.logger.info(f"Converted {len(triples)} triples to {len(results)} quads")
            return {"results": results}
            
        except Exception as e:
            self.logger.error(f"Error converting triples to quad response: {e}")
            return {"results": []}
    
    def _execute_sparql_query(self, space, query: str) -> Dict[str, Any]:
        """
        Execute SPARQL query using pyoxigraph capabilities.
        
        Args:
            space: Mock space instance with pyoxigraph
            query: SPARQL query string
            
        Returns:
            Query results dictionary
        """
        try:
            return space.query_sparql(query)
            
        except Exception as e:
            self.logger.error(f"Error executing SPARQL query: {e}")
            return {"bindings": []}
    
    def _insert_quads_to_store(self, space, quads: List[tuple]) -> bool:
        """
        Insert RDF quads into pyoxigraph store.
        
        Args:
            space: Mock space instance with pyoxigraph
            quads: List of RDF quads (subject, predicate, object, graph)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            for quad in quads:
                if len(quad) == 4:
                    subject, predicate, obj, graph = quad
                    space.add_quad(subject, predicate, obj, graph)
                elif len(quad) == 3:
                    subject, predicate, obj = quad
                    space.add_quad(subject, predicate, obj, None)
            return True
            
        except Exception as e:
            self.logger.error(f"Error inserting quads to store: {e}")
            return False
    
    def _delete_quads_from_store(self, space, subject_uri: str, graph_id: str = None) -> bool:
        """
        Delete RDF quads from pyoxigraph store using SPARQL DELETE.
        
        Args:
            space: Mock space instance with pyoxigraph
            subject_uri: Subject URI to delete quads for
            graph_id: Optional graph identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Clean URI (remove angle brackets if present)
            clean_uri = str(subject_uri).strip('<>')
            clean_graph_id = str(graph_id).strip('<>') if graph_id else None
            
            if clean_graph_id:
                delete_query = f"""
                DELETE WHERE {{
                    GRAPH <{clean_graph_id}> {{
                        <{clean_uri}> ?p ?o .
                    }}
                }}
                """
            else:
                delete_query = f"""
                DELETE WHERE {{
                    <{clean_uri}> ?p ?o .
                }}
                """
            
            space.update_sparql(delete_query)
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting quads from store: {e}")
            return False
    
    def _log_all_quads_in_store(self, space, graph_id: str = None, context: str = ""):
        """
        Log all quads currently in the store for debugging purposes.
        
        Args:
            space: Mock space instance with pyoxigraph
            graph_id: Optional graph identifier to filter by
            context: Context string for logging
        """
        try:
            if graph_id:
                query = f"""
                SELECT ?s ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        ?s ?p ?o .
                    }}
                }}
                """
            else:
                query = """
                SELECT ?s ?p ?o ?g WHERE {
                    GRAPH ?g {
                        ?s ?p ?o .
                    }
                }
                """
            
            results = space.query_sparql(query)
            bindings = results.get("bindings", [])
            
            self.logger.info(f"=== ALL QUADS IN STORE {context} ===")
            self.logger.info(f"Total quads found: {len(bindings)}")
            
            if graph_id:
                self.logger.info(f"Graph: {graph_id}")
                for i, binding in enumerate(bindings):
                    s = binding.get("s", {}).get("value", "")
                    p = binding.get("p", {}).get("value", "")
                    o = binding.get("o", {}).get("value", "")
                    self.logger.info(f"  {i+1}: <{s}> <{p}> <{o}>")
            else:
                for i, binding in enumerate(bindings):
                    s = binding.get("s", {}).get("value", "")
                    p = binding.get("p", {}).get("value", "")
                    o = binding.get("o", {}).get("value", "")
                    g = binding.get("g", {}).get("value", "")
                    self.logger.info(f"  {i+1}: <{s}> <{p}> <{o}> <{g}>")
            
            self.logger.info("=== END QUADS ===")
            
        except Exception as e:
            self.logger.error(f"Error logging quads in store: {e}")
    
    def _get_vitaltype_uri(self, obj_type: str) -> str:
        """
        Get the correct vitaltype URI for a given object type.
        
        Args:
            obj_type: Object type string (e.g., "KGEntity", "KGType", etc.)
            
        Returns:
            Full vitaltype URI
        """
        vitaltype_mapping = {
            "KGEntity": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
            "KGType": "http://vital.ai/ontology/haley-ai-kg#KGType",
            "KGFrame": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
            "KGFrameSlot": "http://vital.ai/ontology/haley-ai-kg#KGFrameSlot"
        }
        
        return vitaltype_mapping.get(obj_type, f"http://vital.ai/ontology/haley-ai-kg#{obj_type}")
    
    def _store_vitalsigns_objects_in_pyoxigraph(self, space, objects: List[GraphObject], graph_id: str) -> int:
        """
        Store VitalSigns objects in pyoxigraph using native conversion to quads.
        
        Args:
            space: Mock space instance with pyoxigraph
            objects: List of VitalSigns GraphObject instances
            graph_id: Graph identifier for storage
            
        Returns:
            Number of objects successfully stored
        """
        try:
            stored_count = 0
            
            for obj in objects:
                try:
                    # Convert object to triples using the object's method
                    self.logger.info(f"Converting object to triples: {obj.URI} (type: {type(obj).__name__})")
                    
                    # Debug: show all properties before conversion
                    self.logger.info(f"Object properties before conversion: {list(obj._properties.keys())}")
                    for prop_uri in obj._properties.keys():
                        if 'hasKGGraphAssertionDateTime' in prop_uri:
                            self.logger.info(f"*** Found hasKGGraphAssertionDateTime property: {prop_uri}")
                    
                    triples = obj.to_triples()
                    self.logger.info(f"Object {obj.URI} generated {len(triples)} triples")
                    
                    # Debug: show all triples generated
                    for i, triple in enumerate(triples):
                        triple_str = f"{triple[0]} {triple[1]} {triple[2]}"
                        if 'hasKGGraphAssertionDateTime' in triple_str:
                            self.logger.info(f"*** Triple {i+1} contains hasKGGraphAssertionDateTime: {triple}")
                        else:
                            self.logger.info(f"Triple {i+1}: {triple}")
                    
                    # Convert triples to quads with graph_id, cleaning all URIs
                    quads = []
                    for s, p, o in triples:
                        clean_s = str(s).strip('<>')
                        clean_p = str(p).strip('<>')
                        clean_o = str(o).strip('<>')
                        # Handle None graph_id properly
                        clean_g = str(graph_id).strip('<>') if graph_id is not None else None
                        quad = (clean_s, clean_p, clean_o, clean_g)
                        self.logger.info(f"Inserting quad: {quad}")
                        quads.append(quad)
                except Exception as e:
                    self.logger.error(f"Error converting object {obj.URI} to triples: {e}")
                    continue
                
                # Store in pyoxigraph
                if self._insert_quads_to_store(space, quads):
                    stored_count += 1
            
            return stored_count
            
        except Exception as e:
            self.logger.error(f"Error storing VitalSigns objects in pyoxigraph: {e}")
            return 0
    
    def _retrieve_vitalsigns_objects_from_pyoxigraph(self, space, vitaltype_uri: str, graph_id: str = None, limit: int = None) -> List[GraphObject]:
        """
        Retrieve VitalSigns objects from pyoxigraph using SPARQL query.
        
        Args:
            space: Mock space instance with pyoxigraph
            vitaltype_uri: The vitaltype URI to filter by
            graph_id: Optional graph identifier
            limit: Optional limit on number of results
            
        Returns:
            List of VitalSigns GraphObject instances
        """
        try:
            # Build SPARQL query
            if graph_id:
                query = f"""
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{vitaltype_uri}> .
                        ?subject ?predicate ?object .
                    }}
                }}
                """
            else:
                query = f"""
                SELECT ?subject ?predicate ?object WHERE {{
                    ?subject a <{vitaltype_uri}> .
                    ?subject ?predicate ?object .
                }}
                """
            
            if limit:
                query += f" LIMIT {limit}"
            
            # Execute query
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                return []
            
            # Group results by subject
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns objects
            vitalsigns_objects = []
            for subject_uri, properties in subjects_data.items():
                obj = self._convert_sparql_to_vitalsigns_object(vitaltype_uri, subject_uri, properties)
                if obj:
                    vitalsigns_objects.append(obj)
            
            return vitalsigns_objects
            
        except Exception as e:
            self.logger.error(f"Error retrieving VitalSigns objects from pyoxigraph: {e}")
            return []
