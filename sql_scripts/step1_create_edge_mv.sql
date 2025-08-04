-- Step 1: Create the optimized edge relationships materialized view
-- This step only creates the view without indexes

CREATE MATERIALIZED VIEW vitalgraph1__wordnet_frames__edge_relationships_mv AS
SELECT 
    edge.subject_uuid as edge_uuid,
    source.object_uuid as source_node_uuid,
    dest.object_uuid as dest_node_uuid,
    edge_type.object_uuid as edge_type_uuid
FROM (
    SELECT 
        t1.term_uuid as has_edge_source_uuid,
        t2.term_uuid as has_edge_destination_uuid,
        t3.term_uuid as graph_uuid,
        t4.term_uuid as rdf_type_uuid
    FROM vitalgraph1__wordnet_frames__term_unlogged t1,
         vitalgraph1__wordnet_frames__term_unlogged t2,
         vitalgraph1__wordnet_frames__term_unlogged t3,
         vitalgraph1__wordnet_frames__term_unlogged t4
    WHERE t1.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
      AND t2.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
      AND t3.term_text = 'http://vital.ai/graph/kgwordnetframes'
      AND t4.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
) constants
CROSS JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged edge
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged source 
    ON source.subject_uuid = edge.subject_uuid
    AND source.predicate_uuid = constants.has_edge_source_uuid
    AND source.context_uuid = constants.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged dest 
    ON dest.subject_uuid = edge.subject_uuid
    AND dest.predicate_uuid = constants.has_edge_destination_uuid
    AND dest.context_uuid = constants.graph_uuid
LEFT JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged edge_type
    ON edge_type.subject_uuid = edge.subject_uuid
    AND edge_type.predicate_uuid = constants.rdf_type_uuid
    AND edge_type.context_uuid = constants.graph_uuid
WHERE edge.context_uuid = constants.graph_uuid;

-- Show basic statistics
SELECT 
    'Edge Relationships Materialized View Created' as status,
    COUNT(*) as total_relationships,
    COUNT(DISTINCT edge_uuid) as unique_edges,
    COUNT(DISTINCT source_node_uuid) as unique_sources,
    COUNT(DISTINCT dest_node_uuid) as unique_destinations
FROM vitalgraph1__wordnet_frames__edge_relationships_mv;
