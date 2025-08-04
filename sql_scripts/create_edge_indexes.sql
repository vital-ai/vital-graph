-- Specialized indexes to optimize edge structure queries
-- These covering indexes support the specific join patterns in edge resolution

-- Index for edge source lookups (subject + predicate + context -> object)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_edge_source_covering
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged (subject_uuid, predicate_uuid, context_uuid)
INCLUDE (object_uuid)
WHERE predicate_uuid = (
    SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
    WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
);

-- Index for edge destination lookups (subject + predicate + context -> object)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_edge_dest_covering
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged (subject_uuid, predicate_uuid, context_uuid)
INCLUDE (object_uuid)
WHERE predicate_uuid = (
    SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
    WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
);

-- Composite index for edge entities (to identify which subjects are edges)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_edge_entities
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged (context_uuid, subject_uuid)
WHERE predicate_uuid = (
    SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
    WHERE term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
) AND object_uuid = (
    SELECT term_uuid FROM vitalgraph1__wordnet_frames__term_unlogged 
    WHERE term_text = 'http://vital.ai/ontology/vital-core#Edge'
);

-- Show index creation status
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'vitalgraph1__wordnet_frames__rdf_quad_unlogged'
  AND indexname LIKE '%edge%'
ORDER BY indexname;
