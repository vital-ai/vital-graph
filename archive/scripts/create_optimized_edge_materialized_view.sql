-- Optimized materialized view for edge relationships
-- Enables efficient frame → slot traversal and other node connections

-- Drop existing materialized view
DROP MATERIALIZED VIEW IF EXISTS vitalgraph1__wordnet_frames__edge_structure_mv CASCADE;

-- Create the optimized materialized view
CREATE MATERIALIZED VIEW vitalgraph1__wordnet_frames__edge_relationships_mv AS
SELECT 
    edge.subject_uuid as edge_uuid,
    source.object_uuid as source_node_uuid,
    dest.object_uuid as dest_node_uuid,
    -- Include edge type for additional filtering capabilities
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

-- Create optimal indexes for different access patterns

-- 1. Source → Destination lookups (frame → slot traversal)
CREATE INDEX idx_edge_rel_source_dest 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (source_node_uuid, dest_node_uuid);

-- 2. Destination → Source lookups (reverse traversal)
CREATE INDEX idx_edge_rel_dest_source 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (dest_node_uuid, source_node_uuid);

-- 3. Edge-centric lookups
CREATE INDEX idx_edge_rel_edge_uuid 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (edge_uuid);

-- 4. Source node lookups (find all outgoing edges from a node)
CREATE INDEX idx_edge_rel_source 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (source_node_uuid);

-- 5. Destination node lookups (find all incoming edges to a node)
CREATE INDEX idx_edge_rel_dest 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (dest_node_uuid);

-- 6. Edge type filtering (when edge type is available)
CREATE INDEX idx_edge_rel_type 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (edge_type_uuid) 
    WHERE edge_type_uuid IS NOT NULL;

-- 7. Composite index for type + source (typed outgoing edges)
CREATE INDEX idx_edge_rel_type_source 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (edge_type_uuid, source_node_uuid) 
    WHERE edge_type_uuid IS NOT NULL;

-- Refresh the materialized view to populate it
REFRESH MATERIALIZED VIEW vitalgraph1__wordnet_frames__edge_relationships_mv;

-- Show statistics about the optimized materialized view
SELECT 
    'Optimized Edge Relationships Materialized View Created' as status,
    COUNT(*) as total_edge_relationships,
    COUNT(DISTINCT edge_uuid) as unique_edges,
    COUNT(DISTINCT source_node_uuid) as unique_source_nodes,
    COUNT(DISTINCT dest_node_uuid) as unique_dest_nodes,
    COUNT(DISTINCT edge_type_uuid) as unique_edge_types,
    COUNT(*) FILTER (WHERE edge_type_uuid IS NOT NULL) as edges_with_type
FROM vitalgraph1__wordnet_frames__edge_relationships_mv;
