-- Step 2: Create indexes for the edge relationships materialized view
-- This step creates the optimal indexes for different access patterns

-- 1. Source → Destination lookups (frame → slot traversal)
CREATE INDEX CONCURRENTLY idx_edge_rel_source_dest 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (source_node_uuid, dest_node_uuid);

-- 2. Destination → Source lookups (reverse traversal)
CREATE INDEX CONCURRENTLY idx_edge_rel_dest_source 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (dest_node_uuid, source_node_uuid);

-- 3. Edge-centric lookups
CREATE INDEX CONCURRENTLY idx_edge_rel_edge_uuid 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (edge_uuid);

-- 4. Source node lookups (find all outgoing edges from a node)
CREATE INDEX CONCURRENTLY idx_edge_rel_source 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (source_node_uuid);

-- 5. Destination node lookups (find all incoming edges to a node)
CREATE INDEX CONCURRENTLY idx_edge_rel_dest 
    ON vitalgraph1__wordnet_frames__edge_relationships_mv (dest_node_uuid);

-- Show index creation status
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename = 'vitalgraph1__wordnet_frames__edge_relationships_mv'
ORDER BY indexname;
