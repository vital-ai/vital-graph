-- Incremental approach to building edge relationships materialized view
-- This builds the view step by step to avoid timeouts

-- Step 1: Drop any existing views/tables
DROP MATERIALIZED VIEW IF EXISTS vitalgraph1__wordnet_frames__edge_relationships_mv CASCADE;
DROP TABLE IF EXISTS vitalgraph1__wordnet_frames__edge_relationships_temp CASCADE;

-- Step 2: Create a regular table first (faster than materialized view)
CREATE TABLE vitalgraph1__wordnet_frames__edge_relationships_temp AS
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
WHERE edge.context_uuid = constants.graph_uuid;

-- Step 3: Add indexes to the temp table
CREATE INDEX idx_temp_edge_source_dest ON vitalgraph1__wordnet_frames__edge_relationships_temp (source_node_uuid, dest_node_uuid);
CREATE INDEX idx_temp_edge_uuid ON vitalgraph1__wordnet_frames__edge_relationships_temp (edge_uuid);
CREATE INDEX idx_temp_source ON vitalgraph1__wordnet_frames__edge_relationships_temp (source_node_uuid);
CREATE INDEX idx_temp_dest ON vitalgraph1__wordnet_frames__edge_relationships_temp (dest_node_uuid);

-- Step 4: Create materialized view directly (avoiding dependency issues)
CREATE MATERIALIZED VIEW vitalgraph1__wordnet_frames__edge_relationships_mv AS
SELECT 
    edge_uuid,
    source_node_uuid,
    dest_node_uuid
FROM vitalgraph1__wordnet_frames__edge_relationships_temp;

-- Step 5: Clean up temp table first
DROP TABLE vitalgraph1__wordnet_frames__edge_relationships_temp;

-- Step 6: Create final indexes on materialized view
CREATE INDEX idx_edge_rel_source_dest ON vitalgraph1__wordnet_frames__edge_relationships_mv (source_node_uuid, dest_node_uuid);
CREATE INDEX idx_edge_rel_edge_uuid ON vitalgraph1__wordnet_frames__edge_relationships_mv (edge_uuid);
CREATE INDEX idx_edge_rel_source ON vitalgraph1__wordnet_frames__edge_relationships_mv (source_node_uuid);
CREATE INDEX idx_edge_rel_dest ON vitalgraph1__wordnet_frames__edge_relationships_mv (dest_node_uuid);

-- Step 7: Show statistics
SELECT 
    'Incremental Edge Relationships MV Created' as status,
    COUNT(*) as total_relationships,
    COUNT(DISTINCT edge_uuid) as unique_edges,
    COUNT(DISTINCT source_node_uuid) as unique_sources,
    COUNT(DISTINCT dest_node_uuid) as unique_destinations
FROM vitalgraph1__wordnet_frames__edge_relationships_mv;
