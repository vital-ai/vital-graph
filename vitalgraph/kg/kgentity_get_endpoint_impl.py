"""
KGEntity Get Operations Implementation

This module contains the implementation functions for KGEntity retrieval operations,
extracted from MockKGEntitiesEndpoint to improve code organization and maintainability.
"""

from typing import List, Optional, Any, Dict
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.model.kgentities_model import EntityGraphResponse


def get_entity_frames_complex_impl(endpoint_instance, space_id: str, graph_id: str, entity_uri: str) -> JsonLdDocument:
    """
    Get all frames connected to a specific entity (returns frame objects, not edges).
    Uses the entity-frame edges to find connected frames, then returns the frame objects.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        entity_uri: Parent entity URI
        
    Returns:
        JsonLdDocument containing frame objects connected to the entity
    """
    endpoint_instance._log_method_call("get_entity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return JsonLdDocument(context={}, graph=[])
        
        # Find frames connected to entity via edges, then return the frame objects
        if graph_id is None:
            # Query default graph
            frame_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?frame ?prop ?value WHERE {{
                # Find Edge_hasEntityKGFrame connecting entity to frames
                ?edge a haley:Edge_hasEntityKGFrame ;
                      vital:hasEdgeSource <{entity_uri}> ;
                      vital:hasEdgeDestination ?frame .
                
                # Get all properties of the connected frames (including rdf:type)
                ?frame ?prop ?value .
            }}
            """
        else:
            # Query named graph
            frame_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?frame ?prop ?value WHERE {{
                GRAPH <{graph_id}> {{
                    # Find Edge_hasEntityKGFrame connecting entity to frames
                    ?edge a haley:Edge_hasEntityKGFrame ;
                          vital:hasEdgeSource <{entity_uri}> ;
                          vital:hasEdgeDestination ?frame .
                    
                    # Get all properties of the connected frames (including rdf:type)
                    ?frame ?prop ?value .
                }}
            }}
            """
        
        endpoint_instance.logger.info(f"Finding frames connected to entity: {entity_uri}")
        frame_results = list(space.store.query(frame_query))
        endpoint_instance.logger.info(f"Found {len(frame_results)} frame properties")
        
        if not frame_results:
            return JsonLdDocument(context={}, graph=[])
        
        # Convert frame results to triples format
        frame_triples = []
        for result in frame_results:
            frame_uri = str(result['frame']).strip('<>')  # Strip brackets from pyoxigraph result
            prop_uri = str(result['prop']).strip('<>')    # Strip brackets from pyoxigraph result
            
            # Properly handle pyoxigraph value objects
            value_obj = result['value']
            if hasattr(value_obj, 'value'):
                # It's a Literal - get the actual value
                value = str(value_obj.value)
            else:
                # It's a NamedNode - get the URI and strip brackets
                value = str(value_obj).strip('<>')
            
            frame_triples.append({
                'subject': f'<{frame_uri}>',
                'predicate': f'<{prop_uri}>',
                'object': f'<{value}>' if str(value).startswith('http') else f'"{value}"'
            })
        
        # Convert frame triples to VitalSigns objects
        endpoint_instance.logger.info(f"Converting {len(frame_triples)} frame triples to VitalSigns objects")
        # Log the triples to debug the Type URI issue
        for i, triple in enumerate(frame_triples):  # Log ALL triples
            endpoint_instance.logger.info(f"Triple {i+1}: {triple}")
        vitalsigns_objects = endpoint_instance._convert_triples_to_vitalsigns_objects(frame_triples)
        endpoint_instance.logger.info(f"VitalSigns conversion returned {len(vitalsigns_objects) if vitalsigns_objects else 0} objects")
        
        if vitalsigns_objects:
            # Convert to JSON-LD - handle single vs multiple objects properly
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            endpoint_instance.logger.info("Converting VitalSigns objects to JSON-LD")
            
            # Always use to_jsonld_list to ensure consistent graph array format
            try:
                jsonld_data = GraphObject.to_jsonld_list(vitalsigns_objects)
                endpoint_instance.logger.info(f"JSON-LD data: {jsonld_data}")
                
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
                
                # Apply the fix to the entire document
                jsonld_data = fix_jsonld_fields(jsonld_data)
                
                # Ensure single objects are wrapped in graph array for consistency
                if 'graph' not in jsonld_data and '@id' in jsonld_data:
                    # Single object returned directly - wrap it in graph array
                    context = jsonld_data.get('@context', {})
                    object_data = {k: v for k, v in jsonld_data.items() if k != '@context'}
                    jsonld_data = {
                        '@context': context,
                        'graph': [object_data]
                    }
                    endpoint_instance.logger.info("Wrapped single object in graph array")
                
                endpoint_instance.logger.info("Creating JsonLdDocument")
                result = JsonLdDocument(**jsonld_data)
                endpoint_instance.logger.info(f"Created JsonLdDocument with graph length: {len(result.graph) if result.graph else 0}")
                return result
            except Exception as e:
                endpoint_instance.logger.error(f"Error in JSON-LD conversion: {e}")
                return JsonLdDocument(context={}, graph=[])
        else:
            endpoint_instance.logger.info("No VitalSigns objects returned, returning empty document")
            return JsonLdDocument(context={}, graph=[])
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting entity frames: {e}")
        return JsonLdDocument(context={}, graph=[])


def get_entity_with_complete_graph_impl(endpoint_instance, space, graph_id: str, entity_uri: str):
    """Get entity with complete graph using hasKGGraphURI.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space: The space object containing the data store
        graph_id: Graph identifier
        entity_uri: URI of the entity to retrieve with complete graph
        
    Returns:
        EntityGraphResponse with entity and complete graph data
    """
    # Step 1: Get the entity itself
    entity_response = endpoint_instance._get_single_entity(space, graph_id, entity_uri)
    
    # Step 2: Get complete graph using SPARQL grouping URI retrieval
    def sparql_executor(query):
        """Execute SPARQL query and return results in expected format."""
        results = endpoint_instance._execute_sparql_query(space, query)
        if not results.get("bindings"):
            return []
        
        # Convert to expected format for GroupingURIGraphRetriever
        formatted_results = []
        for binding in results["bindings"]:
            formatted_results.append({
                'subject': binding.get("subject", {}).get("value", ""),
                'predicate': binding.get("predicate", {}).get("value", ""),
                'object': binding.get("object", {}).get("value", "")
            })
        return formatted_results
    
    # Get complete entity graph triples
    graph_triples = endpoint_instance.graph_retriever.get_entity_graph_triples(
        entity_uri, graph_id, sparql_executor
    )
    
    if graph_triples:
        # Convert triples to JSON-LD document
        complete_graph_jsonld = endpoint_instance._convert_triples_to_jsonld(graph_triples)
        from vitalgraph.model.kgentities_model import EntityGraphResponse
        from vitalgraph.model.jsonld_model import JsonLdDocument
        return EntityGraphResponse(
            entity=entity_response.entity,
            complete_graph=JsonLdDocument(**complete_graph_jsonld)
        )
    else:
        # No complete graph found
        return entity_response


def get_single_entity_impl(endpoint_instance, space, graph_id: str, entity_uri: str):
    """Get just the entity itself (standard retrieval).
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space: The space object containing the data store
        graph_id: Graph identifier
        entity_uri: URI of the entity to retrieve
        
    Returns:
        EntityGraphResponse with entity data (no complete graph)
    """
    # Query for entity data
    if graph_id:
        query = f"""
        SELECT ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                <{entity_uri}> ?predicate ?object .
            }}
        }}
        """
    else:
        query = f"""
        SELECT ?predicate ?object WHERE {{
            <{entity_uri}> ?predicate ?object .
        }}
        """
    
    results = endpoint_instance._execute_sparql_query(space, query)
    
    if not results.get("bindings"):
        # Entity not found
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        from vitalgraph.model.kgentities_model import EntityGraphResponse
        from vitalgraph.model.jsonld_model import JsonLdDocument
        empty_jsonld = GraphObject.to_jsonld_list([])
        return EntityGraphResponse(
            entity=JsonLdDocument(**empty_jsonld),
            complete_graph=None
        )
    
    # Convert SPARQL results to triples format
    triples = []
    for binding in results["bindings"]:
        predicate = binding.get("predicate", {}).get("value", "")
        obj_value = binding.get("object", {}).get("value", "")
        if predicate and obj_value:
            # Format triples as RDF N-Triples strings for VitalSigns
            # Clean predicate URI - remove angle brackets if present
            clean_predicate = predicate.strip('<>')
            clean_obj = obj_value.strip('<>')
            
            triple_str = f"<{entity_uri}> <{clean_predicate}> "
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            if validate_rfc3986(clean_obj, rule='URI'):
                triple_str += f"<{clean_obj}> ."
            else:
                # Remove any existing quotes before adding new ones
                clean_literal = clean_obj.strip('"')
                triple_str += f'"{clean_literal}" .'
            triples.append(triple_str)
    
    # Use VitalSigns to convert triples to proper GraphObjects
    endpoint_instance.logger.info(f"Converting {len(triples)} triples to VitalSigns objects")
    for i, triple in enumerate(triples):
        endpoint_instance.logger.info(f"Triple {i+1}: {triple}")
    vitalsigns_objects = endpoint_instance._triples_to_vitalsigns_objects(triples)
    endpoint_instance.logger.info(f"VitalSigns conversion returned {len(vitalsigns_objects) if vitalsigns_objects else 0} objects")
    
    if vitalsigns_objects:
        # Find the entity object (should be KGEntity, KGFrame, KGSlot, etc.)
        entity_object = None
        for obj in vitalsigns_objects:
            if str(obj.URI) == entity_uri:
                entity_object = obj
                break
        
        if entity_object:
            # Convert to JSON-LD using VitalSigns native functionality
            entity_jsonld = entity_object.to_jsonld()
            endpoint_instance.logger.info(f"Entity object type: {type(entity_object).__name__}")
            endpoint_instance.logger.info(f"Single entity JSON-LD keys: {list(entity_jsonld.keys())}")
            endpoint_instance.logger.info(f"Has @graph: {'@graph' in entity_jsonld}")
            endpoint_instance.logger.info(f"JSON-LD structure: {entity_jsonld}")
            
            # Check if VitalSigns returned a @graph document instead of single object
            if '@graph' in entity_jsonld and entity_jsonld['@graph']:
                # Extract the single object from the @graph array
                graph_items = entity_jsonld['@graph']
                if isinstance(graph_items, list) and len(graph_items) > 0:
                    single_object = graph_items[0]
                    # Add context if present
                    if '@context' in entity_jsonld:
                        single_object['@context'] = entity_jsonld['@context']
                    entity_jsonld = single_object
                    endpoint_instance.logger.info(f"Extracted single object from @graph: {list(single_object.keys())}")
            
            from vitalgraph.model.kgentities_model import EntityGraphResponse
            from vitalgraph.model.jsonld_model import JsonLdObject
            return EntityGraphResponse(
                entity=JsonLdObject(**entity_jsonld),
                complete_graph=None
            )
        else:
            endpoint_instance.logger.warning(f"No entity object found with URI {entity_uri} in converted objects")
    
    # Fallback to empty response
    from vital_ai_vitalsigns.model.GraphObject import GraphObject
    from vitalgraph.model.kgentities_model import EntityGraphResponse
    from vitalgraph.model.jsonld_model import JsonLdDocument
    empty_jsonld = GraphObject.to_jsonld_list([])
    return EntityGraphResponse(
        entity=JsonLdDocument(**empty_jsonld),
        complete_graph=None
    )


def get_current_entity_objects_impl(endpoint_instance, space, entity_uri: str, graph_id: str) -> list:
    """Get all current objects belonging to an entity via grouping URIs.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space: The space object containing the data store
        entity_uri: URI of the entity whose objects to retrieve
        graph_id: Graph identifier
        
    Returns:
        List of objects belonging to the entity (simplified URIPlaceholder objects)
    """
    try:
        if graph_id:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject haley:hasKGGraphURI <{entity_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
            """
        else:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                ?subject haley:hasKGGraphURI <{entity_uri}> .
                ?subject ?predicate ?object .
            }}
            """
        
        results = space.store.query(query)
        # Convert SPARQL results back to VitalSigns objects
        # This is a simplified version - in practice would need full object reconstruction
        objects = []
        subjects_seen = set()
        
        for result in results:
            subject_uri = str(result['subject'])
            if subject_uri not in subjects_seen:
                subjects_seen.add(subject_uri)
                # Create placeholder objects for URI tracking
                # In real implementation, would reconstruct full objects
                class URIPlaceholder:
                    def __init__(self, uri):
                        self.URI = uri
                objects.append(URIPlaceholder(subject_uri))
        
        return objects
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting current entity objects: {e}")
        return []


def get_kgentity_impl(endpoint_instance, space_id: str, graph_id: str, uri: str, include_entity_graph: bool = False) -> EntityGraphResponse:
    """
    Get a specific KGEntity by URI with optional complete graph using grouping URIs.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        uri: Entity URI
        include_entity_graph: If True, include complete entity graph using hasKGGraphURI
        
    Returns:
        EntityGraphResponse with entity and optional complete graph
    """
    endpoint_instance._log_method_call("get_kgentity", space_id=space_id, graph_id=graph_id, uri=uri, include_entity_graph=include_entity_graph)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            # Return empty response for non-existent space
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return EntityGraphResponse(
                entity=JsonLdDocument(**empty_jsonld),
                complete_graph=None
            )
        
        # Clean URI - handle VitalSigns property objects
        clean_uri = str(uri).strip('<>')
        
        if not include_entity_graph:
            # Standard entity retrieval - just get the entity itself
            return endpoint_instance._get_single_entity(space, graph_id, clean_uri)
        else:
            # Complete graph retrieval using hasKGGraphURI
            return endpoint_instance._get_entity_with_complete_graph(space, graph_id, clean_uri)
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting KGEntity {uri}: {e}")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return EntityGraphResponse(
            entity=JsonLdDocument(**empty_jsonld),
            complete_graph=None
        )


def get_kgentity_frames_impl(endpoint_instance, space_id: str, graph_id: str, entity_uri: Optional[str] = None, 
                           page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> Dict[str, Any]:
    """
    Get frames associated with KGEntities using pyoxigraph SPARQL queries.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        entity_uri: Optional specific entity URI
        page_size: Number of frames per page
        offset: Offset for pagination
        search: Optional search term
        
    Returns:
        Dictionary with entity frames data
    """
    endpoint_instance._log_method_call("get_kgentity_frames", space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, page_size=page_size, offset=offset, search=search)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return {"entity_frames": [], "total_count": 0}
        
        # Build SPARQL query to find frame relationships using Edge classes
        if entity_uri:
            if graph_id is None:
                # Query default graph
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?frame ?predicate ?object WHERE {{
                    ?edge a haley:Edge_hasKGFrame .
                    ?edge vital:hasEdgeSource <{entity_uri}> .
                    ?edge vital:hasEdgeDestination ?frame .
                    ?frame ?predicate ?object .
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                # Query named graph
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?frame ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge a haley:Edge_hasKGFrame .
                        ?edge vital:hasEdgeSource <{entity_uri}> .
                        ?edge vital:hasEdgeDestination ?frame .
                        ?frame ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
        else:
            if graph_id is None:
                # Query default graph
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?entity ?frame ?predicate ?object WHERE {{
                    ?entity a haley:KGEntity .
                    ?edge a haley:Edge_hasKGFrame .
                    ?edge vital:hasEdgeSource ?entity .
                    ?edge vital:hasEdgeDestination ?frame .
                    ?frame ?predicate ?object .
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                # Query named graph
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?entity ?frame ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?entity a haley:KGEntity .
                        ?edge a haley:Edge_hasKGFrame .
                        ?edge vital:hasEdgeSource ?entity .
                        ?edge vital:hasEdgeDestination ?frame .
                        ?frame ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
        
        results = endpoint_instance._execute_sparql_query(space, query)
        
        # Process results (simplified for now)
        entity_frames = []
        if results.get("bindings"):
            # Group and process frame data
            # This would need more sophisticated processing based on actual frame relationships
            entity_frames = [{"frame_uri": binding.get("frame", {}).get("value", "").strip('<>')} 
                           for binding in results["bindings"]]
        
        return {
            "entity_frames": entity_frames,
            "total_count": len(entity_frames)
        }
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting KGEntity frames: {e}")
        return {"entity_frames": [], "total_count": 0}