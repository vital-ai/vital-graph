-- SQL Scripts to Find and Clean Up Unused Terms in VitalGraph PostgreSQL Database
-- 
-- These scripts identify terms in the term table that are not referenced by any RDF quad
-- in subject, predicate, object, or context positions.
--
-- Replace {space_prefix} with your actual table prefix (e.g., 'vitalgraph1__space_test')

-- =============================================================================
-- APPROACH 1: Single Query with LEFT JOIN (Most Efficient for Small-Medium Datasets)
-- =============================================================================

-- Find unused terms using LEFT JOIN approach
-- This is typically the most efficient for datasets where unused terms are a small percentage
SELECT 
    t.term_uuid,
    t.term_text,
    t.term_type,
    t.created_time
FROM {space_prefix}__term_unlogged t
LEFT JOIN (
    -- Get all unique UUIDs referenced in RDF quads
    SELECT subject_uuid AS referenced_uuid FROM {space_prefix}__rdf_quad_unlogged
    UNION
    SELECT predicate_uuid FROM {space_prefix}__rdf_quad_unlogged  
    UNION
    SELECT object_uuid FROM {space_prefix}__rdf_quad_unlogged
    UNION
    SELECT context_uuid FROM {space_prefix}__rdf_quad_unlogged
) refs ON t.term_uuid = refs.referenced_uuid
WHERE refs.referenced_uuid IS NULL
ORDER BY t.created_time DESC;

-- =============================================================================
-- APPROACH 2: NOT EXISTS Subqueries (Good for Large Datasets with Many Unused Terms)
-- =============================================================================

-- Find unused terms using NOT EXISTS approach
-- This can be more efficient when there are many unused terms
SELECT 
    t.term_uuid,
    t.term_text,
    t.term_type,
    t.created_time
FROM {space_prefix}__term_unlogged t
WHERE NOT EXISTS (
    SELECT 1 FROM {space_prefix}__rdf_quad_unlogged q 
    WHERE q.subject_uuid = t.term_uuid
       OR q.predicate_uuid = t.term_uuid
       OR q.object_uuid = t.term_uuid
       OR q.context_uuid = t.term_uuid
)
ORDER BY t.created_time DESC;

-- =============================================================================
-- APPROACH 3: Multi-Pass Analysis (Best for Very Large Datasets)
-- =============================================================================

-- Step 1: Create temporary table with all referenced UUIDs
CREATE TEMP TABLE temp_referenced_uuids AS
SELECT DISTINCT subject_uuid AS uuid FROM {space_prefix}__rdf_quad_unlogged
UNION
SELECT DISTINCT predicate_uuid FROM {space_prefix}__rdf_quad_unlogged
UNION  
SELECT DISTINCT object_uuid FROM {space_prefix}__rdf_quad_unlogged
UNION
SELECT DISTINCT context_uuid FROM {space_prefix}__rdf_quad_unlogged;

-- Create index on temp table for fast lookups
CREATE INDEX idx_temp_referenced_uuids ON temp_referenced_uuids (uuid);

-- Step 2: Find unused terms by comparing against temp table
SELECT 
    t.term_uuid,
    t.term_text,
    t.term_type,
    t.created_time
FROM {space_prefix}__term_unlogged t
LEFT JOIN temp_referenced_uuids r ON t.term_uuid = r.uuid
WHERE r.uuid IS NULL
ORDER BY t.created_time DESC;

-- Clean up temp table
DROP TABLE temp_referenced_uuids;

-- =============================================================================
-- APPROACH 4: Statistics and Analysis Queries
-- =============================================================================

-- Get counts for analysis before cleanup
SELECT 
    'Total Terms' as metric,
    COUNT(*) as count
FROM {space_prefix}__term_unlogged
UNION ALL
SELECT 
    'Total Quads' as metric,
    COUNT(*) as count  
FROM {space_prefix}__rdf_quad_unlogged
UNION ALL
SELECT 
    'Unique Referenced Terms' as metric,
    COUNT(DISTINCT uuid) as count
FROM (
    SELECT subject_uuid AS uuid FROM {space_prefix}__rdf_quad_unlogged
    UNION
    SELECT predicate_uuid FROM {space_prefix}__rdf_quad_unlogged
    UNION
    SELECT object_uuid FROM {space_prefix}__rdf_quad_unlogged  
    UNION
    SELECT context_uuid FROM {space_prefix}__rdf_quad_unlogged
) refs
UNION ALL
SELECT 
    'Unused Terms (Estimate)' as metric,
    (SELECT COUNT(*) FROM {space_prefix}__term_unlogged) - 
    (SELECT COUNT(DISTINCT uuid) FROM (
        SELECT subject_uuid AS uuid FROM {space_prefix}__rdf_quad_unlogged
        UNION
        SELECT predicate_uuid FROM {space_prefix}__rdf_quad_unlogged
        UNION
        SELECT object_uuid FROM {space_prefix}__rdf_quad_unlogged
        UNION  
        SELECT context_uuid FROM {space_prefix}__rdf_quad_unlogged
    ) refs) as count;

-- Breakdown by term type
SELECT 
    t.term_type,
    CASE 
        WHEN t.term_type = 'U' THEN 'URI'
        WHEN t.term_type = 'L' THEN 'Literal' 
        WHEN t.term_type = 'B' THEN 'Blank Node'
        WHEN t.term_type = 'G' THEN 'Graph'
        ELSE 'Unknown'
    END as term_type_name,
    COUNT(*) as total_terms,
    COUNT(r.uuid) as referenced_terms,
    COUNT(*) - COUNT(r.uuid) as unused_terms
FROM {space_prefix}__term_unlogged t
LEFT JOIN (
    SELECT DISTINCT subject_uuid AS uuid FROM {space_prefix}__rdf_quad_unlogged
    UNION
    SELECT DISTINCT predicate_uuid FROM {space_prefix}__rdf_quad_unlogged
    UNION
    SELECT DISTINCT object_uuid FROM {space_prefix}__rdf_quad_unlogged
    UNION
    SELECT DISTINCT context_uuid FROM {space_prefix}__rdf_quad_unlogged
) r ON t.term_uuid = r.uuid
GROUP BY t.term_type
ORDER BY t.term_type;

-- =============================================================================
-- CLEANUP OPERATIONS (Use with Caution!)
-- =============================================================================

-- Count unused terms before deletion (safety check)
SELECT COUNT(*) as unused_terms_count
FROM {space_prefix}__term_unlogged t
WHERE NOT EXISTS (
    SELECT 1 FROM {space_prefix}__rdf_quad_unlogged q 
    WHERE q.subject_uuid = t.term_uuid
       OR q.predicate_uuid = t.term_uuid
       OR q.object_uuid = t.term_uuid
       OR q.context_uuid = t.term_uuid
);

-- DANGER: Delete unused terms (BACKUP YOUR DATA FIRST!)
-- Uncomment only when you're sure you want to delete
/*
DELETE FROM {space_prefix}__term_unlogged t
WHERE NOT EXISTS (
    SELECT 1 FROM {space_prefix}__rdf_quad_unlogged q 
    WHERE q.subject_uuid = t.term_uuid
       OR q.predicate_uuid = t.term_uuid
       OR q.object_uuid = t.term_uuid
       OR q.context_uuid = t.term_uuid
);
*/

-- =============================================================================
-- PERFORMANCE OPTIMIZATION QUERIES
-- =============================================================================

-- Check if indexes exist for optimal performance
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename IN ('{space_prefix}__term_unlogged', '{space_prefix}__rdf_quad_unlogged')
ORDER BY tablename, indexname;

-- Analyze table statistics for query planning
ANALYZE {space_prefix}__term_unlogged;
ANALYZE {space_prefix}__rdf_quad_unlogged;

-- =============================================================================
-- USAGE INSTRUCTIONS
-- =============================================================================

/*
USAGE INSTRUCTIONS:

1. Replace {space_prefix} with your actual table prefix throughout all queries
   Example: 'vitalgraph1__wordnet_space' 

2. Choose the appropriate approach based on your dataset size:
   - Small datasets (< 1M terms): Use Approach 1 (LEFT JOIN)
   - Medium datasets (1M-10M terms): Use Approach 2 (NOT EXISTS) 
   - Large datasets (> 10M terms): Use Approach 3 (Multi-pass)

3. Always run the statistics queries first to understand your data

4. Test with LIMIT clauses before running full queries:
   Add "LIMIT 100" to any SELECT query for testing

5. BACKUP YOUR DATABASE before running any DELETE operations

6. Monitor query performance with EXPLAIN ANALYZE:
   Add "EXPLAIN ANALYZE" before any SELECT query

Example for a specific space:
   Replace {space_prefix} with: vitalgraph1__wordnet_space
*/
