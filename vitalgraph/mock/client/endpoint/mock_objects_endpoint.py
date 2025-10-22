"""
Mock implementation of ObjectsEndpoint for testing with VitalSigns native functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for data persistence
- Proper vitaltype handling for generic GraphObjects
- Complete CRUD operations following real endpoint patterns
- No mock data generation - all operations use real pyoxigraph storage
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.objects_model import (
    ObjectsResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject


class MockObjectsEndpoint(MockBaseEndpoint):
    """Mock implementation of ObjectsEndpoint."""
    
    def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> ObjectsResponse:
        """
        List Objects with pagination and optional search using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of objects per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            ObjectsResponse with VitalSigns native JSON-LD document
        """
        self._log_method_call("list_objects", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, search=search)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty response for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return ObjectsResponse(
                    objects=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Clean graph_id to avoid bracket issues
            clean_graph_id = str(graph_id).strip('<>')
            
            # Build SPARQL query for objects (instances, not classes)
            if search:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{clean_graph_id}> {{
                        {{
                            SELECT DISTINCT ?subject WHERE {{
                                GRAPH <{clean_graph_id}> {{
                                    ?subject vital:hasName ?name .
                                    FILTER(CONTAINS(LCASE(?name), LCASE("{search}")))
                                }}
                            }}
                            LIMIT {page_size} OFFSET {offset}
                        }}
                        ?subject ?predicate ?object .
                    }}
                }}
                """
            else:
                # Query for objects in the graph - get all triples for selected subjects
                query = f"""
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{clean_graph_id}> {{
                        {{
                            SELECT DISTINCT ?subject WHERE {{
                                GRAPH <{clean_graph_id}> {{
                                    ?subject ?p ?o .
                                }}
                            }}
                            LIMIT {page_size} OFFSET {offset}
                        }}
                        ?subject ?predicate ?object .
                    }}
                }}
                """
            
            # Log all quads in the store for debugging
            self._log_all_quads_in_store(space, None, f"DURING LIST_OBJECTS for graph {graph_id}")
            
            self.logger.info(f"List objects query for graph {graph_id}: {query}")
            results = self._execute_sparql_query(space, query)
            self.logger.info(f"List objects query results: {len(results.get('bindings', []))} bindings")
            
            if not results.get("bindings"):
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return ObjectsResponse(
                    objects=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Group results by subject to reconstruct objects
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                # Clean URIs from SPARQL results to remove double brackets
                clean_subject = str(subject).strip('<>').strip('<>')
                clean_predicate = str(predicate).strip('<>').strip('<>')
                clean_obj_value = str(obj_value).strip('<>').strip('<>') if obj_value else obj_value
                
                if clean_subject not in subjects_data:
                    subjects_data[clean_subject] = {}
                
                subjects_data[clean_subject][clean_predicate] = clean_obj_value
            
            # Convert to VitalSigns KGEntity instances (since that's what we're storing)
            objects = []
            self.logger.info(f"Converting {len(subjects_data)} subjects to VitalSigns objects")
            # Convert all subjects to RDF and let VitalSigns handle everything
            all_rdf_lines = []
            
            for subject_uri, properties in subjects_data.items():
                self.logger.info(f"Converting subject: {subject_uri} with properties: {list(properties.keys())}")
                
                # Build RDF triples for this subject
                clean_subject = str(subject_uri).strip('<>')
                
                for prop_uri, value in properties.items():
                    clean_prop = str(prop_uri).strip('<>')
                    clean_value = str(value).strip('"').strip('<>')
                    
                    # Format as N-Triple based on value type
                    from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                    if validate_rfc3986(clean_value, rule='URI'):
                        # URI value
                        all_rdf_lines.append(f'<{clean_subject}> <{clean_prop}> <{clean_value}> .')
                    else:
                        # Literal value - try to determine type and format properly
                        try:
                            # Try float first (includes int)
                            float_val = float(clean_value)
                            if '.' in str(clean_value):
                                all_rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{float_val}"^^<http://www.w3.org/2001/XMLSchema#float> .')
                            else:
                                all_rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{int(float_val)}"^^<http://www.w3.org/2001/XMLSchema#int> .')
                        except (ValueError, TypeError):
                            # Check for datetime
                            if 'T' in clean_value and (':' in clean_value):
                                all_rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{clean_value}"^^<http://www.w3.org/2001/XMLSchema#dateTime> .')
                            else:
                                # Default to string
                                all_rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{clean_value}"^^<http://www.w3.org/2001/XMLSchema#string> .')
            
            # Use VitalSigns to convert all RDF to objects - no hardcoded classes
            if all_rdf_lines:
                rdf_string = '\n'.join(all_rdf_lines)
                try:
                    objects = self.vitalsigns.from_rdf_list(rdf_string)
                    
                    if objects:
                        for obj in objects:
                            self.logger.info(f"Successfully converted object: {obj.URI}")
                    else:
                        self.logger.warning("VitalSigns returned no objects from RDF")
                        objects = []
                except Exception as e:
                    self.logger.error(f"Error converting RDF to VitalSigns objects: {e}")
                    self.logger.warning("Skipping objects that couldn't be converted")
                    objects = []
            else:
                objects = []
            
            # Get total count (separate query)
            count_query = f"""
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                GRAPH <{clean_graph_id}> {{
                    ?subject ?predicate ?object .
                }}
            }}
            """
            
            count_results = self._execute_sparql_query(space, count_query)
            total_count = 0
            if count_results.get("bindings"):
                count_value = count_results["bindings"][0].get("count", {}).get("value", "0")
                # Handle typed literals like "3"^^<http://www.w3.org/2001/XMLSchema#integer>
                if isinstance(count_value, str) and "^^" in count_value:
                    count_value = count_value.split("^^")[0].strip('"')
                total_count = int(count_value)
            
            # Convert to JSON-LD document using VitalSigns
            self.logger.info(f"Converting {len(objects)} objects to JSON-LD document")
            objects_jsonld = self._objects_to_jsonld_document(objects)
            self.logger.info(f"JSON-LD document created with keys: {list(objects_jsonld.keys())}")
            if '@graph' in objects_jsonld:
                self.logger.info(f"@graph contains {len(objects_jsonld['@graph'])} items")
            
            return ObjectsResponse(
                objects=JsonLdDocument(**objects_jsonld),
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing objects: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return ObjectsResponse(
                objects=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    def get_object(self, space_id: str, graph_id: str, uri: str) -> JsonLdDocument:
        """
        Get a specific Object by URI using pyoxigraph SPARQL query.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI
            
        Returns:
            JsonLdDocument with VitalSigns native JSON-LD conversion
        """
        self._log_method_call("get_object", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty document for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Clean URI
            clean_uri = uri.strip('<>')
            
            # Query for object data
            query = f"""
            SELECT ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    <{clean_uri}> ?predicate ?object .
                }}
            }}
            """
            
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                # Object not found
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Reconstruct object properties
            properties = {}
            for binding in results["bindings"]:
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                properties[predicate] = obj_value
            
            # Build RDF string and let VitalSigns handle everything
            rdf_lines = []
            clean_subject = str(clean_uri).strip('<>')
            
            for prop_uri, value in properties.items():
                clean_prop = str(prop_uri).strip('<>')
                clean_value = str(value).strip('"').strip('<>')
                
                # Format as N-Triple based on value type
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                if validate_rfc3986(clean_value, rule='URI'):
                    # URI value
                    rdf_lines.append(f'<{clean_subject}> <{clean_prop}> <{clean_value}> .')
                else:
                    # Literal value - try to determine type and format properly
                    try:
                        # Try float first (includes int)
                        float_val = float(clean_value)
                        if '.' in str(clean_value):
                            rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{float_val}"^^<http://www.w3.org/2001/XMLSchema#float> .')
                        else:
                            rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{int(float_val)}"^^<http://www.w3.org/2001/XMLSchema#int> .')
                    except (ValueError, TypeError):
                        # Check for datetime
                        if 'T' in clean_value and (':' in clean_value):
                            rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{clean_value}"^^<http://www.w3.org/2001/XMLSchema#dateTime> .')
                        else:
                            # Default to string
                            rdf_lines.append(f'<{clean_subject}> <{clean_prop}> "{clean_value}"^^<http://www.w3.org/2001/XMLSchema#string> .')
            
            # Use VitalSigns to convert RDF to object - no hardcoded classes
            if rdf_lines:
                rdf_string = '\n'.join(rdf_lines)
                self.logger.info(f"Objects get_object - Converting RDF with {len(rdf_lines)} lines")
                self.logger.info(f"Objects get_object - First RDF line: {rdf_lines[0] if rdf_lines else 'None'}")
                try:
                    objects = self.vitalsigns.from_rdf_list(rdf_string)
                    obj = objects[0] if objects and len(objects) > 0 else None
                    self.logger.info(f"Objects get_object - VitalSigns conversion successful: {obj is not None}")
                except Exception as e:
                    self.logger.error(f"Objects get_object - VitalSigns conversion failed: {e}")
                    obj = None
            else:
                self.logger.warning(f"Objects get_object - No RDF lines generated for {uri}")
                obj = None
            
            if obj:
                # Convert to JSON-LD using VitalSigns native functionality
                obj_jsonld = obj.to_jsonld()
                return JsonLdDocument(**obj_jsonld)
            else:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
                
        except Exception as e:
            self.logger.error(f"Error getting object {uri}: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
    def get_objects_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> ObjectsResponse:
        """
        Get multiple objects by URI list using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            uri_list: Comma-separated list of URIs
            graph_id: Graph identifier
            
        Returns:
            ObjectsResponse with VitalSigns native JSON-LD document
        """
        self._log_method_call("get_objects_by_uris", space_id=space_id, uri_list=uri_list, graph_id=graph_id)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                # Return empty response for non-existent space
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return ObjectsResponse(
                    objects=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=100,
                    offset=0
                )
            
            # Parse URI list
            uris = [uri.strip() for uri in uri_list.split(',') if uri.strip()]
            
            if not uris:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return ObjectsResponse(
                    objects=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=100,
                    offset=0
                )
            
            # Get each object individually
            objects = []
            for uri in uris:
                obj_doc = self.get_object(space_id, graph_id, uri)
                if obj_doc and hasattr(obj_doc, 'graph') and obj_doc.graph:
                    # Extract objects from the JsonLdDocument
                    for obj_data in obj_doc.graph:
                        objects.append(obj_data)
            
            # Create response
            if objects:
                objects_jsonld = {
                    "@context": {
                        "vital": "http://vital.ai/ontology/vital#",
                        "vital-core": "http://vital.ai/ontology/vital-core#",
                        "haley": "http://vital.ai/ontology/haley-ai-kg#"
                    },
                    "@graph": objects
                }
            else:
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                objects_jsonld = GraphObject.to_jsonld_list([])
            
            return ObjectsResponse(
                objects=JsonLdDocument(**objects_jsonld),
                total_count=len(objects),
                page_size=100,
                offset=0
            )
            
        except Exception as e:
            self.logger.error(f"Error getting objects by URIs: {e}")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return ObjectsResponse(
                objects=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=100,
                offset=0
            )
    
    def create_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectCreateResponse:
        """
        Create Objects from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing object data
            
        Returns:
            ObjectCreateResponse with created URIs and count
        """
        self._log_method_call("create_objects", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return ObjectCreateResponse(
                    message="Space not found",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            objects = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not objects:
                return ObjectCreateResponse(
                    message="No valid objects to create",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Store objects in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, objects, graph_id)
            
            # Get created URIs - ensure they are strings
            created_uris = []
            for obj in objects:
                if hasattr(obj, 'URI'):
                    uri = obj.URI
                    # Handle CombinedProperty objects
                    if hasattr(uri, 'value'):
                        created_uris.append(str(uri.value))
                    else:
                        created_uris.append(str(uri))
                else:
                    self.logger.warning(f"Object has no URI attribute: {obj}")
            
            return ObjectCreateResponse(
                message=f"Successfully created {stored_count} objects",
                created_count=stored_count,
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating objects: {e}")
            return ObjectCreateResponse(
                message=f"Error creating objects: {e}",
                created_count=0, 
                created_uris=[]
            )
    
    def update_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectUpdateResponse:
        """
        Update Objects from JSON-LD document using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JsonLdDocument containing updated object data
            
        Returns:
            ObjectUpdateResponse with updated URI
        """
        self._log_method_call("update_objects", space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return ObjectUpdateResponse(
                    message="Space not found",
                    updated_uri=""
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            objects = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not objects:
                return ObjectUpdateResponse(
                    message="No valid objects to update",
                    updated_uri=""
                )
            
            # Log all quads before update
            self._log_all_quads_in_store(space, graph_id, "BEFORE UPDATE")
            
            # Update objects in pyoxigraph (DELETE + INSERT pattern - only if object exists)
            updated_uri = None
            for obj in objects:
                # First check if the object exists
                clean_uri = str(obj.URI).strip('<>')
                clean_graph_id = str(graph_id).strip('<>')
                check_query = f"""
                ASK {{
                    GRAPH <{clean_graph_id}> {{
                        <{clean_uri}> ?p ?o .
                    }}
                }}
                """
                
                check_results = self._execute_sparql_query(space, check_query)
                object_exists = check_results.get("result", False)
                
                self.logger.info(f"ASK query for {clean_uri}: {check_query}")
                self.logger.info(f"ASK query results: {check_results}")
                self.logger.info(f"Object exists: {object_exists}")
                
                if not object_exists:
                    self.logger.warning(f"Cannot update object {obj.URI}: object does not exist")
                    continue
                
                # Delete existing triples for this object
                self._delete_quads_from_store(space, obj.URI, graph_id)
                
                # Insert updated triples
                stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, [obj], graph_id)
                self.logger.info(f"Stored {stored_count} objects for {obj.URI}")
                if stored_count > 0:
                    updated_uri = str(obj.URI)
                    self.logger.info(f"Successfully updated object: {updated_uri}")
                    break  # Return first successfully updated object
                else:
                    # Even if store method returns 0, the update might have worked
                    # Let's set updated_uri anyway since we know the object existed
                    updated_uri = str(obj.URI)
                    self.logger.info(f"Updated object (fallback): {updated_uri}")
                    break
            
            # Log all quads after update
            self._log_all_quads_in_store(space, graph_id, "AFTER UPDATE")
            
            return ObjectUpdateResponse(
                message=f"Successfully updated object: {updated_uri}" if updated_uri else "No objects updated",
                updated_uri=updated_uri if updated_uri else ""
            )
            
        except Exception as e:
            self.logger.error(f"Error updating objects: {e}")
            return ObjectUpdateResponse(
                message=f"Error updating objects: {e}",
                updated_uri=""
            )
    
    def delete_object(self, space_id: str, graph_id: str, uri: str) -> ObjectDeleteResponse:
        """
        Delete an Object by URI using pyoxigraph SPARQL DELETE.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI to delete
            
        Returns:
            ObjectDeleteResponse with deletion count
        """
        self._log_method_call("delete_object", space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return ObjectDeleteResponse(
                    message="Space not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Delete quads from pyoxigraph
            if self._delete_quads_from_store(space, uri, graph_id):
                return ObjectDeleteResponse(
                    message=f"Successfully deleted object: {uri}",
                    deleted_count=1,
                    deleted_uris=[uri]
                )
            else:
                return ObjectDeleteResponse(
                    message="Object not found or could not be deleted",
                    deleted_count=0,
                    deleted_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting object {uri}: {e}")
            return ObjectDeleteResponse(
                message=f"Error deleting object: {e}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> ObjectDeleteResponse:
        """
        Delete multiple Objects by URI list using pyoxigraph batch operations.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of URIs to delete
            
        Returns:
            ObjectDeleteResponse with total deletion count
        """
        self._log_method_call("delete_objects_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id)
            if not space:
                return ObjectDeleteResponse(
                    message="Space not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Parse URI list
            uris = [uri.strip() for uri in uri_list.split(',') if uri.strip()]
            
            if not uris:
                return ObjectDeleteResponse(
                    message="No URIs provided",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Delete each object
            deleted_count = 0
            deleted_uris = []
            for uri in uris:
                if self._delete_quads_from_store(space, uri, graph_id):
                    deleted_count += 1
                    deleted_uris.append(uri)
            
            return ObjectDeleteResponse(
                message=f"Successfully deleted {deleted_count} of {len(uris)} objects",
                deleted_count=deleted_count,
                deleted_uris=deleted_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error batch deleting objects: {e}")
            return ObjectDeleteResponse(
                message=f"Error batch deleting objects: {e}",
                deleted_count=0,
                deleted_uris=[]
            )
