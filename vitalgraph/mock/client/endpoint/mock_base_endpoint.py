"""Mock Base Endpoint

Base class for all mock endpoint implementations.
Provides common functionality and structure for mock endpoints with VitalSigns native JSON-LD support.
"""

from typing import Dict, Any, Optional, List, Union
import logging

# VitalSigns imports for native JSON-LD functionality
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
        
        # Initialize VitalSigns for native JSON-LD operations
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
    
    def _jsonld_to_triples(self, jsonld_obj: Dict[str, Any], graph_id: str = None) -> list:
        """
        Convert a JSON-LD object to RDF triples (VitalSigns-style).
        
        Args:
            jsonld_obj: JSON-LD object dictionary
            graph_id: Optional graph identifier
            
        Returns:
            List of triple dictionaries
        """
        triples = []
        subject_uri = jsonld_obj.get("@id")
        
        if not subject_uri:
            return triples
        
        for key, value in jsonld_obj.items():
            if key == "@id":
                continue
            elif key == "@type":
                # Handle type specially
                type_uri = self._expand_uri(value)
                triples.append({
                    "subject": subject_uri,
                    "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                    "object": type_uri,
                    "graph": graph_id
                })
                self.logger.debug(f"Created type triple: {subject_uri} -> {type_uri}")
            else:
                # Handle other properties
                pred_uri = self._expand_uri(key)
                obj_value = self._format_object_value(value)
                triples.append({
                    "subject": subject_uri,
                    "predicate": pred_uri,
                    "object": obj_value,
                    "graph": graph_id
                })
        
        return triples
    
    def _triples_to_jsonld(self, triples: list, subject_uri: str) -> Dict[str, Any]:
        """
        Convert RDF triples back to JSON-LD object (VitalSigns-style).
        
        Args:
            triples: List of triple dictionaries for the subject
            subject_uri: Subject URI to reconstruct
            
        Returns:
            JSON-LD object dictionary
        """
        obj = {"@id": subject_uri}
        
        for triple in triples:
            if triple["subject"] != subject_uri:
                continue
                
            pred = triple["predicate"]
            obj_val = triple["object"]
            
            if pred == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type":
                # For type, keep the full URI to maintain compatibility
                obj["@type"] = obj_val
            else:
                prop_name = self._compact_uri(pred)
                obj[prop_name] = obj_val
        
        return obj
    
    def _expand_uri(self, uri_or_curie: str) -> str:
        """
        Expand a CURIE or short form to full URI.
        
        Args:
            uri_or_curie: URI, CURIE, or short form
            
        Returns:
            Full URI
        """
        if uri_or_curie.startswith("http"):
            return uri_or_curie
        elif uri_or_curie.startswith("rdfs:"):
            return f"http://www.w3.org/2000/01/rdf-schema#{uri_or_curie.replace('rdfs:', '')}"
        elif uri_or_curie.startswith("rdf:"):
            return f"http://www.w3.org/1999/02/22-rdf-syntax-ns#{uri_or_curie.replace('rdf:', '')}"
        elif uri_or_curie.startswith("foaf:"):
            return f"http://xmlns.com/foaf/0.1/{uri_or_curie.replace('foaf:', '')}"
        elif uri_or_curie == "Class":  # Handle bare "Class" 
            return "http://www.w3.org/2000/01/rdf-schema#Class"
        elif ":" not in uri_or_curie:
            # Assume it's a VitalGraph property
            return f"http://vital.ai/ontology/haley-ai-kg#{uri_or_curie}"
        else:
            return uri_or_curie
    
    def _compact_uri(self, full_uri: str) -> str:
        """
        Compact a full URI to a shorter form when possible.
        
        Args:
            full_uri: Full URI
            
        Returns:
            Compacted URI or original if no compaction possible
        """
        if full_uri.startswith("http://www.w3.org/2000/01/rdf-schema#"):
            return f"rdfs:{full_uri.replace('http://www.w3.org/2000/01/rdf-schema#', '')}"
        elif full_uri.startswith("http://www.w3.org/1999/02/22-rdf-syntax-ns#"):
            return f"rdf:{full_uri.replace('http://www.w3.org/1999/02/22-rdf-syntax-ns#', '')}"
        elif full_uri.startswith("http://xmlns.com/foaf/0.1/"):
            return f"foaf:{full_uri.replace('http://xmlns.com/foaf/0.1/', '')}"
        elif full_uri.startswith("http://vital.ai/ontology/haley-ai-kg#"):
            return full_uri.replace("http://vital.ai/ontology/haley-ai-kg#", "")
        else:
            return full_uri
    
    def _format_object_value(self, value: Any) -> str:
        """
        Format an object value for RDF storage.
        
        Args:
            value: Value to format
            
        Returns:
            Formatted string value
        """
        if isinstance(value, dict) and "@id" in value:
            return value["@id"]
        elif isinstance(value, (int, float, bool)):
            return str(value)
        else:
            return str(value)
    
    def _delete_object_triples(self, space, subject_uri: str, graph_id: str = None):
        """
        Delete all triples for a given subject (VitalSigns update pattern).
        
        Args:
            space: Mock space instance
            subject_uri: Subject URI to delete triples for
            graph_id: Optional graph identifier
        """
        try:
            # Clean URI (remove angle brackets if present)
            clean_uri = subject_uri.strip('<>')
            
            # Query for all triples with this subject
            query = f"""
            SELECT ?p ?o WHERE {{
                <{clean_uri}> ?p ?o .
            }}
            """
            result = space.query_sparql(query)
            
            if result.get("bindings"):
                for binding in result["bindings"]:
                    pred = binding.get("p", {}).get("value", "").strip('<>')
                    obj = binding.get("o", {}).get("value", "").strip('<>')
                    if pred and obj:
                        space.remove_quad(clean_uri, pred, obj, graph_id)
                        
        except Exception as e:
            self.logger.debug(f"Error deleting triples for {subject_uri}: {e}")
    
    def _get_object_from_triples(self, space, subject_uri: str, graph_id: str = None) -> Dict[str, Any]:
        """
        Reconstruct an object from its triples (VitalSigns-style).
        
        Args:
            space: Mock space instance
            subject_uri: Subject URI to reconstruct
            graph_id: Optional graph identifier
            
        Returns:
            JSON-LD object dictionary
        """
        try:
            # Clean URI (remove angle brackets if present)
            clean_uri = subject_uri.strip('<>')
            
            # Query for all triples with this subject
            if graph_id:
                query = f"""
                SELECT ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        <{clean_uri}> ?p ?o .
                    }}
                }}
                """
            else:
                query = f"""
                SELECT ?p ?o WHERE {{
                    <{clean_uri}> ?p ?o .
                }}
                """
            result = space.query_sparql(query)
            
            if result.get("bindings"):
                # Convert query results to triple format
                triples = []
                for binding in result["bindings"]:
                    pred = binding.get("p", {}).get("value", "").strip('<>')
                    obj = binding.get("o", {}).get("value", "").strip('<>')
                    if pred and obj:
                        triples.append({
                            "subject": clean_uri,
                            "predicate": pred,
                            "object": obj
                        })
                
                # Convert triples back to JSON-LD object
                return self._triples_to_jsonld(triples, clean_uri)
            
        except Exception as e:
            self.logger.debug(f"Error reconstructing object {subject_uri}: {e}")
        
        return None
    
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
            # Create the appropriate VitalSigns object based on vitaltype_uri
            if vitaltype_uri == "http://vital.ai/ontology/vital#FileNode":
                from vital_ai_domain.model.FileNode import FileNode
                obj = FileNode()
            elif vitaltype_uri == "http://vital.ai/ontology/haley-ai-kg#KGEntity":
                from ai_haley_kg_domain.model.KGEntity import KGEntity
                obj = KGEntity()
            elif vitaltype_uri == "http://vital.ai/ontology/haley-ai-kg#KGType":
                from ai_haley_kg_domain.model.KGType import KGType
                obj = KGType()
            elif vitaltype_uri == "http://vital.ai/ontology/haley-ai-kg#KGFrame":
                from ai_haley_kg_domain.model.KGFrame import KGFrame
                obj = KGFrame()
            else:
                # Default to GraphObject for unknown types
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                obj = GraphObject()
            
            # Clean URI - remove angle brackets if present (including double brackets)
            clean_uri = str(uri).strip('<>').strip('<>')
            obj.URI = clean_uri
            
            # Set properties using the VitalSigns property system
            for prop_uri, value in properties.items():
                # Clean property URI (remove angle brackets including double brackets) and value (remove quotes)
                clean_prop_uri = str(prop_uri).strip('<>').strip('<>')
                clean_value = str(value).strip('"').strip('<>') if isinstance(value, str) else value
                
                # FileNode specific properties
                if clean_prop_uri == "http://vital.ai/ontology/vital#hasFileName":
                    if hasattr(obj, 'fileName'):
                        obj.fileName = clean_value
                elif clean_prop_uri == "http://vital.ai/ontology/vital#hasFileType":
                    if hasattr(obj, 'fileType'):
                        obj.fileType = clean_value
                elif clean_prop_uri == "http://vital.ai/ontology/vital#hasFileLength":
                    if hasattr(obj, 'fileLength'):
                        try:
                            obj.fileLength = int(clean_value) if isinstance(clean_value, str) and clean_value.isdigit() else int(clean_value)
                        except (ValueError, TypeError):
                            obj.fileLength = clean_value
                #KGEntity specific properties
                elif clean_prop_uri == "http://vital.ai/ontology/vital-core#hasName":
                    if hasattr(obj, 'name'):
                        obj.name = clean_value
                # Shared haley-ai-kg properties
                elif clean_prop_uri == "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription":
                    # Both KGEntity and KGType can have this property
                    if hasattr(obj, 'kGGraphDescription'):
                        obj.kGGraphDescription = clean_value
                    elif hasattr(obj, 'kGraphDescription'):
                        obj.kGraphDescription = clean_value
                
                # KGEntity specific properties
                elif clean_prop_uri == "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType":
                    if hasattr(obj, 'kGEntityType'):
                        obj.kGEntityType = clean_value
                
                # KGType specific properties (from schema)
                elif clean_prop_uri == "http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion":
                    if hasattr(obj, 'kGModelVersion'):
                        obj.kGModelVersion = clean_value
                elif clean_prop_uri == "http://vital.ai/ontology/haley-ai-kg#hasKGTypeVersion":
                    if hasattr(obj, 'kGTypeVersion'):
                        obj.kGTypeVersion = clean_value
                
                # KGFrame specific properties (from schema)
                elif clean_prop_uri == "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription":
                    if hasattr(obj, 'kGFrameTypeDescription'):
                        obj.kGFrameTypeDescription = clean_value
                elif clean_prop_uri == "http://vital.ai/ontology/haley-ai-kg#hasFrameSequence":
                    if hasattr(obj, 'frameSequence'):
                        try:
                            obj.frameSequence = int(clean_value) if isinstance(clean_value, str) and clean_value.isdigit() else int(clean_value)
                        except (ValueError, TypeError):
                            obj.frameSequence = clean_value
            
            return obj
            
        except Exception as e:
            self.logger.error(f"Error converting SPARQL to VitalSigns object: {e}")
            return None
    
    def _objects_to_jsonld_document(self, objects: List[GraphObject]) -> Dict[str, Any]:
        """
        Convert VitalSigns objects to JSON-LD document using native functionality.
        
        Args:
            objects: List of VitalSigns GraphObject instances
            
        Returns:
            Complete JSON-LD document with @context and @graph
        """
        try:
            if not objects:
                # Return empty document with proper structure - use FileNode class method
                from vital_ai_domain.model.FileNode import FileNode
                return FileNode.to_jsonld_list([])
            
            # Create proper @graph structure manually since to_jsonld_list() isn't working as expected
            graph_items = []
            for obj in objects:
                obj_jsonld = obj.to_jsonld()
                # Remove @context from individual objects since it will be at the top level
                if '@context' in obj_jsonld:
                    del obj_jsonld['@context']
                graph_items.append(obj_jsonld)
            
            jsonld_result = {
                '@context': {},
                '@graph': graph_items
            }
            
            # Ensure the context includes the vital prefixes that the test expects
            if '@context' not in jsonld_result:
                jsonld_result['@context'] = {}
            
            # Add the vital prefixes to the context
            jsonld_result['@context'].update({
                "vital": "http://vital.ai/ontology/vital#",
                "vital-core": "http://vital.ai/ontology/vital-core#",
                "haley": "http://vital.ai/ontology/haley-ai-kg#"
            })
            
            return jsonld_result
            
        except Exception as e:
            self.logger.error(f"Error converting objects to JSON-LD document: {e}")
            # Fallback to empty FileNode list
            from vital_ai_domain.model.FileNode import FileNode
            return FileNode.to_jsonld_list([])
    
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
                elif obj.startswith('http'):
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
            # Use VitalSigns native conversion from triples list
            objects = self.vitalsigns.from_triples_list(triples)
            
            # Ensure we return a list
            if not isinstance(objects, list):
                objects = [objects] if objects else []
            
            return objects
            
        except Exception as e:
            self.logger.error(f"Error converting triples to VitalSigns objects: {e}")
            return []
    
    def _triples_to_jsonld_document(self, triples: List[tuple]) -> Dict[str, Any]:
        """
        Convert RDF triples to JSON-LD document structure.
        
        Args:
            triples: List of RDF triples (subject, predicate, object)
            
        Returns:
            JSON-LD document dictionary
        """
        try:
            # Create basic JSON-LD structure using Pydantic field names
            context = {
                "vital": "http://vital.ai/ontology/vital-core#",
                "haley": "http://vital.ai/ontology/haley-ai-kg#",
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#"
            }
            graph_items = []
            
            # Group triples by subject
            subjects = {}
            for subject, predicate, obj in triples:
                if subject not in subjects:
                    subjects[subject] = {"@id": subject}
                
                # Add predicate-object pair
                if predicate not in subjects[subject]:
                    subjects[subject][predicate] = obj
                else:
                    # Convert to array if multiple values
                    current_value = subjects[subject][predicate]
                    if not isinstance(current_value, list):
                        subjects[subject][predicate] = [current_value]
                    subjects[subject][predicate].append(obj)
            
            # Add all subjects to graph
            graph_items = list(subjects.values())
            
            # Debug logging
            self.logger.info(f"Converted {len(triples)} triples to {len(subjects)} subjects")
            self.logger.info(f"Subjects: {list(subjects.keys())}")
            if subjects:
                first_subject = list(subjects.values())[0]
                self.logger.info(f"First subject structure: {first_subject}")
            
            # Return dictionary with proper field names for JsonLdDocument
            return {
                "@context": context,
                "@graph": graph_items
            }
            
        except Exception as e:
            self.logger.error(f"Error converting triples to JSON-LD document: {e}")
            # Return empty JSON-LD document
            from ai_haley_kg_domain.model.KGEntity import KGEntity
            return KGEntity.to_jsonld_list([])
    
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
    
    def _jsonld_to_vitalsigns_objects(self, jsonld_document: Dict[str, Any]) -> List[GraphObject]:
        """
        Convert JSON-LD document to VitalSigns objects using native functionality.
        
        Args:
            jsonld_document: JSON-LD document dictionary
            
        Returns:
            List of VitalSigns GraphObject instances
        """
        try:
            # Handle @graph array format using VitalSigns from_jsonld_list
            if "@graph" in jsonld_document:
                # Use VitalSigns from_jsonld_list for documents with @graph
                objects = self.vitalsigns.from_jsonld_list(jsonld_document)
                
                # Ensure we return a list
                if not isinstance(objects, list):
                    objects = [objects] if objects else []
                
                return objects
            else:
                # Single object document
                try:
                    obj = self.vitalsigns.from_jsonld(jsonld_document)
                    
                    # Handle None result
                    if obj is None:
                        self.logger.warning(f"VitalSigns returned None for JSON-LD document: {jsonld_document}")
                        return []
                    
                    # Ensure we return a list
                    if not isinstance(obj, list):
                        return [obj]
                    else:
                        return obj
                except Exception as e:
                    self.logger.error(f"Error converting single JSON-LD object: {e}")
                    return []
            
        except Exception as e:
            self.logger.error(f"Error converting JSON-LD to VitalSigns objects: {e}")
            return []
    
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
                # Convert object to triples using the object's method
                triples = obj.to_triples()
                
                # Convert triples to quads with graph_id, cleaning all URIs
                quads = []
                for s, p, o in triples:
                    clean_s = str(s).strip('<>')
                    clean_p = str(p).strip('<>')
                    clean_o = str(o).strip('<>')
                    clean_g = str(graph_id).strip('<>')
                    quad = (clean_s, clean_p, clean_o, clean_g)
                    self.logger.info(f"Inserting quad: {quad}")
                    quads.append(quad)
                
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
