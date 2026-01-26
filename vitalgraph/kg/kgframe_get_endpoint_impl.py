"""
KGFrame Get Operations Implementation

This module contains the implementation functions for KGFrame retrieval operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.
"""

from typing import List, Optional, Any
from vitalgraph.model.jsonld_model import JsonLdDocument


def get_frame_slots_complex_impl(endpoint_instance, space_id: str, graph_id: str, frame_uri: str, 
                       kGSlotType: str = None) -> JsonLdDocument:
    """
    Get all slots for a specific frame using /kgframes/kgslots sub-endpoint.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        frame_uri: Parent frame URI
        kGSlotType: Optional filter by slot type URN
        
    Returns:
        JsonLdDocument containing all slots for the frame
    """
    endpoint_instance._log_method_call("get_frame_slots", space_id=space_id, graph_id=graph_id, 
                         frame_uri=frame_uri, kGSlotType=kGSlotType)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            return JsonLdDocument(context={}, graph=[])
        
        # Build query for slots connected to this frame
        slot_type_filter = ""
        if kGSlotType:
            slot_type_filter = f"?slot haley:hasKGSlotType <{kGSlotType}> ."
        
        if graph_id:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?slot ?prop ?value WHERE {{
                GRAPH <{graph_id}> {{
                    # Find slots connected to frame via Edge_hasKGSlot
                    ?edge a haley:Edge_hasKGSlot ;
                          vital:hasEdgeSource <{frame_uri}> ;
                          vital:hasEdgeDestination ?slot .
                    
                    {slot_type_filter}
                    
                    # Get all properties of the slot
                    ?slot ?prop ?value .
                }}
            }}
            """
        else:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?slot ?prop ?value WHERE {{
                # Find slots connected to frame via Edge_hasKGSlot
                ?edge a haley:Edge_hasKGSlot ;
                      vital:hasEdgeSource <{frame_uri}> ;
                      vital:hasEdgeDestination ?slot .
                
                {slot_type_filter}
                
                # Get all properties of the slot
                ?slot ?prop ?value .
            }}
            """
        
        results = list(space.store.query(query))
        if not results:
            return JsonLdDocument(context={}, graph=[])
        
        # Convert results to triples format
        triples = []
        for result in results:
            slot_uri = str(result['slot'])
            prop_uri = str(result['prop'])
            
            # Properly handle pyoxigraph value objects
            value_obj = result['value']
            if hasattr(value_obj, 'value'):
                # It's a Literal - get the actual value
                value = str(value_obj.value)
            else:
                # It's a NamedNode - get the URI
                value = str(value_obj)
            
            triples.append({
                'subject': f'<{slot_uri}>',
                'predicate': f'<{prop_uri}>',
                'object': f'<{value}>' if str(value).startswith('http') else f'"{value}"'
            })
        
        # Convert triples to VitalSigns objects
        vitalsigns_objects = endpoint_instance._convert_triples_to_vitalsigns_objects(triples)
        
        if vitalsigns_objects:
            # Convert to JSON-LD
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_data = GraphObject.to_jsonld_list(vitalsigns_objects)
            return JsonLdDocument(**jsonld_data)
        else:
            return JsonLdDocument(context={}, graph=[])
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting frame slots: {e}")
        return JsonLdDocument(context={}, graph=[])


def get_kgframe_impl(endpoint_instance, space_id: str, graph_id: str, uri: str, include_frame_graph: bool = False) -> JsonLdDocument:
    """
    Get a specific KGFrame by URI with optional complete graph using pyoxigraph SPARQL query.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        uri: KGFrame URI
        include_frame_graph: If True, include complete frame graph (frames + slots + frame-to-frame edges)
        
    Returns:
        JsonLdDocument with VitalSigns native JSON-LD conversion
    """
    endpoint_instance._log_method_call("get_kgframe", space_id=space_id, graph_id=graph_id, uri=uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            # Return empty document for non-existent space
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
        
        # Clean URI - handle VitalSigns property objects
        clean_uri = str(uri).strip('<>')
        
        if not include_frame_graph:
            # Standard frame retrieval - just get the frame itself
            return endpoint_instance._get_single_frame(space, graph_id, clean_uri)
        else:
            # Complete frame graph retrieval using hasFrameGraphURI
            return endpoint_instance._get_frame_with_complete_graph(space, graph_id, clean_uri)
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting KGFrame {uri}: {e}")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return JsonLdDocument(**empty_jsonld)


def get_kgframe_with_slots_impl(endpoint_instance, space_id: str, graph_id: str, uri: str) -> JsonLdDocument:
    """
    Get a specific KGFrame with its associated slots using pyoxigraph SPARQL queries.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        uri: Frame URI
        
    Returns:
        JsonLdDocument containing frame and its slots with VitalSigns native JSON-LD conversion
    """
    endpoint_instance._log_method_call("get_kgframe_with_slots", space_id=space_id, graph_id=graph_id, uri=uri)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
        
        # Clean URI - handle VitalSigns property objects
        clean_uri = str(uri).strip('<>')
        
        # Query for frame and its slots
        if graph_id:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        <{clean_uri}> ?predicate ?object .
                        BIND(<{clean_uri}> as ?subject)
                    }}
                    UNION
                    {{
                        ?subject haley:kGFrameSlotFrame <{clean_uri}> .
                        ?subject ?predicate ?object .
                    }}
                }}
            }}
            """
        else:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?subject ?predicate ?object WHERE {{
                {{
                    <{clean_uri}> ?predicate ?object .
                    BIND(<{clean_uri}> as ?subject)
                }}
                UNION
                {{
                    ?subject haley:kGFrameSlotFrame <{clean_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
            """
        
        results = endpoint_instance._execute_sparql_query(space, query)
        
        if not results.get("bindings"):
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
        
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
        all_objects = []
        for subject_uri, properties in subjects_data.items():
            if subject_uri == clean_uri:
                # This is the frame
                kgframe_vitaltype = endpoint_instance._get_vitaltype_uri("KGFrame")
                obj = endpoint_instance._convert_sparql_to_vitalsigns_object(kgframe_vitaltype, subject_uri, properties)
            else:
                # This is a slot
                kgslot_vitaltype = endpoint_instance._get_vitaltype_uri("KGSlot")
                obj = endpoint_instance._convert_sparql_to_vitalsigns_object(kgslot_vitaltype, subject_uri, properties)
            
            if obj:
                all_objects.append(obj)
        
        # Convert to JSON-LD document using VitalSigns
        objects_jsonld = endpoint_instance._objects_to_jsonld_document(all_objects)
        return JsonLdDocument(**objects_jsonld)
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting KGFrame with slots {uri}: {e}")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return JsonLdDocument(**empty_jsonld)


def get_single_frame_impl(endpoint_instance, space, graph_id: str, frame_uri: str) -> JsonLdDocument:
    """Get just the frame itself (standard retrieval)."""
    try:
        # Query for frame data
        if graph_id:
            query = f"""
            SELECT ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?predicate ?object .
                }}
            }}
            """
        else:
            query = f"""
            SELECT ?predicate ?object WHERE {{
                <{frame_uri}> ?predicate ?object .
            }}
            """
        
        endpoint_instance.logger.info(f"DEBUG _get_single_frame: Looking for frame {frame_uri}")
        results = endpoint_instance._execute_sparql_query(space, query)
        endpoint_instance.logger.info(f"DEBUG _get_single_frame: Query returned {len(results.get('bindings', []))} results")
        
        if not results.get("bindings"):
            # Frame not found - let's check if it exists with different URI format
            if graph_id:
                alt_query = f"""
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject ?predicate ?object .
                        FILTER(CONTAINS(STR(?subject), "KGFrame"))
                    }}
                }}
                """
            else:
                alt_query = f"""
                SELECT ?subject ?predicate ?object WHERE {{
                    ?subject ?predicate ?object .
                    FILTER(CONTAINS(STR(?subject), "KGFrame"))
                }}
                """
            alt_results = endpoint_instance._execute_sparql_query(space, alt_query)
            endpoint_instance.logger.info(f"DEBUG _get_single_frame: Alternative search found {len(alt_results.get('bindings', []))} frame-related triples")
            
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
        
        # Reconstruct frame properties
        properties = {}
        endpoint_instance.logger.info(f"DEBUG _get_single_frame: Processing {len(results['bindings'])} property bindings")
        for binding in results["bindings"]:
            predicate = binding.get("predicate", {}).get("value", "")
            obj_value = binding.get("object", {}).get("value", "")
            
            # Clean angle brackets
            if predicate.startswith('<') and predicate.endswith('>'):
                predicate = predicate[1:-1]
            if obj_value.startswith('<') and obj_value.endswith('>'):
                obj_value = obj_value[1:-1]
                
            properties[predicate] = obj_value
            endpoint_instance.logger.info(f"DEBUG _get_single_frame: Property {predicate} = {obj_value}")
        
        # Get vitaltype for frame conversion
        vitaltype_uri = properties.get("http://vital.ai/ontology/vital-core#vitaltype", "")
        endpoint_instance.logger.info(f"DEBUG _get_single_frame: Found vitaltype {vitaltype_uri}")
        if not vitaltype_uri:
            vitaltype_uri = endpoint_instance._get_vitaltype_uri("KGFrame")
            endpoint_instance.logger.info(f"DEBUG _get_single_frame: Using fallback vitaltype {vitaltype_uri}")
        
        # Convert to VitalSigns KGFrame object
        endpoint_instance.logger.info(f"DEBUG _get_single_frame: Converting to VitalSigns object with URI {frame_uri}")
        frame = endpoint_instance._convert_sparql_to_vitalsigns_object(vitaltype_uri, frame_uri, properties)
        
        if frame:
            endpoint_instance.logger.info(f"DEBUG _get_single_frame: Successfully created frame object {frame.URI}")
            # Convert to JSON-LD using VitalSigns native functionality with proper @graph structure
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            single_frame_jsonld = GraphObject.to_jsonld_list([frame])
            
            # Create proper @graph structure for JsonLdDocument
            if '@context' in single_frame_jsonld:
                # Single object format - wrap in @graph array
                frame_jsonld = {
                    '@context': single_frame_jsonld['@context'],
                    '@graph': [single_frame_jsonld]
                }
            else:
                # Already in @graph format
                frame_jsonld = single_frame_jsonld
            
            endpoint_instance.logger.info(f"DEBUG _get_single_frame: Final JSON-LD has @graph: {'@graph' in frame_jsonld}")
            return JsonLdDocument(**frame_jsonld)
        else:
            endpoint_instance.logger.info(f"DEBUG _get_single_frame: Failed to create frame object")
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
            
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting single frame {frame_uri}: {e}")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return JsonLdDocument(**empty_jsonld)


def get_frame_with_complete_graph_impl(endpoint_instance, space, graph_id: str, frame_uri: str) -> JsonLdDocument:
    """Get frame with complete graph using hasFrameGraphURI."""
    try:
        # Step 1: Get the frame itself
        single_frame_response = endpoint_instance._get_single_frame(space, graph_id, frame_uri)
        
        # Step 2: Get complete frame graph using hasFrameGraphURI grouping URI
        if graph_id:
            complete_graph_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject haley:hasFrameGraphURI <{frame_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
            """
        else:
            complete_graph_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                ?subject haley:hasFrameGraphURI <{frame_uri}> .
                ?subject ?predicate ?object .
            }}
            """
        
        endpoint_instance.logger.info(f"DEBUG _get_frame_with_complete_graph: Querying complete frame graph for {frame_uri}")
        results = endpoint_instance._execute_sparql_query(space, complete_graph_query)
        endpoint_instance.logger.info(f"DEBUG _get_frame_with_complete_graph: Found {len(results.get('bindings', []))} triples in complete graph")
        
        if results.get("bindings"):
            # Convert SPARQL results to triples format
            triples = []
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject and predicate and obj_value:
                    triples.append({
                        'subject': subject,
                        'predicate': predicate,
                        'object': obj_value
                    })
            
            # Convert triples to VitalSigns objects
            vitalsigns_objects = endpoint_instance._convert_triples_to_vitalsigns_objects(triples)
            
            if vitalsigns_objects:
                # Convert to JSON-LD using VitalSigns
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                complete_graph_jsonld = GraphObject.to_jsonld_list(vitalsigns_objects)
                
                endpoint_instance.logger.info(f"DEBUG _get_frame_with_complete_graph: Successfully created complete graph with {len(vitalsigns_objects)} objects")
                return JsonLdDocument(**complete_graph_jsonld)
        
        # Fallback to single frame if no complete graph found
        endpoint_instance.logger.info(f"DEBUG _get_frame_with_complete_graph: No complete graph found, returning single frame")
        return single_frame_response
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error getting frame with complete graph {frame_uri}: {e}")
        # Fallback to single frame on error
        return endpoint_instance._get_single_frame(space, graph_id, frame_uri)


def get_current_frame_objects_impl(endpoint_instance, space, frame_uri: str, graph_id: str) -> list:
    """Get all current objects belonging to a frame via grouping URIs."""
    try:
        if graph_id:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject haley:hasFrameGraphURI <{frame_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
            """
        else:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT DISTINCT ?subject ?predicate ?object WHERE {{
                ?subject haley:hasFrameGraphURI <{frame_uri}> .
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
        endpoint_instance.logger.error(f"Error getting current frame objects: {e}")
        return []