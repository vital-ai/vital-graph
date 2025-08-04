-- Simple edge optimization: Create targeted indexes for edge traversal
-- This avoids the complexity of materialized views while still optimizing edge queries

-- Index for hasEdgeSource lookups (subject + predicate + context -> object)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_edge_source_lookup
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged (subject_uuid, predicate_uuid, context_uuid)
INCLUDE (object_uuid)
WHERE predicate_uuid = (
    SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
    WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
);

-- Index for hasEdgeDestination lookups (subject + predicate + context -> object)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_edge_dest_lookup
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged (subject_uuid, predicate_uuid, context_uuid)
INCLUDE (object_uuid)
WHERE predicate_uuid = (
    SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
    WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
);

-- Index for hasEntitySlotValue lookups (optimizes slot -> entity connections)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_slot_entity_lookup
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged (subject_uuid, predicate_uuid, context_uuid)
INCLUDE (object_uuid)
WHERE predicate_uuid = (
    SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
    WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEntitySlotValue'
);

-- Show index creation status
SELECT 
    'Simple Edge Indexes Created' as status,
    COUNT(*) as total_indexes
FROM pg_indexes 
WHERE tablename = 'vitalgraph1__wordnet_frames__rdf_quad_unlogged'
  AND indexname LIKE '%edge%';
