-- Fix missing indexes on temporary import tables that are causing server blocking
-- These tables contain the actual data being queried

-- Find the active temporary tables with data
-- Based on our analysis, the main tables are:
-- temp_quad_import_partition_import_1756707271 (8.5M rows)
-- temp_term_import_partition_import_1756707271 (3.3M rows)

-- Add critical indexes to the temporary quad table
CREATE INDEX CONCURRENTLY IF NOT EXISTS temp_quad_import_partition_import_1756707271_subject_uuid_idx 
    ON temp_quad_import_partition_import_1756707271 (subject_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS temp_quad_import_partition_import_1756707271_predicate_uuid_idx 
    ON temp_quad_import_partition_import_1756707271 (predicate_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS temp_quad_import_partition_import_1756707271_object_uuid_idx 
    ON temp_quad_import_partition_import_1756707271 (object_uuid);

-- Add critical indexes to the temporary term table
CREATE INDEX CONCURRENTLY IF NOT EXISTS temp_term_import_partition_import_1756707271_term_uuid_idx 
    ON temp_term_import_partition_import_1756707271 (term_uuid);

CREATE INDEX CONCURRENTLY IF NOT EXISTS temp_term_import_partition_import_1756707271_term_text_idx 
    ON temp_term_import_partition_import_1756707271 (term_text);

-- Composite index for term lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS temp_term_import_partition_import_1756707271_text_type_idx 
    ON temp_term_import_partition_import_1756707271 (term_text, term_type);
