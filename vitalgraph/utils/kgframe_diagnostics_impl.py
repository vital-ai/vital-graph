"""
KGFrame Diagnostics Implementation

This module contains diagnostic functions for KGFrame operations,
extracted from MockKGFramesEndpoint to improve code organization and maintainability.
"""


def detect_stale_triples_impl(endpoint_instance, space, graph_id: str) -> dict:
    """
    Detect stale triples and orphaned objects in the frame graph.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space: The space object containing the store
        graph_id: Graph identifier
        
    Returns:
        dict: Report of stale triples categorized by type
    """
    try:
        stale_report = {
            'orphaned_slots': [],
            'orphaned_edges': [],
            'broken_edge_references': [],
            'inconsistent_grouping_uris': [],
            'summary': {}
        }
        
        # Find orphaned slots (slots without Edge_hasKGSlot connections)
        orphaned_slots_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT DISTINCT ?slot WHERE {{
            GRAPH <{graph_id}> {{
                ?slot a ?slotType .
                FILTER(?slotType IN (haley:KGTextSlot, haley:KGIntegerSlot, haley:KGBooleanSlot, 
                                   haley:KGDoubleSlot, haley:KGChoiceSlot, haley:KGEntitySlot))
                FILTER NOT EXISTS {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeDestination ?slot .
                }}
            }}
        }}
        """
        
        orphaned_slots = space.store.query(orphaned_slots_query)
        stale_report['orphaned_slots'] = [str(result['slot']) for result in orphaned_slots]
        
        # Find orphaned edges (edges with non-existent source or destination)
        broken_edges_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT DISTINCT ?edge ?source ?destination WHERE {{
            {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeSource ?source .
                    ?edge vital:hasEdgeDestination ?destination .
                    FILTER NOT EXISTS {{ ?source a haley:KGFrame . }}
                }}
            }}
            UNION
            {{
                GRAPH <{graph_id}> {{
                    ?edge a haley:Edge_hasKGSlot .
                    ?edge vital:hasEdgeSource ?source .
                    ?edge vital:hasEdgeDestination ?destination .
                    FILTER NOT EXISTS {{ 
                        ?destination a ?slotType .
                        FILTER(?slotType IN (haley:KGTextSlot, haley:KGIntegerSlot, haley:KGBooleanSlot))
                    }}
                }}
            }}
        }}
        """
        
        broken_edges = space.store.query(broken_edges_query)
        for result in broken_edges:
            stale_report['broken_edge_references'].append({
                'edge': str(result['edge']),
                'source': str(result['source']),
                'destination': str(result['destination'])
            })
        
        # Find edges without corresponding objects
        orphaned_edges_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT DISTINCT ?edge WHERE {{
            GRAPH <{graph_id}> {{
                ?edge a haley:Edge_hasKGSlot .
                FILTER NOT EXISTS {{
                    ?edge vital:hasEdgeSource ?source .
                    ?edge vital:hasEdgeDestination ?destination .
                }}
            }}
        }}
        """
        
        orphaned_edges = space.store.query(orphaned_edges_query)
        stale_report['orphaned_edges'] = [str(result['edge']) for result in orphaned_edges]
        
        # Find objects with inconsistent grouping URIs
        inconsistent_grouping_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT DISTINCT ?object ?groupingUri WHERE {{
            GRAPH <{graph_id}> {{
                ?object haley:hasFrameGraphURI ?groupingUri .
                FILTER NOT EXISTS {{ ?groupingUri a haley:KGFrame . }}
            }}
        }}
        """
        
        inconsistent_grouping = space.store.query(inconsistent_grouping_query)
        for result in inconsistent_grouping:
            stale_report['inconsistent_grouping_uris'].append({
                'object': str(result['object']),
                'grouping_uri': str(result['groupingUri'])
            })
        
        # Generate summary
        stale_report['summary'] = {
            'total_orphaned_slots': len(stale_report['orphaned_slots']),
            'total_orphaned_edges': len(stale_report['orphaned_edges']),
            'total_broken_references': len(stale_report['broken_edge_references']),
            'total_inconsistent_grouping': len(stale_report['inconsistent_grouping_uris']),
            'has_stale_data': any([
                stale_report['orphaned_slots'],
                stale_report['orphaned_edges'],
                stale_report['broken_edge_references'],
                stale_report['inconsistent_grouping_uris']
            ])
        }
        
        if stale_report['summary']['has_stale_data']:
            endpoint_instance.logger.warning(f"Detected stale triples in graph {graph_id}: {stale_report['summary']}")
        else:
            endpoint_instance.logger.info(f"No stale triples detected in graph {graph_id}")
        
        return stale_report
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error detecting stale triples: {e}")
        return {
            'orphaned_slots': [],
            'orphaned_edges': [],
            'broken_edge_references': [],
            'inconsistent_grouping_uris': [],
            'summary': {'error': str(e)}
        }


def cleanup_stale_triples_impl(endpoint_instance, space, graph_id: str, stale_report: dict = None) -> dict:
    """
    Clean up stale triples based on detection report.
    
    Args:
        endpoint_instance: The MockKGFramesEndpoint instance (for access to methods and logger)
        space: Space object
        graph_id: Graph identifier
        stale_report: Optional pre-generated stale report
        
    Returns:
        dict: Cleanup results
    """
    try:
        if stale_report is None:
            stale_report = endpoint_instance.detect_stale_triples(space, graph_id)
        
        cleanup_results = {
            'deleted_orphaned_slots': 0,
            'deleted_orphaned_edges': 0,
            'deleted_broken_references': 0,
            'errors': []
        }
        
        # Clean up orphaned slots
        for slot_uri in stale_report['orphaned_slots']:
            try:
                delete_query = f"""
                DELETE {{
                    GRAPH <{graph_id}> {{
                        <{slot_uri}> ?predicate ?object .
                    }}
                }}
                WHERE {{
                    GRAPH <{graph_id}> {{
                        <{slot_uri}> ?predicate ?object .
                    }}
                }}
                """
                space.store.update(delete_query)
                cleanup_results['deleted_orphaned_slots'] += 1
                endpoint_instance.logger.info(f"Cleaned up orphaned slot: {slot_uri}")
            except Exception as e:
                cleanup_results['errors'].append(f"Failed to delete slot {slot_uri}: {e}")
        
        # Clean up orphaned edges
        for edge_uri in stale_report['orphaned_edges']:
            try:
                delete_query = f"""
                DELETE {{
                    GRAPH <{graph_id}> {{
                        <{edge_uri}> ?predicate ?object .
                    }}
                }}
                WHERE {{
                    GRAPH <{graph_id}> {{
                        <{edge_uri}> ?predicate ?object .
                    }}
                }}
                """
                space.store.update(delete_query)
                cleanup_results['deleted_orphaned_edges'] += 1
                endpoint_instance.logger.info(f"Cleaned up orphaned edge: {edge_uri}")
            except Exception as e:
                cleanup_results['errors'].append(f"Failed to delete edge {edge_uri}: {e}")
        
        # Clean up broken edge references
        for broken_ref in stale_report['broken_edge_references']:
            try:
                edge_uri = broken_ref['edge']
                delete_query = f"""
                DELETE {{
                    GRAPH <{graph_id}> {{
                        <{edge_uri}> ?predicate ?object .
                    }}
                }}
                WHERE {{
                    GRAPH <{graph_id}> {{
                        <{edge_uri}> ?predicate ?object .
                    }}
                }}
                """
                space.store.update(delete_query)
                cleanup_results['deleted_broken_references'] += 1
                endpoint_instance.logger.info(f"Cleaned up broken edge reference: {edge_uri}")
            except Exception as e:
                cleanup_results['errors'].append(f"Failed to delete broken reference {edge_uri}: {e}")
        
        total_cleaned = (cleanup_results['deleted_orphaned_slots'] + 
                       cleanup_results['deleted_orphaned_edges'] + 
                       cleanup_results['deleted_broken_references'])
        
        endpoint_instance.logger.info(f"Stale triple cleanup completed: {total_cleaned} items cleaned, "
                       f"{len(cleanup_results['errors'])} errors")
        
        return cleanup_results
        
    except Exception as e:
        endpoint_instance.logger.error(f"Error during stale triple cleanup: {e}")
        return {
            'deleted_orphaned_slots': 0,
            'deleted_orphaned_edges': 0,
            'deleted_broken_references': 0,
            'errors': [str(e)]
        }
