-- Materialized view to optimize edge structure queries
-- This pre-computes edge -> source/destination relationships

-- Create the materialized view
CREATE MATERIALIZED VIEW IF NOT EXISTS vitalgraph1__wordnet_frames__edge_structure_mv AS
SELECT 
    edge.subject_uuid as edge_uuid,
    source.object_uuid as source_node_uuid,
    dest.object_uuid as dest_node_uuid
FROM (
    SELECT 
        t1.term_uuid as has_edge_source_uuid,
        t2.term_uuid as has_edge_destination_uuid,
        t3.term_uuid as graph_uuid
    FROM vitalgraph1__wordnet_frames__term_unlogged t1,
         vitalgraph1__wordnet_frames__term_unlogged t2,
         vitalgraph1__wordnet_frames__term_unlogged t3
    WHERE t1.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
      AND t2.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
      AND t3.term_text = 'http://vital.ai/graph/kgwordnetframes'
) ep
CROSS JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged edge
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged source 
    ON source.subject_uuid = edge.subject_uuid
    AND source.predicate_uuid = ep.has_edge_source_uuid
    AND source.context_uuid = ep.graph_uuid
JOIN vitalgraph1__wordnet_frames__rdf_quad_unlogged dest 
    ON dest.subject_uuid = edge.subject_uuid
    AND dest.predicate_uuid = ep.has_edge_destination_uuid
    AND dest.context_uuid = ep.graph_uuid
WHERE edge.context_uuid = ep.graph_uuid;

-- Create indexes on the materialized view for fast lookups
CREATE INDEX IF NOT EXISTS idx_edge_structure_mv_edge_uuid 
    ON vitalgraph1__wordnet_frames__edge_structure_mv (edge_uuid);

CREATE INDEX IF NOT EXISTS idx_edge_structure_mv_source_node 
    ON vitalgraph1__wordnet_frames__edge_structure_mv (source_node_uuid);

CREATE INDEX IF NOT EXISTS idx_edge_structure_mv_dest_node 
    ON vitalgraph1__wordnet_frames__edge_structure_mv (dest_node_uuid);

-- Create a composite index for source->dest lookups
CREATE INDEX IF NOT EXISTS idx_edge_structure_mv_source_dest 
    ON vitalgraph1__wordnet_frames__edge_structure_mv (source_node_uuid, dest_node_uuid);

-- Refresh the materialized view to populate it
REFRESH MATERIALIZED VIEW vitalgraph1__wordnet_frames__edge_structure_mv;

-- Show statistics
SELECT 
    'Edge Structure Materialized View Created' as status,
    COUNT(*) as total_edges,
    COUNT(DISTINCT source_node_uuid) as unique_source_nodes,
    COUNT(DISTINCT dest_node_uuid) as unique_dest_nodes
FROM vitalgraph1__wordnet_frames__edge_structure_mv;
