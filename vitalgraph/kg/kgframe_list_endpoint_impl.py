"""
KGFrame List Operations Implementation

This module contains the implementation functions for KGFrame listing operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.
"""

from typing import Optional
from vitalgraph.model.kgframes_model import FramesResponse
from vitalgraph.model.jsonld_model import JsonLdDocument


def list_kgframes_impl(endpoint_instance, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> FramesResponse:
    """
    List KGFrames with pagination and optional search using pyoxigraph SPARQL queries.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        page_size: Number of frames per page
        offset: Offset for pagination
        search: Optional search term
        
    Returns:
        FramesResponse with VitalSigns native JSON-LD document
    """
    endpoint_instance._log_method_call("list_kgframes", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, search=search)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            # Return empty response for non-existent space
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return FramesResponse(
                frames=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
        
        # Get KGFrame vitaltype URI
        kgframe_vitaltype = endpoint_instance._get_vitaltype_uri("KGFrame")
        
        # Build SPARQL query with optional search
        if search:
            if graph_id:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgframe_vitaltype}> .
                        ?subject ?predicate ?object .
                        ?subject vital:hasName ?name .
                        FILTER(CONTAINS(LCASE(?name), LCASE("{search}")))
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    ?subject a <{kgframe_vitaltype}> .
                    ?subject ?predicate ?object .
                    ?subject vital:hasName ?name .
                    FILTER(CONTAINS(LCASE(?name), LCASE("{search}")))
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
        else:
            if graph_id:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgframe_vitaltype}> .
                        ?subject ?predicate ?object .
                    }}
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
            else:
                query = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    ?subject a <{kgframe_vitaltype}> .
                    ?subject ?predicate ?object .
                }}
                LIMIT {page_size}
                OFFSET {offset}
                """
        
        # Execute query
        results = endpoint_instance._execute_sparql_query(space, query)
        
        if not results.get("bindings"):
            # No results found
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return FramesResponse(
                frames=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
        
        # Group results by subject to reconstruct frames
        subjects_data = {}
        for binding in results["bindings"]:
            subject = binding.get("subject", {}).get("value", "")
            predicate = binding.get("predicate", {}).get("value", "")
            obj_value = binding.get("object", {}).get("value", "")
            
            if subject not in subjects_data:
                subjects_data[subject] = {}
            
            subjects_data[subject][predicate] = obj_value
        
        # Convert to VitalSigns KGFrame objects
        frames = []
        for subject_uri, properties in subjects_data.items():
            frame = endpoint_instance._convert_sparql_to_vitalsigns_object(kgframe_vitaltype, subject_uri, properties)
            if frame:
                frames.append(frame)
        
        # Get total count (separate query)
        if graph_id:
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject a <{kgframe_vitaltype}> .
                }}
            }}
            """
        else:
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                ?subject a <{kgframe_vitaltype}> .
            }}
            """
        
        count_results = endpoint_instance._execute_sparql_query(space, count_query)
        total_count = 0
        if count_results.get("bindings"):
            count_value = count_results["bindings"][0].get("count", {}).get("value", "0")
            # Handle typed literals like "3"^^<http://www.w3.org/2001/XMLSchema#integer>
            if isinstance(count_value, str) and "^^" in count_value:
                count_value = count_value.split("^^")[0].strip('"')
            total_count = int(count_value)
        
        # Convert to JSON-LD document using VitalSigns
        frames_jsonld = endpoint_instance._objects_to_jsonld_document(frames)
        
        return FramesResponse(
            frames=JsonLdDocument(**frames_jsonld),
            total_count=total_count,
            page_size=page_size,
            offset=offset
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error listing KGFrames: {e}")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return FramesResponse(
            frames=JsonLdDocument(**empty_jsonld),
            total_count=0,
            page_size=page_size,
            offset=offset
        )
