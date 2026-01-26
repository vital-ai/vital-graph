"""
KGEntity List Endpoint Implementation

This module contains the implementation functions for KGEntity list operations
that have been extracted from MockKGEntitiesEndpoint for better code organization.
"""

from typing import Optional, Dict, Any
from vitalgraph.model.kgentities_model import EntitiesResponse, EntitiesGraphResponse
from vitalgraph.model.jsonld_model import JsonLdDocument


def list_kgentities_impl(endpoint_instance, space_id: str, graph_id: str, page_size: int = 10, 
                        offset: int = 0, search: Optional[str] = None, include_entity_graph: bool = False) -> EntitiesResponse:
    """
    List KGEntities with pagination and optional search using pyoxigraph SPARQL queries.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        page_size: Number of entities per page
        offset: Offset for pagination
        search: Optional search term
        include_entity_graph: If True, include complete entity graphs with frames and slots
        
    Returns:
        EntitiesResponse with VitalSigns native JSON-LD document
    """
    endpoint_instance._log_method_call("list_kgentities", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, search=search)
    
    try:
        # Get space from space manager
        space = endpoint_instance.space_manager.get_space(space_id)
        if not space:
            # Return empty response for non-existent space
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_jsonld = GraphObject.to_jsonld_list([])
            return EntitiesResponse(
                entities=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
        
        # Get KGEntity vitaltype URI
        kgentity_vitaltype = endpoint_instance._get_vitaltype_uri("KGEntity")
        
        # Build SPARQL query with optional search
        if search:
            if graph_id:
                query = f"""
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                
                SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        ?subject a <{kgentity_vitaltype}> .
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
                    ?subject a <{kgentity_vitaltype}> .
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
                        ?subject a <{kgentity_vitaltype}> .
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
                    ?subject a <{kgentity_vitaltype}> .
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
            return EntitiesResponse(
                entities=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
        
        # Group results by subject to reconstruct entities
        subjects_data = {}
        for binding in results["bindings"]:
            subject = binding.get("subject", {}).get("value", "")
            predicate = binding.get("predicate", {}).get("value", "")
            obj_value = binding.get("object", {}).get("value", "")
            
            if subject not in subjects_data:
                subjects_data[subject] = {}
            
            subjects_data[subject][predicate] = obj_value
        
        # Convert to VitalSigns KGEntity objects
        entities = []
        for subject_uri, properties in subjects_data.items():
            entity = endpoint_instance._convert_sparql_to_vitalsigns_object(kgentity_vitaltype, subject_uri, properties)
            if entity:
                entities.append(entity)
        
        # Get total count (separate query)
        if graph_id:
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject a <{kgentity_vitaltype}> .
                }}
            }}
            """
        else:
            count_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                ?subject a <{kgentity_vitaltype}> .
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
        entities_jsonld = endpoint_instance._objects_to_jsonld_document(entities)
        
        return EntitiesResponse(
            entities=JsonLdDocument(**entities_jsonld),
            total_count=total_count,
            page_size=page_size,
            offset=offset
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error listing KGEntities: {e}")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return EntitiesResponse(
            entities=JsonLdDocument(**empty_jsonld),
            total_count=0,
            page_size=page_size,
            offset=offset
        )


def list_kgentities_with_graphs_impl(endpoint_instance, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                                   search: Optional[str] = None, include_entity_graphs: bool = False) -> EntitiesGraphResponse:
    """
    List KGEntities with optional complete graphs.
    
    Args:
        endpoint_instance: The MockKGEntitiesEndpoint instance (for access to methods and logger)
        space_id: Space identifier
        graph_id: Graph identifier
        page_size: Number of items per page
        offset: Offset for pagination
        search: Optional search term
        include_entity_graphs: If True, include complete entity graphs for all entities
        
    Returns:
        EntitiesGraphResponse containing entities and optional complete graphs
    """
    from vitalgraph.model.kgentities_model import EntitiesGraphResponse
    from vitalgraph.model.jsonld_model import JsonLdDocument
    
    endpoint_instance._log_method_call("list_kgentities_with_graphs", space_id=space_id, graph_id=graph_id, 
                         page_size=page_size, offset=offset, search=search, include_entity_graphs=include_entity_graphs)
    
    try:
        # Get basic entity list
        entities_response = endpoint_instance.list_kgentities(space_id, graph_id, page_size, offset, search)
        
        if not include_entity_graphs:
            # Return standard response without complete graphs
            return EntitiesGraphResponse(
                entities=entities_response.entities,
                total_count=entities_response.total_count,
                page_size=entities_response.page_size,
                offset=entities_response.offset,
                complete_graphs=None
            )
        
        # Get complete graphs for all entities
        # This is a simplified implementation - in practice, this would be optimized
        complete_graphs = {}
        
        # Extract entity URIs from the entities response
        # This would need proper JSON-LD parsing in a real implementation
        # For now, we'll return the basic response
        
        return EntitiesGraphResponse(
            entities=entities_response.entities,
            total_count=entities_response.total_count,
            page_size=entities_response.page_size,
            offset=entities_response.offset,
            complete_graphs=complete_graphs if complete_graphs else None
        )
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error listing entities with graphs: {e}")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        empty_jsonld = GraphObject.to_jsonld_list([])
        return EntitiesGraphResponse(
            entities=JsonLdDocument(**empty_jsonld),
            total_count=0,
            page_size=page_size,
            offset=offset,
            complete_graphs=None
        )
