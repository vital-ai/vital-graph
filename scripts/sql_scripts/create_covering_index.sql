-- Create covering index to optimize frame query performance
-- This index should help with the slot_data CTE bottleneck

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_pred_obj_ctx_subj_covering 
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged 
(predicate_uuid, object_uuid, context_uuid) 
INCLUDE (subject_uuid);

-- Also create an index optimized for the edge_structure CTE
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quad_subj_pred_ctx_obj_covering
ON vitalgraph1__wordnet_frames__rdf_quad_unlogged 
(subject_uuid, predicate_uuid, context_uuid) 
INCLUDE (object_uuid);

-- Show the indexes created
\d+ vitalgraph1__wordnet_frames__rdf_quad_unlogged
